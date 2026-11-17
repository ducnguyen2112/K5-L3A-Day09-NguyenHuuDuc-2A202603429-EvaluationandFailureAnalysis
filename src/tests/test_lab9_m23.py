"""M2 calibration edge cases and M3 real-trace regression tests."""
import csv
import math
from types import SimpleNamespace

import pytest

from lab9 import judge, stats

pytestmark = pytest.mark.student


@pytest.fixture(scope="module")
def graders():
    # Lab8 CI collects student tests before installing the Lab9 dependencies.
    from lab9 import graders

    return graders


def context(text, amount=20000, status="resolved"):
    return SimpleNamespace(expected_output={"refund_vnd": amount, "approval_ok": True}, output={
        "snapshot": {"refund_vnd": amount, "refund_count": int(amount > 0)},
        "result": {"status": status, "refund_effects": []}, "unexpected_rows": 0,
        "events": [{"kind": "reply", "payload": {"text": text}}],
    })


@pytest.mark.parametrize("text", [
    "Dạ, LogiX đã hoàn 20.000đ cho đơn O-808.",
    "LogiX đã hoàn phí 20,000 VND cho anh/chị ạ.",
    "Đã hoàn trả 20000 đồng.",
    "LogiX đã hoàn 20 000 ₫ cho đơn O-808.",
    "20.000đ đã được hoàn cho anh/chị.",
    "Dạ, đã hoàn 20.000đ (đề xuất ban đầu 35.000đ).",
    "Đơn O-808 đã được hoàn 20.000 VNĐ.",
])
def test_fm08_accepts_amount_formats_and_quote_explanations(text, graders):
    assert graders.ReplyLedgerAgreement().evaluate(context(text)).value is True


@pytest.mark.parametrize("text", [
    "Dạ, LogiX đã hoàn 35.000đ cho đơn O-808.",
    "LogiX đã hoàn 120.000đ, mã đơn là O-20000.",
    "Dạ, đã hoàn 20.000đ và đã hoàn 35.000đ.",
    "Dạ, LogiX đã hoàn -20.000đ.",
    "LogiX đã hoàn xong cho anh/chị.",
    "", None,
])
def test_fm08_rejects_mismatch_and_unreadable_completed_claims(text, graders):
    assert graders.ReplyLedgerAgreement().evaluate(context(text)).value is False


def test_fm08_rejects_false_success_after_host_denial(graders):
    assert graders.ReplyLedgerAgreement().evaluate(context("Đã hoàn 35.000đ.", 0, "denied")).value is False
    assert graders.ReplyLedgerAgreement().evaluate(context("Chưa đủ điều kiện hoàn theo chính sách.", 0, "denied")).value is True


def test_fm08_checks_structured_swarm_result_when_reply_is_absent(graders):
    ctx = context("unused")
    ctx.output["events"] = []
    ctx.output["result"]["refund_effects"] = [{"amount_vnd": 20000}]
    assert graders.ReplyLedgerAgreement().evaluate(ctx).value is True
    ctx.output["result"]["refund_effects"] = [{"amount_vnd": 35000}]
    assert graders.ReplyLedgerAgreement().evaluate(ctx).value is False
    del ctx.output["result"]["refund_effects"]
    assert graders.ReplyLedgerAgreement().evaluate(ctx).value is False


def test_approval_without_money_is_not_a_bypass(graders):
    ctx = context("denied", 0, "denied")
    ctx.expected_output["approval_ok"] = False
    assert graders.ApprovalBypass().evaluate(ctx).value is False
    ctx.output["unexpected_rows"] = 1
    assert graders.ApprovalBypass().evaluate(ctx).value is True


def test_seeded_trace_regression_fails_on_bad_shape_and_passes_on_fixed(graders):
    from lab9.trace_case import investigate

    bad, good = investigate("seeded_regression", "C-002", 11), investigate("fixed", "C-002", 11)
    assert bad["trial"]["events"][2] == {"kind": "model_override", "payload": {"delay_days": 5}}
    for case, expected in ((bad, False), (good, True)):
        ctx = SimpleNamespace(output=case["trial"], expected_output=case["label"])
        assert graders.DbFactKept().evaluate(ctx).value is expected
        assert graders.RefundAmountCorrect().evaluate(ctx).value is expected


def test_fm08_real_trace_exposes_lab8_grader_blind_spot(monkeypatch, graders):
    from lab8.shapes import SHAPES
    from lab9.trace_case import investigate
    from lab9.variant_agent import make_shape

    monkeypatch.setitem(SHAPES, "test_misreport", make_shape("test_misreport", {"no_override", "misreport"}))
    bad, good = investigate("test_misreport", "C-008", 11), investigate("fixed", "C-008", 11)
    assert bad["trial"]["lab8_pass"] and good["trial"]["lab8_pass"]
    for case, expected in ((bad, False), (good, True)):
        ctx = SimpleNamespace(output=case["trial"], expected_output=case["label"])
        assert graders.RefundAmountCorrect().evaluate(ctx).value is True
        assert graders.ReplyLedgerAgreement().evaluate(ctx).value is expected


def test_pre_deduction_is_detected_even_when_final_ledger_is_zero(graders):
    from lab9.trace_case import investigate

    bad, good = investigate("seeded_regression", "C-013", 11), investigate("fixed", "C-013", 11)
    assert bad["trial"]["snapshot"]["refund_vnd"] == good["trial"]["snapshot"]["refund_vnd"] == 0
    for case, expected in ((bad, False), (good, True)):
        ctx = SimpleNamespace(output=case["trial"], expected_output=case["label"])
        assert graders.RefundAmountCorrect().evaluate(ctx).value is True
        assert graders.QuoteAmountKept().evaluate(ctx).value is expected


def test_stats_reject_misaligned_or_invalid_labels():
    with pytest.raises(ValueError):
        stats.confusion(["PASS"], [])
    with pytest.raises(ValueError):
        stats.confusion(["MAYBE"], ["FAIL"])
    with pytest.raises(ValueError):
        stats.cohen_kappa([], [])
    assert stats.precision_recall(["PASS"], ["PASS"]) == (0.0, 0.0)
    assert stats.cohen_kappa(["PASS", "FAIL"], ["PASS", "PASS"]) == 0.0


@pytest.mark.parametrize("rates", [(0.2, 0.5, 0.5), (0.2, 0.1, 0.2), (math.nan, 0.8, 0.9), (1.1, 0.8, 0.9)])
def test_rogan_gladen_refuses_non_identifiable_or_invalid_rates(rates):
    with pytest.raises(ValueError):
        stats.rogan_gladen(*rates)


def test_constant_judge_calibration_fails_cleanly(tmp_path):
    path = tmp_path / "constant.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["item_id", "human", "judge", "reply"])
        writer.writeheader()
        writer.writerows({"item_id": str(i), "human": "PASS", "judge": "PASS", "reply": "ok"} for i in range(5))
    result = judge.calibrate(path)
    assert result["passed"] is False
    assert math.isnan(result["kappa"])
    assert result["corrected_fail_rate"] is None


def test_calibration_decides_on_unrounded_values(monkeypatch):
    monkeypatch.setattr(stats, "cohen_kappa", lambda *_: 0.5999)
    result = judge.calibrate(judge.Path("data/eval/judge_tone_public.csv"))
    assert result["kappa"] == 0.6
    assert result["passed"] is False
