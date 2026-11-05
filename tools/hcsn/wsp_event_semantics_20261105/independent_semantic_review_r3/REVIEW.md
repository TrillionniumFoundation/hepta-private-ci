# Hepta Neuron CTMC 事件语义独立审阅

**结论：PASS_WITH_SCOPE_LIMITS。** 冻结实验的主要数值结论及事件定义通过独立复算。现有 generator 包含边界到内部的自发 reset；9 维解析 bank 是终点概率预测；严格首达事件包括初始命中；两侧首次退出需要保留存活质量。REPAIR 的同 tick latent mass/bank 相等，不意味着整个网络输出或未来决策相等。本审阅没有编辑权重，没有测量新泛化收益，没有接触 Pocket4 生产模型。

审阅日期：2026-11-05 UTC。独立成功运行结束于 05:24:32.462363 UTC。最终机器报告为本目录 `REVIEW.json`，成本收据为 `PROCESS_RECEIPT.json`。根目录 `REVIEW.json` 是先前失败尝试遗留文件，**不得把它当成本次最终结论**。

## 1. 证据身份与覆盖范围

| 项目 | 已核验的值 |
| --- | --- |
| 冻结协议 SHA256 | `b6d272a3f329fab883bb1ef12e7fbddcad9a82793a14d8d2409aaca83f5bc648` |
| 冻结时间 | 2026-11-05T05:17:58.465281+00:00，先于生产者 STARTED 时间 |
| 生产者 RESULTS SHA256 | `afeef1c538c358a14afab2294951e7e5c833798270a9dd2d24e6bd1b14701a91` |
| 审阅脚本 SHA256 | `e9904c1d6cad97bddd193ccc2cce8f2159fe892903c361a18ba7d3f85cefbebc` |
| 审阅脚本 | `../review_semantics_r3.py` |
| 审阅预设 | `../REVIEW_PLAN_R3.json`；覆盖及容差与第一版设计相同 |
| 数据 | fits 11、23、37、53、71，每 fit 原始 TRAIN public worlds 64 个 |
| 事件条件 | 320 worlds × 3 horizons（tick 1、2、6）× 3 thresholds（−0.5、0、0.5）= 2880 |
| REPAIR 对照 | 全部 320 个 world，使用可达的首次 READ 失败状态 |
| 状态空间 | 每 checkpoint 31 个内部节点和 2 个参考边界状态，共 33 个有限状态 |
| 模型来源 commit | `5b69a046d886cf4c2a73c50e58197360ea15d8f5`，由冻结协议绑定 |
| 基础训练来源 commit | `36e9ddd099e09688593bccf2c32d1dfabc39ac99`，由冻结协议绑定 |

审阅核对协议列出的每个输入、源文件的字节数和 SHA256；核对五个逐 world 记录的 SHA256、world ID 和 public JSON 内容摘要；结束前重新核对全部已读文件，未发现运行期间变化。完整文件摘要清单在机器报告中。源 commit 是本次冻结协议中的来源标识；本审阅并未重新访问该远程历史来另行证明其全部生成过程。

## 2. 独立数值路线

生产者采用全状态吸收 generator 的矩阵指数，并以 Poisson uniformization 交叉检查；reward count 采用 Van Loan block exponential 和 uniformization 积分。审阅没有调用这些诊断函数，而是使用以下路线。

对于阈值 `K`，令 `S={i: coordinate(i)≤K}`。直接以 `Q[S,S]` 的 transient submatrix 传播尚未命中的质量，再计算：

\[
F_K(t)=1-\boldsymbol{m}_{0,S}\left(\prod_j e^{\Delta t_j Q_{j,SS}}\right)\boldsymbol{1}.
\]

该公式初始仅保留未命中质量，因此 `F_K(0)=P(coordinate(X_0)>K)`，自然包含初始命中。没有把剩余质量重新归一化为条件概率。

对于两侧首次边界退出，令 `A=Q[interior,interior]`，`B=Q[interior,boundaries]`。每段从当前内部质量计算存活转移 `P=exp(Δt A)` 和两种原因的累计流量：

\[
G=A^{-1}(P-I)B.
\]

审阅用线性求解器计算该表达式，没有显式求逆。逐段累加 lower/upper 首次退出质量，验证与生产者两侧吸收模型一致。

另外预先固定每 fit 的首个 TRAIN world，使用 DOP853 积分完整 CTMC 方程和进入/离开边界的计数方程，独立检查五条六段 schedule 的 expected entry/reset counts。ODE 控制的覆盖是五条 schedule，而非全部 320 条；全量 320 条仍完成事件和首因 transient-matrix 检查。

| 核验量 | 最大绝对差 |
| --- | ---: |
| endpoint（独立 ordinary expm 对原始记录） | 1.0147438445073931e-13 |
| first-hit（transient survival complement） | 4.923839114212569e-14 |
| 首次 lower boundary cause | 2.736699755701011e-14 |
| 首次 upper boundary cause | 1.7041923427996153e-14 |
| 未触及两侧边界的存活质量 | 5.440092820663267e-15 |
| 五条预定 ODE controls 的 expected counts | 1.2434497875801753e-14 |
| 五条 ODE controls 的边界占据质量 | 1.149080830487037e-14 |
| 分区及流量守恒残差 | 1.3145040611561853e-13 |
| 存储 transition table 对 expm(generator) | 2.4646951146678475e-14 |

预设接受容差为 `5e-10`。这些结果表明独立数值方法相符；它们不是外向舍入误差包络，也不是连续扩散过程的严格首达证书。

## 3. Generator 已有内生 reset

每个 fit 的三个 drive generator 均含正的边界到内部跃迁率，而且等于 checkpoint 中的 `physical.recovery_rate`。两个参考边界之间没有直接跃迁。核验到的边界到内部总 rate 如下；最后几位因求和舍入存在约 1e-16 差异。

| Fit | 总 reset rate（约值） |
| --- | ---: |
| 11 | 1.0206028990286777 |
| 23 | 0.9995530818159507 |
| 37 | 1.0019572555243250 |
| 53 | 0.9769351608211666 |
| 71 | 1.0115409260553012 |

所以“现有 renewal generator 没有 reset”不符合实际文件。诊断中的 stopped generator 只为计算首次事件而将事件状态吸收，并不是对部署模型权重的修改。

原始初始质量全部位于内部，故原过程具有计数恒等式：

\[
E[N_{entry}(t)]-E[N_{reset}(t)]=P(X_t\text{ 位于参考边界}).
\]

在 tick 6 的 320 worlds 均值中，expected entries 为 `0.6833476606563276`，expected reset departures 为 `0.44071239972323556`，边界 occupancy 为 `0.242635260933094`。其差与 occupancy 相符。累计 entry count 比首次 either-boundary 概率 `0.6010773406942712` 多 `0.08227031996205629`；因此 entry count、首次命中概率和终点 occupancy 是三个不同量。

## 4. Endpoint、严格首达和双通道语义

原始 `NumpyPolicy.represent` 的 9 个 bank 值按三个未来时刻、三个阈值构成，计算 `P(coordinate(X_T)>K)`。本次初始状态对应 horizons 1、2、6。全部 2880 个条件中，它与同 generator 下的 `P(τ_K≤T)` 差异超过预设描述阈值 `2e-8`。

例如 tick 6、K=0 的跨 320 world 均值，endpoint 为 `0.49506464585775756`，strict first-hit 为 `0.8880236537283983`，差为 `0.39295900787064064`。该差不是新模型准确率改善，也不是证明应该把终点任务的预测直接换成首达预测；原始任务是 fixed-deadline target，目标事件必须先匹配。

### 初始命中不可忽略

在 320 worlds × 3 thresholds 的 960 个初始事件定义中，初始命中质量分布为：

| 初始命中质量 | world × threshold 条件数 |
| --- | ---: |
| 0 | 219 |
| 0.5 | 522 |
| 1 | 219 |

因此上面的较大 endpoint/first-hit 差同时受到初始命中、后来跨越及后续离开事件集的影响，不能全部归因于边界 reset。要估计“从当前未命中状态开始”的条件首达，必须另立条件化契约；该条件化不是本次实验定义。

### Endpoint 双侧分区必须包含等号质量

有限网格在阈值处可以有正质量：

\[
P(X_T>K)+P(X_T<K)+P(X_T=K)=1.
\]

因此严格 upper endpoint 的补是 `≤K`。tick 6、K=0 的平均 equality mass 为 `0.041023770833517215`。如果把双通道都定义成严格不等号，再强制两者和为 1，会改变本次有限状态模型的事件契约。不能由此直接推断连续真实变量也有同样大小的阈值原子。

### 两侧 first-exit cause 需要第三个存活量

`first_lower` 和 `first_upper` 是同一个 competing-risk 事件中的互斥首因：

\[
P(\text{lower first by }T)+P(\text{upper first by }T)+P(\text{neither by }T)=1.
\]

tick 6 的三个均值分别为 `0.29028450082877316`、`0.3107928398654981`、`0.3989226593057251`。两种首因通道之和不是 1。它们也不同于在允许 reset 的原过程中分别问“是否曾经到达下界”和“是否曾经到达上界”；后两个事件可能同时成立。

## 5. REPAIR 对照：局部表示相同，网络输出与未来动作不同

审阅从原始任务源码和原始策略源码的独立命名空间选取定义，在全部 320 个 public world 构造首次 READ 失败状态。每个 public 的 failure probability 均大于零，因此该条件状态可达。WAIT 与 REPAIR 均从同一状态推进相同一个 tick，使用相同 history；对照并没有执行新的未来观测。

| 同 tick 对照核验 | world 数 |
| --- | ---: |
| latent mass 逐元素完全相同 | 320 / 320 |
| 9-bank 逐元素完全相同 | 320 / 320 |
| REPAIR 后 READ 重新合法，而 WAIT 后仍不合法 | 320 / 320 |
| 原模型预测 Q 至少有一项不同 | 320 / 320 |
| 原模型预测 belief 不同 | 320 / 320 |

状态变化严格是 `broken` 与 `charges`，费用差等于 `repair_price`；公共特征只改变对应的 indices 3 和 4。原始预测头输入包含公共特征，所以即使 latent mass 和 bank 相同，Q 和 belief 仍可立即不同。这里“不同”是数值不相等的计数，并未评价差异大小、校准、方向或收益。

REPAIR 可恢复后续采样机会；不同政策随后可生成不同 history，从而改变未来 posterior mass、bank 和价值。故本实验支持“REPAIR 没有 commanded latent reset”，不支持“REPAIR 对完整模型或完整未来无效”。已有 generator 的内生 reset 与传感器 REPAIR 是两个独立机制。

## 6. 失败尝试、成本与保存状态

| Reviewer 尝试 | 结果 | whole-child CPU 秒 | wall 秒 |
| --- | --- | ---: | ---: |
| r1 | reviewer loader 合并 task/deployment 命名空间，SCHEMA 被覆盖；在构造状态时报错 | 0.701608 | 0.71661454200148 |
| r2 | 分离原始命名空间后复算；最终 exclusive-write 遇到已存在 REVIEW.json，报告未成功保存 | 1.101085 | 1.120486448999145 |
| r3 | 与 r2 相同数值检查，仅最终输出路径改为独占目录；成功 | 1.084101 | 1.1190233220004302 |
| 总计 | 含失败尝试 | 2.886794 | 2.956124313001055 |

r3 whole-child peak RSS 为 `69963776` bytes。r1/r2/r3 的脚本、预设和进程日志均保留；未修改生产者冻结源文件或结果。r1 是审阅器命名空间错误，并非被审模型错误；r2 stderr 仅报告保存时的 FileExistsError，不能把无报告的 r2 计成一次成功验证。r3 才是可引用的完整成功报告。

这些计时包括 Python imports 和结果写入，不包括 agent/editing、历史训练、生产运行、功耗或模型服务成本，也不构成与梯度训练的端到端效率对比。生产者本身记录的 CPU 时间不应再与其内部 phase 时间重复相加。

## 7. 对 WSP 参数修改的可落实约束

本轮没有发现需要修改冻结诊断实现的数值缺陷。发现的是必须在参数语义图中明确的边界。后续 WSP patch intent 应绑定当前 checkpoint/schema、目标事件、时间索引、strict/non-strict inequality、初始事件处理、endogenous reset 与 action reset 的区分，以及 target-contract digest。只凭 `renewal`、`Call/Put` 或 `REPAIR` 名称不能证明张量的语义。

只有当目标契约确实要求首达或路径事件、而当前可观测表示又不足以提供它时，才有理由增补相应事件状态或解析通道。增补后仍需冻结任务级价值验证、合法行动检查和资源一致的训练对照。本次数据仅来自旧 TRAIN schedules，无法作为独立泛化证据；没有以任何方式改善或替换真实生产权重。
