# B16 driver 下一执行批次：固定输入与门槛复核

**静态输入可供后续绑定；目前未授权或执行 driver。** 必须先取得完整 foundation `QUALIFIED` 终态、实际末树、双锁和对应的完整 metadata。第一组 4/4 PASS 只覆盖该组，不能代替这一前提。

## 精确源码范围

冻结 V7 的 `driver-adoption` 共 61 路径：仅修改既有 `codex-rs/Cargo.toml`（`4713741651affd053bb8ae5aa8b5d76831c15c0e` → `ef34e2f3926055d868a00ceafb3ac4694d7156ed`），新增 60 个 vendor 文件。全部后像已重新从原 payload 按字节数、SHA256、Git blob 核验；完整路径表在 review.json。

原发布包 57 个成员的 bytes/mode 证据保留。新增两个 lifetime 文件、BUILD、dev-runtime 边、两个完整 license overlay 和 100644 规范化各自明确，不把 vendor 全体冒称原包逐字一致。嵌套的发布包 Cargo.lock 不是 workspace 活动锁。

## 顺序与恢复

| B16 内部阶段 | 必需操作 | 实际资格 |
|---|---|---|
| B11 | 61 路径采用；真实 Cargo resolution；原 Bazel update/check；实际 DEP_DATA/rule/deps | 仅真实生成与依赖接入，不预填锁 hash |
| B12 | 仅 establish 的 token clone → None | 原 2 父例须在物理锁探测、callback 仍阻塞和唯一断言处失败；finally 精确恢复 |
| B13 | 仅 handle 删除 forget(token) | 原 1 父例须先证明 BUSY close、WorkerCrashed、原 statement 仍返回 ROW，再命中物理锁断言；finally 精确恢复 |
| B14 | 全部 8 原 driver 例 + 4 新父例 | 12 PASS，0 retry；1 ignored 子入口分列 |
| B15 | 原真实新 Bazel target build | 只证明编译与注册，不宣称 Bazel 测试或平台 CI 通过 |

B12 精确恢复 `establish.rs`：`4e31d9fc66df45eab48b24643f87e5cb52258241` → `7bf04f3f06165371bfbe525c61cbaafa0c46667f`。B13 精确恢复 `handle.rs`：`e106e9ec8dd3e5b33ccde609ed22449709f1a488` → `ed7f2a0798a30f4e3574d0e6e685ac9b41aae1a6`。两对逆变更已按源码身份核验。编译/准备/超时失败不能冒充因果负控；负控恢复不代表测试通过。锁生成失败保留原变更和错误，不做隐式整树回滚。

## 真实依赖与原命令

当前实际 P4 graph 的 sqlx-sqlite 是 registry 0.9.0、8 个原 feature；sqlx-core 已有 `_rt-tokio`，libsqlite3-sys 为 0.37.0、links=sqlite3。采用后须实际观察唯一 local driver 成为新增 workspace member；预期 194 members / 1501 nodes，其他解析节点仅允许必要 ID 映射且 feature/deps 不变。新增 dev-runtime 边须实际出现在 metadata。

`b16_native.py` 使用全 workspace、无 `-p` 的原 build/list/just 路径与 exact nextest 选择，保持 A 的统一 feature graph。epoch 内旧 authored argv 仅保留来源，不能用它冒称执行命令。原 `run-nextest.py` 已提供 no-fail-fast，V7 不重复传入。所有实际 command/raw/JUnit/source/binary/helper 身份应从新运行取得。

## 后续具体 binding 必填

继续保留 `BUILD_ONLY_CURRENT_HOST`、原 P4 build-only 对象、历史 ROG fb9 测试和 40bd hygiene 来源。下一 epoch 的 `initial_tree` 必须等于 foundation 实际末树；`baseline_metadata.source_tree` 必须对应这一树，不能把旧 P4 4a metadata 直接改标签。普通 HEAD/index、source/target/owner、8 工具、原环境、两 SDK 和 V8 的物理输入保持原审核边界。

只有 driver 可创建一个新的 task-owned B Bazel cache。原 user.bazelrc 若存在即拒绝，不覆盖；临时配置仅在 exact pin 校验后清理。整个阶段不清理已有 cache。

## 容量

新 host P4 的 363 program + 33 helper 共 396 文件，原文件字节合计 **18,517,479,536 B**。driver 不适用 foundation 的 22 GB 例外：至少一额外 family，加 12 GB Cargo、8 GB Bazel、2 GB evidence 和 8 GB reserve，当前计划门槛为 **48,517,479,536 B**。这只是估算门，不是峰值证明；运行前需要 fresh free，不能引用旧时点、删缓存或临时降预算。

这些 B11–B15 是 **B16/phase 内部编号**，不改变原 23 项 blocker 的状态。本文没有新测试、原生执行、源码或 ref 变更；后续 pool/checkpoint 与真正 Current/Root 接线仍独立开放。
