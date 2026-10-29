# Parameter field × Hepta：全量执行状态与 comments

状态：**BLOCKED — 全量科学验证尚未完成。** 本文件保留 2026-10-29 08:21 UTC 的注册准入检查，并补充 08:30 UTC 的交付读回。代码已实现、审查并提交；不能把实现完成解释为五项科学假设已经得到支持。

## 已经做完的工作

五项问题均已落实为具体实验、数据访问屏障和成本记录，相关源码在本目录。原科学协议为 [PROTOCOL.json](PROTOCOL.json)；当前操作修订为 [OPS_ATTEMPT02.json](OPS_ATTEMPT02.json)。源码冻结记录逐文件保留原科学实现身份，只有资源管理与证据写入使用新增操作层。

| 用户优先级 | 对应实现与固定比较 | 当前可报告的证据 |
|---|---|---|
| 1. 合法后继是否不同 | A：3 个固定模型、144 个完整 parent、每个 parent 的 4 个候选及相同 baseline tail；分别记录 guard、完整状态、参数/动量、输出、首次分歧、fallback、真实成本 | 两次真实 kernel 工程预检通过；全量 A 运行中断，不能报告完整分支总体统计 |
| 2. 价值标签是否对齐 | A：相同 baseline、guard、时钟、288 步终止预算及配对 tape；9 个固定 head；误差与可得动作收益比较 | 标签/状态/屏障实现与针对性测试完成；完整 bank 与校准结果尚未封存 |
| 3. 场缺失哪类决策信息 | 同动作集上的 field12、54,740 维 current-state predictor、114 维 history；W 固定 parent 的隐藏 momentum 反射诊断 | 比较与诊断已实现；W 尚未运行，不能声称已发现 action-ranking witness |
| 4. 参数场是否有独立净收益 | B：3 个固定模型 × 16 个新 schedule × 5 方法 = 240 路径；ordinary、field、完整当前状态、history、fixed taper；两个 observer；任务/保留能力/总成本 | 独立资格集尚未打开；效应、修正区间和成本优势均待验证 |
| 5. Hepta 是否额外适配 | C：ordinary/dual FPT 神经元 × baseline/field；8 个配对评估 seed，32 个评估端点；全参数 warmup；检验交互 | 首轮完成 20 个 warmstart 后进入分支生成，但未完成 C；未打开最终测试集，不能报告交互结论 |

完整固定计划为 A 117,504、B 69,120、C 57,536、W 2,880 个物理梯度 microsteps，共 247,040。另有 R 的 96,768 步确定性证据重构，合计 **343,808**。这些是待完成计划量，不是已执行量；历史失败与工程预检另计。

## 已有的真实单点证据

两次工程预检各实际执行 432 个梯度 microsteps，耗时分别约 19.60 秒和 19.00 秒。完整状态字节恢复、incoming gradients/RNG 保存、特征测量不改变完整状态、正反动作顺序的独立重放均通过。两次预检在同一个固定 parent 得到一致的下表；它们是重复的工程核验，不是两个独立统计样本。

| 候选学习率倍率 | guard 接受 | 相对 ordinary 合法后继的参数 L2 差 | 已记录的后继差异 |
|---:|:---:|---:|---|
| 0× | 是 | 0 | 只有梯度缓存表示不同 |
| 0.25× | 是 | 0.4033536 | 参数、optimizer、梯度缓存 |
| 1×，该 seed 的 ordinary baseline | 否，执行 rollback | 0 | 参照 |
| 2× | 是 | 1.6292711 | 参数、optimizer、梯度缓存 |

来源：[ENGINEERING_SUMMARY.json](evidence/ENGINEERING_SUMMARY.json)，包含两份原始工程凭据的大小与 SHA。这个结果证明该真实 kernel 中存在产生不同参数/动量合法后继的候选控制。它没有给出独立任务提升、质量/成本净收益或 Hepta 交互的证据。

完整状态 hash 必须与参数/optimizer 差异分开解释。0× 与被拒绝的 baseline 的 hash 可以仅因梯度 `None` 掩码不同；下一 microstep 会清理梯度，这种差异本身不足以证明未来行为不同。报告器因此分别统计完整状态、参数/动量和实际输出。

## 首轮中断与真实成本

第一轮在三组 A 各完成 43/48 个 parent、C 完成 20 个 warmstart 后发生执行服务中断。所有研究计算进程消失，其私有 tmpfs 随进程 namespace 消失；最后导出的逻辑 raw 量为 410,254,736 字节。未归档的原始证据已经丢失，不能把新重跑当成原字节恢复。

观察到 cgroup 上限 8 GiB、峰值超过该值，以及累计 `oom=8 / oom_kill=4`。这与内存压力一致，但累计计数不足以逐 PID 证明中断原因。已经释放本任务尚未写入数据的 RAM 归档预留文件；未删除其他任务数据或终止其他任务。

幸存日志能证明的工作下界如下：

- A：每个 seed 至少 31,440 个 microsteps，三个 seed 共 94,320。
- C：20 个完整 warmstart 共 8,000。
- 两次独立记账的工程预检：432 + 432。
- 已知总下界：**103,184**。未写出日志的部分工作及丢失的附加计数仍未知，不能把此下界当成完整总成本。

[首轮基础设施记录](evidence/INFRASTRUCTURE_FAILURE_01.json) 保留推导与幸存进度；[结构化状态报告](execution_status/RESULTS.json) 没有重复相加包含式小计。历史 V5 exact-regression 的 **FAIL** 保留；原 1 GiB 全研究存储 / 2 GiB 空间保留合同没有被宣布通过。

## 当前阻塞

[FINAL_PRELAUNCH_CHECK.json](evidence/FINAL_PRELAUNCH_CHECK.json) 已验证初始 A/C 四个 job 的冻结源码、协议、操作修订与队列身份，但实际 RAM 准入拒绝：

| 指标 | 字节 / GiB |
|---|---:|
| cgroup 上限 | 8,589,934,592 / 8.000 GiB |
| 当前总占用 | 8,584,249,344 |
| 扣除保守可回收缓存后的有效占用 | 8,131,141,632 / 约 7.573 GiB |
| 首个 worker 预留 + margin | 805,306,368 + 1,073,741,824 / 1.750 GiB |
| 准入所缺的有效容量 | 1,420,255,232 / 约 1.323 GiB |

交付前 08:30 UTC 再次核验时，原 A/C 与新 A/C/controller 共五份 source freeze 的所有文件仍精确匹配；RAM 门仍拒绝，保守有效占用为 7,810,428,928 字节，首个 worker 的容量缺口为 **1,099,542,528 字节，约 1.024 GiB**。见 [DELIVERY_CHECK.json](evidence/DELIVERY_CHECK.json)。

因此 attempt02 的科学 worker 数、梯度数和新 endpoint 访问数都是 **0**。这不是科学阴性结果，而是尚未得到完整科学结果。当前没有新训练在后台运行。

这个缺口只是首个 worker 的启动条件；运行中还要为原始证据增长、第二个 worker 与实际峰值持续保留空间。当前可调用环境没有可直接切换的已就绪备用执行器。恢复需要释放足够实际容量，或提供有空闲 RAM 和证据空间的执行环境。科学配置不需要重新选择。

## 恢复与证据保存

[ATTEMPT02_RUN.md](ATTEMPT02_RUN.md) 给出当前已冻结的精确启动入口。[初始队列](registrations/QUEUE_ATTEMPT02_INITIAL.json) 只含已经可冻结的 A/C job。B、W、R 与评分 job 要等其完整父 artifact seals 存在并绑定后再加入；不能提前跳过这些依赖。

当前操作层使用进程外的任务目录、最多两个 worker、逐写入配额/RAM 检查、统一锁与无损内容去重。所有原始逻辑路径仍按完整字节数记账。这个目录在本次执行服务重启后保留过，但仍不能承诺跨主机销毁持久保存。没有上传新的 raw archive。

R 用新计算重建 576 个 terminal，核对原声明的完整 component/transaction identities，并验证新保存张量的真实恢复。R 不增加统计样本，不重新拟合，不改变原标签；其 96,768 个梯度步全部另计。R 同样尚未执行。

恢复链路、评分祖先屏障、报告器和最终容器共有 **37 项针对性合成测试通过**；它们没有读取新的科学端点。详情见 [ENGINEERING_VALIDATION.json](evidence/ENGINEERING_VALIDATION.json)。全仓 Rust 格式化入口不在本次恢复的 Python 源码子集中，因此没有声称全仓格式化/CI 已通过。

## Comments：后续结果应如何判读

1. **保留三个不同问题。** 候选是否改变合法后继、有限场是否保留动作排序信息、最终策略是否有独立净收益，分别需要机制、表征和任务证据。单点合法后继差异只支持第一个问题。
2. **误差必须与可得收益同尺度比较。** baseline-aligned advantage 已按相同 kernel 与剩余预算定义；下一步要看校准误差、动作可得增益、阈值与 fallback 的共同结果。一个较低的绝对回归误差仍可能大于全部可利用收益。
3. **完整当前状态 predictor 不是最优 oracle。** 它排除了未来 RNG/tape，并含高维 nuisance。有限样本 ridge 的成败不能单独证明参数场充分或不充分。W 若得到近似同场而动作排序改变的构造态，也必须注明 off-policy、非可达性保证。
4. **净收益同时看任务、保留能力与成本。** ordinary 与 fixed taper 是必要对照；两个 observer、完整配对与多重比较修正都保留。所有候选（包括 0×）仍消耗实际 forward/backward/guard 工作，rollback 也不退还已花成本。一时的 reward 提升不能自动解释为成本优势。
5. **Hepta 增量看交互与绝对四臂表现。** 目标交互是 `(dual+field − dual+baseline) − (ordinary+field − ordinary+baseline)`。即使交互为正，也要检查保留能力与绝对任务质量。这次 C 只检验匹配的 ordinary/FPT 事件律增量，不验证完整 Call–Put/NDU/HJB，也不外推到 LLM 尺度。扩大 neuron 或模态应等待这些证据。
