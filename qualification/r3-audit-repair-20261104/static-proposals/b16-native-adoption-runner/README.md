# B16 后续原生验收准备

这份交付是供唯一执行者使用的机器计划、源码组合证明和只读收据检查器。**尚未运行 B 阶段的 Cargo、Bazel 或物理控制，也没有修改 ROG 源码、目标目录、缓存或 refs。** 最终 A 源码树须在最后一次 fix/fmt 后由 root 冻结；计划不把旧 cabc/f825 当成可覆盖的现有源码。

## 必须保持的次序

| 阶段 | 实际范围 | 前置条件 |
|---|---|---|
| Foundation | 原 R2c V3 → R2d → R2e1 → R2e2a/b → R2e3，共 24 个不同新增控制 | 逐路径验证最终 A 的原始后像；保留 R2c 实际 SQLite 版本观察 |
| SQLx adoption | 完整已核对的 57 成员原包、许可证机械补全、60 文件 vendor 内容、真实 workspace/BUILD 注册；8 原单测 + 4 新物理控制 | 原 Cargo metadata、Bazel lock update/check 真正成功；确认唯一实际选中本地 driver |
| 两个 pool | 实际 guarded/coordinated 构造把原 OpenGuard 传入 native token，2 个 state + 1 个 Memory 控制 | Driver 已执行；先负控再精确恢复与正向验证 |
| 私有 checkpoint | 实际 recovery → checkpoint 的原 owner 绑定；1 新物理控制与 14 个原 Linux recovery 用例 | 新 Memory libsqlite3-sys dev-edge 的第二次真实 Cargo/Bazel 生成门 |
| 原 owning 与 hygiene | 原 state/Memory owning 用例、scoped just fix、just fmt、最终锁检查 | 保留完整原始输出、实际 catalog、源码/二进制身份及终态 |

不能把两 pool 的 native token 绑定提前：它会在移除旧 commit-hook/collation anchor 后仍正确持有真实文件锁，使 R2e3 原反事实失去预定的因果含义。该情况不能被误称为产品回归，也不能靠放宽旧断言解决。

`execution-plan.json` 保留 21 个执行阶段的具体参数、补丁身份、预期后像、负控与恢复、原始门禁和证据要求。32 是不同的新增控制数；加上 8 个原 driver 用例，核心集合是 40 个不同用例，阶段重复运行不能累加成新的用例。3 个 ignored owned-child support 单独列出，不算额外 PASS。完整 owning 数量只能来自之后的实际 catalog。

## 已完成的静态工作

`prepare_execution_plan.py` 在独立 scratch 目录对已固定 foundation 最终源、完整 vendor 清单、两 pool 和 checkpoint 做了真实 Git 补丁组合与负控恢复。所有 81 个最终部分源码文件与其固定来源对齐；这不是完整产品树，也不是编译资格。完整 vendor 身份来自此前已核对的原 `.crate` 和固定组装清单，不以刚复制文件的自哈希充当来源证明。

`check_native_receipts.py` 是只读检查器。它核验实际 metadata 中 driver 的本地 manifest、workspace membership、唯一 package 身份、精确 8 features、真实 Tokio runtime 和 SQLite links；也可检查完整 JUnit 的精确选中集合、失败/成功结构、忽略项和重试字段。负控检查结果明确停在“结构符合、仍需读取物理因果证据”，不会把任意 FAIL、超时或简单状态向量升级为因果证明。

## 后续执行边界

原始 `just test` 保留 local profile、原 runner 和时间预算。每次 source mutation 必须绑定完整当前源码树，负控退出时必须精确恢复，任何实际构建或因果门失败均保存并停止后续阶段。真实锁的变化或不变都记录，不手改锁，不假定新本地 driver 自动进入 Bazel。

这里没有正常 Root 生产凭据、真实签名 objective、独立 Current authority、三 pool binder 或 FinalUse 接受证明。即便这些原生控制全部通过，B16 的正常生产入口和原平台门禁仍需分别验收。
