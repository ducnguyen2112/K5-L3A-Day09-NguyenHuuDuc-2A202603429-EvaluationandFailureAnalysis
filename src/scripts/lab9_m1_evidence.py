"""Export M1 trace evidence, using existing bug switches without editing Lab 8.

Run from src/: python scripts/lab9_m1_evidence.py
The output is supporting evidence, not an M4 evaluation report or baseline.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

SRC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SRC))

from lab8.console import utf8_stdio
from lab8.shapes import SHAPES
from lab9 import evalset
from lab9.trace_case import investigate
from lab9.variant_agent import make_shape

# Earliest observable wrong event, indexed from 1 in the unmodified trace.
CASES = (
    ("FM-01", "leaky_trace", "C-001", 11, "debug_claim_row"),
    ("FM-02", "ignore_denied", "C-007", 11, "reply"),
    ("FM-03", None, "C-002", 55, "model_override"),
    ("FM-04", "sum_parts", "C-014", 11, "proposal"),
    ("FM-05", "pre_deducted", "C-014", 11, "proposal"),
    ("FM-06", "stale_clause", "C-006", 11, "quote"),
    ("FM-07", "sibling_refund", "C-010", 11, "batch_refund"),
    ("FM-08", "misreport", "C-008", 11, "reply"),
)


def detects(fm: str, trial: dict, label: dict) -> bool:
    """Evidence assertions only; production graders are a separate M3 task."""
    events, result, snapshot = trial["events"], trial["result"], trial["snapshot"]
    if fm == "FM-01":
        blob = json.dumps(events, ensure_ascii=False)
        return any(token in blob for token in label["forbid_substrings"] if token)
    if fm == "FM-02":
        return snapshot["policy_denied"] and result["status"] == "resolved"
    if fm == "FM-03":
        return any(event["kind"] == "model_override" for event in events)
    if fm == "FM-04":
        return result["proposal_amount"] != label["proposal_amount"]
    if fm == "FM-05":
        return any(event["kind"] == "proposal" for event in events) and snapshot["refund_vnd"] != label["refund_vnd"]
    if fm == "FM-06":
        return any("SHIP-LATE-OLD" in event["payload"].get("clause_ids", [])
                   for event in events if event["kind"] == "quote")
    if fm == "FM-07":
        return trial["unexpected_rows"] > 0
    if fm == "FM-08":
        amount = f"{snapshot['refund_vnd']:,}".replace(",", ".") + "đ"
        replies = [event["payload"]["text"] for event in events if event["kind"] == "reply"]
        return result["status"] == "resolved" and len(replies) == 1 and amount not in replies[0]
    raise ValueError(f"Unknown failure mode: {fm}")


def main() -> int:
    utf8_stdio()
    trials: dict[str, dict] = {}

    def capture(bug: str | None, claim: str, seed: int) -> dict:
        shape = "swarm" if bug is None else ("fixed" if bug == "fixed" else f"m1_{bug}")
        run_id = f"R-{shape}-{claim}-s{seed}"
        if run_id not in trials:
            if bug not in (None, "fixed"):
                SHAPES[shape] = make_shape(shape, {"no_override", bug})
            case = investigate(shape, claim, seed)
            trial = case["trial"]
            if not trial["events"] or trial["result"]["run_id"] != run_id:
                raise RuntimeError(f"Invalid trace: {run_id}")
            trials[run_id] = {"claim_id": claim, "seed": seed, "shape": shape,
                              "bug_switches": [] if bug is None else ["no_override", *([] if bug == "fixed" else [bug])],
                              "label": case["label"],
                              "result": trial["result"], "snapshot": trial["snapshot"],
                              "unexpected_rows": trial["unexpected_rows"], "events": trial["events"],
                              "lab8_pass": trial["lab8_pass"], "lab8_reason": trial["lab8_reason"]}
        return trials[run_id]

    anchors = []
    for fm, bug, claim, seed, kind in CASES:
        bad = capture(bug, claim, seed)
        good = capture("fixed", claim, seed)
        if not detects(fm, bad, bad["label"]) or detects(fm, good, good["label"]) or not good["lab8_pass"]:
            raise RuntimeError(f"Evidence/control check failed: {fm}")
        index, event = next((i, event) for i, event in enumerate(bad["events"], 1) if event["kind"] == kind)
        anchors.append({"failure_mode": fm, "run_id": bad["result"]["run_id"],
                        "first_wrong_event": {"index": index, **event},
                        "fixed_run_id": good["result"]["run_id"]})

    # Each item tag gets its own counterexample and passing fixed control.
    coverage = []
    for claim, modes in evalset.FAILURE_MODES_BY_CLAIM.items():
        for fm in modes:
            bug = {"FM-01": "leaky_trace", "FM-02": "ignore_denied", "FM-03": None,
                   "FM-04": "sum_parts" if claim == "C-014" else "round_down",
                   "FM-05": "pre_deducted", "FM-06": "stale_clause",
                   "FM-07": "sibling_refund", "FM-08": "misreport"}[fm]
            seed = 55 if fm == "FM-03" else 11
            bad, good = capture(bug, claim, seed), capture("fixed", claim, seed)
            # On C-013, pre-deduction removes the proposal and host denial audit;
            # the expected ledger remains zero, so compare proposal and audit too.
            exposed = detects(fm, bad, bad["label"])
            if fm == "FM-05" and claim == "C-013":
                exposed = bad["result"]["proposal_amount"] != bad["label"]["proposal_amount"] and not bad["snapshot"]["policy_denied"]
            if not exposed or detects(fm, good, good["label"]) or not good["lab8_pass"]:
                raise RuntimeError(f"Unsubstantiated item tag: {claim} {fm}")
            coverage.append({"claim_id": claim, "failure_mode": fm,
                             "run_id": bad["result"]["run_id"], "fixed_run_id": good["result"]["run_id"]})

    # Keep source fingerprints so evidence can be tied back to the supplied code/data.
    sources = [Path("lab8/shapes/swarm_reference.py"), Path("lab8/durability.py"),
               Path("lab9/variant_agent.py"), Path("lab9/evalset.py"), Path("scripts/lab9_m1_evidence.py"),
               Path("data/public_world_state.json"), Path("data/public_claims.jsonl")]
    artifact = {"schema": "lab9.m1-evidence.v1", "source": "public MockLLM traces",
                "note": "m1_* shapes use existing bug switches in memory; no official variant is modified.",
                "source_sha256": {str(p).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
                "coding_sheet": anchors, "coverage": coverage, "trials": trials}
    output = SRC.parent / "docs" / "m1_evidence.json"
    output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"M1 evidence PASS: {len(anchors)} failure modes, {len(trials)} trials; every item tag has a checked control.")
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
