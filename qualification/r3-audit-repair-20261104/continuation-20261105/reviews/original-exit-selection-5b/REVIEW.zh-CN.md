# 原退出用例的实际选择核对：固定 5b 源

**结论：54 个待核原名都有既有 Bazel 注册，没有发现需要新增测试注册的缺口。Agentd 的第九例有一个真实的 Cargo 选择边界：默认 whole-workspace full 不会编译或列出它，必须保留独立的 `qualification-cognitive-write` feature scope。当前主 Bazel 矩阵尚待真实执行，其他成功任务不能替代其原退出证据。**

本次固定产品 commit `5b6331250ff459033bd44d1a95daec70131277cc`、tree `b26598d0d97d8d51e723bb5582137315f2174d35`。已核 50 份选定完整源码的 Git 内容身份，以及 93 份完整 workflow 的固定叶子身份。未执行 native、构建、项目测试、dispatch、retry 或修改产品源码/ref。以下原命令只是供唯一 native lane 选择、绑定后执行的清单，本报告本身不授权执行。

## 54 个剩余原名与现有选择

| 组 | 原 blocker 和数量 | 现有 binary / Bazel target | 当前选择结论 |
|---|---|---|---|
| Core integration | B07 22、B08 1、B09 1、B10 14，共 38 | `codex-core::all` / `//codex-rs/core:core-all-test` | 主 Bazel `//...` 包含；Windows Core lifecycle 只跑 `core-unit-tests`，不能覆盖这组。Unix-only 和原 Windows ignore 必须保留。 |
| MCP library | B07 6 | `codex-mcp` / `//codex-rs/codex-mcp:codex-mcp-unit-tests` | 主 Bazel 包含；需要原具名结果，不能用 Core/MCP 相关其他测试替代。 |
| AppServer integration | B09 9 | `codex-app-server::all` / `//codex-rs/app-server:app-server-all-test` | 主 Bazel 包含；其中 8 个 `turn_recover` 原文件为 `cfg(unix)`，不能由 Windows 结果证明。 |
| Agentd qualification | B13 1 | `codex-hepta-agentd` 的 qualification build / `//codex-rs/hepta-agentd:hepta-agentd-cognitive-write-qualification-test` | 外层目标已注册且没有 manual/platform 排除；内部 rust_test 的 manual 不会排除外层。默认 Cargo full 缺少该 feature。 |

`selection-checklist.json` 保存全部 54 个原完整名称、逐例源路径/blob/函数行、原平台范围、原 Bazel target，以及四组完整 argv 和 shell 表示。每组都沿用原 `just test`，使用已有 `--locked --cargo-profile dev-small --no-tests fail --retries 0` 资格规则，未添加 `--all-features` 或重复 `--no-fail-fast`。后者由原 `scripts/run-nextest.py` 注入。

这四组是可选的原名选择方式，不要求同时重跑；主 Bazel 鲜执行提供足够原件时可直接核对。现有成功日志 collector 的 11 个目标白名单已包含上述全部四个目标，不需要为了本清单改 collector 或选择范围。cached、未落本地日志、无具名原文的 target 成功仍遵守原限域。

当前已有具名证据的 20 个相关原例单列保留：Windows Core 的 B08 3 个、B09 9 个，Queue source/merge 的 B13 8 个。Core 同一完整目标有另外 1 FAIL，不能将其整体升级为 PASS。owner-local 的 UDS/Matrixd/Agentd 共 217 例与原 142 名交集为 0；Agentd 172 个默认 `--lib` 例不能填第九例。

## Agentd 第九例：不是仅从 default 字段推断

精确原名为：

`runtime::tests::qualification_prepare_quarantines_expired_registry_attempt_with_h7_evidence`

源为 `codex-rs/hepta-agentd/src/runtime_tests.rs`，Git `31a41d8cad53ee3f04a1106e245dc5c3f4392a5b`，函数位于 608 行，前置 `#[cfg(feature = "qualification-cognitive-write")]`。`Cargo.toml` Git `d94042bddf8fcf785e2963a3acc90afcab3dbd69` 明定该 feature 仅包含 `production-cognitive-write`。

本次进一步读取两份真实 whole-workspace 完整 metadata 和 catalog，检查了实际 feature 统一结果：

| 原始 scope | metadata Git | catalog Git | Agentd 实际 resolve features | 精确第九 / qualification 前缀 |
|---|---|---|---|---|
| A fb9 原 full | `3d2f7bfbd5fb2fc0fd219045444327e929820fdd` | `6215be8be0979a4af011c64de4043c934aeee81a` | `default, production-cognitive-write` | 0 / 0 |
| ai395 P4，4a BUILD_ONLY | `e1f0ddb638f8d46e24d94176c3993e7fa2a293fd` | `bdb4590509011c05005821d6b92c71f81f58098c` | `default, production-cognitive-write` | 0 / 0 |

两份 catalog 均有 363 program、19,563 个原 case，普通 Agentd unit 各 243 个。已保存逐原件 hash、匹配记录和普通 binary 身份。4a→5b 完整树差分中，实际工作区的 Cargo manifests、locks、BUILD、defs、just/run-nextest、nextest 配置都未变；`qualification/` 里的静态候选文件不属于实际编译输入。这个桥接证明选择输入未变，不把 fb9/4a 的历史执行重新标成 5b。

既有独立 workflow `hepta-gap-agentd-process.yml:159–160` 的原命令是：

```sh
just test --locked -p codex-hepta-agentd --features qualification-cognitive-write \
  --lib runtime::tests::qualification_ --test-threads=1
```

该前缀实际有 3 个原测试。workflow 仅有 `workflow_call` 和 `workflow_dispatch`，93 个固定 workflow 中没有调用它的 `uses`，也不是本头已触发的 19 个 run。若 root 选择先补第九例，可通过同一个既有 recipe 精确运行原名：

```sh
just test --locked --cargo-profile dev-small -p codex-hepta-agentd \
  --features qualification-cognitive-write --lib --no-tests fail --retries 0 \
  --success-output immediate \
  -E 'test(=runtime::tests::qualification_prepare_quarantines_expired_registry_attempt_with_h7_evidence)' \
  --test-threads=1
```

不要同时默认执行这两个备选 scope，也不要把一次新 feature 结果冒充默认 full 已覆盖。该 feature 没有增加依赖 feature 边，但会改变 Agentd 编译条件；应由 sole native lane 绑定实际 feature 图、catalog 和新 binary/helper 前后身份。已有 101,107,624 B 普通 Agentd binary 是历史 ROG 观测，不是 qualification binary，更不能据此保证峰值容量。

原测试使用临时真实 registry/SQLite 和 H7/authority-lease。它在现有 30 秒 setup lease 内完成真实绑定写入，然后等到原 `expires_at`，断言过期资格准备不返回可写输入且保留精确过期 registry head。原 nextest `local` 继承 `30s × terminate-after 2`，没有该例专用 override；原内部期限、最终断言、等待方式均不改。BUILD 明确这三个 fixture 不启动 Agentd、AppServer 或 provider 子进程。这是原本地 qualification 退出项，不能升级成 B16 的独立 UID0 Root/Current/FinalUse 接受资格。

## 主 CI 的覆盖和保留边界

`blocking-ci.yml:94–95` 仅在原 scope 的 `full_repo == 'true'` 时调用 Bazel。非 Windows 原测试选择是 `//...`，只排除独立 V8 目标和 argument-comment-lint tag；Windows 原查询排除 manual 内层后按 label 分入四个 PR shard。上述外层目标都在选择范围内。Core/AppServer 外层测试原 timeout 属性为 `long`；Agentd qualification 和 MCP 没有显式 timeout 属性，保留规则继承，不虚构秒数。Bazel 矩阵 job 原总预算为 120 分钟。

本核对没有重新查询 CI。research 的 13:08 UTC snapshot0045 显示总 job 已展开到 59，但主 blocking 测试矩阵仍未展开；先前 44 不是永久总数。静态注册存在不等于实际运行，其他 workflow 的成功不能填这些原门。B10 各原测试仍含 `skip_if_no_network!`，原早退不能算业务通过；Windows 编译缺失/ignored、Wine 和原生平台范围继续分列。

## PTY 计数补充

`tests::output_collector_waits_for_exit_after_output_closes` 已存在于 fb9 原完整 catalog，记录为 `ignored=false`、`filter-match=matches`。该 Linux PTY suite 原为 29 例；Mac 的 31 例是平台 cfg 结果。4a→5b 的 `tests.rs` 仅在原 2 秒结论后添加 4 行诊断，未新增这个测试。因此不能为 5b 的观察补丁再次给原 19,563 catalog 加 1。

完整证据入口为本目录的 `selection-checklist.json`、`actual-full-agentd-feature-catalog-proof.json`、`source-manifest.json` 和 `workflow-input-map.json`。所有原 blocker 状态保持不变。
