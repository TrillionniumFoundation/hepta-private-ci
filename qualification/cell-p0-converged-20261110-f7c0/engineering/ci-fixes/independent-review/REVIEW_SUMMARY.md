# 四项独立源码审查归档

结论：四个固定补丁均未发现源码审查范围内的阻塞项。本文件整理已经完成的审查，没有重审、编译、运行 native 或重复完整 caller scan。机器可读的完整提交、文件哈希、不变量、原路径与限制见 `INDEPENDENT_REVIEWS.json`。

## 固定提交

| 审查 | Commit | Tree | 实际变更 |
|---|---|---|---|
| 格式与 guard 作用域 | `e453a28965ed0364fd5691129a5a5836ecdc85b9` | `947b0bb93c1c903e67fda29e51f640be84497b27` | 两个 YAML、一个 Markdown、一个 watcher 测试文件 |
| Matrix 原始错误诊断 | `7b5ff407bb33ccbf1fc067aefb9c2b37e202ed55` | `759aab567611416d20b96aa25a0df29974b62f1b` | SDK、sync 测试、migration 测试共三个文件 |
| Bazel 单 crate 优化 | `7d5c776dca0245a498896f612a24f5412271bb63` | `798442817120be74ac71583eda6e5be371910145` | MODULE.bazel 增加 7 行 |
| training-stage 宏歧义 | `03f4bfea4cc96ef3bb2ec743b7501a45ddf756b8` | `b2a21d98380340b1c091006f4130aafdbeabca50` | 测试文件增加 1 行显式 import |

## 已核不变量

**格式与 guard：** 两个 YAML 各只删除一个文件末尾换行；Markdown 仅表格填充和分隔线宽度变化，单元格、对齐语义和其他内容不变。原 retained guard 及四条断言完整进入词法 block，后续 await 位于 block 外。旧源码已有显式 drop，因此这项结论是 Clippy 作用域修复，不能说已观察到运行时死锁。生产输出代码、CALLERS 与 verifier 未改变。

**Matrix：** 三处 build timeout 保留内层 `??`，配置和身份拒绝继续保持原顶层分类。原 5 秒 timeout 边界、passphrase、存储路径、恢复成功路径和 drop 后仅一次 fresh login 均保持。六条错误检查仍精确检查两处 Sync、三处 Store、一处 Configuration；原 snapshot/checkpoint 断言保留。当前唯一依赖 crate hepta-matrixd 统一传播错误，没有按这些顶层变体选择重试或重登。

Matrix 的公开 API 确有变化：Initialization 从 unit 改为带 stage/source 的 struct variant，新增 RestoreFallback，并移除 Clone/Copy/Eq/PartialEq。当前仓库内六处 PartialEq 测试依赖已适配，未找到 Copy/Clone 消费。Error::source 的 RestoreFallback 链只沿 fallback，restore 原 SDK/Elapsed 保存在字段与 Debug；直接认证路径原 Authentication 映射仍未改写。跨 crate Send/Sync/static 约束从源码核对，不替代编译验证。

**MODULE：** rules_rs 0.0.96 先按 repository 过滤，再精确匹配 version 字符串，因此仅选中 crates 仓的 matrix-sdk-store-encryption 0.19.1。仅增加 `-Copt-level=3`，其 target flags 在默认 compilation-mode flags 后传入。Cargo.toml、Cargo.lock、MODULE.bazel.lock、Matrix sdk.rs 父子 blobs 相同；timeout、KDF、passphrase、依赖版本和其他 crate 设置不变。原 Cargo 已有同 crate opt-level=3。旧 Bazel artifact 的 opt-level=0 记录只证明配置差异，不能证明旧失败由 KDF 超时导致，也不能证明新候选已通过。

**宏 import：** 从新文件删除 `use pretty_assertions::assert_eq;` 后，字节完全复原父提交文件。六个测试及全部断言、输入、预期和执行顺序均未改变；父 receipt-owner 测试本来就导入同一宏。

## 证据范围

本归档是审查结论记录，不是原始 CI 日志，也不是执行通过 receipt。四次 review 均未运行 native/编译/full caller；fixtures 不计为独立收益样本。Buildifier/fmt 和 metadata-only lock 检查归对应执行者原记录，本报告不冒称自行执行或 lock 已通过。

各文件 SHA-256 绑定 JSON 中的固定 commit。工作树路径用于回查，工作树 HEAD 此后可能变化。合并后的本地候选为 03f4bfea/tree b2a21d；发布身份及其最终完整 caller 结果待 root 后续提供和执行。原 cb0598 全量 caller receipt 保留在 `/workspace/scratch/f7c0ded86bcc/p0_final_caller_audit_cb0598_20261111`，没有移用于新候选。
