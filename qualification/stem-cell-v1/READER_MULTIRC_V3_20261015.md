# MultiRC Reader V3 实验交接（2026-10-15）

本轮已运行真实 Granite97 共享句子特征、问题及候选条件化 Reader、单独冻结的学习型 verifier、冻结 critic，以及在下一步计算前执行的原生 Q32 NDU 控制。独立复核直接重读官方标签，保留每个完整问题的全部候选。最终集是预先选定的官方 validation 子集，不能称为官方 test 成绩；未查询或使用 CI 状态。

三个种子反复评估同一组 747 个候选、152 个问题、16 个段落。合并后的 2241 条答案观察与 456 次问题试验是模型种子的重复测量，不是新增独立测试项；跨段落泛化的支持仍只有 16 个段落。

表中 static 使用相同 hidden=48 的 Reader 架构、按一步深度训练；不是上一轮的 3152 参数轻量 Head。one_step 使用按三跳训练的 core，仅执行一步。除 no_verifier 外，所有 arm 均支付学习型 verifier 的实际调用成本，包括末步；no_verifier 是执行三步的推理消融。因此 static 不代表可能的最廉价无 verifier 纯 Head，也不构成全局 CPU 最优下界。

仅训练数据上的可拟合性门槛完成 1000 步：F1a=0.956522，问题 EM=0.875000；这说明小训练集可拟合，不证明留出泛化。主实验各 seed 的 Reader/core/query-only/verifier 均完成 512 步。

| Seed | Arm | F1a | 问题 EM | 实际步数 | 父进程在线 CPU 秒 | 总在线 CPU 秒 |
|---:|---|---:|---:|---:|---:|---:|
| 41 | static | 0.431159 | 0.032895 | 747 | 9.126761 | 9.126761 |
| 41 | one_step | 0.513644 | 0.032895 | 747 | 9.280457 | 9.280457 |
| 41 | fixed | 0.512156 | 0.039474 | 2241 | 24.862728 | 24.862728 |
| 41 | adaptive | 0.506494 | 0.039474 | 1172 | 14.937398 | 14.937398 |
| 41 | native_ndu | 0.513644 | 0.032895 | 747 | 33.404949 | 34.195444 |
| 41 | no_verifier | 0.510569 | 0.039474 | 2241 | 14.584789 | 14.584789 |
| 41 | reset_state | 0.514469 | 0.032895 | 2241 | 24.854599 | 24.854599 |
| 41 | query_only | 0.478185 | 0.039474 | 2241 | 23.955160 | 23.955160 |
| 47 | static | 0.388778 | 0.039474 | 747 | 10.028753 | 10.028753 |
| 47 | one_step | 0.405204 | 0.032895 | 747 | 10.193116 | 10.193116 |
| 47 | fixed | 0.399254 | 0.032895 | 2241 | 26.017156 | 26.017156 |
| 47 | adaptive | 0.405204 | 0.032895 | 999 | 14.484465 | 14.484465 |
| 47 | native_ndu | 0.405204 | 0.032895 | 747 | 34.948769 | 35.748753 |
| 47 | no_verifier | 0.399254 | 0.032895 | 2241 | 14.682568 | 14.682568 |
| 47 | reset_state | 0.405204 | 0.032895 | 2241 | 25.763246 | 25.763246 |
| 47 | query_only | 0.333333 | 0.046053 | 2241 | 25.610601 | 25.610601 |
| 53 | static | 0.364008 | 0.032895 | 747 | 11.008231 | 11.008231 |
| 53 | one_step | 0.459016 | 0.026316 | 747 | 9.956789 | 9.956789 |
| 53 | fixed | 0.454395 | 0.026316 | 2241 | 25.770208 | 25.770208 |
| 53 | adaptive | 0.454395 | 0.026316 | 1449 | 19.436900 | 19.436900 |
| 53 | native_ndu | 0.459016 | 0.026316 | 747 | 32.116249 | 32.850542 |
| 53 | no_verifier | 0.452145 | 0.026316 | 2241 | 14.537436 | 14.537436 |
| 53 | reset_state | 0.456486 | 0.026316 | 2241 | 26.379280 | 26.379280 |
| 53 | query_only | 0.447653 | 0.032895 | 2241 | 26.049853 | 26.049853 |

合并三个种子的全证据结果：static F1a=0.396104/EM=0.035088；one_step F1a=0.461886/EM=0.030702；fixed F1a=0.457859/EM=0.032895；adaptive F1a=0.457598/EM=0.032895；native_ndu F1a=0.461886/EM=0.030702；no_verifier F1a=0.456460/EM=0.032895；reset_state F1a=0.461278/EM=0.030702；query_only F1a=0.425425/EM=0.039474。
同一面板 all-positive 基线 F1a=0.603738/EM=0.000000；逐种子的 all-negative 与训练多数类基线保留在原始报告。

固定 Reader 的全证据相对删除证据，合并 F1a 差值 +0.000424、问题 EM 差值 +0.004386；种子方向或指标结论未呈一致改善，尚未建立稳定的证据收益。

证据干预检查：seed 41 固定模型删除证据后预测变化 7 条，F1a 差值 -0.002314，query-only 跨 cohort 预测一致=True；seed 47 固定模型删除证据后预测变化 19 条，F1a 差值 0.002222，query-only 跨 cohort 预测一致=True；seed 53 固定模型删除证据后预测变化 2 条，F1a 差值 0.001816，query-only 跨 cohort 预测一致=True。单模型删除证据对照与另行训练的 query-only 对照分别报告，不能据此直接证明语义推理因果机制。

同一冻结 core 的一步与固定深度终点配对诊断：seed 41 首步错→末步对 4、首步对→末步错 2、终点预测改变 6、native NDU 相对一步预测改变 0；seed 47 首步错→末步对 2、首步对→末步错 4、终点预测改变 6、native NDU 相对一步预测改变 0；seed 53 首步错→末步对 5、首步对→末步错 4、终点预测改变 9、native NDU 相对一步预测改变 0。这些是最终标签参与的事后描述，未用于策略选择；终点同时改变计算深度及 verifier 反馈，只揭示本子集的任务级机会，不是可在线使用的 oracle 或一般因果结论。

学习型 verifier 的接受表示模型一致性和置信度，不是语义真值。NDU 优化候选正确率 surrogate，未直接优化非加性的 F1a/问题 EM。原生控制现在实际位于在线下一步决策之前，但仍未集成生产 NDU owner；最初五测试验证与本轮实际二进制的构建收据分别绑定。

no_verifier 是同一个已用冻结 verifier 反馈训练的 core 在推理阶段关闭 verifier 的消融，并非重新训练的无 verifier 模型；query_only 则是单独训练的零证据对照。原生控制使用概率为 1 的单一经验情景与保守 critic 包络，不是一般随机 FBSDE 求解器；停止计算本身不证明产生了推理能力。

主实验采用的规范特征缓存，原始 Encoder 加载已实际计量：CPU 3.425771 秒、墙钟 3.426151 秒；本轮恢复缓存时再次加载也独立计量。两项真实加载收据均保留，不把此前开发缓存的未知加载成本套用于规范主实验缓存。

线上父进程 CPU 与原生子进程 CPU 分列；总 CPU 只有在子进程计量完整时求和。墙钟已经包含原生等待，不重复加子进程墙钟。这些线上时间排除 Reader 训练、critic 拟合及共享 Encoder 摊销；共享物理特征增量成本按实际最终调用单独分配。原生和 Encoder 的未知算术覆盖保持 null，未把预算上限当成实际工作，未建立严格等计算量优势。

线上 CPU 和墙钟包含当前严格算子计量、收据与哈希检查的仪器开销，是本机原型的实际端到端测量；不是去仪器后的 kernel 延迟，也不是目标生产环境的延迟认证。

八个 arm 在预注册实际消耗区间内的共同匹配样本数：seed 41 cpu_ns=0/747，排除={"different_bin": 747, "incomplete_cost": 0, "invalid_execution": 0, "missing_arm": 0, "outside_support": 0}；seed 41 formula_flops=0/747，排除={"different_bin": 258, "incomplete_cost": 489, "invalid_execution": 0, "missing_arm": 0, "outside_support": 0}；seed 47 cpu_ns=0/747，排除={"different_bin": 747, "incomplete_cost": 0, "invalid_execution": 0, "missing_arm": 0, "outside_support": 0}；seed 47 formula_flops=0/747，排除={"different_bin": 287, "incomplete_cost": 460, "invalid_execution": 0, "missing_arm": 0, "outside_support": 0}；seed 53 cpu_ns=0/747，排除={"different_bin": 747, "incomplete_cost": 0, "invalid_execution": 0, "missing_arm": 0, "outside_support": 0}；seed 53 formula_flops=0/747，排除={"different_bin": 305, "incomplete_cost": 442, "invalid_execution": 0, "missing_arm": 0, "outside_support": 0}。共同区间匹配为零时无法形成全八 arm 的实际预算匹配比较；即使存在共同区间，区间匹配也不等同精确相等的工作量，不能报告严格预算比较通过。

permuted 只检验集合排列稳定性，不能解释为顺序推理能力。旧 gate 与 696 行开发 smoke 置于 development，未进入主结果汇总。388 项测试通过；全部原始协议、标签复核、训练记录、构建日志与 source hashes 随包保存，排除源码副本、权重与特征张量。

仓库格式化执行成功且未改工作树；仓库范围的 scoped just test 因稀疏检出缺失 aws-auth/Cargo.toml 而无法启动，不能计为项目级 Rust 通过。隔离原生控制器构建及 Clippy 的通过收据单独保留；这些本地验证不属于 CI 查询。

实现源码分阶段 PR：[#2275](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2275)、[#2276](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2276)、[#2277](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2277)、[#2278](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2278)、[#2279](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2279)、[#2280](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2280)、[#2281](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2281)、[#2282](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2282)。统一入口 [#2283](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2283)。

规范特征缓存仅交付原始 metadata 文件的 SHA256/字节数、预处理与向量摘要，以及逐文本和逐 case 绑定的哈希引用；完整段落、问题和候选文本不会在证据包中重复存放，完整本地缓存保持原状。

证据包 `hepta_reader_multirc_native_ndu_v3_evidence_20261015.zip`；SHA256 `1cfbf1a31ce30ba9182285ac07c65741830e8aed537e17a7ad190218164aa7b6`。包内 RAW_FILE_HASH_MANIFEST.json 逐项绑定原始文件。
