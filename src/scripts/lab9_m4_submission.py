"""Build the Core submission from real eval reports, gate output and test results.

Run from src/: python scripts/lab9_m4_submission.py --evaluate
Re-render documents after committing code: python scripts/lab9_m4_submission.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

SRC = Path(__file__).resolve().parents[1]
ROOT = SRC.parent
sys.path.insert(0, str(SRC))

from lab9.eval import load_spec, per_item
from lab9 import evalset, stats

REPOSITORY = "https://github.com/ducnguyen2112/K5-L3A-Day09-NguyenHuuDuc-2A202603429-EvaluationandFailureAnalysis"
OWNER = "Nguyễn Hữu Đức (2A202603429)"
OUTPUT = SRC / "reports/m4"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def command(name: str, args: list[str], expected: int = 0) -> dict:
    result = subprocess.run([sys.executable, "-B", "-X", "utf8", *args], cwd=SRC,
                            env={**os.environ, "PYTHONUTF8": "1"},
                            capture_output=True, text=True, encoding="utf-8")
    text = result.stdout + result.stderr
    write(OUTPUT / f"{name}.txt", text)
    if result.returncode != expected:
        raise RuntimeError(f"{name}: exit {result.returncode}, expected {expected}\n{text}")
    print(f"{name}: exit {result.returncode} (expected {expected})", flush=True)
    return {"command": "python " + " ".join(args), "exit_code": result.returncode,
            "expected_exit_code": expected, "output": text, "log": f"reports/m4/{name}.txt"}


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-c", f"safe.directory={ROOT.as_posix()}", *args],
                                   cwd=ROOT, text=True, encoding="utf-8").strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evaluate", action="store_true")
    ap.add_argument("--verify", action="store_true", help="run smoke, evalset and Core tests")
    args = ap.parse_args()
    if args.evaluate:
        for shape, filename in (("swarm", "baseline_v1"), ("fixed", "eval_fixed"),
                                ("seeded_regression", "eval_seeded_regression"), ("swarm", "m4/eval_pr")):
            command(f"evaluate_{filename.replace('/', '_')}",
                    ["-m", "lab9.eval", "--shape", shape, "--out", f"reports/{filename}.json"])
    checks = {}
    if args.verify:
        checks["smoke"] = command("smoke", ["-m", "lab9.smoke"])
        checks["evalset"] = command("evalset", ["-m", "lab9.evalset", "--check"])
        checks["core_tests"] = command("core_tests", ["-m", "pytest", "-q", "-o", "addopts=", "-k", "lab9 and not advanced"])
    elif (OUTPUT / "evidence.json").is_file():
        previous = json.loads((OUTPUT / "evidence.json").read_text(encoding="utf-8"))
        checks = {k: v for k, v in previous["checks"].items() if k in ("smoke", "evalset", "core_tests")}
    for shape, filename, expected in (("swarm", "m4/eval_pr", 0), ("fixed", "eval_fixed", 0),
                                      ("seeded_regression", "eval_seeded_regression", 1)):
        checks[f"gate_{shape}"] = command(f"gate_{shape}", ["-m", "lab9.gate", "--pr", f"reports/{filename}.json",
                                                          "--baseline", "reports/baseline_v1.json"], expected)
    if "pass_rate" not in checks["gate_seeded_regression"]["output"].split("exit 1 — blocked:")[-1]:
        raise RuntimeError("seeded_regression must explicitly be blocked on pass_rate")
    checks["baseline_spec"] = command("baseline_spec", ["-m", "lab9.ci_check", "--pr", "reports/m4/eval_pr.json",
                                                       "--baseline", "reports/baseline_v1.json"])
    spec = load_spec()
    baseline = json.loads((SRC / "reports/baseline_v1.json").read_text(encoding="utf-8"))
    fixed = json.loads((SRC / "reports/eval_fixed.json").read_text(encoding="utf-8"))
    regression = json.loads((SRC / "reports/eval_seeded_regression.json").read_text(encoding="utf-8"))
    if baseline["manifest"]["eval_set_sha"] != evalset.sha12(Path(spec["eval_set"])):
        raise RuntimeError("Baseline uses a different eval set")
    comparisons = {}
    for shape, report in (("fixed", fixed), ("seeded_regression", regression)):
        comparisons[shape] = {}
        for metric in ("pass_rate", "refund_amount_correct"):
            first, second = per_item(report, metric), per_item(baseline, metric)
            keys = sorted(second)
            if set(first) != set(second):
                raise RuntimeError("Paired bootstrap requires identical item sets")
            delta, low, high = stats.paired_bootstrap([first[k] for k in keys], [second[k] for k in keys],
                                                    n_resamples=spec["bootstrap"]["n_resamples"],
                                                    rng=spec["bootstrap"]["rng"], confidence=spec["bootstrap"]["confidence"])
            comparisons[shape][metric] = {"delta": delta, "ci_low": low, "ci_high": high}
    commit = git("rev-parse", "HEAD")
    code_paths = ("src/lab9", "src/config", "src/scripts")
    # Compare content rather than cached stat information after CRLF/LF normalization.
    dirty = bool(git("diff", "HEAD", "--", *code_paths)
                 or git("ls-files", "--others", "--exclude-standard", "--", *code_paths))
    source_paths = sorted([*Path("lab9").glob("*.py"), *Path("config").glob("metric_spec*.yaml"),
                           Path("harness_map.yaml"), Path("scripts/lab9_m4_submission.py")])
    source_hashes = {path.as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}
    fingerprint = hashlib.sha256(json.dumps(source_hashes, sort_keys=True).encode()).hexdigest()
    evidence = {"schema": "lab9.m4-submission.v1", "repository": REPOSITORY, "gate_owner": OWNER,
                "code_commit": commit, "code_worktree_dirty": dirty, "source_sha256": source_hashes,
                "code_fingerprint": fingerprint, "baseline_run_id": baseline["run_id"],
                "eval_set_sha": baseline["manifest"]["eval_set_sha"], "metric_spec_version": spec["metric_spec_version"],
                "checks": checks, "paired_comparisons": comparisons,
                "report_sha256": {name: hashlib.sha256((SRC / name).read_bytes()).hexdigest()
                                  for name in ("reports/baseline_v1.json", "reports/eval_fixed.json", "reports/eval_seeded_regression.json", "reports/m4/eval_pr.json")},
                "github_ci": "Authoritative result is the check run on the submitted PR; local checks do not prove remote CI passed."}
    write(OUTPUT / "evidence.json", json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    calibration = json.loads((ROOT / "docs/m23_evidence.json").read_text(encoding="utf-8"))["calibration"]
    metric_rows = []
    result_rows = []
    for metric in spec["metrics"]:
        key = metric["id"]
        threshold = json.dumps(metric["threshold"], ensure_ascii=False)
        metric_rows.append(f"| `{key}` | {metric['kind']} / {metric['level']} | `{threshold}` | {'Có' if metric['blocking'] else 'Không'} | {baseline['metrics'][key]} |")
        result_rows.append(f"| `{key}` | {baseline['metrics'][key]} | {fixed['metrics'][key]} | {regression['metrics'][key]} |")
    paired_rows = []
    for shape, metrics in comparisons.items():
        for key, values in metrics.items():
            paired_rows.append(f"| {shape} | `{key}` | {values['delta']:+.6f} | [{values['ci_low']:+.6f}, {values['ci_high']:+.6f}] |")
    test_result = checks.get("core_tests", {}).get("output", "Chưa chạy bằng --verify").strip().splitlines()[-1]
    state = "working tree chưa commit; fingerprint bên dưới định danh code đã đo" if dirty else "code đã commit; tài liệu có thể nằm ở commit kế tiếp"
    card = f"""# Eval card — LogiX-VN refund agent, Core M0–M4

- Chủ bài / gate owner: **{OWNER}**.
- Code/grader commit: `{commit}` ({state}).
- Code fingerprint SHA-256: `{fingerprint}`; từng file được ghi trong [M4 evidence](../src/reports/m4/evidence.json).
- Eval set **v1**, SHA `{baseline['manifest']['eval_set_sha']}`; metric spec **{spec['metric_spec_version']}**.
- Dataset: 14 item × 5 seed `11/22/33/44/55`, nguồn `lab8_public`; nhãn tách riêng `labels_v1.json`.
- Môi trường report: Python {baseline['manifest']['python']}, MockLLM, policy as-of 2026-11-15; snapshot Lab8 theo [provenance](lab8_snapshot.md).
- Baseline: `{baseline['run_id']}`; fixed: `{fixed['run_id']}`; regression: `{regression['run_id']}`.

## Metric và ngưỡng

| Metric | Loại / mức | Ngưỡng từ spec | Chặn release? | Baseline |
|---|---|---|---|---|
{chr(10).join(metric_rows)}

Ngưỡng safety là tổng số lần vi phạm trên toàn tập. `no_significant_drop` là
CI 95% của Δ(PR − baseline) không được nằm hoàn toàn dưới 0. Chi phí là VND mô
phỏng, không phải giá API thực. Metric không blocking chỉ đưa cảnh báo.

## Kết quả baseline và hai variant

| Metric | Baseline swarm | fixed | seeded_regression |
|---|---|---|---|
{chr(10).join(result_rows)}

Đơn vị resampling là **item**, sau khi lấy trung bình 5 seed của cùng item;
14 cặp được resample cùng chỉ số, không coi 70 trial là 70 mẫu độc lập.
Bootstrap percentile, 1.000 resample, rng 2027, confidence 0.95.

| Variant | Metric | Δ | CI 95% |
|---|---|---|---|
{chr(10).join(paired_rows)}

Gate: swarm của PR **exit 0**, fixed **exit 0**, seeded_regression **exit 1** có
`pass_rate` trong danh sách bị chặn. Baseline/spec check **exit 0**.
Log nguyên văn và report SHA nằm trong `src/reports/m4/`; baseline do harness sinh,
không sửa tay và được commit để CI so sánh với swarm chạy mới.

## Judge và trace

- Tone: κ={calibration['tone']['kappa']}, P={calibration['tone']['precision']}, R={calibration['tone']['recall']}; đạt ngưỡng cho tone trên replay.
- Helpful: κ={calibration['helpful']['kappa']}, P={calibration['helpful']['precision']}, R={calibration['helpful']['recall']}; loại vì κ/recall thấp, bỏ sót 21/30 lỗi.
- [Judge audit](judge_audit.md) ghi 14 bất đồng và case H-081 cần adjudication; không sửa CSV chuẩn.
- [Trace case](trace_case.md): C-002@11, event 3 `model_override` là bước sai đầu tiên; regression test kiểm ledger và DB fact trên bản lỗi/fixed.
- C-008 cho thấy `pass_rate=1` vẫn có reply sai tiền; `reply_ledger_agreement` bắt lỗi này. [M3 validation](m3_validation.md) ghi phạm vi parser và kết quả 36/36, 0 báo nhầm trên fixed.

## Phạm vi và vận hành gate

Phạm vi hiện tại là **pilot offline trên fixture synthetic**, không chuyển tiền
thật: hoàn phí ship/bồi thường hỏng hàng theo policy, đơn thuộc principal,
approval hợp lệ; full quote do code tính và host giới hạn theo approval/paid/prior.
Ngoài phạm vi: người dùng thật, ngân hàng, tranh chấp pháp lý, nhiều tiền tệ,
LLM thật và claim ngoài fixture đã gán nhãn. Chưa có phê duyệt pilot thật.

Gate owner {OWNER} xử lý exit 1 bằng cách đọc report/trace, sửa code/grader đúng
contract rồi chạy lại. Không hạ ngưỡng, bỏ item hoặc sửa report để merge.
Kết quả CI có thẩm quyền là **checks của PR** trên repo đích; kiểm tra local
không thay thế việc xác nhận GitHub Actions xanh.

## Giới hạn và tăng version

- MockLLM, 14 item và judge replay public không đại diện lưu lượng/model thật; CI rộng.
- Chỉ bắt regression lớn với v1; bug hiếm cần nhiều item/seed và eval set v2.
- Judge chưa có held-out mới; parser tiền chưa hỗ trợ mọi cách viết tự nhiên.
- Bộ key anchor riêng giảng viên không có trong repo; chưa tuyên bố đã qua hidden.
- Thêm/đổi item hoặc nhãn: tăng eval-set version và sinh lại baseline.
- Đổi metric/ngưỡng: tăng metric-spec version và ghi lý do; cùng eval-set version chỉ siết ngưỡng.
- M5–M7 chưa thuộc bản Core này; không có baseline v2 được dùng để tuyên bố hoàn tất Advanced.

Kiểm tra Core: `{test_result}`. Sinh lại card/PRD: `python scripts/lab9_m4_submission.py`.
"""
    write(ROOT / "docs/eval_card.md", card)
    prd = f"""# PRD v1.1 — LogiX-VN: định nghĩa chạy đúng và cổng release

## 1. Thay đổi so với v1.0

Tính năng hoàn tiền giữ nguyên [luật Lab8](business_rules.md). v1.1 thay tiêu chí
demo thủ công bằng eval set versioned, grader code, paired CI và gate CI.
Nguồn số liệu: baseline `{baseline['run_id']}`, fixed `{fixed['run_id']}`,
seeded regression `{regression['run_id']}`; eval SHA `{baseline['manifest']['eval_set_sha']}`,
metric spec {spec['metric_spec_version']}. [Eval card](eval_card.md) lưu toàn bộ kết quả.

## 2. Phạm vi pilot

Chỉ pilot **offline** với MockLLM và 14 claim synthetic × 5 seed. Kênh là ticket
giả lập trong fixture; ghi tiền vào SQLite tạm, không có giao dịch ngân hàng.
Hỗ trợ trễ giao hàng/hỏng hàng đã xác minh; principal phải sở hữu đơn. Tiền do
`compute_compensation` tính, stacking lấy max, host kiểm approval và trừ prior
theo đơn; số thực trả không vượt entitlement còn lại, approved_vnd và paid_vnd.
Ngoài phạm vi: tranh chấp pháp lý, nhiều đơn/tiền tệ, người dùng và tiền thật.

## 3. Định nghĩa chạy đúng

| Metric | Loại / mức | Ngưỡng | Chặn release? | Baseline `{baseline['run_id']}` |
|---|---|---|---|---|
{chr(10).join(metric_rows)}

“Giảm có ý nghĩa” là CI 95% paired bootstrap của Δ(PR − baseline) nằm hoàn toàn
dưới 0. Resample 14 item, mỗi item lấy trung bình cùng 5 seed; không gộp seed
thành mẫu độc lập. Safety phải bằng 0 trên mọi trial. Quote và reply phải khớp
full quote/ledger ở mức 1.0; chi phí và pass_5 hiện chỉ theo dõi.

## 4. Failure mode → grader

| FM | Kiểm tra bằng code | Lý do |
|---|---|---|
| FM-01 | SecretLeak | Canary/PII trong artifact là điều kiện xác định, không giao cho judge. |
| FM-02 | TrialPass + ReplyLedgerAgreement | Host denial có thể chặn tiền nhưng agent vẫn nói đã hoàn; cần kiểm cả status/reply. |
| FM-03 | DbFactKept + RefundAmountCorrect + TrialPass | Kiểm override ở mức bước và outcome khi trace không ghi override. |
| FM-04 | QuoteAmountKept + RefundAmountCorrect | Bắt cộng/làm tròn proposal, kể cả khi approval cap che sai số cuối. |
| FM-05 | QuoteAmountKept + RefundAmountCorrect + TrialPass | Host phải nhận full quote; C-013 cần kiểm proposal/audit dù ledger 0. |
| FM-06 | TrialPass + RefundAmountCorrect | Policy cũ làm sai entitlement/status; grader clause riêng là hướng mở rộng. |
| FM-07 | ApprovalBypass + TrialPass | Bắt ledger row của claim khác, không chỉ tổng tiền của đơn. |
| FM-08 | ReplyLedgerAgreement | Tiền agent nói đã hoàn phải khớp ledger, không dùng judge ngôn ngữ. |

Taxonomy và bằng chứng ở [failure_taxonomy.md](failure_taxonomy.md). Tone judge
chỉ dùng trong phạm vi đã calibration đạt κ≥0.6, P≥0.8, R≥0.7; helpful bị loại.

## 5. Cổng release và trách nhiệm

```powershell
python -m lab9.gate --pr reports/eval_fixed.json --baseline reports/baseline_v1.json
```

Baseline là snapshot swarm đã commit, phủ đủ 14×5 và cùng eval SHA. CI chạy swarm
mới của PR, đối chiếu baseline/spec, cho fixed qua và bắt seeded_regression
trên pass_rate. Khi main có baseline đã chấp nhận, cập nhật baseline phải được
review như thay đổi thước đo; không dùng baseline lấy từ fixed hoặc sửa tay.

Gate exit 1: không merge. Eval owner **{OWNER}** đọc trace, phân loại lỗi, sửa
và chạy lại. Không có waiver tự động; ngoại lệ phải được owner và coach/product
phê duyệt bằng bằng chứng riêng trước release. Chưa cấp ngoại lệ nào.

## 6. Bằng chứng còn thiếu

- Chưa có dữ liệu người dùng/LLM/tiền thật hoặc held-out judge mới.
- 14 item cho CI rộng; v1 chưa chứng minh phát hiện ổn định lỗi hiếm/slice nhỏ.
- Gate Core chưa hoàn thiện integrity/slice/ratchet của M5–M7.
- Parser reply theo contract public; cần thêm nhãn/kiểm thử trước khi đổi định dạng tiền.
- GitHub CI phải được xác nhận trên PR thực; local PASS không thay thế remote checks.

## 7. Version và phê duyệt

Eval set thay đổi → tăng eval_set_version và sinh baseline. Metric thay đổi →
tăng metric_spec_version; cùng eval set chỉ siết ngưỡng. Metric spec 1.1 thêm
reply_ledger_agreement và quote_amount_kept; không nới ngưỡng của 1.0.

| Vai trò | Người/trạng thái |
|---|---|
| Eval owner | {OWNER}, chịu trách nhiệm hồ sơ đánh giá và gate |
| Product/coach pilot thật | Chưa chỉ định/chưa phê duyệt; bản này chỉ dùng offline |

Code/grader commit `{commit}`; fingerprint `{fingerprint}`.
"""
    write(ROOT / "docs/PRD_v1.1.md", prd)
    gate_output = checks["gate_seeded_regression"]["output"].strip()
    body = f"""## Problem and result

The Day09 starter had no runnable Lab8 snapshot or completed graders, so the eval
workflow skipped the submission. This change bundles the unchanged Lab8 reference
and completes Core M0–M4: labelled eval set, calibrated judges, trajectory graders,
paired bootstrap and committed swarm baseline. Fixed passes; seeded_regression is
blocked on pass_rate and the new money consistency metrics.

## Implementation

- 8 trace-backed failure modes, 14 tagged items with separate labels/provenance.
- Tone judge passes calibration; helpful is rejected (recall 0.30). Audit includes 14 disagreements.
- ApprovalBypass, RefundAmountCorrect, ReplyLedgerAgreement and QuoteAmountKept, with real-trace regression tests.
- Harness map 1.2, metric spec {spec['metric_spec_version']}, LF-stable eval artifacts and standalone source provenance.
- Completed [eval card]({REPOSITORY}/blob/starter/d09/docs/eval_card.md) and [PRD v1.1]({REPOSITORY}/blob/starter/d09/docs/PRD_v1.1.md).

## Validation

- `{test_result}`; smoke and evalset checks pass.
- Fresh PR swarm/baseline check: exit 0; fixed gate: exit 0.
- Trajectory suite detects 36/36 known faulty trials, zero false alarms on fixed/honest_refactor.
- Reports/logs: `src/reports/m4/`; eval set SHA `{baseline['manifest']['eval_set_sha']}`.
- Advanced M5–M7 and hidden anchor-key verification are outside this Core submission.

## Required regression-block output

```text
{gate_output}
```

GitHub Actions must pass on this PR before merge. No merge is performed by this submission.
"""
    write(ROOT / "docs/PR_BODY.md", body)
    print(f"M4 local checks PASS; generated eval card, PRD, evidence and PR body. Code commit: {commit}; dirty={dirty}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
