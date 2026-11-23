# 七个私有枚举的生产契约与原生资格

这七个类型来自 c12 原 35 个枚举大小诊断，均为完全私有，并在同一历史提交有装箱差异。逐项核验后只在 `ResidentExchangeV3` 引入三个表达式差异。产品树为 c12 加一个 Rust 文件；专项工具独立提交，测试用例、线协议、身份检查、补发规则和门槛沿用 c12。[七项原行与原/供体 Git blob](seven.json) · [产品提交](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/f2d0f3ddaf5a2350ddb46584ad3b80d3271f982f) · [原三作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45159928946)

两臂各有 6/6 个收据对照和 1/1 个真实 UID0 交换原测通过。完整 1,723 项注册名单相等，实际执行的是每臂具名 7 项。原三包 strict 在两臂均返回 101，115 条降至 114，大小诊断从 35 降至 34；唯一差异为 transport.rs 第 77 行原枚举诊断消失。五个 ZIP 的来源与摘要由验证器逐项复核。[机器结果](result.json) · [两臂 UID0 原作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45161496753)

## 采用项与原来可观察的行为

`ResidentExchangeV3` 只在进程内存储当前交换结果，私有值没有自行序列化或持久化。最初与候选都先解析 Current 并核对前驱。候选把已解析的 observation 存入一个 Box，原有后续签名校验仍执行。唯一成功返回处搬出同一值。Uncertain 和 Unavailable 沿用两个原错误，候选没有修改它们。补丁没有测量吞吐或延迟。[生产源码](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f2d0f3ddaf5a2350ddb46584ad3b80d3271f982f/codex-rs/hepta-agentd/src/authority_host_learning_resident_transport.rs#L352)

原 Linux 用例 `resident_root_structured_uncertain_allows_only_same_operation_readback` 在真实 UID0 与受保护的双挂载环境中建立现有 Root 夹具。通过实际本机连接，原测试对端先答 Uncertain，再答具原签名的 Current。客户端断言拒绝 fresh admission、恢复的完整快照及 attestations 相等、没有 pending、实际接收两帧且准入计数为零。其 client 由原夹具以 Fresh 身份建立。此项覆盖私有交换的正反两路；独立已注册 readonly client 和真实长期服务方配对仍须另证。同一次每臂另有六个收据原测作为兼容性对照，收据文件保持 c12 字节。逐帧随机标识和签名输入属于各自执行，工件没有跨执行的逐字 wire/磁盘镜像比对。[原用例](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c12ee03f3185d5a13949faca54f066dfd634e509/codex-rs/hepta-agentd/src/authority_host_learning_resident_transport_tests.rs#L121) · [七个完整 ID](roster.json)

## 其余六项

| 私有类型 | 已锁定或观察到的行为 | 本次保留原表示的具体原因 |
|---|---|---|
| `ClientOriginV3` | Fresh 与 Readback 选择不同授权和动作。真实 Root 用例 `resident_root_lost_fresh_ack_recovers_only_under_explicit_readback_intent` 检验服务方注册/恢复。 | 供体整文件无法通过 `recover_original_root_stream` 中原授权参数顺序。两种公开客户端恢复入口在 c12 的所有 Rust 源均各仅出现一次定义；两个 Readback 构造位于 transport 和 model recovery。已有交换用例从 Fresh 建立客户端。缺当前两个真实 readonly 客户端原正例。 |
| `OriginalCohort` | 原普通 panel 用例读真实 Shared 成员、执行签名与保留数据检查。原 paired policy 的 canonical roundtrip 及截断/重复 identity 拒绝验证的是策略编码。 | 原 manifest 同时要求 `Shared(OriginalCircuitEvaluationCohortReadbackV1)`、`Paired(OriginalCircuitOnPolicyCohortReadbackV1)` 两个逐字声明；供体同时改变两者。未定位一项具名原例把真实 paired 读回所有者转为 custody 后完成物理成员和相应拒绝校验。 |
| `OriginalLearningReceiptSourceV1` | 六个具名原用例覆盖 Generation 和 Feature 真实生产、重开原字节、回滚、过期、错误角色与源撤回。HistoricalFeature 内部原为单个 Arc。 | 本次试过仅装箱两个活动分支的候选。826 项原保护首个拒绝为 `Feature(OriginalCircuitFeatureLearningSourcesV1)` 声明消失，create_feature/recover_feature 原构造顺序同样受保护。候选未进入原生资格，也没有改动这些来源声明。 |
| `HistoryState` | 完整供体能过该文件单项来源约束。生产 Complete 保有四个文件锁和原信任数据；两处真正的调用将账本观察包在全任务回调中。现有原 ledger data 例覆盖图像/记录链、别名等拒绝和数据往返。 | 尚未取得 c12 原正例中，由四个原锁、实际账本/见证、双签名 journal 和当前身份联合证明 Complete 前后检查的成果。旧 warm 的历史文件与 c12 不同；其汇总也记录未独立下载外部 whole phase。 |
| `ReadState` | `root_run_start_historical_join_cannot_skip_or_swallow_physical_read` 是正式 c12 UID0 成功原测，含跳读与过早摘要两个被拒分支。真正 Complete 还要在 finish 再次物理读回并核对身份、截止时间与记录。 | 供体逐字破坏 Bound 绑定、身份和值帧的来源检查。早期 warm 此内层文件同一 blob，但原件未单列同源成功 Complete、持原文件直到第二次校验的正例。 |
| `PreparedCTask` | 完整供体能过该文件单项来源约束。New 与 Existing 用不同生产打开器，Existing 要从同一原任务恢复。早期 NoUpdate19 真 warm 原测 4/4。 | 相同早期研究源的 Cold01 原 cold 成果 0/1，首次 publication 验证的事实不符。缺 c12 原 fixture 中 Existing 完整恢复/重验成功及对应持久字节，不能用 warm 替代。 |

审查材料保留了每个历史供体整文件在 c12 对应 protected_file 项的实际错误、真实构造位置、两份历史 warm/cold 发布原文、原 c12 Root JUnit 和完整清单。七项之外的 28 个诊断不在本轮范围。完整 35 项的先前分类另见前一批证据。[本次真实源回放](source.json) · [上批分类](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/0eb846bfeaf225ed22cc0e5b642dcfae9be219b9/qualification/agentd_feature_publication/screen.json) · [warm 原文](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/fc30fa8df7b72a7723c7f26ce63bcae724324853/evidence/e6-terminal-originals-20261121-ac5459/noupdate19/SUMMARY.json) · [cold 原文](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c93f22d5c5c34b38078c81ebad27d47f34a11e45/evidence/e6-terminal-originals-20261121-ac5459/cold01/SUMMARY.json)

## 日志读回修正

首轮工作流曾在六个收据断言全部通过后停止。Rust 将第三项的真实组件日志插入测试名称与单独一行的 `ok` 之间，最初的工具只接受同一行的结果，导致工作流未执行后续 UID0 项。保留含原红流程的 ZIP。独立验证按每个测试名称到下一名称的实际输出检查最后状态，并对照 Rust 汇总与退出码。补测只执行此前未抵达的 UID0 项，使用同源码、同编译目标、相同的原用例和权限环境；其二进制摘要与先前对应臂逐一核对。

## 原件与复算

运行的两个 musl 工作树均在干净的目标提交编译相同的原 Rust 二进制，用原 `--exact` 名称及原忽略测试的 UID0 环境执行。每个工作树逐条重放 826 个 protected_file 和 11 套共 95 个原源码用例；1,652 是未改 manifest 的注册边界计数。strict 沿用三 crate、all-targets、锁定依赖、`-D warnings` 的原命令。两个基线日志文件保留官方工作作业的错误标题/位置逐字片段。[基线 strict](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45138928408) · [原 c12 UID0 的68项](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45138928116/job/137571844611)

`prior-root.xml`、`prior-checkout.json` 来自 artifact 14805940041，原完整 ZIP SHA256 为 `ddf16083372d026c657405349f7738c3dbb59cf0261159ebc3c2cc1adcb4ffb4`。该旧 workflow 在其他步骤报错；68 是其实际 Root JUnit 通过数。本轮所有 ZIP 保留原字节，独立复核同时查中央目录、SHA、完整列举、每个具体测试原行、UID 证词、二进制摘要、源 blob，以及 115 条诊断逐条多重集。

```sh
python3 verify.py > replay.json
cmp result.json replay.json
python3 -B source.py /path/to/c12 /path/to/f2d0f3dd /path/to/24abd04c > source-replay.json
cmp source.json source-replay.json
```

与 c12 比，研究整合树 3b1387 的 7 个提交改 25 个文件。其目标 transport 原 blob 实读为 `40b744877e6e3a0e02dea0fdc9fffb8859eefdf7`，和 c12 相同。3b1387 另改了同一 crate 的其他生产文件；这一份资格仅针对这里列出的两个确切源码。[树比较清单](overlap.json) · [分支 DAG](https://github.com/TrillionniumFoundation/hepta-private-ci/compare/c12ee03f3185d5a13949faca54f066dfd634e509...3b1387335f57a67ae9f5878064feb26a1601d715)
