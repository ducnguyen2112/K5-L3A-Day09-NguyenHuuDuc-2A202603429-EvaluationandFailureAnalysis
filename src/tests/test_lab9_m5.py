"""M5 slice comparisons: independent cohorts, item weighting and paired uncertainty."""
import copy

import pytest

pytestmark = pytest.mark.student


def reports(values, baseline=None, tags=None):
    tags = tags or {key: ["money_movement"] for key in values}
    def report(data):
        return {"rows": [{"item_id": item, "seed": seed, "slices": tags[item], "pass_rate": value}
                         for item, seeds in data.items() for seed, value in enumerate(seeds, 1)]}
    return report(values), report(baseline or {key: [True] * len(seeds) for key, seeds in values.items()})


def spec(**overrides):
    rule = {"name": "money_movement", "metric": "pass_rate", "min": 0.9, "blocking": True}
    rule.update(overrides)
    return {"slices": [rule], "bootstrap": {"rng": 2027, "n_resamples": 1000, "confidence": 0.95}}


@pytest.fixture(scope="module")
def gate():
    from lab9 import gate
    return gate


def test_small_important_slice_cannot_hide_behind_overall_average(gate):
    values = {f"E-{i}": [True] * 5 for i in range(20)}
    values["E-0"] = [False, True, False, True, False]
    tags = {key: ["money_movement"] if key in ("E-0", "E-1") else [] for key in values}
    pr, base = reports(values, tags=tags)
    assert sum(row["pass_rate"] for row in pr["rows"]) / len(pr["rows"]) == 0.97
    blocked, _ = gate.slice_check(pr, base, spec())
    assert blocked == ["slice:money_movement/pass_rate"]


def test_slice_weights_each_item_equally_instead_of_each_trial(gate):
    pr, base = reports({"A": [False], "B": [True] * 9})
    blocked, lines = gate.slice_check(pr, base, spec(min=0.75))
    assert blocked == ["slice:money_movement/pass_rate"]
    assert "0.500000" in lines[0]


def test_paired_slice_drop_can_block_even_above_floor(gate):
    pr, base = reports({"A": [True] * 4 + [False], "B": [True] * 4 + [False]})
    blocked, lines = gate.slice_check(pr, base, spec(min=0.7, no_significant_drop=True))
    assert blocked == ["slice:money_movement/pass_rate"]
    assert "significant drop" in lines[0]


def test_ci_touching_zero_does_not_block_when_floor_is_met(gate):
    pr, base = reports({"A": [True, False], "B": [True, True]})
    blocked, _ = gate.slice_check(pr, base, spec(min=0.7, no_significant_drop=True))
    assert blocked == []


def test_row_order_and_unrelated_tags_do_not_change_pairing(gate):
    pr, base = reports({"A": [True], "B": [True]})
    pr["rows"].reverse()
    pr["rows"][0]["slices"].append("another_slice")
    assert gate.slice_check(pr, base, spec(no_significant_drop=True))[0] == []


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), "1"])
def test_missing_or_invalid_values_do_not_disappear_from_slice_mean(gate, value):
    pr, base = reports({"A": [True, value]})
    blocked, lines = gate.slice_check(pr, base, spec())
    assert blocked == ["slice:money_movement/pass_rate"]
    assert "MISSING" in lines[0]


def test_missing_baseline_metric_refuses_comparison(gate):
    pr, base = reports({"A": [True]})
    del base["rows"][0]["pass_rate"]
    assert gate.slice_check(pr, base, spec())[0] == ["slice:money_movement/pass_rate"]


def test_empty_or_relabelled_slice_refuses_comparison(gate):
    pr, base = reports({"A": [True], "B": [True]})
    pr["rows"][0]["slices"] = []
    assert gate.slice_check(pr, base, spec())[0] == ["slice:money_movement/pass_rate"]
    pr["rows"][1]["slices"] = []
    assert gate.slice_check(pr, base, spec())[0] == ["slice:money_movement/pass_rate"]


def test_nonblocking_slice_warns_and_custom_slices_are_supported(gate):
    pr, base = reports({"A": [False]})
    assert gate.slice_check(pr, base, spec(blocking=False))[0] == []
    for report in (pr, base):
        report["rows"][0]["slices"] = ["new_hidden_cohort"]
    assert gate.slice_check(pr, base, spec(name="new_hidden_cohort"))[0] == ["slice:new_hidden_cohort/pass_rate"]


def test_slice_baseline_compared_with_itself_always_passes(gate):
    pr, _ = reports({"A": [True, False], "B": [True]})
    assert gate.slice_check(pr, copy.deepcopy(pr), spec(min=0.7, no_significant_drop=True))[0] == []


def test_v2_preserves_v1_labels_and_covers_every_attacked_failure_mode():
    import json
    from collections import Counter
    from pathlib import Path
    from lab9 import evalset

    items = evalset.load_jsonl(evalset.ITEMS_V2)
    labels = json.loads(evalset.LABELS_V2.read_text(encoding="utf-8"))
    original = json.loads(evalset.LABELS.read_text(encoding="utf-8"))
    assert len(items) == 28 and {key: labels[key] for key in original} == original
    attacked = {fm for item in items if item["split"] == "adversarial" for fm in item["failure_modes"]}
    counts = Counter(fm for item in items for fm in item["failure_modes"])
    assert all(counts[fm] >= 3 for fm in attacked)
    for item in items:
        assert "expected" not in item and "label" not in item
        assert ("money_movement" in item["slices"]) == (labels[item["claim_id"]]["refund_vnd"] > 0)
        assert ("adversarial" in item["slices"]) == (item["split"] == "adversarial")
    assert b"\r" not in Path(evalset.ITEMS_V2).read_bytes()


def test_v2_check_rejects_a_dropped_attack_item(tmp_path):
    import json
    from lab9 import evalset

    path = tmp_path / "eval_set_v2.jsonl"
    items = [item for item in evalset.load_jsonl(evalset.ITEMS_V2) if item["claim_id"] != "C-113"]
    path.write_text("".join(json.dumps(item) + "\n" for item in items), encoding="utf-8")
    assert any("C-113: adversarial claim missing" in problem for problem in evalset.check(path, evalset.LABELS_V2))
