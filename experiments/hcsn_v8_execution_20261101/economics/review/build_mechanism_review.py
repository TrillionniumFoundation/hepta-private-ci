"""Independently summarize recorded interventions and nested campaign costs.

This reads saved artifacts only. It never imports a scientific model, performs
training, or changes campaign sources or outputs.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
from statistics import fmean


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    base = repo / "experiments/hcsn_v8_execution_20261101"
    run = base / "mechanisms/results/development001"
    audit_dir = base / "economics/review/mechanism001"
    audit = read(audit_dir / "AUDIT.json")
    assert audit["all_checks_passed"] and not audit["failed_check_examples"]
    plan, summary = read(run / "PLAN.json"), read(run / "SUMMARY.json")
    selected = read(run / "evaluation/FROZEN_INPUTS.json")["selected"]
    with gzip.open(run / "evaluation/runs.jsonl.gz", "rt") as stream:
        rows = [json.loads(line) for line in stream]
    indexed = {tuple(r[k] for k in ("condition", "index", "arm", "fit_seed", "family")): r for r in rows}
    assert len(indexed) == len(rows) == audit["runs"]
    assertions = 0

    def check(ok, name):
        nonlocal assertions
        assertions += 1
        if not ok:
            raise AssertionError(name)

    def close(left, right, name):
        check(abs(left - right) < 1e-10, name)

    def actions(row):
        return {p["tick"]: p["executed_action"] for p in row["trace"]}

    conditions = {}
    for condition in plan["conditions"]:
        effects, support = {}, []
        n = plan["episodes_per_condition"]
        for name in plan["interventions"]:
            changed_actions, changed_distributions, changed_classes = 0, 0, 0
            differences = {key: [] for key in ("closed_net_reward", "fixed_net_reward", "fixed_brier")}
            for index in range(n):
                d = indexed[(condition, index, "D", None, None)]
                fixed = indexed[(condition, index, name + "_fixed_D", None, None)]
                closed = indexed[(condition, index, name + "_closed", None, None)]
                check(actions(d) == actions(fixed), "fixed intervention actions")
                changed_actions += actions(d) != actions(closed)
                for original, altered in zip(d["predictions"], fixed["predictions"]):
                    p, q = original["probabilities"], altered["probabilities"]
                    changed_distributions += any(abs(a - b) > 1e-12 for a, b in zip(p, q))
                    changed_classes += max(range(len(p)), key=p.__getitem__) != max(range(len(q)), key=q.__getitem__)
                for key, altered, field in (("closed_net_reward", closed, "net_reward"),
                                             ("fixed_net_reward", fixed, "net_reward"),
                                             ("fixed_brier", fixed, "brier")):
                    differences[key].append(altered["summary"][field] - d["summary"][field])
            declared = summary["conditions"][condition]["mechanism_effects"][name]
            total = {"action_changed_worlds": changed_actions,
                     "fixed_action_distribution_changes": changed_distributions,
                     "fixed_action_predicted_class_changes": changed_classes,
                     "fixed_actions_identical": True, "paired_worlds": n}
            for key, value in total.items():
                check(value == declared[key], "effect count " + key)
            for key, values in differences.items():
                close(fmean(values), declared["intervention_minus_original_means"][key], "effect mean " + key)
                for value, target in zip(values, declared["paired_differences"][key]):
                    close(value, target, "paired effect " + key)
            effects[name] = {**total, "fixed_output_denominator": n * len(plan["config"]["deadlines"]),
                             "intervention_minus_original_means": {key: fmean(values) for key, values in differences.items()}}
        for index in range(n):
            for p in indexed[(condition, index, "D", None, None)]["predictions"]:
                if p["observed_state"]["has_read"]:
                    support.append(sum(p["count_probabilities"][2:]))
        reachable = {"post_READ_output_states": len(support),
                     "multiple_event_probability_mean": fmean(support),
                     "multiple_event_probability_max": max(support),
                     "states_with_multi_probability_over_01": sum(p > .01 for p in support)}
        for key, value in reachable.items():
            close(value, summary["conditions"][condition]["reachable_support"][key], "reachable support " + key)
        family_means = {}
        for family in plan["ordinary_families"]:
            values = []
            for seed in plan["fit_seeds"]:
                values.append(fmean(indexed[(condition, i, "D", None, None)]["summary"]["net_reward"] -
                                    indexed[(condition, i, "B", seed, family)]["summary"]["net_reward"] for i in range(n)))
            family_means[family] = {"D_minus_B_mean": fmean(values), "by_fit": dict(zip(map(str, plan["fit_seeds"]), values))}
        conditions[condition] = {"selected_factorial": audit["independently_recomputed_contrasts"][condition],
                                 "all_families": family_means, "mechanism_effects": effects, "reachable_support": reachable}

    validation = base / "mechanisms/validation"
    stage_names = ["fit_" + str(seed) for seed in plan["fit_seeds"]] + ["evaluate", "aggregate"]
    costs = {}
    for name in ["campaign_envelope", *stage_names, "prepare001", "tests001"]:
        directory = validation / name
        receipt, supervision = read(directory / "RECEIPT.json"), read(directory / "SUPERVISION.json")
        check(sha(directory / "SUPERVISION.json") == receipt["supervision_sha256"], "supervision identity " + name)
        check(receipt["task_success"] and receipt["complete_task_cpu_coverage"], "cost coverage " + name)
        check(supervision["all_waitable_children_collected"] and supervision["subreaper"]["enabled"], "all children " + name)
        check(receipt["source_unchanged_through_collection"], "measurement freeze " + name)
        for filename, digest in receipt["source_sha256_at_start"].items():
            if name == "tests001" and filename.endswith("/economics/worker_cost.py"):
                source = base / "economics/validation/source002/worker_cost.py"
            else:
                source = Path(filename)
            check(sha(source) == digest, "current or archived measurement source " + name)
        check(supervision["memory"]["family_sampled_peak_rss_sum_bytes"] is None, "family memory unavailable " + name)
        check(supervision["energy"]["joules"] is None, "energy unavailable " + name)
        costs[name] = {"cpu_seconds": receipt["complete_supervisor_wait4"]["cpu_seconds"],
                       "wall_seconds": receipt["cold_supervisor_to_exit_seconds"],
                       "begin_ns": receipt["monotonic_begin_ns"], "end_ns": receipt["monotonic_end_ns"],
                       "nested_in_campaign": name in stage_names,
                       "receipt": str((directory / "RECEIPT.json").relative_to(repo))}
    envelope = costs["campaign_envelope"]
    for name in stage_names:
        check(envelope["begin_ns"] <= costs[name]["begin_ns"] < costs[name]["end_ns"] <= envelope["end_ns"], "nested wall boundary " + name)
    for a, b in zip(stage_names, stage_names[1:]):
        check(costs[a]["end_ns"] <= costs[b]["begin_ns"], "sequential stages " + a)
    for name in ("tests001", "prepare001"):
        check(costs[name]["end_ns"] < envelope["begin_ns"], "separate earlier cost " + name)
    stage_sum = sum(costs[name]["cpu_seconds"] for name in stage_names)
    fit_sum = sum(costs[name]["cpu_seconds"] for name in stage_names if name.startswith("fit_"))
    check(envelope["cpu_seconds"] >= stage_sum, "nested CPU containment")
    audit_receipt = read(audit_dir / "RECEIPT.json")
    check(audit_receipt["monotonic_begin_ns"] >= envelope["end_ns"], "audit outside campaign")
    check(audit_receipt["task_success"] and audit_receipt["complete_task_cpu_coverage"], "audit successful measurement")
    selected_ids = sorted(set(selected.values()))
    report = {"schema": "hcsn-v8-independent-mechanism-review.v1", "all_checks_passed": True,
              "primary_audit_assertions": audit["checks"], "supplemental_assertions": assertions,
              "primary_audit": str((audit_dir / "AUDIT.json").relative_to(repo)),
              "worlds": audit["worlds"], "runs": audit["runs"], "outputs": audit["outputs"],
              "selected_families": selected, "conditions": conditions, "cost_receipts": costs,
              "cost_accounting": {"primary_campaign_cpu_seconds": envelope["cpu_seconds"],
                                  "primary_campaign_wall_seconds": envelope["wall_seconds"],
                                  "nested_stage_cpu_sum_seconds": stage_sum,
                                  "outer_minus_stage_cpu_seconds": envelope["cpu_seconds"] - stage_sum,
                                  "five_paired_fit_stage_cpu_seconds": fit_sum,
                                  "primary_raw_audit_cpu_seconds": audit_receipt["complete_supervisor_wait4"]["cpu_seconds"],
                                  "primary_raw_audit_wall_seconds": audit_receipt["cold_supervisor_to_exit_seconds"],
                                  "rule": "Charge the enclosing campaign once. Seven stage receipts are nested diagnostics. Preparation, earlier tests, and later audits are separate. This is not the complete project cost."},
              "amortization": {str(h): {"observed_campaign_allocation_cpu_seconds": envelope["cpu_seconds"] / h,
                                        "observed_fit_stage_allocation_cpu_seconds": fit_sum / h,
                                        "complete_deployment_cpu_seconds_per_episode": None}
                               for h in (20, 10000)},
              "amortization_scope": "These are allocations of measured development batches, not deployment estimates. The fit allocation is already inside the campaign allocation; do not add them. Per-candidate execution, deployment preparation/pretraining and acquisition costs are not isolated, so complete deployment amortization stays null.",
              "complete_family_memory_bytes": None, "device_energy_joules": None,
              "deployment_episode_source_to_flush_seconds": None,
              "candidate_economic_advantage": None, "scientific_confirmation": False,
              "claims": {"positive_selected_D_minus_B_observed": False,
                         "interventions_change_actions_and_content": True,
                         "risk_mechanism_measured": False, "mechanism_necessity_established": False,
                         "new_real_AV_test": False, "v7_identical_fixed_schedule_gate_met": False},
              "evidence_sha256": {"raw_runs": sha(run / "evaluation/runs.jsonl.gz"),
                                  "summary": sha(run / "SUMMARY.json"), "primary_audit": sha(audit_dir / "AUDIT.json"),
                                  "primary_auditor_source_at_review": sha(base / "economics/audit_mechanism_records.py"),
                                  "review_builder_source": sha(Path(__file__))}}
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / "REPORT.json"
    with target.open("x") as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    lines = ["# 机制开发运行：独立结果与成本复核", "",
             f"独立原始记录审计的 {audit['checks']:,} 项检查全部通过；本次补充复核的 {assertions:,} 项检查全部通过。覆盖 48 个独立生成世界、1,728 个运行和 6,912 个强制输出。没有重跑模型、改变科学源码或覆盖原始结果。", "",
             "## 解析核心增量", "",
             "五个拟合种子的普通核心都由验证集计数 NLL 选择 GRU。主口径是每个种子在同一批世界上的均值，再在五个拟合间取均值。", "",
             "| 条件 | A | B | C | D | D−B | D−C | 交互 |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for condition, data in conditions.items():
        c = data["selected_factorial"]
        lines.append("| " + condition + " | " + " | ".join(f"{c[k]:.6f}" for k in ("A", "B", "C", "D", "D-B", "D-C", "interaction")) + " |")
    lines += ["", "这批结果没有观察到正的主口径 D−B。它支持已经实际完成普通 GRU／SSM 与解析核心的受控比较，不能支持解析核心取得正增量。D/C 在五个普通拟合之间复用；每条件只有 24 个世界，不能把它们当作 120 个独立的解析核心样本。SSM 的各拟合结果完整保留，但不能因某个子组较有利而替换预先由验证 NLL 选择的参照。", "",
              "A/C 使用共同的置信度触发轻控制规则；其观察动作可能不同，未满足 v7 的完全相同固定观察日程。循环模型序列是四个内部预测时间节点，不是持续 AV 观察记忆。任务使用合成更新过程和完美传感读取；本次没有新真实 AV 确认。效用为四次输出的平均准确率减 0.04 × 实际 READ 次数，不含 CPU 或能量货币化。", "",
              "## 单因素干预", "",
              "所有固定动作配对都复现了 D 的实际动作；原始审计还逐概率重建了两种计数变换。下表的分布与类别变化以每条件 96 个强制输出为分母，动作变化以 24 个世界为分母。效用及 Brier 均为干预减原始；Brier 增大表示变差。", "",
              "| 条件 | 干预 | 动作改变 | 固定动作后分布改变 | 类别改变 | 闭环效用差 | 固定动作效用差 | 固定动作 Brier 差 |", "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for condition, data in conditions.items():
        for name, effect in data["mechanism_effects"].items():
            means = effect["intervention_minus_original_means"]
            lines.append(f"| {condition} | {name} | {effect['action_changed_worlds']}/24 | {effect['fixed_action_distribution_changes']}/96 | {effect['fixed_action_predicted_class_changes']}/96 | {means['closed_net_reward']:.6f} | {means['fixed_net_reward']:.6f} | {means['fixed_brier']:.6f} |")
    lines += ["", "mean_two_point 保持计数均值并改为邻接两点分布；single_transition 保持 P(N=0)，把所有正计数质量放到 N=1，因此后者也改变计数均值。变化证明这两个预测机制在可达状态上能够影响动作与内容，不证明它们不可替代。固定动作下每个条件只有一次类别变化，闭环效用差也并非解析机制被破坏后一致下降。", "",
              "普通核心另行训练后执行的替代结果已经测量，但没有对受干预解析核心重新训练、也没有测量外部服务风险机制，不能据此声称全部三种机制的必要性。解析 D 在已 READ 输出状态中，多事件概率超过 1% 的数量为 matched 9/92、失配 7/89；完整均值与最大值见 REPORT.json。", "",
              "## 完整执行边界与费用包含关系", "",
              f"整个五次拟合、评估和汇总批次的外层费用为 **{envelope['cpu_seconds']:.6f} CPU 秒／{envelope['wall_seconds']:.9f} 壁钟秒**。它包含七个阶段的启动、执行、普通后代、测量、排空及内部证据写入。所有可等待后代已经回收，计量源码保持冻结。", "",
              "| 嵌套阶段 | CPU 秒 | 壁钟秒 |", "| --- | ---: | ---: |"]
    for name in stage_names:
        lines.append(f"| {name} | {costs[name]['cpu_seconds']:.6f} | {costs[name]['wall_seconds']:.9f} |")
    lines += ["", f"七阶段 CPU 小计为 {stage_sum:.6f} 秒，已经包括在外层 {envelope['cpu_seconds']:.6f} 秒内；两者差额为 {envelope['cpu_seconds'] - stage_sum:.6f} 秒。差额覆盖外层测量、调度及阶段启动器等边界工作，不分配给任何单个候选。五次成对拟合小计 {fit_sum:.6f} 秒同样是嵌套诊断。不能把这些数值再次相加。", "",
              f"prepare001 的 {costs['prepare001']['cpu_seconds']:.6f} 秒、较早 tests001 的 {costs['tests001']['cpu_seconds']:.6f} 秒及独立原始审计的 {audit_receipt['complete_supervisor_wait4']['cpu_seconds']:.6f} 秒处于主批次之外；这些各自有凭证。较早测试使用的旧计量源码已与存档哈希相符。此处没有把仍未计量的探索、人工复核和外层最终凭证写入冒称为零，也没有把列出的开发费用称为整个项目总成本。", "",
              "完整部署进程族 RSS 与直接可归因设备能量仍为 null。已登记集合峰值、单进程 high-water 和共享页 RSS 求和都不能替代完整族峰值。本机制批次没有 episode 输出 flush 标记，只有进程壁钟；仿真逻辑截止时间不能当作实机延迟。评估批次同时包括世界生成、校准、多候选执行与原始记录写入，不能把其 CPU 除以 1,728 当成候选部署推理成本。", "",
              "## H=20 与 H=10,000", "",
              "| H | 已测开发批次费用 / H（CPU 秒） | 其中五次成对拟合 / H（CPU 秒） | 完整部署每 episode 成本 |", "| ---: | ---: | ---: | --- |"]
    for h in (20, 10000):
        lines.append(f"| {h:,} | {envelope['cpu_seconds'] / h:.9f} | {fit_sum / h:.9f} | null |")
    lines += ["", "这只是对实际开发费用做明确的分摊运算；第二列已经包含第三列，不能相加。每个候选的部署准备、预训练、输入获取和执行费用没有分别隔离，因此完整部署摊销继续保持 null，不能用本表证明经济优势。", "",
              "## 可复核文件", "",
              "- 原始复核：`economics/review/mechanism001/AUDIT.json`，其同目录包含运行费用及完整标准输出。",
              "- 本复核的紧凑机器报告：`REPORT.json`；其中列出所有凭证路径及证据 SHA256。",
              "- 本复核生成程序：`build_mechanism_review.py`；执行凭证位于 `economics/review/mechanism_report001/`。",
              "- 科学原始记录与冻结输入：`mechanisms/results/development001/evaluation/`。", ""]
    with (args.out / "MECHANISM_REVIEW.md").open("x") as stream:
        stream.write("\n".join(lines))
    print(json.dumps({"all_checks_passed": True, "supplemental_assertions": assertions,
                      "selected_families": selected_ids, "report": str(target)}))


if __name__ == "__main__":
    main()
