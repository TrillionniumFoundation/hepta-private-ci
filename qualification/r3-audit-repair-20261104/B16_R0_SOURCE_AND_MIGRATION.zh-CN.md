# B16-R0：普通 Root 联合入口的源码准备与独立迁移批次

状态：**已完成固定源码审查；尚未迁移代码、编译或运行普通 Root 联合入口。** 本稿用于下一独立代码批次，不把 B16 代码混入正在收尾的 P0 修复。完整逐文件记录和类型边界在配套 JSON；当前入口的 18 段源码证明另存为 Git blob `4272a55179316d39863378a53023944dfef1a8d8`。

## 一、现在缺的是哪些实际接线

**当前普通 Desktop Root 仍走 Notes 专用启动；联合 Notes/Calculator 的正常 producer 仍须实现。** 这个结论来自实际入口、完整子树和类型调用链，不能全部归为“等外部环境”。

| 固定对象 | 本次独立确认的事实 |
| --- | --- |
| Hepta `ff72d462d74f9eb856aa9edbc368caad9c466708` | 普通 Agentd main 仍从进程环境取配置，再进入原 `run`；没有 donor 的 `AgentdProductionStartup`、Root preflight 或联合启动分支。 |
| 原生候选树 `a69b20c4c3cfee9cf483496742d6bea1469d847a` | Agentd 与 ff72 的完整净差只有两个 integration test 文件；App Server 只有 executor_skills 测试变化。arg0、Memory、Contracts、Objective、Agent Protocol、UDS、App Server Transport 七整个 crate 子树相同。因此这些入口源码结论同样适用于 a69，运行资格仍单独计算。 |
| Hepta donor `14e2d89b3367232ec5dbe6187f09feed0f2b68d3` | 有显式 Root handoff、protected Current 和联合运行时组件；它们有实际 API，但不等于当前普通产品已接入。 |
| Desktop 当前 `c42eccaf8b9b5a163d0c52b1a3c42466fe0f425b` 与旧 `c2c369836e87e9cf27b4dc9aa8b7446e85efdf90` | 两者 services 整棵树均为 `247dfcc7a451b8bd6926fe2d5013120ace0c984d`。旧 c2 也没有不同的联合普通 producer 可直接搬来。 |
| 当前 Desktop 与旧 c2 的 UI | 两分支 diverged，ahead 12 / behind 2。当前完整 UI 树缺旧 c2 的 desktop_startup、desktop_bootstrap、Calculator organ/lifetime 等模块；当前实际 parser 也不接受 `--desktop-root-bootstrap-stdin`。 |
| #4800 `1b390853e50aa2fdae2e6c68793f94742d2d667c` | 十个变更文件提供 native G2 role socket 工作。其 PID-1 owner/control 场景与普通 Desktop 联合 UI producer 是不同接线，不能相互替代资格。 |

当前实际 Root 调用链很明确：

- `services/hepta-session-host/src/product_root/mod.rs`，blob `3c62925cc7e6c7aae2fc6805fa64c2bf11cc196b`：向 Agentd 传 `--root-production-profile notes` 和 Notes 专用 handoff/deployment/listener 描述符，调用 `with_notes_startup_from_session_before`；恢复分支调用原 Notes 专用恢复接口。
- `session.rs`，blob `7054223d1c27a66f02da4f487e094fc7029cc0ff`：启动真实 Session 的参数为 `--notes-root-bootstrap-stdin`，解析 `NotesStartupReservation`，保留真实 pidfd/进程身份。
- `seed.rs`，blob `64156170baea0436213546da6b710b511a8e79eb`：调用 `seed_original_notes_thread`，使用 `NotesThreadSeedReceipt`。
- `authority.rs`，blob `0c030f500806c8b7a18c714e328aab10c1a0215e`：发行 `organ.desktop.notes` scope、Notes admission profile 和 `hepta.root.notes_launch_profile.v1`，保留原 TextRecovery 合同。
- 当前服务 Cargo 文件仍把相关 Hepta 依赖固定到 A39；它不能证明 ff72/a69 已包含 A39 的整套入口，也不能用改 pin 代替缺失的类型与接线。

联合 donor 要求的是严格的 `notes_calculator_v1`、`hepta.root.desktop_launch_profile.v1`、`hepta.agentd.original_desktop_launch.v1`，真实两目标 reservation、独立的 joint deployment、`DesktopThreadSeedReceipt` 与六工具目录。把 Notes 字符串改名不会满足这些合同。

## 二、必须保留的两个当前接口

### 1. 原 Objective sender 返回合同

当前 `production_composition.rs` 的 `AgentdProductionHostAttachment<C>` 持有 `original_sender`，与同一个 checkpoint/writer 绑定。实际 `desktop_objective_ui.rs` 会消费这个 sender，并要求调用方提供已经签名、与窗口和草稿完整绑定的 original request。

donor 同名 `attach_production_operation_host` 却返回 `Option<NotesTargetIdentity>`。这不是可直接覆盖的兼容接口。应移植 protected Current 的能力，同时保留当前泛型 attachment、checkpoint acknowledgement 与原 sender。渲染器不能获得签名能力，现有 UI API 也不能因 donor 没有而删除。

直接来源：当前 composition blob `1464029ba8643aa7a44f3835d0ab700bb3673156`、UI blob `88fbf93a7d27f0382143df8caaab8a65591699e2`；donor composition blob `3e554d364d992c20ca53628b3f0852d5cb296782`。

### 2. 普通本地连接的 peer gate

当前 App Server 的普通 UDS acceptor 在每条连接升级前执行 `ensure_control_peer`，最终检查 current-user peer。donor 只在 `inherited` 路径检查 owner 或 Root。若整文件覆盖，会丢掉当前普通入口的检查。

因此新增 Root-bound/inherited listener 必须是显式路径；普通入口原有身份验证、Windows owner-local 类型和源文件、已修复的 shutdown signal 生命周期都要保留。donor 的 UDS 树缺少当前的 `owner_local*` 文件，不能以 donor 为整 crate 替换来源。

直接来源：当前 transport blob `0cb230d72e799350eef0405deb2f34d4ef8d79ac`（79–85、183–184）；donor blob `f419409fb1004e1e9e74e4ef0e033e4ba880756b`（122–127）；当前 UDS lib blob `1fe59d7df88a6a155e37e36329535231d3c61a86`。

## 三、六组必须一起满足的接口合同

| 组 | 实际文件和类型入口 | 原子边界与最小退出条件 |
| --- | --- | --- |
| C1 Root handoff | Agentd production_launcher/inputs、root_production_handoff、root_production_writer_handoff、bootstrap seal | 真实 Root 在 spawn 前建立匿名通道；独立 sealed bootstrap 与同一 Root pidfd/凭据；distinct FD、有限 deadline、错误 rights 全关闭。producer/caller 不得由 API 导出代替。 |
| C2 Registry / arg0 / Core | arg0、Agentd main/config、config_root_handoff/credentials、runtime/app_runtime/control | 单线程 preflight 在 alias/dotenv/runtime 前完成；保留实际 Starting generation、原 writer inode/锁和原 Core/App Server 入口；普通路径不回退。 |
| C3 protected Current | Memory cognitive_checkpoint 系列、Agentd production_protected_host/root_production_inputs/root_authority_session | 独立 Current receipt 是真实恢复输入；same writer/checkpoint/sender；所有 await 后仍需 live checks，最后原子安装。保留当前泛型返回合同。 |
| C4 issuer / FinalUse | Contracts 的 Root clock/frontier/peer，Agentd root_issuer_client、authority_host_* | 同一 Root issuer/签名/时钟/进程寿命；真实 human/session/source 绑定；expiry、revoke、unknown 与单次 effect 进入保持原语义。 |
| C5 listener custody | root_bound_socket、config_sockets、UDS inherited、App Server inherited acceptor；#4800 publication 可单独审 | Root 父目录与 UID/GID/mode、FD/name custody、configure-before-publish、NOREPLACE、匹配 inode cleanup。只有合法最终 owner 调用 listen；普通 peer gate 不变。 |
| C6 普通联合产品入口 | Desktop product_root 的新联合 producer；旧 c2 联合 consumer 与当前 c42 合并；Hepta desktop_*、Calculator、Objective typed source | 新六工具原线程、严格 joint profile、真实两目标 reservation/offer/ACK、同一 writer/issuer/UI owner；配对精确源码和锁；最终从普通可执行入口完成真实回合。 |

完整 JSON 的 **102 条决策记录**逐文件列出当前/donor blob、所属组、需保留的接口和可采用方式。这是已定位的 review 范围，不是假称编译后证明的最小文件闭包。另有 **474 条源与构建文件净差记录**，来自九个完整 Git 子树，包含尚需逐实现审查的依赖。

ff72 与 14e2 的 compare API 返回 300 个文件已经截顶，且两者分叉；这类 diff 是 merge-base 到 head 的结果，不能代替两树净差。Agentd 完整子树有 813 个 blob path 差异，其中也包含大量历史文档/资格记录。旧 PR 的 89 路径既不等于全部先决依赖，也不是本次推荐全搬的范围。

## 四、最小的第一独立代码批次

建议 **R1 只做 arg0 的同步 preflight 基础接口**。它属于 C2 的先决工作，不声称完成 B16。

唯一生产路径是 `codex-rs/arg0/src/lib.rs`：

- 当前 blob `f44dc145b15d656fc04d87affe6e760de090ee35`；donor blob `4e41e7affbb627df162b7b6780203b75a7dd839f`。两文件净行数相差 24，原有七个单元测试模块逐字相同。
- 新 API 的顺序为 helper dispatch → 同步 preflight → alias/dotenv → runtime。默认 `arg0_dispatch_or_else` 仅包装 `Ok(main_fn)`，保留原行为。
- 本批不改 Agentd main，不转换真实凭据，不打开 Root 权限，不新增依赖。真实使用者要等后续组合合同到齐。
- 新入口保留原单线程进程启动前提；同步 preflight 不得创建线程或启动异步 runtime。之后原 dotenv/PATH 的环境写入仍依赖这个前提。
- 新测试要用独占子进程证明拒绝 preflight 后没有 alias/runtime/main 副作用；证明成功 preflight 的真实线程与执行顺序；证明实际 helper 分派优先、alias 在 async 返回前仍存在。不要用复写实现的测试函数代替实际入口。

验证命令可用 `just test -p codex-arg0 --lib`。这是由实际 package 声明（Cargo blob `bb45db45521a60e80088f9032431d28ff4e717ed`）与现有 just test recipe（blob `a215a76cf407ace9715bca39c20497014e7dd4dc`，工作目录设为 codex-rs）推导的后续命令，**本次未执行**。原七例和新增控制必须给出同源码、零重试、完整名单的实际结果。

后续依赖顺序：

1. **R1：arg0 preflight 基础。**
2. **R2：Root trust/Current 类型与寿命、显式 inherited socket 合同。** 可以独立于 R1 审查；不得改掉当前 sender 或普通 peer gate。
3. **R3：实际 Agentd Root 装配。** 依赖 R1/R2；将身份转换、sealed handoff、原 writer 恢复、listener、deadline、取消/退出作为一个可验证的组合。
4. **R4：joint Objective/Calculator 与最新 Desktop consumer。** R2 类型基础就绪后可以并行准备源迁移；可编译集成还必须依赖 R3，因为 deployment reader 实际调用 Root seal 的 `validate_sealed`。保留 c42 新活动与原 Notes 路径。
5. **R5：实现并启用新 normal product_root producer。** 依赖 R3/R4；固定一对 Hepta/Desktop commit、生成锁与真实构建输入。
6. **R6：实际普通入口验收。** 从同一产品包发起真实 Root/session/Core 回合；长期续期和联合恢复继续分别设计/验收。

## 五、原验证命令与来源

下列是固定 donor/旧 consumer 文档里的原命令，方便代码批次完成后直接交唯一构建 lane 执行；本次没有运行，也不继承 donor 文档中作者报告的结果。

Hepta `codex-rs/hepta-agentd/DESKTOP_ORGAN_CANDIDATE.md`，blob `62aeb3436f8a4e00aad21bd9d32e8fe818ac5e75`：

```sh
cd codex-rs
just test --locked -p codex-hepta-memory --lib production_calculator
just test --locked -p codex-hepta-memory --lib desktop_turn
just test --locked -p codex-hepta-memory --lib objective_sender_desktop
just test --locked -p codex-hepta-objective --lib desktop_thread
just test --locked -p codex-hepta-agentd --lib desktop
just test --locked -p codex-hepta-agentd --lib calculator
just test --locked -p codex-hepta-agentd --lib production_launcher
```

`PRODUCTION_LAUNCHER.md`，blob `a9faeb4a88aaca14d51be4620c371a4026746b48`，另保留 inherited UDS、inherited App Server、retained MCP 等原组件命令。若选择只新增 Desktop 入口，就不应为了整文件复制 donor 而顺带搬入未需要的 Android/MCP 变化；若采用完整 launcher，则该依赖必须单独闭合。

旧 Desktop 的 `ui/core`、`ui/session`、`ui/app-window` README 原命令：

```sh
RUSTUP_TOOLCHAIN=1.96.0 cargo test --manifest-path ui/Cargo.toml -p trill-ui-core --locked
RUSTUP_TOOLCHAIN=1.96.0 cargo test --manifest-path ui/Cargo.toml -p trill-ui-core --locked emit_cross_repository_wire_fixture_from_app_serialization -- --nocapture
RUSTUP_TOOLCHAIN=1.96.0 cargo test --manifest-path ui/Cargo.toml -p trill-session --locked
RUSTUP_TOOLCHAIN=1.96.0 cargo test --manifest-path ui/Cargo.toml -p trill-session --locked desktop_bootstrap
RUSTUP_TOOLCHAIN=1.96.0 cargo test --manifest-path ui/Cargo.toml -p trill-app-window --locked
```

真实产品构建仍应走当前 `support/ui/ROOT_PRODUCT.md` 与 `build_root_product.py` 的原输入验证、Cargo metadata pin 校验、真实 UI 包、两套独立 build cache、pack/verify。当前 builder 的源/锁身份检查不能绕过。它现在生产的是 Notes 路径，必须在联合 producer 实现并审过后才能用于联合资格；组件测试不能替代安装后实际 Root、真实 Session/UI owner、原 Core 和实际 model/human 的回合。

## 六、仍然开放的产品边界

donor 当前联合会话有有限 Root lifetime 上限 300,000ms，不含长期 issuer renewal 或 epoch continuation；sealed joint deployment 不接受 `previous_recovery`。应保留这项设计限制，而不是把旧 Notes recover 改名当成联合 restart。

联合验收应分别保留实际 app 状态、原因果 receipt 与未知结果，核对 same writer / checkpoint / signed source / original callback / exact target 的来源。状态看起来相同不能替代 receipt；不确定结果不能重发成第二次 effect。实际 Root death、Session death、expiry、revocation、listener 替换与第二 effect 尝试仍需真实负控。

本次完成的是仓库内可执行工作的源码准备。没有启动 Root，没有请求新凭据，没有改变源码或 ref，也没有做新的 native/Cargo/Bazel 测试。后续完全可以先推进 R1–R5 的仓库内实现和有限组件验证，再分别处理实际环境与操作员验收门。

## 根审修正记录

独立复核确认 102 条唯一文件决策和九个 crate 的 474 项源/构建净差自洽。依据 `production_desktop_deployment.rs`（blob `c756a1ac5f22644a9b0b1c012c2dfd5879750a13`）的实际 seal 调用，本版补明 R4 的可编译集成依赖 R3；保留 R2 后并行源码准备。还补明 R1 调用方的单线程前提。原稿 blobs `428fe82692a0a400211356b6a94b219e8e31b441` / `1a156dcca8cecd9107777ad28aa891587edb35de` 保留，102/474 数据与冻结外部计划未改；没有新增运行资格。
