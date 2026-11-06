# 67cc 的 Linux 完整门准备包

**状态：PREPARED_DISABLED_FOR_ROOT_REVIEW。** 本包只完成云端源与请求重绑，未启动原生程序、未查询宿主容量，也没有新增产品测试或资格结论。

目标是主候选 `67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed` / tree `3982ba56dc5a3f1da0c1de7ea57992f88125c359`。旧 prepared 的预定目标 ca1 是 eed 的树；ca1 到新树恰好变化三个文件：`control_tests.rs`、`environment_selection.rs` 和 `collect_bazel_failed_test_logs.py`。原生唯一旧 ca1 启动在源码修改前被原内存门阻止，已记录的实际工作树仍是 e78。

因此本包仍从原 e78 工作树出发：更新旧转换中的 control_tests，再增加 environment_selection 和 collector 两条，得到 **14 条转换、原 2 个新增文件、10,582 叶子**。完整叶子和 Merkle 根与实际发布根一致；普通 checkout HEAD 和普通 index 仍保持原 5b 身份，不宣称实际 checkout 已变为 67cc。

新 intent 使用 `hepta-ai395-core-candidate-67cc5c28-full-20261105-v1`，输出目录为 `/home/qq/work/hepta-core-musl-full-20261105/candidate-67cc5c28-default-full-v1`，与旧 ca1 key/目录分离。请求为 `execute=false`、`root_execution_guard=null`。运行前仍须具体新的容量依据和根审；本包不构成原生启动授权。

runner 相对原 ca1 文件只替换七组描述或绑定：输出目录、最终树、发布 commit、14 条转换数量及说明、新 key。其余字节可以逐字逆变换还原。原磁盘下限 **64,000,000,000 bytes**、内存下限 **34,359,738,368 bytes**、jobs=4，完整源/index/lock/tool/physical guards、七 helper、原 default full、零重试和 raw/JUnit 规则均不改。原历史图为 193 members/1501 nodes；完整 roster 为 19,563（19,506 eligible/57 原 ignore）。这些是冻结的输入和待原生重新比较的合同，不是新源已执行的结果。

实际测试结果经根审后，才按原顺序进行 scoped fix、fmt。独立 Agentd feature scope 保留单独验收；旧 B16 UNKNOWN driver 没有接触或重放。

解包后运行 `python verify_rebound_packet.py` 可离线复核全部源、请求、图、roster、原停止记录和七处 runner 差异；它只执行原文件中的纯 Merkle 函数，不导入或执行 native runner。`prepare_rebound.py` 是从已有固定原件生成本包的程序。`delivery/member-manifest.json` 记录完整归档成员字节身份，`delivery/transport-manifest.json` 记录压缩归档及分片；实际 create_blob/full-GET 回执另在登记表中记录。
