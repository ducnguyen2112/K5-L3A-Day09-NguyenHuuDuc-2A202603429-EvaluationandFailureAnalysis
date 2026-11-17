"""Reliability estimators and generic report-integrity/ratchet regressions."""
import copy
import itertools
import math

import pytest

from lab9 import ci_check, gate, stats
from lab9.eval import aggregate

pytestmark = pytest.mark.student


@pytest.mark.parametrize("args", [(0, 0, 1), (-1, 0, 1), (5, -1, 1), (5, 6, 1),
                                    (5, 1, 0), (5, 1, -1), (5, 1, 6),
                                    (5.0, 1, 1), (5, True, 1), (5, 1, False),
                                    (5, 1, 1.5), (True, 1, 1), (5, "1", 1)])
def test_reliability_rejects_invalid_counts_for_both_estimators(args):
    for estimator in (stats.pass_at_k, stats.pass_hat_k):
        with pytest.raises(ValueError):
            estimator(*args)


def test_reliability_matches_exhaustive_sampling_without_replacement():
    for n in range(1, 8):
        for c in range(n + 1):
            population = [True] * c + [False] * (n - c)
            for k in range(1, n + 1):
                draws = list(itertools.combinations(population, k))
                at, hat = stats.pass_at_k(n, c, k), stats.pass_hat_k(n, c, k)
                assert at == pytest.approx(sum(any(draw) for draw in draws) / len(draws))
                assert hat == pytest.approx(sum(all(draw) for draw in draws) / len(draws))
                assert hat <= c / n + 1e-12
                assert c / n <= at + 1e-12
    assert math.isfinite(stats.pass_at_k(10000, 5000, 5000))
    assert math.isfinite(stats.pass_hat_k(10000, 5000, 5000))


SPEC = {"eval_set_version": "v2", "pass_k": [1, 3, 5], "metrics": [
    {"id": "pass_rate", "kind": "capability", "blocking": True,
     "threshold": {"min": 0.85, "no_significant_drop": True}},
    {"id": "pass_hat_5", "kind": "capability", "blocking": True, "threshold": {"min": 0.8}},
    {"id": "secret_leak", "kind": "safety", "blocking": True, "threshold": {"max": 0}},
    {"id": "cost_per_success", "kind": "system", "threshold": {"max_increase": 0.1}}],
    "slices": [{"name": "private_cohort", "metric": "pass_rate", "min": 0.9,
                "blocking": True, "no_significant_drop": True}]}


def report():
    rows = [{"item_id": name, "seed": seed, "slices": ["private_cohort"],
             "pass_rate": True, "secret_leak": False, "cost": 1}
            for name in ("X", "Y") for seed in range(1, 6)]
    return {"run_id": "test", "shape": "swarm", "manifest": {"items": 2, "seeds": list(range(1, 6)),
            "eval_set_sha": "fixture"}, "rows": rows,
            "metrics": aggregate(rows, ["pass_rate", "secret_leak"], [1, 3, 5]), "evaluator_failures": []}


def test_honest_reordering_does_not_change_integrity_or_gate():
    base, pr = report(), report()
    pr["rows"].reverse()
    pr["manifest"]["seeds"].reverse()
    assert gate.integrity_check(pr, base, SPEC, SPEC) == []
    assert gate.check(pr, base, SPEC, SPEC)[0] == []


@pytest.mark.parametrize("attack", ["duplicate", "cherry_pick", "drop", "green_grader_error", "missing_raw",
                                   "null_raw", "nan_raw", "inf_summary", "fake_summary", "fake_reliability",
                                   "relabel_one_seed", "relabel_all_seeds", "duplicate_seeds", "wrong_item_count",
                                   "malformed_row", "missing_manifest", "null_rows", "missing_summary",
                                   "negative_safety", "non_binary_pass"])
def test_integrity_blocks_tampering_even_on_otherwise_green_report(attack):
    base, pr = report(), report()
    if attack == "duplicate":
        pr["rows"][-1] = copy.deepcopy(pr["rows"][0])
    elif attack == "cherry_pick":
        pr["manifest"]["seeds"] = [1, 2, 3, 4]
        pr["rows"] = [row for row in pr["rows"] if row["seed"] != 5]
    elif attack == "drop":
        pr["rows"].pop()
    elif attack == "green_grader_error":
        pr["evaluator_failures"] = ["grader crashed on a green run"]
    elif attack == "missing_raw":
        for row in pr["rows"]:
            del row["secret_leak"]
    elif attack in ("null_raw", "nan_raw"):
        pr["rows"][0]["pass_rate"] = None if attack == "null_raw" else float("nan")
    elif attack == "inf_summary":
        pr["metrics"]["extra"] = float("inf")
    elif attack == "fake_summary":
        pr["rows"][0]["secret_leak"] = True
    elif attack == "fake_reliability":
        pr["metrics"]["pass_hat_5"] = 0.9
    elif attack.startswith("relabel"):
        for row in pr["rows"][:1 if attack == "relabel_one_seed" else 5]:
            row["slices"] = []
    elif attack == "duplicate_seeds":
        pr["manifest"]["seeds"] = [1, 2, 3, 4, 4]
    elif attack == "wrong_item_count":
        pr["manifest"]["items"] = 3
    elif attack == "malformed_row":
        pr["rows"][0] = None
    elif attack == "missing_manifest":
        pr["manifest"] = None
    elif attack == "null_rows":
        pr["rows"] = None
    elif attack == "missing_summary":
        del pr["metrics"]["pass_hat_5"]
    elif attack == "negative_safety":
        pr["rows"][0]["secret_leak"] = -1
    elif attack == "non_binary_pass":
        pr["rows"][0]["pass_rate"] = 1.2
    blocked, lines = gate.check(pr, base, SPEC)
    assert blocked == ["integrity"]
    assert all("INTEGRITY" in line for line in lines)


@pytest.mark.parametrize("attack", ["min", "max", "increase", "remove_threshold", "drop_blocking",
                                   "drop_metric", "drop_slice", "slice_min", "slice_blocking",
                                   "drop_ci", "slice_drop_ci", "change_grader", "drop_k"])
def test_ratchet_blocks_each_way_of_weakening_same_version(attack):
    loose = copy.deepcopy(SPEC)
    if attack == "min":
        loose["metrics"][0]["threshold"]["min"] = 0.8
    elif attack == "max":
        loose["metrics"][2]["threshold"]["max"] = 1
    elif attack == "increase":
        loose["metrics"][3]["threshold"]["max_increase"] = 0.2
    elif attack == "remove_threshold":
        loose["metrics"][0]["threshold"] = {}
    elif attack == "drop_blocking":
        loose["metrics"][0]["blocking"] = False
    elif attack == "drop_metric":
        loose["metrics"].pop(0)
    elif attack == "drop_slice":
        loose["slices"] = []
    elif attack == "slice_min":
        loose["slices"][0]["min"] = 0.8
    elif attack == "slice_blocking":
        loose["slices"][0]["blocking"] = False
    elif attack == "drop_ci":
        del loose["metrics"][0]["threshold"]["no_significant_drop"]
    elif attack == "slice_drop_ci":
        del loose["slices"][0]["no_significant_drop"]
    elif attack == "change_grader":
        original = copy.deepcopy(SPEC)
        original["metrics"][0]["grader"] = "real_grader"
        loose["metrics"][0]["grader"] = "always_pass"
        assert any("RATCHET" in p for p in gate.integrity_check(report(), report(), loose, original))
        return
    elif attack == "drop_k":
        loose["pass_k"] = [1]
    assert any("RATCHET" in p for p in gate.integrity_check(report(), report(), loose, SPEC))


def test_tightening_allowed_and_new_dataset_version_resets_ratchet():
    tight = copy.deepcopy(SPEC)
    tight["metrics"][0]["threshold"]["min"] = 0.99
    assert gate.integrity_check(report(), report(), tight, SPEC) == []
    reset = copy.deepcopy(SPEC)
    reset.update(eval_set_version="v3", slices=[])
    reset["metrics"][0]["threshold"]["min"] = 0.1
    assert gate.integrity_check(report(), report(), reset, SPEC) == []


def test_reliability_blocks_a_subtle_regression_without_override_events():
    base, pr = report(), report()
    # One failure per item: high pass@5, but zero probability of five successes.
    for row in pr["rows"]:
        row["pass_rate"] = row["seed"] != 5
    pr["metrics"] = aggregate(pr["rows"], ["pass_rate", "secret_leak"], [1, 3, 5])
    spec = copy.deepcopy(SPEC)
    spec["metrics"][0]["threshold"] = {"min": 0.7}
    spec["slices"] = []
    assert pr["metrics"]["pass_at_5"] == 1
    assert gate.check(pr, base, spec)[0] == ["pass_hat_5"]


def test_ci_sanity_recognizes_derived_metrics_but_still_requires_own_grader():
    base = report()
    spec = copy.deepcopy(SPEC)
    spec["metrics"].append({"id": "reply_ledger_agreement", "kind": "capability", "blocking": True})
    assert ci_check.check(base, base, spec) == []
    assert any("no blocking capability" in p for p in ci_check.check(base, base, SPEC))
