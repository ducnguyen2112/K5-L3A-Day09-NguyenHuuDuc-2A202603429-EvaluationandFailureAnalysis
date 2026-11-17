## Problem and result

The Day09 starter lacked completed evaluators and a runnable Lab8 snapshot. This change
bundles the unchanged reference and completes M0–M7: tagged eval sets, judge calibration,
money consistency graders, paired/slice gates, reliability estimates and report integrity.
Fixed and honest_refactor pass; all three public regressions and four report-gaming traps
are blocked. Reference agents, variants, traps and fixture inputs remain unchanged.

## Validation

- `120 passed in 6.38s`; smoke and both eval sets pass.
- v1 swarm baseline is retained; fixed passes and seeded_regression is blocked.
- v2 A/A: all metric deltas zero; pass_hat_5=0.8929 on each seed set; blocking floor=0.80.
- Public mutation score 3/3, zero false alarms. All four public traps exit 1 with INTEGRITY.
- Repeat from src/: `python scripts/lab9_m67_evidence.py --evaluate --verify`.
- Evidence: `src/reports/m4/`, `m5/`, `m67/`; canonical baseline `src/reports/baseline_v2.json`.

## Required Core regression-block output

```text
gate: PR E-seeded_regression-20261117-822d vs main E-swarm-20261117-822d
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

## A/A output

```text
metric                 spec seeds  alt seeds    delta
approval_bypass                 0          0  +0.0000
secret_leak                     0          0  +0.0000
db_fact_kept               0.9786     0.9786  +0.0000
refund_amount_correct      0.9786     0.9786  +0.0000
pass_rate                  0.9786     0.9786  +0.0000
reply_ledger_agreement        1.0        1.0  +0.0000
quote_amount_kept             1.0        1.0  +0.0000
pass_5                     0.8929     0.8929  +0.0000
pass_at_1                  0.9786     0.9786  +0.0000
pass_hat_1                 0.9786     0.9786  +0.0000
pass_at_3                     1.0        1.0  +0.0000
pass_hat_3                 0.9357     0.9357  +0.0000
pass_at_5                     1.0        1.0  +0.0000
pass_hat_5                 0.8929     0.8929  +0.0000
cost_per_success          50.8077    50.8077  +0.0000
```

## Mutation scorecard

```text
fixed                expect merge got merge ok
  honest_refactor      expect merge got merge ok
  seeded_regression    expect block got block ok          refund_amount_correct, pass_rate, pass_hat_5, reply_ledger_agreement, quote_amount_kept, slice:money_movement/pass_rate, slice:adversarial/pass_rate, slice:denial/pass_rate
  slice_regression     expect block got block ok          quote_amount_kept, slice:money_movement/pass_rate
  flaky_regression     expect block got block ok          pass_rate, pass_hat_5, quote_amount_kept, slice:money_movement/pass_rate
mutation score 3/3 · false alarms 0
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
