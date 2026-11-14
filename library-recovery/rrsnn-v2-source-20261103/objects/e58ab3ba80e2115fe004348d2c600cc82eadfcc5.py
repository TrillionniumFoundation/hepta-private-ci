"""Build a self-contained Chinese research notebook from verified raw results."""
from __future__ import annotations
import base64
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parent
FIG=ROOT/'figures'
NAMES={
 'lif':'解析区间 LIF','alif':'事件刷新 ALIF','resource_lif':'资源 LIF',
 'rr_no_rollover_sampled':'FP／无续约分支','rr_fixed_sampled':'多期限／固定边界',
 'rr_density_sampled':'RR：采样训练、真实 CTMC','rr_collapse_maturity_sampled':'RR：期限分支取均值',
 'rr_shuffle_maturity_sampled':'RR：期限分支固定重排','rr_frozen_resource_sampled':'RR：冻结资源分支',
 'rr_density':'RR：分布期望','rr_moment_collapse':'RR：均值闭合消融',
 'ctrnn':'连续时间 RNN','ctrnn_matched':'状态预算匹配 RNN','ctrnn_matched_cpu':'CPU 预算匹配 RNN'}
SHORT={'rr_density_sampled':'RR / real CTMC','rr_density':'RR / density',
       'ctrnn_matched_cpu':'RNN / equal CPU','ctrnn_matched':'RNN / equal updates',
       'rr_fixed_sampled':'Fixed boundary','rr_no_rollover_sampled':'No rollover',
       'rr_collapse_maturity_sampled':'Collapsed branch','rr_shuffle_maturity_sampled':'Shuffled branch',
       'rr_frozen_resource_sampled':'Frozen resource','rr_moment_collapse':'Moment closure',
       'lif':'Analytic LIF','alif':'Event-held ALIF','resource_lif':'Resource LIF','ctrnn':'CTRNN'}

def read(relative): return json.loads((ROOT/relative).read_text())
def fmt(v,digits=2): return f'{v:.{digits}f}'
def stat(value,scale=1,digits=2): return f"{value['mean']*scale:.{digits}f} ± {value['seed_sd']*scale:.{digits}f}"
def interval(value,scale=1):
    lo,hi=value['paired_bootstrap_95_percentile_interval']
    return f"{value['mean']*scale:+.2f} [{lo*scale:+.2f}, {hi*scale:+.2f}]"
def table(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+
                     ['| '+' | '.join(map(str,row))+' |' for row in rows])

def style():
    plt.rcParams.update({'figure.dpi':140,'savefig.dpi':180,'font.size':10,
        'axes.spines.top':False,'axes.spines.right':False,'axes.titleweight':'bold',
        'axes.labelcolor':'#344054','text.color':'#1d2939','axes.edgecolor':'#98a2b3',
        'xtick.color':'#475467','ytick.color':'#475467','figure.facecolor':'white'})

def figures(aggregate):
    FIG.mkdir(exist_ok=True);style()
    d=read('audit/results/density_operator_validation.json')['convergence']
    fig,axes=plt.subplots(1,3,figsize=(13.5,3.8))
    for ax,key,x,label in [(axes[0],'space_convergence','grid','Active voltage nodes N'),
                            (axes[1],'phase_convergence','phases','Refractory phases K')]:
        rows=d[key];ax.plot([r[x] for r in rows],[abs(r['error_vs_continuous']) for r in rows],'-o',color='#2f6bce')
        ax.set_xscale('log',base=2);ax.set_yscale('log');ax.set_xlabel(label);ax.set_ylabel('Absolute mean-count error')
        ax.grid(alpha=.2)
    rows=d['floor_expansion_at_fixed_spacing'];axes[2].plot([-r['lower_bound'] for r in rows],
        [abs(r['error_vs_continuous']) for r in rows],'-o',color='#d97735')
    axes[2].set_xscale('log',base=2);axes[2].set_yscale('log');axes[2].set_xlabel('Reflecting-floor distance -L')
    axes[2].set_ylabel('Absolute mean-count error');axes[2].grid(alpha=.2)
    for ax,title in zip(axes,['Spatial refinement, K=128','Phase refinement, N=256','Floor expansion, fixed spacing']): ax.set_title(title)
    fig.suptitle('Continuous-model approximation: three distinct error sources',y=1.03,fontsize=14)
    fig.tight_layout();fig.savefig(FIG/'rrsnn_v2_convergence.png',bbox_inches='tight');plt.close(fig)

    order=['lif','alif','resource_lif','rr_no_rollover_sampled','rr_fixed_sampled','rr_density_sampled',
           'rr_density','ctrnn','ctrnn_matched','ctrnn_matched_cpu','rr_collapse_maturity_sampled',
           'rr_shuffle_maturity_sampled','rr_frozen_resource_sampled','rr_moment_collapse']
    by={r['run_name']:r for r in aggregate['rows']};ys=np.arange(len(order))
    fig,axes=plt.subplots(1,2,figsize=(12,7.4),sharey=True)
    colors=['#d97735' if name=='ctrnn_matched_cpu' else '#2f6bce' if name=='rr_density_sampled' else '#667085' for name in order]
    for ax,dataset,title in zip(axes,['test','shift'],['Synthetic test','Synthetic distribution shift']):
        for y,name,color in zip(ys,order,colors):
            s=by[name]['evaluation'][dataset]['metrics']['normalized_utility']
            ax.errorbar(100*s['mean'],y,xerr=100*s['seed_sd'],fmt='o',color=color,capsize=3)
        ax.set_title(title);ax.set_xlabel('Mean oracle-normalized utility (%)')
        ax.set_xlim(0,102);ax.grid(axis='x',alpha=.2)
    axes[0].set_yticks(ys,[SHORT[n] for n in order]);axes[0].invert_yaxis()
    fig.suptitle('Frozen protocols, five training seeds; bars are seed SD',fontsize=14)
    fig.tight_layout();fig.savefig(FIG/'rrsnn_v2_main_results.png',bbox_inches='tight');plt.close(fig)

    names=['rr_density_sampled','ctrnn_matched_cpu','rr_density'];conditions=['A0','A2','B0','B2']
    fig,ax=plt.subplots(figsize=(9,4.6));x=np.arange(4);width=.24
    for j,(name,color) in enumerate(zip(names,['#2f6bce','#d97735','#8994a8'])):
        values=[by[name]['evaluation']['paired']['by_condition'][c]['normalized_utility']['mean']*100 for c in conditions]
        sd=[by[name]['evaluation']['paired']['by_condition'][c]['normalized_utility']['seed_sd']*100 for c in conditions]
        ax.bar(x+(j-1)*width,values,width,yerr=sd,label=SHORT[name],color=color,capsize=3)
    ax.set_xticks(x,['A / no shock','A / shock 2','B / no shock','B / shock 2'])
    ax.set_ylabel('Oracle-normalized utility (%)');ax.set_ylim(0,106);ax.legend(frameon=False,ncol=3,loc='upper center',bbox_to_anchor=(.5,1.16))
    ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
    ax.set_title('Matched values, budget, memory count and mean deadline',pad=38)
    fig.tight_layout();fig.savefig(FIG/'rrsnn_v2_paired_results.png',bbox_inches='tight');plt.close(fig)
    coupled=read('coupled/results/aggregate.json')
    fig,axes=plt.subplots(1,2,figsize=(11.5,4.5),sharey=True)
    names=['test','shift','paired'];x=np.arange(3)
    for ax,milestone,title in zip(axes,['fixed_updates','equal_cpu'],['Equal updates','Matched CPU targets']):
        r=coupled['milestones'][milestone]
        for j,(role,color,label) in enumerate([('candidate','#2f6bce','Spike feedback SNN'),('reference','#d97735','Time-basis RNN')]):
            points=[r['datasets'][dataset][role]['metrics']['normalized_utility'] for dataset in names]
            ax.bar(x+(j-.5)*.34,[p['mean']*100 for p in points],.34,
                   yerr=[p['seed_sd']*100 for p in points],color=color,label=label,capsize=3)
        ax.set_xticks(x,['Test','Shift','Paired']);ax.set_title(title);ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
        ax.set_ylim(0,106)
    axes[0].set_ylabel('Oracle-normalized utility (%)')
    handles, labels = axes[1].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, loc='lower center', ncol=2,
               bbox_to_anchor=(.5, -.025))
    fig.suptitle('Actual spike-feedback supplement: five seeds, synthetic tasks',fontsize=14)
    fig.tight_layout(rect=(0, .06, 1, 1));fig.savefig(FIG/'rrsnn_v2_coupled_results.png',bbox_inches='tight');plt.close(fig)
    return ['rrsnn_v2_convergence.png','rrsnn_v2_main_results.png','rrsnn_v2_paired_results.png','rrsnn_v2_coupled_results.png']

def md(source): return {'cell_type':'markdown','metadata':{},'source':source}
def image_cell(filename,caption):
    data=base64.b64encode((FIG/filename).read_bytes()).decode()
    return {'cell_type':'code','execution_count':None,'metadata':{},'source':f'# {caption}',
        'outputs':[{'output_type':'display_data','data':{'image/png':data,'text/plain':[caption]},'metadata':{}}]}

def coupled_result_tables():
    report=read('coupled/results/aggregate.json')
    rows=[]
    for milestone,label in [('fixed_updates','固定 256 更新'),('equal_cpu','CPU 预算目标匹配')]:
        item=report['milestones'][milestone]
        for dataset in ['test','shift','paired']:
            comparison=item['paired_comparisons'][dataset]
            rows.append([label,dataset,NAMES[item['comparator']],
                stat(item['datasets'][dataset]['candidate']['metrics']['normalized_utility'],100),
                stat(item['datasets'][dataset]['reference']['metrics']['normalized_utility'],100),
                interval(comparison['contrasts_candidate_minus_reference']['normalized_utility'],100),
                f"{comparison['negative_transfer_episode_fraction']['mean']*100:.2f}%"])
    training=[]
    for milestone,label in [('fixed_updates','固定更新'),('equal_cpu','同 CPU 目标')]:
        item=report['milestones'][milestone]['training']
        training.append([label,stat(item['best_validation_nll']),stat(item['train_cpu_seconds']),
                         stat(item['updates']),stat(item['actual_training_spikes']),
                         stat(item['cpu_budget_overshoot_seconds'])])
    return table(['预算','数据','预定对照','coupled 效用 %','对照效用 %','差 / 百分点 [95% CI]','负迁移'],rows)+\
        '\n\n'+table(['预算','验证 NLL','训练 CPU 秒','更新数','实际训练 spikes','CPU 目标超额秒'],training)+\
        '\n\n两行来自五条训练轨迹的不同里程碑，不当作十个独立训练 seed。固定更新行不按 CPU 预算停止，超额栏记为零。'

def measured_cost_table():
    rows=[]
    for path,is_coupled in [('benchmark_results/scaling_results.json',False),
                            ('coupled/benchmark_results/scaling_results.json',True)]:
        report=read(path)
        if len(report['results'])!=(4 if is_coupled else 20):
            raise ValueError('Refuse a partial formal cost table: '+path)
        ordering={'rr_density_sampled':0,'lif':1,'ctrnn':2,'ctrnn_matched':3,'ctrnn_matched_cpu':4}
        for r in sorted(report['results'],key=lambda item:(ordering.get(item['run_name'],99),item['rows'])):
            label='RR：真实脉冲反馈' if is_coupled else NAMES[r['run_name']]
            eligible=r['resource_observation']['primary_resource_table_eligible']
            condition='未观察到限额事件' if eligible else r['resource_observation']['condition']
            rows.append([label,r['rows'],fmt(r['tick_latency_ms_p50'],3),fmt(r['tick_latency_ms_p95'],3),
                         fmt(r['tick_latency_ms_p99'],3),fmt(r['row_ticks_per_second'],1),
                         fmt(r['process_peak_rss_bytes']/2**20,1),condition])
    return table(['实现','实例数','p50 ms','p95 ms','p99 ms','实例-ticks/s','进程峰值 MiB','资源窗口'],rows)

def build():
    a=read('results/aggregate.json');plan=read('experiment_plan.json')
    coupled=read('coupled/results/aggregate.json')
    coupled_shift=coupled['milestones']['equal_cpu']['paired_comparisons']['shift']['contrasts_candidate_minus_reference']['normalized_utility']
    by={row['run_name']:row for row in a['rows']};primary=a['comparisons']['primary']
    shift=primary['datasets']['shift'];paired=primary['datasets']['paired']
    delta=shift['contrasts_candidate_minus_reference']['normalized_utility']
    ci=delta['paired_bootstrap_95_percentile_interval']
    if ci[1]<0: verdict='主候选在预先锁定的同 CPU 对照下落后；这轮结果不支持晋升该候选。'
    elif ci[0]>0: verdict='主候选在预先锁定的合成 shift 比较中取得正差异；这仍不足以替代真实未来窗口和目标系统验收。'
    else: verdict='主比较没有建立主候选相对同 CPU 基线的优势；区间包含零，不应把均值差包装为已证实的优劣。'
    figs=figures(a)
    comparison_rows=[]
    for name in ['test','shift','paired']:
        c=primary['datasets'][name]
        comparison_rows.append([name,interval(c['contrasts_candidate_minus_reference']['normalized_utility'],100),
            f"{100*c['negative_transfer_episode_fraction']['mean']:.2f}%",
            f"{100*c['positive_transfer_episode_fraction']['mean']:.2f}%",c['actual_aligned_replay_episode_comparisons']])
    main_rows=[]
    for row in a['rows']:
        main_rows.append([NAMES[row['run_name']],stat(row['validation_nll']),
            stat(row['evaluation']['test']['metrics']['normalized_utility'],100),
            stat(row['evaluation']['shift']['metrics']['normalized_utility'],100),
            fmt(row['training_cpu_seconds']['mean'],1),fmt(row['actual_updates']['mean'],0)])
    c=[]
    c.append(md('# RR-SNN v2：从解析原语到真实事件、可训练策略与可复现实验\n\n'
        +verdict+'\n\n本报告保存完整结果、模型定义、方法边界和尚未闭合的外部验收条件。'
        '数学原语正确、合成任务有效、实际系统可部署分别有各自的证据要求。'
        '本轮没有将任何未注册研究状态激活到生产 Hepta，也没有生成官方 owner 回执。\n\n'
        f"主矩阵：{a['models']} 组配置 × 5 seeds = {a['completed_training_runs']} 次训练。"
        '新 train/validation/test/shift 数据量分别为 1024/256/512/512；另有 128 个匹配价值组、每组四个 A/B×冲击反事实。'
        '全部主要模型含 977 个参数，共用 22 维观察与 81 动作空间。'))
    c.append(md('真实脉冲反馈补充实验独立训练五个种子，每条轨迹保存固定更新和同 CPU 目标两个里程碑。'
        '其同 CPU 目标下的合成 shift 效用差为 **'+interval(coupled_shift,100)+' 个百分点**。'
        '该结果与主矩阵分别检验、分别记录；完整路径可训练性没有自动带来任务性能优势。'))
    c.append(md('## 从原论文借用了什么\n\n'
        '[He 与 Xiong (2012)](https://www.princeton.edu/~wxiong/papers/rollover.pdf) 把续约损失、继续价值和内生违约边界联立求解，'
        '使用平稳债务结构以及 Laplace 变换等解析技术。原文允许增发权益承担损失；本实验另加的硬资源预算和有限期限队列不是原文直接给出的神经元模型。\n\n'+
        table(['本项目保留的数学结构','神经算子中的明确选择'],[
            ['到达边界的事件','证据首达触发脉冲，随后 reset 与不应期'],
            ['继续价值与更新成本相互作用','记忆续约、输出与释放共用资源账本'],
            ['期限影响当前决策','保留逐项期限，比较相同均值下的不同到期分布'],
            ['解析传播与边界条件','受限标量解析核；有限 CTMC 矩阵指数；真实事件采样']])+
        '\n\n这是一个需要实验检验的工程建模选择；金融变量没有被直接当成生物变量，当前也没有生物神经记录拟合证据。'))
    c.append(md('### 任务效用、内部脉冲与预算的单位\n\n'
        '任务包含四个带价值和期限的记忆项。到期时可释放、续约两单位时间，或输出提前结果；续约／输出各耗费一单位预算，释放免费。'
        '终点 T=4 的左极限查询仍存活的项目。给定 early_penalty=0.15，总效用为\n\n'
        '$$U=\\sum_{i\\,\\mathrm{emitted}} v_i e^{-0.15(4-t_i)}+\\sum_{i\\,\\mathrm{alive\\ at}\\ 4^-}v_i.$$\n\n'
        '资源冲击先扣除当前可用预算，补充随后按固定事件时序入账；各模型共用精确合法动作 mask。'
        '因此预算不透支是共同环境约束的结果，不能单独归功于某个神经元。归一化效用是每个场景 U/U* 再取均值，U* 由独立动态规划求出。\n\n'
        '这里有两个不同的事件单位：隐藏神经元的内部 spike，以及任务 head 选择的记忆输出动作。'
        '任务预算对后者及续约计费；内部 spike 未逐次从同一账本扣款。边界公式中的 cost 是由资源／期限信息构造的策略参数，'
        '不是已测量的每个脉冲能耗。实际计算成本由独立 CPU、RSS、吞吐与时延测试记录。'))
    c.append(md('## 1. 已冻结主比较的结果\n\n'
        '主候选是 `rr_density_sampled`：以观测端点状态轨迹的似然比梯度训练，部署评估由真实 Gillespie CTMC 执行。'
        '主对照 `ctrnn_matched_cpu` 在打开新 holdout 前锁定，每个 seed 的 CPU 训练预算目标等于候选对应 seed 的实测值；'
        '停止发生在完整 epoch／validation 边界，实际超出量保留在 receipt，不宣称逐秒相等。'
        '普通固定预算组均为 32 epochs、256 次 Adam 更新。\n\n'+table(
        ['数据','归一化效用差 / 百分点 [95% CI]','负迁移','正迁移','实际配对回放数'],comparison_rows)+
        '\n\n差值方向为候选减去对照。负迁移按每次真实回放的原始效用比较，在平均回放之前取符号。'
        '置信区间对训练 seed 与共享场景／价值组做成组配对 bootstrap，10,000 次；paired 的四个条件保持在同一价值组内。'
        '区间条件于已固定的有限路径回放，并不额外估计无限未来脉冲采样的全部方差。只有五个训练 seed，结论的外推范围有限。'))
    c.append(md('### 全部主配置\n\n'+table(['配置','验证 NLL','test 效用 %','shift 效用 %','训练 CPU 秒均值','更新数均值'],main_rows)+
        '\n\n“±”是五个 seed 的样本标准差，不是置信区间。所有选择使用 validation，不按 test/shift 的最好结果选择基线。'
        f"次要对照由预列候选中的最低平均 validation NLL 确定：`{a['secondary_comparator']}`。"
        '零 oracle 效用的场景统一记归一化效用为 1；两模型在这些场景的差为零，原始效用与零分母场景数量均保存在原始 JSON。'))
    c.append(image_cell(figs[1],'主结果：五个训练 seed 的均值与标准差；这是合成数据比较。'))
    c.append(md('## 2. 相同当前状态、不同期限结构\n\n'
        '每个组共用四个记忆价值、初始预算 4、记忆数 4、平均期限 2；A 的期限为 `(1,1,3,3)`，B 为 `(2,2,2,2)`。'
        '两者初始输入仅第 7–10 号期限特征不同。预算冲击为 0 或 2，发生在 t=1.5；t=2.5 补充 1。'
        '价值与未来资源日程在 t=0 对所有模型同样宣布，后续价值 cue 不重复给出。这里测量的是对已宣布未来压力的提前调整。\n\n'
        '每个随机策略、每个 seed 回放四次，确定策略一次并在比较中广播；没有把广播复制当作新增独立样本。'
        '终末保留值、高值项目保留比例及同数量保留超额同时记录，但这些指标不包含提前输出收益，不能取代总效用。'))
    c.append(image_cell(figs[2],'匹配反事实：A/B 有相同平均期限；误差条为 seed SD。'))
    strict=read('audit/strict_initial_counterfactual/aggregate.json')
    strict_comparison=strict['paired_comparison']
    c.append(md('### 补充：共同的实际初始神经状态\n\n'
        '主矩阵匹配了初态分布，四条件的实际初态抽样各自独立。另一个在打开 holdout 前声明的诊断，'
        '先从正确 reset 分布为每个价值组抽一个完整实际状态，再复制给四个条件。'
        '初始 indices、电位、context、drift、boundary、time、counts 与 observed 标记逐位相同；该主模型没有独立 spike-trace buffer。'
        '四份复制只计为一个初态样本。四个审计 seed 各 4096 组的边际检验最大 |z|=1.773。\n\n'
        '共同状态指 t=0 观察之前；期限介入后控制与后续路径可以分化，未来噪声没有强制共享。该实验仍使用同一因果账本与对照，'
        '5 个训练 seed、128 组、4 次真实回放得到：\n\n'+table(
        ['指标','严格共同初态诊断'],[
            ['候选归一化效用 %',stat(strict['candidate']['metrics']['normalized_utility'],100)],
            ['同 CPU RNN 效用 %',stat(strict['reference']['metrics']['normalized_utility'],100)],
            ['效用差 / 百分点 [95% CI]',interval(strict_comparison['contrasts_candidate_minus_reference']['normalized_utility'],100)],
            ['负迁移比例',f"{strict_comparison['negative_transfer_episode_fraction']['mean']*100:.2f}%"]])+ 
        '\n\n'+table(['终点诊断','主 RR 候选','同 CPU RNN'],[
            ['保留价值',stat(strict['candidate']['metrics']['retained_value'],digits=4),stat(strict['reference']['metrics']['retained_value'],digits=4)],
            ['最高两项的保留比例 %',stat(strict['candidate']['metrics']['retained_top2_fraction'],100),stat(strict['reference']['metrics']['retained_top2_fraction'],100)],
            ['相同保留数量的价值超额',stat(strict['candidate']['metrics']['retained_value_excess_same_count'],digits=4),stat(strict['reference']['metrics']['retained_value_excess_same_count'],digits=4)]])+
        '\n\n终点指标不包括提前输出的收益，须与总效用同时解读。原始主 paired 结果未被替换。证据位于 `audit/strict_initial_counterfactual/`。'))
    c.append(md('### 提前动作的分布检查\n\n'
        '独立 probe 在 A 场景 t=1 的首个决策比较宣布冲击 0 与 2。此刻预算、alive、价值和当前到期状态完全相同；冲击尚未发生。'
        '随机候选对每个价值组与条件使用 64 条真实脉冲路径，报告期望续约数与输出数的处理效应。'
        '随机单路径动作不一致本身不能证明提前响应；经验动作分布 TV 在有限样本下上偏，因此只作描述性指标。\n\n'
        '完整 probe 和处理效应区间位于 `results/anticipation_probe.json` 与主 aggregate 的 `anticipation_probe` 字段。'))
    if a['anticipation_probe']['status']!='complete':raise ValueError('Anticipation probe incomplete')
    c.append(md(table(['策略','冲击 2−0：续约数 [95% CI]','冲击 2−0：输出数 [95% CI]'],[
        [NAMES[r['run_name']],interval(r['renewal_treatment_effect']),interval(r['emission_treatment_effect'])]
        for r in a['anticipation_probe']['rows']])+
        '\n\n这些区间比较同一策略对宣布冲击的动作响应；动作响应本身不等于比其他策略获得更高效用。'))
    c.append(md('## 3. 修复的动力学与仍存在的模型近似\n\n'
        '连续标量原语采用到阈值的距离 $X_t=x+\u03bc t+\u03c3 W_t$，$x>0$，在 0 吸收。'
        '其首达密度与存活联合密度分别为\n\n'
        '$$f(t\\mid x)=\\frac{x}{\\sigma\\sqrt{2\\pi t^3}}\\exp\\!\\left[-\\frac{(x+\\mu t)^2}{2\\sigma^2t}\\right],$$\n\n'
        '$$K_t(y\\mid x)=\\frac{\\exp[-(y-x-\\mu t)^2/(2\\sigma^2t)]}{\\sigma\\sqrt{2\\pi t}}'
        '\\left(1-\\exp[-2xy/(\\sigma^2t)]\\right),\\quad y>0.$$\n\n'
        '这里的 K 是未归一化的 killed kernel，积分为存活概率；条件于未发放时才除以该积分。'
        '首达事件使用 f，末段没有事件时使用存活概率；折现首达量不能直接当作发放概率。'
        '输入事件之间的生存传播可定义为 $\\mathcal A_tg(x)=e^{-\\rho t}\\int_0^\\infty K_t(y\\mid x)g(y)dy$，'
        '再连接首达输出、reset 与不应期的 renewal 算子。以上是经典首达数学的应用，不声称它们为本项目新定理。\n\n'
        'v2 保存完整有限状态概率分布，而非把条件均值重新当作单点证据。默认每个神经元有 16 个活动电位节点、2 个 Erlang 不应期相位。'
        '跨阈值跳转产生脉冲，随后经过不应期相位并重置；同一区间可以反复发放。行向量约定为\n\n'
        '$$p(t+\\Delta)=p(t)\\exp(Q\\Delta).$$\n\n'
        '累计期望计数通过带 reward column 的增广矩阵指数计算。独立长区间测试得到 8.733 次期望发放，未施加每段一次的上限。'
        '步进顺序为：用旧控制推进到当前时间、接收当前观察、更新控制与跳变、读出。首帧 dt=0；no-op 只推进时间，不能偷偷重算控制。\n\n'
        '独立审计中，有限 CTMC 的半群误差为 4.44×10⁻¹⁵；32,768 条真实 Gillespie 路径的平均发放计数对矩阵指数参照相差 0.740 个标准误。'
        '这些是指定有限模型的实现证据。相对于连续 Brownian＋确定性不应期参照，默认 N=16、K=2 在一组明确测试中仍有 +0.088614 的平均计数误差。'
        '空间网格、反射下界、相位数和观测 remap 分开检查，不能由极小的矩阵求值误差推断连续模型误差同样小。'))
    c.append(image_cell(figs[0],'三个独立收敛方向。每个面板固定其余条件；原始参数与参照值在审计 JSON 中。'))
    c.append(md('### 真实事件方法与数值替代\n\n'
        'LIF 对照使用恒定电流区间的解析首达时间、发放周期、reset、不应期以及所有事件时刻的指数迹，未使用小步 Euler 作为唯一参照。'
        '三个脉冲基线各 200 个随机区间与独立标量事件循环核对，整数计数差为零，状态最大差约 4.05×10⁻¹⁵。'
        'ALIF 是观察事件刷新、区间内保持阈值的明确版本；它没有完整复现连续衰减阈值 ALIF／LSNN 的训练方案。\n\n'
        '这些 LIF 对照的 hard forward 执行整数真实事件；训练 backward 使用 sigmoid／连续计数 surrogate，属于有偏梯度估计。'
        '资源 LIF 用当前观测预算调节阈值，也是启发式策略，不宣称求解完整资源控制问题。\n\n'
        '同一权重下，matrix exponential 与 uniformization 的验证集实现控制已覆盖五个 seed；另有数值求根边界＋uniformization 的完整有限算子控制。'
        '完整控制中，36 个标量根对独立 brentq 的最大差为 4.88\u00d710\u207b\u00b9\u2075，隐函数梯度有限差分误差 3.28\u00d710\u207b\u00b9\u2070。'
        '五个正式权重、每个 64 个 validation 场景共 570 个合法决策没有 argmax 差异；logits 最大差 1.91\u00d710\u207b\u2075，'
        'expected-set NLL 最大差 4.77\u00d710\u207b\u2077，全部参数梯度相对 L2 差最大 3.26\u00d710\u207b\u2076。'
        '此处 backward 专指这些采样训练权重上的确定性 expected-distribution NLL，'
        '不包括 endpoint likelihood-ratio 或 coupled full-path 目标的数值替代比较。\n\n'
        '数值控制不改变资源任务和读出，也不把有限 CTMC 当成已求出的连续 PDE。该控制比较求值与局部反向梯度，不声称进行了两套实现的全流程重新训练。'))
    c.append(md('### 相同权重、不同传播／决策方式\n\n'+table(
        ['训练版本','实际回放模型','数据','归一化效用 %','相对原执行方式差 / 百分点 [95% CI]'],[
            [NAMES[r['run_name']],r['backend'],r['dataset'],
             stat(r['target']['metrics']['normalized_utility'],100),
             interval(r['target_minus_primary_execution']['contrasts_candidate_minus_reference']['normalized_utility'],100)]
            for r in a['transfer_diagnostics'] if r['status']=='complete'])+
        '\n\nBrownian 回放采用连续证据、确定性不应期和真实首达；它与有反射下界／Erlang 相位的有限 CTMC 是不同物理模型。'
        '将分布训练权重用于真实 CTMC 也会改变非线性动作决策，因此这些是事先声明的迁移诊断，不是相同模型精确相等的检查。'
        '没有根据该表重新选取主候选。'))
    c.append(md('## 4. 三种训练证据的清楚区分\n\n'+
        table(['层次','随机对象与梯度','能够支持的结论'],[
          ['标量删失校准','首达密度及末段 survival','受限模型的事件概率、删失似然与参数拟合'],
          ['主候选 endpoint 训练','观测端点 CTMC 状态；区间内事件积分消去','观测状态轨迹的期望决策 NLL 梯度'],
          ['真实事件路径训练','实际跳变计数、驻留时间、初态／remap 概率','真实事件网络在固定示教输入上的期望决策 NLL 梯度']])+
        '\n\n主候选的 score-function 估计同时保留损失的直接导数：\n\n'
        '$$\\nabla_\\theta E[L]=E[\\nabla_\\theta L+(L-b)\\nabla_\\theta\\log p_\\theta(Z)].$$\n\n'
        'baseline 使用其他序列的 leave-one-sequence-out 损失并 detach；条件于输入与参数，各序列采样独立。'
        '独立小模型完全枚举了 96 条非零端点路径，损失与四个参数梯度的 Monte Carlo 结果与精确枚举相符。'
        '这类训练目标是固定示教输入的决策 NLL，并非动作改变资源环境后的终点效用策略梯度。\n\n'
        '另外完成两神经元真实首达、reset、确定不应期的延迟 count 反馈训练：三个 seed 的精确期望 cost 从 1.951156 降到约 0.636，'
        '路径 score 梯度有独立 renewal-count 分布的参照。这是指定小网络的训练证据。'))
    c.append(md('### 补充：真正由脉冲反馈驱动的循环网络\n\n'
        '主矩阵的 CTMC 控制器由确定性观察历史 context 驱动。为覆盖随机脉冲反馈，本轮另实现 `coupled/`：'
        '循环权重只读取真实脉冲的指数迹，head 只读取脉冲迹，控制只在真正观察事件更新。'
        '当前 remap 即时脉冲立即进入 head，在下一次真正观察才更新循环控制。\n\n'
        '每段真实 Gillespie 路径的对数似然为\n\n'
        '$$\\log p=\\sum_{i\\ne j}N_{ij}\\log q_{ij}-\\sum_i T_i\\lambda_i'
        '+\\log p_{\\mathrm{initial}}+\\sum\\log P_{\\mathrm{remap}}.$$'
        '\n\n它包含最后的右删失驻留时间和参数相关 reset 分布。漏掉初态／重复 reset 的边界导数会产生明显错误。'
        '补充计划在打开 holdout 前冻结，分别保存固定 256 更新与同 CPU 总预算的 validation 最优检查点；这是同一训练轨迹的两个里程碑。'
        '结果单独保存在 `coupled/results/aggregate.json`，不替换主比较，也不称为连续时刻即时反馈的全异步网络。'))
    c.append(md('### 脉冲反馈网络的独立结果\n\n'+coupled_result_tables()))
    c.append(image_cell(figs[3],'真实脉冲反馈网络：两个事先指定的预算比较；全部数据为合成任务。'))
    c.append(md('## 5. 期限结构必要性的严格有限反例\n\n'
        '在另一个完全规定的有限控制模型中，Y=2、budget=2、两个义务价值均为 1、记忆总量 2、平均期限 2，'
        '仅改变期限 A=(1,3)、B=(2,2)，得到：\n\n'+table(
        ['首动作','A 的 Q 值','B 的 Q 值'],[['等待','3.9403969893','2.1843707397'],['最佳立即输出','3.6648448011','2.5875900237'],['严格最优','等待','立即输出']])+
        '\n\n若 A/B 各有一半先验概率，首步只看到合并汇总状态，即使首步之后恢复完整期限信息，最小平均 regret 仍为 0.1377760941。'
        '随机化首动作不能超过线性目标的最佳纯动作。这个构造证明仅保留均值等汇总量并不普遍充分；它不证明 RR 网络胜过同样获得期限信息的 RNN。'
        '完整 specification、569 个已求值状态、初始 Q 表与前向回报／预算核验保存在 `audit/results/full_control_bellman.json`。'))
    c.append(md('## 6. Lambert-W 特例与完整控制问题\n\n'
        '对向上证据 $dY=a\\,dt+\\sigma\\,dW$、无限时域、固定输出效用 Y−c、reset 为 $y_r$、固定不应期，'
        '假设 $c>y_r$、$\\rho,\\sigma>0$、$\\tau\\geq0$，且不应期内无其他状态变化。对这个标量问题，'
        '值匹配和光滑拼接给出\n\n'
        '$$\\gamma=\\frac{\\sqrt{a^2+2\\rho\\sigma^2}-a}{\\sigma^2},\\qquad'
        ' h=c+\\frac{1+W_0(-\\exp[-\\rho\\tau-1-\\gamma(c-y_r)])}{\\gamma}.$$'
        '\n\n这条 Lambert-W 表达式由上述限定神经控制问题推导，不是 He–Xiong 原文的违约边界公式。'
        '该特例的 QVI 残差与阈值策略最优性已经核验。当前控制器把资源和期限压力映射为 cost，再使用该公式并裁剪边界，'
        '是一个具有解析结构的策略类。它没有求解整个资源、期限与延迟网络的价值函数。\n\n'
        '完整状态至少包含证据、预算、逐项剩余期限、价值、不应期、已宣布外生事件与未到达的延迟事件。内部 QVI 需要等待生成元、'
        '输出／释放干预算子，并在到期与资源冲击处指定联合边界跳转；共享预算使逐项独立最大化通常失效。'
        '不应期内资源和期限继续变化时，继续价值必须使用完整转移算子，不能只乘一个折现因子然后 reset。'
        '详细推导与合法适用范围在 `audit/full_control_qvi.txt`。本轮未求出一般多维连续 QVI 的全局解析解或普遍策略误差界。'))
    c.append(md('### 续约压力映射到 cost 的含义需要保留\n\n'
        '在上述冻结标量问题中，令 $q=\\exp[-\\rho\\tau-\\gamma(h-y_r)]$，由隐函数求导得到 '
        '$\\partial h/\\partial c=1/(1-q)>0$。因此，其他条件不变时，提高输出成本会推迟向上的首达输出。'
        '当前实现把期限压力的一部分加到这个 cost 上，是一种具体策略归纳偏置。'
        '它与把将来到期的续约负担直接写入继续价值、从而改变提前输出意愿的完整控制问题并不相同。\n\n'
        '这说明“金融模型能给出内生边界”还不足以证明当前神经元的压力映射方向最优。'
        '本轮消融和任务结果用于检验这个选择；不能把正确的求根或梯度检查当作该建模选择已被证实。'))
    c.append(md('## 7. 资源成本与 Hepta 对接\n\n'
        '资源实验的横轴是 64/256/1024/4096 个同时驻留的策略状态，共享一组权重，每个策略含八个隐藏单元。'
        '这些是本机参考实现的策略实例；没有把它们改称真实生产 Hepta Cell。\n\n'
        '主测量固定 CPU 7、单线程、5 条预热序列、25 条八步序列，共 200 个全行批处理 tick 时延样本。'
        '主表报告 tick p50/p95/p99、row-ticks/s 和峰值进程 RSS；25 个 whole-sequence 样本另列，其 p99 仅作探索。'
        '所有实例状态先驻留，再按同一 microbatch 协议处理。\n\n'
        '训练中的首轮成本测试发现共享 cgroup 内存回收压力；原始极端值完整保留在 `benchmark_results/memory_pressure_run/`，'
        '未据此形成稳定算法尾延迟结论。主表由独立 observer 记录每行测量前后的 memory.events/current/stat 与磁盘余量，'
        '发生触顶、OOM 或状态未知的行不能被静默当作正常结果。\n\n'
        '全部主要模型的可训练参数均为 977；676 B 是共同的数值状态上限，不是每种模型都占用完全相同字节。'
        '实际推理持久数值状态为：普通 RNN 64 B、LIF 128 B、资源 LIF 160 B、ALIF 192 B、真实 CTMC 233 B、'
        'coupled 305 B、分布版／匹配 RNN 672 B、冻结资源分布版 676 B。'
        '主候选训练时使用完整端点分布，部署时真实 CTMC wrapper 去除冗余概率表，不能把部署 233 B 当作其训练占用。'
        '固定 buffers、RNG、Python 对象、临时 Q、反向图及进程基础开销另计。资源账本是合成任务的无量纲预算，没有把脉冲次数换算成未经测量的焦耳。'))
    c.append(md('### 完整本机成本表\n\n'+measured_cost_table()+
        '\n\n每个 tick 处理该行全部 N 个策略实例。吞吐单位是实例-ticks/s，不能把批次时延除以 N 后当作逐请求 p99。'
        '进程 RSS 包含 Python、框架、输入与输出、工作区和分配器；它不等于状态数组大小。'
        '这批共享权重的状态实例也不包含真实 Hepta owner 路由和 Cell 组件成本。\n\n'
        'coupled 使用事先固定的 equal_cpu seed101 权重，按相同输入和计时协议单独增补。'
        '其原生推理仍计算跳变计数、驻留时间和路径 score；这些当前可优化的实现开销全部计入，不能据此声称架构理论下界。'
        '所有受压或资源状态未知的行原样保留并标记，不形成未经限定的稳定尾延迟结论。'))
    c.append(md('### 已实际完成的 Hepta 离线集成\n\n'+table(['项目','证据'],[
        ['真实源码编译','锁定提交 f8c9419df6ddeb36ff8b522a50219981fb8d9345；三个完整原始 crate 的库目标在缩小工作区编译，62 个源文件字节未改'],
        ['官方类型与摘要','5 项适配合约测试通过；codec、feature/tick digest 与独立 Python 重算一致'],
        ['Rust 物理 checkpoint','6 项测试通过；完整 RNG 与状态两条 Rust 往返路线重现后续三个真实脉冲'],
        ['正式权重联合恢复','四个恢复点重现实际脉冲、动作、期限队列、资源账本与终态；八类非法恢复拒绝'],
        ['新脉冲反馈状态恢复','另建完整 trace/context/pending-score/RNG 适配器；两个 seed101 里程碑共八个恢复点、十八个拒绝案例通过'],
        ['审阅 shadow proposal','真实八维 sampled latent 经过官方类型适配，Q24 最大误差 2.98×10⁻⁸；owner_executed=false，activation=false']])+
        '\n\n上述构建不等同于整个 monorepo 编译或正式 owner 执行。研究 envelope 尚未注册到生产协议；原 V1 对未知物理状态字段的拒绝行为已保留。'))
    c.append(md('## 8. 哪些 gate 尚未闭合\n\n'
        '当前可调用环境没有验证过的 dot／目标机执行入口，没有正式 inference owner 回执，也没有真实独立未来窗口与真实 Cell 工作负载。'
        '因此无法完成目标机上的 64/256/1024/4096 Cell 资源验收、真实未来效用与负迁移验收，或证明生产 journal／witness／CAS 的恢复行为。'
        '这些缺失不能用合成 shift、独立状态复制或只读源码访问替代。\n\n'
        '要继续实际 R5 评估，需要接入明确的目标执行环境、实际 owner 接口与身份、冻结的未来窗口数据及评价目标，以及 Cell 的真实工作负载和成本口径。'
        '研究包已经提供可执行离线入口与审阅 proposal；尚未获得的回执字段明确保持为空。'
        '完整逐项状态见总 `closure_ledger.json`、原 `hepta/closure_ledger.json` 及 `audit/coupled_checkpoint/closure_addendum.json`；'
        '主任务统计结论与外部集成证据分别记录。'))
    c.append(md('## 9. 新颖性与结论的边界\n\n'
        '原论文的可迁移内容是内生边界、继续价值与续约损失相互作用的建模方法。论文采用平稳、均匀错开的债务期限结构；'
        '本任务的有限非平稳期限队列需要另外定义状态和控制问题。首达神经元、精确事件模拟、自适应阈值、连续时间解析网络与多时间尺度记忆已有公开研究。'
        '因此不能把任意一种已有算子加上金融名称就宣称原创。可检验的贡献应是具体的期限／资源耦合机制、正确的事件与梯度实现、可证明的信息必要性，以及公平任务中的实际收益。\n\n'
        '本轮的主要新实证是：旧闭合问题得到有限模型内的修复；真实脉冲反馈与完整路径梯度可执行；期限汇总存在严格反例；'
        '候选优劣由已冻结实验决定。没有生物神经数据拟合、没有证明新的生物机制，也没有建立文献优先权或生产收益。\n\n'
        '机制消融只改专用分支，原始 22 维观察仍相同。固定重排不是删除期限信息，均值分支也不使公共输入完全看不到逐项期限。'
        '均值闭合消融只能与分布期望版比较，不能为它强行构造同律单路径。主 v2 数据与架构均变更，不能把 v0/v2 的分数差单独归因为一个修复。'))
    refs=read('references.json')
    c.append(md('## 10. 原始文献与复现\n\n'+'\n'.join(f"- [{r['title']}]({r['url']}) ({r['year']})：{r['relevance']}" for r in refs)+
        '\n\n```bash\npython -m rrsnn_v2.density_validation\npython -m rrsnn_v2.validate_spiking_baselines\npython -m rrsnn_v2.run_matrix --workers 6\npython -m rrsnn_v2.run_evaluations --workers 6\npython -m rrsnn_v2.anticipation_probe\npython -m rrsnn_v2.aggregate_results\npython rrsnn_v2/hepta/run_offline_replay.py --checkpoint rrsnn_v2/results/rr_density_sampled/seed_101/model.pt --joint-output-name rr_density_sampled_seed101\n```\n\n'
        '训练与全部评估结束后，资源表使用 `python rrsnn_v2/benchmark_resource_observer.py run`。补充循环 SNN 的命令与冻结计划在 `coupled/`。'
        '训练、参数、数据和评估源码的 SHA 均写入 receipt；聚合在文件不齐或哈希漂移时拒绝输出部分主表。'
        '原始 logits／动作与逐次脉冲记录、全部模型检查点、独立审计和 vendored Rust 依赖保存在研究包中。'))
    notebook={'cells':c,'metadata':{'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},
             'language_info':{'name':'python','version':'3.12'},'generated_at_host_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
             'evidence_aggregate_sha256':hashlib.sha256((ROOT/'results/aggregate.json').read_bytes()).hexdigest()},
             'nbformat':4,'nbformat_minor':5}
    for index,cell in enumerate(c): cell['id']=f'rrsnn-v2-{index:03d}'
    output=ROOT/'RR_SNN_V2_Report.ipynb';output.write_text(json.dumps(notebook,ensure_ascii=False,indent=1)+'\n')
    try:
        import nbformat
        nbformat.validate(nbformat.read(output,as_version=4))
    except ImportError: pass
    shutil.copy2(ROOT/'results/aggregate.json',ROOT.parent/'RR_SNN_V2_Main_Results.json')
    print(json.dumps({'report':str(output),'cells':len(c),'bytes':output.stat().st_size,'verdict':verdict},ensure_ascii=False))

if __name__=='__main__': build()
