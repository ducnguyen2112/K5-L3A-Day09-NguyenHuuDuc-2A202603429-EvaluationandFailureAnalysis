"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from numbers import Real
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems = []
    if not isinstance(pr, dict) or not isinstance(base, dict):
        return ["reports must be objects"]
    metrics = spec.get("metrics", [])
    raw_ids = {m["id"] for m in metrics if m["id"] in GRADERS or m.get("grader") == "code"}
    # Accept additional graders without coupling the check to public metric names.
    raw_ids.update(m["id"] for m in metrics if any(
        m["id"] in row for report in (pr, base)
        for row in (report.get("rows") if isinstance(report.get("rows"), list) else []) if isinstance(row, dict)))
    pairs, tags = {}, {}
    for label, report in (("PR", pr), ("baseline", base)):
        manifest, rows, values = report.get("manifest", {}), report.get("rows"), report.get("metrics")
        if not isinstance(manifest, dict) or not isinstance(rows, list) or not rows or not isinstance(values, dict):
            problems.append(f"{label}: missing manifest, rows or metrics")
            continue
        seeds, count = manifest.get("seeds"), manifest.get("items")
        if not isinstance(manifest.get("eval_set_sha"), str) or not manifest["eval_set_sha"]:
            problems.append(f"{label}: missing eval_set_sha")
        if (not isinstance(seeds, list) or not seeds
                or any(type(seed) is not int for seed in seeds) or len(set(seeds)) != len(seeds)
                or type(count) is not int or count < 1):
            problems.append(f"{label}: invalid manifest items/seeds")
            continue
        if len(rows) != count * len(seeds):
            problems.append(f"{label}: row count differs from manifest items x seeds")
        failures = report.get("evaluator_failures")
        if not isinstance(failures, list) or failures:
            problems.append(f"{label}: evaluator_failures must be an empty list")
        for mid, value in values.items():
            if value is not None and not _finite(value):
                problems.append(f"{label}: metric {mid} is non-numeric or non-finite")
        for metric in metrics:
            if not _finite(values.get(metric["id"])):
                problems.append(f"{label}: missing/non-finite metric {metric['id']}")
        seen, item_tags, valid_rows = set(), {}, True
        for index, row in enumerate(rows):
            if (not isinstance(row, dict) or not isinstance(row.get("item_id"), str)
                    or not row["item_id"] or type(row.get("seed")) is not int):
                problems.append(f"{label}: malformed row {index}")
                valid_rows = False
                continue
            pair = (row["item_id"], row["seed"])
            if pair in seen:
                problems.append(f"{label}: duplicate (item, seed) {pair}")
            seen.add(pair)
            row_tags = row.get("slices", [])
            if not isinstance(row_tags, list) or any(not isinstance(tag, str) for tag in row_tags):
                problems.append(f"{label}: malformed slice tags at {pair}")
                valid_rows = False
            else:
                normalized = frozenset(row_tags)
                if row["item_id"] in item_tags and item_tags[row["item_id"]] != normalized:
                    problems.append(f"{label}: inconsistent slice tags across seeds for {row['item_id']}")
                item_tags[row["item_id"]] = normalized
            for mid in raw_ids:
                if not _finite(row.get(mid)) or (mid in GRADERS and row[mid] not in (0, 1)):
                    problems.append(f"{label}: missing/non-finite/non-binary row metric {mid} at {pair}")
                    valid_rows = False
            if "cost" in row and (not _finite(row["cost"]) or row["cost"] < 0):
                problems.append(f"{label}: invalid cost at {pair}")
                valid_rows = False
        items = {item for item, _ in seen}
        if len(items) != count or seen != {(item, seed) for item in items for seed in seeds}:
            problems.append(f"{label}: incomplete item x seed grid")
        pairs[label], tags[label] = seen, item_tags
        # Recompute report summaries, so editing only the headline cannot hide bad rows.
        if valid_rows:
            for metric in metrics:
                mid = metric["id"]
                if mid in raw_ids and _finite(values.get(mid)):
                    total = sum(row[mid] for row in rows)
                    expected = total if metric.get("kind") == "safety" else round(total / len(rows), 4)
                    if not math.isclose(values[mid], expected, rel_tol=0, abs_tol=5e-5):
                        problems.append(f"{label}: aggregate {mid} disagrees with rows")
            if "pass_rate" in raw_ids:
                per_claim = {}
                for row in rows:
                    per_claim.setdefault(row["item_id"], []).append(bool(row["pass_rate"]))
                expected_k = {"pass_5": sum(all(v) for v in per_claim.values()) / len(per_claim)}
                for k in spec.get("pass_k", []):
                    if all(len(v) >= k for v in per_claim.values()):
                        for prefix, fn in (("pass_at", stats.pass_at_k), ("pass_hat", stats.pass_hat_k)):
                            expected_k[f"{prefix}_{k}"] = sum(fn(len(v), sum(v), k) for v in per_claim.values()) / len(per_claim)
                for mid, expected in expected_k.items():
                    if mid in values and (not _finite(values[mid]) or not math.isclose(values[mid], round(expected, 4), rel_tol=0, abs_tol=5e-5)):
                        problems.append(f"{label}: aggregate {mid} disagrees with rows")
                if all("cost" in row for row in rows) and "cost_per_success" in values:
                    passes = sum(row["pass_rate"] for row in rows)
                    if passes and _finite(values["cost_per_success"]):
                        expected = round(sum(row["cost"] for row in rows) / passes, 4)
                        if not math.isclose(values["cost_per_success"], expected, rel_tol=0, abs_tol=5e-5):
                            problems.append(f"{label}: aggregate cost_per_success disagrees with rows")
    if pairs.get("PR") != pairs.get("baseline"):
        problems.append("PR (item, seed) set differs from baseline")
    if tags.get("PR") != tags.get("baseline"):
        problems.append("PR slice tags differ from baseline")
    if base_spec is not None and spec.get("eval_set_version") == base_spec.get("eval_set_version"):
        problems += _ratchet(spec, base_spec)
    return list(dict.fromkeys(problems))


def _finite(value) -> bool:
    return isinstance(value, Real) and math.isfinite(value)


def _ratchet(spec: dict, base_spec: dict) -> list[str]:
    problems = []
    for section in ("metrics", "slices"):
        def key(rule):
            return rule["id"] if section == "metrics" else (rule["name"], rule["metric"])
        current = {key(rule): rule for rule in spec.get(section, [])}
        if len(current) != len(spec.get(section, [])):
            problems.append(f"RATCHET duplicate {section} rules")
        for old in base_spec.get(section, []):
            identity = key(old)
            if identity not in current:
                problems.append(f"RATCHET removed {section} {identity}")
                continue
            new = current[identity]
            if old.get("blocking") and not new.get("blocking"):
                problems.append(f"RATCHET disabled blocking {identity}")
            before = old.get("threshold", {}) if section == "metrics" else old
            after = new.get("threshold", {}) if section == "metrics" else new
            for name in ("min", "max", "max_increase"):
                if name in before and (not _finite(after.get(name)) or
                        (after[name] < before[name] if name == "min" else after[name] > before[name])):
                    problems.append(f"RATCHET loosened {identity}/{name}")
            if before.get("no_significant_drop") and not after.get("no_significant_drop"):
                problems.append(f"RATCHET removed no_significant_drop {identity}")
            for name in ("kind", "grader", "level"):
                if name in old and old[name] != new.get(name):
                    problems.append(f"RATCHET changed {identity}/{name}")
    for name in ("eval_set", "labels", "adversarial_pack", "seeds"):
        if name in base_spec and base_spec[name] != spec.get(name):
            problems.append(f"RATCHET changed {name} without a new eval-set version")
    if not set(base_spec.get("pass_k", [])) <= set(spec.get("pass_k", [])):
        problems.append("RATCHET removed pass_k estimates")
    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bootstrap = spec.get("bootstrap", {})
    for rule in spec.get("slices", []):
        name, metric = rule["name"], rule["metric"]
        identifier = f"slice:{name}/{metric}"
        problems = []
        subsets = {}
        for label, report in (("PR", pr), ("baseline", base)):
            rows = [row for row in report["rows"] if name in (row.get("slices") or [])]
            if not rows:
                problems.append(f"{label}: empty slice")
            elif any(not isinstance(row.get(metric), Real) or not math.isfinite(row[metric]) for row in rows):
                # Do not silently drop None/NaN from a slice average.
                problems.append(f"{label}: missing/non-finite {metric}")
            else:
                subsets[label] = per_item(report, metric, slice_name=name)
        value, note = None, ""
        if not problems:
            first, second = subsets["PR"], subsets["baseline"]
            if set(first) != set(second):
                problems.append("slice item sets differ from baseline")
            else:
                value = sum(first.values()) / len(first)
                if "min" in rule and value < rule["min"]:
                    problems.append(f"below min={rule['min']}")
                if rule.get("no_significant_drop"):
                    keys = sorted(second)
                    delta, low, high = stats.paired_bootstrap(
                        [first[key] for key in keys], [second[key] for key in keys],
                        n_resamples=bootstrap.get("n_resamples", 1000), rng=bootstrap.get("rng", 2027),
                        confidence=bootstrap.get("confidence", 0.95))
                    note = f"items={len(keys)} Δ {delta:+.3f} CI [{low:+.3f}, {high:+.3f}]"
                    if high < 0:
                        problems.append("significant drop")
        if problems and rule.get("blocking"):
            blocked.append(identifier)
        verdict = ("BLOCK" if rule.get("blocking") else "warn") if problems else "ok"
        shown = "MISSING" if value is None else f"{value:.6f}"
        lines.append(f"  {identifier:<40} {shown:<9} {note} {verdict} {'; '.join(problems)}".rstrip())
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    if pr["manifest"].get("eval_set_sha") != base["manifest"].get("eval_set_sha"):
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027),
                                               confidence=bs.get("confidence", 0.95))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    try:
        pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
        base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"  INTEGRITY unreadable report: {exc}")
        print("exit 1 — blocked: integrity")
        return 1
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    pr_id = pr.get("run_id", "unknown") if isinstance(pr, dict) else "invalid"
    base_id = base.get("run_id", "unknown") if isinstance(base, dict) else "invalid"
    print(f"gate: PR {pr_id} vs main {base_id}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
