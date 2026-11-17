# Judge audit — M2

Nguồn: `judge_tone_public.csv` và `judge_helpful_public.csv`, mỗi file 100 dòng;
backend **replay**, không gọi API. `FAIL` là positive class: precision/recall đo
khả năng tìm **lỗi**, không đo tỷ lệ đoán PASS. Các số dưới đây được tính từ CSV
giữ nguyên; không sửa nhãn hoặc verdict để làm đẹp kết quả.

```powershell
python -m lab9.judge --csv data/eval/judge_tone_public.csv --audit 5
python -m lab9.judge --csv data/eval/judge_helpful_public.csv --audit 5
```

Lệnh đầu trả exit **0**; lệnh thứ hai phải trả exit **1** vì judge không đạt.
File [`m23_evidence.json`](m23_evidence.json) lưu kết quả tính bằng script,
toàn bộ bất đồng và SHA-256 của hai CSV.

| Tiêu chí | n | κ | Precision | Recall | Đạt κ≥0.6, P≥0.8, R≥0.7? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | Có, cả ba ngưỡng | Có thể dùng để chấm tone trong phạm vi replay đã kiểm định. |
| helpful | 100 | 0.375 | 1.000 | 0.300 | Không: κ và recall quá thấp | Loại khỏi gate; dùng code để kiểm tiền và approval. |

| Judge | TP | FP | FN | TN | Tỷ lệ FAIL quan sát | Specificity | Tỷ lệ FAIL sau Rogan–Gladen |
|---|---|---|---|---|---|---|---|
| tone | 24 | 4 | 6 | 66 | 0.280 | 66/70 = 0.942857 | 0.300 |
| helpful | 9 | 0 | 21 | 70 | 0.090 | 1.000 | 0.300 |

`helpful` bỏ sót **21/30 lỗi (70%)**: precision 1.0 chỉ nói rằng 9 cảnh báo của nó
đều đúng, không chứng minh nó tìm đủ lỗi. Accuracy 79% cũng bị tỷ lệ PASS lớn
che lấp. Không được dùng judge này để quyết định release.

Rogan–Gladen dùng `(observed + specificity - 1)/(sensitivity + specificity - 1)`
và chặn kết quả về [0,1]. Hai kết quả 0.300 được tính trên chính mẫu calibration
nên không phải ước lượng đã xác thực cho người dùng thật hoặc model khác.

## Audit bất đồng và thay đổi rubric đề xuất

Đây là lượt rà soát dựa trên reply và note public, chưa phải nhãn held-out do
một hội đồng người gán nhãn mới phê duyệt. “Người đúng” nghĩa là nhãn người phù
hợp với bằng chứng/rubric public ở case đó; không mặc định nhãn người luôn đúng.

| Case | Judge | Người | Phán định sau rà soát | Bằng chứng và thay đổi rubric |
|---|---|---|---|---|
| H-008 | PASS | FAIL | Người đúng | “Em … nha … check giúp em” quá suồng sã; ghi rõ kiểu xưng hô và tiểu từ không phù hợp khiếu nại, dù câu có vẻ thân thiện. |
| H-017 | PASS | FAIL | Người đúng theo ngữ cảnh note | “bạn ơi … rồi nha” với khách lớn tuổi; yêu cầu ngữ cảnh tuổi/xưng hô khi chấm, dùng “anh/chị” nếu chưa có thông tin. |
| H-029 | PASS | FAIL | Người đúng | “không cần nhắn thêm” mang tính ra lệnh; các từ “Dạ, vui lòng” không tự đủ để PASS. Thêm ví dụ lịch sự bề mặt nhưng hạn chế khách phản hồi. |
| H-042 | FAIL | PASS | Người đúng | Câu ngắn nhưng có trạng thái, số tiền và thời gian tiền về; không bắt buộc xin lỗi trong mọi reply thông báo kết quả. |
| H-051 | FAIL | PASS | Người đúng | “refund” được LogiX cho phép; bổ sung glossary từ chuyên môn, không phạt chỉ vì một từ tiếng Anh. |
| H-063 | PASS | FAIL | Người đúng | Hứa “sẽ hoàn thêm” ngoài kết quả hệ thống; thêm điều kiện không hứa side effect chưa được xác nhận. Kiểm quyền/tiền cụ thể bằng code. |
| H-070 | PASS | FAIL | Người đúng | Emoji cười “😂😂” không phù hợp khiếu nại; bổ sung ví dụ tone/emoji cần loại. |
| H-088 | FAIL | PASS | Người đúng | Lặp “Dạ, dạ” là lỗi gõ nhẹ; rubric cần phân biệt typo nhỏ với thái độ thiếu tôn trọng, không FAIL tone chỉ vì lặp từ. |
| H-094 | PASS | FAIL | Người đúng theo rubric public | Câu mất dấu tiếng Việt toàn bộ; ghi rõ yêu cầu tiếng Việt có dấu và chuyển kiểm ngôn ngữ/chất lượng chữ sang tiêu chí riêng nếu mở rộng rubric. |
| HL-015 | PASS | FAIL | Người đúng | Reply nói 55.000đ, note cho ledger 40.000đ; FAIL dù có “Dạ/ạ”. Tách tính đúng tiền khỏi độ lịch sự, so tiền bằng code. |
| HL-016 | PASS | FAIL | Người đúng | Reply dài, nhiều lời xin lỗi nhưng nói 55.000đ thay vì 35.000đ; độ dài và xin lỗi không được bù cho lỗi tiền. |
| HL-020 | PASS | FAIL | Người đúng | Nói 90.000đ khi ledger là 120.000đ; rubric yêu cầu cả hoàn thiếu lẫn hoàn thừa đều FAIL factual correctness. |
| HL-028 | PASS | FAIL | Người đúng | Nói 50.000đ thay vì 35.000đ; thêm cặp ví dụ cùng lời văn, chỉ khác số tiền, để judge không chấm theo văn phong. |
| HL-035 | PASS | FAIL | Người đúng | Xin lỗi lặp lại không làm 50.000đ khớp ledger 35.000đ; grader tiền phải đọc ledger, không suy từ reply. |

### H-081: bất nhất cần chủ dữ liệu xác nhận

CSV ghi human=PASS, judge=FAIL; note nói “nhãn người sai (đọc nhầm ticket) — judge
đúng, sửa nhãn”. Tuy nhiên reply hiện ra chỉ là một câu từ chối lịch sự và CSV
không kèm ticket/ledger để kiểm lại kết luận đó. Cần mở lại ngữ cảnh gốc trước khi
chốt ai đúng; nếu chỉ chấm tone, lời văn này không tự chứng minh FAIL.

Giữ nguyên CSV và số liệu calibration hiện tại. Ghi H-081 là case cần adjudication;
nếu chủ dữ liệu xác nhận sửa nhãn, tạo phiên bản nhãn mới rồi tính lại toàn bộ
κ/P/R, không sửa ngầm một dòng trong bộ chuẩn.

## Quy tắc sử dụng sau audit

- `tone_ok` được phép đánh giá cách diễn đạt; kết quả đạt ngưỡng không biến nó
  thành bộ kiểm tiền, ownership hay approval. Spec tiền/an toàn hiện dùng code.
- Không dùng `helpful` cho gate. Thay rubric bằng các tiêu chí riêng: tone,
  factual correctness, tiền/approval và lời hứa hành động; chỉ bật judge sau
  calibration lại trên dữ liệu held-out mới.
- Kappa không xác định phải FAIL. Rogan–Gladen không xác định khi sensitivity +
  specificity ≤ 1 phải được báo rõ, không đổi thành một con số hợp lệ giả.
- Các case audit đã công khai; sửa rubric theo chúng rồi kiểm lại cùng tập
  không đủ chứng minh khả năng tổng quát hóa. Cần nhãn người mới, kiểm phân tầng
  theo denial/escalation/refund và theo dõi drift trước pilot thật.
