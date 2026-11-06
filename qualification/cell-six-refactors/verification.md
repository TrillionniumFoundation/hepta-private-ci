# Cell 六项收敛：验证记录

最终冻结源码 `cb6f0a4a180677213988f6a4cc25c8431dfe5805` 的四包 native gate **959/959 通过，退出 0**。新增异步 bootstrap、人口统计和成本端口的 5 项服务测试均已实际执行通过。另有 67 项在执行前省略。本记录证明列明的软件行为，不代表六个最终目标全部闭环、继承工作区全部通过，或生产采用、长期服务、模型质量和效率认证。

## 最终冻结源码与结果

- 源码 commit：`cb6f0a4a180677213988f6a4cc25c8431dfe5805`。
- 源码 tree：`d28638c3c38228891b2016758d795b787bb8e6d3`。
- 平台：ai395、Linux x86_64；Rust/Cargo 1.96.0；cargo-nextest 0.9.146。
- 运行器原文：`Summary [ 111.810s] 959 tests run: 959 passed (1 slow), 67 skipped`。
- 测试前后源码身份和干净状态一致；报告与原始记录随后以纯证据/文档提交加入，不能当作另一次代码执行。

| 包 | 执行 | 通过 | 失败 / 错误 |
| --- | ---: | ---: | ---: |
| `codex-hepta-agentd` | 658 | 658 | 0 / 0 |
| `codex-hepta-infer-core` | 35 | 35 | 0 / 0 |
| `codex-hepta-infer-worker-host` | 57 | 57 | 0 / 0 |
| `codex-hepta-neuron` | 209 | 209 | 0 / 0 |
| **合计** | **959** | **959** | **0 / 0** |

独立解析 JUnit 得到相同计数，没有 flaky、rerun-failure 或 skipped testcase 节点。67 skipped 是运行器在执行前省略的用例，不在上述已执行 testcase 内；没有把重试计为额外通过项。

`scoped-fix`、`scoped-strict`、`helpers`、`scoped-test` 四阶段均退出 0。前三个修改包经过 `just fix` 与 `cargo clippy --locked --tests ... -- -D warnings`；测试另纳入与派发/未知结果持久性直接相关的 `codex-hepta-infer-core`。完整命令保留在状态文件，测试命令为：

```bash
just test --locked \
  -p codex-hepta-neuron -p codex-hepta-agentd \
  -p codex-hepta-infer-worker-host -p codex-hepta-infer-core \
  --test-threads 2
```

十个 helper 均从 Cargo 的实际 executable 产物记录解析，测试后重新核对的 SHA-256 与大小全部一致。构建 helper 依赖包不等于测试了那些额外包。原始 Cargo JSONL、stderr、环境、manifest 和每阶段输出均保存在完整归档内。

证据：[最终状态](evidence/native-cb6f0a4a/status.json)、[独立摘要](evidence/native-cb6f0a4a/independent-summary.json)、[JUnit](evidence/native-cb6f0a4a/junit.xml)、[测试日志](evidence/native-cb6f0a4a/scoped-test.log)、[进程终态](evidence/native-cb6f0a4a/controller-terminal.json)。

## 本次补齐的异步接线

现有 bootstrap 的 `with_population` 把真实 host 提供的 artifact/capability/role/limits 绑定到原 owner；handle 的 `population_observation`、`step_with_population` 和 `record_cost` 进入原队列与服务。服务继续执行原 Admission、Dispatch、Settlement/recovery 检查。

五项服务测试覆盖：artifact/role 不匹配在写盘和 worker 联系前拒绝；合法绑定的实际执行与精确 replay；输出 ACK 前后的活动观察；drain 拒绝；未绑定路径的明确拒绝与兼容调用；Unknown peer 保持活动容量；入队前的 4,096-peer 和 257-envelope-member 拒绝；错误 task/source 成本拒绝；失败 Training 的部分计量、None、重放、冲突、包络不重复计费和重开持久性。

这补齐了现有同步 owner 与 async bootstrap/service 之间的端口缺口。真实 artifact 自动解析/启用和训练 receipt 到具体 task/source 账本的映射仍由 host 提供；测试没有生成默认角色、默认模型或伪造计量证明。

## 保留的早期尝试与父级范围

| 源码 | 当次范围与结果 | 本记录中的地位 |
| --- | --- | --- |
| `7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75` | 较广的 20 包既有记录：6,631 执行、6,577 通过、51 普通失败、3 超时；94 项省略，退出 100 | 父级基线；本次四包通过不覆盖其未重跑范围 |
| `75c90ebaee64f95ae03644d0b250f118ad676b0c` | scoped-fix 退出 101；assert_eq 宏歧义造成 20 个编译错误，未进入 native test | 保留首次编译失败及后续测试 import 修复 |
| `c058c08fcf188d66b9d378ccc97630b3bc9dbade` | 四包 954 执行、952 通过、2 失败；67 项省略，退出 100 | 保留修复前的完整失败与 helper 记录 |
| `a8dd9d4639ebe781ceb06afdf09e3fdcb9bf48be` | 四包 954/954 通过；67 项省略，退出 0 | 异步端口补线之前的通过版本，归档保留 |
| `cb6f0a4a180677213988f6a4cc25c8431dfe5805` | 四包 959/959 通过；67 项省略，退出 0 | 本次最终代码验证版本 |

`c058c08f` 的两个失败分别是成本测试在新增阶段后仍使用固定数组下标，以及 Agentd resident 测试沿用了单次进程传完整资产的 IPC 阈值。修复改为按实际阶段定位 Unknown 项，以及按实际请求/响应/资产/帧长计算精确 IPC。生产执行代码没有为了通过这两个断言而放宽边界；两项完整 testcase 身份在后续通过 JUnit 中仍存在。

父级 JUnit 的 54 个 failure 节点包含 3 个 watchdog timeout，不能额外再重复加 3 个超时。本次未重跑父级的 core、exec-server、supervisor 等其他范围。随附的基线材料是独立解析和运行器摘要，包含原 XML 路径、大小及哈希；当前证据包不包含该原始 XML。

证据：[父级摘要](evidence/baseline-7391c3dc/scoped-runner-summary.json)、[父级 JUnit 独立解析](evidence/baseline-7391c3dc/junit-independent-parse.json)、[首次编译失败](evidence/native-first-75c90eba/status.json)、[两项失败摘要](evidence/native-c058c08f/independent-summary.json)、[前一通过版本](evidence/native-a8dd9d46/independent-summary.json)。

## 本地 V13 验证

Python 3.12.14、NumPy 2.3.5 下，`unittest discover` **20/20 通过**：11 项内容闭包测试、9 项 selected-use 测试。执行记录的源码为 `75c90eba`；比较至本次最终源码，V13 测试、Python 实现、参考源和 provenance 内容逐字节相同，目录只有 README 改动。这是相同代码的既有本地验证，未冒充在最终 native host 重新训练或执行 Python gate。

这些测试使用明确标记的 synthetic checkpoint/encoder、原 Adapter 和原 SourceOwner。覆盖完整内容成员、受限读取、选择/来源改变时拒绝、新进程下一任务预测及分批一致性。独立结构 validator 检查形状和有限值，没有验证真实 MiniLM artifact、重跑 V13 训练或证明未来任务质量。`DENY_ALL`、`adoption_performed: false` 保留；V13 资格没有转给 Joint。

证据：[本地元数据](evidence/local/run.json)、[20 项完整日志](evidence/local/v13-tests-final.log)。格式化日志和本地开发期 Clippy 记录也保留，最终 Rust 结果以上述 native gate 为准。

## 完整归档和复核

| 原始归档 | bytes | SHA-256 |
| --- | ---: | --- |
| [native-a8dd9d46.tar.gz](evidence/native-a8dd9d46.tar.gz) | 531,052 | `4a65450b81e7fe82483f5568d020d821a74587ddf53026f9affa6bfb06b2d655` |
| [native-c058c08f.tar.gz](evidence/native-c058c08f.tar.gz) | 538,535 | `e9bc765e153a79a15fab46433aa49ca57cfe25d1e48b76941dc627ae6f3634b3` |
| [native-cb6f0a4a.tar.gz](evidence/native-cb6f0a4a.tar.gz) | 563,937 | `a6f32c739eae672bcb946b8c0496f3c2009a98fa3a6f8542b87d1ccc0d63cb07` |

所有归档按固定远端版本分块读取；每块和整包均校验 SHA-256。拒绝路径越界、链接和重复目的路径后，逐项核对 raw-index 的大小与哈希。raw-index 不自引用，其身份由完整归档哈希固定。完整 helper JSONL、stderr 和其他原始记录在 tar.gz 中保留；状态、摘要、最终 JUnit 与测试日志另提供原字节可读副本。小体积本地/首次失败/父级摘要直接保留，不改写失败记录。

最终 JUnit：203,635 bytes，SHA-256 `6438071ad4e807aaadee50943f16041ef412ccce6fe08519d83984d33b19e35f`。所有随附文件及归档身份见 [总索引](evidence/manifest.json)。

当前长期容量、具体生产 migration verifier、Joint microbatch/tensor kernel、真实效果评价，以及训练/评价/模型取得 owner 的完整计量仍有实现或证据缺口，详见 [六项实现与边界](README.md)、[生命周期](lifecycle.md) 和 [resident](resident.md)。通过上述 gate 不会解除这些边界。
