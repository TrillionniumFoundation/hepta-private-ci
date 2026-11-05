# 第四轮：七项已实现范围的验收缺证与下一精确源门槛

本节保留 B07、B08、B09、B13、B20、B22、B23 的原退出条件，**没有新增任何 blocker 闭合声明**。本次读取的是已保存的 cabc 原 CI 工件，未重跑测试、修改分支或操作原生 Cargo。当前发布源是 `cabcb40d36e116beaa65750e1f674c52035da785`，树 `b2d7f038d6d88156bc6a4cb29c8703f69b808f29`；普通 CI 实际合成提交为 `28af7f705fa1024b9a6d2ef751fec116002260eb`，树相同。旧收据不自动转成 df74、最终新 head 或其他分支的资格。

## 数量与证据边界

七项台账的原用例索引共 **97 个名称**：B07 28、B08 4、B09 19、B13 9、B20 19、B22 13、B23 5。检索时另加入 **8 个 Windows isolated-lifecycle 上下文名称**，所以实际检索集合为 **105**。这 8 项分别属于环境启动等待、两项 rollout 恢复、两项 fork 历史、registry 替换、延迟 shutdown 和 cold-close 所有权；完整精确名称及归属保存在机器清单，不能并入七项的 97 个原用例。

7 个原 ZIP 的 243 个成员已验证字节、SHA 和 CRC，得到 **406 条结果记录 = 331 条台账记录 + 75 条上下文记录**；实际匹配 **72 个不同名称 = 64 个台账名称 + 8 个上下文名称**。其中 39 个 Mac XML 是目标级 wrapper，字段嵌在各 member 中，精确用例匹配数为 0。重复分片和重试记录均保留，不能把 406 解释成独立用例数。

GNU 与“musl”标签的 54 个对应成员正文逐字节相同，来自同一 GNU RBE 配置；这些记录不补足真正 musl 编译或运行资格。Windows 完整 Core unit 的其他实际失败也保留，局部成功不能提升为整个目标通过。

## 哪些旧证据已经够用，最终原 CI 还缺什么

| 项目 | cabc 已有可引用的精确结果 | 最小剩余取证 |
| --- | --- | --- |
| **B07 Hook／MCP／Executor／TokenBudget** | 原 22 例在 Linux 普通／Wine 变体、Mac ARM／Intel 普通 Core 有精确 `ok`；Windows TokenBudget 3 例有正文。18 个 Hook 例按原 cfg 不在 Windows 编译；CodeMode 的原 Windows ignore 保留。 | **Q01：codex-mcp unit 的 6 个 binding 正向／拒绝控制**，读取各适用原平台的成功正文。不能用 unit target/cache 标记代替。 |
| **B08 attempted replay** | Windows 完整 unit 日志中是实际 **2 个 recorder＋1 个 wire** 名称，8 份日志共 24 条成功记录；Unix namespace／实际 prompt-output replay 有精确成功。不存在已核“第 3 个 recorder”。 | **Q02：Linux／Mac Core unit 的这 3 个原名称**。保留 resolved endpoint 的 wire 矩阵及 retained calls／实际 output 对应，不能改成所有 provider 都剥除的笼统表述。 |
| **B09 terminal／Wine recovery** | Linux Wine AppServer 的 8 个 turn_recover（含 feature gate）和注入原例有精确成功；Windows 注入成功，7 个 terminalizer＋2 个 steer unit 共 72 条成功记录；Unix suspension 原例成功。 | **Q03–Q04：普通 Linux／Mac AppServer 的注入＋8 recovery，以及 Core unit 的 9 个 terminal／steer**。Wine 与普通目标分别记账；turn_recover 原 `cfg(unix)` 不能算 Windows 缺测或通过。 |
| **B13 Queue／Lease** | 目标级成功与缓存标记可保留；Windows Queue 确实执行并 target PASS。历史 native 资格仍属于原来的树。 | **Q05–Q06：Queue 8 例＋Agentd 过期／quarantine 1 例**的精确正文。现有失败专用 ZIP 没有这些成功目标正文。 |
| **B20 remote handshake** | Linux Wine 与 Windows AppServer 的原 **19 例均有精确 `ok`**；所有已保存 attempt 一并投影，没有把所选 B20 失败藏在最终通过后。目标整体 FLAKY 来自其他用例，仍保留。 | **Q07：普通 Linux／Mac AppServer 的同 19 例**。不把变体成功借给普通目标，不重做已完成的旧源因果负控来凑数量。 |
| **B22 Windows TUI** | Windows TUI 的非缓存目标成功真实存在：29.4 秒、8 个分片时间。但原 7 包内没有 13 个所选名称的成功正文。 | **Q08：TUI 原 13 个名称**，重点是 Windows 的匹配 turn／stdout 就绪、interrupt／shutdown 顺序。单个上传文件被判断为 compact log 仍只是 source＋数量推断，不能写成已读 ZIP 的事实。 |
| **B23 Unix signals** | 历史因果负控 3 个 signal 失败＋2 个 drain 成功、修后 5 成功保留在旧树；它证明原问题与修法，但不是 cabc 平台正文。 | **Q09–Q10：最终 Unix 的原 5 例；Windows 仅 portable drain 2 例**。不把 Unix signal 的 cfg 排除计作 Windows 成功。 |

机器清单包含全部 97 个原名称、cfg 证据、旧结果原始指针、10 组 exact-name 查询和原预算。这些查询合并后为 **7 个原目标、33 个目标／平台标签组合**，涉及 73 个“至少还缺一适用平台正文”的不同原名称；这是取证范围，不是新增 73 次测试任务。原 24 个已具备对应适用旧源范围的名称不再安排补跑。

原时限保持：Hook 原 5／10／15 秒各自用途不变；recovery 的 READ 10 秒、STARTUP 25 秒和故意 provider delay 30 秒不变；Queue／Lease 的真实 TTL、DB acknowledgement 及原等待不变；remote 的 EOF／shutdown／disconnect 各 10 秒不变；TUI readiness 5 秒和真实 shell 场景不变；signal 父 10 秒、子 5 秒不变。完整细分预算保留在 JSON，不设一个替代原代码的“统一时限”。

## 已补好的证据留存，以及它尚未证明的范围

3 脚本成功日志留存改动已在源码树 `df74afac9e4e31b61a94725d9689b5d0e40eddfe` 完成实际 Linux 脚本验收：`bash -n`、两个文件的 `py_compile`、原 `unittest discover` **57／57 成功、0 skip、0 retry，6.288 秒**。11 个原记录的字节与 SHA 已独立复核，完整 verbose roster 中实际有 57 条 `ok`；该阶段**没有 JUnit，也没有 Rust 或 Windows 执行资格**。

新 collector 的 10 个精确目标标签覆盖上述 7 个目标，并保留 AppServer／Core 原 Wine counterpart 和 Core integration。它不改变原 Bazel 命令、筛选、缓存、重试、skip、时限或退出码；未报告、歧义或 SKIP 的目标不去读旧目录。下一精确 head 的原托管 CI 才能证明成功日志是否实际可取得。远端成功日志没有落地时，继续记 `EVIDENCE_MISSING`；mtime、缓存 PASS 或 `complete_for_selected` 本身不是 invocation 身份。

执行顺序只需：冻结最终 head／tree 与实际 checkout／merge → 让已要求的原 CI 正常完成 → 校验原 ZIP／member 身份 → 用既有只读投影脚本执行清单查询。JSON 的最终 head、tree、artifact 绑定字段保持空值并显式阻塞，等真实发布输入补齐；本节没有制造一个可误通过的临时资格。source 与 merge、cached 与 executed、首次与重试结果分别保留。

## 已知跨 owner 分支的定点增量

2026-11-04 23:16–23:24 UTC 定点读取了 [#4797](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4797)、[#4806](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4806)、[#4808](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4808)，并在 23:24 后补核 #4806 的终态元数据。没有重复全量库存。#4797 仍是 cabc／b2d7，base 636；main 仍为 `732e934ba496d90fbe042b8d41d479ef901643e5`。

- **#4806**：Draft，head `fbf786803f07e402bcaddbb8fbe3dd387f6b7688`、base `14e2d89b3367232ec5dbe6187f09feed0f2b68d3`，23 个文件完整分页。原 blocking 已失败，37 个 job 中 22 success、11 failure、4 skipped。实际 merge `a5fb5b493637d2d89d8ce17251e52ffa0e9e6bbc` 的树与 head 同为 `030f5a4ce442c5b53676176be750ca244b9414d3`；closed-caller 检查原文报告 `authority_lease_put` 的 unexpected caller `deployment_calculator.rs`。PR 已承认这个既有整合缺口，应由该 owner 保留原权限契约处理，不能仅加白名单就视为接受。
- **#4808**：Draft，head `2496308dbbe8b2452ea599357fcd9cd63884e2b9`，12 个文件完整分页。虽然当前 base 指向 fbf，head 的实际父仍为 `735b980092e4cca7790037923111322660672059`；与当前 #4806 **ahead 1／behind 5，已分叉**。base 变化不能视为 head 已包含后续修复。它新增 Windows private-state 创建入口、Fleet 接线及测试改动，不能归入“全是 fixture”。
- #4808 的 private-state 原负控任务先通过 6 个脚本自测，随后被 `production source differs from frozen controls` 阻断；这没有执行出新的攻击负控结论。native UI source-head 的实际失败是链接缺 `-lpulse`，不是该阶段原 native 用例失败。原 Windows regression 的 7 个真实 scope 共选中 91 例，记录 47 个 non-passing：State／Git／MCP 3 个 scope 成功，Memory／operator／shadow／sandbox 4 个 scope 失败；这些结果全部属于 2496 源。其余进行中平台状态保留观察时间，不借任何 donor 通过给 P0。

这些增量说明其他 owner 的修复仍需精确整合和自身原门禁，**没有改变本轮单一 P0 候选，也没有触碰 Windows token／ACL／loader／DLL 生产边界**。

## 固定证据

- 完整旧投影：`37a93aba1fb93023262caf5f51d43960c5acc83d`；独审／97-name index：`203d8eab0dd003f272c09f962e16ca9505da4f2a`。
- 本节机器清单：`6f8f5bbc43a627f280766457ccdae46cef93a9c9`；既有只读 projector：`bbe91c8941ebe2736c6ef62fe7edea89e1acb6b6`。
- 脚本真实 57 例 bundle：`e30e254b712f868ec0c21ecf272cbaa294cde8ef`；root 独核：`ca33e423db6f2bf7aa9e552b6a468af6ed484484`。
- 定点 PR／分页／run／job／原日志索引：`d302cad4ead462c17258c8fce33eac0c21f5ad37`。四份完整原日志分别固定为 `61df2e0c8eceedb7c9fc7816c8faab8d89682b9e`、`09e3124f97e9be90530858fc0e56e8668f7ec592`、`951efbee877044de88a3ffed136690362e6d21a2`、`d3586d5c2f3ea83d7df746f268adb52a9f53db59`，没有签名下载 URL。
