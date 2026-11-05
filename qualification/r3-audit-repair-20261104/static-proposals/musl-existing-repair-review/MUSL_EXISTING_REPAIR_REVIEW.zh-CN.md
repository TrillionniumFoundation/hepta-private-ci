# 真正 musl 链接失败与既有修复的独立复核

**结论：现有 `c8f5d3c7b96e9d649cf34f6cfcac3d7b1912ed5e` 中的两路径 musl 候选已覆盖本次确证的配置根因；不需要再叠加平台映射补丁。此结论仅为静态接受，真实新源码构建、ELF 和进程 smoke 仍待原工作流验收。**

## 已证明的失败链

原 run `41902318446`、job `126827727706` 使用 PR head `cabcb40d36e116beaa65750e1f674c52035da785` 的合成提交 `28af7f705fa1024b9a6d2ef751fec116002260eb`，tree `b2d7f038d6d88156bc6a4cb29c8703f69b808f29`。构建一次，1088.832641159 秒后 exit 1，源码前后相同；没有合格产品哈希或进程 smoke。原收据保存于 `e95871fa957364dc4cbd2f26b5a0d49f0e41c05a` 的完整嵌入成员。

失败首先落在 `//codex-rs/bwrap:bwrap`。原 stderr 第 336 行的同一 Rust 动作，同时包含 `--target=x86_64-unknown-linux-gnu`、GNU `rustlib` 搜索路径和 `--codegen=link-arg=x86_64-linux-musl`。随后 `open64`、`fstat64`、`lseek64`、`stat64`、`mmap64` 的未定义引用明确来自该 GNU `libstd`。这比工作流名称或编译器宿主名称更直接地证明 Rust 产品 ABI 与 C 链接 ABI 不一致。

固定 [rules_rs 0.0.96 的独立 Linux libc 约束](https://github.com/hermeticbuild/rules_rs/blob/87811fbf13177eff8f118a808610fe3a4fd0eed7/rs/platforms/constraints/BUILD.bazel) 默认选择 glibc；[工具链选择](https://github.com/hermeticbuild/rules_rs/blob/87811fbf13177eff8f118a808610fe3a4fd0eed7/rs/toolchains/declare_rustc_toolchains.bzl) 同时据此选择 Rust target 和标准库。原 LLVM-only 平台仅设置 LLVM libc 等约束。rules_rs 已发布的 [完整 musl triple 平台](https://github.com/hermeticbuild/rules_rs/blob/87811fbf13177eff8f118a808610fe3a4fd0eed7/rs/platforms/triples.bzl) 则同时设置 Rust musl、LLVM musl 和相应 PIE 合同。

## 既有候选覆盖与保留的门

| 路径 | 原 blob | 候选 blob | 本次结论 |
|---|---|---|---|
| `bazel/platforms/release_binaries.bzl` | `7ac59c2b5e1f670d1653c2b3efdd8a82f2963bdc` | `7a88987f54fce5d6062eb7258a7f8679975de90d` | 两个既有 musl 别名改用完整 rules_rs 平台，其他映射保留 |
| `.github/workflows/hepta-musl-product-smoke.yml` | `6aad46b1fe0edcf315ef8b1a5546225c59efe235` | `a157c21a3e79460dc6f32147d952f3dacb4ed197` | 同平台构建前核 CLI 与实际失败 bwrap 的 Rust 动作；实际产品门保留 |

完整既有 patch 为 `3fd46e3fe77e18899c34b9fd8114f5f438f0406c`，两路径共 65 行增删。本次在隔离目录实际 `git apply --check` / `git apply` 后，两份 postimage 逐字吻合。新动作门只增加必要条件，不能单凭 cquery 通过成为合格产品。

原 4,144 字节的产品与 smoke 检查块逐字不变：真实文件位于 Bazel 输出内、外层/内层产物为同一物理文件、ELF64/x86_64、没有 `PT_INTERP` 和 `DT_NEEDED`、实际同一二进制 `--version` 与 `--help` 各 30 秒、源码和产物执行前后哈希不变。原 job/step 预算和缓存政策保留；没有借 GNU loader 执行。

## 证据范围与下一原验收

本次逐体校验 28 个固定来源的 bytes/SHA256/Git blob，另核原诊断中三个完整成员；读取的是原 666 行 stderr 的 85 行固定诊断投影，并非重新下载 ZIP 或声称新做全量 CRC 验证。上游 tag/固定源码已核，未重新下载发行归档，也未重审整份 MODULE 锁的 MVS 解析。原实际 GNU Rust/musl C 命令不依赖这些未完成项即可成立。

下一最终源码使用原 `hepta-musl-product-smoke` 工作流，保留真实目标 `//codex-rs/cli:hepta_linux_amd64_musl`、完整平台 `@rules_rs//rs/platforms:x86_64-unknown-linux-musl`、原 lock gate 与 `--remote_download_toplevel`。必须取得实际 cquery 动作、构建退出码、物理 ELF/哈希和两个原进程 smoke 收据。之前 GNU/RBE 的 441 个通过目标、静态接受或 arm64 映射存在都不能代替此验收；完整 musl 业务行为与 Alpine 部署资格仍是另外的门。

本次没有执行 native/Cargo/Bazel，没有修改共享源码、index、target 或任何 ref，也没有创建重复产品补丁。机器可读细节与逐体身份见同目录 `independent-review.json`、`static-verification.json`。
