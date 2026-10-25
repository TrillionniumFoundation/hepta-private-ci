"""Publish compact measured evidence and a readable matched-training report."""

import argparse
import json
from pathlib import Path
import shutil

from ...abc_recovery.base_recovery import file_sha


NAMES = {"mean": "新均值训练", "risk": "新风险训练", "risk_success": "新风险＋成功率约束训练",
         "warm_mean": "固定旧均值模型"}


def bounds(record, scale=1):
    low, high = record["interval"]
    return f"{scale * record['gain']:+.6f} [{scale * low:+.6f}, {scale * high:+.6f}]"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    analysis = json.loads(args.analysis.read_text())
    if analysis["status"] != "completed":
        raise ValueError("Only a complete, frozen-census analysis may be published")
    destination = args.output
    protocol = json.loads((destination / "EVALUATION_PROTOCOL.json").read_text())
    if analysis["protocol_sha256"] != file_sha(destination / "EVALUATION_PROTOCOL.json"):
        raise ValueError("Analysis and published protocol differ")
    training = json.loads((destination / "TRAINING_RESULTS.json").read_text())
    processes = {}
    for phase in ("training", "evaluation", "analysis"):
        path = args.runs / f"{phase}-001.process.json"
        receipt = json.loads(path.read_text())
        if receipt["exit_code"] != 0:
            raise ValueError("A primary process did not finish successfully")
        processes[phase] = receipt
        if phase != "training":
            shutil.copyfile(path, destination / f"{phase.upper()}_PROCESS_RECEIPT.json")
            registration = args.runs / f"{phase}-001.process.registration.json"
            shutil.copyfile(registration, destination / f"{phase.upper()}_PROCESS_REGISTRATION.json")
    shutil.copyfile(args.analysis, destination / "RESULTS.json")
    outcome = "通过" if analysis["primary_conjunction_passed"] else "未通过"
    main = analysis["observers"]["primary"]["comparisons"][0]
    primary = analysis["observers"]["primary"]
    secondary = analysis["observers"]["secondary"]
    lines = ["# ABC4：实际输出风险训练与成功率约束", "",
        f"预先登记的联合主门槛**{outcome}**。候选为 `risk_success`，参考为相同训练预算的新 `mean`；",
        f"联合 CE 差为 **{bounds(main['raw_joint_CE'])}**，精确成功率差为 **{bounds(main['success_probability_difference'], 100)} 个百分点**。",
        "两项均为名义 97.5% 区间。通过要求分别为下端点 > 0、下端点 ≥ 0；成功率容忍边际为零。", "",
        "## 问题与实际实现", "",
        "上一轮风险训练提高了风险效用，但成功率点估计下降。本轮以固定旧均值模型为共同起点，",
        "对五个 seed 各执行三组新的生成器参数训练。每个模型 400 个 Adam 更新；每步 16 个条件、每条件 8 个实际随机输出。",
        "三组共享训练来源、条件与随机数日程，均执行独立抽样的固定参考生成器，以匹配参考计算成本。", "",
        "| 训练臂 | 实际目标 |", "| --- | --- |",
        "| mean | 负均值效用＋0.05 监督辅助目标 |",
        "| risk | `(E exp(-2 U)-1)/2`＋0.05 监督辅助目标 |",
        "| risk_success | risk 目标＋可预测的对偶乘子×实际失败概率 |", "",
        "当前梯度使用观察当前输出之前的乘子；下一步乘子按独立参考与候选的成功率差投影更新，范围 [0,5]、步长 0.1。",
        "每次实际图文输出先写入 NPZ、flush/fsync、关闭并重新打开，核对内容摘要，然后由冻结观察器评分。",
        "固定生成路径不根据被丢弃的随机草稿选择动作；终端保留输出的概率给出本路径的得分函数梯度。",
        "保留第 400 步模型，没有按留出结果挑 checkpoint。", "",
        "优化中的约束参考是**旧 warm mean**，正式评价的强参考是**新 mean continuation**。这两个比较不能互换。",
        "风险变换与 CE 在没有额外项时有相同最优解；加入固定权重辅助项后，不能声称两者仍是完全相同的整体目标。",
        "有限步、带乘子上限的随机训练也不提供总体可行性或全局最优证明。", "",
        "## 冻结来源与统计单位", "",
        "在全部 15 个新模型和 5 个固定参考模型冻结并发布后，打开 256 个新来源对（512 张不同原图），",
        "每个来源有 8 个预定输入视图、2 个输出随机情景；20 个模型共 81,920 个实际终端输出。",
        "这些来源与本轮控制成本实验共享，不增加独立 N；两项实验的随机数命名空间不同，不拼接一项的质量与另一项的成本。",
        "冻结的来源审计检查个体 ID 和像素摘要重叠；没有作者聚类元数据，无法证明作者层面的独立性。", "",
        "风险 CE 先在每个训练 seed 内计算，再等权平均五个模型。4,000 次配对 bootstrap 同时重采样来源与训练 seed，",
        "保留全部视图、输出情景和处理臂的对应关系。五个 seed 的名义百分位区间不构成精确覆盖保证；",
        "额外报告固定这五个模型、仅重采样来源的区间。其他比较和第二观察器均为描述性分析。", "",
        "## 主观察器结果", "",
        "| 模型 | 联合 CE | 平均效用 | 精确成功率 | 输出完成率 | 输出损失 CVaR90 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for arm, name in NAMES.items():
        cell = primary["cells"][arm]
        loss = cell["loss_tails"]["output_level"]["mean_across_seed_summaries"]["cvar"]
        lines.append(f"| {name} | {cell['raw_utility']['joint_ce']:.6f} | {cell['mean_metrics']['utility']:.6f} | {100*cell['mean_metrics']['success']:.4f}% | {100*cell['mean_metrics']['complete']:.4f}% | {loss:.6f} |")
    lines += ["", "输出完成率指已核对的图像载体与非空文本是否存在，不代表事实正确。CVaR 是逐模型实际输出损失最坏 10% 的精确经验尾均值，再平均模型。", "",
        "| 比较：候选 − 参考 | CE 差及区间 | 成功率差及区间（百分点） | 地位 |",
        "| --- | ---: | ---: | --- |"]
    for row in primary["comparisons"]:
        lines.append(f"| {row['candidate']} − {row['reference']} | {bounds(row['raw_joint_CE'])} | {bounds(row['success_probability_difference'],100)} | {'主检验，97.5%' if row['primary'] else '描述性，95%'} |")
    conditional = main["fixed_five_seed_source_intervals"]
    lines += ["", f"固定五个模型、仅来源重采样：CE **{bounds(conditional['CE'])}**；成功率 **{bounds(conditional['success'],100)} 个百分点**。",
        "这些区间只适用于这五个已拟合模型，不能替代跨训练 seed 的主区间。", "", "## 第二冻结观察器", "",
        "该观察器未参与本轮梯度或 checkpoint 选择，其结果是观察器敏感性检查。", "",
        "| 比较 | CE 差及描述性 95% 区间 | 成功率差及描述性 95% 区间（百分点） |",
        "| --- | ---: | ---: |"]
    for row in secondary["comparisons"]:
        lines.append(f"| {row['candidate']} − {row['reference']} | {bounds(row['raw_joint_CE'])} | {bounds(row['success_probability_difference'],100)} |")
    lines += ["", "## 实际成本与验证", "",
        "| 完整子进程 | 墙钟秒 | CPU 秒 | 峰值 RSS（MiB） |", "| --- | ---: | ---: | ---: |"]
    for phase, receipt in processes.items():
        lines.append(f"| {phase} | {receipt['wall_ns']/1e9:.3f} | {receipt['child_cpu_ns']/1e9:.3f} | {receipt['exact_child_peak_rss_bytes_linux']/2**20:.2f} |")
    lines += ["", f"实际训练共 {len(training['models'])} 个新模型、{analysis['new_optimizer_updates']:,} 次优化更新，候选与固定参考分别执行 {sum(m['candidate_rows'] for m in training['models']):,} 个输出。",
        "计时来自 Linux 对精确子进程 PID 的 wait4，包含启动、导入、工作、输出和退出；未把共享主机当作隔离硬件。",
        "本表不包含既有模型的历史训练成本、试运行或验证工具运行，也不能用批量评价时间宣称单请求 P50/P95 延迟。",
        "主训练成本已完整计入本轮训练子进程；同一参考重复执行不增加来源样本量。", "",
        "4 项目标/梯度测试、4 项评价身份/完整性测试，以及真实两步三臂试运行和历史来源实际输出读回验证，在正式运行前完成。",
        "完整性检查拒绝缺失处理臂、重复重放、错误来源角色或被修改的评价文件。详细记录见 `VALIDATION.json`；未依赖 CI。", "",
        "## 解释边界与复现入口", "",
        "本结果检验一个明确的小型图文生成器训练配方。控制器、真实文字/语音和原生 admission 各有独立协议与报告。",
        "本实验不声称全模态大模型、总体成功率约束证书、全局 Merton/HJB 最优解或生产更新授权已闭合。", "",
        "- `TRAINING_PROTOCOL.json`：训练目标、固定日程、起点及执行源码身份。",
        "- `EVALUATION_PROTOCOL.json`：留出开启前的全部模型、来源、观察器和主检验冻结。",
        "- `TRAINING_RESULTS.json`、`RESULTS.json`：完整聚合结果、逐 seed/视图统计、尾部与比较。",
        "- `*_PROCESS_RECEIPT.json` 与 `*_PROCESS_REGISTRATION.json`：精确进程成本、命令与日志身份。",
        "- `train.py`、`evaluate.py`、`analysis.py`：可执行工作流。模型权重、原始输出与逐行记录不推 GitHub。", "",
        f"评价协议 SHA-256：`{analysis['protocol_sha256']}`。分析结果 SHA-256：`{file_sha(args.analysis)}`。", ""]
    (destination / "REPORT.md").write_text("\n".join(lines))
    print(json.dumps({"report": str(destination / "REPORT.md"), "primary_conjunction_passed": analysis["primary_conjunction_passed"]}))


if __name__ == "__main__":
    main()
