# Digital cell follow-up status — 2026-11-01

本轮实现、训练、确认、独立审计和证据均已提交；**核心任务收益与完整成本采用门仍未闭合。** 未通过不是零效应、等效或显著负效应的证明。

| 工作线 | 本轮实际证据 | 严格结论 | 交付 |
| --- | --- | --- | --- |
| 连续首达与多次复位 | 45项数值检查；独立killed PDE最大误差1.31e-5；40新世界、80实际任务episode及505同进程边界后缀重放 | 在声明参数域内的数值参考与任务适配通过；采用显式continuous truncated reset，不能替换旧folded-bin核的既有资格 | [PR #4580](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4580) |
| 价值控制修复 | 5 fit、25最终模型、额外6000更新；400新确认世界、10000episode、54282动作独立核验 | 14主比较0通过；IID五族value均低于自身修复后fixed。FPT−ordinary bank的value差为IID −0.0622875、OOD −0.03405，调整区间均跨零 | [PR #4591](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4591)、[完整报告](CONTROL_RESULTS.md) |
| Rust执行与ACK恢复 | 125配对episode、390CLI调用、57 pending冷进程恢复；分数误差≤4.72e-16；178测试通过、1继承忽略 | exact原始fixture与来源绑定的一致性通过；原just test因缺cargo-nextest仍失败。仍用旧17状态表，非连续核Rust资格 | [PR #4582](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4582) |
| 连续cell冷进程边界恢复 | V1全505进程有16个路径回执失配；修复保持原相对路径，V2重新505/505严格通过，独立审计通过 | 完成动作后的Linux新解释器恢复通过；不覆盖mid-action、断电、撕裂快照、外部exactly-once或Rust ACK | [PR #4592](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4592) |

两类505的覆盖不同：PR #4580在同一进程中检查JSON后缀恢复；PR #4592每个边界启动新的Python解释器。它们均来自80个原始任务episode，不能算作新的独立收益样本。

确认真实发生17104次到期读取尝试，其中15063次成功解码、2041次失败；1617个唯一成功packet另由独立审计执行FullHX。400个新世界全部按冻结seed重新生成，2903个实际文件逐字节相同，297个故意缺失packet状态正确。全部确认效用、费用、指标与14个调整区间重算误差为零。

修复只训练继承head，所有旧cell参数和转移／特征表均冻结。每族新增240更新，不能与旧240更新当成同训练预算；1700是名义参与目标的head坐标数，不能替代有效容量或信息匹配。连续数值参考及其冷进程结果不能解释本轮有限核的效用变化。

新训练完整进程CPU为113.681440秒，确认143.584502秒；内部stage计时包含于完整进程，不能重复相加。旧训练仍是warm-start前置成本。旧轮283.018CPU秒属于另一次模型字节相同的计时复现，不是原始训练完整计时。本轮独立审计、Rust构建、资格、归档等另有成本。连续cold V1+V2子进程CPU合计519.275087秒，失败版保留；不包含在上述训练／确认数字中。没有同成本加速、能耗节省或生产采用结论。

## 科学身份与封存顺序

| 身份 | 固定值 |
| --- | --- |
| 原始完整基线 | `012bcf3505cb9306d9cef094a1acc3ca34c978be` |
| 新拟合之前发布源码／协议 | `9cedb204b30eb62ec8d26ba5668fbe905e176b9a` |
| 新确认之前发布25模型及全部训练原始记录 | `bd8e8a4ff5adf63d7a246d4aaba04491f7ddd39d` |
| 连续task adapter在采样前发布 | `2b4345b80c1c2773e961915522df32c77675685e` |
| 冷进程V1在执行前发布 | `56fb94039bea79b72b059c639b61d1f7bbb0b2be` |
| 冷进程V2在完整重跑前发布 | `866ecf9872c968db55bc12ccf63826b7651c5918` |
| 最终Rust来源digest | `7c897bdfafdf33568f41ec7a0733956cfe17af13284ef0fcf9662e5ff6122b21` |

训练完整原始归档11600170bytes／3384文件，确认原始归档13208053bytes／3155文件；均用有序分片保存，索引含整体SHA256与每片Git blob身份。模型原始MODEL_FREEZE在训练归档内，不能编辑后冒用本轮身份。参见本分支[evidence/CONTROL_TRAINING_ARCHIVE.json](evidence/CONTROL_TRAINING_ARCHIVE.json)、[确认索引](evidence/CONTROL_CONFIRMATION_ARCHIVE.json)、[独立全量审计](evidence/independent_confirmation_audit.json)和[输入身份](evidence/input_manifest.json)。安全恢复命令见[控制报告](CONTROL_RESULTS.md)。

其余分支的归档同样按其index的parts列表顺序重组，核对bytes与SHA256之后再解包并校验成员。Rust以`evidence/NATIVE_ARCHIVES.json`中exact-fixture为最终资格，两份较早配置仅作development记录；连续cold以`evidence/CONTINUOUS_COLD_ARCHIVES.json`的V2为最终资格，V1是保留的失败。

[远端范围审计](evidence/REMOTE_SCOPE_VERIFICATION.json)在记录的四个head逐级核对root/tools/hcsn，所有既有目录的SHA、类型和mode均不变，唯一新增namespace为`tools/hcsn/digital_read_followup_20261101`。后续结果也只写入该namespace。生产授权与激活没有改变。

## 仍未闭合

连续核进入端到端训练后的完整梯度和收益；相同控制下的独立核心贡献；有效容量、完整资源和质量共同匹配后的采用门；移动／自由边界、GPU／能耗及生产资格。当前结果不支持宣布全部blocker闭合。
