# Feature 更新只调整前驱记录的内存表示

产品提交 `6d65e2ee95f37d1f4983e3ba7393ed8ac2163c80` 的父为 c12。它只改 `circuit_feature_current.rs` 的两处。完全私有的 `Publication::Update` 将拥有的 `PublishedCircuitFeatureCompletionV1` 放入一个 Box。在唯一的构造点，原前驱绑定、清单、源、检查点、运行 ID 和观察值校验全部先执行，然后分配 Box。Initial 的值、调用形式和分配方式均保持。原 Clippy 报告的两个变体下界为 2744 和 40 字节。此项资格没有测量新类型的精确大小、堆分配吞吐或应用延迟。[独立产品差异](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/6d65e2ee95f37d1f4983e3ba7393ed8ac2163c80) · [同仓供体](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/24abd04c825cb0d5d0ce27b52ac5008eda13dde4/codex-rs/hepta-agentd/src/circuit_feature_current.rs)

原 35 条 `large_enum_variant` 中，12 个类型完全私有，15 个可见到父模块，2 个在 crate 内公开，6 个为 pub 声明。source.json 列出逐项路径、原行和受保护状态。这次选择了完全私有集合里的一个。此前已单独确认的 bootstrap 不重复计数。MemoryServing 的选中/回滚仍缺匹配前驱的真实引用材料。供体还改过私有的三个 automation 配置变体。本次没有将它们纳入同一次资格。[原严格检查](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45138928408/job/137573328612)

候选的六个原生用例全部通过。原 strict 编译仍以 101 退出，逐项对照从 115 降至 114，large_enum_variant 从 35 降至 34。唯一消失的是本文件第 161 行的枚举；新增诊断为零。二进制摘要为 `401ad6b68a1b031772961afd0b3eb9d9310d9d9e19d959575a7cf1d202ea97d1`。此结果针对 c12 加这一处产品变化。[原生作业与归档](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45155793910/job/137628248445) · [独立 strict 作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45155793910/job/137628248846)

### 35 个编译器原行的筛查范围

| c12 原行的筛查结果 | 条数 | 已确定的范围 |
|---|---:|---|
| 完全私有，已独立取证 | 2 | 本次 Publication 与先前 VersionedBootstrap 各有产品、原件及对照；后者已进入 11e。 |
| 完全私有，已定位缺件 | 2 | Decision 缺真实选中与回滚前驱引用链；AutomationEffectHostFile 有 HTTP / V2 / Linux V3 供体，目前未核定 V2 经完整文件入口成功构造的独立凭据。 |
| 完全私有，仅核实同仓装箱声明 | 7 | HistoryState、ReadState、ClientOriginV3、ResidentExchangeV3、OriginalCohort、OriginalLearningReceiptSourceV1、PreparedCTask 的供体声明确有变化。各自的独立行为资格待查。 |
| 完全私有，供体声明相同 | 1 | ResidentStagesV3 的供体沿用原声明。其载荷拥有父模块可见的阶段所有者类型。 |
| 可见到父模块或 crate，带显式标签的双向 serde 协议 | 9 | 两个 Command、两个 Readiness、五个 CommandResult。需审其作用域内构造和匹配，并独立核对文档所定字节、顺序与拒绝。 |
| 可见到父模块，其他内部载荷 | 8 | 涉及原件保管、历史账本、resident 权限和阶段所有者、原命令证据及模型效果；作用域内消费者和原始正反例待查。 |
| 类型声明使用 pub | 6 | 涉及账本状态、学习准备度、评估时序、源/训练输入和 trainer。需分别追踪重导出及下游 Rust 构造类型。上述声明本身不足以判定每个变体实际对外可见。 |

这些条数互斥。相关 enum 的字段装箱可能改变声明作用域内的 Rust 构造类型，serde 字节能否保持须单独验证。screen.json 保存每条归类、精确源行和 Git blob。完全私有的 12 条供体 blob 均已与 24abd04 的 Agentd 源目录 Git tree `7982f0ddaec3394c53189f1920e5ae70aa6d7ac8` 核对。重放用 `python3 screen.py /path/to/c12 /path/to/24abd04 > screen-replay.json`，结果可同 screen.json 逐字比较。

## 被验证的行为

枚举无 Serde 实现。生产构造只出现在 initial 和 update 两条启动路径。其他模块按引用读出字段。供体另有一个公开的 re-export，独立修补只取原来的两处 Box 变动。两个原工作树分别通过全部 826 项 protected-file 检查和与本类型相关的 15 + 12 个源完整性测试，清单在两侧均含 1,652 个调用边界。[原构造及检查顺序](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c12ee03f3185d5a13949faca54f066dfd634e509/codex-rs/hepta-agentd/src/circuit_feature_current.rs#L260)

6 个原生用例均使用既有原断言。Feature 夹具通过实际初始发布构造 A，执行 A，取前驱完成记录，再用实际准备、签名及发布生成 C。正例检验原 Selection/Observer 盘上记录、FinalUse claims 和源所有者字节，重开后读取同一结果。拒绝用例走源撤销、收据回滚、错误密钥或角色及过期声明。另三例覆盖保留源的作用域与消费者绑定、新任务后原 outbox 读取、数据库更换后的拒绝。文件含运行时刻，字节相等断言在每轮自己的盘上原件上执行。可观察输出与原资格结果由 verify.py 分别从各原件复核。[原发布、重开及拒绝夹具](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c12ee03f3185d5a13949faca54f066dfd634e509/codex-rs/hepta-agentd/src/circuit_feature_learning_receipt_tests.rs#L45) · [保留源夹具](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c12ee03f3185d5a13949faca54f066dfd634e509/codex-rs/hepta-agentd/src/cell_q24_retained_learning_source_tests.rs)

原生对照取自同根树 `9554ddb1` 的早先 musl 作业。六个具名用例分布在三个真实 shard test.log 中，逐一为 ok。c12 的独立正式 nextest 也逐一 PASS。源码与 prospective merge 两条官方 Clippy 日志有相同根树和 115 条逐项诊断。[原 musl 同树归档](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e3fce928e4395868148da24c1d91e83a5765e37a/docs/learning/evidence/musl-child-completion-20261123/native-musl-comparison.zip) · [c12 正式 nextest](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45138928118/job/137587164011) · [原两条 strict 作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45138928408)

## 离线复核

本目录提供候选两份原始 Actions 工件、原始出错对照的摘要和复算输入。prior.zip 内保留 c12 官方 startup 工件原封 ZIP 及两份 strict 诊断行。native-musl-comparison.zip 用上面的固定原归档。源码重放使用 c12 和产品提交的完整工作树，并从上面的 24abd04 供体保存 circuit_feature_current.rs。

```sh
python3 verify.py > replay.json
cmp replay.json result.json
python3 -m zipfile -e prior.zip prior
python3 baseline.py /path/to/native-musl-comparison.zip prior/full.zip prior/strict-137573328612.log prior/strict-137573328628.log > base-replay.json
cmp base-replay.json baseline.json
python3 source.py /path/to/c12 /path/to/product /path/to/donor.rs > source-replay.json
cmp source-replay.json source.json
```
