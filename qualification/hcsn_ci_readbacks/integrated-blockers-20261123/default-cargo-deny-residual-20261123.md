# main 派生 cookie 修补后的原生 cargo-deny 剩余告警全集

本清单基于 2026-11-23 原生 GitHub [45165845066 / 137662452404](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45165845066/job/137662452404) 的具名原日志，由日志 RUSTSEC ID 和相邻 Cargo.lock 库名/版本逐项复算。诊断 head `7fb858bf3e62b5b35aabe866d6a6b9fc71ba5afd` 实际固定检出锁候选 `86d13925f313caaca0e674e47eb6c89a932d9976`（从 main 冻结 `732e934ba496d90fbe042b8d41d479ef901643e5` 改动**仅两个锁**）。原 Cargo/Bazel 锁校验成功，原 cargo-deny 失败。**未重新派发作业。**

共 59 条不同 RUSTSEC 编号，分属 26 个 crate；漏洞类 51、维护停止类 8。这不是相同数量的不同生产可利用路径。另有原 warning 指向 yanked `chacha20`、`clipboard-win`、`spin`，不算入下表。原终局 `advisories FAILED; bans/licenses/sources ok`；绝不通过 ignore/白名单或更改策略伪造绿门。

| Cargo.lock crate | 原锁版本 | 类别 | 原具名 RUSTSEC 编号（统一前缀 RUSTSEC-） |
|---|---|---|---|
| `anymap2` | `0.13.0` | 维护停止 | 2026-0319 |
| `basic-toml` | `0.1.10` | 维护停止 | 2026-0374 |
| `chrono` | `0.4.43` | 维护停止 | 2026-0543 |
| `crypto-bigint` | `0.5.5` | 漏洞 | 2026-0387 |
| `hickory-proto` | `0.25.2` | 漏洞 | 2026-0487 2026-0489 2026-0490 2026-0491 2026-0504 2026-0505 2026-0511 2026-0512 2026-0530 2026-0531 2026-0532 2026-0549 2026-0550 2026-0551 |
| `hickory-resolver` | `0.25.2` | 漏洞 | 2026-0514 |
| `libsqlite3-sys` | `0.37.0` | 漏洞 | 2026-0459 |
| `matrix-sdk-crypto` | `0.18.0` | 漏洞 | 2026-0318 |
| `openssl` | `0.10.75` | 漏洞 | 2026-0463 2026-0473 2026-0474 2026-0475 2026-0476 2026-0477 2026-0478 2026-0479 |
| `pin-utils` | `0.1.0` | 维护停止 | 2026-0441 |
| `rmcp` | `3.1.3` | 漏洞 | 2026-0457 2026-0461 2026-0462 |
| `ruma-identifiers-validation` | `0.12.1` | 漏洞 | 2026-0588 2026-0589 |
| `rustls` | `0.23.45` | 漏洞 | 2026-0346 2026-0347 2026-0348 2026-0349 |
| `rustls-webpki` | `0.103.15` | 漏洞 | 2026-0382 |
| `unsafe-libyaml` | `0.2.11` | 维护停止 | 2024-0449 |
| `url` | `2.5.8` | 漏洞 | 2026-0592 |
| `vodozemac` | `0.10.0` | 漏洞 | 2026-0451 2026-0510 |
| `webpki-root-certs` | `1.0.5` | 漏洞 | 2026-0383 |
| `webpki-roots` | `1.0.9` | 漏洞 | 2026-0381 |
| `zbus_names` | `3.0.0` | 维护停止 | 2026-0371 |
| `zip` | `2.4.2` | 漏洞 | 2026-0367 2026-0368 2026-0369 2026-0429 2026-0545 2026-0548 |
| `zstd` | `0.13.3` | 漏洞 | 2026-0391 |
| `zstd-safe` | `7.2.4` | 漏洞 | 2026-0398 2026-0403 |
| `zstd-sys` | `2.0.16+zstd.1.5.7` | 漏洞 | 2026-0410 |
| `zvariant` | `4.2.0` | 维护停止 | 2026-0370 |
| `zvariant_derive` | `4.2.0` | 维护停止 | 2026-0372 |

对照：#7032 精确科学源码上的独立两锁修复 `b1af67a38f8cf9cee700cc067da1e6001ce220a8` 在 [45165787601](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45165787601) 完成原 cargo-deny、Cargo 重建和 Bazel 锁重建 **3/3**，但不能据此把 main 或原 #7032 未修复 SHA 判绿。完整证据见 [双依赖图记录](cookie-7032-paired-security-20261123.md)。这份仅是故障清单，未进行生产代码/依赖变更，发布和原全仓资格仍 HOLD。
