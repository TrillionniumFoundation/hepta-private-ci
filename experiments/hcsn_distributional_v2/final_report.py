"""Render a Chinese synthesis only from complete, audited study outputs.

This is a reporting layer. It imports no training, model or solver code, creates
no new statistical gates, and never changes a registered analysis.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import time


PACKAGE = Path(__file__).resolve().parent
TASKS = ('selective_copy', 'mqar', 'irregular', 'mnist', 'fsdd', 'multimodal_select')
TASK_LABELS = ('选择性复制', 'MQAR', '不规则时间', 'MNIST', 'FSDD', '真实模态选择')
MODEL_LABELS = {
    'distribution_free_dual': '分布＋自由边界＋双值',
    'distribution_conditional_dual': '分布＋学习条件边界＋双值',
    'distribution_free_ordinary': '分布＋自由边界＋普通特征',
    'active_mean_collapse_free_dual': '活动均值闭合＋自由边界＋双值',
    'legacy_free': 'v1 均值模型',
    'two_gates': '普通双门控',
    'transformer': '小型 Transformer',
    'lif_snn': '传统 LIF SNN（补充）',
}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, record):
    with Path(path).open('x') as handle:
        json.dump(record, handle, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        handle.write('\n')


def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |',
                      '| ' + ' | '.join('---' for _ in headers) + ' |'] +
                     ['| ' + ' | '.join(map(str, row)) + ' |' for row in rows])


def run(output, costs_path):
    paths = {
        'content': PACKAGE/'results/content_analysis002/ANALYSIS.json',
        'lif': PACKAGE/'results/lif_analysis001/ANALYSIS.json',
        'content_protocol': PACKAGE/'CONTENT002_PROTOCOL.json',
        'lif_protocol': PACKAGE/'LIF_SUPPLEMENT001_PROTOCOL.json',
        'content_scheduler': PACKAGE/'results/content002/SCHEDULER_EXECUTION.json',
        'lif_scheduler': PACKAGE/'results/lif_supplement001/SCHEDULER_EXECUTION.json',
        'kernel': PACKAGE/'results/kernel_validation003/RESULTS.json',
        'control': PACKAGE/'results/grid_control_validation001/RESULTS.json',
        'runtime': PACKAGE/'results/runtime_review001/SUMMARY.json',
        'task': PACKAGE/'results/task_value002/EVALUATION_SUMMARY.json',
        'task_review': PACKAGE/'results/independent_execution_review001/SUMMARY.json',
        'native_v2': PACKAGE/'results/distributional_native001/COMPLETE.json',
        'native_v2_rows': PACKAGE/'results/distributional_native001/EVALUATION_SUMMARY.json',
        'calibration': PACKAGE/'results/task_future_calibration001/SUMMARY.json',
        'costs': Path(costs_path).resolve(),
    }
    identities = {name: {'path': str(path.relative_to(PACKAGE))
                         if path.is_relative_to(PACKAGE) else str(path), 'sha256': sha(path)}
                  for name, path in paths.items()}
    d = {name: read(path) for name, path in paths.items()}
    c, lif, proto = d['content'], d['lif'], d['content_protocol']
    assert c['expected'] == c['valid'] == 176 and c['invalid'] == 0
    assert not c['common_initialization_mismatches']
    assert c['protocol_sha256'] == sha(paths['content_protocol'])
    assert c['analyzer_sha256'] == proto['source_files_sha256']['experiments/hcsn_distributional_v2/content_analysis.py']
    assert lif['status'] == 'passed' and lif['expected_pairs'] == lif['valid_pairs'] == 18
    assert lif['protocol_sha256'] == sha(paths['lif_protocol'])
    assert lif['parent_protocol_sha256'] == c['protocol_sha256']
    assert lif['analysis_source_sha256'] == d['lif_protocol']['source_files_sha256']['experiments/hcsn_distributional_v2/lif_supplement_analysis.py']
    for name in ('content_scheduler', 'lif_scheduler'):
        assert d[name].get('returncode', d[name].get('exit_code')) == 0
        protocol_name = name.replace('_scheduler', '_protocol')
        assert d[name]['protocol_sha256'] == sha(paths[protocol_name])
    assert d['kernel']['passed'] and d['control']['passed']
    assert d['runtime']['status'] == 'passed' and d['task_review']['status'] == 'passed'
    assert d['native_v2']['status'] == 'completed'
    assert d['costs']['status'] == 'complete' and not d['costs']['missing_required_inputs']
    assert all(row['complete'] for row in c['mechanism'])
    assert all(row['complete'] for row in c['content_screens'])
    assert all(row['complete'] for row in lif['table'] if row['available'])
    output = Path(output).resolve()
    if not output.is_relative_to(PACKAGE):
        raise ValueError('Report destination must be a new v2 package directory')
    output.mkdir(parents=True, exist_ok=False)

    core = {(r['task'], r['model'], r['split']): r for r in c['core']}
    lt = {(r['task'], r['split']): r for r in lif['table']}
    models = tuple(proto['core']['models'])
    assert set(models) == set(MODEL_LABELS)-{'lif_snn'}
    id_rows, ood_rows = [], []
    for model in models + ('lif_snn',):
        cells = []
        for task in TASKS:
            if model == 'lif_snn':
                values = lt[(task, 'test')]['lif_accuracies']
                mean, sd = statistics.mean(values), statistics.stdev(values)
            else:
                row = core[(task, model, 'test')]
                assert row['complete']
                mean, sd = row['mean'], row['sd']
            cells.append(f'{100*mean:.2f} ± {100*sd:.2f}')
        id_rows.append([MODEL_LABELS[model]]+cells)
        cells = []
        for task in TASKS[:3]:
            if model == 'lif_snn':
                row = lt[(task, 'ood')]
                mean, sd = statistics.mean(row['lif_accuracies']), statistics.stdev(row['lif_accuracies'])
            else:
                row = core[(task, model, 'ood')]
                assert row['complete']
                mean, sd = row['mean'], row['sd']
            cells.append(f'{100*mean:.2f} ± {100*sd:.2f}')
        ood_rows.append([MODEL_LABELS[model]]+cells)
    mechanism_rows = [[MODEL_LABELS[r['comparison']], f"{100*r['mean']:+.3f}",
        f"[{100*r['interval'][0]:+.3f}, {100*r['interval'][1]:+.3f}]",
        f"{r['holm_p']:.6f}", '达到' if r['positive_gate'] else '未达到'] for r in c['mechanism']]
    screen_rows = [[TASK_LABELS[TASKS.index(r['task'])], MODEL_LABELS[r['best_external']],
                    f"{100*r['gap']:+.3f}", '达到' if r['screen'] else '未达到']
                   for r in c['content_screens']]
    lif_rows = [[TASK_LABELS[TASKS.index(r['task'])], f"{100*r['difference_mean']:+.3f}",
                f"{100*r['difference_sd']:.3f}"] for r in lif['table'] if r['split']=='test']

    kr = d['kernel']['records']; qr = d['control']['records']
    dense = kr['independent_chunks_dense']['records']
    fd = kr['independent_chunks_gradients']['records']
    enum = qr['exhaustive_policy_reference']
    max_qvi = max(max(row['residuals'][key] for key in ('active_qvi_absolute_residual',
        'continuation_positive_violation', 'forced_phase_absolute_residual', 'obstacle_positive_violation'))
        for row in enum)
    largest_gain = max((row for row in enum if row['cells']==8), key=lambda row: row['initial_relative_improvement'])
    numerical_rows = [
        ['最终内核', f"{d['kernel']['tests_run']} 项测试通过"],
        ['独立稠密传播：最大状态 L1 误差', f"{max(r['state_l1_error'] for r in dense):.3e}"],
        ['独立稠密传播：最大发放次数误差', f"{max(r['event_error'] for r in dense):.3e}"],
        ['8 个参数局部梯度：最大缩放误差', f"{max(r['scaled_error'] for r in fd):.3e}"],
        ['64 步混合长间隔 float32：最大质量误差', f"{kr['independent_chunks_float32_long_sequence']['maximum_mass_error']:.3e}"],
        ['有限控制：全部枚举策略数', str(sum(r['policy_count'] for r in enum))],
        ['Howard 值与独立枚举最大误差', f"{max(r['maximum_exhaustive_error'] for r in enum):.3e}"],
        ['有限 QVI 最大违反 / 残差', f'{max_qvi:.3e}'],
        ['受控流：贴现奖励＋末端值闭合误差', f"{max(r['discounted_reward_plus_terminal_error'] for r in qr['controlled_process']):.3e}"],
        ['有限控制 7 参数固定策略梯度最大误差', f"{max(r['scaled_error'] for r in qr['fixed_active_set_gradients']['records']):.3e}"],
    ]
    throughput_rows, learning = [], {}
    for model in models:
        rows = [a for a in c['audits'] if a['job']['model']==model and a['job']['seed'] in proto['core']['seeds']]
        assert len(rows)==18
        candidates = [r for a in rows for r in a['candidates']]
        throughput_rows.append([MODEL_LABELS[model], rows[0]['counts']['backbone'],
            f"{statistics.median(r['updates'] for r in candidates):.1f}",
            f"{sum(r['training_cpu_seconds'] for r in candidates):.2f}",
            f"{sum(r['complete_child_cpu_seconds'] for r in rows):.2f}"])
    lif_audits = [pair['lif'] for pair in lif['pair_audits']]
    assert len(lif_audits)==18
    lif_candidates = [candidate for audit in lif_audits for candidate in audit['candidates']]
    throughput_rows.append([MODEL_LABELS['lif_snn'], lif_audits[0]['counts']['backbone'],
        f"{statistics.median(r['updates'] for r in lif_candidates):.1f}",
        f"{sum(r['training_cpu_seconds'] for r in lif_candidates):.2f}",
        f"{sum(r['complete_child_cpu_seconds'] for r in lif_audits):.2f}"])
    for group in ('content', 'dynamics', 'boundary', 'reset', 'refractory'):
        candidates = [r for a in c['audits'] if a['job']['model']=='distribution_free_dual' for r in a['candidates']]
        learning[group] = {'candidates': len(candidates),
            'minimum_observed_max_gradient': min(r['observed_group_gradient_max'][group] for r in candidates),
            'minimum_selected_change_l2': min(r['selected_group_change_l2'][group] for r in candidates)}
        assert all(learning[group][key] > 0 for key in ('minimum_observed_max_gradient', 'minimum_selected_change_l2'))

    runtime = d['runtime']; recover = runtime['recovery']
    runtime_rows = [[MODEL_LABELS[r['model']], f"{1000*r['forward_cpu_median']:.3f}",
                    f"{1000*r['optimizer_cpu_median']:.3f}"] for r in runtime['cases'] if r['length']==128]
    ratios = {r['comparison']: r['free_dual_optimizer_ratio'] for r in runtime['runtime_ratios'] if r['length']==128}
    task, review = d['task'], d['task_review']; prices = tuple(task['actual_native'])
    task_rows = []
    for name in ('bellman_value_head', 'ordinary_action_head', 'tabular_bellman', 'validation_schedule', 'validation_risk'):
        task_rows.append([name,
            f"{statistics.mean(task['counterfactual'][p][name]['mean_utility'] for p in prices):.6f}",
            f"{statistics.mean(task['actual_native'][p][name]['mean_utility'] for p in prices):.6f}",
            f"{statistics.mean(task['actual_native'][p][name]['complete_execution_cpu_per_stream'] for p in prices):.6f}"])
    comparisons = review['paired_comparisons']; planner = comparisons['tabular_bellman']
    head = comparisons['bellman_value_head']; expense = review['costs']
    native_rows = d['native_v2_rows']['rows']
    # The stored field names are inspected, rather than guessing other policies.
    v2_means = {name: statistics.mean(row['utility'] for row in native_rows if row['family']==name)
                for name in ('tabular_bellman', 'tabular_myopic')}
    calibration_rows = []
    for name, label in [('v1_cached128', 'v1 缓存 128 流'), ('v1_native16', 'v1 native 16 流'), ('v2_engineering2', 'v2 工程 2 流')]:
        row = d['calibration']['panels'][name]
        interval = row['bootstrap']['intervals']['bias'] if row['bootstrap'] else None
        calibration_rows.append([label, f"{row['mean_predicted_future']:.6f}",
            f"{row['mean_actual_later_net_reward']:.6f}", f"{row['bias_prediction_minus_actual']:+.6f}",
            f'[{interval[0]:+.6f}, {interval[1]:+.6f}]' if interval else '样本仅用于工程描述'])

    gates, screens = c['positive_mechanism_gates'], c['passed_content_screens']
    verdicts = [
        ['1', '合同明确', '已完成', '金融价值、内部策略值、有限控制最优值、任务值分别定义；FIRE 含后续再生收益'],
        ['2', '低维 oracle', '在已声明问题内通过', '解析参考与有限模型独立核对；有限网格最优性单独评估'],
        ['3', '联合训练', '实现与更新审计通过', '176 个搜索完整审计；五类参数有有效梯度和实际更新'],
        ['4', '隔离贡献并取得优势', f'{gates}/4 项登记优势门', '只能按具体对照和固定两任务范围解释'],
        ['5', '内容能力达到强基线', f'{screens}/6 项 ID 描述性筛查', '完整 ID/OOD 与 LIF 数据如下；不等同基础模型验收'],
        ['6', '实际执行与规模化净收益', '执行与恢复已验证；整体优势未确立', '当前 CPU 明显较慢；旧表格规划器的局部收益不能归给新架构'],
    ]
    summary = {
        'schema': 'hcsn-complete-evidence-synthesis.v1', 'created_utc': datetime.now(timezone.utc).isoformat(),
        'source_sha256': sha(__file__), 'input_sha256': identities,
        'integrity': {'content_valid': c['valid'], 'content_invalid': c['invalid'], 'lif_valid_pairs': lif['valid_pairs']},
        'registered_mechanism_positive_gates': gates, 'descriptive_content_screens': screens,
        'acceptance': verdicts, 'free_dual_joint_learning': learning,
        'observed_cpu_lower_bound_seconds': d['costs']['observed_cpu_lower_bound_seconds'],
        'research_cost_is_complete_all_work_bill': False,
        'new_training_or_inference': False, 'new_statistical_tests_or_selection': False,
        'foundation_model_or_gpu_advantage_established': False,
        'native_v2_policy_mean_utility': v2_means,
    }
    blocks = [
        '# HCSN 全量验证：完整证据与六项验收',
        f"主矩阵 **176/176** 搜索、**352** 个 LR 候选已完整审计；传统 LIF 补充 **18/18** 对、**36** 个新 LR 候选已完整审计。登记的机制优势门达到 **{gates}/4**，核心内容 ID 描述性筛查达到 **{screens}/6**。执行、恢复和低维数学可以分别成立；当前证据没有确立替代 Transformer 或训练全模态基础模型的整体优势。",
        table(['顺序', '工作', '本轮状态', '有效解释'], verdicts),
        '## 1. 实现对象与可训练性',
        '本实现是受金融内生边界思想启发的再生控制研究模型。He–Xiong 原模型联合确定债务、股权与违约边界；债务不是直接命名的 Put，金融违约也没有自动神经再生。本项目另行定义压力过程、内部发放收益、复位与不应期。正式合同见 [CONTRACT.md](../../CONTRACT.md)，标量闭式与唯一边界验证见 [v1 MATH.md](../../../hcsn_free_boundary_v1/MATH.md)。',
        r'内部合法干预为 $G(x)=x-K+D J(r)$，未来项没有删去。连续参考值在边界满足价值匹配和一阶平滑粘贴；它是分段 $C^2$，并非所有实现分支的全局光滑函数。实际模型保留每个通道八格活动概率和两个 Erlang 阶段，层间仍有 32 维内容路径。概率是各通道边际分布，并非整个网络的联合随机分布。',
        r'当前 $(\rho I-A)J^\pi=g$ 是所选有限策略的局部值；冻结当前系数，不预测未来输入。$G^\pi$ 是立即 FIRE 后继续原策略的反事实值。这些值参与任务交叉熵训练的内容门控，主模型没有把独立 QVI 最优策略装入内容递推。',
        '对每个候选，完整审计核对全部 minibatch 前缀、共同初始化、两个 LR、15/30/60 CPU 门、选择锁、所有检查点 SHA、原始预测标签/位置/交叉熵以及选中权重推理重放。四个分布 arm 的内容、动力学、边界、复位、不应期五类参数均检查非零梯度及选中权重实际变化；其他基线核对其实际前端、backbone和readout组。分布状态路径还经过切断直接参数到门控路径的独立梯度检查。传统 LIF 另外核对学习漏电与阈值的选中和末端变化。',
        '## 2. 独立数学与数值参考',
        table(['检查', '结果'], numerical_rows),
        f"有限控制在 6 组场景、4/6/8 格上独立枚举；在八格场景 `{largest_gain['case']}` 中，允许活动格点立即 FIRE，将起始价值从 {largest_gain['old_initial_value']:.9f} 提高到 {largest_gain['optimal_initial_value']:.9f}，相对提高 **{100*largest_gain['initial_relative_improvement']:.3f}%**。这说明连续理想模型的边界不自动成为有限网格最优策略，不能只检查价值方程就宣布整套最优。",
        '参考还核对受控生成器、初始即时发放、阶段强制续存、贴现奖励加末端值，以及两组各 20,000 条独立路径。梯度核对在固定插值片段、固定分段数或固定最优动作集内进行；不覆盖动作切换点的普通导数。完整结果见 [kernel_validation003](../kernel_validation003/REPORT.md) 与 [grid_control_validation001](../grid_control_validation001/REPORT.md)。',
        '## 3. 内容能力：完整主比较与 LIF 补充',
        '以下为三个训练种子的准确率均值 ± 样本标准差，单位 %。各模型相同数据、前端/readout 初始化、训练 CPU 预算和选择机会；有效 backbone 参数差不超过 3%。不同吞吐产生不同更新次数。普通物理特征 arm 看到相同完整概率与七项物理系数，省去其没有使用的 J/G 求解；它是双值特征贡献的直接对照。',
        table(['模型']+list(TASK_LABELS), id_rows),
        '### 时序与长度外推',
        '合成 OOD 将长度 32 增到 64；不规则时间任务另外将间隔分布乘三。真实图像、音频、模态选择任务没有另外的 OOD split。',
        table(['模型']+list(TASK_LABELS[:3]), ood_rows),
        '### 预先登记的机制对比',
        '差值为分布自由边界双值减对照，先在每个种子内平均两个固定任务。八种子的双侧符号翻转检验共用四项 Holm 校正；正面门同时要求均值至少 +1 pp、Holm p≤0.05、名义 95% t 区间下限大于零。符号翻转依赖相应对称/交换性假设，区间未作同时覆盖调整；固定两个任务不构成任务总体随机样本。',
        table(['对照', '差值 pp', '名义 95% 区间 pp', 'Holm p', '登记门'], mechanism_rows),
        '### 基线接近度与传统 SNN',
        '两百分点筛查只描述当前核心三个种子是否接近测试均值最高的三个外部对照；这不是正式非劣效检验，且这个“最佳”由测试结果描述性选出。',
        table(['任务', '核心外部对照最高均值', 'HCSN 减该对照 pp', '描述性筛查'], screen_rows),
        'LIF 为单独补充：硬 0/1 前向、fast-sigmoid 替代梯度、学习漏电和阈值、减法复位。替代梯度不是硬阈值的真实导数。补充沿用相同 CPU/选择协议，仅新增18次搜索，不修改原四项 Holm 家族。下表不新增 p 值或优势门。',
        table(['任务', 'HCSN 减 LIF 平均 pp', '配对差值 SD pp'], lif_rows),
        '### 达到相同训练预算实际做了多少工作',
        '以下只取每个主模型的 18 个核心搜索，以及18个补充LIF搜索，各含两个 LR；不会因机制组额外种子数不同而混淆总工作量。训练 CPU 是完整 worker CPU 的嵌套成分，二者不能相加。',
        table(['模型', '有效 backbone 参数', '每 LR 更新数中位数', '36 LR 训练 CPU 秒', '18 搜索完整 CPU 秒'], throughput_rows),
        '## 4. 实际运行与独立进程恢复',
        'CPU 微基准：B=4、T=128、width=32、depth=1，预热后三次中位数；使用随机权重计时，完整 Adam 步包含前向、交叉熵、反向、梯度裁剪和优化器。此处不代表等质量吞吐、GPU 或芯片能耗。',
        table(['模型', '前向 CPU 毫秒', '完整 Adam 步 CPU 毫秒'], runtime_rows),
        f"该配置下分布双值完整 Adam 步为普通双门控的 **{ratios['two_gates']:.2f} 倍**、小型 Transformer 的 **{ratios['transformer']:.2f} 倍**。当前实现中数值求解、分布传播和反向的整模型代价很高，不能由取消硬 step 推导效率优势。内部期望事件流仍执行稠密计算；只有真正的 owner STOP 才停止之后的模型调用。",
        f"独立恢复使用成功训练的 MNIST checkpoint：B=2、256 token，第113步保存，在另一个 Python 进程恢复后143步。每步持续状态均为 **{recover['persistent_state_bytes_min']} 字节**；恢复后的 logits 和最终状态逐位一致。整序列与逐步流式前向最大差 {recover['full_vs_stream_max_absolute_logit_error']:.3e}，argmax 分歧 {recover['full_vs_stream_argmax_disagreements']}，最大概率质量误差 {recover['max_probability_mass_error']:.3e}。快照包含非零不应期质量。",
        r'持续状态字节公式为 $4B\{1+D[W+C(S+R+1)]\}$；不包含权重、输出、BPTT 激活、准备的时变算子或对照 KV。该数值验证状态有界，不验证无限长召回，也不等于固定训练内存。详见 [runtime_review001](../runtime_review001/REPORT.md)。',
        '## 5. Hepta 任务执行：未来项、实际动作与净收益',
        '任务层价值定义 READ、FIRE、quiet、RESET 和后续任务。FIRE 对真实标签评分并停止当前 owner；两次 quiet tick 不执行模型，随后启动后续任务。旧 backbone 面板含128个三任务流的缓存反事实，以及其中前16个流的真实 native 执行。三种 READ 价格等权平均；两者分别报告，不能当作144个独立流。两个学习头同输入、同有效参数与同更新/选择机会，它们比较训练目标，不是重新比较物理双通道。',
        table(['策略', '缓存128流平均效用', 'native16流平均效用', 'native CPU 秒/流'], task_rows),
        f"独立重算中，表格 Bellman 相对验证集锁定的普通调度：缓存差 {planner['cached_counterfactual_128']['mean']:+.6f}，native差 {planner['actual_native_16']['mean']:+.6f}；native 的19,999次配对描述性 bootstrap 95%区间为 {planner['actual_native_16']['nominal_percentile_interval_95']}。学习价值头的缓存差为 {head['cached_counterfactual_128']['mean']:+.6f}，并没有复制表格规划器收益。此处的 nominal 区间不是新登记的多重比较优势门。",
        '旧面板审计核对240个真实 native 情形、594个进程、8273次实际 READ，以及每个 STOP 后拒绝。Q24 与浮点动作和缓存/native 语义均无分歧。未来任务队列变化在同观测条件下会改变真实 KEEP/STOP，说明未来项确实进入执行。',
        f"在新 v2 checkpoint 的工程面板中，12个情形产生34个 owner、397次实际模型/owner/kernel/NDU 调用；6个配对情形有4个动作不同。然而完整未来策略平均效用为 {v2_means['tabular_bellman']:.6f}，同观测短视对照为 {v2_means['tabular_myopic']:.6f}。这两条复用 VAL 流只支持执行/恢复验证，效果为负，不能当作总体质量证明。",
        '### 未来价值是否预测对了',
        '比较第一次 FIRE 记录的后续价值与同一执行策略后来实际正确性减 READ 费；排除第一次任务奖励。下面报告预测减实际的边际偏差，原始流按三种价格先平均再 bootstrap。',
        table(['面板', '预测后续收益', '实际后续收益', '偏差', '描述性 95%偏差区间'], calibration_rows),
        '四置信度状态只是从 TRAIN 拟合的粗化 Markov 模型，未证明是神经历史的充分统计量。平均误差区间包含零不证明条件校准；单次绝对误差非零也不能单独证明失准，因为实际奖励含随机性。结构上包含未来项与准确预测未来是两个验收问题。',
        '### 部署成本的具体含义',
        f"对旧表格规划器，保守地把新活动、失败尝试与相应分析成本共 {expense['conservative_extra_setup_cpu_for_candidate']:.6f} CPU秒全部分配给候选，普通对照获得免费新设置。每流运行CPU差为 {expense['candidate_minus_reference_runtime_cpu_per_stream']:+.9f} 秒。历史共享 backbone 费用在差值中抵消，但保留原始费用；这里不将整个研究账单伪装为单一部署方案。",
        r'部署期 $N$ 流、CPU 每秒效用价格 $\alpha$ 下，$\Delta U_{net}=\Delta U_{task}-\alpha[\Delta C_{runtime}+\Delta C_{setup}/N]$。这是声明的效用情景，不是实测货币或能耗。',
        f"只要求CPU抵消的寿命约为 {expense['equal_cpu_lifetime_streams']:.2f} 流；它和质量效用盈亏平衡不是同一个数。独立敏感性分析包含短寿命：N=1、α=0.01时净差为 {next(r['net_difference'] for r in review['short_lifetime_sensitivity'] if r['lifetime_streams']==1 and r['utility_per_cpu_second']==.01):+.6f}，说明收益并非对所有部署条件都成立。完整原始收据见 [independent_execution_review001](../independent_execution_review001/REPORT.md)。",
        '## 6. 成本、失败记录和证据完整性',
        f"统一成本账本在其明确截止点记录互不重叠的 CPU 下界 **{d['costs']['observed_cpu_lower_bound_seconds']:,.6f} 秒**（**{d['costs']['observed_cpu_lower_bound_seconds']/3600:.3f} CPU小时**）。输入门为 complete，意味着要求的活动/分析/封存收据齐全；不意味着未计量研发、下载、编辑和网络服务的费用为零。逐收据SHA、字段、嵌套排除与未知范围见 `{identities['costs']['path']}`。本报告自身生成费另留 EXECUTION.json，避免递归计费。",
        f"主内容完整 worker 为 {c['complete_child_cpu_seconds']:.6f} CPU秒，训练部分为 {c['training_cpu_seconds']:.6f}；两者嵌套。LIF新增 worker 为 {lif['extra_lif_search_worker_cpu_seconds']:.6f}，复用的18个分布搜索不再计费。旧content001完整调度树2227.408732秒及其16完成/4失败结果均保留，未复用到主比较。",
        '原始数据、每个候选、所有检查点、全更新日志、预测、native journal、恢复状态和源码身份均封存。完整成功run按完成记录分批保存，选择规则不看分数；主结论只读取完整冻结分析。恢复器拒绝不同内容覆盖。复现入口为 [REPRODUCE.md](../../REPRODUCE.md)。',
        '## 7. 对 encoder、传统 SNN 和 Transformer 的判断',
        '本轮建立了一个可学习、可解释并可核对的再生状态单元。其可检验长处是持续状态有界、可处理不规则间隔、内部未来发放收益明确，并能为任务级停止控制提供连续信号。只有表格中达到的具体比较才算已有内容证据。边界和双值特征都是状态及系数的确定函数，不自动增加原始输入信息；价值必须体现为在预算内更好的表示或决策。',
        '传统 SNN 的硬事件前向与替代梯度、当前 HCSN 的概率流及局部梯度分别有其近似。取消0/1 step 没有取消所有不光滑点，也不自动保留事件芯片的稀疏计算收益。小型 Transformer 与双门控在本CPU实现上具有明确的运行成本优势；跨硬件和大模型结论尚无测量。',
        'LIF 补充也不代表全部 SNN 训练方法。EventProp 在其事件轨迹条件下利用伴随与导数跳跃条件计算精确梯度；CfC 已研究显式连续时间门控。因而“连续且可导”本身不足以证明本项目具有独有优势。详细文献定位与适用范围见 [RELATED_WORK.md](../../RELATED_WORK.md)。',
        '真实多模态测试是 MNIST/FSDD 的模态选择，未覆盖自然图像、语言、广义音频语义对齐、长视频或全模态预训练。主核心三种子为描述性结果，数据已在旧研究被观察。没有GPU、分布式、基础模型训练或能耗实测，不能把这些项目标成通过。',
        '后续架构改变应建立新协议：先针对本轮暴露的具体瓶颈或失败任务提出修改，再在未观察数据和成本条件下验证。若引入QVI控制，必须同时改变所执行的受控流；若学习任务价值，应改进观察状态与预测校准；若追求效率，应测量完整反向及实际跳过计算，而不只报告解析函数或单个内核。当前证据不足以支持直接投入大规模全模态预训练。',
        '## 原始文献',
        '- He, Z. & Xiong, W. (2012), [Rollover Risk and Credit Risk](https://www.princeton.edu/~wxiong/papers/rollover.pdf)：金融模型及其边界条件。\n- [Surrogate Gradient Learning in Spiking Neural Networks](https://arxiv.org/abs/1901.09948)：SNN硬脉冲与替代梯度背景。\n- [Zoology](https://arxiv.org/abs/2312.04927)：关联召回测量背景；本文的小任务结果只来自本仓库。\n- [Mamba](https://arxiv.org/abs/2312.00752)：选择性状态空间与硬件实现背景；本文不声称复现其论文大规模结果。',
    ]
    report = output/'REPORT.zh-CN.md'
    with report.open('x') as handle:
        handle.write('\n\n'.join(blocks)+'\n')
    write(output/'SUMMARY.json', summary)
    assert all(sha(paths[name]) == record['sha256'] for name, record in identities.items())
    write(output/'EXECUTION.json', {
        'source_sha256': sha(__file__), 'report_sha256': sha(report),
        'summary_sha256': sha(output/'SUMMARY.json'), 'whole_self_cpu_seconds_through_cutoff': time.process_time(),
        'scope': 'This read-only reporting process through receipt; no new training/inference, no altered statistical gates; not retroactively added into its input cost ledger',
    })
    print(json.dumps({'report': str(report), 'valid_content': c['valid'], 'valid_lif_pairs': lif['valid_pairs'],
                      'mechanism_gates': gates, 'content_screens': screens}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--costs', type=Path, required=True)
    args = parser.parse_args()
    run(args.output, args.costs)
