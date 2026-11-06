# musl 资格独立审计：ff72d462

审计时间：2026-11-04T18:25:24.378Z。固定 head `ff72d462d74f9eb856aa9edbc368caad9c466708`；实际 CI checkout `8e20cb5ec8261053ea472f06f79a0def072f3dce`；相同 tree `f780fe13946102a33b329898af48810be9c7bf0c`。

## 结论

当前 blocking CI 的 GNU、musl 两个 Linux 标签选择同一个 GNU/glibc RBE 平台，不能记成两种 libc 的独立测试资格。当前源码确有四项 **musl 目标 V8 依赖库构建**成功记录，但构建主要由远端动作缓存满足，四个 Cargo smoke 都在打印跳过信息后退出。它们既不是当轮全新编译，也不是 Rust/Hepta 产品可执行文件的运行测试。

本次对 exact-head GitHub runs 完整读取 18 项，第二页为空、无重复；其中没有 rust-release、postmerge-ci 或 rust-ci-full 运行。结论仅覆盖当前 head 与已审证据，不宣称仓库历史或其他外部环境从未做过 musl 验收。

## 两个 blocking Linux 标签的实际范围

- [GNU 标签 job 126733764675](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41875454075/job/126733764675)：实际 test invocation `bde32dd9-f619-4e18-b75b-a27f863acd8e`；完整 decoded UTF-8 log 2,207,973 B，SHA-256 `9ce6829a4ccbd6f8156942ac66138a89dd881a99d0641a0167d3b67a9a5fd716`。
- [musl 标签 job 126733764827](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41875454075/job/126733764827)：实际 test invocation `99b1f5d9-685c-4337-9cf1-502f666dad5a`；完整 decoded UTF-8 log 2,199,546 B，SHA-256 `f1206af791e4fd04c685715b70a285b7451ea861d10b08992010b9fb2d1966f2`。两份原日志由 ci_audit 保留。

固定源证明：`.github/actions/setup-bazel-ci/action.yml` 的 target 参数只用于缓存命名；`run-bazel-ci.sh` 为 Linux 选择 `ci-linux`；[.bazelrc](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/.bazelrc) 指向 `//:rbe`；[rbe.bzl](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/rbe.bzl) 明确声明 `@llvm//constraints/libc:gnu.2.28` 和固定的 Ubuntu 系 RBE 容器。该约束不是对容器实际 glibc 版本的测量。下载的 cargo-binstall/just 等 musl 主机工具不属于被测产品编译证据。

建议报告称为：**Linux GNU/glibc RBE — GNU 标签 lane／musl 标签 lane**。仍保留两个 job 各自的实际状态、重试及跳过；不能把两个标签相加为双 libc 覆盖。

## 已存在的四个独立 musl V8 构建

工作流：[v8-canary run 41875454034](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41875454034)。四 job 实际 checkout 均为上述 merge，显式选择已有 `@llvm//platforms:linux_amd64_musl` 或 `linux_arm64_musl`。

| Job | 目标与变体 | 原构建动作统计 | Cargo smoke 实际结果 |
|---|---|---|---|
| 126734406638 | x86_64 musl，ptrcomp-sandbox | 5,823 remote cache hits + 9,886 internal | SKIPPED，原 log 5372 |
| 126734406654 | x86_64 musl，release | 5,823 remote cache hits + 9,886 internal | SKIPPED，原 log 5354 |
| 126734406655 | aarch64 musl，release | 6,062 remote cache hits + 10,388 internal | SKIPPED，原 log 5325 |
| 126734406721 | aarch64 musl，ptrcomp-sandbox | 6,062 remote cache hits + 10,388 internal | SKIPPED，原 log 5335 |

四份完整 decoded job log 的 SHA-256：

- 126734406638，516,510 B：`352c9b2c1bed646736cc83d9f0b3bedae67f76ae6bf0157fa19a847a005c8ec9`
- 126734406654，514,389 B：`0297bd7e728c5a4e5564347561eff4c615d0a6fe30b4ecf95aac04ece693235a`
- 126734406655，511,234 B：`70c0713ce51e31a1a7d3810962eec7d339eb6c0b8228ce1a12151943cda0eb39`
- 126734406721，512,327 B：`9e7deeb4b27a3da1d7b13171f1e3d54d9f0b0cc6a245bdfb37e9adcd200ba628`

四工件 ID 为 13346887327、13347505391、13345983851、13345759100；API size/digest 与上传日志对应，详见配套 JSON。未下载或独立验证工件 ZIP 成员字节。当前可记为 **musl 目标 V8 库／绑定构建成功，使用动作缓存；运行 smoke 未执行**。

[固定 v8-canary 源](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/.github/workflows/v8-canary.yml) 的 299–305 行只允许 GNU Linux 与对应 macOS 进入 Cargo smoke，musl 明确 `echo "Skipping non-native Cargo smoke ..."; exit 0`。因此 GitHub 的绿色 step 状态不能用作 musl runtime PASS。

## 已有构建入口与最小后续选择

[release_binaries.bzl](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/bazel/platforms/release_binaries.bzl) 已通过 `platform_data` 定义 musl 平台转换；[CLI BUILD](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/codex-rs/cli/BUILD.bazel) 已实例化四个具体目标：

```text
//codex-rs/cli:codex_linux_amd64_musl
//codex-rs/cli:hepta_linux_amd64_musl
//codex-rs/cli:codex_linux_arm64_musl
//codex-rs/cli:hepta_linux_arm64_musl
```

这些目标标记为 manual；本轮没有取得其显式构建与执行回执。MODULE 注册工具链、Cargo 元数据列出 musl triples，也不等于这些产品目标已通过。PR 的 “Verify release” 主要验证关闭 debug assertions 后的编译面，不能据名字推断 musl 产品构建完成。

1. **先做精确源码、独立且不发布的产品构建验收。** 从已有 x86_64 musl CLI 目标中选择产品入口，保持构建工具／proc macro 的 GNU 执行环境，记录真实解析的目标工具链、产物 ELF 信息、hash 与源码。复用现有平台，先取得实际结果，再决定是否调整 blocking 矩阵。
2. **随后单独取得运行证据。** 运行那些相同 hash 的 musl 产品字节及选定原行为测试，保留真实命令、OS／CPU、JUnit、skip/retry。只生成 archive、`--no-run` 或成功退出的 skip 都不足以闭合。musl 静态程序在 Ubuntu 上执行只能按该范围命名，不能外推 Alpine 部署验收。
3. **已有 Cargo 备选路径。** [rust-release.yml](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/.github/workflows/rust-release.yml) 包含真正的 `cargo build --target ...-musl`、现有 linker 安装脚本、V8 校验及 bwrap 最终字节摘要流程，可在单独审查的不发布工作流中复用。当前只在 tag release 上触发，没有本 head 实跑资格；不能为补测试触发发布流程。

现有 `rust-ci-full.yml` 的 musl 项主要是 compile/lint；其 Linux nextest 调用方只有 GNU。可复用显式 target archive 机制，但新的 musl runtime 调用方及前置条件需要实际验收，不能当成现成通过记录。

## 本次操作边界

仅只读 GitHub 取证与报告固化；未运行 Cargo/Bazel、安装平台、调整矩阵／filters／库依赖、启动或重跑工作流。报告以不可达 blob 交接，不移动任何 ref。
