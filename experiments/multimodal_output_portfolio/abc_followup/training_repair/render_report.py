"""Render the separately registered reference repair without selecting a new winner."""

import argparse
import json
from pathlib import Path
import shutil

from ...abc_recovery.base_recovery import file_sha


NAMES = {
    "mean": "固定的新 mean continuation",
    "old_constraint": "旧 warm-floor 风险约束模型",
    "matched_floor": "强参考，初始乘子 0",
    "matched_floor_warmdual": "强参考，初始乘子 1（主候选）",
}


def bounds(record, scale=1):
    low, high = record["interval"]
    return f"{scale * record['gain']:+.6f} [{scale * low:+.6f}, {scale * high:+.6f}]"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    destination = args.output
    analysis = json.loads(args.analysis.read_text())
    protocol_path = destination / "EVALUATION_PROTOCOL.json"
    if analysis["status"] != "completed" or analysis["protocol_sha256"] != file_sha(protocol_path):
        raise ValueError("Only the complete registered analysis can be published")
    training = json.loads((destination / "TRAINING_RESULTS.json").read_text())
    processes = {}
    for phase in ("training", "evaluation", "analysis"):
        path = args.runs / f"{phase}-001.process.json"
        receipt = json.loads(path.read_text())
        if receipt["exit_code"] != 0:
            raise ValueError("An experimental process did not finish successfully")
        processes[phase] = receipt
        if phase != "training":
            shutil.copyfile(path, destination / f"{phase.upper()}_PROCESS_RECEIPT.json")
            shutil.copyfile(args.runs / f"{phase}-001.process.registration.json",
                            destination / f"{phase.upper()}_PROCESS_REGISTRATION.json")
    shutil.copyfile(args.analysis, destination / "RESULTS.json")
    primary, secondary = (analysis["observers"][key] for key in ("primary", "secondary"))
    main_result = primary["comparisons"][0]
    outcome = "通过" if analysis["primary_conjunction_passed"] else "未通过"
    lines = ["# ABC4：强成功率参考与初始对偶乘子的独立修复实验", "",
        f"新的 1,000 个来源对上，预登记的联合主门槛**{outcome}**。主候选始终是 `matched_floor_warmdual`，参考始终是 `mean`。",
        f"联合 CE 差为 **{bounds(main_result['CE'])}**；精确成功率差为 **{bounds(main_result['success'], 100)} 个百分点**。",
        "两项分别使用名义 97.5% 区间；通过条件是 CE 下端 > 0，成功率差下端 ≥ 0，成功率容忍边际为零。",
        "没有根据这次评价改选另一训练臂、另一个 seed、checkpoint、容忍边际或观察器。", "",
        "## 为什么单独开展这一轮", "",
        "[前一项完整训练实验](../training/REPORT.md)保留原结果：风险约束候选相对新均值参考的 CE 提高，",
        "但成功率下降，联合门槛失败。其优化中的成功率参考是更弱的旧 warm mean，而正式比较用的是新 mean continuation。",
        "达到弱参考的成功率并不推出达到强参考。本轮把这一具体错位与初始乘子的贡献分开检验。",
        "这是由已观察的失败启发、重新登记且使用新来源的研究轮次；不把旧 final 改写为成功，",
        "也不声称多个自适应研究轮次共同具有预设的全局第一类错误控制。", "",
        "| 模型 | 成功率优化参考 | 初始乘子 | 作用 |", "| --- | --- | ---: | --- |",
        "| mean | 无该约束 | — | 已冻结强参考，不重新训练 |",
        "| old_constraint | 固定旧 warm mean | 0 | 已冻结的旧失败配方 |",
        "| matched_floor | 固定同 seed 的新 mean | 0 | 与 old_constraint 的比较只改变参考 |",
        "| matched_floor_warmdual | 固定同 seed 的新 mean | 1 | 与 matched_floor 的比较只改变初始乘子 |", "",
        "## 训练与真实输出", "",
        "两种新配方各训练五个 seed：17、29、43、59、71。共同从旧 warm mean 开始，各执行 400 个 Adam 更新，",
        "学习率 0.0001；每步 16 个条件、每条件 8 个实际随机终端输出。条件、候选抽样和参考抽样日程的摘要与前一轮逐模型吻合。",
        "固定执行 `refine_image → refine_text`，没有基于未保留随机草稿的隐藏选择。",
        "每个候选和参考图文输出均写入 NPZ、flush/fsync、关闭、重新打开并核对内容后，才交给冻结观察器评分。", "",
        "目标为 `(E exp(-2 U)-1)/2 + 0.05 L_supervised + lambda_old P(failure)`。当前梯度只使用本批结果出现前的乘子；",
        "下一批乘子更新为 `clip(lambda_old + 0.1*(success_reference-success_candidate), 0, 5)`。",
        "没有辅助项时，最小化该风险矩等价于最大化 CE；有固定辅助项后不声称整体目标仍完全等价。",
        "有限 400 步、有限乘子上限并不构成总体约束、收敛或全局最优证书。所有模型固定取最后一步。", "",
        "| Seed | matched_floor 最终乘子 | warmdual 最终乘子 |", "| --- | ---: | ---: |"]
    for seed in analysis["training_seeds"]:
        dual = {row["arm"]: row["dual_final"] for row in training["models"] if row["seed"] == seed}
        lines.append(f"| {seed} | {dual['matched_floor']:.6f} | {dual['matched_floor_warmdual']:.6f} |")
    lines += ["", "乘子的实测终值仅描述优化状态，不能替代留出成功率检验。", "",
        "## 新来源分配与防止重复计数", "",
        "评价使用原 manifest 中尚未分配的全部 2,000 张不同原图，组成 1,000 个来源对。",
        "只读审计对原始 ID 与像素 SHA 分别查重：与其余全部 13 个角色均无交集，包含整个已存在的 test 角色，",
        "因此也排除了刚完成的控制、旧训练以及 native calibration/verification 的来源。",
        "对 24,358 个 JSON/JSONL 共 1,880,634,756 字节的既有记录检查，不按文件大小跳过；",
        "这些候选 ID 只出现在原始来源目录，没有发现非目录执行记录。一个增长中的成本记录按打开时前缀审计，范围写明。",
        "该审计支持保留工作区中的来源未使用性，不证明不可访问历史系统或作者层面的独立性。", "",
        "原 `load_roles` 拒绝 unallocated 的保护保持不变。本轮以独立 `ROLE_ASSIGNMENT.json` 正式分配新 `repair_test` 角色；",
        "新 loader 在完整 20 模型评价协议、分配 SHA 和访问登记全部一致后，才实际构造该角色。",
        "全部新模型与参考模型身份先发布 GitHub，之后才首次打开这批来源的评价输出。", "",
        "评价有 20 个固定模型、1,000 个来源对、8 个输入视图、2 个输出情景，共 **320,000 个实际图文输出**。",
        "独立来源单位仍是 1,000 对，训练随机性只有五个 seed；不能把输出、视图、情景或重放当作新的独立 N。",
        "4,000 次 crossed bootstrap 同时重采样 seed 与来源，保留处理臂、视图和情景的配对。",
        "CE 先在每个 seed 内计算，再平均五个 seed。主项是名义 97.5% 百分位区间，其他比较均为描述性 95%；",
        "五个训练 seed 的名义覆盖不提供精确有限样本保证。", "",
        "## 主观察器的全部处理臂", "",
        "| 模型 | 联合 CE | 平均效用 | 精确成功率 | 完成率 | 损失 CVaR90 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for arm, name in NAMES.items():
        cell = primary["cells"][arm]
        cvar = cell["loss_tails"]["output_level"]["mean_across_seed_summaries"]["cvar"]
        lines.append(f"| {name} | {cell['utility']['joint_ce']:.6f} | {cell['mean_metrics']['utility']:.6f} | {100*cell['mean_metrics']['success']:.4f}% | {100*cell['mean_metrics']['complete']:.4f}% | {cvar:.6f} |")
    lines += ["", "完成率只表示图像和非空文本载体实际存在。CVaR90 是每个模型最坏 10% 输出的经验损失尾均值，再平均模型。", "",
        "| 候选 − 参考 | CE 差及区间 | 成功率差及区间（百分点） | 地位 |",
        "| --- | ---: | ---: | --- |"]
    for row in primary["comparisons"]:
        lines.append(f"| {row['candidate']} − {row['reference']} | {bounds(row['CE'])} | {bounds(row['success'], 100)} | {'主检验，97.5%' if row['primary'] else '描述性，95%'} |")
    reference_change = primary["comparisons"][3]
    initial_dual_change = primary["comparisons"][4]
    lines += ["", "`matched_floor − old_constraint` 隔离参考变化；`warmdual − matched_floor` 隔离初始乘子变化。",
        "这些描述性比较不能取代预先固定的主候选与强参考比较，也不能将合成变化全部归因于风险偏好。", "",
        "当前只识别这两条条件比较。没有训练 weak-floor＋初始乘子1这一臂，因此不是完整的 reference×initial-dual 因子设计，不能识别其交互项。", "",
        "### 这次修复识别了什么", "",
        f"仅更换参考时，成功率差为 **{bounds(reference_change['success'], 100)} 个百分点**，CE 差为 **{bounds(reference_change['CE'])}**。",
        "这为该训练配方中的参考错位提供了直接的描述性机制证据：它能修复相对旧配方的成功率缺口。",
        "但相对旧配方的改善不推出相对新 mean 的零边际非劣性已经得到统计支持。", "",
        f"再改变初始乘子时，CE 差为 **{bounds(initial_dual_change['CE'])}**，成功率差为 **{bounds(initial_dual_change['success'], 100)} 个百分点**。",
        "本轮没有证据支持把更强的初始惩罚当作额外成功率收益；它消耗了风险效用。",
        "这些是同一新留出上的描述性比较，不增设新的主门槛，也没有由它们再选择最终候选。", "",
        "## 第二冻结观察器", "",
        "第二观察器没有参与梯度、乘子更新或 checkpoint 选择。以下为观察器敏感性分析，均为描述性 95% 区间。", "",
        "| 候选 − 参考 | CE 差及区间 | 成功率差及区间（百分点） |", "| --- | ---: | ---: |"]
    for row in secondary["comparisons"]:
        lines.append(f"| {row['candidate']} − {row['reference']} | {bounds(row['CE'])} | {bounds(row['success'], 100)} |")
    lines += ["", "主观察器区间跨零不表示主候选与 mean 等效或无害；成功率区间仍允许下降。第二观察器对主候选相对 mean 的成功率还给出负向描述性区间，必须一并保留。"]
    lines += ["", "## 错误提示与缺失模态", "",
        "所有视图均属于同一批来源，不构成额外验证集。下表只描述主候选相对 mean 的逐视图差，主门槛仍使用冻结的全视图汇总。", "",
        "| 输入视图 | CE 差 | 成功率差（百分点） |", "| --- | ---: | ---: |"]
    candidate = primary["cells"]["matched_floor_warmdual"]["by_view"]
    reference = primary["cells"]["mean"]["by_view"]
    for view in analysis["views"]:
        lines.append(f"| {view} | {candidate[view]['CE']-reference[view]['CE']:+.6f} | {100*(candidate[view]['success']-reference[view]['success']):+.4f} |")
    lines += ["", "## 完整实际成本与已完成检查", "",
        "| 精确子进程 | 墙钟秒 | CPU 秒 | 峰值 RSS（MiB） |", "| --- | ---: | ---: | ---: |"]
    for phase, receipt in processes.items():
        lines.append(f"| {phase} | {receipt['wall_ns']/1e9:.6f} | {receipt['child_cpu_ns']/1e9:.6f} | {receipt['exact_child_peak_rss_bytes_linux']/2**20:.2f} |")
    lines += ["", "新增训练共 10 个模型、4,000 次更新，候选与固定参考各执行 512,000 个真实输出；参考执行也是实际训练成本。",
        "表中由 wait4 精确子进程 PID 记录，包含进程启动、导入、完整工作、写盘与退出。",
        "训练使用两个线程；运行于共享 Linux 宿主，评价末期与语音 final 短暂重叠。",
        "上述 batch 评价时间不是单请求 P50/P95，不能与控制线的逐请求延迟混用。",
        "旧模型训练的完整成本另见前一实验，不能因本轮复用而称其历史成本为零；pilot、来源审计和工具安装未混入这张正式阶段表。", "",
        "正式训练前执行真实两步、两个新臂、一个 seed 的历史来源 pilot，共 512 个候选及 512 个参考输出。",
        "目标数学复用此前精确枚举验证的可预测对偶梯度；新角色/模型/来源/数据完整性四项测试通过。",
        "独立 agent 审阅了强参考与初始乘子的分离、新来源审计和显式角色 loader；未依赖 CI。", "",
        "## 证据、复现与结论范围", "",
        "- [TRAINING_PROTOCOL.json](TRAINING_PROTOCOL.json)：打开新来源前冻结的训练配方。",
        "- [EVALUATION_PROTOCOL.json](EVALUATION_PROTOCOL.json)：20 个固定模型、来源、观察器和主检验。",
        "- [SOURCE_ALLOCATION.json](SOURCE_ALLOCATION.json) 与 [ROLE_ASSIGNMENT.json](ROLE_ASSIGNMENT.json)：新来源审计与正式角色分配。",
        "- [TRAINING_RESULTS.json](TRAINING_RESULTS.json) 与 [RESULTS.json](RESULTS.json)：逐模型训练摘要、完整处理臂、尾部、视图及比较。",
        "- `*_PROCESS_RECEIPT.json`、`*_PROCESS_REGISTRATION.json`、[VALIDATION.json](VALIDATION.json)：完整过程身份与成本。",
        "- `protocol.py`、`train.py`、`evaluate.py`、`analysis.py`：执行入口；先训练、冻结全部模型，再首次评价新角色。", "",
        "本结果只适用于固定的小型图文生成器、冻结目标与来源；它不验证全模态模型或全局 Merton/HJB 最优组合。",
        "本轮原始输出、权重与逐行日志仅保留 SHA 和必要聚合证据，按要求不推 GitHub。",
        f"评价协议 SHA-256：`{analysis['protocol_sha256']}`。结果 SHA-256：`{file_sha(args.analysis)}`。", ""]
    (destination / "REPORT.md").write_text("\n".join(lines))
    print(json.dumps({"report": str(destination / "REPORT.md"),
                      "primary_conjunction_passed": analysis["primary_conjunction_passed"]}))


if __name__ == "__main__":
    main()
