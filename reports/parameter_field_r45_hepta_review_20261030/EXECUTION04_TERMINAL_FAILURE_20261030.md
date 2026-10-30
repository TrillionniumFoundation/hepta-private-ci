# Execution04 终止记录与 execution05 恢复边界

本记录更新于 **2026-10-30 02:18 EDT（America/New_York）**；终止事件发生于 **2026-10-30 01:47 EDT**（机器时间 2026-10-30T05:47:05Z）。它取代此前“仍处于初始准入”的当前状态描述；此前带时点的原记录保留。

## 已确认的结果

execution04 已以失败结束，原 launcher、supervisor、controller 和 A-29 worker 的进程身份均已消失。**科学任务完成 1/14，原阶段持久化确认完成 1/17；没有 primary COMPLETE，也没有完整研究结论。**

| 项目 | 实际观察 |
| --- | --- |
| A-17 | 完成 39,168 个 scheduled / gradient backward microsteps；阶段原始文件归档、上传、实际远端读回与 ACK 均完成 |
| A-29 | 完成前失败；FAILED 记录 14,784 个 scheduled / gradient backward microsteps、13,728 optimizer steps |
| 终止类型 | worker 与 controller 先后发生原 RAM margin / pending-growth guard 的 MemoryError |
| cgroup OOM / oom_kill | 事件前后均为 4 / 4；未出现新增计数 |
| 其余任务 | 未完成；不得由进程启动、部分日志或已存在目录推定完成 |
| 本轮已知梯度工作 | 53,952 microsteps；包含完成 A-17 和失败 A-29 |
| 本轮已知 CPU 下界 | 4,560.319171912 秒，范围与包含关系如下 |

A-29 的 FAILED 写入时间为 05:47:05.058429 UTC；controller 的 ENVELOPE_FAILED 写入时间为 05:47:05.323109 UTC。controller traceback 指向读取 worker stdout 后调用 StorageBudget.append_bytes，随后原 check 拒绝待写分配。controller 实际 exit_code 为 1、wait_status 为 256。worker 旧代码没有保存第一次拒绝的精确目标、待写字节或完整 traceback，因此不能将后来 STATUS 的资源采样冒充精确拒绝输入。

A-29 只有部分状态与轨迹；BANK、三类 head / feature bank、PATHS 以及 COMPLETE 均不齐全。最后日志里的 parent 19/48 不是经过验证的恢复游标。任何新执行必须明确登记为整个 A-29 任务重做。

## 成本的可加范围

外层 wait4 测得 supervisor 及其已等待后代合计 CPU **3,290.208896 秒**、wall **6,375.233694451 秒**。A-29 失败阶段自报 CPU **1,270.110275912 秒**；该 worker 没有被旧 controller 正常 wait4 回收，所以这项不在上述等待树中。两项相加给出 **4,560.319171912 秒** 的已知下界。

该下界未包含根代理的独立上传/读回进程、launcher 自身 CPU，以及 A-29 未测得的入口、清理和其他未等待成本。A-17、controller 和归档的嵌套成本不能再次加到外层等待树上。全部成本记录保留其测量范围；失败工作不会被新 episode 的成功结果抹去。

## 完整失败证据已经保存并读回

终止后，关闭的 RAW 及元数据被打包为 **720 个文件**的完整失败归档。归档为 **172,768,632 bytes**，SHA-256：

`9e8a1e2eaacff1d6e0aefc8672f98a6a70c99a3186f0aae13573f095cee4fddb`

归档、manifest、verification 与 failure summary 共四项，合计 **173,153,524 bytes**。实际上传及四次独立远端物化均已完成，逐项检查了内容 SHA、字节数、实际文件/版本身份、元数据、传输收据和真实 helper wait4。完整远端核验收据 SHA-256：

`2eff6678e6929b512214a18f12054df0b8f181ea461bb448529d8181d1fbb724`

这证明失败证据被保存，**不代表科学研究完成**。本公开记录只公布状态与内容承诺，不发布模型、数据、私有文件身份、凭据或传输链接。

A-17 原阶段归档另有独立持久化链：308 个逻辑文件、141,140,262 个逻辑字节；两份压缩 part 共 128,969,999 bytes。原 ACK SHA 为 `d7e9bcb25e6c665269980622fa7cff4e454134ef63699add94a5261c60d0e480`，原 ACK_VERIFIED SHA 为 `e89c99e65a0723b46cacf18183f860b12e8c7d23ff8ccfd0c52126bbed354e57`。接受 ACK 后，仅删除了两个已核验的独立本地读回副本；原 RAW、原归档、CAS、远端版本和全部小凭据保留。删除与验证收据也包含在已保存的证据链中。

## 新恢复方案的约束

下一轮身份拟为 `execution05_backpressure_20261030`，使用独立源码分支和全新 RAW / OPS 目录。此记录发布时，**execution05 尚未开始科学执行**。

恢复设计包括三个明确变化：

1. 显式继承已完成并持久化的 A-17，核验原源冻结、profile、runtime、全部导入文件及 state header；旧科学 seal 保持原字节。新目录的继承凭据明确标记 executed_here=false，不伪造新 START、PID 或新训练。
2. A-29 从原固定种子和输入重新执行整个任务；失败 A-29 的 14,784 microsteps 单独保留为额外成本。A-17 在完成研究的总体梯度数中只计一次。
3. 对明确的临时资源拒绝建立有界等待：保留原 margin、reserve、CPU、wall、step 与 OOM 门；等待前释放所有写锁，恢复时重验游标、文件身份和预算。同一写入只提交一次，不重做梯度或评分。未知 MemoryError、部分写入、源变化或完整性失败继续终止。控制器异常路径真实回收自己创建的子进程并记录 wait4。

这些属于待完成验证与登记的运维改动。必须先完成集成测试、源码发布与冻结、实际 import closure 和资源准入，才能启动新科学任务。共享资源不足仍然是实际阻塞；没有通过修改原门槛把它标为关闭。

## P1–P5 的状态与解释

五项优先级的动作空间、数据划分、baseline、guard、预算、统计阈值和结论规则均保持原登记。A-17 单任务完成不能回答整体效果，P1–P5 仍需完整任务人口、原 26 / 30 个 seal、literal restore 和已登记补充分析。

尤其需要保留：

- “控制意图不同”与“guard 后合法后继不同”的区别，及真实 fallback、首次可见分歧和成本范围。
- baseline-aligned advantage 的时钟、剩余预算与完整状态绑定。
- 固定动作空间下 field、完整状态和同信息历史的比较；完整状态拟合未获胜不能证明 field 充分。
- 强 ordinary、轻量 fixed-taper、独立任务结果、保留能力与总成本的实际比较；原 B 的单一布尔 gate 不自动覆盖轻量 controller 或成本。
- Ordinary / Hepta × baseline / field 的两项简单效应、交互和跨架构 field 比较；正交互不自动意味着两架构都受益。

论文与 Hepta 的理论评论仍见 [THEORY_TO_HEPTA_REVIEW.md](THEORY_TO_HEPTA_REVIEW.md)，预先固定的判定矩阵见 [DECISION_MATRIX_DRAFT.zh-CN.md](DECISION_MATRIX_DRAFT.zh-CN.md)。当前没有足够的完整本轮数据宣称参数场控制有独立净收益，或 Hepta 提供额外适配性。

## 后续执行器中断：2026-10-30 07:52 EDT

07:52 EDT 的只读核验发现，原工作区的源码、RAW、OPS 与运行环境在当前执行器均不可见；三个独立任务也确认其新代码文件不可见。已保存的四项完整失败证据随后被实际恢复，173,153,524 bytes 的 SHA 均与上述原承诺一致；公开源码也恢复到精确提交 6b9353d8fd5ba2d05346afb0772dc49daa6038bd。尚未公开的新恢复代码按保留的上下文重建，并重新验证；失联前的测试不代替重建版本的测试。此事件及重建成本将单独记录，没有因此启动或补记任何科学工作。
