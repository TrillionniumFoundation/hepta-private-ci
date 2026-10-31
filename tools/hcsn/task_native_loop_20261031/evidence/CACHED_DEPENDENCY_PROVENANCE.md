# 缓存依赖来源复核

本次复核绑定 `BUILD_ATTEMPT03.json`，没有修改依赖版本、缓存源文件、编译用 vendor 副本或构建脚本。7 个缺失 `.crate` 归档的包，均从实际 `Cargo.toml` 与 `.cargo_vcs_info.json` 读取 repository 和 commit，再通过 GitHub connector 获取该精确 commit 的完整递归 Git tree。

**结果：267 个可对应上游文件的 Git blob 全部一致，0 个差异、0 个缺失。** 其中 133 个文件属于 `src/` 或 `build.rs`，覆盖所有缓存源目录和构建入口；其余核对包括原始 manifest、许可证、测试与其他已打包文件。每包的 `Cargo.toml.orig` 均与上游 `Cargo.toml` 字节一致。

| 包 | 上游 commit | 匹配文件 | 其中 src/build |
|---|---|---:|---:|
| cfg-if 1.0.5 | [8b0a2b0](https://github.com/rust-lang/cfg-if/commit/8b0a2b0fc1fa3b3741b9e72895f390cf499fe36f) | 11 | 1 |
| memchr 2.8.3 | [5fdb40c](https://github.com/BurntSushi/memchr/commit/5fdb40c054e1fff359a2f7bdf7f87a13b34b465d) | 56 | 45 |
| proc-macro2 1.0.107 | [ed8a549](https://github.com/dtolnay/proc-macro2/commit/ed8a5497669cd63db33bf24646f261b012bbbc4a) | 30 | 16 |
| quote 1.0.47 | [723dcb4](https://github.com/dtolnay/quote/commit/723dcb47d3f0ddc896e17287c8a8d3f2ea2317d5) | 32 | 8 |
| syn 3.0.9 | [7c44a55](https://github.com/dtolnay/syn/commit/7c44a5565b4421035101cc16184e9af08ab5fc77) | 101 | 56 |
| unicode-ident 1.0.27 | [c1ac3af](https://github.com/dtolnay/unicode-ident/commit/c1ac3afb721f3cea6527bc2255340a04d0de3ca0) | 23 | 2 |
| zmij 1.0.23 | [7b7cc48](https://github.com/dtolnay/zmij/commit/7b7cc48b58028e8af7be87e94c0c1c8936f1a57c) | 14 | 5 |

全部 **295 个缓存文件**（包含生成元数据）的 SHA256 同时匹配实际编译使用的 vendor 副本与 `BUILD_ATTEMPT03.source_files`，重新计算的 7 个 source snapshot digest 也完全匹配。逐文件证据、Git tree URL、commit、blob SHA1、文件 SHA256 与检查结果见同目录 `CACHED_DEPENDENCY_PROVENANCE.json`。

28 个生成文件分开处理：每包的 normalized `Cargo.toml`、`Cargo.lock`、`.cargo_vcs_info.json`、`.cargo-ok`。normalized manifest 的依赖、features、target 条件、库入口、build 入口及原有 package 字段均通过语义比较；字符串依赖展开、开发依赖 path 移除、显式目标生成与 workspace/patch 移除均记录。memchr 的 profile `debug=true` 被 normalized 为 `debug=2`，这是 [Cargo 官方文档](https://doc.rust-lang.org/cargo/reference/profiles.html#debug) 规定的同义值。生成的 `Cargo.lock` 没有被误判为上游源文件差异。

**原始 `.crate` 归档仍未取得，因此 7 包 `archive_checksum_verified` 继续为 `false`。** 本结果补充了缓存源与上游精确 Git commit 的一致性证据；没有声称重建或验证发布归档的压缩字节，也没有改变原构建记录中的这一限制。
