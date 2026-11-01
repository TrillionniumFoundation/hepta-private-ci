# R17：冷进程与挂起动作恢复

本轮新增闭合的是**有限研究 owner 的冷进程恢复**：在完整与锚定两种表示上，实际杀死解释器，再由新解释器从磁盘重建模型、owner、内存和动作游标。修正依赖冻结后的 run02 共 **76/76** 个 SIGKILL 恢复案例通过；**164** 个进程均以空转移／事件缓存启动。连续动作、观察、费用、effect ID、最终内存及 checkpoint hash 与无中断执行完全一致；新状态机的完整查询记录也与冻结的 R16 `execute` 一致。

这项结果不提供解析核心质量增益或生产采用资格。范围是一个冻结拟合（151101）、IID/OOD 两个确定性六查询世界、full/anchored 两种内存和三个策略设置；76 是故障位置组合数，不是76个独立统计样本。

## 恢复机制与覆盖

SQLite 是唯一的本地持久权威。一次提交同时保存内存、query cursor、pending action、已收到的观察、费用与effect ID；CAS序号拒绝旧状态重放。WAIT、READ、REFRESH 分别覆盖 prepared、elapsed、received、applied 后的进程死亡，并在观察已获得但未持久化、效果已计算但未提交时杀死进程。另有 value policy 的查询边界恢复。

READ/REFRESH 来自冻结的只读确定性owner：相同绝对时间、key、quality、query、step重试得到同一token。这样能检验本地重复观察与收费是否发生，但不能推出状态型外部RPC的exactly-once。controller只接收belief与公开价格，不接收owner路径或评分target。

九项拒绝测试全部通过：模型配置不匹配、非法模型payload、owner配置不匹配、owner世界指纹不匹配、旧sequence重放、错run状态、状态字节损坏、history回滚和重复effect。校验和不是对可重写全部磁盘并重新计算hash的攻击者的认证。

## 独立检查与成本

不导入runtime、planner或executor的stdlib审计从SQLite与JSON重算：76组完整状态比较、456个query、728个effect，重新核对收费、奖励、operation ID唯一性、死亡时pending阶段、真正的SIGKILL、新进程PID和零缓存启动；全部通过。独立代码复核发现初版冻结遗漏kernel和cell protocol；原始结果与窄冻结均保留，没有静默替换。

| 记录 | 完整子进程CPU | 其中被杀子进程CPU | 说明 |
| --- | ---: | ---: | --- |
| run01 | 63.114997 s | 23.862056 s | 原29文件窄冻结；保留development |
| run02 | 59.976592 s | 22.427258 s | 修正32文件冻结后完整重跑 |
| 两轮合计 | 123.091589 s | 46.289314 s | 328个worker，失败／被杀尝试不免费 |

run02子进程最大RSS为77,648KiB；上述不是整个模型内存或稳态部署指标。wait4覆盖解释器、import、模型／owner重建、SQLite读取、全部执行、fsync和输出。父进程参照生成、开发与审计没有完整外层计量，所以不能写成全项目总成本；CPU秒不换算成焦耳。

## 仍未闭合

生产Rust ownership、真实transport／外部状态效果、并发owner与fencing、OS重启／断电耐久、所有fit/版本/硬件覆盖仍未验收。SIGKILL发生在声明的本地转换前后；未在SQLite内部提交指令中注入死亡。数值模型里的WAIT/READ/REFRESH是逻辑耗时动作，不是实际网络挂起。解析核心D−B、完整同质量成本优势、连续自由边界、学习全参数梯度、未知生成器与真实开放域跨模态、GPU和能耗仍须各自证据。

复现见README；正式使用 `--manifest SOURCE_MANIFEST_V2.json`。run02的完整冻结SHA256为 `ba88bf7ebfaa215fc2da247e9ba6956ff074316395bf81d85b4f46618ab4fd0f`。本轮是工程故障复现，不称远端预注册的科学确认。生产激活保持false。

完整原始证据以 [delivery_small/MANIFEST.json](delivery_small/MANIFEST.json) 绑定19个不超过80,000字节的切片；下载、重组、哈希校验及解包见 [delivery_small/README.md](delivery_small/README.md)。两轮全部SQLite字节、日志与冻结状态都在切片内；直接可读的SUMMARY与审计保留在results目录。
