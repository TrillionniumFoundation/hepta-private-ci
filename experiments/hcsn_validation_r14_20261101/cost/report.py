"""Static scientific figures and a plain-language report from retained replay rows."""

import argparse
from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path
import statistics


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def make(output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    summary = read(output / "SUMMARY.json")
    aggregate = read(output / "aggregate_quality_cost.json")
    with (output / "paired_analytic_ordinary.csv").open() as stream:
        paired = list(csv.DictReader(stream))
    groups = defaultdict(list)
    for row in paired:
        groups[(row["task"], row["mode"], row["domain"], int(row["batch"]))].append(row)
    comparisons = []
    for (task, mode, domain, batch), rows in sorted(groups.items()):
        ratios = [float(r["analytic_over_ordinary_cpu"]) for r in rows]
        comparisons.append(dict(task=task, mode=mode, domain=domain, batch=batch,
            accuracy_delta=statistics.mean(float(r["analytic_minus_ordinary_accuracy"]) for r in rows),
            mean_paired_cpu_ratio=statistics.mean(ratios), min_paired_cpu_ratio=min(ratios),
            max_paired_cpu_ratio=max(ratios), slower_seeds=sum(r > 1 for r in ratios)))
    with (output / "analytic_vs_ordinary_summary.json").open("x") as stream:
        json.dump(comparisons, stream, indent=2, sort_keys=True)
        stream.write("\n")

    families = ("ordinary_dual", "probit", "analytic", "lif_snn", "continuous_rnn", "cfc", "mamba1", "transformer")
    colors = dict(zip(families, ("#334155", "#7c3aed", "#c02642", "#ca8a04", "#16a34a", "#0891b2", "#2563eb", "#111827")))
    figure, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    for axis, (task, mode) in zip(axes.flat, ((t, m) for t in ("recall", "binding") for m in ("frozen_frontend", "joint"))):
        values = [r for r in aggregate if r["task"] == task and r["mode"] == mode and r["domain"] == "iid" and r["batch"] == 1]
        for row in values:
            axis.scatter(row["mean_cpu_s_per_sample"] * 1000, row["mean_accuracy"] * 100,
                         s=75 if row["family"] == "analytic" else 48,
                         color=colors[row["family"]], marker="D" if row["family"] == "analytic" else "o",
                         label=row["family"])
        axis.set_title(task + " / " + mode)
        axis.set_xlabel("Warm full-model CPU (ms / sample; batch 1)")
        axis.set_ylabel("Historical test accuracy (%)")
        axis.grid(alpha=.22)
    handles, labels = axes.flat[0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="outside lower center", ncol=4, frameon=False)
    figure.suptitle("R14: historical weights replayed on identical inputs\nThree fit seeds; descriptive means, no new training", fontsize=13)
    for suffix in ("svg", "png"):
        figure.savefig(output / ("quality_cost_iid." + suffix), dpi=160)
    plt.close(figure)

    domains = [(r["task"], r["domain"]) for r in comparisons if r["mode"] == "joint" and r["batch"] == 1]
    labels = [task + ": " + domain for task, domain in domains]
    figure, axes = plt.subplots(2, 2, figsize=(15, 10), sharex=True, constrained_layout=True)
    for axis, (mode, batch) in zip(axes.flat, ((m, b) for m in ("frozen_frontend", "joint") for b in (1, 32))):
        selected = {(r["task"], r["domain"]): r for r in comparisons if r["mode"] == mode and r["batch"] == batch}
        for index, key in enumerate(domains):
            row = selected[key]
            mean, low, high = row["mean_paired_cpu_ratio"], row["min_paired_cpu_ratio"], row["max_paired_cpu_ratio"]
            axis.plot([low, high], [index, index], color="#94a3b8", linewidth=2)
            axis.plot(mean, index, "o", color="#c02642", markersize=5)
        axis.axvline(1, color="#334155", linestyle="--", linewidth=1)
        axis.set_yticks(range(len(labels)), labels, fontsize=8)
        axis.invert_yaxis()
        axis.set_title(mode + " / batch " + str(batch))
        axis.set_xlabel("Analytic / ordinary CPU ratio (higher costs more)")
        axis.grid(axis="x", alpha=.2)
    figure.suptitle("All stress conditions: paired CPU ratios\nPoints: mean of 3 seed ratios; bars: observed seed range (not confidence intervals)", fontsize=13)
    for suffix in ("svg", "png"):
        figure.savefig(output / ("stress_cpu_ratios." + suffix), dpi=160)
    plt.close(figure)

    lines = ["# R14：全部历史域的实际内容质量—成本重放", "",
        f"已完成 **{summary['workers']} 个串行新进程**，覆盖 8 个模型族、2 个训练模式、3 个既有拟合种子、recall 的 7 个域和 binding 的 8 个域。每个模型/域均测 batch 1、32，共 **{summary['model_domain_batch_cells']} 个条件**；新执行 **{summary['historical_predictions_reexecuted']:,} 个原始测试预测**，最大 logit 差为 `{summary['maximum_logit_replay_difference']:.8g}`。", "",
        "这是历史冻结权重与原始输入的硬件重放。没有新增训练，也没有把原测试集重新称为独立确认。`frozen_frontend` 的含义保持不变：只冻结共同 encoder；它不等于完整内容后端冻结。", "",
        "## 1. 本轮补齐的实际成本", "",
        "旧 profile 只使用验证集 IID 形状。本轮所有长干扰、空白保持、不规则时间、四倍时钟、改查询和缺失模态的质量均配上该域的实际完整模型时间，未用 IID 延迟代填。", "",
        "batch 1 的 first call 是该新 worker 中的第一次完整模型前向；batch 32 的 first call 已经过 batch 1，只称首次形状调用。输入生成与权重加载在内层前向计时之外，计入完整 fresh worker。全部模型前向含 NumPy 输入转 tensor、encoder、全部序列步、readout 和 CPU 输出复制。", "",
        f"完整 worker 合计 CPU **{summary['complete_worker_cpu_seconds']:.6f} 秒**，串行 wall **{summary['complete_worker_wall_seconds']:.6f} 秒**；最大单 worker 峰值 RSS 为 **{summary['maximum_worker_rss_bytes']:,} 字节**。这些完整账单已经包含 first/warm 调用、函数计数和质量重放，不能再与内层计时相加。", "",
        f"解析/普通的 {summary['analytic_comparison_pairs']} 个同 seed/域/batch 配对中，解析 warm CPU 更高的有 **{summary['analytic_slower_cpu_pairs']} 个**。以下是三个 fit seed 的描述性均值与范围，不是显著性结论。", "",
        "| 任务 | 模式 | 域 | batch | 解析−普通准确率 | 解析/普通CPU均值 | seed范围 |", "|---|---|---|---:|---:|---:|---:|"]
    for row in comparisons:
        lines.append(f"| {row['task']} | {row['mode']} | {row['domain']} | {row['batch']} | {row['accuracy_delta']:+.6f} | {row['mean_paired_cpu_ratio']:.3f}× | {row['min_paired_cpu_ratio']:.3f}–{row['max_paired_cpu_ratio']:.3f}× |")
    lines.extend(["", "![全部域的实测CPU比例](stress_cpu_ratios.png)", "",
        "## 2. 质量与最强可实施对照", "",
        "所有八族结果均保留，含普通双头、中心斜率匹配 probit、解析 renewal、LIF+SG、连续时间 RNN、官方 CfC、Mamba-1 CPU reference 与 SDPA Transformer。描述性 Pareto 标记按每个 task/mode/domain/batch 的均值单独计算，不把低质量的快模型说成同质量优势，也不把 CPU reference 说成优化 GPU 实现。", "",
        "![IID质量与完整模型CPU](quality_cost_iid.png)", "",
        "全部 480 个三 seed 聚合单元见 `aggregate_quality_cost.json`；1,440 个逐 seed 条件见 `per_seed_quality_cost.csv`。模型预算与选择沿用原始冻结协议，并未充分逐族重新调参。", "",
        "## 3. 特殊函数、状态和训练账", "",
        "独立未计时前向实际统计 Python 调用路径中的 `log_ndtr`、`logaddexp`、`expm1` 和 `exp` 次数与元素数量；instrumented 与普通输出逐位相同。计数不是耗时替代指标；实际特殊函数执行已在完整模型前向计时内。张量方法形式的 exp 等其他调用不计入该专项计数，未宣称算子全覆盖。", "",
        "精确记录参数/缓冲、原始输入、返回的序列状态历史及输出字节。返回历史字节不是总工作内存；RSS 不是状态分布专项内存。该历史内容实现没有完整存活密度、恢复年龄状态或任务自由边界求解，相应字段保留 null 并说明未实现，不能写成实测零成本。", "",
        "训练摊销沿用原始外部 wait4 账，独立候选管线含一次共同 donor 与 candidate fit/selection。N 表示总样本请求，只报告 N≥batch 且 N 能整除 batch 的完整批量情景；batch 1 的范围从 1 到 1,000,000，batch 32 至少需要 32 个请求，不把满批成本分摊给 N=1 或 10。尾批费用尚未测量。新 forward 测量单独进入每请求项；不是重新执行历史训练，也不是把共享 donor 同时重复加入研究总账。", "",
        "## 4. 明确的未测范围", "",
        "物理能量为 null；没有用 CPU 秒乘猜测功率。GPU、原媒体获取、在线查询、网络、部署服务初始化及上游预训练成本未由这组历史合成输入重放建立。720 个完整科学 worker 包含核对/写证据的研究工作，其总耗时不是线上单请求冷启动。", "",
        "三 fit seeds、各域和重复计时保留其依赖结构，不按 184,320 个重复预测虚增独立拟合数。内容任务收益与控制线的 D−B 分开报告，未把此成本覆盖修复当作解析网络核心准入。", "",
        "## 5. 可核对入口", "",
        "`PROTOCOL.json`、`SOURCE_FREEZE.json`、`INPUT_MANIFEST.json` 固定本轮方法与历史权重/输入/训练账；`SOURCE_SNAPSHOTS/` 保存对应源码字节；`workers/*/RESULT.json` 与 `predictions.npz` 是每个域的原始测量和重放预测；`receipts/` 和 `process_ledger.csv` 保留全部新进程执行成本。复现命令见父目录 `README.md`。", ""])
    (output / "REPORT_ZH.md").write_text("\n".join(lines), encoding="utf-8")
    products = [p for p in output.iterdir() if p.suffix in (".svg", ".png", ".csv") or p.name in ("REPORT_ZH.md", "SUMMARY.json", "aggregate_quality_cost.json", "analytic_vs_ordinary_summary.json")]
    with (output / "FIGURE_DATA_IDENTITIES.json").open("x") as stream:
        json.dump({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(products)}, stream, indent=2)
        stream.write("\n")
    return dict(figures=4, report="REPORT_ZH.md", comparison_groups=len(comparisons))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    print(json.dumps(make(parser.parse_args().output), sort_keys=True))
