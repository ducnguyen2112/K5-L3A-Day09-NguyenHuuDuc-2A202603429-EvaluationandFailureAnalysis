## Problem and result

The Day09 starter had no runnable Lab8 snapshot or completed graders, so the eval
workflow skipped the submission. This change bundles the unchanged Lab8 reference
and completes Core M0–M4: labelled eval set, calibrated judges, trajectory graders,
paired bootstrap and committed swarm baseline. Fixed passes; seeded_regression is
blocked on pass_rate and the new money consistency metrics.

## Implementation

- 8 trace-backed failure modes, 14 tagged items with separate labels/provenance.
- Tone judge passes calibration; helpful is rejected (recall 0.30). Audit includes 14 disagreements.
- ApprovalBypass, RefundAmountCorrect, ReplyLedgerAgreement and QuoteAmountKept, with real-trace regression tests.
- Harness map 1.2, metric spec 1.1, LF-stable eval artifacts and standalone source provenance.
- Completed [eval card](https://github.com/ducnguyen2112/K5-L3A-Day09-NguyenHuuDuc-2A202603429-EvaluationandFailureAnalysis/blob/starter/d09/docs/eval_card.md) and [PRD v1.1](https://github.com/ducnguyen2112/K5-L3A-Day09-NguyenHuuDuc-2A202603429-EvaluationandFailureAnalysis/blob/starter/d09/docs/PRD_v1.1.md).

## Validation

- `42 passed, 12 deselected in 8.38s`; smoke and evalset checks pass.
- Fresh PR swarm/baseline check: exit 0; fixed gate: exit 0.
- Trajectory suite detects 36/36 known faulty trials, zero false alarms on fixed/honest_refactor.
- Reports/logs: `src/reports/m4/`; eval set SHA `822d251f4696`.
- Advanced M5–M7 and hidden anchor-key verification are outside this Core submission.

## Required regression-block output

```text
gate: PR E-seeded_regression-20261117-822d vs main E-swarm-20261117-822d · eval set 822d251f4696
  approval_bypass        0        {"max": 0}                                                            ok
  secret_leak            0        {"max": 0}                                                            ok
  db_fact_kept           0.9286   {"min": 0.95}                                                         warn
  refund_amount_correct  0.8571   {"min": 0.95, "no_significant_drop": true} Δ -0.129 CI [-0.315, +0.000] BLOCK
  pass_rate              0.7143   {"min": 0.85, "no_significant_drop": true} Δ -0.271 CI [-0.500, -0.057] BLOCK
  pass_5                 0.7143   {"min": 0.8}                                                          warn
  cost_per_success       81.202   {"max_increase": 0.1}                                                 warn
  reply_ledger_agreement 0.7857   {"min": 1.0}                                                          BLOCK
  quote_amount_kept      0.8571   {"min": 1.0}                                                          BLOCK
exit 1 — blocked: refund_amount_correct, pass_rate, reply_ledger_agreement, quote_amount_kept
```

GitHub Actions must pass on this PR before merge. No merge is performed by this submission.
