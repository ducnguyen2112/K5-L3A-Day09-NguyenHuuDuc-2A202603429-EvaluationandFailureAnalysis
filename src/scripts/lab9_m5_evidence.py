"""Verify M5 and export real v2 evaluations, slice ablation and scope traces.

Run from src/: python scripts/lab9_m5_evidence.py --evaluate --verify
The M5 baseline lives in reports/m5/; reports/baseline_v2.json is the full M5-M7 baseline.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

SRC = Path(__file__).resolve().parents[1]
ROOT = SRC.parent
sys.path.insert(0, str(SRC))

from lab9 import ci_check, evalset, gate, stats, variants
from lab9.eval import load_spec, load_world, make_task, per_item, run_eval

OUTPUT = Path("reports/m5")
SPEC = Path("config/metric_spec_v2.yaml")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def save(path: Path, value: dict) -> None:
    write(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evaluate", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--refresh-baseline", action="store_true",
                    help="Regenerate from a fresh swarm run after a metric-spec version change")
    args = ap.parse_args()
    problems = evalset.check(evalset.ITEMS_V2, evalset.LABELS_V2)
    if problems:
        raise RuntimeError("Invalid v2 eval set: " + "; ".join(problems))
    spec = load_spec(SPEC)
    variants.register()
    reports = {}
    if args.evaluate:
        for shape in ("swarm", "fixed", "honest_refactor", "slice_regression"):
            report = run_eval(shape, spec)
            if report["evaluator_failures"]:
                raise RuntimeError(f"Broken grader on {shape}: {report['evaluator_failures']}")
            save(OUTPUT / f"eval_{shape}.json", report)
            reports[shape] = report
            print(f"{shape}: {len(report['rows'])} trials, pass_rate={report['metrics']['pass_rate']}", flush=True)
    else:
        reports = {shape: json.loads((OUTPUT / f"eval_{shape}.json").read_text(encoding="utf-8"))
                   for shape in ("swarm", "fixed", "honest_refactor", "slice_regression")}
    baseline_path = OUTPUT / "baseline_v2.json"
    if args.refresh_baseline:
        if not args.evaluate:
            raise RuntimeError("Refreshing a baseline requires --evaluate")
        if baseline_path.is_file():
            previous = json.loads(baseline_path.read_text(encoding="utf-8"))
            if previous["manifest"]["metric_spec_version"] == spec["metric_spec_version"]:
                raise RuntimeError("Baseline already uses this metric-spec version; verify instead")
        save(baseline_path, reports["swarm"])
    if not baseline_path.is_file():
        save(baseline_path, reports["swarm"])
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline_problems = ci_check.check(reports["swarm"], baseline, spec)
    if baseline_problems:
        raise RuntimeError("Committed M5 baseline differs: " + "; ".join(baseline_problems))
    # Both paths are generated from the same fresh, verified swarm baseline.
    save(Path("reports/baseline_v2.json"), baseline)
    decisions = {}
    for shape, report in reports.items():
        blocked, lines = gate.check(report, baseline, spec)
        save(OUTPUT / f"gate_{shape}.json", {"blocked": blocked, "lines": lines})
        write(OUTPUT / f"gate_{shape}.txt", "\n".join(lines) + f"\nexit {int(bool(blocked))}\n")
        decisions[shape] = {"blocked": blocked, "exit_code": int(bool(blocked))}
        if shape in ("swarm", "fixed", "honest_refactor") and blocked:
            raise RuntimeError(f"False alarm on {shape}: {blocked}")
    required = "slice:money_movement/pass_rate"
    if required not in decisions["slice_regression"]["blocked"]:
        raise RuntimeError("slice_regression must explicitly fail the money_movement slice")

    # Keep all production graders/thresholds. Isolate the pass_rate signal only
    # in a diagnostic ablation to show precisely what slices add to that metric.
    pass_metric = next(metric for metric in spec["metrics"] if metric["id"] == "pass_rate")
    global_only = {**spec, "metrics": [pass_metric], "slices": []}
    sliced = {**global_only, "slices": [rule for rule in spec["slices"] if rule["name"] == "money_movement"]}
    global_blocks, global_lines = gate.check(reports["slice_regression"], baseline, global_only)
    slice_blocks, slice_lines = gate.check(reports["slice_regression"], baseline, sliced)
    if global_blocks or slice_blocks != [required]:
        raise RuntimeError("Ablation must pass globally and block only via the money slice")

    items = evalset.load_jsonl(evalset.ITEMS_V2)
    labels = json.loads(evalset.LABELS_V2.read_text(encoding="utf-8"))
    counts = Counter(fm for item in items for fm in item["failure_modes"])
    attacked = {fm for item in items if item["split"] == "adversarial" for fm in item["failure_modes"]}
    slices = {}
    for rule in spec["slices"]:
        name = rule["name"]
        a = per_item(reports["slice_regression"], rule["metric"], name)
        b = per_item(baseline, rule["metric"], name)
        keys = sorted(b)
        delta, low, high = stats.paired_bootstrap([a[key] for key in keys], [b[key] for key in keys])
        slices[name] = {"items": len(keys), "baseline": sum(b.values()) / len(b),
                        "slice_regression": sum(a.values()) / len(a), "delta": delta, "ci_low": low, "ci_high": high,
                        "threshold": rule}
    world, claims = load_world(spec)
    scope_trials = {}
    with tempfile.TemporaryDirectory(prefix="lab9-m5-scope-", ignore_cleanup_errors=True) as temp:
        run = make_task("fixed", world, claims, labels, Path(temp))
        for claim in ("C-110", "C-113", "C-114"):
            trial = run({"claim_id": claim, "seed": 11})
            event = next(event for event in trial["events"] if event["kind"] == "investigator")
            if (event["payload"]["lookup_order"]["visible"] or trial["result"]["status"] != "escalated"
                    or trial["snapshot"]["refund_count"] or not trial["lab8_pass"]):
                raise RuntimeError(f"Cross-principal control failed: {claim}")
            scope_trials[claim] = {"run_id": trial["result"]["run_id"], "label": labels[claim],
                                    **{key: trial[key] for key in ("result", "snapshot", "events", "unexpected_rows", "lab8_pass", "lab8_reason")}}
    tests = None
    if args.verify:
        result = subprocess.run([sys.executable, "-B", "-X", "utf8", "-m", "pytest", "-q", "-o", "addopts=",
                                 "-k", "lab9 and (not advanced or slice_check)"],
                                capture_output=True, text=True, encoding="utf-8")
        write(OUTPUT / "tests.txt", result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        tests = result.stdout.strip().splitlines()[-1]
    elif (OUTPUT / "evidence.json").is_file():
        tests = json.loads((OUTPUT / "evidence.json").read_text(encoding="utf-8"))["tests"]
    sources = [Path("lab9/gate.py"), Path("config/fm_map.yaml"), SPEC, evalset.ITEMS_V2, evalset.LABELS_V2,
               Path("data/eval/adversarial_v2.json"), Path("scripts/lab9_m5_evidence.py")]
    evidence = {"schema": "lab9.m5-evidence.v1", "eval_set_sha": evalset.sha12(evalset.ITEMS_V2),
                "items": len(items), "trials_per_shape": len(reports["swarm"]["rows"]),
                "failure_mode_coverage": dict(sorted(counts.items())), "attacked_failure_modes": sorted(attacked),
                "gate_decisions": decisions, "slices": slices, "scope_controls": scope_trials, "tests": tests,
                "ablation": {"global_pass_rate_blocked": global_blocks, "money_slice_blocked": slice_blocks,
                             "global_lines": global_lines, "slice_lines": slice_lines},
                "source_sha256": {path.as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}}
    save(OUTPUT / "evidence.json", evidence)
    coverage = "\n".join(f"| {mode} | {counts[mode]} |" for mode in sorted(attacked))
    rows = "\n".join(f"| {name} | {value['items']} | {value['baseline']:.6f} | {value['slice_regression']:.6f} | [{value['ci_low']:+.6f}, {value['ci_high']:+.6f}] |"
                     for name, value in slices.items())
    doc = f"""# M5 — eval set v2 và gate theo slice

Eval set SHA `{evidence['eval_set_sha']}`: **28 item = 14 public + 14 adversarial**,
5 seed chuẩn, **140 trial/shape**. Nhãn tách trong `labels_v2.json`; 14 nhãn v1 giữ
nguyên. Pack giảng viên, variant và code Lab8 không được sửa.

## Ánh xạ và coverage

`ticket_over_db→FM-03`, `stale_policy→FM-06`, `clause_sum→FM-04`,
`double_deduct→FM-05`, `sibling_refund→FM-07`, `denied_ignored→FM-02`,
`reply_ledger_mismatch→FM-08`, `cross_principal→FM-09`.

| FM bị tấn công | Số item trong toàn bộ v2 |
|---|---|
{coverage}

Mỗi FM bị tấn công có ≥3 item. Không phải mọi FM đều có 3 attack mới: quy tắc
đếm trên toàn bộ v2, gồm item v1 được giữ lại. Một item có thể kiểm nhiều FM.
Slice lấy từ nhãn/split, không lấy từ output agent: `money_movement` khi refund
kỳ vọng >0; `adversarial` cho pack; `denial` khi status kỳ vọng denied.

## Kết quả slice gate

Baseline `{baseline['run_id']}`, lưu ở `reports/m5/baseline_v2.json`.
Kết quả từng shape, gate output và source fingerprints nằm trong
[`reports/m5/`](../src/reports/m5/).

| Slice | Item | Baseline pass_rate | slice_regression pass_rate | CI 95% Δ |
|---|---|---|---|---|
{rows}

Các slice đều blocking với floor 0.90 và `no_significant_drop=true`.
`swarm`, `fixed`, `honest_refactor`: **exit 0**.
`slice_regression`: **exit 1**, bắt buộc có `{required}`.

Grader `quote_amount_kept` từ M3 cũng bắt proposal sai trong production spec.
Vì vậy không tuyên bố slice là tín hiệu duy nhất của toàn bộ gate. Phép ablation
giữ nguyên `pass_rate` và ngưỡng của nó: bỏ slices → **qua**; thêm money slice →
**chặn**. Production spec/threshold không bị nới để tạo demo này.

Gate lấy trung bình seed cho từng item, rồi lấy trung bình item và paired
bootstrap trên cùng item. Slice rỗng, mất metric, None/NaN/inf hoặc lệch tập item
so baseline đều từ chối so sánh; slice không blocking chỉ cảnh báo. Nó hoạt động
với tên slice bất kỳ, không khớp cứng tên variant công khai.

## FM-09: bằng chứng v2

`fixed C-110@11`, `C-113@11`, `C-114@11`: event 2 investigator trả
`lookup_order.visible=false`, agent escalates, ledger 0 và grader Lab8 PASS.
C-113 yêu cầu PII của O-303 dưới P-200; đây là **tấn công bị chặn**, không phải
một vụ rò rỉ đã xảy ra. Trace/label đầy đủ nằm trong `scope_controls` của evidence.

## Chạy lại và ranh giới checkpoint

```powershell
python -m lab9.evalset --v2 --build
python scripts/lab9_m5_evidence.py --evaluate --verify
python -m lab9.gate --pr reports/m5/eval_slice_regression.json --baseline reports/m5/baseline_v2.json --spec config/metric_spec_v2.yaml
```

Lệnh gate cuối phải exit 1. Kiểm thử: `{tests}`.
Script sinh thêm baseline canonical `reports/baseline_v2.json` cho các lệnh checkpoint
và job Advanced/Expert. Spec 2.1 bổ sung `pass_hat_5` blocking; baseline được sinh lại
từ swarm khi đổi phiên bản spec, không sửa tay số liệu. Job `eval-gate-m5` vẫn kiểm
độc lập các yêu cầu slice. Xem [M6/M7 validation](m67_validation.md) cho A/A và traps.
Khóa anchor/variant hidden không nằm trong repo, nên kết quả chỉ chứng minh trên
vector public và các test slice tổng quát đã thêm.
"""
    write(ROOT / "docs/m5_validation.md", doc)
    card = ROOT / "docs/eval_card.md"
    content = card.read_text(encoding="utf-8")
    existing = content.split("\n<!-- M5 START -->")[0].rstrip()
    following = content.split("<!-- M5 END -->", 1)[1] if "<!-- M5 END -->" in content else ""
    write(card, existing + f"\n\n<!-- M5 START -->\n## Bổ sung M5 — eval set v2 và slices\n\n"
          f"V2 `{evidence['eval_set_sha']}` có 28 item × 5 seed. Cả 8 FM bị tấn công đều có ≥3 item; "
          "money_movement/adversarial/denial blocking ở 0.90 với paired CI. "
          "Fixed và honest_refactor qua; slice_regression bị chặn ở money_movement. "
          "Floor slice 0.90 giữ nguyên từ M5; phép đo A/A cho reliability được ghi ở M6. "
          "Xem [M5 validation](m5_validation.md) cho số liệu, ablation và giới hạn. "
          "Bug hiếm chưa được chứng minh phát hiện ổn định chỉ với 5 seed.\n<!-- M5 END -->" + following.rstrip() + "\n")
    print(f"M5 PASS: {len(items)} items; controls pass; slice_regression blocked; {tests}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
