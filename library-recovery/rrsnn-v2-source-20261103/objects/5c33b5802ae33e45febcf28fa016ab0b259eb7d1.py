"""Build a self-contained Chinese computational report from frozen result files."""
from __future__ import annotations

from pathlib import Path
import base64
import hashlib
import json
import uuid
import numpy as np

ROOT = Path(__file__).resolve().parent
LABELS = {
    'lif': 'LIF', 'alif': 'ALIF', 'resource_lif': '资源受限 LIF',
    'fp_no_maturity': '无期限机制的首达模型', 'fp_multi_fixed': '多期限＋固定阈值',
    'rr_full': '完整 RR 候选 v0', 'ctrnn': '连续时间 RNN，16 维',
    'ctrnn_budget': '连续时间 RNN，联合预算对照',
    'rr_no_rollover': '删除续约反馈', 'rr_collapse_maturity': '内部合并期限',
    'rr_shuffle_maturity': '内部历史期限重采样', 'rr_frozen_resource': '冻结内部资源信号',
}


def load(relative):
    return json.loads((ROOT/relative).read_text())


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |',
                       '| '+' | '.join(['---']*len(headers))+' |']+
                     ['| '+' | '.join(str(v) for v in row)+' |' for row in rows])


def pm(value, scale=1, digits=3):
    return f"{scale*value['mean']:.{digits}f} ± {scale*value['seed_sd']:.{digits}f}"


def main():
    aggregate = load('results/aggregate.json')
    rows = {r['variant']: r for r in aggregate['rows']}
    rr = rows['rr_full']
    reference = aggregate['selected_reference_baseline']
    comparison = aggregate['RR_minus_comparators'][reference]
    scale = load('models/scaling_results.json')['results']
    censored = load('runtime/results/censored/censored_training_results.json')
    gap = load('hepta/proxy_exact_gap.json')
    repair = load('hepta/semigroup_repair_probe.json')
    controls = load('models/implementation_control_results.json')
    matrix = load('results/matrix_status.json')
    assert matrix['completed'] == 60 and not matrix['failures']
    assert matrix['source_unchanged_during_matrix']
    assert controls['complete']
    cells = []

    def md(text):
        text = text.replace(chr(92)*2, chr(92))
        cells.append({'cell_type':'markdown','metadata':{},'id':uuid.uuid4().hex[:8],
                      'source':text.strip()+'\n'})

    def code(source, outputs=None):
        cells.append({'cell_type':'code','metadata':{},'id':uuid.uuid4().hex[:8],
                      'source':source.strip()+'\n','execution_count':None,
                      'outputs':outputs or []})

    def figure(relative, title):
        payload = base64.b64encode((ROOT/relative).read_bytes()).decode()
        code(f"# {title}\nfrom IPython.display import display, Image\ndisplay(Image(filename=str(ROOT / {relative!r})))",
             [{'output_type':'display_data','metadata':{},
               'data':{'image/png':payload,'text/plain':title}}])

    e = rr['evaluation']
    delta = comparison['future_expected']['normalized_utility_RR_minus_comparator']
    md(f"""
# RR-SNN：R1—R5 实验报告与可复现记录

**执行日期：2026-10-29。60/60 个冻结训练实验完成；5 个训练种子；全部训练源码保持冻结。**

本轮从标量解析原语继续推进事件引擎、期限队列、资源账本、可训练代理、强基线、机制消融、概率校准、规模成本和 Hepta 离线接口。主要结果是：**当前完整 RR 候选尚未给出足以晋级的效用—成本证据。**

在最贴近用户要求的 128 组 A/B×预算收缩反事实中，冻结权重后的 RR 相对 oracle 效用为 **82.54%**，强 RNN 为 **86.61%**；RR 低 **4.07 个百分点**，探索性配对区间为 **[−6.23，−2.23]**。差距集中在分散到期且有预算收缩的场景，高价值记忆保留也没有显示优势。

完整候选在同分布测试上的归一化效用为 **{pm(e['test_expected']['normalized_utility_mean'],100,2)}%**，合成分布偏移上为 **{pm(e['future_expected']['normalized_utility_mean'],100,2)}%**；验证集选择的参考基线是 **{LABELS[reference]}**，偏移集上 RR 相对它的平均差为 **{100*delta['mean_delta']:+.2f} 个百分点**。这些结果属于观察网格训练代理，不属于精确事件引擎，也不是实际 Hepta 未来窗口收益。

同时，我们定位到了一个可以直接修复的数学断点：生存分支只保留条件均值，破坏首达概率的时间分割一致性。在预先指定的两个初始场景、一个真实训练 checkpoint 的 32 个单元控制中，H=1 的平均误差为 **5.755 个百分点**。改为积分完整 killed density 后，96 项局部核对的最大数值差为 **3.33×10⁻¹⁶**。这为下一轮实验提供了比继续堆模型规模更明确的方向。

这里的“RR 候选”是借鉴续约压力与资源反馈构造的研究实现。它使用冻结参数的标量最优阈值作为启发式控制，并未求解完整期限队列与资源状态耦合的 QVI。本报告不把金融建模类比、现有首达公式或这些负结果包装成已证实的新神经理论。
""")
    code("""
from pathlib import Path
import json
import numpy as np

# Open this notebook from the extracted experiment directory or its parent.
ROOT = Path.cwd()
if not (ROOT / 'results' / 'aggregate.json').exists():
    ROOT = ROOT / 'rrsnn_experiments'
assert (ROOT / 'results' / 'aggregate.json').exists(), 'Extract the full ZIP first.'
summary = json.loads((ROOT / 'results' / 'aggregate.json').read_text())
print(summary['completed_runs'], summary['selected_reference_baseline'])
""", [{'output_type':'stream','name':'stdout','text':f"60 {reference}\n"}])
    figure('figures/rrsnn_results_overview.png', '训练代理的效用、消融、延迟与生存分布传播误差')

    md(r"""
## 1. 研究问题和证据边界

本轮检验三个可证伪问题：在所有方法看到相同期限信息时，期限结构与续约反馈是否提供增益；解析原语能否支持正确的事件推进与右删失学习；相应机制在真实计算成本约束下是否值得继续进入 Hepta。

实现有两层，不能混用结论。`runtime/event_runtime.py` 是分段常系数 Brownian 首达事件的参考引擎。`models/sequence_models.py` 则是用于批量训练的观察网格代理，生存后使用条件均值、每区间最多一次内部事件、预期模式使用事件概率。其 hard 模式产生二值事件，但仍继承上述近似。当前训练比较并没有把模型完整迁移到 R1 引擎。

训练代理先读取当前观测，再以相邻观测的间隔作为本次编码更新的 dt，初始观测采用 0.1 的编码时长。这是序列编码约定，不等于真实物理时钟上的因果连续传播；全部方法采用同一输入协议，也没有因而获得未公开的未来标签。R1 的真实事件时钟与训练代理尚未合并。

这次实验的实际任务是四个记忆义务的有限预算规划。价值和预算日程在初始观测提供一次，网络随后需要记住它们。它不是生物膜电位拟合、未观测冲击预测、真实能耗测量或生产 Cell 运行。
""")

    md(r"""
## 2. R1：输入事件、条件传播、多次发放和不应期

令距离吸收边界的状态满足

$$dX_t=\mu\,dt+\sigma\,dW_t,\quad X_0=x>0,\qquad \tau=\inf\{t:X_t\le0\}.$$

首达分布为

$$F(x,t)=\Phi\!\left(\frac{-x-\mu t}{\sigma\sqrt t}\right)
+e^{-2\mu x/\sigma^2}\Phi\!\left(\frac{-x+\mu t}{\sigma\sqrt t}\right).$$

在外部事件到来且尚未触发时，正确状态更新来自 killed kernel 的条件分布：

$$K(y,t\mid x)=\frac{\exp[-(y-x-\mu t)^2/(2\sigma^2t)]}{\sigma\sqrt{2\pi t}}
\left[1-\exp\!\left(-\frac{2xy}{\sigma^2t}\right)\right],\quad y>0,$$

$$p(X_t=y\mid\tau>t)=K(y,t\mid x)/(1-F(x,t)).$$

参考实现保留向外漂移时永不首达的概率质量；在输入、漂移、噪声或阈值切换时按生存条件传播；支持多次 reset、不应期、跳跃越阈和延迟连接。预先抽取但尚未实现的未来首达时间可在条件状态更新后重抽。独立 Brownian 创新与延迟跳跃构成当前网络耦合范围。

12 组检查全部通过：确定性发放时间 `[1.0, 2.2, 3.4]`；漂移切换触发时间 0.8；输入跳跃触发 0.25；阈值下降触发 0.4；连接传播 1.0→1.1。16,000 个条件端点样本的 KS 统计量为 0.00598；稀有存活区间另测了数值逆分布回退。向外漂移的 100,000 个样本首达比例为 0.25058，对照值 0.250896。

输入跳跃＋漂移切换的解析核合成值为 0.466251708，独立细网格前向 PDE 为 0.466250677，差 1.03×10⁻⁶；事件引擎 12,000 次模拟的比例为 0.466083。另一个 8 单元、16 条边的随机循环网络完成 54 次发放与 1,389 次生存条件更新。

这些证据只支持所限定模型的模拟正确性。系数与边界在事件之间固定；不应期内的输入 kick 按已记录规则丢弃；尚不覆盖连续移动边界、乘性噪声或片段内连续资源反馈。引擎还会在全局事件时同步所有单元，复杂度约为单元数乘事件数，不是生产优化实现。

证据：`runtime/results/runtime_validation.json`，`runtime/results/coupled_network_trace.json`。
""")

    from rrsnn_experiments.resource_env import Scenario, rollout
    example = []
    for shock in (0, 2):
        for profile, deadlines in [('A',(1.,1.,3.,3.)),('B',(2.,2.,2.,2.))]:
            s = Scenario(values=(1.4,1.2,.7,.5),deadlines=deadlines,budget=4,
                         shock_amount=shock,refill_amount=1,profile=profile)
            result = rollout(s,use_oracle=True)
            action = next(r['action'] for r in result['trace'] if r.get('cost',0))
            example.append([profile,shock,action,f"{result['utility']:.6f}",f"{result['retained_value']:.6f}"])
    md(r"""
## 3. R2：同当前状态、不同期限分布

A 的期限为 `[1,1,3,3]`，B 为 `[2,2,2,2]`。两者的当前证据相同、预算相同、义务质量相同、平均期限均为 2。固定示例的价值为 `[1.4,1.2,0.7,0.5]`，总价值 3.8；初始预算为 4；t=1.5 发生预算收缩，t=2.5 补充 1 单位。

每项义务到期时可以丢弃、付 1 单位续期 2 个时间单位，或付 1 单位提前输出；提前输出价值按 `exp[-0.15(4-t)]` 折扣。t=4 的终点查询发生在该时刻到期之前，仍存活的义务按原价值计入收益。模型只在到期点选择动作，不允许任意时刻的预防性续期。

动态规划枚举合法动作，作为这个有限任务的最优值参照。独立实现使用显式逐项期限队列核对了 89 个场景、4,578 个状态，最优值最大差为 0；另一条独立审阅也核对了 14 个边界案例。账本满足初始预算＋补充−收缩−实际付费＝剩余预算。

动作编码：0 是到期丢弃／其他时间不操作，1 是续期，2 是提前输出。下表是同一个固定示例的精确最优策略；A 第一次决策在 t=1，早于收缩；B 第一次决策在 t=2。
"""+'\n\n'+table(['期限','收缩量','第一次付费动作','最优效用','终点保留价值'],example)+r"""

这里已经可以确认：**只保留当前预算、总价值和平均期限，不足以决定最优策略。**但这个反例证明的是任务中期限结构的价值，不能直接证明 RR 架构优于能观察相同期限的普通 RNN。

所有基线均接收相同 22 项观测。所有方法共用合法动作 mask，因此零预算违规来自统一硬约束，不能算作 RR 学到的安全性质。初始时就公开预算日程，提前动作只表示利用已知日程，并非预测未知未来。

证据：`data/resource_validation.json`，`runtime/results/resource_independent_audit.json`。
""")

    paired_path = ROOT/'runtime/results/paired_counterfactual/summary.json'
    if paired_path.exists():
        paired = json.loads(paired_path.read_text())
        assert paired['runs'] == 60
        paired_rows = {r['variant']:r for r in paired['rows']}
        paired_rr = paired_rows['rr_full']
        paired_reference = paired_rows[reference]
        paired_table = []
        for name in LABELS:
            r = paired_rows[name]
            paired_table.append([LABELS[name],
                pm(r['all_conditions_mean']['normalized_utility'],100,2),
                f"{100*r['announced_shock_changes_A_t1_action_fraction']['mean']:.2f}",
                f"{100*r['normalized_utility_delta_vs_reference']['mean']:+.2f}",
                f"{100*r['negative_transfer_episode_fraction']['mean']:.2f}"])
        condition_table = []
        for name in paired['conditions']:
            condition_table.append([name,f"{paired['oracle_by_condition'][name]:.4f}",
                pm(paired_rr['by_condition'][name]['normalized_utility'],100,2),
                pm(paired_reference['by_condition'][name]['normalized_utility'],100,2)])
        d = paired_rr['normalized_utility_delta_vs_reference']
        lo,hi = d['two_way_bootstrap_95_percentile_interval']
        high_value = paired_rr['retained_value_excess_delta_vs_reference']
        high_lo,high_hi = high_value['two_way_bootstrap_95_percentile_interval']
        md(r"""
### 追加的 128 组 A/B × 有无收缩配对诊断

为了直接检验用户提出的反事实，另取 128 个独立价值向量（seed 72001），每个向量建立 A/B × 收缩 0/2 四个条件，共 512 个场景。每组的价值、预算 4、补充 1、总义务、均期与观测时间点均相同；A/B 初始观测只有四项期限特征不同，有无收缩则只有初始公布的收缩量不同。价值与期限向量应用同一个随机 item 置换。

全部 12 个模型、5 个训练种子的现有 checkpoint 再做 expected 模式闭环重放，共 30,720 条轨迹。原始 evaluator 源码不变；为避免重复解 DP，引用原 Oracle 预计算的只读表，并对 8 个场景确认所有非计时输出逐项一致。所有 checkpoint 与训练冻结摘要也再次核对。这是追加的探索性诊断，没有重新训练、选择基线或调参，不冒充新一轮确认性实验。

下表的总体效用平均四个配对条件；“提前反应”是在 A 的 t=1 处，仅因 t=0 公布的收缩量从 0 变成 2 而改变动作的种子×价值样本比例。此时 t=1.5 的收缩尚未发生。改变动作本身不一定更优，必须和实际效用及高价值保留一起看。负迁移对照固定为验证集选出的联合预算 RNN。
"""+'\n\n'+table(['模型','效用／oracle %','提前反应 %','相对强 RNN，百分点','负迁移对比例 %'],paired_table)+
        '\n\n四个条件的直接比较如下。\n\n'+
        table(['条件','oracle 平均效用','RR／oracle %','强 RNN／oracle %'],condition_table)+f"""

RR 的配对平均差为 **{100*d['mean']:+.3f} 个百分点**，探索性双向 bootstrap 95% 区间为 **[{100*lo:+.3f}, {100*hi:+.3f}]**；负迁移为 **{100*paired_rr['negative_transfer_episode_fraction']['mean']:.3f}%**，分母是 5×128×4 个种子—场景对。差距主要集中在 A＋收缩 2；两个 B 条件下两种模型的实际效用一致。

在 A 的提前反应中，RR 为 **6/640=0.9375%**，强 RNN 为 **85/640=13.28125%**。这说明当前 RR 没有在这个预先宣布预算变化的任务上体现更好的提前调整。

高值保留也没有支持优势。为排除“只因多保留了几项”的影响，我们使用终点保留价值减去相同保留数量下均匀选项的平均价值作为描述性指标。RR 减去强 RNN 的平均差为 **{high_value['mean']:+.6f}**，区间 **[{high_lo:+.6f}, {high_hi:+.6f}]**，跨过零。这个保留指标不包含提前输出，实际总效用已经同时计入提前输出与终点记忆。

冲击×期限的交互定义为 `(U_A2−U_A0)−(U_B2−U_B0)`；oracle 的平均交互为 {paired['oracle_utility_interaction_mean']:.6f}，RR 为 {paired_rr['shock_x_maturity_utility_interaction']['mean']:.6f}，强 RNN 为 {paired_reference['shock_x_maturity_utility_interaction']['mean']:.6f}。交互大小反映任务与策略如何响应两种条件，不能直接当作架构优越性的分数。

证据：`runtime/results/paired_counterfactual/summary.json`；同目录的 60 份 gzip JSON 保留全部逐例结果、动作和账本重建。
""")
        figure('figures/rrsnn_paired_counterfactual.png','同当前状态、不同期限结构与预算收缩的配对反事实')

    recovery = censored['parameter_recovery']
    calibration_table = []
    for name,label in [('untrained','未训练初值'),('trained','训练后'),('true_parameters','真参数参考')]:
        if name not in censored['pooled_test']:
            continue
        r = censored['pooled_test'][name]
        calibration_table.append([label,f"{r['censored_nll']:.6f}",f"{r['brier']:.6f}",f"{r['ece_10_equal_width']:.6f}"])
    md(r"""
## 4. R3：首达参数学习与删失概率校准

另外独立拟合了标量首达模型。真实漂移为 −0.7、噪声为 0.8；距离 x 已知并固定尺度，x∈[0.25,2]，观测期限 H∈[0.25,1.5]。每个种子有 4,096 训练、2,048 验证、4,096 测试样本，生成器使用对应逆高斯分布。拟合器只获得 `min(τ,H)` 与是否触发，未看到被删失的潜在触发时间。

正确的损失同时使用已触发密度与未触发的生存概率：

$$\mathcal L=-\delta\log f(\tau\mid x,\mu,\sigma)
-(1-\delta)\log S(H\mid x,\mu,\sigma).$$

5 个种子各做固定 400 步 full-batch Adam，float64，验证删失 NLL 选择 checkpoint。所有 2,000 步梯度有限，自动微分与中心差分最大差为 5.31×10⁻¹¹。
"""+f"\n\n恢复结果为 μ={recovery['mu_mean']:.5f}±{recovery['mu_std']:.5f}，σ={recovery['sigma_mean']:.5f}±{recovery['sigma_std']:.5f}；± 表示种子标准差。合并 20,480 个独立测试样本的结果如下。\n\n"+
       table(['模型','右删失 NLL','Brier','合并 10-bin ECE'],calibration_table)+r"""

合并 ECE 与各种子 ECE 的均值不是同一统计量。训练后合并 ECE 约为 0.007424，而种子 ECE 均值为 0.015688；报告完整保存了每个分箱的样本量、预测均值、实测比例和 Wilson 区间。

这个实验支持标量分布可从触发和删失观测中学习。生成过程就在拟合模型族中，因此尚未检验模型失配；它也没有覆盖资源控制、期限策略、循环耦合或完整硬脉冲网络的梯度。
""")
    figure('runtime/results/censored/censored_reliability.png','标量首达模型的右删失学习与概率校准')

    full_table = []
    for row in aggregate['rows']:
        ev = row['evaluation']
        full_table.append([LABELS[row['variant']],row['parameters'],row['active_state_bytes_per_sequence'],
                           pm(ev['test_expected']['normalized_utility_mean'],100,2),
                           pm(ev['future_expected']['normalized_utility_mean'],100,2),
                           pm(ev['future_hard']['normalized_utility_mean'],100,2),
                           pm(row['training_seconds'],1,2)])
    md(r"""
## 5. R4：12 个模型 × 5 种子的冻结比较

训练集 1,024 个场景、验证集 256 个；正式同分布测试与分布偏移测试分别 384 个。五个种子为 101、211、307、401、503。固定 64 epochs、batch 128、Adam 学习率 0.003、梯度范数上限 1、每次 512 个优化更新；验证集的最优动作集合 NLL 决定 checkpoint。训练使用最优策略轨迹的监督模仿，测试则运行模型自身动作造成的闭环状态转移，不是 teacher-forced 测试，也不是强化学习或 DAgger。

最初的 16-epoch LIF pilot 仅为开发实验。观察到验证损失仍在下降后，统一训练预算提高到 64 epochs，并换用新的正式测试随机种子；之后没有依据正式测试重新调参。所有原始 pilot 数据仍保留。

标准模型均为 2,001 个可训练参数，包括公共 81 动作输出头。为防止 RR 拥有更多内部状态，额外加入 96 维、低秩输入输出、对角循环的连续时间 RNN：它有 1,984 参数、384 字节活跃状态。所有模型都受同一 388 字节活跃状态上限约束，**实际状态大小并不相等**。这个上限不包括外部期限队列、输入、输出、权重、临时张量、运行库与训练图；真实进程 RSS 另测。

这里的状态字节是跨步逻辑状态的 float32 表示成本。通用 forward 还创建部分未使用的辅助张量，所以它不是实测分配上限；不能声称全进程内存已经严格匹配。成本实验单独报告完整进程峰值 RSS。

此处 ALIF 仅实现适应阈值机制，未复刻完整 LSNN 训练方案；连续时间 RNN 是明确的指数状态更新对照，不称为 CfC。全部模型看到同样的期限观测和资源日程，期限消融只改内部专用分支，原始输入投影保持一致。

主指标是每个场景“实际效用／该场景最优效用”的平均；± 是五个训练种子的标准差，非置信区间。hard 列是固定权重的硬事件代理重放，仍不是 R1 的精确连续时间网络。训练时间为各进程训练与验证的墙钟时间，宿主机有并发负载。
"""+'\n\n'+table(['模型','参数','活跃状态 B','同分布 %','偏移集 %','偏移集 hard %','训练秒'],full_table))
    comparison_table = []
    for name,label in [('test_expected','同分布 expected'),('future_expected','偏移 expected'),
                       ('test_hard','同分布 hard'),('future_hard','偏移 hard')]:
        d = comparison[name]['normalized_utility_RR_minus_comparator']
        lo,hi = d['crossed_seed_episode_bootstrap_95_interval']
        comparison_table.append([label,f"{100*d['mean_delta']:+.2f}",
                                 f"[{100*lo:+.2f}, {100*hi:+.2f}]",
                                 f"{100*d['negative_transfer_seed_episode_fraction']:.2f}%"])
    zero_test=e['test_expected']['zero_oracle_episodes']; zero_shift=e['future_expected']['zero_oracle_episodes']
    md(f"""
### 参考基线、负迁移和不确定性

参考基线由七个基线的平均验证 NLL 选择，结果为 **{LABELS[reference]}**；没有按测试收益挑选比较对象。以下差值均为 RR 减去该基线。

{table(['比较','效用差，百分点','描述性 95% 区间','负迁移，种子×场景对比例'],comparison_table)}

区间用 4,000 次配对交叉 bootstrap，同时重采样训练种子与场景索引，保持模型间配对；负迁移比例是在相同训练种子、相同场景上 RR 效用更低的比例。五个种子仍然很少，这些区间是描述性统计，未做多重比较校正，不能当作外部任务上的通用证明。

同分布集有 {zero_test}/384 个最优效用为零的场景，偏移集有 {zero_shift}/384 个。这些场景所有合法策略的实际效用也必为零，主指标约定比例为 1，并单独报告数量。排除这些场景后 RR 的同分布均值为 {pm(e['test_expected']['normalized_utility_excluding_zero_oracle'],100,2)}%，偏移均值为 {pm(e['future_expected']['normalized_utility_excluding_zero_oracle'],100,2)}%。完整 JSON 也保存原始效用、regret、预算消耗、保留价值和每例结果。

对当前候选的判断是“在这个已冻结预算与任务下没有获得晋级证据”，而非整个建模方向不可能有效。64 epochs 也不保证所有机制都达到最优；多数 checkpoint 接近预算上限，机制常数没有进行公平的大规模超参搜索。相同训练步数并不匹配 FLOPs、墙钟或实际能耗。
""")

    numeric_max = max(r['validation']['max_abs_logit_difference'] for r in controls['results'])
    md(r"""
## 6. 六项消融与实现控制

删除续约反馈同时取消续约压力对成本的作用和相关 retain gate；合并期限把内部专用分支中的期限替换为均期；历史期限重采样只使用已经观察过的历史剖面。对称聚合下，单纯同时打乱 item 的期限与 alive 对并不会改变算子，因此不能把这种无效置换当作有效期限消融。

固定边界版本与 `fp_multi_fixed` 在相同参数下数学等价，复用其训练结果；同权重检查输出完全一致，不重复计入独立模型证据。冻结资源仅固定内部控制读出的资源信号，真实环境仍使用相同预算账本和合法动作约束。

数值实现控制在完全相同的五个 RR checkpoint 下，把首达 CDF F 和折扣首达 H 换成变换后的密度积分；每段采用 48 点 Gauss–Legendre，两段积分。条件存活均值与 Lambert-W 阈值仍使用解析式，因此它不是所有解析技术的移除，也不是完整 PDE 网络。
"""+f"\n\n五个种子分别比较 64 个验证样本及两个正式集各前 64 个样本，共 640 个闭环配对案例。验证最大 logit 差为 {numeric_max:.3g}，实际动作与效用没有变化。这个控制说明这些案例的结果不依赖于 F/H 计算方式的细小数值差异；没有额外重训数值版本，不能据此断言两种实现的训练动力学完全相同。\n\n"+r"""
独立 PDE 核对来自 R1 的前向方程求解，确实是另一条数值路线。事件性能对照还包括精确指数阈值交叉的 LIF 与首达 CDF 的数值反演采样，不只与很小步长 Euler 比较。数值反演仍然调用解析 CDF，不能冒充“移除解析核”。

证据：`models/implementation_control_results.json`，`models/validation_results.json`，`runtime/results/runtime_benchmark.json`。
""")

    gap_table = []
    for r in gap['summaryByHorizon']:
        if r['horizon'] in (.5,1.,2.,4.):
            gap_table.append([r['horizon'],f"{r['meanMissedCount']:.6g}",
                              f"{100*r['meanAbsoluteMeanClosureProbabilityGap']:.3f}",
                              f"{100*r['maximumAbsoluteMeanClosureProbabilityGap']:.3f}"])
    md(r"""
## 7. 关键发现：条件均值不是可组合的生存状态

用正式 RR seed 101 checkpoint，在固定 A/B 两个初始场景提取 32 个单元控制。固定漂移、阈值、噪声、资源可用性、reset 与不应期，隔离两个局部近似：每区间最多一次事件的计数误差，以及“条件均值取代条件分布”的首达概率误差。

正确的首达组合满足

$$F(x,2h)=F(x,h)+\int_0^\infty K(y,h\mid x)F(y,h)\,dy.$$

均值闭合改成

$$F(x,h)+S(x,h)F\bigl(\mathbb E[X_h\mid\tau>h],h\bigr),$$

由于 F 对状态是非线性函数，二者通常不相等。把每个区间内部的标量函数精确计算，并不能让这个状态压缩变成精确的动态传播。
"""+'\n\n'+table(['总区间 H','单事件上限平均漏计次数','均值闭合平均误差，百分点','最大误差，百分点'],gap_table)+r"""

当前训练间隔最大为 1。在该尺度，重复发放平均只漏计 0.000150 次，而均值闭合平均首达概率差为 5.755 个百分点。因此在这个局部诊断里，应先修复生存分布传播；不能预设重复发放一定是主导问题。H=2/4 属于超过训练间隔的压力检查。

最明显的一个 H=1 例子，精确概率为 0.115372，两个半区间的均值闭合结果为 0.042011，低估 7.336 个百分点；没有触发尾部数值 clamp。32 个单元场景组合不是 32 个独立训练重复，诊断只涉及一个种子、两个初始观察上下文。

使用完整 K 的自适应积分，在 H=0.5/1/2 共 96 项检查中，直接组合差最大为 3.33×10⁻¹⁶，quad 自身最大误差估计为 4.00×10⁻¹¹。应把它解读为这些标量控制下的数值一致性，而非所有网络误差已达到机器精度。权重没有修改、完整网络没有重训、任务效用也没有因此重新改善。

后续可从正确的 K/S 条件采样或保留完整／受控近似的存活分布入手。发放后区间剩余时间、reset 与不应期、资源反馈和循环耦合也必须共同处理；只替换一个均值函数仍不够。若用粒子、低阶密度或额外状态，应重新向连续时间 RNN 分配同等参数、状态和计算预算。

证据：`hepta/proxy_exact_gap.json`，`hepta/semigroup_repair_probe.json`。
""")

    costs = []
    for r in scale:
        costs.append([LABELS[r['variant']],r['batch_instances'],
                      f"{r['latency_ms_p50']:.2f}",f"{r['latency_ms_p95']:.2f}",f"{r['latency_ms_p99']:.2f}",
                      f"{r['process_peak_rss_mib']:.2f}",f"{r['eight_step_sequences_per_second']:.0f}"])
    md(r"""
## 8. 64／256／1024／4096 规模的真实执行成本

以下实测的是当前宿主机上完整 8 步模型＋81 动作输出头，单 CPU 线程；每个模型规模组合独立进程，3 次预热、20 次计时。每行 batch 由独立状态组成，共享模型权重；只选真实长度为 8 的验证序列，在样本不足时循环 88 个模板，未把 padding 算作有效工作。每次计时都重新初始化序列状态。

该规模单位是研究代理的独立状态行，**不是已部署的 Hepta Cell 数，也不是生物神经元数量**。进程峰值 RSS 包含 Python、Torch、导入、预热、输入输出和临时分配，不等于每个状态的专属内存；吞吐按计时均值换算为完整 8 步序列／秒。
"""+'\n\n'+table(['模型','独立状态数','p50 ms','p95 ms','p99 ms','峰值 RSS MiB','8步序列/s'],costs)+r"""

当前 RR 实现执行了多次 CDF、折扣核与阈值计算，成本明显较高。4096 行时它的 p50 约 628.76ms，对照 LIF 24.38ms、联合预算 RNN 42.16ms。这个结果足以否定当前实现“解析核自动带来整网加速”的说法；不能推广为所有优化实现或硬件的固有比值。

20 次观测只能提供经验 p95/p99，不足以支撑稳定的生产尾延迟承诺。宿主机也同时运行其他任务。详细结果保存原始时间、CPU 时间、共享参数字节、活跃状态字节、输入与输出张量字节和 RSS 阶段读数；没有把 RSS 差值冒称为纯临时工作区，也没有从发放次数推断能耗。

R1 另测了 64/256/1024/4096 个参考单元、quiet 和固定 8 个活跃单元的负载，包含直接逆高斯／Levy 首达采样、CDF 反演与精确事件 LIF。4096 单元的稀疏活跃负载，中位时间分别约 0.967s、2.058s、0.118s。Brownian 和 LIF 动力学及全局同步次数不同，不能用这组数算同质量架构加速比。固定 8 个活跃单元也不代表 4096 个全活跃单元。

局部 PDE 微基准求解整个空间网格并包含网格、矩阵构建，解析式只输出一个标量概率，且 PDE 可缓存复用；两者不能被包装成端到端加速倍数。

证据：`models/scaling_results.json`，`runtime/results/runtime_benchmark.json`。
""")

    md(r"""
## 9. R5：Hepta 实际契约与离线候选

只读核对的仓库为 `TrillionniumFoundation/hepta-private-ci`，固定 commit `f8c9419df6ddeb36ff8b522a50219981fb8d9345`，日期 2026-10-16。16 个源文件及各自 blob/hash/URL 保存于 `hepta/provenance.json` 和 `hepta/sources/`。

源码中的运行链包含 NeuronRuntime、NeuronModelPort、InferenceControlModelPort 与真实 inference owner；可信运行 receipt 需要实际模型身份、参数／运行时／设备、资源与 checkpoint 上下文。纯 Q24 稀疏内核只接受宿主机提供的 frozen-head drive，并不自动执行 RR 的随机动力学。

`SparseConfig.width` 的有效范围为 5..256；协议中的 4096 是信号字段数上限，不能把它解释成 4096 维单个生产内核。当前稀疏 checkpoint 有 temporal、activation、activity、threshold、eligibility 五组 i64 向量，其基础元素存储为每维 40 字节，尚不含容器、边、journal 和其他元数据。这也不能直接与 Python 研究代理每行 384 字节混为同一语义。

已完成严格 JSON、Q24、尺寸、特征与 tick digest 的离线结构检查。100,000 个数值的 Q24 量化最大误差约 2.9802×10⁻⁸，未超过半量子；对正式 RR seed 101 的 16 维终端 latent，误差为 1.86265×10⁻⁸，没有 clipping。该候选绑定真实模型 checkpoint SHA。

结构示例使用上游协议 fixture，候选 latent 则来自合成期限任务；二者不是实际输入输出推理对。这一限制已写入 `trained_rr_seed101_shadow_provenance.json`。所有 shadow proposal 均明确无执行权、无官方 runtime receipt、无 checkpoint 发布、无生产激活。没有修改远端仓库、没有 Rust 编译验证或实际 owner 推理。

当前没有真实未来窗口、目标宿主机运行、生产 Cell 批次与真实资源审计数据。由此 R5 的真实未来效用、真实负迁移与系统规模验收尚未完成。如果只把 RR 输出接入现有 frozen-head 端口，得到的是一个辅助驱动候选，不能声称已经替换底层神经动力学。完整替换还需要版本化保存证据、期限队列、预算、不应期、事件时间与可重放随机数状态，并验证中断恢复和真实 owner receipt。

原始契约链接：

- [sparse.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f8c9419df6ddeb36ff8b522a50219981fb8d9345/codex-rs/hepta-neuron/src/sparse.rs)
- [protocol.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f8c9419df6ddeb36ff8b522a50219981fb8d9345/codex-rs/hepta-neuron/src/protocol.rs)
- [runtime.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f8c9419df6ddeb36ff8b522a50219981fb8d9345/codex-rs/hepta-neuron/src/runtime.rs)
""")

    md(r"""
## 10. 阶段验收与下一轮唯一优先事项

| 阶段 | 已获得的证据 | 不能声称已完成的部分 |
| --- | --- | --- |
| R0 | 上一轮限定模型的解析原语及数值核对 | 完整资源—期限 QVI 的解析解、全新数学定理 |
| R1 | 条件端点、输入事件、多次发放、不应期、延迟网络、独立 PDE 核对 | 连续移动边界、生产优化和完整训练网络迁移 |
| R2 | 明确续期／输出／丢弃成本、期限队列、守恒账本、独立 DP 核对 | 真实硬件能耗、未知冲击预测 |
| R3 | 标量右删失 MLE、梯度核对、独立概率校准；代理训练全部有限 | 完整硬脉冲 RR 网络的无偏／正确梯度与校准 |
| R4 | 60 组同信息、同更新预算比较，强状态预算对照，六项机制／实现控制 | 对当前候选的优越性证明、全面超参优化、整网精确求解比较 |
| R5 | 固定真实源码契约、离线 Q24 候选、4 个规模的研究代理成本 | 真实未来效用、生产负迁移、目标机 p99、实际 Cell 验收 |

**下一轮优先修复生存分布跨事件传播，再决定是否扩大任务或接入生产。**

具体的实验门槛应是：固定权重先验证时间切分、插入无操作观测、改变输入间隔不再产生额外分布偏差；在多次发放、reset、不应期、资源耗尽和阈值跳变下，与 R1 参考引擎的一致性成立。之后才做新的冻结训练矩阵，使用全新的测试集，继续让强 RNN 获得相同信息、实际状态与计算预算。

有两个诚实的实现路线。第一是 K/S 条件采样加精确事件时钟，明确处理随机梯度和事件后的剩余时间。第二是可微密度／更新算子加受控离散化，保存存活分布而不只保存其均值；它会增加状态或计算成本，必须纳入比较。任何近似闭合都应报告它对时间切分恒等式的误差，而不是只展示函数值的局部数值精度。

晋级要求应同时包含留出效用增益、负迁移、真实预算、内存和尾延迟。当前 v0 结果不足以支持直接进入 Hepta 生产链；这并不否定继续研究期限结构，而是把下一轮的首要不确定性缩小到了一个已被定位并局部验证了修复方向的动态传播问题。

## 11. 文件与重现

`README.txt` 给出依赖、执行顺序和各类结果边界。`results/aggregate.json` 保存完整主表、配对比较与统计定义；各模型目录保留五个 checkpoint、每个 epoch 的验证轨迹和逐例测试输出；`results/source_freeze.json` 记录训练源码摘要。所有模型的冻结数据与原始性能计时保留在完整 ZIP 内，新增诊断没有改变训练源码或原权重。

`make_figures.py` 和本文件只汇总已存在结果，不再拟合或调参。`aggregate_results.py` 验证 60 个 checkpoint 与冻结源码后生成主表。重跑训练命令会覆盖相应结果，应先复制目录；保留的数据已经是正式输入，不应直接用旧 pilot 数据生成 CLI 覆盖它们。
""")
    code("""
# Recompute the main summary from the saved episode outcomes. No training.
import subprocess
import sys
subprocess.run([sys.executable, '-m', 'rrsnn_experiments.aggregate_results'],
               cwd=str(ROOT.parent), check=True)
""")
    report = {'cells':cells,'metadata':{'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},
                                      'language_info':{'name':'python','version':'3.12.14'},
                                      'rrsnn_evidence_scope':'frozen synthetic research; no production activation'},
              'nbformat':4,'nbformat_minor':5}
    output = ROOT/'RR_SNN_Experimental_Report.ipynb'
    output.write_text(json.dumps(report,ensure_ascii=False,indent=1)+'\n')
    print(output,output.stat().st_size,'bytes',len(cells),'cells')


if __name__ == '__main__':
    main()
