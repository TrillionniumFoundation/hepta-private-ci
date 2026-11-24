# 默认分支安全图与已通过科学候选的静态差异复算（2026-11-24 UTC）

本轮从 GitHub 精确源码重新读取完整 Cargo.lock 与 workspace Cargo.toml；未重新派发历史作业。main 仍为 `732e934ba496d90fbe042b8d41d479ef901643e5`；默认分支锁候选 `86d13925f313caaca0e674e47eb6c89a932d9976` 与已通过安全门的科学候选 `b1af67a38f8cf9cee700cc067da1e6001ce220a8` 不是同一依赖图。

- [main 派生候选锁](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/86d13925f313caaca0e674e47eb6c89a932d9976/codex-rs/Cargo.lock) blob `fe57c533e45e4e0b549da17c9a1ec2a8e21d34f1`，1517 package 记录。
- [科学候选锁](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b1af67a38f8cf9cee700cc067da1e6001ce220a8/codex-rs/Cargo.lock) blob `e5d61c8f7478700f481a35b1902160089ee80b64`，1540 package 记录。
- 两份 manifest blob 分别为 `d2703b590935ab17316e6c258657c0ce5ab7412a` 与 `38944025536086b5bde79792bd59e4c7eecbac62`。按 TOML `[[package]]` 分段提取 name/version/source 及直接依赖。依赖父列表是锁记录边，不等于启用 feature 的生产调用图。

## 26 个原告警 crate 的逐项对照

同名版本改变 19 个；原同名 package 不再出现在对照锁 6 个；另 1 个 anymap2 同版本但源从 registry 变为本地 path。此为静态清点，不是对 main 的安全修复或新的 cargo-deny 运行。

| Crate | main 派生锁 | 科学候选锁 | main 锁中的直接父包 |
|---|---|---|---|
| anymap2 | 0.13.0 | 0.13.0 | matrix-sdk@0.18.0 |
| basic-toml | 0.1.10 | — | i18n-config@0.4.8 |
| chrono | 0.4.43 | 0.4.45 | app_test_support@0.0.0, codex-agent-identity@0.0.0, codex-api@0.0.0, codex-app-server@0.0.0, codex-app-server-transport@0.0.0, codex-cli@0.0.0, codex-cloud-config@0.0.0, codex-cloud-tasks@0.0.0, codex-cloud-tasks-client@0.0.0, codex-cloud-tasks-mock-client@0.0.0, codex-core@0.0.0, codex-core-plugins@0.0.0, codex-external-agent-migration@0.0.0, codex-git-utils@0.0.0, codex-goal-extension@0.0.0, codex-hepta-memory-extension@0.0.0, codex-hooks@0.0.0, codex-login@0.0.0, codex-memories-write@0.0.0, codex-models-manager@0.0.0, codex-network-proxy@0.0.0, codex-otel@0.0.0, codex-protocol@0.0.0, codex-rollout@0.0.0, codex-state@0.0.0, codex-thread-store@0.0.0, codex-tui@0.0.0, codex-windows-sandbox@0.0.0, oauth2@5.0.0, rama-http@0.3.0-alpha.4, rama-http-headers@0.3.0-alpha.4, rmcp@3.1.3, schemars@1.2.1, serde_with@3.17.0, sqlx-core@0.9.0, sqlx-mysql@0.9.0, sqlx-postgres@0.9.0, sqlx-sqlite@0.9.0 |
| crypto-bigint | 0.5.5 | 0.7.10 | elliptic-curve@0.13.8 |
| hickory-proto | 0.25.2 | 0.26.3 | hickory-resolver@0.25.2 |
| hickory-resolver | 0.25.2 | 0.26.3 | rama-dns@0.3.0-alpha.4 |
| libsqlite3-sys | 0.37.0 | 0.39.1 | codex-state@0.0.0, rusqlite@0.39.0, sqlx-sqlite@0.9.0 |
| matrix-sdk-crypto | 0.18.0 | 0.19.1 | matrix-sdk-base@0.18.0, matrix-sdk-indexeddb@0.18.0, matrix-sdk-sqlite@0.18.0 |
| openssl | 0.10.75 | 0.10.81 | native-tls@0.2.14 |
| pin-utils | 0.1.0 | — | aws-smithy-http@0.62.6, aws-smithy-runtime@1.9.5, aws-smithy-types@1.4.7, hyper@1.8.1, loom@0.7.2 |
| rmcp | 3.1.3 | 3.9.0 | codex-app-server@0.0.0, codex-app-server-protocol@0.0.0, codex-core@0.0.0, codex-mcp@0.0.0, codex-mcp-server@0.0.0, codex-rmcp-client@0.0.0, codex-tools@0.0.0, codex-tui@0.0.0, mcp_test_support@0.0.0 |
| ruma-identifiers-validation | 0.12.1 | 0.14.0 | ruma-common@0.19.0, ruma-macros@0.19.0 |
| rustls | 0.23.45 | 0.23.46 | aws-smithy-http-client@1.1.12, codex-exec-server@0.0.0, codex-hepta-bao-adapter@0.0.0, codex-http-client@0.0.0, codex-utils-rustls-provider@0.0.0, codex-websocket-client@0.0.0, hyper-rustls@0.27.7, matrix-sdk@0.18.0, quinn@0.11.9, quinn-proto@0.11.14, rama-tls-rustls@0.3.0-alpha.4, reqwest@0.12.28, reqwest@0.13.4, rustls-platform-verifier@0.7.0, sqlx-core@0.9.0, tokio-rustls@0.26.4, tokio-tungstenite@0.28.0, tungstenite@0.27.0 |
| rustls-webpki | 0.103.15 | 0.103.16 | rustls@0.23.45, rustls-platform-verifier@0.7.0 |
| unsafe-libyaml | 0.2.11 | — | serde_yaml@0.9.34+deprecated |
| url | 2.5.8 | 2.5.9 | actix-web@4.12.1, app_test_support@0.0.0, aws-config@1.8.12, codex-api@0.0.0, codex-app-server@0.0.0, codex-app-server-client@0.0.0, codex-app-server-test-client@0.0.0, codex-app-server-transport@0.0.0, codex-backend-client@0.0.0, codex-cli@0.0.0, codex-core@0.0.0, codex-core-plugins@0.0.0, codex-exec-server@0.0.0, codex-hepta-bao-adapter@0.0.0, codex-hepta-matrix-protocol@0.0.0, codex-hepta-matrix-sdk@0.0.0, codex-hepta-matrixd@0.0.0, codex-linux-sandbox@0.0.0, codex-login@0.0.0, codex-mcp@0.0.0, codex-model-provider@0.0.0, codex-network-proxy@0.0.0, codex-rmcp-client@0.0.0, codex-sandboxing@0.0.0, codex-shell-command@0.0.0, codex-skills-extension@0.0.0, codex-tui@0.0.0, codex-utils-path-uri@0.0.0, codex-web-search-extension@0.0.0, codex-websocket-client@0.0.0, codex-workload-identity@0.0.0, cookie_store@0.22.1, hickory-proto@0.25.2, matrix-sdk@0.18.0, matrix-sdk-crypto@0.18.0, oauth2@5.0.0, reqwest@0.12.28, reqwest@0.13.4, rmcp@3.1.3, ruma-client-api@0.24.0, ruma-common@0.19.0, sentry-core@0.46.1, sentry-types@0.46.1, sqlx-core@0.9.0, sqlx-macros-core@0.9.0, sqlx-sqlite@0.9.0, webbrowser@1.2.4, wiremock@0.6.5 |
| vodozemac | 0.10.0 | 0.11.2 | matrix-sdk@0.18.0, matrix-sdk-crypto@0.18.0, matrix-sdk-sqlite@0.18.0 |
| webpki-root-certs | 1.0.5 | 1.0.10 | rustls-platform-verifier@0.7.0, ureq@3.1.4 |
| webpki-roots | 1.0.9 | 1.0.10 | hyper-rustls@0.27.7, matrix-sdk@0.18.0, rama-tls-rustls@0.3.0-alpha.4, reqwest@0.12.28, sqlx-core@0.9.0 |
| zbus_names | 3.0.0 | — | zbus@4.4.0 |
| zip | 2.4.2 | 9.1.3 | codex-core-plugins@0.0.0 |
| zstd | 0.13.3 | 0.14.3 | codex-app-server-protocol@0.0.0, codex-cli@0.0.0, codex-core@0.0.0, codex-http-client@0.0.0, codex-queue-extension@0.0.0, codex-rollout@0.0.0, codex-thread-store@0.0.0, core_test_support@0.0.0, zip@2.4.2 |
| zstd-safe | 7.2.4 | 8.2.0 | zstd@0.13.3 |
| zstd-sys | 2.0.16+zstd.1.5.7 | 2.1.2+zstd.1.5.7 | zstd-safe@7.2.4 |
| zvariant | 4.2.0 | — | zbus@4.4.0, zbus_names@3.0.0 |
| zvariant_derive | 4.2.0 | — | zvariant@4.2.0 |

## 实际迁移约束

- main workspace 对 rmcp 精确固定 =3.1.3，科学候选为 =3.9.0 且使用本地 third_party/rmcp-3.9.0-time；zip 从 2.4.2 到 =9.1.3（本地 third_party/zip-9.1.3），zstd 从 0.13 到 0.14.3；不能仅复制 lock。
- Matrix SDK 0.18.0→0.19.1 同时牵涉 rusqlite 0.39.0→0.41.1 与 libsqlite3-sys 0.37→0.39.1；main 的已有 SQLite 兼容说明不可直接覆盖。anymap2 0.13.0 在科学候选锁不再有 registry source/checksum，manifest 明示 third_party/anymap2-compat；相同版本不代表同一源。
- hickory 0.25.2→0.26.3 对应 rama-dns 0.3.0-alpha.4→0.3.0。需迁移并验证原网络代理及 TLS 行为。
- main 与科学候选的 deny.toml blob 分别为 `677f941360b2d82ab96aa4d419d97f4616cc2194` 与 `f23c418ec8cb3e8eaabf78f95d21cb6cb44fb533`；后者 advisories ignore=[]，不是通过新增忽略条目取得绿门。两份配置并非完全相同，不可把整文件复制视为局部修复。

建议先拆分 semver 兼容锁更新与需要源码/本地补丁的迁移组，原 Cargo+Bazel 双锁生成、原 cargo-deny、各组原行为测试及全仓 gate 分别取证。保留原 59 告警及 #7032 局部通过身份。无产品变更、无 CI 重跑、无红门合并。
