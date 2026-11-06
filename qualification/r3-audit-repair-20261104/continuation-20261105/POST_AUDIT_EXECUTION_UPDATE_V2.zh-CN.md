# 审计发布后的执行增量 V2

**当前结论仍为16项限定闭合、6项开放、1项科学保留；尚未满足全部 blocker 闭合。** 本增量在完整审计 `fc10fbef82ec8e1a7db511c06d865c147200f1fc` 和首轮追加 `9ad1f5902f3a2b0b2c712e718a39c2ad2a6c791f` 后，登记真实依赖产物、单一产品候选、完整Intel失败证据及新的并行项目观察。原23个退出条件不变，机器台账V8保留原字节；本增量没有新增闭合转换。

## 1. 单一产品候选已经实际发布

[Draft PR #4936](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4936) 于2026-11-06 07:27:25 UTC发布。

| 身份 | 实际值 |
|---|---|
| head | `2d1137b1ba39fab0e6a28bac8decc114dfa0138c` |
| 产品tree | `99a9c0cefa627290c9fc72a9ba90d0485020fe11` |
| first parent | `67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed` |
| additional parents，按实际顺序 | arg0 `3c9e2bba4e7e84616509d6320a9ae013a274532c`；Windows `18bbef4f61c6086f145bdb6f7acbf82127741a14`；PTY `8075eb367b6e97546af206b27bbf4a3a867497c8`；holdout `4a1410f332e4a34564feafbc4dcb2e808c7f6c5f` |
| target | `integration/ui-objective-20261103-product`，`63652be658ebed8d3052eb789b951793384fd5e4` |
| actual merge | `a0cb0f33661e199674012e3302b0602407c91a8d`，tree与head完全相同，parents精确为target/head |
| 默认main | fresh GET仍为 `732e934ba496d90fbe042b8d41d479ef901643e5` |
| 状态 | open Draft，maintainer_can_modify=false，mergeable=true；没有合入main |

本次提交相对67基线的差异严格为**230路径：3个Cargo/Bazel根文件、220个新vendor文件、7个既有修复文件**。10个原文件改变，另外10,572个原文件的模式和blob均不变；产品共10,802个叶。四个proposal工具文件完全排除，原workflow、deny规则和Bazel配置不变。独立组成复核另外重算全部1,617个tree节点，并核对367条原CI/scripts/BUILD/.bzl/deny/Bazel配置路径。

PR相对target显示1,561 changed files、102 commits；原#4797相同target下已有1,335 changed files、96 commits。这两个分母与本次相对first-parent的230路径分别保留，不能宣称整个PR只有230路径。四个修复donor作为真实parents保留；Windows donor直接parent是340源，但其完整tree相对67只有指定两叶差异。

纳入决定如下。所有独立支线的旧绿色结果保留原归属，不合并为新候选资格。

| 来源 | 纳入路径及用途 | 保留的接受边界 |
|---|---|---|
| #4931真实proposal | 3根文件+220vendor；移除活动依赖图中的pin-utils并同步两锁 | 生成/deny成功不能代替产品编译和原平台测试 |
| #4923 arg0 | 两个原fixture文件，移除被strict Clippy拒绝的expect写法 | 原断言保留；原GNU通过只属于该支线 |
| #4913 Windows | setup_error.rs与setup_main/win.rs，保全真实错误原因链和原formatter修正 | 不改变token/ACL，也未修复已证明的外部删除缺口 |
| #4927 PTY | unix_io.rs，在receiver关闭后避免无用分配/发送 | 原2秒/5秒、完整drain、child/FD断言保留；实际Intel失败原因仍UNKNOWN |
| #4933 holdout | 文件锁owning guard和三个duplicate-handle回归 | 明确尝试unlock再close；不承诺OS unlock永不失败，也不据Linux受控观察认定原Mac holder原因 |

完整组合、原patch在组合树上的正向/逆向index回放，以及实际commit/ref/PR/merge回读均已完成。组合独审接受的是组成关系。新holdout测试含一条带参数注释的106字符行，真实formatter仍须原CI验收，本机没有Rust工具链，不声称fmt或Rust测试通过。

## 2. Cargo与Bazel依赖阻塞已推进到真实、可整合的产物

[普通自动run42175704028](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42175704028) / job127753541837在head `ddacfba30b28e86eae9615d7063fff2c7941b1d4` 成功，attempt1；实际checkout是head，并未把同tree的merge误称执行源。官方artifact13482877841为2,232,775 B，SHA256 `9417426f75e0b56a2796782e8df49d0f1ea4992570dd1a85a04d826dcb041496`。全部41成员、21,038,943 B展开原件和1,512,530 B原job日志完整保留。

原15条命令全部exit0，包括两次实际Cargo生成、两次实际Bazel生成、原锁检查和原 `cargo +1.95.0 deny --locked --all-features check --config deny.toml`。原deny日志12,322,124 B，终态为advisories/bans/licenses/sources全部ok；原警告与ANSI字节仍保留，不写成“无警告”。原Bazelisk冷启动下载stderr独立保留，版本仍严格绑定Bazel9.3.0。生成器源、实际两轮相等守卫和独立全字段比较分别举证。

独立验证确认：

- Cargo从1,502包变为1,501包。变化只有四个相同版本的registry来源改为path、四条pin-utils边删除、唯一pin-utils0.1.1节点删除；其余1,497包及依赖顺序和全部其他字段相同。
- workspace完整metadata相同，仍为193个member；原aws-config维护补丁及其76个原叶保持。
- MODULE仅删除四个crate旧registry fact及pin-utils fact，新增四个path fact。其他全部JSON字段和保留fact的原字符串完全相同。
- 四个path fact逐字段匹配实际规范manifest，并依据锁定的rules_rs0.0.96官方源码核对版本、默认feature、optional、target/build和strip_prefix语义；不是只看两轮锁是否重复。
- 220个vendor文件从四份固定官方archive完整重建，含212个原成员及8个新增provenance；只有14个原成员作已审变换，其余字节、模式和许可证保持。活动workspace锁不含pin-utils；保留的上游历史嵌套Cargo.lock不冒充活动依赖图。
- Loom保留 `futures=["pin-utils"]`，以空 `pin-utils=[]` 保持旧feature名兼容；私有副本MSRV明确为1.68，工作区工具链为1.95.0。

产品专用实际tree为 `c7b9fb4e029dc38034a7dfce10a646ccde3e0bf6`。同一原patch在工具源及纯产品基线分别正反回放，223个postimage相同；219个不同产品blob均完成实际创建和完整GET。正式独审 `6e4b893e481623a1c56520b05550438e502131a9` 的决定为 `ACCEPT_ACTUAL_DUAL_LOCK_AND_223_PRODUCT_POSTIMAGES_FOR_INTEGRATION`，本范围剩余源码阻断为0。根另行重放，6,979 B输出与冻结原件逐字节相等。

本项形成了真实解决依赖advisory的产品输入，已进入#4936。B02/B15的原退出还包括该组合源自己的原CI全部通过，因此两项仍OPEN。[完整产物与独审登记](current-head-ci/pin-utils-proposal-4931-native-20261106/registry.actual.json)。

## 3. Intel v3失败证据完整收齐，产品失败未被收件结果覆盖

原[run42164663819](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42164663819) / job127718214088最终failure，source84cc的产品部分仍精确为67基线，执行的是head。官方ZIP13481118302为78,262,690 B，1,182成员、93,538,178 B展开内容；完整job日志、compact、源码清单和1,002个log/XML均保留。BEP保存的是collector产生的credential-sanitized / opaque-payload-omitted派生件，3项opaque payload被省略，raw BEP未保留；不能称为原始BEP全字节归档。

| 统计层 | 实际结果 |
|---|---|
| 501个唯一testResult attempt | 495 PASS、5 FAIL、1 TIMEOUT |
| 438个唯一testSummary | 433 PASS、1 FLAKY、4 FAIL |
| 控制台target终态 | 438执行，434通过（含最终flaky）、4失败，167跳过；总605 |
| PTY | 28P/3F，共31例 |
| HTTP | 84P/1F |
| grpc_notifications | 0P/4F |
| grpc_tcp | 0P/4F |
| Core | 8分片、10attempt：8P/1F/1TIMEOUT；原自动retry后两分片通过，summary为FLAKY |

PTY三项原失败分别保留：关闭receiver后的portable退出2.1319秒；保留FD的Python REPL就绪5.0029秒；大输入关闭stdin后的EOF收集5.5091秒。第一项观察到reader4002次调用、read=discard2,050,048 B、child未退；这些非原子观察不能单独证明因果。HTTP为errno35/WouldBlock；两个gRPC组保留约10秒原endpoint等待。Core原shard4有900秒timeout，shard5原断言失败；不能用retry PASS删去失败尝试，也不能将子进程的嵌套摘要与父摘要相加。

进程exit38、BEP BuildFinished TESTS_FAILED/3、collector exit1分别保留。原manifest complete=false且记录original_bazel_exit_mismatch。固定Bazel9.3.0源码说明后续BES上传失败可将原测试退出改为PUBLISH_ERROR；原日志也保留四次原上传重试。该解释区分退出阶段，**没有将测试失败改成成功，也没有豁免exit38或改写complete=false**。

compact中四个失败target各自的log/XML绑定成立；Core两次retry的XML helper仍记录初次XML摘要，不能声称retry XML都由该compact输出摘要证明。原scope中“TestRunner”辅助动作也不全是独立产品测试。

独立审阅 `a22832628b288af87b1f32d2db3141ff2fe19c4d` 接受上述范围的原失败证据，B21/B15保持OPEN。最终290路径由288个payload、registry自身和单独的registry.self.actual.json组成，包含原43成员包及263分片、完整恢复回执和中断历史；根在新目录恢复并重放，exit0、stderr0，内部16,908 B输出与原冻结结果全字节相同。[完整登记](reviews/b21-collector-v3-native-20261106/registry.actual.json)。

## 4. 新CI观察及环境恢复的准确边界

原主候选67的完整19runs/93jobs终态仍为68成功、9失败、10取消、6跳过；9失败中包含两个汇总门，不能计为9个独立根因。Windows格式源18的blocking终态为37jobs：26成功、7失败、4跳过，其中5个执行失败和2个汇总门；原repo-check/just fmt成功保持其源归属。

07:22:06 UTC最新有界读取中，PTY源8075的blocking为36jobs：26成功、5失败、1运行、4跳过；唯一运行仍是Intel job127729084043。holdout源4a的blocking为11jobs：4成功、1运行、6跳过；完整Bazel/repo-check/rust-ci/cargo-deny被既有scope规则跳过，不能据此授予全平台或formatter接受。

#4936初次完整head列表为18个workflows：16queued、2skipped。07:32:36 UTC的blocking42180997764完整jobs仍仅有3个queued：Select scope、Blob policy、Codespell。排队不算通过、失败或已执行。后续结果以新切点追加，初始原件不倒写。

07:37:14 UTC下一独立切点中，Codespell job127770341439已成功，scope与Blob policy仍queued。repo-checks、cargo-deny、rust-ci和Bazel依赖scope，尚未生成这些job不能算跳过或失败。该后续观察不改写07:32的原排队切点。

07:43:03 UTC再次完整读取同一head的18个run，结果为13queued、2in_progress、1success、2skipped；新成功项是Windows ordinary consumers，Windows private-state与Windows Bazel process-env正在执行。07:47:10 UTC blocking的第五个独立切点仍为Codespell成功、scope和Blob policy排队，尚无可归因的执行失败。队列等待不按job启动后的timeout预算判定失败，原记录逐次保留。

执行环境曾明确unavailable，随后新的环境恢复，主工作目录保留而/tmp丢失。没有通过取消或重跑CI处理这一故障。Cargo官方artifact重新取得后完整摘要相同；B21外包按保留原件精确重建，78,836,946 B/SHA256 `277c7def3759f2913ad0b9fa4dfe2975b06791bf4d7f48eb417ddc91c644fc35`、整个manifest和263分片均与中断前相同。

丢失的231份旧逐批工具raw返回不伪造；154个旧对象以新的fresh GET重新观察。当前340份工具返回通过无损模板和已登记payload引用完整恢复并逐字节核对，具体为62次新创建返回、277次成功完整GET和1次失败GET；它们是恢复后的新实际工具返回，不能称为旧返回重现。早先NOT_ACCEPTED和partial检查点保持原字节，新的完成记录在其后追加。

## 5. 并行项目发展方向的补充

07:06:59 UTC有界观察读取50个不同PR，其中38个在03:35:10后更新；搜索只返回36个，遗漏REST已见的#4797/#4884。完整03:31–03:43元数据普查仍为3,555开放PR、5,333分支；本增量不把这些数字当此刻实时总量。

实际#4855 head已为ef0cf55、相对正文旧1a2增加35commits/57paths；#4907也已有62e60b9后继，正文仍描述2f源。进度必须绑定实际ref/tree。新增Joint桥接明确分开proposal worker、durable control、Cell journal和ACK；V13验证器核实际checkpoint内容，但不授予质量或采用权。NDU作者的新NO_GO报告保持有限实验负结果，不能用工程测试数替代科学采用。[完整并行增量](reviews/post-audit-execution-v2-20261106/CONCURRENT_INCREMENT.zh-CN.md)。

总体方向保持：正常UI/API的真实目标，经受保护的Root/FinalUse进入有界Memory/Context，再由Agentd组织Codex和worker执行可观察、可取消、可恢复的真实效果。优先完成这一纵向闭环，再做规模、shadow对照、长期学习、更新/撤回和外部consumer。Cell/优化器/研究worker不能因新增内容hash或局部测试而自行获得authority。

## 6. 剩余工作的下一可验收门

| ID | 当前已推进到的位置 | 下一门与闭合证据 |
|---|---|---|
| B02 | 单一#4936、230路径、双锁、五parents和同tree merge已实得 | 该候选的原始必需CI全部通过；后继修补重新绑定最终head/base/merge |
| B11 | 原宿主误判已排除，真实strict/legacy外部删除缺口仍在；错误原因链已整合 | 在原允许边界内取得真实对象/操作授权机制和原攻击/权限/文件系统全验收；超边界设计须按原审批要求升级 |
| B15 | 原失败和实际依赖修复均留存，新的组合源已进入自动CI | 最新组合所有必需workflow终态成功、目标main重新核实、实际发布与merge同树；私有full门不得在没有新容量证据时启动 |
| B16 | Foundation及并行Root/Current源码有进展，真实正常UI/issuer/provider闭环仍未验收 | 同源真实Root/Session、原signed objective与provider/target完成任务、取消、丢ACK、重启，保物理效果/Memory/authority回执；原driver身份UNKNOWN不以第四次重放或新key掩盖 |
| B19 | 固定Hepta×Chain传输尺寸与双端源码已审，后继branch另有增量 | 精确external binary build来源、原paired native、兼容/故障/安全与Bao/Chain/HIA各自真实consumer接受 |
| B21 | 原Intel全失败包已完整独审，receiver关闭优化已进入组合候选 | 原2秒/5秒及完整drain/child/FD不变，原Intel范围与相关CI通过，并解释实际失败原因 |
| B18 | SCIENTIFIC_HOLD不变 | 新的事前冻结2×2、重点D−B、独立未来数据、充分精度、全部失败与完整成本；未通过保留强普通默认 |

执行顺序为P0原工程门及单一候选，P1真实普通产品闭环，随后P2实际资源/吞吐/尾延迟规模测量，P3固定预算shadow强基线，P4只读因果分析，P5长期学习及忘记/撤回，P6受约束工程演化，P7实体效果，P8外部产品兼容。各阶段沿用[完整方向计划V7](PROJECT_DIRECTION_AND_EXECUTION_PLAN_V7.zh-CN.md)的退出条件；本增量没有用新的证据收件要求改写已闭合B23的原合同。

## 7. 复核入口

- [原23项机器台账V8](continuation-blocker-progress-v8.json)，状态与退出条件保留。
- [本次机器增量](post-audit-execution-v2.json)，将发布/原生/待运行资格分开。
- [本次实际证据索引V12](evidence-index-v12-addendum.json)，保留全部旧V10/V11路径。
- [依赖实际产物及独审](current-head-ci/pin-utils-proposal-4931-native-20261106/registry.actual.json)。
- [B21完整失败原件](reviews/b21-collector-v3-native-20261106/registry.actual.json)。
- [根发布与恢复原件](reviews/post-audit-execution-v2-20261106/registry.actual.json)。
