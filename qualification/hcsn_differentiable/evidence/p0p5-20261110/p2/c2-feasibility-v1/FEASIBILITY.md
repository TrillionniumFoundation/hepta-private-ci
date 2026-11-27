# C2：墙钟截尾后的恢复可行性与有界追加阶段

状态：**设计和独立结构验证器；未部署、未启动 C2、未启动原生快照循环。**

## 结论

v8 在完整 epoch 的边界保存模型、AdamW 状态、Torch RNG、数据顺序 RNG、累计完整 epoch 数和 main update 数，具备恢复下一 epoch 所需的核心状态。单个 `last.pt` 使用临时文件再原子替换。因此，若父任务最终留下来源一致的 `last.pt`、对应完整 journal 前缀、该前缀的严格最佳 checkpoint，以及可证明仅由墙钟额度触发的终态，**可以另建 C2 从这一边界恢复**。

这不是对原执行的无损、不间断恢复。完整边界之后已经执行、但未纳入恢复锚点的更新必须作为被丢弃的实际工作保留并收费；重放同一数据和更新再次发生，也再次收费。仅有 `interrupted.pt`、仅有 epoch 数、仅有 `budget_exhausted` 字符串，均不足以自动准入。

## 实际受测源码与写入顺序

分析对象是 `training-source-v8.zip`，121,388 字节，SHA256 `288283cae2b2cf4e7b68432e040e643a5e1b00a7de961fc848dd5cf20eb46102`。逐字节核对了 C1 capsule 中继承的 v8 文件，完全相同；没有修改 C1 或 canonical 文件。

| 文件／入口 | 精确来源 | 与恢复有关的行为 |
|---|---|---|
| `train.py`，`checkpoint()`，第 164 行 | SHA256 `06cb85c7a0da85fb8d656526c2b07285979bc6c47c2e00c154e89f43bcfc1a22` | `torch.save(path.tmp)` 完成后 `replace(path)`；保存 model、完整 configuration、optimizer、Torch/order RNG、epochs、main updates、数据 manifest SHA。 |
| `train.py`，epoch 提交流程，第 351 行起 | 同上 | append report row → shared hash 检查 → `epoch_completed` journal flush → 如创新高保存 `best.pt` → 更新 plateau anchor/stale → 保存 `last.pt` → 判断 plateau。 |
| `train.py`，异常收尾，第 392 行起 | 同上 | budget 异常与普通失败分开；失败路径写 `interrupted.pt`，之后才写 `finished` 和最终 result。中途硬杀可能没有完整 result。 |
| `train.py`，`budget()`，第 83 行 | 同上 | wall 超限和 peak RSS 超限共用同一条 TimeoutError 文本。必须结合计时及 RSS 原件区分。 |
| `data.py`，`save()`，第 27 行 | SHA256 `0b0676b7ec22cca17b525da25de9c767c2dd06086b177a1de1e201e235952001` | 最终 JSON 用 create-only 写入，但不是临时文件原子替换；不能把存在的半截 result 当完整报告。 |
| `campaign.py`，`run()` | SHA256 `7c353cd58d4ea555e4a44b04cc4acd43352ce227bbbb197eeaeec1954bee8f28` | 父外层实际限额取 `min(14400, 15000-dispatch_elapsed)`；inner wall 参数减 30 秒；外层 subprocess 可在 inner 收尾前硬杀。 |

### 三个不能混为一谈的边界

1. **最后完成的 optimizer step**：`optimizer_started` 在 step 前，`optimizer_completed` 在 step 后；二者之间硬杀时，是否已经完成更新只能记为未知区间，不能猜成 0。
2. **journal 已记录的完整 epoch**：写入时模型仍是该 epoch 的状态，但 `best.pt` / `last.pt` 可能尚未同步。
3. **最后持久化的自洽 checkpoint 集合**：必须核对 `last@k`、journal 的完整 `1..k` 前缀、完整数据顺序和 update 数、以及 `best@argmax(1..k)`。`best` 已到 k+1 而旧的前缀 best 被覆盖时，不能用新 best 代替旧前缀最佳。

原子替换保护单个 checkpoint；它没有构成多个 checkpoint 与 journal 的事务，也没有在 producer 中 fsync 形成断电耐久承诺。

## C2 的准入条件

本轮验证器只覆盖保守的 **soft-wall terminal** 路径：

- 原 outer 为实际 `failed / returncode 2 / fit_status budget_exhausted`，原 result 完整且哈希匹配；不把它改成 completed。
- 原 result 的 inner wall 已达到原计划限额，并且原 peak RSS 未超过原 RSS 限额。若 RSS 也超限或缺失，不能声称仅由 wall 触发。
- source_before/source_after、父 plan、原数据、initial/last/best、journal、外部依赖/runtime 身份全部逐字节绑定；shared 和 frozen physics 参数一致。
- 原训练诊断确实通过；不重跑、换样本或降低门槛。
- 未达到 plateau。除检查 stop_reason，还从完整 epoch 的 D 曲线重新计算 meaningful-improvement anchor/stale。
- `last.pt` 的 main update 数必须是完整 epoch 批次数乘 k；order RNG 与从原 seed、原数据顺序逐 epoch shuffle 得到的状态相同；所有 batch 的 episode IDs 和事件数一致。
- 模型全部状态、完整 GridSpec、每个 AdamW moment、moment step、超参数、参数顺序以及 Torch RNG 都可恢复；恢复前与原 initial 对照 frozen 参数和 buffer。
- `best.pt` 必须是该完整前缀的严格 D argmax。delta 只用于 plateau，不能改严格 best 选择。

**明确 HOLD 的情况：**硬杀且缺最终 result；result 残缺；source/hash 不匹配；无法排除 RSS/数值失败；best 领先 last 且旧前缀 best 已丢；缺失完整 epoch/order/update 证据；使用 partial interrupted checkpoint 作为完整边界；旧 snapshot 需要回滚多个已完成 epoch 却没有专门的回滚链协议。

如果已经到达 plateau，只是在加载 best 后的最终 D 评估被预算截断，应该另作只评估的 finalization 阶段，不应追加训练。该阶段也须保留原 budget-exhausted 报告并计入新增评估成本。

## 提议的有界资源方案

- 仅考虑原六个 HCSN `{101,211,307} × {0.001,0.003}` 的 wall-only 候选，准入与 D 分数高低无关。所有候选和拒绝理由都保留，不能只续训练表现较好的 seed。
- 每 fit 累计 **active process wall 最多 43,200 秒（12 小时）**，累计逻辑 epoch 最多 **200**。每个 fit 的 C2 剩余额度先扣除原完整 outer wall，再扣新增阶段已经发生的实际 per-fit wall；不按保留 epoch 或更新数退费。
- LR、seed、冻结 frontend/head、统一 adapter、完整 GridSpec、frozen physics、有效 batch32、micro8、CPU1/FP64、AS8GiB、RSS6GiB 均沿用原设置；min30、patience10、delta.002、严格 best 选择和诊断门槛不变。
- 不新增 LR、seed、初始化或调参网格；不重做 memorization。主训练从 last 边界恢复 optimizer 与两个 RNG，冷启动重建 exact-table cache；其成本计入 C2 外层计时。
- 原 4 小时结果和 300/900/1800 秒 wall/CPU 等资源截点保持原样。C2 是充分训练视图的新增预算阶段，不能回填原预算成绩，不能与原 15,000 秒 campaign 日历长度等同。
- 最多 6 个此类 HCSN active fit；若原 fit 尚存，绝不并发启动同一 fit 的 C2。正式执行前重新记录主机负载、可用内存、实际并发与 UTC 重叠。
- 以当前约 300 秒/epoch 的观测估算，12 小时仍可能先于 200 epoch 到限。达到任一 cap 仍未 plateau，继续记 insufficient；不再静默延长。

### 成本与逻辑轨迹分开

必须分别保留 `retained_trajectory_updates`、原父任务 journal 已完成但被回滚的 updates、未完成 forward/backward、`optimizer_started` 后是否完成的未知 0–1 区间，以及 C2 实际执行的 replay/new updates。完整父 outer wall、原诊断、未保留工作和全部 C2 冷启动/验证/失败尝试均进入总账。

C2 每 fit 外层时钟要在 import 与 per-fit validation 之前启动。共享 controller/preflight/source-transfer 成本单列一次，避免按 fit 重复相加；也不能当作免费。每个 epoch 只采样一次 phase wall，cumulative wall 从同一次采样加已消耗的 phase outer wall 得到。首步前写不可变 `resume-start.pt` 和 receipt，包含原 last SHA、model/config/optimizer/Torch RNG/order RNG 的身份。

原 v8 的 final fit CPU 是 fit-entry delta，不能作为完整 parent process CPU 点值拼接。原阶段的 epoch process-CPU 截点仍精确；跨阶段 CPU 如果没有原 per-PID 完整 rusage，必须给出下界/区间并保留未知。新的 C2 controller 可用经过验证的 per-PID rusage 收束，但不能追造原 PID 的精确末尾 CPU。

## 原任务仍运行时的一次性只读快照设计（尚未执行）

由于每个 last 是原子替换，普通预算中断通常仍留下上一个完整 last；最主要风险是 last/best/journal 不同代以及最终 result 尚未写全。建议在接近原 wall 上限时，经 root 决定后，对六个 fit 做 **一次有界的只读保存**，不启动周期循环。

1. 使用新的快照目录，按原 `last.pt` 打开只读文件描述符；记录 inode/device/size/mtime 和 SHA，分块复制。检查源 FD 前后 fstat 一致；名字随后被 producer 替换不影响已打开旧 inode。
2. 同法复制 best、initial、plan、memo checkpoint（若存在）、完整 journal 的某个已读字节前缀；journal 不完整末行单独保留，不把它算完成事件。绝不复制 `.tmp` 作为恢复模型。
3. 对快照运行独立 boundary validator，要求 `last@k`、完整 `1..k` journal 和严格 prefix best 一致。若碰到多文件提交窗口，保留失败快照和成本，返回 HOLD；不静默重试直至“碰巧通过”。
4. 保存 source capsule、原 source/data/runtime 身份和 snapshot manifest；snapshot 本身写完后 fsync，再封存完成标记。训练端文件保持不变。
5. 当前运行快照只证明一个边界可恢复，不能提前证明最终 wall-only 资格。最终仍需原 terminal outer/result 对账。若只能使用比最终完整 epoch 更早的 snapshot，需要独立声明回滚完整 epoch、全局 best 保留及 replay/费用协议；本轮 v1 terminal guard 会拒绝这种自动升级。

快照不会在运行中加载或改变原 optimizer、不会运行 forward/backward、不会读取 E。若原生连接不稳，保留 unknown，不重复启动任何不确定 snapshot 任务。

## 已实现与未实现

`c2_boundary.py` 提供结构验证和保守 terminal guard；它不是训练入口，也不是快照程序。结果始终保留 `execution_authorized: false` 和独立 byte-identity/runtime 合同要求，不能绕过 C1 的 completed-parent guard。

测试使用精确 v8 trainer 的真实写入代码及小 HCSN、显式 synthetic 数据；有真实 AdamW partial update 和冷缓存恢复后同一步逐张量相等检查。纯元数据的 wall/RSS/hard-kill 用例只验证拒绝逻辑，不冒充真实 native 终态。生产六个 HCSN checkpoint 尚未用于这些测试；不因此增加科学训练或数值资格。

尚未实现/执行：C2 runner/controller、原生一次性 snapshot、生产 terminal admission、原生 resumed-update 对照、最终训练后 posterior 审计。最终 checkpoint 的 P1 资格必须另审，原有限 trace/prefix 的覆盖不足不能由 C2 恢复测试补足。
