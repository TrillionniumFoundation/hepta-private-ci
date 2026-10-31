"""Interpret a frozen aggregate without recomputing effects or changing gates."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from .analysis_audit import digest


GROUPS = ("content", "dynamics", "boundary", "reset", "refractory")
EXTERNAL = ("two_gates", "transformer", "lif_snn")


def findings(report):
    jobs, comparisons = report["job_audit"], report["comparisons"]
    full = [row for row in jobs if row["job"]["arm"] == "value_dual"]
    group_rows = []
    for group in GROUPS:
        rows = [row for row in full if group in row["group_delta"] and group in row["selected_group_delta"]]
        group_rows.append(dict(group=group, jobs=len(rows), expected_jobs=len(full),
            last_changed_positive=sum(row["group_delta"][group]["changed"] > 0 and row["group_delta"][group]["l2"] > 0 for row in rows),
            selected_changed_positive=sum(row["selected_group_delta"][group]["changed"] > 0 and row["selected_group_delta"][group]["l2"] > 0 for row in rows),
            positive_mean_gradient=sum(row["mean_gradient"][group] > 0 for row in rows),
            minimum_selected_delta_l2=min(row["selected_group_delta"][group]["l2"] for row in rows)))
    freezes = []
    for row in jobs:
        if not row["job"]["arm"].startswith("freeze_"):
            continue
        group = row["job"]["arm"].removeprefix("freeze_")
        unchanged = all(row[scope][group]["changed"] == 0 and row[scope][group]["l2"] == 0
                        and row[scope][group]["trainable"] == 0 for scope in ("group_delta", "selected_group_delta"))
        freezes.append(dict(id=row["id"], group=group, unchanged_at_both_checkpoints=unchanged,
                            mean_gradient_zero=row["mean_gradient"][group] == 0))
    cost = [row for row in comparisons if row["qualified_whole_worker_cpu_advantage"]]
    matched = [row for row in comparisons if row["matched_mechanism_accuracy_gain"]]
    effects = [(block["case"], name, row) for block in report["factorial"] if block.get("complete")
               for name in ("main_effects", "interactions") for row in block[name]]
    return dict(full_model_jobs=len(full), joint_groups=group_rows, frozen_jobs=freezes,
        joint_updates_verified=all(row["jobs"] == row["last_changed_positive"] == row["selected_changed_positive"]
                                  == row["positive_mean_gradient"] == len(full) for row in group_rows),
        all_freezes_verified=all(row["unchanged_at_both_checkpoints"] and row["mean_gradient_zero"] for row in freezes),
        qualified_cost_comparisons=cost, qualified_external_cost_comparisons=[r for r in cost if r["baseline"] in EXTERNAL],
        unique_worker_cost_pair_sets=len({(tuple(r["candidate_ids"]), tuple(r["baseline_ids"])) for r in cost}),
        matched_accuracy_gain_comparisons=matched,
        factorial_accuracy_effects=len(effects),
        factorial_accuracy_intervals_excluding_zero=sum(row["accuracy"]["lower"] > 0 or row["accuracy"]["upper"] < 0 for _, _, row in effects),
        factorial_ce_intervals_excluding_zero=sum(row["cross_entropy"]["lower"] > 0 or row["cross_entropy"]["upper"] < 0 for _, _, row in effects),
        scope="Descriptive audit/interpretation of the already frozen aggregate; no thresholds, checkpoints, or predictions changed")


def ci(value, scale=1.):
    return f"{value['mean']*scale:.3f} [{value['lower']*scale:.3f}, {value['upper']*scale:.3f}]"


def interpretation(value):
    lines = ["## 执行后的核心判断", "",
        f"**训练与冻结实现通过了证据检查，但当前实验没有建立边界解析策略或双通道的独立任务收益，也没有建立对外部基线的等质量 CPU 成本优势。** 完整 value_dual 的 {value['full_model_jobs']} 个作业中，五组参数在最后优化状态与验证选择 checkpoint 均有实际变化，平均梯度均为正；{len(value['frozen_jobs'])} 个冻结作业的目标组在两处均未变化，梯度为零。‘联合可训练’与‘该机制提高任务质量’是不同结论。", "",
        f"selective_copy 三个测试长度合计 {value['factorial_accuracy_effects']} 个边界/通道主效应及交互准确率区间中，{value['factorial_accuracy_intervals_excluding_zero']} 个排除零；CE 区间排除零的个数为 {value['factorial_ce_intervals_excluding_zero']}。这支持‘此轮未检出净增益’，不证明所有任务上永远没有增益。", "",
        "### 参数和训练 CPU 均匹配的准确率正收益", "",
        "| 任务/预算 | 对照 | 长度 | 准确率差及95%CI（百分点） | 参数最大差 | 训练CPU最大差 | 完整worker CPU比及95%CI |",
        "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in value["matched_accuracy_gain_comparisons"]:
        c, cpu = row["condition"], row["cost_ratios"]["child_cpu_seconds"]
        lines.append(f"| {c['task']} / {c['training_cpu_budget']}s | {row['baseline']} | {row['case']} | {ci(row['accuracy_delta'],100)} | {max(row['max_allocated_parameter_gap'],row['max_trainable_parameter_gap']):.3%} | {row['max_training_cpu_gap']:.3%} | {cpu['geometric_mean']:.3f} [{cpu['lower']:.3f}, {cpu['upper']:.3f}] |")
    lines += ["", "这几项比较整体架构的任务表现；它们没有单独隔离自由边界或双通道的贡献。训练 CPU 匹配也不等于完整 worker 成本匹配，完整 worker 还包括初始化、验证、checkpoint、测试与推理计量。", "",
        "### 成本资格应如何理解", "",
        f"通过质量非劣及完整 worker CPU 比门槛的 {len(value['qualified_cost_comparisons'])} 项，实际涉及 {value['unique_worker_cost_pair_sets']} 组 worker 成本配对；其中相对 two_gates、Transformer、LIF 的资格数是 **{len(value['qualified_external_cost_comparisons'])}**。", ""]
    for row in value["qualified_cost_comparisons"]:
        cpu = row["cost_ratios"]["child_cpu_seconds"]
        lines.append(f"- {row['condition']['task']} / {row['case']}：{row['candidate']} 相对 {row['baseline']}，CPU 比 {cpu['geometric_mean']:.3f} [{cpu['lower']:.3f}, {cpu['upper']:.3f}]；实际训练 CPU 最大相对差 {row['max_training_cpu_gap']:.3%}。")
    lines += ["", "三个长度可能使用同一组训练作业与同一次完整成本测量，因此不能把这些资格重复解释为独立成本复现。相对冻结边界的内部消融结果也不能转写为优于 Transformer/SNN 的经济性。全部区间仍为未校正多重比较的三 seed 名义区间。", ""]
    return "\n".join(lines)


def render(aggregate):
    aggregate = Path(aggregate)
    output = aggregate.parent
    report = json.loads(aggregate.read_text())
    value = findings(report)
    value.update(aggregate_sha256=digest(aggregate), source_sha256=digest(__file__),
                 generated_at_utc=datetime.now(timezone.utc).isoformat())
    path = output/"AUDIT_FINDINGS.json"
    if path.exists():
        raise FileExistsError("Interpretation evidence may not be overwritten")
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+"\n")
    findings_text = interpretation(value)
    (output/"FINDINGS_ZH.md").write_text(findings_text)
    result = output/"RESULTS_ZH.md"
    original = result.read_text()
    backup = output/"RESULTS_ZH.initial.md"
    if backup.exists():
        raise FileExistsError("Original report already preserved")
    backup.write_text(original)
    marker = "## 判定规则与结论边界"
    result.write_text(original.replace(marker, findings_text+"\n"+marker, 1))
    receipt = dict(aggregate_sha256=digest(aggregate), original_report_sha256=digest(backup),
                   final_report_sha256=digest(result), findings_sha256=digest(path),
                   numerical_aggregate_unchanged=True, operation="Added interpretation; preserved original generated report")
    (output/"interpretation_receipt.json").write_text(json.dumps(receipt, indent=2)+"\n")
    print(json.dumps({k: value[k] for k in ("joint_updates_verified", "all_freezes_verified", "factorial_accuracy_intervals_excluding_zero", "unique_worker_cost_pair_sets")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aggregate", type=Path, default=Path(__file__).parent/"results/study001/analysis/aggregate.json")
    render(parser.parse_args().aggregate)
