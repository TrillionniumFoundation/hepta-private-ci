"""Render audited V8 development outcomes; no optimization or data selection."""

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+"\n")


def render(workspace, audit_directory, grid, output):
    workspace, audit_directory, grid, output = map(Path, (workspace, audit_directory, grid, output))
    audit = read(audit_directory/"audit.json")
    cases = read(audit_directory/"case-census.json")
    infra_path = workspace/"pft-development-v8/grid-infrastructure-accounting.json"
    infra, run = read(infra_path), read(grid/"run.json")
    assert audit["status"] == infra["status"] == "PASS"
    assert len(cases) == audit["primary_records"] == 1152
    assert sha(audit_directory/"case-census.json") == audit["case_census_sha256"]
    assert sha(audit_directory/"audit.json") == infra["independent_full_retry_audit_sha256"]
    assert sha(grid/"development_seal.json") == audit["development_seal_sha256"] == infra["complete_retry_seal_sha256"]
    assert not output.exists() and output not in grid.parents and grid not in output.parents
    lookup = {(r["index"], r["fit_id"], r["policy"]): r for r in cases}
    assert len(lookup) == 1152
    parity = []
    for row in audit["full_reference_parity"]:
        pair = [lookup[row["configuration_index"], row["fit_id"], p]
            for p in ("future_field_h8", "full_h8")]
        complete = all(r["status"] == "completed" and r["completed_steps"] == 32 for r in pair)
        error_available = "maximum_action_absolute_error" in row and "maximum_full_state_absolute_error" in row
        numeric_ok = error_available and max(row["maximum_action_absolute_error"],
            row["maximum_full_state_absolute_error"]) <= row["absolute_tolerance"]
        assert row["passed"] == (complete and numeric_ok)
        parity.append({**row, "both_completed_32": complete, "numeric_comparison_available": error_available,
            "numeric_agreement": bool(numeric_ok), "steps": [r["completed_steps"] for r in pair]})
    assert len(parity) == 288
    config_rows = []
    for row in audit["configuration_table"]:
        index = row["index"]
        groups = [r for r in audit["group_rows"] if r["index"] == index]
        comparisons = [v for g in groups for v in g["future"]]
        available = [g for g in groups if g["available"]]
        pairs = [r for r in parity if r["configuration_index"] == index]
        failures = {"policy_outputs_not_completed_32": 96-row["complete_primary"],
            "actual_error_records": row["actual_error_records"],
            "full_field_pairs_not_completed_32": sum(not r["both_completed_32"] for r in pairs),
            "numeric_parity_mismatches": sum(r["numeric_comparison_available"] and not r["numeric_agreement"] for r in pairs),
            "groups_unavailable_for_32step_comparison": 8-len(available),
            "available_cpu_groups_above_3": sum(g["candidate_h1_cpu_ratio"] > 3 for g in available),
            "available_future_contrasts_above_minus006": sum(v["mean_difference"] > -.006 for v in comparisons),
            "future_contrasts_unavailable": 16-len(comparisons),
            "available_old_groups_above_minus020": sum(g["old_mean_difference"] > -.020 for g in available),
            "old_groups_unavailable": 8-len(available)}
        config_rows.append({**row, "criterion_failures": failures,
            "future_contrasts_evaluated": len(comparisons), "old_groups_evaluated": len(available),
            "complete_full_field_pairs": sum(r["both_completed_32"] for r in pairs)})
    selected = audit["selection"]["selected_index"]
    selected_groups = [g for g in audit["group_rows"] if g["index"] == selected]
    stopped = [{k:r[k] for k in ("index", "fit_id", "policy", "completed_steps", "status", "actual_errors")}
        for r in cases if r["status"] != "completed" or r["completed_steps"] != 32]
    statuses = {p:dict(Counter(r["status"] for r in cases if r["policy"] == p))
        for p in sorted({r["policy"] for r in cases})}
    parity_summary = {}
    for name, rows in (("all_registered", parity), ("completed32", [r for r in parity if r["both_completed_32"]]),
            ("stopped_prefixes", [r for r in parity if not r["both_completed_32"]])):
        comparable = [r for r in rows if r["numeric_comparison_available"]]
        parity_summary[name] = {"pairs": len(rows), "numerically_comparable": len(comparable),
            "numerically_agreeing": sum(r["numeric_agreement"] for r in comparable),
            "maximum_action_absolute_error": max((r["maximum_action_absolute_error"] for r in comparable), default=None),
            "maximum_full_state_absolute_error": max((r["maximum_full_state_absolute_error"] for r in comparable), default=None)}
    summary = {"schema": "hepta.audited-development-grid-summary.v8", "status": "PASS",
        "source": {"audit_sha256": sha(audit_directory/"audit.json"), "case_census_sha256": audit["case_census_sha256"],
            "infrastructure_accounting_sha256": sha(infra_path), "development_seal_sha256": audit["development_seal_sha256"],
            "execution_source_commit": audit["executed_source_commit"], "execution_source_sha256": audit["executed_source_sha256"],
            "protocol_sha256": audit["protocol_sha256"], "summarizer_sha256": sha(__file__)},
        "registered_outputs": 1152, "actual_updates_replayed": audit["actual_updates_replayed"],
        "policy_statuses": statuses, "stopped_cases": stopped, "configurations": config_rows,
        "all96_group_rows": audit["group_rows"], "selected_eight_groups": selected_groups,
        "selection": audit["selection"], "parity": parity_summary,
        "maximum_committed_old_panel_excess": max(r["maximum_empirical_old_panel_excess"] for r in cases),
        "maximum_source_metric_selection_error": audit["source_metric_and_selection_maximum_absolute_error"],
        "portfolio_workload": audit["portfolio_workload"],
        "costs": {"all_policy_call_cpu_ns": run["all_policy_call_cpu_ns"],
            "shared_preparation": run["shared_preparation"], "producer_recorded_cpu_ns": run["cpu_ns"],
            "producer_recorded_wall_ns": run["wall_ns"], "independent_audit_cpu_ns": audit["cpu_ns"],
            "two_producer_attempts_cpu_lower_bound_ns": infra["producer_recorded_cpu_lower_bound_across_attempts_ns"],
            "infrastructure_pause_ns": infra["same_process_suspension_ns"], "cost_exact_known": False,
            "scope": infra["recorded_interval_scope"]},
        "all46_original_retry_pairs_bit_equal": not any(infra[k] for k in
            ("shared_array_changes", "shared_receipt_changes", "shared_state_hash_changes", "shared_status_or_step_changes")),
        "new_confirmation_selected": False, "scientific_acceptance": False}
    output.mkdir(parents=True)
    write(output/"summary.json", summary)
    original = (audit_directory/"case-census.json").read_bytes()
    compressed = gzip.compress(original, compresslevel=9, mtime=0)
    assert gzip.decompress(compressed) == original
    (output/"case-census.json.gz").write_bytes(compressed)
    write(output/"compressed-census-receipt.json", {"logical_sha256": hashlib.sha256(original).hexdigest(),
        "logical_bytes": len(original), "compressed_sha256": hashlib.sha256(compressed).hexdigest(),
        "compressed_bytes": len(compressed), "rows": len(cases), "roundtrip_verified": True})
    lines = ["# V8 完整开发网格：独立审计与失败项", "",
        "**1152/1152 个注册输出已保留，独立完整性与计算审计 PASS；没有配置通过预先冻结的确认实验开发筛选。** "
        "六个配置满足完成率、数值等价和成本的基础资格，但 plausible 集合为空。配置 09 仅为冻结规则选出的诊断结果，"
        "不触发新确认样本，也不产生科学准入。", "",
        "## 1. 固定设计与完整分母", "",
        "24 个历史 fit（V5/V6 × AG News/DBpedia × linear/gated × 三个种子），12 个共有配置（old 权重 0/0.25/0.5 × "
        "提交步长 1/2/4/8），每个 fit/config 实际执行四个策略。每条注册 32 个 Adam 更新；动作盒、零 old 松弛和 "
        "single-ray→joint 固定组合对所有策略相同。所有来源及原评价角色已明确转为 development。", "",
        "| 策略 | 注册 | 完成 32 步 | 拒绝停止 | 实际异常 |", "|---|---:|---:|---:|---:|"]
    for p,counts in statuses.items():
        lines.append(f"| {p} | 288 | {counts.get('completed',0)} | {counts.get('not_executed_rejected',0)} | 0 |")
    lines += ["", "26 个停止全部来自历史 V5 DBpedia gated，位于配置 00（9）、01（7）、02（9）、06（1）；"
        "实际停止步数为 24–29。它们的完整已执行前缀、终态、付费失败尝试和历史来源分数都保留；"
        "不会进入要求 32 步的组间比较。全部 26 条精确 ID 见 summary.json 的 stopped_cases。", "",
        "## 2. 每个配置的未通过项", "",
        "CPU 为候选/H1 整策略调用 CPU 比率；每组为同一来源版本、任务、头型下三个种子的 CPU 之和。"
        "future 要求全部 16 个配对均值 ≤ −0.006；old 要求全部 8 个相对原 warmup 均值 ≤ −0.020。"
        "这些是开发进入筛选，不是新的统计显著性检验。不可用组保持缺失，不能算通过。", "",
        "| 配置 | old 权重 | 提交步长 | 完成/96 | 完整 Full/field 对/24 | CPU 最大比 | CPU 超 3 组 | future 达标/可比（注册16） | old 达标/可比（注册8） | 基础资格 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for r in config_rows:
        f=r["criterion_failures"];cfg=r["configuration"]
        lines.append(f"| {r['index']:02d} | {cfg['old_weight']:g} | {cfg['commit_stride']} | {r['complete_primary']} | "
            f"{r['complete_full_field_pairs']} | {r['cpu_ratio_maximum']:.6f} | {f['available_cpu_groups_above_3']} | "
            f"{r['future_mean_thresholds_met']}/{r['future_contrasts_evaluated']} | {r['old_mean_thresholds_met']}/{r['old_groups_evaluated']} | "
            f"{'满足' if r['eligible'] else '未满足'} |")
    lines += ["", "00/01/02/06 有未完成策略；00/04/08 还存在超过 3 倍的可比 CPU 组。"
        "03/05/07/09/10/11 满足基础资格。全部 12 个配置均未满足 future 与 old 的全组开发要求；"
        "单组改善或低成本不能替代这个交集。每项失败及不可用数量完整保存在 summary.json。", "",
        "## 3. 配置 09 的全部八组", "",
        "配置 09 为 old 权重 0.5、预测窗口 H8、提交步长 2。表中差值为候选减基线，NLL 越低越好；"
        "各组使用原 512 个有序 future 来源和 512 个 old 来源、三个配对种子。这里是已使用过标签上的开发均值。", "",
        "| 版本 | 任务 | 头 | future − H1 | future − Loss2 | old − warmup | CPU/H1 |",
        "|---|---|---|---:|---:|---:|---:|"]
    for g in selected_groups:
        values={v["baseline"]:v["mean_difference"] for v in g["future"]}
        lines.append(f"| {g['version']} | {g['task']} | {g['head']} | {values['myopic_h1']:+.9f} | "
            f"{values['loss2_h8']:+.9f} | {g['old_mean_difference']:+.9f} | {g['candidate_h1_cpu_ratio']:.6f} |")
    lines += ["", "配置 09 的 future 仅 2/16 达到 −0.006，old 仅 6/8 达到 −0.020。V6 DBpedia 的两个头对两条基线的 "
        "future 差值均为正；这四个反向结果原样保留。八个 CPU 比率均 ≤ 3，因此此配置的不足不能归结为成本或未完成。", "",
        "## 4. 等价、保留和恢复的实际范围", "",
        f"独立实际引擎回放 {audit['actual_updates_replayed']:,} 个已提交更新，核验 {audit['canonical_controller_preimages_checked']:,} 个 "
        "canonical controller 预像和全部状态/receipt 链。配置 09 的 96 个策略槽均从 0/16/17/32 完整 checkpoint 实际加载，"
        "并以原已记录动作回放后缀。这个检查不重新规划未来策略。逐来源分数与选择计算的最大绝对误差为 0。", "",
        f"280/280 对完整 Full/field 轨迹在原 1e−9 容差内一致：动作最大误差 {parity_summary['completed32']['maximum_action_absolute_error']:.12g}，"
        f"完整连续状态最大误差 {parity_summary['completed32']['maximum_full_state_absolute_error']:.12g}。另外 8 对在相同长度停止；"
        f"其已执行前缀最大动作误差 {parity_summary['stopped_prefixes']['maximum_action_absolute_error']:.12g}、状态误差 "
        f"{parity_summary['stopped_prefixes']['maximum_full_state_absolute_error']:.12g}。它们缺少 32 步完成资格，并非观察到了数值等价失败。", "",
        f"全部已提交更新的四个原 old 面板均满足零松弛，最大 excess 为 {summary['maximum_committed_old_panel_excess']:.12g}。"
        "这是反复用于搜索和选择的经验面板约束，不是独立总体保留证书，也不认证未提交的预测尾部。", "",
        "固定组合记录 22,123 次调用、22,735 次过滤器尝试和 612 次 joint fallback。原记录合计 1,023,384 次面板查询、"
        "67,671 次前瞻优化器更新；这些工作量为独立加总的原始账目，并非对整网格新增的逐 oracle 观测。"
        "本次后置审计没有重新调用规划器或安全搜索，也没有独立重建每个 forecast 的全部系数。", "",
        "## 5. 两次基础设施执行与成本", "",
        "第一次执行因磁盘写满中断，原 238 个文件（8,307,860 字节）、46 个完整结果、47 号部分输出与日志均保持不变。"
        "其中 39 条完成、7 条拒绝；重试完整执行全部 1152 槽，没有选择性重跑。原 46 条与重试对应的动作、终态向量、"
        "512-source 分数数组、receipt、全状态哈希及状态/步数全部逐位相同。", "",
        f"完整重试 producer 已记录 CPU 区间 {run['cpu_ns']/1e9:.9f} 秒，其中策略整调用 {run['all_policy_call_cpu_ns']/1e9:.9f} 秒，"
        f"共享准备 {run['shared_preparation']['cpu_ns']/1e9:.9f} 秒；最后 run.json/seal 写入在该计时区间之外。"
        f"独立完整审计另计 {audit['cpu_ns']/1e9:.9f} 秒。第一次可恢复 CPU 下界为 57.251806899 秒；两次 producer "
        f"合计下界 {infra['producer_recorded_cpu_lower_bound_across_attempts_ns']/1e9:.9f} 秒，不能称精确总成本。", "",
        f"重试沿用同一 PID 暂停/恢复，暂停 {infra['same_process_suspension_ns']/1e9:.9f} 秒；原 "
        f"{run['wall_ns']/1e9:.9f} 秒 wall 包含该暂停。所有原 CPU/wall 记录均未修改，未把后处理、暂停或失败尝试隐藏进策略收益。", "",
        "## 6. 复核入口与身份", "",
        "机器可读逐组与逐停止数据在 [summary.json](./summary.json)；全部 1152 条 canonical/controller 摘要在 "
        "[case-census.json.gz](./case-census.json.gz)，解压哈希见 compressed-census-receipt.json。独立完整 audit.json、"
        "qualification.json 与基础设施回执由同一发布清单绑定。", "",
        f"执行 commit：`{audit['executed_source_commit']}`；117-source canonical SHA：`{audit['executed_source_sha256']}`。", "",
        f"协议 SHA：`{audit['protocol_sha256']}`；完整 seal SHA：`{audit['development_seal_sha256']}`。", "",
        f"独立 audit SHA：`{sha(audit_directory/'audit.json')}`；基础设施账 SHA：`{sha(infra_path)}`。", "",
        "原科学要求（独立来源、12 项 family、future 上界 < −0.001、old 上界 ≤ 0、成本 ≤ 3 与完整执行）没有改变。"
        "这一轮未抽取、编码或打开新确认样本；scientific_acceptance 仍为 false。", ""]
    (output/"GRID_DEVELOPMENT_REPORT.md").write_text("\n".join(lines))
    return {"status": "PASS", "summary_sha256": sha(output/"summary.json"),
        "report_sha256": sha(output/"GRID_DEVELOPMENT_REPORT.md"), "selection": summary["selection"]}


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("workspace", "audit-directory", "grid", "output"):
        parser.add_argument("--"+name, required=True)
    print(json.dumps(render(**vars(parser.parse_args())), ensure_ascii=False))
