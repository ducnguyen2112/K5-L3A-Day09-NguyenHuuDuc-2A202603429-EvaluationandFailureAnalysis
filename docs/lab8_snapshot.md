# Nguồn Lab8 dùng để chạy Day09

Repo Day09 này chứa snapshot Lab8 cần thiết để clone rồi chạy trực tiếp; workflow
`eval-gate` sẽ thực thi thay vì bỏ qua vì thiếu `src/lab8/`.

- Nguồn: `https://github.com/blueT52Hz/K5-L3A-DAY08-Nhom3Nguoi-FromWorkflowsToAgents`.
- Commit nguồn: `b72cd96` (bản `NguyenHuuDuc` đã có Lab9 overlay).
- Git tree của riêng `src/lab8/`: `acb1ce068ece8a9c4109313ae6696ed75a07504f`.
- Toàn bộ file trong `src/lab8/` được chép nguyên nội dung, chỉ chuẩn hóa CRLF/LF theo `.gitattributes`, không sửa logic để qua grader.
- Dữ liệu public, policy, pricing và tool manifest cũng được giữ nguyên từ nguồn.
- Các chỉnh sửa bài Day09 nằm trong `src/lab9/`, metric spec, eval set, harness map,
  test, script xuất bằng chứng và tài liệu Day09.
- Không mang theo `.env`, môi trường Python, DB chạy thử, trace runtime hoặc bộ hidden.

Baseline và M0–M4 chạy shape `swarm` reference; không yêu cầu các shape còn lại
của Lab8 hoàn tất. `docs/business_rules.md`, `docs/contracts.md`, `docs/metrics.md`
được mang theo để người chấm đọc được contract và luật gốc.

Nếu cần ghép lại vào repo nhóm, sử dụng overlay Day09 theo README. Không chép đè
`src/lab8/` hoặc các cấu hình nghiệp vụ của một bản Lab8 khác.
