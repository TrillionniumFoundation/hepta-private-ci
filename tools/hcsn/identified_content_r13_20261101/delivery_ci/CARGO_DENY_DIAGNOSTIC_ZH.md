# cargo-deny 继承基线：只读诊断

## 已观察到的结论

固定 cargo-deny 0.19.0、Rust 1.95.0 和 `--all-features` 的本地完整检查退出码为 **1**，在记录的 RustSec 数据库快照下产生 **22 条错误：16 条漏洞公告、6 条停止维护公告，涉及 16 个包版本**。本次基线诊断没有改动 Cargo.lock、deny.toml、Rust 源码或测试，也没有运行训练或测试。

远端 R12 作业 124715983908 和 R13 作业 124730176835 的步骤摘要都显示 `Run cargo-deny` 失败、随后 clean-worktree 检查成功。但远端原始日志接口反复返回 `Transport closed`，所以本文件报告的是**同配置本地复现的确定依赖阻断**，不把它称为已读取的远端原始错误。

R12 `7d19d1f68b5c03f61c4ba92c42abf0cf4774d7c1` 与 R13 `eeb17ab1f4127d365025e9b1b53f9cc44eed01a5` 的 **202 个 Cargo 清单、锁文件、deny 配置及 cargo-deny 工作流 Git blob 完全相同**。其中当前本地实际存在的 201 个文件也逐个匹配；剩余工作流通过固定提交的 GitHub 内容接口核对。完整列表和对象哈希在同目录 JSON 中。

RustSec 数据库提交为 `2295466c4e9df26647fd67d8fa1c705ac2fc7f81`，22 个公告源文件各自的 SHA256 已记录。公告数据库会随时间变化，复现时必须核对快照。

## 完整错误清单及父链

下列“安全版本”是工具在该数据库快照中的报告，不代表已完成升级、编译兼容或运行路径的可利用性验证。停止维护并不等于已发现可利用漏洞。表中展示每个错误的一条最短第一方父链；JSON 保存全部解析到的直接父包、实际依赖别名和版本约束，以及最短第一方入口链。

| 包及锁定版本 | 错误类别 | 公告 | 工具报告的安全版本 | 一条第一方父链 |
|---|---|---|---|---|
| anymap2 0.13.0 | 停止维护 | [RUSTSEC-2026-0319](https://rustsec.org/advisories/RUSTSEC-2026-0319) | 该公告未列出同 crate 的安全升级版本 | codex-hepta-matrix-sdk → matrix-sdk → anymap2 |
| basic-toml 0.1.10 | 停止维护 | [RUSTSEC-2026-0374](https://rustsec.org/advisories/RUSTSEC-2026-0374) | 该公告未列出同 crate 的安全升级版本 | codex-secrets → age → i18n-embed-fl → i18n-config → basic-toml |
| crypto-bigint 0.5.5 | 漏洞公告 | [RUSTSEC-2026-0387](https://rustsec.org/advisories/RUSTSEC-2026-0387) | Upgrade to >=0.7.6 | codex-aws-auth → aws-config → p256 → elliptic-curve → crypto-bigint |
| matrix-sdk-crypto 0.18.0 | 漏洞公告 | [RUSTSEC-2026-0318](https://rustsec.org/advisories/RUSTSEC-2026-0318) | Upgrade to >=0.19.0 | codex-hepta-matrix-sdk → matrix-sdk → matrix-sdk-base → matrix-sdk-crypto |
| rustls 0.23.45 | 漏洞公告 | [RUSTSEC-2026-0346](https://rustsec.org/advisories/RUSTSEC-2026-0346) | Upgrade to >=0.23.46 | codex-exec-server → rustls |
| rustls 0.23.45 | 漏洞公告 | [RUSTSEC-2026-0347](https://rustsec.org/advisories/RUSTSEC-2026-0347) | Upgrade to >=0.23.46 | codex-exec-server → rustls |
| rustls 0.23.45 | 漏洞公告 | [RUSTSEC-2026-0348](https://rustsec.org/advisories/RUSTSEC-2026-0348) | Upgrade to >=0.23.46 | codex-exec-server → rustls |
| rustls 0.23.45 | 漏洞公告 | [RUSTSEC-2026-0349](https://rustsec.org/advisories/RUSTSEC-2026-0349) | Upgrade to >=0.23.46 | codex-exec-server → rustls |
| rustls-webpki 0.103.15 | 漏洞公告 | [RUSTSEC-2026-0382](https://rustsec.org/advisories/RUSTSEC-2026-0382) | Upgrade to >=0.103.16, <0.104.0-alpha.1 OR >=0.104.0-alpha.8 | codex-exec-server → rustls → rustls-webpki |
| unsafe-libyaml 0.2.11 | 停止维护 | [RUSTSEC-2024-0449](https://rustsec.org/advisories/RUSTSEC-2024-0449) | 该公告未列出同 crate 的安全升级版本 | codex-core-plugins → serde_yaml → unsafe-libyaml |
| webpki-root-certs 1.0.5 | 漏洞公告 | [RUSTSEC-2026-0383](https://rustsec.org/advisories/RUSTSEC-2026-0383) | Upgrade to >=1.0.10 | codex-feedback → sentry → ureq → webpki-root-certs |
| webpki-roots 1.0.9 | 漏洞公告 | [RUSTSEC-2026-0381](https://rustsec.org/advisories/RUSTSEC-2026-0381) | Upgrade to >=1.0.10 | codex-code-mode → reqwest → webpki-roots |
| zbus_names 3.0.0 | 停止维护 | [RUSTSEC-2026-0371](https://rustsec.org/advisories/RUSTSEC-2026-0371) | 该公告未列出同 crate 的安全升级版本 | codex-keyring-store → keyring → zbus → zbus_names |
| zip 2.4.2 | 漏洞公告 | [RUSTSEC-2026-0367](https://rustsec.org/advisories/RUSTSEC-2026-0367) | Upgrade to >=9.0.0 | codex-core-plugins → zip |
| zip 2.4.2 | 漏洞公告 | [RUSTSEC-2026-0368](https://rustsec.org/advisories/RUSTSEC-2026-0368) | Upgrade to >=9.0.0 | codex-core-plugins → zip |
| zip 2.4.2 | 漏洞公告 | [RUSTSEC-2026-0369](https://rustsec.org/advisories/RUSTSEC-2026-0369) | Upgrade to >=9.0.0 | codex-core-plugins → zip |
| zstd 0.13.3 | 漏洞公告 | [RUSTSEC-2026-0391](https://rustsec.org/advisories/RUSTSEC-2026-0391) | Upgrade to >=0.14.3 | codex-app-server-protocol → zstd |
| zstd-safe 7.2.4 | 漏洞公告 | [RUSTSEC-2026-0398](https://rustsec.org/advisories/RUSTSEC-2026-0398) | Upgrade to >=8.2.0 | codex-app-server-protocol → zstd → zstd-safe |
| zstd-safe 7.2.4 | 漏洞公告 | [RUSTSEC-2026-0403](https://rustsec.org/advisories/RUSTSEC-2026-0403) | Upgrade to >=8.2.0 | codex-app-server-protocol → zstd → zstd-safe |
| zstd-sys 2.0.16+zstd.1.5.7 | 漏洞公告 | [RUSTSEC-2026-0410](https://rustsec.org/advisories/RUSTSEC-2026-0410) | Upgrade to >=2.1.2 | codex-app-server-protocol → zstd → zstd-safe → zstd-sys |
| zvariant 4.2.0 | 停止维护 | [RUSTSEC-2026-0370](https://rustsec.org/advisories/RUSTSEC-2026-0370) | 该公告未列出同 crate 的安全升级版本 | codex-keyring-store → keyring → zbus → zvariant |
| zvariant_derive 4.2.0 | 停止维护 | [RUSTSEC-2026-0372](https://rustsec.org/advisories/RUSTSEC-2026-0372) | 该公告未列出同 crate 的安全升级版本 | codex-keyring-store → keyring → zbus → zvariant → zvariant_derive |

## 分阶段处置，保持检查规则

| 阶段 | 候选范围 | 公告覆盖数量 | 仍需完成 |
|---|---|---:|---|
| 1 | rustls 0.23.46、rustls-webpki 0.103.16、webpki-roots 1.0.10、webpki-root-certs 1.0.10 | 预期 7/22 | 独立候选实际解析、完整 cargo-deny 重跑、定向验证、`just bazel-lock-update` |
| 2 | Matrix SDK、AWS/椭圆曲线密码父链、zip、zstd 父链升级 | 另有 9/22 漏洞公告 | 超出当前部分版本约束；须核对 API、持久数据和平台兼容，逐阶段评审 |
| 3 | anymap2、basic-toml、unsafe-libyaml、zbus_names、zvariant、zvariant_derive 的维护中父链或替代实现 | 6/22 | 无该 crate 原版本线的公告安全版本；优先通过上游父包升级消除，不添加 ignore |

阶段覆盖数字是基线分组，不是已经关闭的数量；父依赖升级也可能同时消除多个组中的问题。候选结果另行记录，本基线证据保持原样。任何 Cargo 依赖变更必须同步 MODULE.bazel.lock。需要升级的父链包括：`matrix-sdk`；`aws-config → p256 → elliptic-curve`；`age → i18n-embed-fl → i18n-config`；`serde_yaml → unsafe-libyaml`；`keyring → zbus`。不会通过关功能、关测试或放宽 cargo-deny 规则消除检查输出。

## 诊断过程的边界

最初的 workspace-only metadata 只读取 193 个工作区包；完整离线解析当时因缺少锁定的 tungstenite Git checkout 失败，那只是本地缓存缺件。随后按正式审批流程取得官方 cargo-deny 二进制并读取依赖，完整 metadata 成功解析 **1517 个包及 1517 个节点**。这两个阶段已分开记录。

静态 Cargo.lock 曾显示 `matrix-sdk-indexeddb → async-trait` 不在直接 wrappers 表内；实际完整 cargo-deny 没有报告这一候选为 banned 错误，因此不能据此修改规则或称其为本次根因。锁里的边也不能代替工具实际构图和策略解释。

官方二进制下载归档 SHA256 为 `0e8c2aa59128612c90d9e09c02204e912f29a5b8d9a64671b94608cbe09e064f`，与官方发布 digest 一致。复现比 CI 额外使用 `--locked` 防止锁文件写入，并关闭颜色；两者未改变依赖审查规则。基线命令运行前后 Cargo.lock SHA256 都是 `8354b4cbdf14389db7aa5508e2ed5b524fc2d4c4ea0ecb475955c933f8bea389`，deny.toml SHA256 都是 `3713c011667dcbeda9edf1b2644a813f2b5253ebb7b2f3e98ea60aab69407352`。

## 复查材料

- `CARGO_DENY_DIAGNOSTIC.json`：命令、工具来源、22 条错误、父链、202 个输入对象、公告数据库及源文件哈希、远端步骤摘要、初始受限检查与后续成功解析。
- `CARGO_DENY_BASELINE.stderr.txt.gz.vol000` 和 `.vol001`：按 JSON 顺序拼接，再校验 gzip SHA256，解压后校验原始日志 SHA256；完整日志约 14.3 MB，分卷均不超过 480000 字节。
- `CARGO_DENY_DIAGNOSTIC.py.gz`：该证据 JSON 的汇总脚本。输入 JSON 在报告的 `evidence` 字段完整保存，可重建；原始 stderr 从上述分卷重建。工具执行命令及退出结果在 `evidence.run_summary`，此汇总脚本本身不执行网络、依赖更新或测试。

来源：[固定 action Dockerfile](https://github.com/EmbarkStudios/cargo-deny-action/blob/82eb9f621fbc699dd0918f3ea06864c14cc84246/Dockerfile)、[固定 action 配置](https://github.com/EmbarkStudios/cargo-deny-action/blob/82eb9f621fbc699dd0918f3ea06864c14cc84246/action.yml)、[官方 0.19.0 发布](https://github.com/EmbarkStudios/cargo-deny/releases/tag/0.19.0)、[固定 RustSec 快照](https://github.com/rustsec/advisory-db/tree/2295466c4e9df26647fd67d8fa1c705ac2fc7f81)。
