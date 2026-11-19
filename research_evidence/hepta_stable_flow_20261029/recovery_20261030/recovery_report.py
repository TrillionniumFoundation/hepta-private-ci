"""Build a separate report from exact primary recovery and new appendix replays.

This wrapper never trains, selects, scores, benchmarks or edits frozen sources.
It preserves report002 and does not claim recovery of its missing input set.
"""

import argparse
import html
import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path("research_evidence/hepta_stable_flow_20261029")
RECOVERY = EVIDENCE / "recovery_20261030"
PRIMARY_SHA = "062c049ab04abe6ca1a12f1cf2f67b88056c74dcde60cc212fa38bc6c22de992"
ORIGINAL_RECEIPT_SHA = (
    "e531f9be028d52a20e9c92e987557c70b8bb4c7ed2cabd3426bb7462a2436c8a"
)
ORIGINAL_HTML_SHA = "1c712e7fa11dd67c95b0fb5a373962d057a92b96fe6cb8f08a948c7358c67fa5"
ORIGINAL_COMMIT = "5ada4d04f905d713dd82f76189e05a739ee8b756"
BASE = "https://github.com/TrillionniumFoundation/hepta-private-ci/blob/"


def bind_recovery(report, inputs):
    original = inputs.json(
        EVIDENCE / "report002/report_receipt.json", ORIGINAL_RECEIPT_SHA
    )
    inputs.read(
        EVIDENCE / "report002/Hepta_New_Scientific_Report_20261029.html",
        ORIGINAL_HTML_SHA,
        "preserved-original-report",
    )
    contract = inputs.json(RECOVERY / "recovery_contract.json")
    for path, digest in contract["bindings"].items():
        inputs.read(path, digest, "original-recovery-contract-binding")
    for row in original["source"]:
        inputs.read(row["path"], row["sha256"], "frozen-report-generator")
    primary = inputs.json(RECOVERY / "primary_reconstruction_receipt.json")
    report.require(
        primary["all_original_primary_digests_reproduced"]
        and primary["original_inputs_unchanged"]
        and not primary["training_or_selection_executed"],
        "Primary recovery was not exact or changed the frozen experiment",
    )
    rows = [
        row
        for row in original["consumed_inputs"]
        if "/formal_run001/predictions/" in row["path"]
        or row["path"].endswith("/formal_run001/results.json")
    ]
    report.require(len(rows) == 61, "Expected exactly 61 original primary bindings")
    for row in rows:
        raw = inputs.read(row["path"], row["sha256"], "exact-original-primary-bytes")
        report.require(len(raw) == row["bytes"], "Original primary length mismatch")
    inputs.read(report.STUDY / "results.json", PRIMARY_SHA)
    log_proof = inputs.json(RECOVERY / "selection_log_reconstruction.json")
    report.require(
        log_proof["classification"] == "digest_verified_deterministic_reconstruction"
        and not log_proof["selection_reexecuted"]
        and not log_proof["timing_regenerated"],
        "Selection log recovery lacks an exact-byte contract",
    )
    for row in log_proof["bindings"] + log_proof["restored"]:
        inputs.read(row["path"], row["sha256"], "selection-log-recovery-binding")
    for name in ("object_recovery_inventory.json", "input_availability_initial.json"):
        inputs.json(RECOVERY / name)
    for path in sorted((ROOT / RECOVERY).glob("*.py")):
        inputs.read(path.relative_to(ROOT), role="recovery-execution-source")
    inputs.read(Path(__file__).relative_to(ROOT), role="recovery-report-generator")
    for current, original_name in (
        (report.NUMERICS, "trained_numerics_appendix001"),
        (report.RUNTIME, "inference_cost_appendix001"),
    ):
        expected = contract["bindings"][str(EVIDENCE / original_name / "protocol.json")]
        inputs.read(current / "protocol.json", expected, "unchanged-original-protocol")
        for path in sorted((ROOT / current / "replay_execution").rglob("*")):
            if path.is_file():
                inputs.read(path.relative_to(ROOT), role="new-replay-execution-receipt")
    return {
        "schema": "hepta-recovery-report-provenance-v1",
        "primary_classification": "digest_verified_deterministic_reconstruction",
        "primary_exact_artifacts": len(rows),
        "primary_results_sha256": PRIMARY_SHA,
        "numerics_classification": "new_execution_on_same_checkpoints_and_protocol",
        "runtime_classification": "new_measurement_not_original_clock_recovery",
        "copied_protocols_are_original_contracts_not_new_blind_preregistrations": True,
        "training_or_model_selection_reexecuted": False,
        "original_report002_html_preserved": True,
        "original_report002_complete_input_set_restored": False,
        "original_complete_archive_recovered": False,
        "all_research_blockers_closed": False,
        "contract": contract,
        "primary_reconstruction": primary,
        "selection_log_reconstruction": log_proof,
    }


def recovery_html(report, data, images):
    page = report.render(data, images)
    provenance = data["reconstruction_provenance"]
    original_url = (
        BASE
        + ORIGINAL_COMMIT
        + "/"
        + str(EVIDENCE)
        + "/report002/Hepta_New_Scientific_Report_20261029.html"
    )
    archive = provenance["contract"]["original_complete_archive"]
    panel = f"""<section id="recovery-provenance"><h2>恢复报告：原始字节与新重放明确区分</h2>
<p class="notice"><strong>本页是 report003_recovery，不是旧报告或原始完整归档的补写。</strong>
临时环境在公开上传途中被重置。训练、300 个检查点和封存选模身份来自此前已公开的原始文件；
没有重新训练或重新选模。主测试的 60 份预测与 results.json 共
{provenance["primary_exact_artifacts"]} 个文件通过原始 SHA256 和字节长度逐一核对后精确恢复。</p>
<p><strong>下方数值附录与推理计时属于新的固定检查点重放。</strong>
复用原先注册的检查点、数据、阈值与计时协议；复制原协议不等于在看到旧结果后建立新的盲注册。
数值表和 CPU/wall 原始计时显示本次真实执行的结果，不声称恢复了原先的计时时钟。
训练与原验证选择成本保留原回执；评分恢复与数值、推理重放成本按新执行解释。</p>
<p>原 <a href="{html.escape(original_url, quote=True)}">report002 可读 HTML</a>及原输入回执保持原字节。
原 report002 的全部输入尚未恢复，原完整归档
<code>{html.escape(archive["sha256"])}</code>（{archive["bytes"]:,} 字节）也未恢复。
本报告不宣称所有科学门槛通过、全部 blocker 已闭合，或证明跨架构及多模态优势。</p>
<p>本页的报告摘要和新回执只绑定当前实际可读的原文件、精确重建文件及新重放文件。
生成时间为 {html.escape(data["generated_utc"])}；独立审计和远端发行验证在此后分别执行。</p></section>"""
    changes = {
        "Hepta：共享自由边界 Call–Put 网络的新执行科学报告": "Hepta：固定检查点恢复与重放科学报告",
        "HEPTA · NEW EXECUTION · 2026-10-29": "HEPTA · RECOVERY AND REPLAY · 2026-10-30 UTC",
        "新源码与新检查点的科学报告。": "保留原训练与选模身份的恢复报告。",
        "这是一轮<strong>新执行的受控小模型研究</strong>": "本页恢复并复核一轮<strong>已完成的受控小模型研究</strong>",
        "所有正式结果与附录已具备才生成此报告。": "精确恢复的原主结果与本次重放附录全部具备后才生成此报告。",
        "4. 数值资格：精度、离散化和参照分别报告": "4. 本次数值重放：精度、离散化和参照分别报告",
        "5. 推理成本：全部 20 个别名、两种 batch": "5. 本次推理重测：全部 20 个别名、两种 batch",
        "选择和测试评分子进程 CPU": "原选择与本次评分恢复子进程 CPU",
        "按 phase_execution 回执计量": "分别使用原选择回执与新评分恢复回执；不是旧评分时钟",
        "[N] trained_numerics_appendix001/protocol.json": "[N] trained_numerics_replay_20261030/protocol.json",
        "[R] inference_cost_appendix001/protocol.json": "[R] inference_cost_replay_20261030/protocol.json",
    }
    for old, new in changes.items():
        report.require(page.count(old) == 1, "Presentation source changed: " + old)
        page = page.replace(old, new, 1)
    start_marker = "<p>用户已明确授权本轮新工作公开发布到"
    end_marker = "<p>本 HTML、图表、"
    report.require(
        page.count(start_marker) == page.count(end_marker) == 1,
        "Original release section changed",
    )
    start, end = page.index(start_marker), page.index(end_marker)
    replacement = f"""<p>本次恢复证据使用独立的发行身份，不能沿用未恢复的原完整包身份。
当前公开分支的 <a href="{BASE}research/hcsn-callput-rebuild-20261028/HEPTA_RESEARCH_STATUS.md">
HEPTA_RESEARCH_STATUS.md</a> 提供实际发行清单和验证入口。
最终归档大小、分片、SHA256 和远端读回结果以该次实际发行回执为准；本报告不预填或提前宣布成功。</p>
"""
    page = page[:start] + replacement + page[end:]
    report.require(page.count("<main>") == 1, "Unexpected HTML document structure")
    return page.replace("<main>", "<main>" + panel, 1)


def run(output):
    sys.path.insert(0, str(ROOT))
    report = importlib.import_module("experiments.call_put_stable_flow_analysis.report")
    output = output.resolve()
    report.require(
        output.parent == ROOT / EVIDENCE
        and output.name.startswith("report003_recovery")
        and not output.exists(),
        "Use a fresh report003_recovery directory; preserve every existing report",
    )
    report.NUMERICS = EVIDENCE / "trained_numerics_replay_20261030"
    report.RUNTIME = EVIDENCE / "inference_cost_replay_20261030"
    report.prerequisites(ROOT)
    prior = report.Inputs(ROOT)
    provenance = bind_recovery(report, prior)
    inputs, data = report.load(ROOT)
    for row in prior.manifest():
        for role in row["roles"]:
            inputs.read(row["path"], row["sha256"], role)
    data["version"] = "hepta-recovery-scientific-report-20261030-v1"
    data["reconstruction_provenance"] = provenance
    output.mkdir(exist_ok=False)
    images = report.figures(data, output / "figures")
    inputs.unchanged()
    data["consumed_inputs"] = inputs.manifest()
    page = recovery_html(report, data, images)
    report.require(
        "data:image/png;base64," in page and "<script src=" not in page,
        "Recovery report is not self-contained",
    )
    name = "Hepta_Recovery_Scientific_Report_20261030.html"
    (output / name).write_text(page, encoding="utf-8")
    report.write_json(output / "report_summary.json", data)
    outputs = [
        {
            "path": str(p.relative_to(output)),
            "bytes": p.stat().st_size,
            "sha256": report.sha(p.read_bytes()),
        }
        for p in sorted(output.rglob("*"))
        if p.is_file()
    ]
    report.write_json(
        output / "report_receipt.json",
        {
            "schema": "hepta-recovery-scientific-report-input-output-binding-v1",
            "generated_utc": data["generated_utc"],
            "environment": data["environment"],
            "consumed_inputs": inputs.manifest(),
            "outputs": outputs,
            "source": [
                r
                for r in inputs.manifest()
                if any("generator" in role for role in r["roles"])
            ],
            "recovery_provenance": {
                k: v
                for k, v in provenance.items()
                if k
                not in (
                    "contract",
                    "primary_reconstruction",
                    "selection_log_reconstruction",
                )
            },
            "original_report002_receipt_sha256": ORIGINAL_RECEIPT_SHA,
            "no_training_reselection_or_primary_score_changes": True,
            "independent_final_audit_not_yet_asserted": True,
            "all_research_blockers_closed": False,
            "publication_not_yet_asserted": True,
        },
    )
    return {
        "status": "recovery_report_generated_pending_independent_audit",
        "output": str(output),
        "consumed_inputs": len(inputs.records),
        "receipt_sha256": report.sha((output / "report_receipt.json").read_bytes()),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / EVIDENCE / "report003_recovery"
    )
    args = parser.parse_args()
    print(json.dumps(run(args.output), indent=2, ensure_ascii=False))
