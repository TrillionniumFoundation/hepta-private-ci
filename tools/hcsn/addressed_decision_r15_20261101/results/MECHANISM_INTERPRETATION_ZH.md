# R15 补充确认：机制动作计数与解释

本报告只读分析 `run_02` 的 16 个原始确认文件；不改训练、控制器、冻结源码或主要统计，不新增确认对象。原始文件 SHA-256、逐 fit 计数及动作转移表见 [MECHANISM_ACTION_COUNTS.json](MECHANISM_ACTION_COUNTS.json)。

每域分母为 **8 fits × 128 episodes × 6 queries = 6144 queries**。表格单元依次为“首动作不同 / 完整动作序列不同 / 最终答案不同”的次数；完整序列包含隐式 STOP。独立统计单位仍为 8 个 fit，不能把 6144 条查询当作独立样本计算显著性。

## 1. D 与其他执行臂

| 对照（左臂均为 D） | IID：首 / 序 / 答 | OOD：首 / 序 / 答 |
| --- | ---: | ---: |
| 同矩阵 HMM | 0 / 0 / 0 | 0 / 0 / 0 |
| factorized | 11 / 11 / 1 | 32 / 32 / 1 |
| memoryless | 9 / 9 / 1 | 29 / 29 / 5 |
| free CTMC | 75 / 76 / 5 | 124 / 125 / 17 |
| learned：state/confidence | 2111 / 2111 / 173 | 2460 / 2460 / 216 |
| learned：STOP value | 2114 / 2114 / 175 | 2459 / 2459 / 217 |
| learned：value+risk | 2114 / 2114 / 174 | 2474 / 2474 / 217 |
| learned：ordinary dual | 2116 / 2116 / 174 | 2467 / 2467 / 217 |

同矩阵 HMM 与 D 的完整 query 字典也逐项相同，两域均为零差。这个有限模型可由普通 CTMC/HMM 实现；无法据此提出 HX 独有的推断算子收益。

factorized、memoryless 产生了少量实际动作差，但最终答案差很少；free CTMC 的动作差较多。动作改变本身不等于净效用改善。[SUMMARY.json](SUMMARY.json) 中这三个机制对照的效用 t95 区间都跨零，主要质量增益准入也未通过。

D 使用三步有限期限控制，四个 learned 策略只在 query 起点选择一次 READ/REFRESH 后 STOP。因此 D 与 learned 的差异同时包含控制范围差异，不能归因于某个特征通道。

## 2. 四种 learned 特征之间

| 两个 learned 臂 | IID：首 / 序 / 答 | OOD：首 / 序 / 答 |
| --- | ---: | ---: |
| state/confidence vs STOP value | 15 / 15 / 2 | 17 / 17 / 1 |
| state/confidence vs value+risk | 39 / 39 / 3 | 82 / 82 / 7 |
| state/confidence vs ordinary dual | 11 / 11 / 1 | 38 / 38 / 1 |
| STOP value vs value+risk | 24 / 24 / 1 | 93 / 93 / 8 |
| STOP value vs ordinary dual | 14 / 14 / 1 | 35 / 35 / 2 |
| value+risk vs ordinary dual | 38 / 38 / 2 | 84 / 84 / 8 |

这里的 STOP value 是终点正确率预测，不是原金融股权价值；risk 是自然首达概率。value+risk 相对 STOP value 改变 24/93 个首动作，相对普通双特征改变 38/84 个首动作，仍不足以证明稳定净收益。特征受共同训练与参数化影响，应按原预登记视为描述性敏感性。

## 3. 哪些结论成立，哪些仍未成立

**轨迹可能分叉。** 首动作、观察时刻或 token 不同后，后续 query 的历史可能不同。上述全部计数是实际成对轨迹的描述，不能统一解释为同一个 prefix 上的局部因果效应。作为定位信息，D/factorized 在记录的先前动作—观察历史仍相同的 query 上，IID/OOD 首动作差为 11/30；D/memoryless 为 9/26。这些记录适合下一轮重放，但没有证明两个当前 belief 仍有相同边缘。

**三个分布证据回答不同问题。** [decision_probe.json](decision_probe.json) 找到同 phase/content 边缘的 synthetic joint，最优动作分别为 STOP 与 READ；这证明受控有限模型中可以出现这样的决策差。另一个固定真实历史开发探针用了 16 episodes、768 格点，未找到 full posterior 与即时 factorized 投影的动作差。当前补充确认在持续传播/持续投影、拟合参数及不同部署历史上发现少量差异，与该有限探针的阴性结果不矛盾。不能把 synthetic belief 直接称为可达后验，也不能把 768 次未找到概括为所有可达历史都无作用。

**mean 失效不能算作收益。** IID 的 1024 个 mean episode 完成；OOD 有 1008 个完成、16 个 `invalid_support`。index-mean 压缩会删除 recovery 支持，使真实 READ erasure 的模型概率为零。按补充协议，两域 mean 性能及 D−mean 都为 null；本报告也不对成功子集计算动作或性能对照。

## 4. 下一轮最有判别力的设计

1. **先取得可达、同边缘、不同 joint 的公开历史对。** 从当前首个动作分叉的原始 prefix 重放出发，寻找预先容差内边缘匹配的历史；不能在滤波后直接修改 belief 冒称可达。更严格的受控检验可预登记两个运输构造的 p₊、p₋，以 p₀=(p₊+p₋)/2 为 owner 初始联合分布，向所有核心提供同一个真实二元观测，其发射为 E(±|z)=p±(z)/(2p₀(z))。观测发生后，Bayes 后验才真正达到 p₊ 或 p₋。这只是一项受控机制实验；应使用预先固定的参数族和独立新对象，不能把为数学见证设计的传感器当作真实语义能力。

2. **把压缩改成支持保持的明确模型。** 保留 active/recovery 总质量，及两组各自的 content 条件分布；组内再压缩 phase 形状或保留有限 age 分量。这样不靠 epsilon 补洞。先验证传播、公开 WRITE 和 Bayes 更新以后，所有合法可观察事件仍有正确的支持，再比较完整 joint、块条件分布与原 factorized 的成本收益。不得用已失效的 index-mean 作为主要弱对照。

3. **同一个完整控制器下比较强普通核心。** 保留完全同矩阵 HMM 作为数值等价基线，以自由率 CTMC 和充分训练的普通 recurrent/SSM 作为可实施候选；共享可用观察、动作、规划深度、真实后继和完整候选成本。先在相同公开 prefix 上执行配对 READ/WAIT/REFRESH/STOP 后续，再在全轨迹上检验净效用。新确认应对上述压缩和真实内容保持的收益作独立检验，不能用控制器本身的 B−A 增益代替 D−B。

本轮的结论是：联合状态确实可以影响决策，补充确认中也有少量实际动作差；当前证据尚未把这种差异转化为强普通对照下的稳定解析核心净收益。
