"""Prespecified paired-seed analysis, never checkpoint selection or tuning.

Execution requires --execute-after-completion and terminal receipts for every
protocol job. Existing analysis outputs and failed receipts are never replaced.
"""

import argparse
from datetime import datetime, timezone
import itertools
import json
import math
from pathlib import Path

import numpy as np
from scipy.stats import t as student_t

from .analysis_audit import audit_job, digest, global_integrity, pending_jobs, read_json, registered_jobs


DEFAULT_SEEDS = (31031, 31067, 31103)
BOUNDARIES = ("value", "fixed", "direct")
CHANNELS = ("dual", "single", "ordinary")
EXTERNAL = ("two_gates", "transformer", "lif_snn")


def interval(values):
    values = np.asarray(values, dtype=float)
    if values.ndim != 1 or not len(values) or not np.all(np.isfinite(values)):
        raise ValueError("A finite nonempty paired sample is required")
    n, mean = len(values), float(values.mean())
    sd = float(values.std(ddof=1)) if n > 1 else None
    critical = 4.302652729911275 if n == 3 else float(student_t.ppf(.975, n-1)) if n > 1 else None
    half = critical*sd/math.sqrt(n) if n > 1 else None
    return dict(n=n, mean=mean, sd=sd, lower=None if half is None else mean-half,
                upper=None if half is None else mean+half, confidence=.95,
                critical_t=critical, values=values.tolist())


def ratios(numerator, denominator):
    a, b = np.asarray(numerator, float), np.asarray(denominator, float)
    if a.shape != b.shape or np.any(a <= 0) or np.any(b <= 0):
        return None
    statistics = interval(np.log(a/b))
    return dict(n=statistics["n"], geometric_mean=math.exp(statistics["mean"]),
                ratio_of_means=float(a.mean()/b.mean()),
                lower=None if statistics["lower"] is None else math.exp(statistics["lower"]),
                upper=None if statistics["upper"] is None else math.exp(statistics["upper"]),
                per_seed=(a/b).tolist(), method="paired log ratios; exponentiated Student-t 95% interval")


def condition(job):
    return tuple(job.get(k) for k in ("task", "width", "updates", "batch_size",
                                     "learning_rate", "training_cpu_budget"))


def condition_dict(key):
    return dict(zip(("task", "width", "registered_updates", "batch_size",
                     "learning_rate", "training_cpu_budget"), key))


def pair(candidate, baseline, case, expected_seeds, policy):
    seeds = sorted(set(candidate) & set(baseline))
    rows = [(candidate[s], baseline[s]) for s in seeds
            if case in candidate[s]["metrics"] and case in baseline[s]["metrics"]]
    if not rows:
        return None
    seeds = [a["job"]["seed"] for a, _ in rows]
    identity = all(a["metrics"][case]["data_sha256"] == b["metrics"][case]["data_sha256"]
                   and a["metrics"][case]["cohort_sha256"] == b["metrics"][case]["cohort_sha256"]
                   for a, b in rows)
    train_identity = all(a["dataset_sha256"] == b["dataset_sha256"] for a, b in rows)
    complete = set(seeds) == set(expected_seeds) and len(seeds) == len(expected_seeds)
    accuracy = interval([a["metrics"][case]["accuracy"]-b["metrics"][case]["accuracy"] for a, b in rows])
    ce = interval([a["metrics"][case]["cross_entropy"]-b["metrics"][case]["cross_entropy"] for a, b in rows])
    ce_ratio = ratios([a["metrics"][case]["cross_entropy"] for a, _ in rows],
                      [b["metrics"][case]["cross_entropy"] for _, b in rows])
    allocated_gap = max(abs(a["allocated_parameters"]-b["allocated_parameters"])/b["allocated_parameters"] for a, b in rows)
    active_gap = max(abs(a["trainable_parameters"]-b["trainable_parameters"])/max(1, b["trainable_parameters"]) for a, b in rows)
    training_gap = max(abs(a["costs"]["training_cpu_seconds"]-b["costs"]["training_cpu_seconds"])/b["costs"]["training_cpu_seconds"] for a, b in rows)
    parameter_match = max(allocated_gap, active_gap) <= policy["parameter_gap"]
    cpu_match = training_gap <= policy["training_cpu_gap"]
    comparable = complete and identity and train_identity
    ni = bool(comparable and accuracy["lower"] >= -policy["accuracy_noninferiority_margin"]
              and ce_ratio is not None and ce_ratio["upper"] <= policy["ce_noninferiority_ratio"]
              and ce_ratio["ratio_of_means"] <= policy["ce_noninferiority_ratio"])
    cost_ratios = {name: ratios([a["costs"][name] for a, _ in rows],
                               [b["costs"][name] for _, b in rows])
                   for name in ("training_cpu_seconds", "child_cpu_seconds", "child_peak_rss_bytes", "checkpoint_bytes")}
    cpu = cost_ratios["child_cpu_seconds"]
    gain = bool(comparable and accuracy["lower"] > 0)
    return dict(candidate=rows[0][0]["job"]["arm"], baseline=rows[0][1]["job"]["arm"],
                condition=condition_dict(condition(rows[0][0]["job"])), case=case,
                paired_seeds=seeds, complete_seed_set=complete, identical_evaluation_data=identity,
                identical_training_validation_data=train_identity,
                candidate_ids=[a["id"] for a, _ in rows], baseline_ids=[b["id"] for _, b in rows],
                accuracy_delta=accuracy, ce_delta=ce, ce_ratio=ce_ratio,
                max_allocated_parameter_gap=allocated_gap, max_trainable_parameter_gap=active_gap,
                parameter_budget_matched=parameter_match, max_training_cpu_gap=training_gap,
                training_cpu_matched=cpu_match,
                equal_actual_updates=all(a["actual_updates"] == b["actual_updates"] for a, b in rows),
                quality_noninferiority_qualified=ni, accuracy_gain_nominal95=gain,
                accuracy_sign=("unqualified_pairing" if not comparable else "positive" if accuracy["lower"] > 0
                               else "negative" if accuracy["upper"] < 0 else "interval_contains_zero"),
                matched_mechanism_accuracy_gain=gain and parameter_match and cpu_match,
                cost_ratios=cost_ratios,
                qualified_whole_worker_cpu_advantage=bool(ni and cpu is not None and cpu["upper"] < 1),
                qualification_scope="Prespecified paired seed condition/case; nominal intervals, no multiplicity correction")


def grouping(audits):
    groups, duplicates = {}, []
    for row in audits:
        if not row["audit_ok"]:
            continue
        arms = groups.setdefault(condition(row["job"]), {})
        seeds = arms.setdefault(row["job"]["arm"], {})
        seed = row["job"]["seed"]
        if seed in seeds:
            duplicates.append([seeds[seed]["id"], row["id"]])
        else:
            seeds[seed] = row
    if duplicates:
        raise ValueError("Ambiguous duplicate arm/condition/seed runs: "+json.dumps(duplicates))
    return groups


def planned_pairs(arms):
    pairs = set()
    if "value_dual" in arms:
        pairs.update(("value_dual", name) for name in arms if name != "value_dual")
    for boundary in BOUNDARIES:
        for other in ("single", "ordinary"):
            pairs.add((boundary+"_dual", boundary+"_"+other))
    for channel in CHANNELS:
        for other in ("fixed", "direct"):
            pairs.add(("value_"+channel, other+"_"+channel))
    return sorted((a, b) for a, b in pairs if a in arms and b in arms)


def factorial(groups, expected_seeds, planned=None):
    output = []
    for key in (groups if planned is None else planned):
        arms = groups.get(key, {})
        if key[0] != "selective_copy" or key[1] != 16 or key[-1] is not None:
            continue
        names = [b+"_"+c for b in BOUNDARIES for c in CHANNELS]
        if not all(name in arms and set(arms[name]) == set(expected_seeds) for name in names):
            output.append(dict(condition=condition_dict(key), complete=False,
                               reason="Full 3x3 factorial with all registered seeds is unavailable"))
            continue
        cases = sorted(set.intersection(*(set(arms[name][s]["metrics"]) for name in names for s in expected_seeds)))
        for case in cases:
            identity = all(len({(arms[name][s]["metrics"][case]["data_sha256"],
                                 arms[name][s]["metrics"][case]["cohort_sha256"],
                                 json.dumps(arms[name][s]["dataset_sha256"], sort_keys=True))
                                for name in names}) == 1 for s in expected_seeds)
            if not identity:
                output.append(dict(condition=condition_dict(key), case=case, complete=False,
                                   reason="Factorial cells do not use identical paired data/cohorts"))
                continue
            effects, interactions = [], []
            def cell(b, c, seed, metric):
                return arms[b+"_"+c][seed]["metrics"][case][metric]
            for factor, levels, other in (("boundary", BOUNDARIES, CHANNELS),
                                          ("channel", CHANNELS, BOUNDARIES)):
                for a, b in itertools.combinations(levels, 2):
                    metrics = {}
                    for metric in ("accuracy", "cross_entropy"):
                        values = []
                        for seed in expected_seeds:
                            vals = [(cell(a, z, seed, metric)-cell(b, z, seed, metric)) if factor == "boundary"
                                    else (cell(z, a, seed, metric)-cell(z, b, seed, metric)) for z in other]
                            values.append(float(np.mean(vals)))
                        metrics[metric] = interval(values)
                    effects.append(dict(factor=factor, candidate=a, baseline=b, **metrics))
            for a, b in itertools.combinations(BOUNDARIES, 2):
                for c, d in itertools.combinations(CHANNELS, 2):
                    metrics = {metric: interval([cell(a, c, s, metric)-cell(b, c, s, metric)
                                                -cell(a, d, s, metric)+cell(b, d, s, metric)
                                                for s in expected_seeds])
                               for metric in ("accuracy", "cross_entropy")}
                    interactions.append(dict(boundary_contrast=[a, b], channel_contrast=[c, d], **metrics))
            output.append(dict(condition=condition_dict(key), case=case, complete=True,
                               main_effects=effects, interactions=interactions,
                               sampling_unit="Seed; average other-factor cells within each seed before computing CI"))
    return output


def arm_summaries(groups):
    result = []
    for key, arms in groups.items():
        for name, seeds in arms.items():
            rows = [seeds[s] for s in sorted(seeds)]
            cases = sorted(set.intersection(*(set(r["metrics"]) for r in rows)))
            for case in cases:
                result.append(dict(condition=condition_dict(key), arm=name, case=case,
                    seeds=sorted(seeds), allocated_parameters=[r["allocated_parameters"] for r in rows],
                    trainable_parameters=[r["trainable_parameters"] for r in rows],
                    actual_updates=[r["actual_updates"] for r in rows],
                    accuracy=interval([r["metrics"][case]["accuracy"] for r in rows]),
                    cross_entropy=interval([r["metrics"][case]["cross_entropy"] for r in rows]),
                    costs={name: interval([r["costs"][name] for r in rows]) for name in
                           ("training_cpu_seconds", "child_cpu_seconds", "child_peak_rss_bytes", "checkpoint_bytes")}))
    return result


def inference_summaries(groups):
    result = []
    for key, arms in groups.items():
        for name, seeds in arms.items():
            lengths = sorted({s["length"] for row in seeds.values()
                              for s in row.get("inference", {}).get("samples", [])})
            for length in lengths:
                rows = [(seed, sample) for seed, row in sorted(seeds.items())
                        for sample in row.get("inference", {}).get("samples", []) if sample["length"] == length]
                result.append(dict(condition=condition_dict(key), arm=name, length=length,
                    seeds=[seed for seed, _ in rows],
                    median_cpu_seconds=interval([s["median_cpu_seconds"] for _, s in rows]),
                    median_wall_seconds=interval([s["median_wall_seconds"] for _, s in rows]),
                    persistent_numeric_state_bytes=[s["persistent_numeric_state_bytes"] for _, s in rows],
                    persistent_storage_bytes=[s["persistent_storage_bytes"] for _, s in rows],
                    input_tensor_bytes=[s["input_tensor_bytes"] for _, s in rows],
                    output_logits_bytes=[s["output_logits_bytes"] for _, s in rows],
                    scope="No-grad full-sequence batch=1; returned recurrent-state storage only; null is unavailable, not zero"))
    return result


def _ci(row, scale=1., digits=3):
    if row is None or row.get("lower") is None:
        return "不可判定"
    mean = row.get("mean", row.get("geometric_mean"))
    return f"{mean*scale:.{digits}f} [{row['lower']*scale:.{digits}f}, {row['upper']*scale:.{digits}f}]"


def chinese_report(report):
    audits, comparisons = report["job_audit"], report["comparisons"]
    valid = sum(row["audit_ok"] for row in audits)
    gain = sum(row["accuracy_gain_nominal95"] for row in comparisons)
    matched = sum(row["matched_mechanism_accuracy_gain"] for row in comparisons)
    ni = sum(row["quality_noninferiority_qualified"] for row in comparisons)
    cost = sum(row["qualified_whole_worker_cpu_advantage"] for row in comparisons)
    signs = {name: sum(row["accuracy_sign"] == name for row in comparisons)
             for name in ("positive", "negative", "interval_contains_zero", "unqualified_pairing")}
    lines = ["# HCSN 任务价值研究：完整注册矩阵分析", "",
             f"注册 {len(audits)} 个作业；完整性审计通过 {valid} 个，失败或证据不完整 {len(audits)-valid} 个。所有失败保留，未以失败作业替换成新种子。",
             "", "## 判定规则与结论边界", "",
             "所有 checkpoint 均由验证集交叉熵选择。分析不调参、不选择新的 checkpoint；审计重新核对预测、选择记录、源文件与 checkpoint 哈希。具体记录见 aggregate.json。",
             "",
             "比较单位是相同 seed 的差值；三个 seed 的名义 95% t 区间使用 df=2、临界值 4.30265273。CE 比先对每个 seed 取 log，再计算区间并指数变换，同时保留均值之比。区间未做多重比较校正；3 个初始化重复无法代表新数据集、受试者或硬件的不确定性。",
             "",
             f"共 {len(comparisons)} 个预定成对条件/评测情形：{gain} 个准确率差区间下界大于零，其中 {matched} 个同时满足参数和实际训练 CPU 匹配；{ni} 个满足质量非劣门槛；{cost} 个还满足完整 worker CPU 比区间上界小于 1。不同长度及缺失情形分别计数，不能把这些数量当作独立重复的证据。",
             f"准确率区间分类：正 {signs['positive']}，负 {signs['negative']}，包含零 {signs['interval_contains_zero']}，配对或 seed 不完整 {signs['unqualified_pairing']}；另有 {len(report['unavailable_comparisons'])} 个注册比较没有可用配对，全部保留为不可判定。",
             "",
             "质量非劣要求准确率差区间下界不低于 -0.02，CE 比区间上界及均值之比均不高于 1.05。只有通过质量非劣的配对，才允许在其具体条件下讨论测得的成本优势。简单点估计、低事件数、一次快运行或某个组件有梯度均不足以成立。",
             "", "## 主任务与外部基线", "",
             "下表为默认宽度 16、固定更新数、正常输入情形；准确率差使用百分点，正值有利于 value_dual。CPU 比为完整 worker CPU，包含启动、训练、验证、测试和存盘。",
             "", "| 任务 | 对照 | 准确率差及95%CI | CE比及95%CI | 全程CPU比及95%CI | 参数最大差 | 实际训练CPU匹配 | 质量非劣 | 有条件CPU优势 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in comparisons:
        c = row["condition"]
        if c["width"] == 16 and c["training_cpu_budget"] is None and row["case"] == "length32" and row["baseline"] in EXTERNAL and row["candidate"] == "value_dual":
            gap = max(row["max_allocated_parameter_gap"], row["max_trainable_parameter_gap"])
            lines.append(f"| {c['task']} | {row['baseline']} | {_ci(row['accuracy_delta'],100)} | {_ci(row['ce_ratio'])} | {_ci(row['cost_ratios']['child_cpu_seconds'])} | {gap:.1%} | {row['training_cpu_matched']} | {row['quality_noninferiority_qualified']} | {row['qualified_whole_worker_cpu_advantage']} |")
    lines += ["", "完整比较同时保留 CE 差、全部 seed、参数差、实际更新数、训练与全程 CPU 比、RSS 比和 checkpoint 字节比；未等预算的比较不会被标记为已隔离的机制优势。", "",
              "## 边界与通道的因子效应", "",
              "先在每个 seed 内对另一个因子的三个水平取平均，再计算主效应；交互为配对的差中之差。正准确率效应才有利于左侧水平。", "",
              "| 因子 | 对比 | 准确率差及95%CI（百分点） | CE差及95%CI |", "| --- | --- | --- | --- |"]
    for block in report["factorial"]:
        if block.get("complete") and block.get("case") == "length32":
            for effect in block["main_effects"]:
                lines.append(f"| {effect['factor']} | {effect['candidate']} − {effect['baseline']} | {_ci(effect['accuracy'],100)} | {_ci(effect['cross_entropy'])} |")
    lines += ["", "| 边界对比 × 通道对比 | 准确率交互及95%CI（百分点） | CE交互及95%CI |", "| --- | --- | --- |"]
    for block in report["factorial"]:
        if block.get("complete") and block.get("case") == "length32":
            for item in block["interactions"]:
                label = " − ".join(item["boundary_contrast"])+" × "+" − ".join(item["channel_contrast"])
                lines.append(f"| {label} | {_ci(item['accuracy'],100)} | {_ci(item['cross_entropy'])} |")
    lines += ["", "## 冻结与停止边界梯度", "",
              "差值为完整 value_dual 减去对应消融。冻结有意改变可训练容量，不能把它视为同可训练参数预算的另一完整架构。group_delta 核对最后优化状态，selected_group_delta 另核对实际测试所用的验证选择 checkpoint；两者均保留。", "",
              "| 消融 | 准确率差及95%CI（百分点） | CE差及95%CI |", "| --- | --- | --- |"]
    for row in comparisons:
        if row["case"] == "length32" and (row["baseline"].startswith("freeze_") or row["baseline"] == "stop_gradient_dual"):
            lines.append(f"| {row['baseline']} | {_ci(row['accuracy_delta'],100)} | {_ci(row['ce_delta'])} |")
    lines += ["", "## 宽度、长序列、真实AV与等CPU实验", "",
              "全部宽度及长度的结果见 aggregate.json 的 arm_summaries 和 comparisons；每个条件均显示 seed、实际更新数、CI 与成本，负结果及未匹配情况保留。", "",
              "| 任务 | 宽度 | 训练CPU上限 | 模型 | 正常长度准确率均值 | CE均值 | 全程CPU均值（秒） |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in report["arm_summaries"]:
        c = row["condition"]
        if row["case"] == "length32" and row["arm"] in ("value_dual", *EXTERNAL):
            budget = "固定更新数" if c["training_cpu_budget"] is None else str(c["training_cpu_budget"])
            lines.append(f"| {c['task']} | {c['width']} | {budget} | {row['arm']} | {row['accuracy']['mean']:.4f} | {row['cross_entropy']['mean']:.4f} | {row['costs']['child_cpu_seconds']['mean']:.3f} |")
    lines += ["", "真实 AV 的输入是实际解码的音频/视频因果特征，测试参与者与训练分离；该 cohort 已在此前工作观察过，不是新的独立确认样本。缺失模态是显式干预，保留采集时间与 valid 末标签；无 payload 的位置使 HCSN 只推进先前参数下的状态，不刷新信号或写入。两门/LIF 对照每 observed 事件一步，dt=0 首事件亦接收输入；这不声称其与 HCSN 共享相同物理 ODE。", "",
              "| AV情形 | 对照 | 准确率差及95%CI（百分点） | CE比及95%CI |", "| --- | --- | --- | --- |"]
    for row in comparisons:
        if row["condition"]["task"] == "async_av" and row["candidate"] == "value_dual" and row["baseline"] in ("value_ordinary", *EXTERNAL):
            lines.append(f"| {row['case']} | {row['baseline']} | {_ci(row['accuracy_delta'],100)} | {_ci(row['ce_ratio'])} |")
    totals = report["resource_totals"]
    lines += ["", "## 完整成本账本", "",
              f"有 receipt 的注册作业合计 child CPU 为 {totals['child_cpu_seconds']:.3f} 秒；监控进程 CPU 另计 {totals['supervisor_cpu_seconds']:.3f} 秒，不能再次把内层训练 CPU 加进全程数。",
              f"单个 worker 的最高峰值 RSS 为 {totals['maximum_child_peak_rss_bytes']} 字节；这不是所有并发 worker 的合计内存。已审计 checkpoint 共 {totals['checkpoint_bytes']} 字节，包含模型、优化器及复现实验状态。",
              "",
              "receipt 不含此前环境安装、共享数据准备及未被 worker 回收的外部进程。推理计量是共享 CPU 主机上整段序列、batch=1、一次预热后五次重复；并非优化 KV-cache 服务，长输入通过重复首个测试输入构造。能耗未直接测量，未从 CPU 时间、事件数或本地 I/O 推造焦耳。", "",
              "推理的 logical tensor 字节与按底层 storage 去重的字节均在 inference_summaries 中逐长度报告；null 表示该接口未提供缓存状态，不能当作零内存。返回状态不包括输入、输出 logits、反向传播图或所有临时分配，训练内存不由这些数字界定。", "",
              "## 失败、完整性问题与未关闭问题", ""]
    lines.extend("- **全局证据**："+error for error in report["integrity"]["errors"])
    for row in audits:
        if row["errors"]:
            lines.append(f"- **{row['id']}**："+"；".join(row["errors"]))
    if valid == len(audits):
        lines.append("全部注册作业通过本次文件与数值一致性审计；此前独立数值验证中的失败日志仍保留。")
    warnings = sum(bool(row["warnings"]) for row in audits)
    if warnings:
        lines.append(f"另有 {warnings} 个作业含非致命审计提醒（如可训练组的变化/梯度为零，或未达到 CPU 上限）；逐项保留在 job_audit.warnings，不能因作业完成而视作该机制有效。")
    for row in report["unavailable_comparisons"]:
        c = row["condition"]
        lines.append(f"- **不可判定比较**：{c['task']} / width={c['width']} / CPU上限={c['training_cpu_budget']} / {row['case']} / {row['candidate']} − {row['baseline']}：没有完整性审计通过的配对数据。")
    lines += ["", "学习到的局部奖励及Brownian边界不等于全序列任务最优解；8-bin有限流与连续参考存在数值差距。这里的结果不能自动推广到大规模多模态预训练、GPU吞吐、端侧能耗或真实神经形态硬件。只有满足报告中明示门槛的具体比较才支持相应范围的结论。", ""]
    return "\n".join(lines)


def analyze(study, output, *, authorized=False):
    if not authorized:
        raise RuntimeError("Final analysis requires explicit execute-after-completion authorization")
    study, output = Path(study), Path(output)
    protocol_path = study/"protocol.json"
    protocol = read_json(protocol_path)
    registered = registered_jobs(study, protocol)
    pending = pending_jobs(study, registered)
    if pending:
        raise RuntimeError("Registered jobs are not terminal; no predictions opened: "+", ".join(pending))
    integrity = global_integrity(study, protocol)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("Use a new analysis directory; previous analyses are retained")
    output.mkdir(parents=True, exist_ok=True)
    seeds = tuple(protocol.get("seeds", DEFAULT_SEEDS))
    policy = {"accuracy_noninferiority_margin": .02, "ce_noninferiority_ratio": 1.05,
              "parameter_gap": .05, "training_cpu_gap": .10}
    evaluation = protocol.get("evaluation", {})
    for declared, name in (("accuracy_noninferiority_margin", "accuracy_noninferiority_margin"),
                           ("maximum_ce_ratio", "ce_noninferiority_ratio"),
                           ("parameter_relative_gap_max", "parameter_gap"),
                           ("cpu_relative_gap_max", "training_cpu_gap")):
        if declared in evaluation:
            policy[name] = evaluation[declared]
    if evaluation.get("confidence", .95) != .95 or abs(evaluation.get("paired_seed_t_critical", 4.302652729911275)-4.302652729911275) > 1e-12:
        raise ValueError("Analysis implements the registered 95% paired t contract only")
    source_cache = {}
    audits = [audit_job(study, registration, source_cache) for registration in registered]
    for row in audits:
        if integrity["errors"]:
            row["errors"].extend(integrity["errors"])
            row["audit_ok"] = False
    groups = grouping(audits)
    planned = {}
    for row in registered:
        planned.setdefault(condition(row["job"]), set()).add(row["job"]["arm"])
    comparisons, unavailable = [], []
    for key, names in planned.items():
        arms = groups.get(key, {})
        for a, b in planned_pairs(names):
            cases = ("length32", "missing_modality0", "missing_modality1") if key[0] == "async_av" else ("length32", "length64", "length128")
            for case in cases:
                comparison = pair(arms.get(a, {}), arms.get(b, {}), case, seeds, policy)
                if comparison:
                    comparisons.append(comparison)
                else:
                    unavailable.append(dict(condition=condition_dict(key), candidate=a, baseline=b, case=case))
    totals = {name: float(sum(r["costs"].get(name) or 0 for r in audits))
              for name in ("child_cpu_seconds", "supervisor_cpu_seconds")}
    totals["maximum_child_peak_rss_bytes"] = max((r["costs"].get("child_peak_rss_bytes") or 0 for r in audits), default=0)
    totals["checkpoint_bytes"] = sum(r["costs"].get("checkpoint_bytes") or 0 for r in audits)
    report = dict(schema="hcsn-paired-study-analysis.v1", created_at_utc=datetime.now(timezone.utc).isoformat(),
                  protocol_sha256=digest(protocol_path), registered_jobs=len(registered), expected_seeds=seeds,
                  analysis_thresholds=policy, integrity=integrity, job_audit=audits, comparisons=comparisons,
                  unavailable_comparisons=unavailable, factorial=factorial(groups, seeds, planned),
                  arm_summaries=arm_summaries(groups), inference_summaries=inference_summaries(groups),
                  resource_totals=totals, test_predictions_used_for="Final prespecified reporting only",
                  source_sha256={name: digest(Path(__file__).parent/name) for name in ("analysis.py", "analysis_audit.py")},
                  limitations=["Three-seed nominal t intervals; no multiplicity correction",
                               "Seed intervals do not measure dataset or hardware generalization",
                               "Equal training CPU is an inner clock; full worker cost is separately reported",
                               "Failed jobs and unmatched budgets cannot support qualified benefit claims"])
    (output/"aggregate.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False)+"\n")
    (output/"RESULTS_ZH.md").write_text(chinese_report(report))
    print(json.dumps({"output": str(output), "registered_jobs": len(registered),
                      "audit_ok": sum(r["audit_ok"] for r in audits),
                      "comparisons": len(comparisons)}, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, default=Path(__file__).parent/"results"/"study001")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--execute-after-completion", action="store_true")
    options = parser.parse_args()
    analyze(options.study, options.output or options.study/"analysis", authorized=options.execute_after_completion)
