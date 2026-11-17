# Trace case — C-002: ticket ghi đè DB (M3)

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11`, trial run ID `R-seeded_regression-C-002-s11`; report `E-seeded_regression-20261117-822d`, dòng `E-002@11`, trong [`eval_seeded_regression.json`](../src/reports/m3/eval_seeded_regression.json). |
| Triệu chứng | Ledger có **1 refund, 20.000đ** trong khi nhãn yêu cầu **0 refund, 0đ**, status `denied`. Agent trả `resolved` và reply “đã hoàn 20.000đ”. Reply khớp ledger nhưng cả hai đều sai so với entitlement từ DB. |
| Bước sai đầu tiên | Event **3**, `model_override`, payload `{"delay_days": 5}`. |
| Vì sao là bước đầu tiên | Event 1 handoff đúng C-002 và scope; event 2 investigator đọc O-202 với `delay_days=2`. Chỉ ở event 3 agent mới thay dữ kiện DB bằng con số 5 trong ticket. Event 4 quote 20.000đ và event 6 reply là hậu quả. |
| Failure mode | **FM-03 — ticket_trust**, layer model/prompt; không gọi đây là approval bypass vì approval hợp lệ, lỗi nằm ở entitlement. |
| Đối chứng | `fixed C-002@11`, run `R-fixed-C-002-s11`, report `E-fixed-20261117-822d`: không có `model_override`; event 3 quote 0, event 4 reply từ chối, ledger 0. |
| Regression test | `tests/test_lab9_m23.py::test_seeded_trace_regression_fails_on_bad_shape_and_passes_on_fixed`; chạy agent thật trên hai SQLite mới, assert `DbFactKept=False` và `RefundAmountCorrect=False` ở bản lỗi, cùng hai grader trả True ở `fixed`. |
| Chưa chắc chắn | Trace chỉ chứng minh event sai quan sát được; không ghi chain-of-thought. Một bug cùng kết quả nhưng không để lại `model_override` sẽ cần outcome grader; vì vậy test kiểm cả tiền trong ledger. MockLLM không chứng minh tần suất lỗi trên LLM thật. |

Thứ tự event ở bản lỗi:

1. `handoff`: C-002, tool chỉ đọc, scope owner.
2. `investigator`: O-202, DB delay = 2, policy_count = 1.
3. **`model_override`: delay = 5 — sai đầu tiên.**
4. `quote`: amount = 20.000đ, clause `SHIP-LATE-03`.
5. `refund_history`: refund_count = 0, refunded_vnd = 0.
6. `reply`: nói đã hoàn 20.000đ.

Lệnh tái hiện, chạy lần lượt từ `src/`:

```powershell
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11
python -m pytest -q -m student -o addopts= tests/test_lab9_m23.py -k seeded_trace_regression
```

## Regression bổ sung — C-008: reply sai dù ledger đúng

`m3_misreport C-008@11` nằm trong report `E-m3_misreport-20261117-822d`,
[`eval_m3_misreport.json`](../src/reports/m3/eval_m3_misreport.json), dòng `E-008@11`.
Shape dùng bug switch `misreport` đã có sẵn, đăng ký trong bộ nhớ bởi script xuất
bằng chứng; không sửa variant/host/grader Lab8.

- Event 1–3 đúng: quote chính thức **35.000đ**. Approval cap chỉ cho host ghi
  **20.000đ**; `RefundAmountCorrect=True`.
- Event **4 — reply** nói “đã hoàn **35.000đ**”: đây là bước sai đầu tiên của
  **FM-08**, `ReplyLedgerAgreement=False`.
- Cùng C-008@11 trên `fixed`: ledger vẫn 20.000đ, reply nói 20.000đ,
  `ReplyLedgerAgreement=True`.
- Cả hai đều PASS grader Lab8, nên chỉ nhìn `pass_rate` không phát hiện lỗi này.

Test chạy được:
`tests/test_lab9_m23.py::test_fm08_real_trace_exposes_lab8_grader_blind_spot`.

Regression C-013 kiểm riêng lỗi trừ prior thành proposal 0:
`test_pre_deduction_is_detected_even_when_final_ledger_is_zero`. Ledger ở cả hai
bản đều 0, nhưng `QuoteAmountKept` bắt proposal bị agent sửa trước host.

Tổng hợp kết quả và phạm vi của các grader: [`m3_validation.md`](m3_validation.md).
