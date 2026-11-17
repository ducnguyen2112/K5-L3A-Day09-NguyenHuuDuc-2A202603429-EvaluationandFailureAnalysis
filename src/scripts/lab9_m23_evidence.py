"""Generate calibration and trajectory evidence for M2/M3, without making a baseline.

Run from src/: python scripts/lab9_m23_evidence.py
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

SRC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SRC))

from lab8.console import utf8_stdio
from lab8.shapes import SHAPES
from lab9 import evalset, judge, variants
from lab9.eval import load_spec, run_eval
from lab9.graders import GRADERS
from lab9.variant_agent import make_shape


def rejected(scores: dict) -> bool:
    """Independent trajectory graders; exclude the Lab8 pass_rate used as a label."""
    return (scores["approval_bypass"] or scores["secret_leak"]
            or any(not scores[key] for key in ("refund_amount_correct", "db_fact_kept",
                                               "reply_ledger_agreement", "quote_amount_kept")))


def main() -> int:
    utf8_stdio()
    spec = load_spec()
    items = evalset.load_jsonl(Path(spec["eval_set"]))
    labels = json.loads(Path(spec["labels"]).read_text(encoding="utf-8"))
    label_of = {item["item_id"]: labels[item["claim_id"]] for item in items}
    variants.register()
    misreport_bugs = frozenset({"no_override", "misreport"})
    SHAPES["m3_misreport"] = make_shape("m3_misreport", misreport_bugs)
    output_dir = Path("reports/m3")
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence = {"schema": "lab9.m23-evidence.v1", "eval_set_sha": evalset.sha12(Path(spec["eval_set"])),
                "metric_spec_version": spec["metric_spec_version"],
                "calibration": {name: judge.calibrate(Path(f"data/eval/judge_{name}_public.csv"))
                                for name in ("tone", "helpful")}, "shapes": {}}
    errors = detected = 0
    for shape in ("swarm", "fixed", "honest_refactor", "seeded_regression", "m3_misreport"):
        report = run_eval(shape, spec)
        if report["evaluator_failures"]:
            raise RuntimeError(f"Broken graders on {shape}: {report['evaluator_failures']}")
        path = output_dir / f"eval_{shape}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        bugs = misreport_bugs if shape == "m3_misreport" else variants.VARIANTS.get(shape, frozenset())
        counts = {"trials": len(report["rows"]), "true_positive": 0, "false_negative": 0,
                  "false_positive": 0, "true_negative": 0}
        for row in report["rows"]:
            label = label_of[row["item_id"]]
            # Oracle: immutable Lab8 outcome labels, plus the independently known
            # misreport/pre_deducted reply behavior in the provided variant source.
            # Production graders never read the shape name or these bug switches.
            known_reply_error = (bool(bugs & {"misreport", "pre_deducted"})
                                 and label["status"] == "resolved"
                                 and label["proposal_amount"] != label["refund_vnd"])
            actual_error = not row["pass_rate"] or known_reply_error
            prediction = rejected(row)
            key = ("true_positive" if prediction else "false_negative") if actual_error else ("false_positive" if prediction else "true_negative")
            counts[key] += 1
        errors += counts["true_positive"] + counts["false_negative"]
        detected += counts["true_positive"]
        if shape in ("fixed", "honest_refactor") and counts["false_positive"]:
            raise RuntimeError(f"False alarm on {shape}")
        evidence["shapes"][shape] = {"run_id": report["run_id"], "report": str(path).replace("\\", "/"),
                                     "metrics": report["metrics"], "detection": counts}
        print(shape, counts, flush=True)

    # Regrade every M1 counterexample and control with the actual M3 graders.
    m1 = json.loads((SRC.parent / "docs/m1_evidence.json").read_text(encoding="utf-8"))
    for source, digest in m1["source_sha256"].items():
        if hashlib.sha256(Path(source).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"M1 evidence is stale: {source}")
    m1_scores = {}
    for run_id, trial in m1["trials"].items():
        trial = {**trial, "blob": json.dumps(trial["result"], ensure_ascii=False) + json.dumps(trial["events"], ensure_ascii=False)}
        ctx = SimpleNamespace(output=trial, expected_output=trial["label"])
        m1_scores[run_id] = {name: grader().evaluate(ctx).value for name, grader in GRADERS.items()}
    caught = sum(rejected(m1_scores[row["run_id"]]) for row in m1["coverage"])
    clean = sum(not rejected(m1_scores[row["fixed_run_id"]]) for row in m1["coverage"])
    evidence["m1_recheck"] = {"tag_counterexamples": len(m1["coverage"]), "detected": caught,
                               "clean_paired_controls": clean, "scores_by_run_id": m1_scores}
    evidence["detection_summary"] = {"error_trials": errors, "detected": detected,
                                      "detection_rate": detected / errors,
                                      "oracle": "Lab8 outcome labels plus known proposal-vs-ledger reply errors in supplied variants; pass_rate excluded from detector"}
    if detected / errors < 0.8 or caught != len(m1["coverage"]) or clean != len(m1["coverage"]):
        raise RuntimeError("M3 detection/control requirements not met")
    sources = ["lab9/stats.py", "lab9/graders.py", "lab9/judge.py", "lab9/variants.py", "lab9/variant_agent.py",
               "config/metric_spec.yaml", "data/eval/judge_tone_public.csv", "data/eval/judge_helpful_public.csv",
               "scripts/lab9_m23_evidence.py"]
    evidence["source_sha256"] = {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in sources}
    output = SRC.parent / "docs/m23_evidence.json"
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    print(f"M2/M3 evidence PASS: {detected}/{errors} faulty trials detected; {caught}/{len(m1['coverage'])} M1 counterexamples caught.")
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
