# Joint / R2 本轮实现与实验状态

本轮完成真实训练权重的原生重放和原 PyTorch 数值对照、一次真实 tiny-sd 参数更新与冷装载、原 transition 接口上的 action-value SGD、greedy 的原 runner 接通，以及既有 R2 候选协议的完整归档。**完整 R2 四臂确认性实验尚未启动，六个科学准入条件仍开放，没有模型晋级或质量收益结论。**

## 可审阅的提交线

| 交付 | PR | 固定执行/实现身份 |
| --- | --- | --- |
| 历史训练后继的原生 Joint 重放与原 Torch oracle | [#4943](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4943)，基于 #4929 | native 内核 `7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75`；证据 `b0f8eb831dd2dad9e3615823fefdda60321f5f8c` |
| 真实 tiny-sd 开发训练/冷装载 | [#4939](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4939)，基于 #4857 | 执行依赖闭包 `fdbbfdbe582b2de80077236c8f2f0ab8fcbe76c3`；原证据 `47f6729e7efad14f631c1aa2dc04db2be0501283` |
| C action-value 与 D greedy | [#4949](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4949)，基于 #4939 | C `7044eac0f5132f894da2de93158f9bf07c86e8ad`；D `f62034b45ca30573f17caa830ed21c9c641455ad`；完整证据 `bf6571d118b4d5750d13fc46c734faa351631669` |
| 原 R2 候选协议/统计/准入工具 | [#4951](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4951)，基于 #4949 | 原样归档 `5ab254a56830a160fe6c21ed65ddb88b48e2c852`；此后集成保留其41文件原字节 |

上游 A recorder/observer 在本轮中并发发布为 #4857 的 `68564f6fd8414ba5452ad6c6bf37d7cc41c767e8`。五个 A blob 与我们复用、测试的版本完全一致，已通过非破坏性 merge 接回上游；没有重新制作另一条 recorder 路径。以上身份区分产品内核、执行依赖闭包、测试源和证据提交，不等于整棵最新仓库都已执行。

## 实际结果与边界

### 原生 Joint

复用实际历史训练后继 checkpoint，67 tensors、596,985 parameters，历史收据为16次 optimizer updates，本轮没有重新训练。接受的 replay-r3 有48次真实 native子进程调用、40次成功proposal、8次预期拒绝和64项检查；两种 sampler 的同状态/种子/动作重复，前缀和fresh-process恢复字节一致。

独立原历史 PyTorch 模型比较20个真实 helper状态、每状态16组张量，分别对照FP64与FP32；最大绝对误差3.9968028886505635e-15与7.407944591086846e-7，低于事前门槛1e-9与5e-5。mean模式四模态载荷及早期提交音频前缀逐字节一致。原 checkpoint严格加载和原 exporter重导出也保持weights/public身份。

这仍是历史小型机制输入，不是自然四模态质量证据。原 selected parent checkpoint字节、optimizer resume、实际Agentd取消/durable owner adoption仍未资格；Torch与SplitMix的随机采样律不同，未建立随机媒体跨实现同seed位级等价。详见[固定原生证据](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b0f8eb831dd2dad9e3615823fefdda60321f5f8c/qualification/neuron-generation-bridge/TRAINED-REPLAY.md)。

### 真实生成器开发更新

在ai395上以旧R1 bee图片运行一次真实tiny-sd开发fit：CPU FP32、一项固定噪声/时间步计划、一次SGD，只更新UNet conv_out的两个tensor，共11,524参数。其余356个UNet、248个VAE、196个文本编码器状态项不变。新进程冷加载后，实际batch和noise prediction hash完全一致，真实pipeline完成12 diffusion steps并输出256×256 RGB PNG。

这是实际图像生成器更新与加载机制。它不构成新来源训练、自然语言生成器训练、完整joint fit或语义质量提升。checkpoint、delta、optimizer/RNG与原始PNG均在[SD证据](../sd_development_20261106/README.md)。

### C 与 D 的实际开发路径

C以原公开before-view、实际动作和声明标签训练143维线性action value，保存真实SGD/momentum状态，冷加载要求checkpoint与完成FIT的双外部摘要。A+C同进程36项控制通过；独立修复了FIT状态重绑、数值溢出缺终态、超时动作获得正标签及终态写入取消逃逸四类问题，原失败记录均保留。

D把C接到原choose(View)。六项集成控制与四项独立probe通过。600-update合成fixture的新进程canary执行draft→text→stop，18次预测，runner为delivered但语义评价仍pending；独立复用160-update fixture执行perceive→text→draft→verify，22次预测后为incomplete。两份不同结果均保留，没有为消除未完成结果而补跑或改标签。

所有未知动作评分仍为null；缺完整合法动作覆盖时显式STOP。C目标已经净扣历史controller/action费用，D不再扣第二遍。加载、所有评分和trace写入由原runner记费，内部诊断时段不重复相加。中断导致缺失磁盘trace时，不把内存行冒称durable evidence。详见[C证据](../action_value_development_20261106/README.md)与[D证据](../greedy_development_20261106/README.md)。这两段使用合成标签/后端验证机制，没有真实独立评价的控制器fit或强greedy资格。

## 成本：已测边界分别保留

| 执行 | Wall秒 | CPU秒与范围 |
| --- | ---: | --- |
| Joint replay-r3 | 8.814469289 | child6.638179 + harness2.199150271 |
| 原Torch oracle完整观察进程包络 | 7.447762378 | 含已等待子孙9.383129 |
| tiny-sd fit完整子进程 | 10.581983571 | 11.459588 |
| tiny-sd冷加载及12-step生成完整子进程 | 20.601632982 | 32.325550 |
| A+C组合36项验证 | 1.613524754 | 含已等待后代5.081776 |
| D六项验证区间 | 3.045380354 | current2.716937743 + child1.547164 |
| D独审四项区间 | 0.444830083 | current0.155362431 + child1.033761 |

各行对应不同测试边界，不是性能排名，也不是完整研发总成本。父/子包络与其内部阶段不能重复计费。早期失败/修复、构建、归档及协议搬迁成本在各原收据中另列；缺完整包络的尝试保留未知。能耗、物理I/O、部分历史训练/初始安装/编写/发布成本尚未完整测量。1000/10000/100000请求的原摊销窗口未改写，未通过增加部署次数制造收益。

## 协议状态与剩余条件

[候选协议README](../r2_protocol_candidate_20261106/README.md)及[逐项覆盖表](../r2_protocol_candidate_20261106/REQUIREMENTS_COVERAGE.md)原样保留。该README中D仍在审阅的描述是归档时点状态；本文件补充之后完成的限定开发证据，不修改旧合同或原41文件manifest。

原主比较仍为CE11−CE01；另报告CE11−CE00等七项对比。先分别计算每臂gamma=2 CE，再作差；配对只用于估计/重采样，不能改成CE(R11−R00)。32 fit seeds、每来源2 draw、99,999 crossed bootstrap与七项Bonferroni区间属于计划和算术。原17项控制/scalar审阅已保留，搬迁仅重跑两个CLI：compile生成128条全部NOT_RUN，readiness以exit2拒绝六个开放条件。

| 条件 | 当前缺少的真实材料 |
| --- | --- |
| NEW_DATA | 新采集、来源簇隔离、相对旧cohort去重、固定split与许可/捕获链 |
| EVALUATOR_CUSTODY | 实际独立评价身份、标签、访问拒绝证据和盲评调度 |
| REAL_TRAINER | 控制器/生成器完整fit组合、真实开发标签及四臂训练流程 |
| BUDGET_AND_BASELINES | 数值总预算、实际service mapping、强基线实现/训练/选择；当前总量仍null |
| QUALITY_AND_POWER | 真实评价校准、功效输入/模拟、最终N与固定底线；0.02 MDE/0.8 power等仍是候选 |
| CANDIDATE_IDENTITY | 完整新研究全部候选、未选/失败权重及最终固定fit结果roster |

用户要求的匹配actor–critic、等总预算简单生成、完整NDU、强planner/retrieval及四类匹配消融没有全部实现或资格。旧七列分析器不会自动覆盖这些新增条件；扩展必须事前形成新方法/比较族/预算/功效addendum。当前没有联合成功率、最弱模态质量、p95/p99、旧任务保持、未见来源泛化或CE增益的确认性结果，也未推进自然音视频和规模扩展。

所有PR保持draft；本轮局部机制验证不等于全仓CI通过，不替代既有产品采用与生命周期资格。
