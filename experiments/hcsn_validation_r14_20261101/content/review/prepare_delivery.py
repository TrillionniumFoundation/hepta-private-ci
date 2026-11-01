"""Prepare compact, fully sourced content results and a static scientific plot."""

import hashlib
import json
from collections import defaultdict
from pathlib import Path


CONTENT=Path(__file__).resolve().parent.parent
FORMAL=CONTENT/'results/formal_01'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path,value):
    with path.open('x') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,sort_keys=True,allow_nan=False)
        stream.write('\n')


def mean(values):
    values=list(values)
    return sum(values)/len(values)


def signed(value):
    return f'{value:+.6f}'


def main():
    raw=read(FORMAL/'RESULTS.json')
    protocol=read(FORMAL/'PROTOCOL.json')
    audit_path=FORMAL/'review/INDEPENDENT_RESULTS_AUDIT_01.json'
    audit=read(audit_path)
    follow_path=FORMAL/'review/DEVELOPMENT_AND_WEIGHT_AUDIT.json'
    follow=read(follow_path)
    if audit['status']!='pass' or follow['status']!='pass':
        raise ValueError('Do not publish a failed audit as accepted results')
    groups=defaultdict(list)
    for row in raw['rows']:
        groups[row['task'],row['mode'],row['domain'],row['family']].append(row)
    metrics=('value_utility','light_utility','value_accuracy','light_accuracy','read_count','actual_fee',
             'initial_selected','initial_stop','value_cpu_seconds','value_wall_seconds','light_cpu_seconds',
             'actor_model_calls','processed_prefix_tokens')
    aggregated=[]
    for key,rows in sorted(groups.items()):
        rows=sorted(rows,key=lambda r:r['seed'])
        if [r['seed'] for r in rows]!=protocol['seeds']:
            raise ValueError('Family aggregate does not contain exactly the three registered fits')
        aggregated.append(dict(zip(('task','mode','domain','family'),key),n_fit_seeds=3,
            **{k:mean(r[k] for r in rows) for k in metrics},
            paired_seed_value_utility=[r['value_utility'] for r in rows],paired_seed_light_utility=[r['light_utility'] for r in rows]))
    compact=dict(schema='hcsn.r14.content.compact.v1',
        sources={str(p.relative_to(CONTENT)):sha(p) for p in (FORMAL/'PROTOCOL.json',FORMAL/'SOURCE_FREEZE.json',FORMAL/'CANDIDATE_FREEZE.json',FORMAL/'RESULTS.json',audit_path,follow_path)},
        counts=dict(raw_rows=len(raw['rows']),contrasts=len(raw['contrasts']),means=len(raw['means']),family_domain_aggregates=len(aggregated)),
        fit_seeds=protocol['seeds'],estimand=protocol['estimand'],means=raw['means'],contrasts=raw['contrasts'],family_domain_aggregates=aggregated,
        interpretation='Three inherited fitting seeds. All effects descriptive; seed ranges are not confidence intervals. Initial-stop accuracy is distinct from initial_selected stop frequency. Joint read-all cells use the same value-trained weights.',
        integrated_full_distribution=False,physical_energy_measured=False)
    write(FORMAL/'RESULTS_COMPACT.json',compact)
    if (FORMAL/'RESULTS_COMPACT.json').stat().st_size>512000:raise ValueError('Compact results exceed publication bound')
    keyed={(r['task'],r['mode'],r['domain'],r['comparison']):r for r in raw['means']}
    task_names={'recall':'延迟关联检索','binding':'跨模态绑定'}
    mode_names={'frozen_backend':'全后端冻结','joint_backend':'联合价值训练'}
    domain_names={'iid':'IID','long_distractors':'长度／干扰外推','blank_retention':'查询后空白保持','irregular_dt':'交替不规则间隔',
                  'clock4x':'整体时钟 ×4','query_swap':'更换查询','missing_payload':'缺失数值载荷','missing_a':'缺失模态 A','missing_b':'缺失模态 B'}
    audit_cpu=read(FORMAL/'review/AUDIT_01_PROCESS.json')['child_cpu_seconds']
    follow_cpu=read(FORMAL/'review/DEVELOPMENT_AUDIT_PROCESS.json')['child_cpu_seconds']
    train_cpu=audit['result']['full_process_cost']['train']['full_child_cpu_seconds']
    eval_cpu=audit['result']['full_process_cost']['evaluate']['full_child_cpu_seconds']
    admin={p.stem:read(p)['cpu_seconds'] for p in (CONTENT/'results/formal_01_admin').glob('*.json') if 'cpu_seconds' in read(p)}
    summary=dict(schema='hcsn.r14.content.review-summary.v1',status='pass',
        full_results_audit=dict(path=str(audit_path.relative_to(CONTENT)),sha256=sha(audit_path),checks=len(audit['checks']),failed_checks=len(audit['failed_checks']),full_child_cpu_seconds=audit_cpu),
        development_and_weights_audit=dict(path=str(follow_path.relative_to(CONTENT)),sha256=sha(follow_path),checks=len(follow['checks']),full_child_cpu_seconds=follow_cpu),
        source_freeze_sha256=sha(FORMAL/'SOURCE_FREEZE.json'),candidate_freeze_sha256=sha(FORMAL/'CANDIDATE_FREEZE.json'),
        complete_frozen_backends=48,joint_backends_changed_at_selected_and_final=48,joint_components_changed=144,
        every_joint_component_nonzero_gradient_steps=256,
        joint_selected_steps=follow['formal_joint_selected_steps'],
        development=dict(first_attempt='Validation Long/Bool means failed before first update; source snapshot, stderr and nonzero receipt retained.',
                         first_attempt_child_cpu_seconds=follow['development01_child_cpu_seconds'],
                         fix='A single stats[k].float().mean() cast; targets/data/selection unchanged.',
                         second_attempt='Two updates, recall seed12031, both frozen/joint; freeze and both training children exit zero; no heldout.',
                         second_attempt_child_cpu_seconds=follow['development02_child_cpu_seconds'],
                         second_attempt_selected_steps=follow['development02_selected_steps']),
        scientific_cost=dict(formal_training_child_cpu_seconds=train_cpu,formal_evaluation_child_cpu_seconds=eval_cpu,
                             formal_admin_child_cpu_seconds=admin,development_child_cpu_seconds=follow['total_development_child_cpu_seconds'],
                             independent_audits_child_cpu_seconds=audit_cpu+follow_cpu,energy_joules=None),
        estimand=protocol['estimand'],
        binding_frozen_iid='Both matched ordinary_dual and analytic choose initial STOP for every row in all three fits: zero READs and zero backend forward calls. Their actor-time ratio is not a core-computation speed comparison.',
        scope='Audit verifies saved outcomes, checkpoints, identities and logs. Three inherited fits, fixed renewal gate, synthetic read tariffs, unoptimized online prefix recomputation, no conditional expected regret or foundation-core acceptance.')
    write(CONTENT/'review/REVIEW_SUMMARY.json',summary)
    lines=['# R14 内容验证：完整后端冻结、联合价值训练与实际控制','',
        '## 结论与证据范围','',
        '本轮完成了实际 READ/STOP 执行下的同信息、同权重控制消融，并以三个继承拟合种子比较解析门与普通核心。结果同时包含正、负和零差值；没有形成跨任务、跨压力域的一致解析核心优势。最关键的 D−B 必须与具体对照和域一起报告。',
        '',
        f'正式结果含 {len(raw["rows"])} 条逐模型／域结果、{len(raw["contrasts"])} 个逐种子四格对比、{len(raw["means"])} 个三种子均值，全部逐样本 NPZ 保留。独立审计从 NPZ 重算效应并核对权重和数据，{len(audit["checks"]):,} 项检查通过，0 失败。',
        '',
        '[完整结果](results/formal_01/RESULTS.json) · [紧凑结果与八族全域聚合](results/formal_01/RESULTS_COMPACT.json) · [独立审计](results/formal_01/review/INDEPENDENT_RESULTS_AUDIT_01.json) · [开发与权重补核](results/formal_01/review/DEVELOPMENT_AND_WEIGHT_AUDIT.json)',
        '',
        '## 四格与估计量','',
        '|核心|读取全部后提交|共同价值控制器实际 READ/STOP|','|---|---|---|',
        '|普通对照|A|B|','|解析活动门|C|D|','',
        'A/B 使用同一份普通内容权重，C/D 使用同一份解析内容权重。每个 task/seed/mode 的八家使用完全相同的 critic 权重；matched 对照固定为 ordinary_dual，validation-selected 对照在七个普通家族中按验证效用选择，并固定用于该种子的全部测试域。',
        '',
        '全后端冻结包括 encoder、core 和 readout。联合层中，A/C 是价值联合训练后相同权重的 read-all 执行消融，因此 B−A、D−C 与交互项是该训练制度下的执行控制效应，不是分别训练 light/value 网络的端到端总效应。D−B 比较相同价值训练目标、共同 critic 和控制规则下的核心。独立 light-policy 训练没有执行，也不计作已闭合验证。',
        '',
        '完整时间表与观察预算在初始 STOP 前公开，实际载荷须先选择 READ 才传入后端；本实验不覆盖未来到达时刻未知的情形。',
        '',
        '## IID 四格结果','',
        '数值为任务效用，三个拟合种子等权平均。差值保留方向；不据这三个继承种子作显著性或通用准入声明。','',
        '|任务|模式|普通对照|A|B|C|D|D−B|','|---|---|---|---:|---:|---:|---:|---:|']
    for task in ('recall','binding'):
        for mode in protocol['modes']:
            for comparison in ('matched','strong_selected'):
                r=keyed[task,mode,'iid',comparison]
                lines.append('|'+ '|'.join([task_names[task],mode_names[mode],comparison]+[f'{r[k]:.6f}' for k in ('A','B','C','D')]+[signed(r['D_B'])])+'|')
    lines += ['',
        '绑定任务的冻结层中，analytic 与 matched ordinary_dual 在三个种子上全部立即 STOP：每行 READ 数为 0、后端 forward 调用为 0，B=D=0.5。这里的 D−B=0 表示这一停止策略的相同结果；在线 actor 计时的差别不代表内容核心运算速度。',
        '',
        '## 全部域的 D−B','',
        '下面每格为“均值 [三种子最小值, 最大值]”。范围与散点是三个实际拟合种子的描述，**不是置信区间**。所有域、两种对照均列出，没有按正负筛选。',
        '',
        '![D−B 的全域核心效应](results/formal_01/core_effects.png)','',
        '[PNG](results/formal_01/core_effects.png) · [SVG](results/formal_01/core_effects.svg)','']
    for task in ('recall','binding'):
        for mode in protocol['modes']:
            lines += [f'### {task_names[task]} · {mode_names[mode]}','',
                      '|域|matched ordinary_dual|validation-selected ordinary|','|---|---:|---:|']
            for domain in protocol['domains'][task]:
                cells=[]
                for comparison in ('matched','strong_selected'):
                    r=keyed[task,mode,domain,comparison];v=r['paired_seed_D_B']
                    cells.append(f'{signed(r["D_B"])} [{signed(min(v))}, {signed(max(v))}]')
                lines.append('|'+ '|'.join([domain_names[domain]]+cells)+'|')
            lines.append('')
    lines += ['### 如何读这些压力结果','',
        '联合训练的检索任务中，空白保持和长度／干扰外推对两种普通对照均为正；IID、不规则间隔和更换查询对两种对照均为负。整体时钟 ×4 的结论依赖对照：相对 validation-selected 为 +0.064142，相对 matched 为 −0.006670。缺失载荷均值对两种对照为正，但相对 validation-selected 的三个种子并非同号。各正差值是对应任务／域的观察结果，不能扩展成全面核心优势；负差值也不能抹掉已保留的正压力结果。',
        '',
        '绑定的缺失模态数据经过独立核对：当整段可见观察完全相同时，两标签计数严格平衡。这里用于检验缺失信息的行为边界，不能将不可恢复的标签信息作为本可获得的内容收益。',
        '',
        '## 冻结、共同训练与选中步','',
        '48/48 个冻结后端的 selected 和 final 完整张量哈希均与继承初始权重完全相同。48/48 个联合后端在 selected 和 final 均改变；其 144/144 个 encoder/core/readout 组件均改变，每个组件记录的非零梯度步数为 256。审计核对梯度日志与实际张量变化，没有冒称重新执行了每一步反传。',
        '',
        '|联合任务|seed 12031|seed 12032|seed 12033|','|---|---:|---:|---:|',
        '|检索|256|192|256|','|绑定|256|256|192|','',
        '选中的是八家后端加共同 critic 的整组权重，按验证均值选择，step 0 允许入选，最早并列优先。冻结层有三组选中 step 0，因此并非每组所用 critic 都来自训练后的选中权重。全部选中验证路径及 heldout 路径通过在线／离线动作和预测一致性门限。',
        '',
        '## 实际成本与失败保留','',
        '|工作|完整子进程 CPU 秒|','|---|---:|',
        f'|正式训练：12 个共享八后端组|{train_cpu:.6f}|',
        f'|正式 heldout 科学评估：12 个组|{eval_cpu:.6f}|',
        f'|正式 freeze / candidates / summarize|{sum(admin.values()):.6f}|',
        f'|开发第一次：freeze 与失败 fit|{follow["development01_child_cpu_seconds"]:.6f}|',
        f'|开发第二次：freeze、两种模式各 2 updates|{follow["development02_child_cpu_seconds"]:.6f}|',
        f'|独立逐样本结果审计|{audit_cpu:.6f}|',
        f'|开发与权重补核|{follow_cpu:.6f}|','',
        '第一次开发在首次更新前因 Long/Bool 指标直接求 mean 失败。只把 validation 聚合改成 float 后求均值；目标、数据、选择规则不变。原始冻结、stderr、失败回执和全部成本保留。第二次开发的 freeze、frozen、joint 三个子进程均正常退出，未访问 heldout。',
        '',
        '正式训练成本是八后端加共享 critic 的整组优化成本，不能除以八宣称单候选独立训练成本。评估的完整 CPU 已含在线阶段计时和离线诊断，不能再次相加。实际价值 actor 每次重算已付费前缀；read-all 轻量臂一次完整 forward，当前比较不是最优增量部署实现。主机共享，单次计时不是严格隔离微基准。历史 donor／初始拟合为既有共享成本，另列于总成本账；本轮不重复冒算为新训练。图表生成、打包及恢复有独立 publication 回执。物理能耗未测，值为 null。',
        '',
        '## 仍未覆盖的科学问题','',
        '解析家族仍是继承的固定 renewal 活动门，独立数值线的完整条件分布求解器没有整合进内容网络；任意移动边界、正延迟恢复与全分布内容学习不由本实验验证。任务为合成检索／绑定，费用为声明的 READ／时间价格。只有一条实现未来的 Q 目标和 hindsight gap，不能称条件期望 regret。三个继承拟合种子、新数据域、八个家族和逐样本数均不构成八次全新拟合。',
        '',
        '本次为明确限定范围的实验与审计完成；不据此宣布解析动力学已达到新基础网络核心的质量／成本准入。','']
    with (CONTENT/'RESULTS_ZH.md').open('x') as stream:stream.write('\n'.join(lines))
    make_figure(protocol,keyed)
    print(json.dumps(dict(compact_bytes=(FORMAL/'RESULTS_COMPACT.json').stat().st_size,
        family_aggregates=len(aggregated),figures={name:dict(bytes=(FORMAL/name).stat().st_size,sha256=sha(FORMAL/name)) for name in ('core_effects.png','core_effects.svg')},
        report_sha256=sha(CONTENT/'RESULTS_ZH.md'),review_summary_sha256=sha(CONTENT/'review/REVIEW_SUMMARY.json')),sort_keys=True))


def make_figure(protocol,keyed):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    names={'iid':'IID','long_distractors':'Long distractors','blank_retention':'Blank retention','irregular_dt':'Irregular intervals',
           'clock4x':'Clock x4','query_swap':'Query swap','missing_payload':'Missing payload','missing_a':'Missing modality A','missing_b':'Missing modality B'}
    colors={'matched':'#2266AA','strong_selected':'#C56518'}
    fig,axes=plt.subplots(2,2,figsize=(13.5,9.2),sharex=True)
    all_values=[]
    for i,task in enumerate(('recall','binding')):
        for j,mode in enumerate(protocol['modes']):
            ax=axes[i,j]
            domains=protocol['domains'][task]
            for y,domain in enumerate(domains):
                for comparison,offset in (('matched',-.14),('strong_selected',.14)):
                    row=keyed[task,mode,domain,comparison];values=row['paired_seed_D_B'];all_values.extend(values)
                    yy=y+offset;color=colors[comparison]
                    ax.plot([min(values),max(values)],[yy,yy],color=color,lw=1.5,alpha=.8,zorder=2)
                    ax.vlines([min(values),max(values)],yy-.035,yy+.035,color=color,lw=1)
                    ax.scatter(values,[yy-.035,yy,yy+.035],s=21,color=color,alpha=.65,zorder=3)
                    ax.scatter([row['D_B']],[yy],marker='D',s=35,color=color,edgecolors='white',linewidths=.6,zorder=4)
            ax.axvline(0,color='#333333',ls='--',lw=.9,zorder=1)
            ax.set_yticks(range(len(domains)),[names[d] for d in domains],fontsize=9)
            ax.invert_yaxis();ax.grid(axis='x',color='#DADDE2',lw=.6,alpha=.8)
            ax.set_title(('Recall' if task=='recall' else 'Binding')+' | '+('Frozen backend' if mode=='frozen_backend' else 'Joint value training'),fontsize=12,loc='left',pad=10)
            ax.spines[['top','right']].set_visible(False)
            ax.spines[['left','bottom']].set_color('#BBBBBB')
            ax.tick_params(axis='x',labelsize=9)
            if i==1:ax.set_xlabel('Analytic minus ordinary utility (D - B)',fontsize=10)
    low,high=min(all_values),max(all_values);padding=.07*(high-low)
    for ax in axes.flat:ax.set_xlim(low-padding,high+padding)
    legend=[Line2D([0],[0],color=colors[k],marker='D',lw=1.5,markersize=5,label=label) for k,label in
            (('matched','Matched ordinary_dual'),('strong_selected','Validation-selected ordinary'))]
    fig.suptitle('Core effects under the same value controller',fontsize=17,x=.5,y=.985)
    fig.text(.5,.949,'Dots: 3 inherited fit seeds   |   Diamonds: mean   |   Bars: min-max seed range, NOT confidence intervals',ha='center',fontsize=10,color='#42464C')
    fig.legend(handles=legend,loc='upper center',bbox_to_anchor=(.5,.93),ncol=2,frameon=False,fontsize=10)
    fig.text(.5,.012,'Joint A/C are read-all execution ablations of value-trained weights. Synthetic tasks; inherited fixed renewal gate.',ha='center',fontsize=8.7,color='#42464C')
    fig.tight_layout(rect=(.02,.04,.995,.90),h_pad=2.1,w_pad=2.5)
    for extension in ('png','svg'):
        path=FORMAL/('core_effects.'+extension)
        if path.exists():raise FileExistsError(path)
        fig.savefig(path,dpi=150,facecolor='white')
        if path.stat().st_size>512000:raise ValueError('Figure exceeds publication bound: '+str(path))
    plt.close(fig)


if __name__=='__main__':main()
