# R19：真正计算状态的 Rust 有限算子与 owner

本轮已从不透明状态重放前进到真实原生计算。Rust 自行从公开 Q、prior、emission 推进四十状态分布，执行 Bayes、公开 WRITE、支持保持的事件锚定更新及当前 query 的三槽有限动作规划。独立 provider 只在合法动作完成时返回实际观测；未来 target 留在 private scorer，Python 后继状态或动作没有进入 Rust。

在先发布／回读源码、后开启 namespace19063 的 run02 中，**80/80** 个 native case、**56/56** 个算子检查和 **16/16** 次真实 pending cold recovery 通过。全部动作、提交类别、实际 token 和 microcredit 费用与冻结 Python 执行完全一致。独立 raw audit 核对480个 query、302次动作、237份进程收据及实际 provider 账本。

## 数学计算与有限合同

Uniformization 使用非负幂和 Poisson 剩余项；最少保留39阶以覆盖结构路径，再要求绝对与最小正 entry 的相对尾差。对不支持的微小正支持明确拒绝，不用 epsilon 补概率。超过限定时长、分段、阶数或 roundoff 预算也拒绝。killed law 的首达概率由事件奖励积分得到，避免 `1-survival` 的稀有概率消减；完整 Q 的事件奖励保留复位后的多次事件。概率与 count 的尾差／roundoff 分开，并在复合时保留 `g_A+P_A g_B` 的交叉误差与行范数增长。

| 独立比较 | 最大绝对差 |
| --- | ---: |
| 转移矩阵／SciPy expm | 4.44e-15 |
| 转移矩阵／独立 DOP853 | 2.00e-11 |
| 重复事件数／SciPy 增广矩阵 | 7.19e-14 |
| 重复事件数／独立 ODE | 1.07e-11 |
| 首达概率／独立矩阵参照 | 1.19e-14 |
| 概率质量缺陷 | 1.91e-14 |
| 最终 owned belief／Python | 3.30e-15 |

八个稀有案例另用100位 Decimal、80项直接 Q-Taylor 作独立参照；它没有调用 uniformization。原生 likelihood 最大相对误差1.11e-15，条件后验最大差2.54e-21。这里还保留了参照本身的失败：SciPy expm 在约1e-41的 recovery 质量上最大相对偏差约40%，条件后验可偏6.98e-6；很小的绝对矩阵差不能代替稀有条件后验检查。

FP64 roundoff allowance 是在声明算术／libm假设下的工程合同，不是机器核验的区间证明。动作与提交类别均使用原优先序的严格 argmax；gap≤1e-7时停止并记录不合格，另提供只读取公开模型和owned state的密集参照 fallback。实际最小动作 gap 为6.40e-6，最小类别 gap 为0.2994，本轮没有调用 fallback，也没有容差重判平局。

## 冷进程、模型身份与真实 provider

Rust 保存自己的数值状态、phase、pending action／inbox、时钟与费用。真实 ACT 已由 provider 原子记账但 owned state 未提交时杀死进程，新解释器重建空 Q cache、取得新LEASE、恢复实际 belief并继续；16个预定案例全部实际触发。provider 的 ACT／SUBMIT semantic opid 对新generation重试幂等，旧generation被隔离。

五个原生负例通过：保持 MODEL header 不变但修改合法 Q 后不能恢复旧state；重新计算seal的 NaN／负clock与NaN／负belief均被拒绝。caller header只是metadata，状态还绑定实际模型文件内容fingerprint。此处FNV64用于可信host文件的上下文／偶发损坏检测，不能冒称恶意写者认证。

范围为8个冻结fit、IID／OOD各2条新轨迹、两种表示，共4条不同owner tape的64组普通执行，加16组恢复。80不是80条独立世界，也不是核心收益的统计样本。锚定模式当前仍保存4×40个FP64 belief和4个anchor；没有移植R16的4×8 packing，不能借用296B或77%节省声明。

## 必须保留的 provenance 与成本

run01在本项目规定的远端source→world顺序完成前误启动，已全部排除，不能借其通过结果作正式确认。原42个operator、55个case、167份收据和执行源完整保留；已记录子进程CPU为22.981258秒，中断外层及未记录成本为未知，未按零计算。随后仅增加强制publication receipt门和新namespace，数值算法、阈值及案例合同均未改变。run02对应源提交 `13a8c2596a4c1955619d352b02f6ce0113849f0f`，执行源manifest为 `bf361b8d89af1a0041db61c6fe3f5a6539ce1fe24a33ecb872a454ef8e6e8847`。

run02完整外层CPU为 **46.080450秒**、墙钟133.586744秒；其中237个子进程CPU为34.534088秒，已包含在外层，不能重复相加。外层涵盖私有owner构造、原生计算、全部参照、检查与输出；编译、开发、审计和run01未知部分没有形成完整项目总成本。最大wait4 RSS为95,328KiB，不能当成纯Rust稳态内存。CPU不是焦耳，本轮也没有同质量的部署成本优势门。

## 仍未闭合

原生实现覆盖导出的有限Q，不包括完整He–Xiong参数到Q构造、连续自由边界最优性或学习全参数梯度。真实trained symbol／FP32 head／γQ的介入和owner恢复属于另一个独立阶段，不能借用当前plain后验argmax结论。生产ModelPort、校准／release authority、网络、断电、GPU、能耗和开放域跨模态仍需各自证据，production_activation保持false。

原始数据、排除记录、每逻辑文件hash与还原步骤见 [delivery_small/README.md](delivery_small/README.md)。
