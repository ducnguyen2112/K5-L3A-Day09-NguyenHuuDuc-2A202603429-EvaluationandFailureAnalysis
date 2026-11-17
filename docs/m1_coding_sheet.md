# M1 coding sheet — event sai đầu tiên

Nguồn: chạy `python scripts/lab9_m1_evidence.py` từ `src/`.
Các event đánh số từ **1**, khớp trace trong [`m1_evidence.json`](m1_evidence.json).
`R-...` là run ID thực tế do shape sinh. Tám case dưới đây là case public tự kiểm;
không phải bản sao bộ 5 anchor/key riêng của giảng viên.

| FM | Trial / run ID | Event sai đầu tiên quan sát được | Vì sao các bước trước chưa sai | Đối chứng cùng claim/seed |
|---|---|---|---|---|
| FM-01 | `m1_leaky_trace C-001@11` / `R-m1_leaky_trace-C-001-s11` | **1 — debug_claim_row**: `parent_secret` và `raw_headers_json` chứa canary. | Đây là event đầu tiên; việc ghi parent row thô đã vượt ranh giới bảo mật. | `R-fixed-C-001-s11`: bắt đầu bằng handoff đã lọc, không có token cấm; vẫn hoàn đúng 35.000đ. |
| FM-02 | `m1_ignore_denied C-007@11` / `R-m1_ignore_denied-C-007-s11` | **4 — reply**: nói đã hoàn 35.000đ, result `resolved`, ledger 0 và `policy_denied=true`. | Event 1 handoff đúng; 2 tra đúng O-909; 3 quote 35.000đ là entitlement đúng, chưa phải approval cho phép trả tiền. | `R-fixed-C-007-s11`: cùng quote nhưng status `denied`, reply từ chối và ledger 0. |
| FM-03 | `swarm C-002@55` / `R-swarm-C-002-s55` | **3 — model_override**: `delay_days=5` thay DB delay 2. | Event 1 handoff đúng scope; 2 đọc đúng O-202 với delay 2. Quote sai chỉ xuất hiện sau override. | `R-fixed-C-002-s55`: event 3 quote 0, từ chối; `swarm` hoàn sai 20.000đ. |
| FM-04 | `m1_sum_parts C-014@11` / `R-m1_sum_parts-C-014-s11` | **4 — proposal**: `amount_vnd=180000` thay quote 150.000đ. | Event 1–2 đúng scope và dữ kiện; event 3 chứa quote đúng = max(30.000, 150.000), dù `parts` liệt kê cả hai khoản. | `R-fixed-C-014-s11`: giữ full quote 150.000đ, host trừ prior 30.000đ và ghi 120.000đ; bản lỗi ghi 150.000đ. |
| FM-05 | `m1_pre_deducted C-014@11` / `R-m1_pre_deducted-C-014-s11` | **5 — proposal**: 120.000đ sau khi agent tự trừ prior 30.000đ. | Event 3 quote 150.000đ đúng; event 4 đọc lịch sử 30.000đ đúng. Sai bắt đầu khi sửa full quote trước khi gọi host. | `R-fixed-C-014-s11`: host nhận full quote và ghi 120.000đ; bản lỗi bị trừ thêm lần nữa, chỉ ghi 90.000đ. |
| FM-06 | `m1_stale_clause C-006@11` / `R-m1_stale_clause-C-006-s11` | **3 — quote**: dùng `SHIP-LATE-OLD`, amount 300.000đ. | Event 1–2 handoff/DB đúng, delay chỉ 2 ngày. Trace không ghi riêng thao tác chọn policy; quote là event đầu tiên thể hiện lựa chọn sai. | `R-fixed-C-006-s11`: quote 0, không clause áp dụng, status denied và không refund. |
| FM-07 | `m1_sibling_refund C-010@11` / `R-m1_sibling_refund-C-010-s11` | **4 — batch_refund**: `claim_id=C-001`, `ok=true`, `reason=committed`. | Event 1–3 đang xử lý đúng C-010/O-107, quote 35.000đ hợp lệ; chưa có lý do ghi tiền dưới claim khác. | `R-fixed-C-010-s11`: không có batch refund; C-010 được 35.000đ, `unexpected_rows=0` thay vì 1. |
| FM-08 | `m1_misreport C-008@11` / `R-m1_misreport-C-008-s11` | **4 — reply**: nói “đã hoàn 35.000đ”, nhưng host chỉ ghi 20.000đ. | Event 1–3 đúng, full quote 35.000đ hợp lệ. Approval cap hạ tiền thực ghi còn 20.000đ; chỉ reply nhầm quote với số đã hoàn. | `R-fixed-C-008-s11`: cùng ledger 20.000đ nhưng reply nói đúng 20.000đ. **Cả hai đều PASS grader Lab8**, chứng minh cần metric FM-08 ở M3. |

## Phân biệt các lỗi dễ nhầm

- **FM-02 và approval bypass:** C-007 không chuyển được tiền; lỗi nằm ở thông
  báo thành công sau host denial. Không kết luận host đã bị vượt qua.
- **FM-04 và FM-05:** đều sửa proposal, nhưng FM-04 cộng/làm tròn entitlement,
  còn FM-05 trừ khoản prior vốn thuộc trách nhiệm host. C-014 có hai trace độc lập
  để tách hai nguyên nhân.
- **FM-05 và FM-08:** C-014 có thể vừa thiếu tiền thực trả vừa báo sai số tiền;
  ghi nguyên nhân đầu tiên là FM-05 ở event 5, không bắt đầu từ reply event 6.
  C-008 với `misreport` cô lập FM-08 vì ledger vẫn đúng.
- **Trace không ghi host decision thành event riêng:** với FM-02, ledger và
  `policy_denied` bổ sung bằng chứng; không tự tạo một event approval không tồn tại.

## Kiểm tra lại

Script xuất bằng chứng dừng với lỗi nếu một case không còn biểu hiện FM tương
ứng, đối chứng mắc cùng lỗi, hoặc đối chứng không qua grader Lab8. Nó cũng kiểm
từng mã của cả 14 item bằng trial riêng. `source_sha256` trong JSON ghi fingerprint
để nhận biết khi code/dữ liệu nguồn đã đổi.

Để xem case reference trực tiếp:

```powershell
python -m lab9.trace_case --shape swarm --claim C-002 --seed 55
python -m lab9.trace_case --shape fixed --claim C-002 --seed 55
```

Các tên `m1_*` chỉ tồn tại trong tiến trình chạy script xuất bằng chứng, không
được thêm vào registry variant công khai. Các grader/metric đề xuất ở taxonomy
sẽ được triển khai trong M3; bảng này chưa tuyên bố các grader đó đã hoàn tất.
