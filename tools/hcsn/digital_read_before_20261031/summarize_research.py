#!/usr/bin/env python3
"""Render the completed frozen experiment into a Chinese research report.

Accepts byte-identical original primary evidence only, including its original
training and timing receipts. New runs need their own audit and report. This
tool does not train, select, mutate, or execute any model.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORIGINAL_SUMMARY_SHA256 = "f98f7441f5ca64e7592c82ffa3069df6aa32032cef8e7ceb294cca2eb13b2e25"
ORIGINAL_RESULTS_SHA256 = "041bc3a580b77788c10a391abe5f06db52d71e5ec6dddac769d8f05ffd1b7155"
FAMILIES = ("ordinary_base", "ordinary_bank", "clocked_bank", "first_passage_bank", "raw_history")
LABELS = dict(ordinary_base="Ordinary + 多项式", ordinary_bank="Ordinary + digital bank",
              clocked_bank="Clocked + digital bank", first_passage_bank="First-passage + digital bank",
              raw_history="Raw history", bayes="TRAIN 拟合 Bayes + DP")


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require_original(path, expected):
    actual = sha(path)
    if actual != expected:
        raise ValueError(
            f"Original evidence SHA-256 mismatch: {path}; expected {expected}, got {actual}. "
            "This renderer accepts only byte-identical original evidence. "
            "A new run requires its own matching audit and report."
        )


def mean(values):
    values = list(values)
    return math.fsum(values)/len(values)


def f(value, places=4):
    return f"{value:.{places}f}"


def table(headers, rows):
    return "\n".join(["| " + " | ".join(headers) + " |",
                      "| " + " | ".join("---" for _ in headers) + " |",
                      *["| " + " | ".join(str(x) for x in row) + " |" for row in rows]])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, required=True, help="Original or byte-identically restored confirmation")
    parser.add_argument("--training", type=Path, required=True, help="Original or byte-identically restored primary fits")
    parser.add_argument("--timed-training", type=Path, required=True, help="Original or byte-identically restored timed replay")
    parser.add_argument("--report", type=Path, default=HERE/"REPORT.md", help="Markdown output; independent of --tables")
    parser.add_argument("--tables", type=Path, default=HERE/"evidence/RESEARCH_TABLES.json",
                        help="JSON output; independent of --report")
    args = parser.parse_args()
    protocol = read(HERE/"protocol.json")
    freeze, source = read(HERE/"MODEL_FREEZE.json"), read(HERE/"SOURCE_FREEZE.json")
    try:
        require_original(args.runs/"SUMMARY.json", ORIGINAL_SUMMARY_SHA256)
        require_original(args.runs/"RESULTS.json", ORIGINAL_RESULTS_SHA256)
        for fit in protocol["fits"]:
            primary_index = read(HERE/f"evidence/training/fit_{fit}/PACKAGING_INDEX.json")
            timed_index = read(HERE/f"evidence/training_timed/fit_{fit}/PACKAGING_INDEX.json")
            require_original(args.training/f"fit_{fit}/data/fit_{fit}_data.json",
                             freeze["training_data_sha256"][str(fit)])
            require_original(args.training/f"fit_{fit}/models/COMPLETE.json",
                             primary_index["complete"]["raw_sha256"])
            measurements = [member for member in timed_index["full_fit_members"]
                            if member["path"] == "PROCESS_MEASUREMENT.json"]
            if len(measurements) != 1:
                raise ValueError(f"Expected one original timing receipt for fit {fit}")
            require_original(args.timed_training/f"fit_{fit}/PROCESS_MEASUREMENT.json",
                             measurements[0]["sha256"])
        for model in freeze["models"]:
            require_original(args.training/f"fit_{model['fit']}/models/{model['family']}.json",
                             model["model_sha256"])
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if args.report.resolve() == args.tables.resolve():
        parser.error("--report and --tables must name different output files")
    summary, results = read(args.runs/"SUMMARY.json"), read(args.runs/"RESULTS.json")
    audit = read(HERE/"evidence/INDEPENDENT_CONFIRMATION_AUDIT.json")
    bank_audit = read(HERE/"evidence/BANK_AUDIT.json")
    assert audit["status"] == "passed" and summary["number_of_episodes"] == len(results) == 4800
    assert summary["published_model_commit"] == read(args.runs/"STARTED.json")["published_model_commit"]
    for path, expected in freeze["source_sha256"].items():
        assert sha(HERE.parents[2]/path) == expected
    metric = {(r["split"], r["family"], r["controller"]): r["metrics"] for r in summary["aggregate"]}
    fits = {(r["fit"], r["split"], r["family"], r["controller"]): r["metrics"] for r in summary["fit_means"]}
    assert len(metric) == 24 and len(fits) == 120
    def m(split, family, controller, name="utility"):
        return metric[(split, family, controller)][name]
    for key, metrics in metric.items():
        expected = mean(r["metrics"]["utility"] for r in results
                        if (r["split"], r["family"], r["controller"]) == key)
        assert abs(metrics["utility"]-expected) < 1e-12
    interactions = []
    for family in ("clocked_bank", "first_passage_bank"):
        for split in ("iid", "ood"):
            A, B = m(split, "ordinary_bank", "fixed"), m(split, "ordinary_bank", "value")
            C, D = m(split, family, "fixed"), m(split, family, "value")
            deltas = []
            for fit in protocol["fits"]:
                a, b = (fits[(fit, split, "ordinary_bank", c)]["utility"] for c in ("fixed", "value"))
                c, d = (fits[(fit, split, family, c)]["utility"] for c in ("fixed", "value"))
                deltas.append(dict(fit=fit, B_minus_A=b-a, C_minus_A=c-a, D_minus_B=d-b,
                                   D_minus_C=d-c, interaction=(d-c)-(b-a)))
            interactions.append(dict(family=family, split=split, A=A, B=B, C=C, D=D,
                                     B_minus_A=B-A, C_minus_A=C-A, D_minus_B=D-B,
                                     D_minus_C=D-C, interaction=(D-C)-(B-A), fits=deltas))
    training, physical = [], []
    all_complete = {fit: read(args.training/f"fit_{fit}"/"models/COMPLETE.json") for fit in protocol["fits"]}
    for family in FAMILIES:
        records = [all_complete[fit]["models"][family] for fit in protocol["fits"]]
        row = dict(family=family, allocated=records[0]["allocated_parameters"],
                   active_coordinates=records[0]["effective_parameters"],
                   training_cpu_seconds=sum(r["training"]["cpu_seconds"] for r in records),
                   training_wall_seconds=sum(r["training"]["wall_seconds"] for r in records),
                   export_cpu_seconds=sum(r["export_preparation"]["cpu_seconds"] for r in records),
                   model_bytes_mean=mean(r["model"]["bytes"] for r in records),
                   validation_initial_mean=mean(r["initial_validation"]["loss"] for r in records),
                   validation_final_mean=mean(r["final_validation"]["loss"] for r in records),
                   parameter_shift_l2_mean=mean(r["all_parameter_shift_l2"] for r in records),
                   raw_shift=[dict(fit=fit, shift=all_complete[fit]["models"][family]["raw_parameter_shift"]) for fit in protocol["fits"]])
        training.append(row)
        if family != "raw_history":
            values = [read(args.training/f"fit_{fit}"/"models"/f"{family}.json")["kernel"]["physical"] for fit in protocol["fits"]]
            physical.append(dict(family=family, means={k:mean(v[k] for v in values) for k in values[0]},
                                 fits=[dict(fit=fit, parameters=v) for fit,v in zip(protocol["fits"], values, strict=True)]))
    replays = [read(args.timed_training/f"fit_{fit}"/"PROCESS_MEASUREMENT.json") for fit in protocol["fits"]]
    assert all(r["returncode"] == 0 and r["primary_models_unchanged"] and
               all(x["byte_identical"] for x in r["model_equality"]) for r in replays)
    replay_cpu = sum(r["total_cpu_seconds"] for r in replays)
    native_rows = [r for r in results if r["family"] != "bayes"]
    native_totals = {k: sum(r["metrics"][k] for r in native_rows) for k in
                     ("cpu_seconds", "wall_seconds", "native_cpu_seconds", "native_wall_seconds",
                      "content_calls", "persistence_bytes", "events", "recovery_count", "failed_reads")}
    cost_fields = ("open_attempts", "successful_opens", "bytes_read", "artifact_load_nanos", "representation_nanos",
                   "neural_nanos", "selection_nanos", "propagation_nanos", "content_nanos", "persist_nanos")
    stage_totals = {k: sum(r[k] for r in audit["confirmation"]["native_cost_totals"]) for k in cost_fields}
    primary = summary["primary_contrasts"]
    assert len(primary) == 4
    all_fail = all(not row["benefit_gate"] for row in primary)
    if not all_fail:
        raise ValueError("This report's preregistered conclusion template requires review because a benefit gate passed")
    derived = dict(schema="digital-read-before-research-tables-v1", summary_sha256=sha(args.runs/"SUMMARY.json"),
                   results_sha256=sha(args.runs/"RESULTS.json"), protocol_sha256=sha(HERE/"protocol.json"),
                   model_freeze_sha256=sha(HERE/"MODEL_FREEZE.json"), auditor_sha256=sha(HERE/"evidence/INDEPENDENT_CONFIRMATION_AUDIT.json"),
                   reporting_script_sha256=sha(Path(__file__)), aggregate=summary["aggregate"],
                   primary_contrasts=primary, factorial_descriptive=interactions,
                   training=training, physical_parameters=physical, native_totals=native_totals,
                   native_stage_totals=stage_totals, timed_replay_cpu_seconds=replay_cpu,
                   timed_replays=replays, reporting_changes_numeric_core=False)
    lines = []
    lines.append("# Digital read-before：解析概率算子、有限脉冲单元与自主读取策略研究报告\n\n版本：2026-11-01；全部结果来自预先冻结的实现和 25 个最终模型。")
    lines.append(f"""## 1. 研究结论

**本轮完成了可训练、可原生执行、可带 ACK 恢复的有限单元原型，但没有证实预先登记的任务收益。** 四项主比较的调整区间全部未达到实际收益门槛。First-passage 相对普通 Brownian bank 的 value 控制器，IID 平均效用差为 {f(primary[0]['mean'],6)}，OOD 为 {f(primary[1]['mean'],6)}。Bank 相对多项式基线的 value 控制器，IID 差为 {f(primary[2]['mean'],6)}，OOD 为 {f(primary[3]['mean'],6)}；后者正均值也未通过预登记门槛。

更直接的负面结果是：**全部五个学习模型族的 value 控制器，在 IID 和 OOD 上都低于本族 fixed 控制器的平均效用。** OOD 的 clocked/value 为 {f(m('ood','clocked_bank','value'),6)}，first-passage/value 为 {f(m('ood','first_passage_bank','value'),6)}，均低于立即 STOP 的确定性零效用基线。较少读取并没有保住任务收益。

同信息来源的 TRAIN 拟合 Bayes+DP 从 fixed 到 value，IID 为 **{f(m('iid','bayes','fixed'),7)} → {f(m('iid','bayes','value'),7)}**，OOD 为 **{f(m('ood','bayes','fixed'),7)} → {f(m('ood','bayes','value'),7)}**。当前任务存在可利用的决策价值，当前学习器尚未稳定提取出来。Raw-history/value 的 IID/OOD 为 {f(m('iid','raw_history','value'),7)} / {f(m('ood','raw_history','value'),7)}，也高于 FPT/value 的 {f(m('iid','first_passage_bank','value'),7)} / {f(m('ood','first_passage_bank','value'),7)}。原生一致性、概率守恒和梯度验证支撑实现可信度，不能替代收益证据。本轮是一个有限单元加小型 MLP 的受限任务实验，没有验证新型大规模或通用语言 SNN。来源：[完整确认汇总](evidence/confirmation/SUMMARY.json)、[独立最终审计](evidence/INDEPENDENT_CONFIRMATION_AUDIT.json)、[可复算研究表](evidence/RESEARCH_TABLES.json)。""")
    lines.append(f"""## 2. 冻结顺序、任务和样本单位

源码版本为 [`{source['source_commit']}`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/{source['source_commit']})；源码冻结记录提交为 `{freeze['source_freeze_commit']}`。全部 25 个模型及其哈希在提交 [`{summary['published_model_commit']}`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/{summary['published_model_commit']}) 公开到该私有仓库后，才生成本轮新的 IID/OOD 确认世界。SOURCE_FREEZE 和 MODEL_FREEZE 保留独立文件身份；确认程序逐项检查冻结源码和模型。没有用 validation 选择 checkpoint：所有模型均采用登记的第 240 次更新。[源码冻结](SOURCE_FREEZE.json)、[模型冻结](MODEL_FREEZE.json)、[协议](protocol.json)。

这是按登记规则合成的部分观察任务：隐藏目标、带标记符号的 packets、费用、时延和缺失均由任务生成器产生；文件访问、FullHX 推理和 owner 执行则实际发生。自然语言生产工作负载和真实市场数据均未纳入本轮。

任务有一个二元隐藏目标、6 个决策时隙和最多 3 次读取预算，动作固定为 STOP、WAIT、READ、REPAIR、SUBMIT_0、SUBMIT_1。整个未来的 duration/reliability/read-price/read-delay schedule 对所有策略公开。READ 先扣费并创建 pending，延迟 1 或 2 个时隙；只有到期边界才实际打开源 packet、执行固定 FullHX 并产生观察。未观察内容、隐藏标签和教师 posterior/Q 不进入学习策略输入。STOP/SUBMIT 会取消 pending，保留已花费的时间和费用，不再读取内容。缺失或无效 packet 计费并进入 broken；REPAIR 显式清除该状态。[任务定义](DESIGN.md)、[任务实现](task.py)、[原生 owner](native/owner.rs)。

效用为终止奖励减去实际任务费用：正确提交 +1，错误提交 −1，STOP 为 0；费用包括读取、修复，以及公开的逻辑 duration×latency price。逻辑时间费用不是测得的主机 CPU 成本，两者独立报告。

五个独立 fit 为 {', '.join(map(str,protocol['fits']))}；每 fit 64 个 TRAIN 世界、16 个 validation 世界，另有 64 条平衡校准样本估计 FullHX confusion。每 fit 冻结五个模型，同一模型的参数同时用于 fixed/value。每 fit 各生成 40 个新 IID 世界和 40 个新 OOD 世界，共 400 个独立任务世界；12 个 family/controller 组合配对执行，得到 **4,800 个 episode：4,000 个实际 Rust owner、800 个 Python Bayes 参考**。每个 family/controller/split 有 200 个 episode，但推断单位是五个独立 fit，不能把 200 次 episode 当成 200 个独立训练重复。

IID 的 duration 为 0.5/1.0，reliability 为 0.65/0.85，read price 为 0.03/0.12，缺失率 0.08；OOD 同时变为 0.25/1.5、0.55/0.95、0.01/0.18、缺失率 0.16，并提高时间与修复价格。因此这里的 OOD 是登记的联合扰动，不是单变量归因实验。[确认数据与全部原始执行归档](evidence/confirmation/PACKAGING_INDEX.json)。""")
    lines.append(r"""## 3. 实际比较了哪些模型

共同神经头为 48 → 32 tanh → 7：36 个 public features 加 12 个 representation features，输出六个 Q 值和一个 belief logit。fixed 使用**自身学习的 belief**，阈值为 0.8；否则请求可用观察、等待 pending、修复失败，在期限或预算耗尽时提交。value 选择合法动作中 Q 最大者。两者不绕过神经头调用 owner 的后验。

| 模型族 | 动态与读出 | 对照作用 |
| --- | --- | --- |
| ordinary_base | 普通 Gaussian 端点转移，外侧尾质量折入边缘网格；位置的 2…10 次幂、位置本身、两个 mode flags | 同维多项式读出基线 |
| ordinary_bank | 相同普通动态，九个 digital call 概率、位置、mode flags | 解析概率特征的增量 |
| clocked_bank | 同一 Brownian law，区间终点落到边界外才产生事件并进入相应 refractory | 终点判定的事件单元 |
| first_passage_bank | 同一 Brownian law，killed transition 加竞争的上下首次退出质量 | 检测区间内已经退出的事件 |
| raw_history | 无 cell；六个已观察符号槽与六个有效 reliability 槽，未完成读取为零 | 学习型完整观察历史对照 |
| Bayes + DP | 使用 TRAIN 拟合的 confusion 和同一已读 history，计算 posterior 与有限任务 DP | 同信息来源的强参考，未使用 evaluator 的隐藏标签 |

所有学习族共享同一 head 形状、每 fit 的初始 head、240×128 的优化更新预算和相同 mini-batch 序列，head 都分配 1,799 个参数坐标。**这不是完全相同的有效容量实验。** ordinary 的 reset/recovery raw 坐标不参与任务计算，两个 refractory flags 在可达轨迹中恒为零，相应的 2×32=64 个 head 输入权重没有任务信号；代码的 active count 只扣除三个 inactive raw，没有扣除这 64 个权重。raw_history 保存的信息形态又不同。参数个数、计算量和表文件大小需要单独报告。这些对照比较已定义的模型架构与信息表示，尚不能完全隔离一个事件机制的因果效应。[模型代码](model.py)、[冻结模型独立审计](evidence/INDEPENDENT_MODEL_FREEZE_AUDIT.json)。

### Call/put 与解析 bank 的边界

活动态下采用同一自由 Brownian law 的九个概率：

\[
C_{h,k}(x)=\Phi\!\left(\frac{x+\mu h-k}{\sigma\sqrt h}\right),\qquad
P_{h,k}(x)=1-C_{h,k}(x),
\]

其中阈值为 boundary 的 −0.5、0、0.5 倍，horizon 为 0.25、0.75、1.5。这里只用九个 call 作为输入；put 由补概率确定，未作为另一套自由参数或额外容量。概率 bank 与相同 Gaussian/probit 数值对照一致，单凭金融命名不能宣称不同函数族。

其明确语义是 `free_endpoint_conditional_on_active`：给定当前活动状态、假设未来保持这一自由 drift/diffusion law 的端点概率。它**不包含**未来 reset、refractory、未来观察变化或任务动作，不能解释为真实任务成功率、未来脉冲概率或 reset-aware 多期预测。在 refractory 行，call/position 特征被活动态掩码置零，以 mode flags 标识；对应 call+put 质量为 active indicator，而不是把 refractory 强行解释为自由扩散概率为一。[bank 实现](bank.py)、[数学审计](evidence/BANK_AUDIT.json)。

### First-passage 仍然是有限投影和区间删失记录

所有 cell 有 15 个活动网格代表点、上下两个 refractory 状态，共 17 状态。clocked 的事件在区间末判定；first-passage 的一次 draw 记录的是“本区间结束前是否首次退出、从哪一侧退出”，**并没有采样或保存精确的区间内首次命中时间**。每区间最多一个新事件；原有 refractory 状态仅在区间末以 `1-exp(-rate×dt)` 释放到声明的 reset 分布，新事件不能在同一区间再次释放。

因此这里没有实现任意多次区间内 spike/reset 的精确连续 renewal 过程。连续 Brownian 核经有限 image 截断、网格投影和逐步重投影后，也不能直接继承全部连续半群结论。原生执行使用权重绑定的有限 transition/features 表，**不在每个动作现场重新计算 erf/image sums**；表生成、存储和加载都需计成本。[有限核边界](DESIGN.md)、[原生执行说明](native/README.md)。""")
    lines.append(r"""## 4. 训练目标及其实际证明范围

本轮是**有限 DP 教师监督训练**。独立于 cell 的随机合法行为轨迹提供实际读结果与前缀，教师依据 TRAIN 校准 law 计算每个历史的 posterior 和六动作 Q。训练对完整前缀产生的有限 cell 分布求和：

\[
L(\theta,\phi)=\frac1N\sum_i\sum_z p_\phi(z\mid h_i)
\left[\frac{\sum_{a\in A_i}(Q_\theta(h_i,z,a)-q_i^\star(a))^2}{|A_i|}
+0.25\,\operatorname{BCE}(\ell_\theta(h_i,z),p_i^\star)\right]
+10^{-4}\|\phi_{\rm active}\|^2.
\]

梯度包含 `p(z|完整前缀)` 本身、transition、读出、reset/recovery 路径及神经头；不是先取平均 feature 再计算非线性 loss，也不是只优化一个边缘事件概率。独立审计对真实 `train.expected_loss` 的完整短路径、分支共享前缀、有限和及各 raw 梯度作了核对。部署则硬采样一个 cell 状态，用该状态真实选择动作，RNG 被持久化。[训练实现](train.py)、[优化前独立审计](evidence/INDEPENDENT_PREFIT_AUDIT.json)。

这里的“精确梯度”限定于**所实现的有限数值核、固定行为状态分布和上述监督目标**。这不是自主策略回报的精确梯度，也不是 DQN 更新、policy-gradient 收敛结果，不能借用别处的 Q-learning 定理宣称本实验已取得收敛保证。固定行为分布与实际贪心策略访问状态的分布不同；教师又能通过 history 得到比压缩 cell 更完整的条件信息。这些都是实际收益可能落后的机制入口，当前验证没有消除它们。

使用 float64、AdamW、学习率 0.012、weight decay 0.0001、梯度裁剪 5，共 25×240=6,000 次登记更新。validation 仅诊断，不选择权重；测量重放也不增加独立 fit 数。""")
    lines.append("## 5. 完整任务效用\n\n下表为五个 fit 均值的平均；每格覆盖 5×40 个配对 episode。所有结果均保留。\n\n" + table(
        ["模型族", "IID fixed", "IID value", "OOD fixed", "OOD value"],
        [[LABELS[family], *(f(m(split,family,controller),6) for split,controller in (("iid","fixed"),("iid","value"),("ood","fixed"),("ood","value")))] for family in (*FAMILIES,"bayes")]))
    lines.append(f"""Raw-history/value 是本轮学习型 value 控制器中均值最高者，IID/OOD 为 {f(m('iid','raw_history','value'),6)} / {f(m('ood','raw_history','value'),6)}；它仍低于自身 fixed。固定控制器下，ordinary bank 相对多项式读出的 IID/OOD 描述性差为 {f(m('iid','ordinary_bank','fixed')-m('iid','ordinary_base','fixed'),6)} / {f(m('ood','ordinary_bank','fixed')-m('ood','ordinary_base','fixed'),6)}。这不能替代预登记的 value 主对比，不能在看到结果后换成“成功的主终点”。

Bayes 参考属于拟合 law 下的强参考：它不是真实分布已知的无限样本神谕。它的较高实际效用也不能解释成算法理论最优性的外推。其 Python 后端、内容模型复用和持久化条件与 Rust owner 不同，运行时间不能用来证明同后端下的算法加速。""")
    lines.append("## 6. 四项预登记区间与收益门槛\n\n两个主差值各在 IID/OOD 报告一次，共四项。每项使用五个 fit 的配对差值、df=4 的双侧 Student t 区间，以 Bonferroni 将整体 α=0.05 分给四项，所以每个区间置信水平为 98.75%。预登记门槛是**调整区间下限严格大于 +0.02 utility**。这是带小样本近似正态假设的推断，不是无条件保证；五个 fit 的区间很宽。\n\n" + table(
        ["主差值（均为 value）", "Split", "均值", "调整下限", "调整上限", "下限 > .02"],
        [["FPT bank − Ordinary bank" if r['name']=='first_passage_increment' else "Ordinary bank − Ordinary base", r['split'].upper(), f(r['mean'],6),f(r['lower'],6),f(r['upper'],6),"否"] for r in primary]))
    lines.append("四项区间均覆盖零，均未通过收益门槛。不能宣称 FPT 有稳定增益，也不能宣称 bank 在 value 路由下已有可靠收益；同样不能把未通过门槛说成已证明零效应、等效或无害。为避免平均数掩盖 seed 波动，下面保留全部独立 fit 差值：\n\n" + table(
        ["比较", "Split", *map(str,protocol['fits'])],
        [[r['name'],r['split'].upper(),*(f(x,6) for x in r['fit_differences'])] for r in primary]))
    lines.append("## 7. Clocked/FPT 的 2×2 描述性拆分\n\n对每个事件族，A=ordinary_bank/fixed，B=ordinary_bank/value，C=事件族/fixed，D=事件族/value。B−A 表示普通动态下切换控制器；C−A 表示固定控制器下更换动态；D−B 表示 value 下更换动态；(D−C)−(B−A) 是控制器增量的差。以下是描述性均值，不是新增通过多重性控制的确认主张。\n\n" + table(
        ["事件族", "Split", "B−A", "C−A", "D−B", "D−C", "交互差"],
        [[r['family'],r['split'].upper(),*(f(r[k],6) for k in ('B_minus_A','C_minus_A','D_minus_B','D_minus_C','interaction'))] for r in interactions]))
    lines.append("正的交互差只表示相对变化，不自动表示 D 好于 B、C 或零基线。该表的完整五-fit 分解见 [RESEARCH_TABLES.json](evidence/RESEARCH_TABLES.json)。独立审计在相同已达状态上计算 fixed/value 建议是否不同，可证明路由真实不同；建议分歧次数本身不证明这些变化有益。")
    lines.append(r"""## 8. 实际结果校准、教师遗憾和信息增益

以下指标采用正式运行的真实隐藏标签和终止结果，而不是拿教师 posterior 当作真实标签：

- **Brier**：每个 episode 内对决策时刻的 `(learned belief − actual label)^2` 取平均，再平均 episode；越小越好。
- **选中 Q 的未来回报 MSE**：预测 Q 与 `终止 reward − (终止 charges − 当前 charges)` 的差平方。它不扣两次已付费用；包含实际回报噪声及后续自主策略与教师最优续策的差，不能等同于训练时的教师 Q 拟合误差。
- **平均动作遗憾**：在实际访问的每个状态，计算拟合教师 `max Q* − Q*(实际动作)`。这依赖 TRAIN 拟合 law，不是分布无关的真实最优性证书。
- **信息增益**：相同拟合 law 下已读 history 的熵下降，单位 nats；是参考后验的信息量，不是神经元 forecast 的经验校准分数。

各控制器访问的状态和决策数不同，以下是实际策略分布上的指标；没有据此宣布同一条件状态下的普遍校准排序。[指标实现](metrics.py)、[独立逐决策复算](evidence/INDEPENDENT_CONFIRMATION_AUDIT.json) 服务于这些明确的定义。
""")
    for split in ("iid","ood"):
        lines.append(f"### {split.upper()}\n\n" + table(
            ["模型 / 控制器", "Brier", "未来回报 MSE", "动作遗憾", "信息增益 nats", "完成读取/episode"],
            [[family+" / "+controller,*(f(m(split,family,controller,k),5) for k in
                ("belief_brier","selected_q_remaining_return_mse","mean_action_regret","information_gain_nats","reads_completed"))]
             for family in (*FAMILIES,"bayes") for controller in ("fixed","value")]))
    lines.append("value 路由在若干模型中减少了读取和获得的信息，但 Q 的实际未来回报误差与动作遗憾没有相应改善。Bayes/value 的教师遗憾为零是其定义所致，不能当作新经验发现；它的实际 Brier 和 utility 仍由新标签检验。神经元内部事件概率的校验则是另一件事：抽样事件服从自身导出核，并不等于该事件对任务有用。")
    lines.append("### 事件与恢复的实际发生次数\n\n" + table(
        ["Split", "事件族 / 控制器", "事件/episode", "预测事件总概率/episode", "恢复/episode"],
        [[split.upper(),family+" / "+controller,*(f(m(split,family,controller,k),5) for k in ("events","predicted_events","recovery_count"))]
         for split in ("iid","ood") for family in ("clocked_bank","first_passage_bank") for controller in ("fixed","value")]))
    lines.append("## 9. 训练是否真正改变参数，以及实际训练成本\n\n以下 CPU/wall 为原始五个 fit 的优化循环累计量；export 为有限表准备 CPU，独立列出。模型大小是未压缩 JSON 平均值。其余初始化、诊断、序列化等成本包含于更外层计时，不能与嵌套计时重复相加。\n\n" + table(
        ["模型族", "分配/启用坐标", "训练 CPU s", "训练 wall s", "导出 CPU s", "模型 KiB", "validation loss 初→末", "参数变化 L2 均值"],
        [[r['family'],f"{r['allocated']} / {r['active_coordinates']}",f(r['training_cpu_seconds'],3),f(r['training_wall_seconds'],3),
          f(r['export_cpu_seconds'],4),f(r['model_bytes_mean']/1024,2),f"{f(r['validation_initial_mean'])} → {f(r['validation_final_mean'])}",f(r['parameter_shift_l2_mean'],4)] for r in training]))
    lines.append("所有最终 head 和参与计算的 cell 参数都有实际更新记录，ordinary 的三个不参与计算的 reset/recovery raw 坐标保持零。validation loss 下降证明了所定义教师目标的拟合改善，不等于自主动作效用改善。本轮的实际确认结果正好说明这两者不能替换。25 个模型均保留每一次梯度/更新记录，没有只挑一个好 seed。[原始训练归档](evidence/training/PACKAGING_ALL_PRIMARY.json)。")
    lines.append("### 最终物理参数的五-fit 均值\n\n" + table(
        ["模型族", "boundary", "diffusion", "gain", "bias", "reset +", "reset −", "recovery rate"],
        [[r['family'],*(f(r['means'][k],5) if r['family'] not in ('ordinary_base','ordinary_bank') or k not in ('reset_plus','reset_minus','recovery_rate') else "未启用"
                      for k in ('boundary','diffusion','gain','drift_bias','reset_plus','reset_minus','recovery_rate'))] for r in physical]))
    lines.append(f"""参数表是描述性汇总。代码里的 effective count 指“参与计算的可训练坐标数”，并非可辨识函数维数：在物理边界内部，把 boundary、diffusion、gain、bias 同乘一个比例，同时保持 normalized reset 和 recovery rate，有限核与读出保持不变。ordinary 的四个活动物理坐标至多提供三个可辨识组合；clocked/FPT 的七个至多六个，有限数据还可能更少。Raw L2/AdamW 可以选择一个表示，但没有消除观测等价性。未来可固定尺度或报告无量纲比值，不能把冗余坐标算成机制优势。

### 完整进程的独立计时重放

原始训练内部 timer 没有覆盖解释器/import 和所有外层数据序列化，因此另做五个完整进程计时重放。它包括解释器、校准、真实 FullHX 数据准备、训练、诊断、表导出、序列化与退出，累计 **{f(replay_cpu,3)} CPU 秒**；五个进程 wall 时间之和为 {f(sum(r['wall_seconds'] for r in replays),3)} 秒。重放的全部 **25 个模型逐字节等于原始模型**，增加的独立 fit 数仍为零。这是额外测量成本，不能倒填为原始训练的完整 CPU 测量，也不能把两个 campaign 当成十个独立 fit。[重放独立审计](evidence/INDEPENDENT_MODEL_FREEZE_AUDIT.json)、[包含完整进程凭据的归档](evidence/training/PACKAGING_WITH_TIMED_REPLAY.json)。""")
    lines.append(f"""## 10. 原生执行、内容读取与持久化的实际成本

4,000 个 Rust episode 合计外部子进程 **CPU {f(native_totals['cpu_seconds'],6)} 秒、wall {f(native_totals['wall_seconds'],6)} 秒**；内部 owner CPU/wall 为 {f(native_totals['native_cpu_seconds'],6)} / {f(native_totals['native_wall_seconds'],6)} 秒。两组计时存在包含关系，不能相加。外部值包含进程启动和 JSON 输出；都不是整个研究 campaign 加上所有 Python 教师求解、报告和归档工作的总成本。

实际到期 packet 打开尝试 **{int(stage_totals['open_attempts']):,} 次**，真正 FullHX decode **{int(native_totals['content_calls']):,} 次**，失败读取 {int(native_totals['failed_reads']):,} 次；读取 **{int(stage_totals['bytes_read']):,} 字节**。累计持久化 payload **{int(native_totals['persistence_bytes']):,} 字节**，包括 checkpoint 写入和 append-only journal/witness 增长。它不测量块设备写放大、filesystem metadata 或真实电能。

下面每行有 200 个 episode；CPU/wall 为外部每 episode 平均，内 CPU 为 owner 内部值。不同模型全部承担模型加载、真实内容、ACK 和持久化条件。[逐族成本及全部原始日志索引](evidence/confirmation/PACKAGING_INDEX.json)、[独立成本复核](evidence/INDEPENDENT_CONFIRMATION_AUDIT.json)。""")
    lines.append(table(["Split", "模型 / 控制器", "CPU ms", "wall ms", "内 CPU ms", "decode/episode", "持久化 KiB/episode"],
        [[split.upper(),family+" / "+controller,f(1000*m(split,family,controller,'cpu_seconds'),3),f(1000*m(split,family,controller,'wall_seconds'),3),
          f(1000*m(split,family,controller,'native_cpu_seconds'),3),f(m(split,family,controller,'content_calls'),3),f(m(split,family,controller,'persistence_bytes')/1024,3)]
         for split in ('iid','ood') for family in FAMILIES for controller in ('fixed','value')]))
    lines.append(f"""内部计时的阶段归因总量包括：artifact load {f(stage_totals['artifact_load_nanos']/1e9,3)} s，神经头 {f(stage_totals['neural_nanos']/1e9,3)} s，representation {f(stage_totals['representation_nanos']/1e9,3)} s，cell propagation {f(stage_totals['propagation_nanos']/1e9,3)} s，内容执行 {f(stage_totals['content_nanos']/1e9,3)} s，持久化/runtime 归因 {f(stage_totals['persist_nanos']/1e9,3)} s。这些是具体代码段的 wall 归因，与 owner/external 包含关系不同，不应累加成另一个“总 CPU”。

**没有能耗测量，也没有无损计算节省证据。** 事件少不意味着跳过了相同数量的神经计算：每个动作仍执行 head，每个推进区间仍查表和硬采样；first-passage 事件也没有触发区间内的异步 owner 调度。减少读取同时降低了效用，应作为资源—质量变化报告。

**没有完整历史内存节省证据。** 所有 owner 都持久化完整已读 history 和动作 ledger，用于可恢复状态与审计；cell family 只是在神经头输入处采用压缩表示。`raw_history` 无 cell，且本轮 JSON 模型文件明显更小。NeuronModelPort 的 14,392 字节 resident 字段只是 head 数组估算，不是实测进程 RSS，不含 FullHX/kernel。不能将单一 17 状态单元大小当作整个系统内存。""")
    lines.append(f"""## 11. 可核验的不变量与原生资格

| 已核验事项 | 结果 | 不能推出的结论 |
| --- | --- | --- |
| Gaussian/probit 同函数对照 | 最大误差 {bank_audit['gaussian']['bank_probit_max_abs_error']:.3g} | 仅改名就得到新函数族 |
| 概率边界、质量、零时长/原子约定、image/spectral 对照与梯度 | [数学审计](evidence/BANK_AUDIT.json) 通过；覆盖指定 envelope 样本 | 任意连续参数域的完整证明、精确连续 renewal |
| 全前缀监督目标与梯度 | [独立优化前审计](evidence/INDEPENDENT_PREFIT_AUDIT.json) 通过 | 自主策略回报收敛 |
| 原始 just fmt / just test 入口 | 176 个测试通过，1 个上游显式 ignored 的历史测量测试未运行 | 全仓库 CI、production qualification |
| 未训练输入异常资格 | 49 次实际进程通过，含缺失/修改/超限/symlink/非法动作/ACK 拒绝 | 实际任务增益 |
| 训练后 ACK 恢复 | 25 模型×2 controller，50 案例、150 进程；32 个 pending 恢复均到期只读一次，18 个非 pending 恢复；逐字段一致 | 所有崩溃点、所有工作负载都已证明 |
| 正式执行独立复算 | 4,800 episode、120 组，4,000 native、800 reference；21,271 次 native 决策，最大分数误差 {audit['confirmation']['maximum_independent_native_score_error']:.3g} | 数学正确自动产生决策优势 |

原生使用真实固定版本 `NeuronRuntime` / `NeuronModelPort`，每次恢复要求外部 ACK。完整 checkpoint 包含 pending source/due、last observation、history、cell index、RNG、费用、时钟和内容 receipt；恢复不重新执行已完成读取。源码、权重、public、FullHX、controller、seed 和 mode 均绑定身份。native authority 保持 `DENY_ALL`、`production_activation=false`，calibration 为明确标注的研究占位 profile。[构建证据](evidence/NATIVE_BUILD.json)、[训练后恢复证据](evidence/TRAINED_ACK_QUALIFICATION.json)、[最终独立审计](evidence/INDEPENDENT_CONFIRMATION_AUDIT.json)。

冻结 native source digest：`{freeze['native_source_digest']}`；binary SHA-256：`{freeze['native_binary_sha256']}`。构建是环境重置后真正恢复工具链并编译的结果，后续离线重建复用本次生成的 Cargo cache，没有冒称丢失的历史缓存仍然可用。""")
    lines.append(r"""## 12. 六条工作的交付状态

| 工作线 | 本轮已经完成 | 仍未解决或未证明 |
| --- | --- | --- |
| 真实 read-before 决策 | 六动作、费用、delay 1/2、真实到期 FullHX、失败/REPAIR、取消 pending | 更长时域、更大任务的策略稳定性 |
| 解析多阈值 bank 与对照 | 3×3 call bank、put 补概率、等价 probit 验证、多项式与 raw-history 对照 | value 路由下经过主门槛确认的 bank 收益 |
| 同一过程的 clocked / first-passage | 共用 Brownian law、17 状态、可训练 reset/recovery、实际硬事件 | 精确区间内 hit time、多次 renewal、reset-aware 多期预测 |
| 全目标训练 | 全前缀条件质量、非线性期望 loss、head/cell 参数更新和梯度审计 | 自主策略回报最优性、DQN/策略梯度收敛 |
| 原生与恢复及成本 | 真实 runtime、版本绑定导出、全 checkpoint、50 个训练后恢复案例、真实 CPU/读调用/持久化 | 无损节能、完整历史内存压缩、生产校准与授权 |
| 五-fit 严格确认 | 先冻源码、再冻 25 模型、再生成新 IID/OOD；完整 4,800 episode 与四项调整区间 | 四个预登记收益门槛全部未通过，不能宣称研究阻碍已全部关闭 |

这六条的工程交付可以复核；收益、可扩展性和连续过程语义仍是开放研究问题。当前实现可作为 Hepta neuron 的受限研究候选与可复现实验基座，不能作为替换已有生产神经元或宣布架构优势的依据。
""")
    lines.append(r"""## 13. 下一轮应解决的具体机制

**先解决价值路由如何保住信息和效用。** 当前所有学习族的 value 均低于自身 fixed，而 Bayes/value 高于 Bayes/fixed；raw-history/value 也出现同方向下降。这表明问题不能只归结于脉冲核。优先在 TRAIN/validation 上分析贪心策略访问状态是否被行为数据覆盖、选中动作的 Q margin 与教师误差、WAIT/STOP/READ 之间的错序，再预登记下一轮状态收集或目标调整。可比较增加真实策略访问状态的监督训练，或在这个小型有限任务上直接枚举所定义策略的期望回报；两者都需新版本、新冻结和新的确认世界，不能对本轮确认集调参。

一个具体候选是把已知终止动作结构写入输出：`Q_STOP=0`、`Q_SUBMIT_0=1−2×belief`、`Q_SUBMIT_1=2×belief−1`，仅学习还需规划的 WAIT/READ/REPAIR 值。它可避免六个独立 Q 输出与单独 belief 相互矛盾；是否提升收益尚未验证，应在所有家族中对称应用，并重新报告参数与计算预算。另一候选是在实际策略访问的 task×cell 联合状态上求所声明策略目标的梯度。这些都是待验证的机制假设，本轮没有实施，也不能追溯归因为已观察到的失败原因。

**再分离信息压缩与事件/reset 的作用。** ordinary bank、event bank 和 raw history 目前保存历史的能力不同；持续使用最后一次观察驱动 drift，也可能在多个 WAIT 区间重复强化同一条证据。应把这当作待验证假设，加入保持相同已读信息、相同计算预算的积累/一次性输入/重置对照，记录事件前后可恢复的后验信息。确认是否需要保留事件符号、累计证据或时间戳，再讨论事件机制是否有额外价值。当前负面结果不允许直接把任务换成更有利的设置后宣称原结论被推翻。

**把动力学层次和预测语义继续分开。** 若下一步目标是连续时间神经元，需要先实现并校验区间内 hit time、事件后剩余时间的继续演化和多次 renewal；若目标是多期预测，需要明确未来输入假设，并用包含 reset/refractory 的转移预测，而不是继续把 free-endpoint bank 当作真实未来状态预测。当前有限原型提供接口和基线，不提供这些尚未实现的能力。

**成本主张需要真实跳过工作。** 当前每步 head 和有限表传播都执行。下一轮若要研究事件驱动节省，应设计实际的计算触发条件、真实跳过哪些组件、可接受的决策误差与预先登记的质量下限，同时测量完整过程 CPU、内存和硬件能量。只有事件计数下降不能支持节能结论；减少读请求但丢失效用也不能称无损收益。

**先消除无意义参数自由度，再扩规模。** 可固定 voltage 尺度或改用 sigma/boundary、gain/boundary、bias/boundary 等无量纲组合；增加真实信息容量与计算量匹配的对照。更大网络、更多神经元和长时域任务需要各自的可恢复状态、学习目标及误差分析。本轮五-fit 结果应继续保留为负面或不确定基线，任何改动单列后续实验。
""")
    lines.append(f"""## 14. 复现入口与证据索引

从有权限的完整仓库 checkout 运行，Python 依赖版本以各 fit 的 COMPLETE 为准：本轮 Python 3.12.14、PyTorch 2.9.1+cpu、NumPy 2.3.5，训练 CPU threads=1；SciPy 用于统计/独立数值核验。以下命令中的运行目录必须是新目录，原始脚本拒绝覆盖既有 formal attempt。

### A. 重新训练是独立复现运行

以下命令可重放训练程序、检查模型是否重现，并记录一套新的计时。它们产生新的运行证据，不覆盖也不替代已发布的原始结果。

```sh
python -m tools.hcsn.digital_read_before_20261031.run_training --fit 11 --runs /tmp/digital-reproduction-training
python -m tools.hcsn.digital_read_before_20261031.run_training --fit 23 --runs /tmp/digital-reproduction-training
python -m tools.hcsn.digital_read_before_20261031.run_training --fit 37 --runs /tmp/digital-reproduction-training
python -m tools.hcsn.digital_read_before_20261031.run_training --fit 53 --runs /tmp/digital-reproduction-training
python -m tools.hcsn.digital_read_before_20261031.run_training --fit 71 --runs /tmp/digital-reproduction-training
```

即使重训得到逐字节相同的模型，新 `fit_N_data.json` 仍包含新的路径与运行计时，其文件摘要一般不会等于 MODEL_FREEZE 登记的原始 `training_data_sha256`。因此，**不能把上面的新训练目录直接传给已冻结的 confirmation，也不能修改冻结摘要来绕过校验。**

### B. 已冻结确认使用逐字节恢复的原始训练档案

使用 [原始训练恢复工具](restore_training.py) 恢复到一个新目录；工具会验证分片、完整 gzip/tar、归档成员以及 MODEL_FREEZE 绑定的原始数据与模型：

```sh
python -m tools.hcsn.digital_read_before_20261031.restore_training --out /tmp/digital-restored-primary
```

从 [原始训练归档索引](evidence/training/PACKAGING_ALL_PRIMARY.json) 找到每个 fit 的 `full_fit.tar.gz.index.json`。按其中列出的顺序拼接分片，逐片核对 bytes/SHA-256，再核对完整 gzip 的 SHA-256，解压后核对 raw SHA-256。**每个 fit 的归档应分别安全展开到 `/tmp/digital-restored-primary/fit_N`**：tar 成员从 `data/fit_N_data.json`、`models/`、`RUN_COMPLETE.json` 等开始，归档本身不带 `fit_N` 前缀。恢复后的完整路径才是 `/tmp/digital-restored-primary/fit_N/data/fit_N_data.json`。恢复过程必须保留原始 JSON 字节，不重新序列化，不把其中记录的历史路径改写成当前路径；最后逐 fit 核对 `fit_N_data.json` 与 MODEL_FREEZE 的 `training_data_sha256` 完全相同。

confirmation 只从该已验证的原始数据文件取 TRAIN confusion，并严格核对文件身份；其新 IID/OOD 世界仍在新的确认输出目录生成。已发布模型也从 MODEL_FREEZE 指定的 25 个文件解压并校验原始模型字节，不从新训练目录自动替换。

上述恢复命令已实际成功恢复 5 个 fit、3,386 个文件、24,302,363 bytes；五份原始训练数据和 25 个模型均通过冻结摘要校验，重复使用相同输出目录被拒绝。详见 [原始训练恢复检查](evidence/RESTORE_TRAINING_CHECK.json)。

### C. 原生重建与新的确认执行

原生构建要求准备 [UPSTREAM_SOURCE_IDENTITY](native/UPSTREAM_SOURCE_IDENTITY.json) 指定的 runtime 源，以及 [builder](build_native.py) 指定 Git blob 的原始 justfile/scripts。Runtime 源来自 `732e934ba496d90fbe042b8d41d479ef901643e5`，just 入口来自 `6c6f25f736df040e0d447e0242fb9819e15b3022`；不能用任意当前 HEAD 代替。用可用的 Rust 1.95.0、just、cargo-nextest 运行，把新的构建 receipt 写到临时路径，以免覆盖已发布的 NATIVE_BUILD 证据：

```sh
python tools/hcsn/digital_read_before_20261031/build_native.py --upstream-root /tmp/hepta-digital-upstream --work-dir /tmp/hepta-digital-reproduction-build --rust-bin /tmp/hepta-digital-rust195/bin --tools-bin /tmp/hepta-digital-tools/bin --cargo-home /tmp/hepta-digital-cargo --receipt /tmp/digital-reproduction-native-build.json
python -m tools.hcsn.digital_read_before_20261031.experiment --binary /tmp/hepta-digital-reproduction-build/codex-rs/target/release/hepta-digital-read-before-native --runs /tmp/digital-reproduction-confirmation --training /tmp/digital-restored-primary --published-model-commit {summary['published_model_commit']}
```

默认构建走离线锁定依赖；初次需要下载 Cargo registry 依赖时显式使用 `--allow-network`。新构建、确认、计时和 ACK receipt 都是独立的复现证据；运行时延参与原生 checkpoint 身份，因此不要求新 receipt 的摘要等于原始摘要，也不能把新的计时倒填到原实验。新训练若因环境产生不同模型字节，同样不能冒称是同一冻结模型。训练后恢复的真实入口为 `native/trained_qualification.py`。

### D. 报告生成器只重排原始证据

[报告生成器](summarize_research.py) 是本轮原始证据的渲染器。它在写出任何结果前核对固定的 SUMMARY/RESULTS SHA-256、MODEL_FREEZE 绑定的五份原始训练数据与 25 个模型，以及归档索引绑定的五份原始 COMPLETE 和五份计时重放 PROCESS_MEASUREMENT。**新训练、新确认或新计时目录会被拒绝；它们需要对应的新独立审计和新报告，不能套用本轮审计的 stage totals。** 逐字节恢复的原始档案可以用于重排，不改变任何数字核心。

例如，将 [确认归档](evidence/confirmation/PACKAGING_INDEX.json) 中的原始 SUMMARY、RESULTS、STARTED 逐字节恢复到 `/tmp/digital-restored-confirmation`，将 [计时重放归档](evidence/training/PACKAGING_WITH_TIMED_REPLAY.json) 中各 fit 的原始 PROCESS_MEASUREMENT 恢复到 `/tmp/digital-restored-timed/fit_N`，并使用 B 节恢复的训练数据：

```sh
python -m tools.hcsn.digital_read_before_20261031.summarize_research --runs /tmp/digital-restored-confirmation --training /tmp/digital-restored-primary --timed-training /tmp/digital-restored-timed --report /tmp/digital-original-evidence-report.md --tables /tmp/digital-original-evidence-tables.json
```

`--report` 与 `--tables` **分别控制** Markdown 和 JSON 输出。只指定 `--report` 不会改变表的默认位置；临时重排时须像上例一样同时指定两者，避免覆盖已发布文件。两个默认位置分别是本目录 REPORT.md 和 evidence/RESEARCH_TABLES.json。输入身份检查的成功与拒绝路径见 [报告输入边界检查](evidence/REPORT_INPUT_GUARD_CHECK.json)。

证据阅读顺序：[协议](protocol.json) → [源码冻结](SOURCE_FREEZE.json) → [模型冻结](MODEL_FREEZE.json) → [原始训练与全部模型](evidence/training/PACKAGING_ALL_PRIMARY.json) → [确认 SUMMARY](evidence/confirmation/SUMMARY.json) → [RESULTS/全部原始执行/输入的归档索引](evidence/confirmation/PACKAGING_INDEX.json) → [独立最终审计](evidence/INDEPENDENT_CONFIRMATION_AUDIT.json)。补充包括 [数学审计](evidence/BANK_AUDIT.json)、[优化前审计](evidence/INDEPENDENT_PREFIT_AUDIT.json)、[原生构建](evidence/NATIVE_BUILD.json)、[未训练 qualification 原始档案](evidence/NATIVE_ARCHIVES.json)、[全部训练模型 ACK 恢复](evidence/TRAINED_ACK_QUALIFICATION.json)、[训练后恢复原始档案](evidence/TRAINED_ACK_ARCHIVES.json)、[本报告完整可复算表](evidence/RESEARCH_TABLES.json)。

报告输入 SUMMARY SHA-256：`{derived['summary_sha256']}`；RESULTS SHA-256：`{derived['results_sha256']}`。完整原始数值、五-fit 差值和每个模型参数均保留；本文展示的小数位仅用于阅读。""")
    report_text = ("\n\n".join(lines)+"\n").replace("\\[\n", "$$\n").replace("\n\\]", "\n$$")
    tables_text = json.dumps(derived, indent=2, ensure_ascii=False, allow_nan=False)+"\n"
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.tables.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report_text)
    args.tables.write_text(tables_text)
    print(json.dumps(dict(report=str(args.report), bytes=args.report.stat().st_size,
                         research_tables=str(args.tables),
                         all_primary_gates_failed=all_fail, numeric_core_modified=False), ensure_ascii=False))


if __name__ == "__main__":
    main()
