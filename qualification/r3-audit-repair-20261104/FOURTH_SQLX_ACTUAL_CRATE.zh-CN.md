# SQLx 实际 crate 身份增补

已核定：实际 native 缓存中的 `sqlx-sqlite 0.9.0` 与 `sqlx-core 0.9.0` 均记录 VCS 提交 `003b698e99e024f3621b8043a2426fde5b741171`。此前版本标签指向 `75bc0487eb661da811bb7a3c5d158f1bd463fef4`；旧报告明确未核 registry archive，原对象保持不变。

## 实际核验结果

- 完整 native receipt `93b99eb2fc88c5b8fd4b48f7efc0db8057e24d47` 的 196,031 字节与 SHA-256 已独立复核。
- 17 个嵌入文件全部重新计算字节数、SHA-256 与 Git blob，且逐项等于原收据的真实 archive member 记录。其中 11 个 Rust 文件（SQLite 8 个、Core 3 个）与两个固定 Git 提交均逐字相同。
- 两个 `Cargo.toml.orig` 也逐字等于实际 VCS 提交中的 package manifest。规范化 `Cargo.toml` 单独保留，不能拿 Git workspace manifest 冒充。
- SQLite 原归档：93,440 字节，SHA-256 `488e99c397a62007e4229aec669a179816339afc6d2620ca6fa420dbee2e982c`。
- Core 原归档：154,984 字节，SHA-256 `05b44e85bf579a8eeb4ceaa77a3a523baf2bf0e9bac7e40f405d537b5d2d5ccb`。
- 上述两个原归档哈希均与当前完整 Cargo.lock（Git blob `71fc8fa78b5afa076835b29790a5e6b0bd772558`）对应 package checksum 相等。两包的 `.cargo-checksum.json` 实际不存在；未补造值。

原生执行者实际读取并比对了已有归档成员。本独审者重新核了完整收据中的所有文件字节及 checksum 对应关系，未另行下载或重新解压二进制归档。这两个层次在 JSON 中分开记录。

## 两个 Git 提交的关系

原研究的 12 个完整主源文件全部相同。第 12 个是上游 workspace Cargo.toml，不是这两个 registry 子包的归档成员。完整 `sqlx-sqlite`、`sqlx-core`、`sqlx-macros-core` 与 `tests` 子树 Git tree 也相同。两根 tree 分别是 `67490ea20a61000a47e74e591b075e1e02e8fb87` 与 `f2d8d0148472a0f13eb2c3abaf0c7ea5a3c5ee56`，根目录唯一不同项是 README.md；不称全库身份相同。

因此目前没有发现会改变 R2c/d/e 或原生 lifetime token 草案的源码/API 差异，但后续依赖方案必须记录真实 VCS 原点、规范化 manifest 与原归档校验。实际 SQLite crate 的规范化 Cargo.toml 未发布 Git manifest 中的 path-only sqlx dev dependency；新测试不能假定它存在。

此次只补证身份。未修改 native、依赖或锁，未编译 B 批次，未运行新控制，也未证明 Current/Root 接线或 B16 完成。
