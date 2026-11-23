# MemoryServingQualificationV1 的既有实物覆盖

提交 `43e5da1bb81369e4e999adfa8558f5ccb5460eb6` 的 strict 作业留下 115 条诊断。按该提交的物理 `CALLERS.toml` 展开 826 个受保护文件，再按诊断原行筛选完全私有的枚举声明，得到 12 条。11 条位于受保护文件。唯一例外是 `memory_serving_qualification.rs:17` 的 `Decision`。本读回仅处理这 1 条，其余 114 条保留各自的归因。[具名原诊断](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/153052756d0174d201b6ce48433fc00d4d7dd589/qualification/hcsn_ci_readbacks/integrated-blockers-20261123/combined-43e5/strict-remaining.json) · [原类型](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/43e5da1bb81369e4e999adfa8558f5ccb5460eb6/codex-rs/hepta-agentd/src/memory_serving_qualification.rs)

历史候选把两个枚举载荷放到堆上，对应的两个构造处各增加一次装箱。逐字还原这四处后得到供体 Git blob `814ca0a11bd200572a0be348189584af807f95e1`，其余判断、公开函数签名和当前性检查保持原字节。生产路径要求下列两份不同的证据链。[历史候选](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/24abd04c825cb0d5d0ce27b52ac5008eda13dde4/codex-rs/hepta-agentd/src/memory_serving_qualification.rs)

| 分支 | 原构造与使用时的核对 | 已有覆盖 |
| --- | --- | --- |
| 选中 | `selected` 同时绑定已验证选择的决定、候选制品、目标和数据集摘要。公共引用入口先复验完整的选择对象，再校验观察者签名、每项独立审查、完整清单与角色分离。 | 现有选择测试用合成签名和虚拟时钟走选择入口；引用单测用手工普通 receipt 直接测内部 census。两者的输入未构成同一次可验证的交付。[公共核验](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/43e5da1bb81369e4e999adfa8558f5ccb5460eb6/codex-rs/hepta-intelligence-eval/src/memory_citation_gate.rs#L170) · [引用夹具](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/43e5da1bb81369e4e999adfa8558f5ccb5460eb6/codex-rs/hepta-intelligence-eval/src/memory_citation_gate_tests.rs#L270) |
| 回滚 | `rollback` 绑定回滚来源中的前驱制品和同一目标。服务绑定继续核对清单支持数据、前驱身份及代次，使用时复验选择与引用证据的当前性和撤回集合。需要前驱成为候选时自身的有效引用证书。 | 既有回滚 admission 测试构造合成选择及回滚；没有提供与该前驱匹配的当前证书。服务执行器接收调用者已取得的资格对象。[原回滚夹具](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/43e5da1bb81369e4e999adfa8558f5ccb5460eb6/codex-rs/hepta-intelligence-eval/src/self_evolution_ingress_tests.rs) · [服务消费者](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/43e5da1bb81369e4e999adfa8558f5ccb5460eb6/codex-rs/hepta-agentd/src/selected_memory_service.rs) · [原资格约定](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/43e5da1bb81369e4e999adfa8558f5ccb5460eb6/codex-rs/hepta-intelligence-eval/MEMORY_CELL_CONTINUATION.md#L215) |

从带原始 Git 提交标识的源码归档与 43e5 的 63 个 Rust 变动重建 9,312 个常规 Rust 文件。另一次使用原生作业对应的独立物理清单，逐路径与 blob 复核其中 `codex-rs` 全部 9,141 个文件，其 SHA-256 为 `d18a2f9e4d23118386725d0f8cfc0fa7c73fe775ee67a1b49bd395fa931ecbe4`。扫描发现，`MemoryServingQualificationV1` 出现在五个文件中，分别为定义、两处重导出和两处接收对象的消费者。按类型全名搜索 `::selected(`、`::rollback(` 均为零处，公共 `verify_memory_citation_census_v1` 只有定义和重导出两处。逐行核对了上述五个文件，以及生产检查和测试夹具共 17 条具名条件。该扫描限于仓内 Rust 源码；外部服务持有的机密材料不在本次观察范围。

**真实材料缺口。** #1452 的历史交接实际导出了 2,000 个待审请求，核对 2,014 个归档清单条目。两个检索臂均发出零个引用标记，精确率没有可计算的分母。作者记录未取得独立签名达到门槛的语义引用清单、三个已认证独立快照与两个真实未来窗口，也未验收生产选中及回滚。交接脚本保留原答案和待审请求。复算这一分支需要同一目标及数据集下的真实选中证书、对应前驱自身的有效引用证书、回滚凭据和当时可复验的信任及撤回状态。现有证据只能证明四处源码形状一致，新增原生或 strict 作业数为零。[#1452 原交接结论](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1452) · [固定版本的交接脚本](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/81d9fcb36bddfcc6dc914f87697c642824273cc1/scripts/memory_cell/adjudication_handoff.py)

独立重放需用精确 43e5 工作树，并从上方具名诊断链接保存原始 JSON。脚本直接读取提交中的 Git blob。它还调用仓内原加载器展开物理清单，校验冻结诊断 SHA 和历史供体 blob。

```sh
python readback.py /path/to/43e5-checkout /path/to/strict-remaining.json | cmp - readback.json
```
