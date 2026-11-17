"""Run the complete M5-M7 checks and export reproducible evidence. Run from src/."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

SRC = Path(__file__).resolve().parents[1]
ROOT = SRC.parent
sys.path.insert(0, str(SRC))

from lab9 import ci_check, gate, stats, variants
from lab9.eval import load_spec, per_item, run_eval

OUT = Path("reports/m67")
SPEC = Path("config/metric_spec_v2.yaml")
ALT_SEEDS = [66, 77, 88, 99, 110]


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def save(path: Path, value) -> None:
    write(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def command(name: str, args: list[str], expected: int = 0) -> str:
    print(f"Checking {name}...", flush=True)
    result = subprocess.run([sys.executable, "-B", "-X", "utf8", *args],
                            capture_output=True, text=True, encoding="utf-8")
    output = result.stdout + result.stderr
    write(OUT / f"{name}.txt", output)
    if result.returncode != expected:
        raise RuntimeError(f"{name}: expected exit {expected}, got {result.returncode}\n{output}")
    return output


def section(path: Path, marker: str, content: str) -> None:
    before = path.read_text(encoding="utf-8").split(f"\n<!-- {marker} -->")[0].rstrip()
    write(path, before + f"\n\n<!-- {marker} -->\n" + content.rstrip() + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evaluate", action="store_true")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()
    spec = load_spec(SPEC)
    variants.register()
    if args.evaluate:
        command("m5", ["scripts/lab9_m5_evidence.py", "--evaluate"])
        reports = {name: read(Path(f"reports/m5/eval_{name}.json"))
                   for name in ("swarm", "fixed", "honest_refactor", "slice_regression")}
        for name in ("seeded_regression", "flaky_regression"):
            reports[name] = run_eval(name, spec)
            print(f"{name}: pass_rate={reports[name]['metrics']['pass_rate']}; "
                  f"pass_hat_5={reports[name]['metrics']['pass_hat_5']}", flush=True)
        reports["aa_alt"] = run_eval("swarm", spec, ALT_SEEDS)
        for name, report in reports.items():
            if report["evaluator_failures"]:
                raise RuntimeError(f"Broken evaluator on {name}: {report['evaluator_failures']}")
            save(OUT / f"eval_{name}.json", report)
    else:
        reports = {name: read(OUT / f"eval_{name}.json") for name in
                   ("swarm", "fixed", "honest_refactor", "slice_regression",
                    "seeded_regression", "flaky_regression", "aa_alt")}
    baseline = read(Path("reports/baseline_v2.json"))
    problems = ci_check.check(reports["swarm"], baseline, spec)
    if problems:
        raise RuntimeError("Baseline verification: " + "; ".join(problems))
    decisions = {}
    for name, report in reports.items():
        if name == "aa_alt":
            continue
        blocked, lines = gate.check(report, baseline, spec, spec)
        code = int(bool(blocked))
        save(OUT / f"gate_{name}.json", {"blocked": blocked, "lines": lines, "exit_code": code})
        write(OUT / f"gate_{name}.txt", "\n".join(lines) + f"\nexit {code}" +
              (f" — blocked: {', '.join(blocked)}\n" if blocked else " — merge\n"))
        decisions[name] = {"blocked": blocked, "exit_code": code}
        expected = name in ("seeded_regression", "slice_regression", "flaky_regression")
        if bool(blocked) != expected or "integrity" in blocked:
            raise RuntimeError(f"Wrong decision for honest report {name}: {blocked}")
    if "pass_hat_5" not in decisions["flaky_regression"]["blocked"]:
        raise RuntimeError("Flaky regression must fail reliability")
    if "slice:money_movement/pass_rate" not in decisions["slice_regression"]["blocked"]:
        raise RuntimeError("Slice regression must fail the money slice")

    # A/A is a measurement with intentionally different seeds, not a gate comparison.
    base_items = per_item(reports["swarm"], "pass_rate")
    alt_items = per_item(reports["aa_alt"], "pass_rate")
    keys = sorted(base_items)
    aa = {"base_seeds": spec["seeds"], "alternate_seeds": ALT_SEEDS,
          "metrics": {key: {"baseline": value, "alternate": reports["aa_alt"]["metrics"][key],
                            "delta": reports["aa_alt"]["metrics"][key] - value}
                      for key, value in reports["swarm"]["metrics"].items()},
          "pass_rate_paired_ci": stats.paired_bootstrap([alt_items[k] for k in keys], [base_items[k] for k in keys])}
    if any(abs(m["delta"]) > 1e-9 for m in aa["metrics"].values()):
        raise RuntimeError("MockLLM A/A drifted; revisit thresholds before accepting evidence")
    # Measure the added reliability signal without claiming it is exclusive.
    reliability_only = {**spec, "metrics": [m for m in spec["metrics"] if m["id"] in ("pass_rate", "pass_hat_5")], "slices": []}
    rate_only = {**reliability_only, "metrics": [m for m in spec["metrics"] if m["id"] == "pass_rate"]}
    rate_blocked, rate_lines = gate.check(reports["flaky_regression"], baseline, rate_only)
    reliable_blocked, reliable_lines = gate.check(reports["flaky_regression"], baseline, reliability_only)
    if "pass_hat_5" not in reliable_blocked:
        raise RuntimeError("Reliability ablation must catch flaky_regression")
    save(OUT / "aa.json", aa)
    save(OUT / "reliability_ablation.json", {"rate_only": rate_lines, "rate_only_blocked": rate_blocked,
                                           "with_reliability": reliable_lines, "with_reliability_blocked": reliable_blocked})

    mutation_log = command("mutation", ["-m", "lab9.mutation", "--spec", str(SPEC), "--baseline", "reports/baseline_v2.json"])
    if "mutation score 3/3" not in mutation_log or "false alarms 0" not in mutation_log:
        raise RuntimeError(mutation_log)
    command("aa", ["-m", "lab9.mutation", "--spec", str(SPEC), "--aa", ",".join(map(str, ALT_SEEDS))])
    command("traps", ["-m", "lab9.traps", "--pr", str(OUT / "eval_slice_regression.json"),
                      "--baseline", "reports/baseline_v2.json", "--spec", str(SPEC)])
    trap_results = {}
    for path in sorted(Path("reports/traps").glob("*.json")):
        args_gate = ["-m", "lab9.gate", "--pr", str(path), "--baseline", "reports/baseline_v2.json"]
        trap_spec = path.with_suffix(".spec.yaml")
        args_gate += ["--spec", str(trap_spec if trap_spec.is_file() else SPEC)]
        if trap_spec.is_file():
            args_gate += ["--base-spec", str(SPEC)]
        output = command(f"trap_{path.stem}", args_gate, expected=1)
        if "INTEGRITY" not in output or "exit 1 — blocked: integrity" not in output:
            raise RuntimeError("Trap must produce a deliberate integrity verdict, not an exception")
        trap_results[path.stem] = {"exit_code": 1, "reason": "INTEGRITY"}
    if len(trap_results) < 4:
        raise RuntimeError("Missing public traps")
    command("smoke", ["-m", "lab9.smoke"])
    command("evalset_v1", ["-m", "lab9.evalset", "--check"])
    command("evalset_v2", ["-m", "lab9.evalset", "--v2", "--check"])
    for shape, expected in (("fixed", 0), ("seeded_regression", 1)):
        command(f"core_{shape}", ["-m", "lab9.gate", "--pr", f"reports/eval_{shape}.json",
                                 "--baseline", "reports/baseline_v1.json"], expected=expected)
    tests = None
    if args.verify:
        output = command("tests", ["-m", "pytest", "-q", "-o", "addopts="])
        tests = output.strip().splitlines()[-1]
    elif (OUT / "evidence.json").is_file():
        tests = read(OUT / "evidence.json").get("tests")
    protected = subprocess.run(["git", "-c", f"safe.directory={ROOT.as_posix()}", "diff", "--exit-code", "HEAD", "--",
                                "src/lab8", "src/lab9/variants.py", "src/lab9/variant_agent.py", "src/lab9/traps.py",
                                "src/data/eval/adversarial_v2.json", "src/data/eval/labels_v1.json"],
                               cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if protected.returncode:
        raise RuntimeError("Protected reference files changed: " + protected.stdout + protected.stderr)
    sources = [Path("lab9/stats.py"), Path("lab9/gate.py"), Path("lab9/ci_check.py"), SPEC,
               Path("tests/test_lab9_m67.py"), Path("scripts/lab9_m67_evidence.py")]
    evidence = {"schema": "lab9.m67-evidence.v1", "eval_set_sha": baseline["manifest"]["eval_set_sha"],
                "metric_spec_version": spec["metric_spec_version"], "gate_decisions": decisions,
                "aa": aa, "mutation_score": "3/3", "false_alarms": 0, "traps": trap_results, "tests": tests,
                "reference_files_unchanged": True,
                "source_sha256": {p.as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}}
    save(OUT / "evidence.json", evidence)
    results = "\n".join(f"| {name} | {rep['metrics']['pass_rate']} | {rep['metrics']['pass_hat_5']} | {decisions[name]['exit_code']} |"
                        for name, rep in reports.items() if name != "aa_alt")
    floor = next(m["threshold"]["min"] for m in spec["metrics"] if m["id"] == "pass_hat_5")
    validation = f"""# M6/M7 — reliability, A/A and integrity

Eval set `{evidence['eval_set_sha']}`, spec `{spec['metric_spec_version']}`, 28 items × 5 seeds.
Baseline `{baseline['run_id']}` is generated by the harness and verified against a fresh swarm run.

## M6: estimators and threshold

`pass@k = 1 - C(n-c,k)/C(n,k)` estimates at least one success; `pass^k = C(c,k)/C(n,k)`
estimates all k successes, sampled without replacement. Both reject non-integer or invalid
counts (`n >= 1`, `0 <= c <= n`, `1 <= k <= n`). At n=k=5, pass^5 is the share of items
whose five trials all pass. Unit tests compare the estimators with exhaustive sampling.

A/A uses swarm with seeds {spec['seeds']} and {ALT_SEEDS}. Every reported metric has Δ=0;
pass_rate paired CI is {aa['pass_rate_paired_ci']}. Both runs have pass_hat_5={aa['metrics']['pass_hat_5']['baseline']}.
The blocking floor {floor:.2f} is below that observed band with 0.0929 headroom.
It is fixed from A/A, not lowered to make a variant pass. Other thresholds remain unchanged.
MockLLM determinism does not imply a zero noise band for a real LLM: real deployments need
repeated A/A runs, a representative item set and a floor below its lower noise bound.
Five seeds cannot establish stable detection of every rare (e.g. 1/3-seed) bug or independence.

| Shape | pass_rate | pass_hat_5 | Gate exit |
|---|---|---|---|
{results}

The flaky regression exceeds the pass_rate floor (0.9143 > 0.85), but its paired CI
also blocks it on this eval set. pass_hat_5 supplies another blocking signal (0.5714 < 0.80);
it is not claimed to be the only production signal. A separate generic test uses a subtle
regression with no override events and proves pass_hat_5 can block when the pass_rate
gate accepts. This diagnostic ablation leaves the production spec unchanged. The slice regression
also fails money_movement; the M3 quote grader supplies an additional production signal.
Logs: [A/A](../src/reports/m67/aa.txt), [scorecard](../src/reports/m67/mutation.txt),
[ablation](../src/reports/m67/reliability_ablation.json).

## M7: integrity and ratchet

The gate validates both reports: finite required metrics, empty evaluator_failures,
complete item × seed grid, no duplicate pairs, equal baseline/PR pairs, consistent slice tags,
and summaries recomputed from row evidence. It checks arbitrary metric/slice names.
With `--base-spec`, the same eval-set version cannot lose a metric/slice, loosen min/max/cost
thresholds, disable blocking or significant-drop checks, or replace a grader. Tighter rules
are allowed; a new eval-set version can establish a new baseline. CI reads the PR base spec.

Each public trap exits 1 with `INTEGRITY` (loosened_spec includes `RATCHET`):

```text
evaluator_errors_as_nan  exit 1 — blocked: integrity
dropped_failing_rows    exit 1 — blocked: integrity
cherry_picked_seeds     exit 1 — blocked: integrity
loosened_spec           exit 1 — blocked: integrity
```

The traps command itself exits 0 when all four traps are blocked. Additional tests cover
duplicate rows with unchanged counts, evaluator failures on green runs, slice relabeling
on one/all seeds, forged aggregate metrics, and malformed reports. No reference agent,
public variants/traps, adversarial pack, v1 labels or Lab8 file was changed.

Limits: report checks do not cryptographically attest execution. An attacker who fabricates
all consistent rows and summaries can still lie; trusted CI must rerun the harness. Hidden
grader vectors and instructor anchor keys are unavailable, so no hidden-test claim is made.

## Reproduce from src/

```powershell
python scripts/lab9_m67_evidence.py --evaluate --verify
```

Result: mutation score **3/3**, **0** false alarms, **4/4** public traps blocked.
Tests: `{tests}`. Evidence and source fingerprints: [evidence.json](../src/reports/m67/evidence.json).
Local checks do not establish that GitHub Actions has run or passed.
"""
    write(ROOT / "docs/m67_validation.md", validation)
    section(ROOT / "docs/eval_card.md", "M67 START", f"""## Completed M6/M7 — eval set v2

Spec {spec['metric_spec_version']} adds blocking pass_hat_5 ≥ {floor:.2f}.
A/A gives Δ=0 and pass_hat_5=0.8929 on both seed sets, leaving 0.0929 margin to the floor.
Mutation: 3/3 regressions blocked, fixed/honest_refactor accepted; four public traps blocked
with INTEGRITY. Tests: `{tests}`. Full results, sample-size limits and reproducible logs:
[M6/M7 validation](m67_validation.md). Real LLM noise requires repeated A/A; consistent forged
reports still require a trusted CI rerun. Remote CI status must be checked on the PR.
""")
    section(ROOT / "docs/PRD_v1.1.md", "M67 START", """## M6/M7 acceptance addendum

The offline v2 gate blocks reliability below pass_hat_5=0.80, violations in money/adversarial/
denial slices, and structurally untrustworthy reports. Same-version threshold changes require
ratchet verification against the base-branch spec. Public mutation score is 3/3 with zero
false alarms; four public traps are rejected. This does not authorize a live financial pilot.
See [M6/M7 validation](m67_validation.md) for A/A selection, limitations and rerun instructions.
""")
    pr_body = f"""## Problem and result

The Day09 starter lacked completed evaluators and a runnable Lab8 snapshot. This change
bundles the unchanged reference and completes M0–M7: tagged eval sets, judge calibration,
money consistency graders, paired/slice gates, reliability estimates and report integrity.
Fixed and honest_refactor pass; all three public regressions and four report-gaming traps
are blocked. Reference agents, variants, traps and fixture inputs remain unchanged.

## Validation

- `{tests}`; smoke and both eval sets pass.
- v1 swarm baseline is retained; fixed passes and seeded_regression is blocked.
- v2 A/A: all metric deltas zero; pass_hat_5=0.8929 on each seed set; blocking floor=0.80.
- Public mutation score 3/3, zero false alarms. All four public traps exit 1 with INTEGRITY.
- Repeat from src/: `python scripts/lab9_m67_evidence.py --evaluate --verify`.
- Evidence: `src/reports/m4/`, `m5/`, `m67/`; canonical baseline `src/reports/baseline_v2.json`.

## Required Core regression-block output

```text
{(OUT / 'core_seeded_regression.txt').read_text(encoding='utf-8').strip()}
```

## A/A output

```text
{(OUT / 'aa.txt').read_text(encoding='utf-8').strip()}
```

## Mutation scorecard

```text
{mutation_log.strip()}
```

## Trap gate verdicts

```text
evaluator_errors_as_nan: exit 1 — blocked: integrity
dropped_failing_rows:   exit 1 — blocked: integrity
cherry_picked_seeds:    exit 1 — blocked: integrity
loosened_spec:          exit 1 — blocked: integrity (RATCHET)
```

Read `docs/eval_card.md` and `docs/m67_validation.md` for noise, sample-size and integrity
limits. Hidden instructor tests were unavailable. Local verification does not establish
remote CI status; GitHub Actions checks must pass before merge.
"""
    write(ROOT / "docs/PR_BODY.md", pr_body)
    print(f"M0-M7 PASS: mutation 3/3; false alarms 0; traps {len(trap_results)}/4; {tests}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
