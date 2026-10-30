"""Build the sequence report from complete, auditable per-seed records."""
import json
from pathlib import Path

import numpy as np
from scipy.stats import t

ROOT=Path(__file__).parent
KINDS=("hcsn_v2_reference","hcsn","sigmoid","memory_only","full_hx","gru","transformer","snn")
NAMES={"hcsn_v2_reference":"未修改 v2", "hcsn":"v3 HCSN", "sigmoid":"v3 sigmoid",
       "memory_only":"v3 memory-only", "full_hx":"v3 full-HX", "gru":"GRU",
       "transformer":"Transformer", "snn":"LIF-SNN"}


def read(name):
    return json.loads((ROOT/name).read_text())


def stats(rows,task,kind,split):
    chosen=sorted((r for r in rows if r["task"]==task and r["kind"]==kind),key=lambda r:r["seed"])
    values=np.array([r["metrics"][split]["accuracy"] for r in chosen])
    return values,chosen


def main():
    records=[read(name) for name in ("results.json","v2_reference_results.json","full_results.json")]
    assert all(r["complete"] for r in records)
    rows=[row for r in records for row in r["runs"]]
    assert len(rows)==120
    challenge=read("challenge_results.json")
    audit=read("checkpoint_audit.json")
    writes=read("write_diagnostics.json")
    assert challenge["complete"] and audit["passed"]
    lines=["# HCSN v3：有界关联记忆、完整 HX 核与同预算序列验证", "",
        "本目录完成 **120 次训练**：固定 v3 主矩阵 90 次、未修改 v2 同预算参考 15 次、完整 HX 数值算子注入 15 次。所有训练均使用 600 次更新、batch 32、5 个种子；此前 v1/v2 原始源码与结果未修改。另完成 120 组冻结 checkpoint 挑战评估，以及全部 120 个 checkpoint 的独立重放。", "",
        "**结论：限定的初始符号长记忆得到修复，内容检索明显改善，但预声明 90% 检索目标仍未达到；Put 形状独有收益没有建立。** 改善不能全归因于槽记忆，因为训练课程和预算也改变；本目录专门加入未修改 v2 的同条件控制。", "",
        "## 1. 冻结方案与公平范围", "",
        "主设计在训练之前写入 `protocol.json`。训练长度 8/16/32 按更新轮换，每长度 2048 个训练样本，validation32 和每个 heldout32/64/128 各 1024 个样本；全新数据 seed base=1700000。Adam LR=0.003，梯度范数裁剪1，验证 loss 每50步选择一次 checkpoint。测试集不传入训练函数。", "",
        "数据、minibatch indices、更新次数匹配，参数量约匹配；状态容量和 FLOPs 不匹配。新增 SNN 也在同一600步课程下重新训练，未将旧300步结果作为本轮对照。未修改 v2 参考在初期 v3 memory 结果之后声明，属于用于消除预算/课程混杂的诊断控制，不是另一次盲确认性架构选择。", "",
        "| 模型 | 可训练参数 | 逻辑持久动态状态标量 |", "| --- | ---: | ---: |"]
    for kind in KINDS:
        first=next(r for r in rows if r["kind"]==kind)
        state=first["persistent_state_scalars"]
        lines.append(f"| {NAMES[kind]} | {first['parameter_count']} | {state if state is not None else '完整序列注意力参考'} |")
    full=records[2]["metadata"]
    lines += ["",f"full-HX 另有共享固定算子表：未压缩 JAX 数组 {full['fixed_operator_table_array_bytes']} bytes；NPZ 文件 {full['fixed_operator_table_file_bytes']} bytes。它不是可训练参数，也没有被忽略成零内存成本。", "",
        "## 2. v3 机制与有界性", "",
        "输入通过同一个可学习 key/query 投影寻址8个槽，value 也由通用投影学习。没有按任务名称或 marker 列手写路由。普通关闭写门为 w=relu(s)^2/(1+relu(s)^2)，当 s<=0 时值与一阶导均为零。槽更新 m_j←m_j+w·address_j·(tanh(candidate)−m_j) 是凸组合，从零初态保持每个槽在[-1,1]。读旧记忆后再写当前 token。", "",
        "HCSN 和 sigmoid 的整个图、初始参数和训练规则相同，仅 q 形状不同。memory-only 移除动态神经元，仍保留通用内容寻址与关闭写门。它用于判断关联存储自身的收益；不同宽度用于匹配参数，不能把它视作完全相同状态容量的消融。快慢神经状态沿用有界增益与时间常数，有限正dt下保持既有状态界。", "",
        "独立 float64 有限差分最大误差：HCSN 5.46e-12、sigmoid 6.97e-12、memory-only 2.30e-12。关闭区域及其零导数、放大1e6输入和100倍时间间隔的有限输出均检查。梯度是实现的离散更新梯度，不是精确连续ODE流，也不证明任意长期梯度稳定。", "",
        f"`analyze_writes.py` 检查了{len(writes['checks'])}个已训练memory模型，真正对全部4种filler关闭全局写门的模型数为{writes['all_filler_global_gate_closed_count']}。这些权重主要依靠内容地址隔离干扰；softmax非零写权重仍会衰减旧槽状态的直接系数。因此“门具有严格关闭能力”不等于“本次训练已使用该能力”，也不能从128步准确率推出任意长度严格保持。该系数诊断本身不证明分类信息必然丢失，其他槽及神经状态也可能携带信息。", "",
        "## 3. 主要样本外结果", "",
        "数值为五种子均值±样本标准差，单位百分比。所有长度的检索仍只有4个关联项；延长干扰间隔不能当作增加内容容量。", ""]
    for task in ("memory","retrieval","irregular"):
        lines += [f"### {task}","","| 模型 | Test32 | Test64 | Test128 | Test128 最差种子 |",
                  "| --- | ---: | ---: | ---: | ---: |"]
        for kind in KINDS:
            vals=[stats(rows,task,kind,s)[0] for s in ("test_32","test_64","test_128")]
            cells=[f"{v.mean()*100:.3f} ± {v.std(ddof=1)*100:.3f}" for v in vals]
            lines.append(f"| {NAMES[kind]} | "+" | ".join(cells)+f" | {vals[-1].min()*100:.3f} |")
        lines.append("")
    lines += ["## 4. 结构修复、课程和算子形状分别贡献了什么", "",
        "| 指标 | 同新预算 v2 | v3 HCSN | 配对均值变化 |", "| --- | ---: | ---: | ---: |"]
    for task in ("memory","retrieval","irregular"):
        for split in ("test_32","test_128"):
            old,_=stats(rows,task,"hcsn_v2_reference",split)
            new,_=stats(rows,task,"hcsn",split)
            lines.append(f"| {task} {split} | {100*old.mean():.3f}% | {100*new.mean():.3f}% | {100*(new-old).mean():+.3f} pp |")
    lines += ["", "GRU 在新的课程与预算下也能很好地完成记忆任务，说明旧固定长度300步实验不是这些架构的能力上限。检索仍显示关联记忆相对未修改 v2 的明显增量，但个别种子低于90%的结果说明8槽softmax寻址尚有训练/碰撞问题。", "",
        "下表比较同图 HCSN 与 sigmoid。名义95% t区间仅描述五个训练种子的差值，不包含完整数据抽样不确定性，也未做多重比较校正。", "",
        "| 任务 | Split | HCSN−sigmoid | 名义95%区间 |", "| --- | --- | ---: | ---: |"]
    for task in ("memory","retrieval","irregular"):
        for split in ("test_32","test_64","test_128"):
            a,_=stats(rows,task,"hcsn",split);b,_=stats(rows,task,"sigmoid",split)
            d=100*(a-b);half=t.ppf(.975,4)*d.std(ddof=1)/np.sqrt(5)
            lines.append(f"| {task} | {split} | {d.mean():+.3f} pp | [{d.mean()-half:+.3f}, {d.mean()+half:+.3f}] |")
    lines += ["", "## 5. 完整金融算子进入真实序列训练", "",
        "`with_operators.py` 复制冻结 v3 图，只开放一个 q/a 注入点。注入旧 gate 时，logits 与全部参数梯度和原图逐项完全相同，最大误差均为0。随后注入 `next/full_kernel` 的完整股权数值表与新设计C1风险通道，使用标准化危险坐标 z=log(Vb/V)/(sigma*sqrt(m))。15次训练全部记录、没有根据full-HX test改设计。", "",
        "财务9参数固定于模板；训练的是神经权重、边界偏置、时间常数与寻址。这里并非9参数金融模型全量训练，表也不是闭式非线性时间流。风险通道的C1构造属于新模型设计。full-HX完整记录在`full_results.json`，表SHA与源码SHA一并固定。", "",
        "## 6. 冻结模型的额外挑战", "",
        "挑战协议在v3训练进行中、检索结果出现前声明；后加入v2/full-HX对照的决定也在挑战第一次评估之前。所有挑战只评估已有验证集选中的checkpoint，不重新选择或调参。", "",
        "| 挑战 | 模型 | 平均±SD | 最差种子 |", "| --- | --- | ---: | ---: |"]
    for row in challenge["summary"]:
        lines.append(f"| {row['challenge']} | {NAMES[row['kind']]} | {100*row['mean']:.3f} ± {100*row['seed_sd']:.3f}% | {100*row['min']:.3f}% |")
    lines += ["", "8个关联项和更强filler噪声是新的容量/干扰分布，不是只把4个项隔得更远。失败时必须保留容量限制；不能因为32/64/128的四项任务改善，就宣布任意长上下文检索解决。", "",
        "## 7. 真实计时与重放", "",
        "所有模型使用`next/common.py`：参数强dtype，三种训练长度分别AOT预编译，训练预算之外不执行任何丢弃的optimizer warmup。前两步和最后一步的optimizer状态签名均保持不变。记录compilation、optimizer execution、validation、host batch和总调用时间；首次AOT执行仍可能有冷dispatch开销。纯logits延迟另做三次预测预热，排除编译与指标计算。所有时间来自共享CPU，不支持能耗或部署成本结论。", "",
        f"全部 {audit['checkpoints_replayed']} 个checkpoint 已重新载入并重放test32，accuracy/loss/Brier/ECE最大误差 {audit['max_metric_absolute_error']:.3g}。训练预算、所有split的配对数据摘要、固定金融表与 {audit['source_hash_pairs_verified']} 组源码摘要均通过检查。", "",
        "## 8. 复现与剩余结论", "",
        "在项目根目录，先运行`python next/sequence/validate.py`，随后依次运行`run.py`、`run_v2_reference.py`、`run_full.py`、`challenge.py`、`audit.py`、`write_report.py`（均位于`next/sequence/`）。依赖沿用项目CPU版本；完整金融表须先由其目录生成。", "",
        "主v3满足预声明的memory均值门槛，retrieval均值未达90%；Put相对sigmoid的稳定独有收益仍未建立。完整算子实际训练缺口已经补上，但不意味着完整金融模型在所有参数下、任意长上下文或多模态backbone上已获证明。后续任何寻址修复必须另开协议和未触碰holdout，不能改写本目录失败。", ""]
    (ROOT/"README.md").write_text("\n".join(lines))
    summary=dict(training_runs=len(rows),checkpoint_replay_passed=audit["passed"],
        full_financial_operator_training_performed=True,financial_template_parameters_frozen=True,
        memory_targets_passed=all(stats(rows,"memory","hcsn",s)[0].mean()>=.95 for s in ("test_32","test_64","test_128")),
        retrieval_targets_passed=all(stats(rows,"retrieval","hcsn",s)[0].mean()>=.9 for s in ("test_32","test_64","test_128")),
        put_specific_benefit_established=False,scope="This fixed v3 experiment; later experiments must keep its negative results")
    (ROOT/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    print(json.dumps(summary,indent=2))


if __name__=="__main__":
    main()
