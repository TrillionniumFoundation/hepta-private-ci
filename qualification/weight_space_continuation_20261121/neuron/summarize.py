"""Read-only aggregation of the sole finished attempt; no model execution."""
import json
from pathlib import Path
import numpy as np
from compile_core import ROOT, FT, read, save, identity

out=ROOT/'attempt001';r=read(out/'RESULTS.json');receipt=read(ROOT/'attempt001_supervisor.json')
reader=read(ROOT/'RECORD_REVIEW.json');reader_receipt=read(ROOT/'READER_EXECUTION_RECEIPT.json')
discovery={fit:read(out/f'discovery/fit_{fit}.json') for fit in r['fits']}
old_training={fit:read(FT/'attempt001'/f'fit_{fit}_CANDIDATE.json.gz') for fit in r['fits']}
domain_metrics={}
for domain in ('iid','ood'):
    blocks=[read(out/f'confirmation_{fit}_{domain}.json.gz') for fit in r['fits']]
    rows=[row for block in blocks for row in block['records']]
    domain_metrics[domain]=dict(
        expected_decisions_mean=float(np.mean([row['arms']['J_COMPILED']['expected_decisions'] for row in rows])),
        expected_continuations_mean=float(np.mean([row['arms']['J_COMPILED']['expected_continuations'] for row in rows])),
        Brier_means={arm:float(np.mean([block['Brier_means'][arm] for block in blocks])) for arm in r['summary'][domain]})
save(ROOT/'SAVED_RECORD_SUMMARY.json',dict(scope='descriptive saved-record aggregation only',
    domain_metrics=domain_metrics,
    original_training=[dict(fit=fit,steps=old_training[fit]['training']['steps'],
        epochs=old_training[fit]['training']['epochs'],
        optimizer_CPU_seconds=old_training[fit]['training']['CPU_seconds'],
        attributed_total_candidate_CPU_seconds=old_training[fit]['candidate_attributed_CPU_seconds']) for fit in r['fits']],
    parent_science_child_CPU_seconds=receipt['child_CPU_seconds'],
    reader_child_CPU_seconds=reader_receipt['child_CPU_seconds'],
    combined_science_reader_child_CPU_seconds=receipt['child_CPU_seconds']+reader_receipt['child_CPU_seconds']))

lines=['# Hepta Neuron：own-law Continuation 编译与局部权重可实现性审计','',
'## 一、结论','',
'本轮唯一新决策候选 `J_COMPILED` 在新独立生成的 IID/OOD 公共日程上恢复了 checkpoint 自有 law 的解析 Continuation 决策价值。四项冻结 primary 全通过。完整 Q 证据被编译为仅含所选策略可达状态的闭合自动机；180 个世界的动作、完整状态更新、终止状态和期望 utility 与完整图严格一致。',
'',
'这是执行程序的结构化编译，不是固定 85→tanh48→4 架构的权重编辑成功。本轮权重编辑数、梯度更新数和部署数均为零。局部可实现性审计没有证明现有半径不够：所有非固定终止障碍的逐约束下界均在预算内，全 MLP 的保守下界也未排除任何状态。多个状态的联合可满足性仍未解决。','',
'## 二、冻结、隔离与统计边界','',
f'- Protocol SHA256：`{r["protocol_sha256"]}`。',
'- 先经零 forward 预检与跨 agent 静态审查，再冻结一次；随后仅运行一个 science attempt。没有技术重试、结果后调参或确认集筛选。',
'- 完整排除3456已知历史日程，包括失败且未评分的旧 DEV。新增 DEV20（每fit4个IID），仅用于契约资格；之后独立 entropy 生成 CONF160（每fit每域16）。新 DEV 也从 CONF 排除，最终内容键3636。',
'- 独立分析单位仍是五个原始 fit：11、23、37、53、71。世界数不增加 n。采用 fit-level paired Student-t、df4、两侧 Bonferroni4 familywise95%；正态近似及五fit条件推断是限制。',
'- 新日程内容不重叠不等于外部独立性证明；entropy 与预注册均无外部托管。此四项 family 不与过去的显著性检验合并。',
'- 所有实验在独立副本；原始输入155个 pins 的前后字节校验通过，五份 C gzip 的恢复副本完全一致。','',
'## 三、同批新 CONF 的模型质量','',
'以下是固定 deadline-six endpoint 任务的 declared-law 期望 utility，不是实际市场 P&L。','',
'| 候选 | IID 平均 utility | OOD 平均 utility | 身份 |',
'| --- | ---: | ---: | --- |']
names={'C':'原模型','D':'旧147 Q head编辑','T':'旧4324 MLP梯度训练候选','K':'上一轮已封存selector结果','J_COMPILED':'本轮own-law解析策略编译'}
for arm in ('C','D','T','K','J_COMPILED'):
    lines.append(f'| {arm} | {r["summary"]["iid"][arm]["mean"]:.12f} | {r["summary"]["ood"][arm]["mean"]:.12f} | {names[arm]} |')
lines+=['','| 冻结 primary | 平均差 | Bonferroni4 simultaneous95% CI | lower > .005 |','| --- | ---: | --- | --- |']
for name,x in r['primary'].items():
    lines.append(f'| {name} | {x["delta"]:+.12f} | [{x["familywise95"][0]:.12f}, {x["familywise95"][1]:.12f}] | PASS |')
lines+=['',
'D/T 仅是相同新样本上的已冻结历史参考。其构造、训练、teacher 与选择预算不匹配本轮编译，不能把表格解释为公平预算下“直接编辑普遍优于训练”。T 曾进行8 epochs、224–240 Adam steps；实际 optimizer CPU 每fit约0.730–0.864秒，但包含 teacher/data preparation 等归因的候选成本约25.48–28.96秒。只删除反向传播并不必然删除主要成本。','',
'## 四、结构化 Q 到策略自动机','',
'编译接口只接受 checkpoint、其 stored transition tables、原 decoder confusion 与公共日程。它先枚举完整合法状态 DAG 并用自己的 law 求 Bellman Q，然后才构造评估器真 law 图；没有 future packet 内容、实现的未来观测或 evaluator 标签进入编译。',
'',
'动作是 STOP、WAIT、READ、REPAIR、SUBMIT_0、SUBMIT_1。继续动作 tick+1，事件只有 NONE、FAILURE@due、OBS0@due、OBS1@due。READ 观测完成边界；REPAIR 修 sensor，并不 reset 潜在过程。完整 state 保留 budget、pending source/due ticks、broken、last_symbol/reliability、所有历史、elapsed、charges、terminal 与 submitted。',
'',
'算法不按不完整 Markov key 代替 owner state，不用观测概率抽样删除分支。它仅删除在已确定最优策略下不可达的节点，保留所选动作的每个结构性结果，即使概率为零。完整图作为可重算 witness 保留，执行自动机拒绝未知状态或 completion。','',
'| 180个世界的编译量 | 完整 Q 证据 | 所选策略自动机 |','| --- | ---: | ---: |',
f'| 总 states | {reader["states"]} | {reader["policy_states"]} |',
f'| 总 edges | {reader["own_edges"]} | {int(r["costs"]["policy_edges"]["sum"])} |',
f'| states 中位数 | {r["costs"]["full_states"]["median"]:.0f} | {r["costs"]["policy_states"]["median"]:.0f} |',
f'| states 最大值 | {r["costs"]["full_states"]["max"]:.0f} | {r["costs"]["policy_states"]["max"]:.0f} |',
f'| canonical JSON bytes 中位数 | {r["costs"]["dense_canonical_bytes"]["median"]:.0f} | {r["costs"]["sparse_canonical_bytes"]["median"]:.0f} |',
f'| canonical JSON bytes 合计 | {r["costs"]["dense_canonical_bytes"]["sum"]:.0f} | {r["costs"]["sparse_canonical_bytes"]["sum"]:.0f} |','',
f'各世界 sparse/dense 字节比中位数为{100*r["costs"]["sparse_to_dense_byte_ratio"]["median"]:.6f}%。这是序列化结构的缩小，并未单独证明运行时 RSS 按同样比例下降。完整 witness 仍需保留用于校验，native 实现是否在校验后释放它须另计。',
'',
f'新 CONF 的 J 平均决策调用数：IID {domain_metrics["iid"]["expected_decisions_mean"]:.6f}、OOD {domain_metrics["ood"]["expected_decisions_mean"]:.6f}；平均继续动作数分别{domain_metrics["iid"]["expected_continuations_mean"]:.6f}、{domain_metrics["ood"]["expected_continuations_mean"]:.6f}。这些是固定任务的 expected calls，不是未来生产调用量。','',
'## 五、权重级缺陷与半径必要条件','',
'DISCOVERY仅重用原320 TRAIN世界、144397状态输入与之前冻结的 own-law teacher。原 C strict forward 与缓存逐数值完全一致。目标是每个状态的 own-law 最优 action；权重半径为原147 continuation readout范数的一半。','',
'固定 hidden 与 belief 时，continuation/continuation 的单竞争约束下界是 gap/(sqrt(2)||[h,1]||)，continuation/固定动作是 gap/||[h,1]||。每个状态取所有竞争动作下界之最大。严格 tie-priority 约束的半径是 infimum，等号不必可达。若固定 terminal 本身优先于目标 terminal，则任何147Q-only编辑都不能令该终止目标获胜。','',
'| fit | 半径 R | own-law/C动作不同状态 | 固定terminal障碍状态 | 障碍占 C占用×own action gap 的质量 | 全MLP必要半径最大 |','| --- | ---: | ---: | ---: | ---: | ---: |']
for fit,d in discovery.items():
    obstruction=d['fixed_Q147_lower_bound']['incumbent_occupancy_times_own_action_gap']['mass_fixed_terminal_obstruction']
    lines.append(f'| {fit} | {d["radius"]:.9f} | {d["changed_optimal_actions"]} | {d["fixed_terminal_obstruction_states"]} | {100*obstruction:.6f}% | {d["whole_MLP_max_bound"]:.9f} |')
lines+=['',
'全部有限的147Q单约束下界均小于对应 R；整体4324 MLP 的保守必要下界也全部小于 R。因此本轮不能支持“架构或全半径全局不可实现”。固定 belief 的终止障碍在动作缺口加权质量中只占很小部分，不能单独解释主要端到端收益不足。',
'',
'全MLP推导允许48 hidden与4个readout同时移动。令 X=||[x,1]||、H=||[h,1]||，首层/读出位移分别rA,rB，则每个动作差的变化至多 M X rA+B H rB+B X rA rB。用 Cauchy–Schwarz 与rA*rB≤r²/2，得到 Lr+(BX/2)r²，其中 L=sqrt((MX)²+(BH)²)。正根给必要位移界；各动作类别的M/B明列于冻结协议。使用 f64 数值而非区间算术。',
'',
'所有原始逐状态界与权重均保存在 discovery/fit_*.npz；报告同时保存全支持均匀、原 C eligible occupancy、occupancy×action gap、disagreement occupancy四种分布。它没有解联合多状态可满足性，也没有把弱下界当作可实现性证明。下一次若开展权重求解，应先做联合约束的可满足性/最小半径证据，再决定是否值得编辑。','',
'## 六、资源、NDU与严格验证','',
f'- science完整子进程CPU {receipt["child_CPU_seconds"]:.5f}秒，wall {receipt["enclosed_wall_seconds"]:.5f}秒，峰RSS {receipt["child_peak_RSS_bytes"]} bytes；CPU7、单数值线程。',
f'- 独立reader完整子进程CPU {reader_receipt["child_CPU_seconds"]:.5f}秒，model forward0；合计 {receipt["child_CPU_seconds"]+reader_receipt["child_CPU_seconds"]:.5f}子进程CPU秒。零forward预检另计，不隐藏为训练成本。',
f'- 编译器内存中完整准备（own-law图、canonical序列化、parse、闭合与状态验证）中位CPU {r["costs"]["full_cold_compile_CPU_seconds"]["median"]:.9f}秒，最大{r["costs"]["full_cold_compile_CPU_seconds"]["max"]:.9f}秒，180世界合计{r["costs"]["full_cold_compile_CPU_seconds"]["sum"]:.9f}秒。artifact gzip写盘、评估与报告另含于science总CPU，未被假冒为此内存函数计时。',
'- dense/sparse parse的原始零计时保留，表示本次计时分辨率未分辨到开销；不得据此称零成本或报告无限加速。',
'- 每个日程都唯一，没有相同日程复用；未观察到的摊销次数、生产 horizon 或 CPU→utility 汇率未填造。完整新编译成本必须归属该日程。',
'- NDU的生产默认仍为 KEEP_ORIGINAL_AND_STOP；只有独立定义的净价值与未来资源条件为正时，才能选择额外计算或替换执行程序。','',
f'独立reader重算180世界全部{reader["own_edges"]} own-law edges的源顺序 Bellman、所有候选 declared-law utility、Brier、四个主检验区间、policy closure和{reader["terminal_updates"]}个 terminal更新，全部通过。原序逐项 += 与最低action index tie规则固定，避免过去 compensated sum 引入的1ulp action差异。native Rust的checkpoint law认证、真实step与disk恢复由并行runtime研究单独出具receipt，不把其未完成项目冒充本报告测试。','',
'## 七、结论的应用范围','',
'这批模型任务是固定deadline endpoint分类、带读取与修复成本的解析控制。它没有金融Call/Put双价值通道，也没有first-passage目标；端到端true-law评估仍是明确声明的有限生成机制。真实金融evaluator来源、独立标签与交易utility映射尚需另外建立，不能将本轮数值转成HeptaTrader收益证明。','',
'本轮支持的下一步是把已经恢复的own-law策略价值留在明确、有界、可执行且可恢复的语义程序里；对固定架构权重编辑继续以联合可满足性证据设门槛。旧小幅表示替换失败既不能证明所有联合编辑失败，也不构成继续消耗算力的理由。','']
with (ROOT/'EXPERIMENT_REPORT.md').open('x') as f:f.write('\n'.join(lines))
manifest={str(path.relative_to(ROOT)):identity(path) for path in sorted(ROOT.rglob('*'))
    if path.is_file() and '__pycache__' not in path.parts and path.name!='ARTIFACT_MANIFEST.json'}
save(ROOT/'ARTIFACT_MANIFEST.json',dict(schema='hepta-structured-compile-artifacts-v1',
    files=manifest,file_count=len(manifest),total_bytes=sum(x['bytes'] for x in manifest.values())))
print(json.dumps(dict(report=str(ROOT/'EXPERIMENT_REPORT.md'),files=len(manifest),
    total_bytes=sum(x['bytes'] for x in manifest.values()),model_calls=0)))
