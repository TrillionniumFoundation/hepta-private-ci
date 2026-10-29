# P1 Cell 原生参数、双地址与 canonical owner 接入：状态快照 v1

记录日期：2026-10-29。基线为 `TrillionniumFoundation/hepta-private-ci` PR #4173 的提交 `0f41c4968eea63727c69e2b979491e94a99a9dbb`。本记录对应尚未执行 `just fix` / `just fmt` 的精确源码重放。后续任何格式化或修复均须更新发布文件字节与摘要。

## 结论与边界

原始残差 Cell 的参数化函数、库存值和四步程序已在 Rust 中接入，使用原有 SQLite canonical owner、Agentd 控制路径和 Memory Cell 发布生命周期。远端已报告数值、类型、owner、Agentd 定向测试成功，并实际完成一次纠正后重新训练、重新发布、重新选择与撤回的 owner 闭环。

语言寻址没有完成质量验收。已运行的 n-gram 基线在已知问题上的覆盖明显不足，必须保留为失败证据。新的固定 multilingual MiniLM 编码器、Rust 双分类头和独立双精确键候选已完成源码及协议测试，但截至本快照，其真实训练、真实编码器推理、冻结评估与运行开销测量尚未回传完成结果。

这些结果证明有限库存任务的原生参数及 owner 接入可工作，不证明任意任务泛化、开放环境自主学习、分裂收益或通用智能。集成试验使用隔离的真实 SQLite、Unix socket 和签名发布路径，没有部署为生产 owner。

## 可发布源码及分组

重放使用已发送且固定摘要的源码包与补丁，保留原先应用顺序。最终文件索引为 `MANIFEST.json`。索引包含每个文件的 SHA256、Git blob SHA1、基线 blob 和修改阶段。两个需要基线内容的 neuron 文件已逐字节匹配基线 Git blob；Agentd v1 的全部路径均由 v2 覆盖，没有遗留 v1 独有文件。

| 文件集合 | 文件数 | 内容与状态 |
| --- | ---: | --- |
| `native-plus-ngram-files.json` | 60 | 语义候选加入前的原生闭环与失败 n-gram 基线 |
| `tested-final-files.json` | 77 | 远端已应用并参加相关定向测试的精确最终源码；“已测试源码”不等于每条实验分支均已实际执行 |
| `unexecuted-additions.json` | 4 | 隔离环境准备工具及测试、直接 Rust/Torch 数值诊断；真实安装和直接诊断尚未执行 |
| `all-source-files.json` | 81 | 上述 77 个文件与 4 个新增工具的并集，便于完整发布；各自验证状态仍然区分 |

| 逻辑组 | 文件数 | 主要内容 |
| --- | ---: | --- |
| `native_numeric_parameter_port` | 14 | 原始参数解码、残差前向、typed readout、六个模型与 48 例参考 |
| `typed_contract_and_canonical_owner` | 10 | 独立 entity/workflow 类型、库存程序、原 SQLite owner 获取及写入 |
| `native_agentd_publication_and_control` | 19 | 原始 Agentd control、参数包、同一发布 host、最终 owner/lifecycle 再验证 |
| `native_owner_learning_cycle` | 2 | 当前 canonical 来源的真实干净重训练与生命周期闭环 |
| `shared_agentd_wiring` | 1 | Agentd 公共导出及模块声明 |
| `ngram_negative_baseline` | 14 | 已训练低成本基线、冻结数据、失败结果、Rust 等价性测试 |
| `semantic_candidate_not_language_qualified` | 17 | 固定 MiniLM worker、Rust 角色/回答形状头、独立双键和待执行评估 |

这些是审阅分组，不是彼此独立可编译的提交。最终 Agentd `lib.rs` 同时引用实验模块；应原子应用完整 77 文件集合。若拆分提交，应按真实依赖拆分 wiring，并对新的组合进行必要验证。

`tested-final-files.json` 的 SHA256 为 `ba5af6925bc7019199672f686fe4642ed1b4375514d79f00c4efcc15043c4fd5`。`all-source-files.json` 的 SHA256 为 `88b656834c8ddc2aacef504f6f8e475f64adbcbae672a43f9eda2b84cf3031e5`。这些是文件映射包的摘要，不是 Git commit ID。

## 已接入的语义与来源约束

### 原始参数与 typed readout

`hepta-neuron/src/memory_residual_cell.rs` 保留原始 `H(x + B A x) + bias` 函数、384 维特征、原始 f32 参数及参数/编码器摘要。Semantic profile 将 12 个 bit 读成 `reserve`、`pack`、`limit` 三个 4-bit 值；skill profile 从 4×7 logits 读出完整四步 opcode 程序。没有把原模型换成数据库值回填或答案缓存。

读出保留原 f32 sigmoid 阈值语义；skill 先以 f32 softmax 再取最大项，首个并列项获胜，避免极近 logits 在舍入后改变原函数。参数包严格限制大小、维度与 lineage，绑定编码器、checkpoint 和 training-history 摘要。没有新增 Cargo 依赖。

### 独立双地址与 canonical owner

`Inventory*V1` 引入独立的 entity 和 workflow 标识，未把它们混成单一索引，也未伪装为旧单 opcode/label profile。外部自然语言请求包含文本、时间与预算，不允许携带 gold route 或正确地址。Semantic 需要 entity，Procedure 需要 workflow，Apply 需要二者。

owner 仍为原 `CognitiveStore` 和 SQLite canonical 记录。创建、纠正、遗忘、引用、tombstone 与作用域检查沿用原有 owner；没有第二个权威数据库。只读 owner snapshot 是不透明值；参数来源被绑定到真实来源记录与训练版本。

精确事件/hold 的当前 cut 与语义/程序参数的训练 cut 分开：事件或 hold 改变时读路径重读当前 owner，无需重训不相关参数；训练事实被纠正时，旧参数训练 cut 会失效。首次原参数导入保持不可变 `training_origin`，不能把旧参数重新绑定成纠正后的新来源。干净重训练使用当前 canonical 来源，不凭 warm-start 参数的旧 lineage 获得新授权。

### 同一个发布生命周期

内部 `TypedMemoryCellReleaseHostV1<B>` 复用原有 durable CURRENT、发布、独立签名选择、撤回、重启与最终使用前再验证。保留旧 `MemoryCellReleaseHostV1` 具体类型别名及 `::new()` 调用方式。

公开 bundle trait 的解码入口需要 crate 内才能产生的能力 token；外部调用者不能构造该 token，且不存在公共 Default/Deserialize 通路。原有外部使用者无需制造 token。

参数包读出后，Agentd 仍执行实际 owner 和 lifecycle 复核。失败时返回空失败输出，不泄露部分结果。一个专门测试刻意改变模型 head、保持 canonical owner 数值不变，并观察读出随模型参数改变，以验证返回值确由模型产生。

## 验证记录

远端执行由主任务 `/root` 负责。下表的远端成功依据为主任务明确回传的执行结果；本快照尚未重新读取、归档这些运行的完整 stdout/stderr。因此缺失的精确测试总数不补猜，后续应以原始日志补全。源码位置和本地冻结参考可由最终文件索引核对。

| 检查 | 已收到结果 | 证据范围与限制 |
| --- | --- | --- |
| neuron 残差参数测试 | 通过，完整远端计数待归档 | 最终源码包含 5 个测试；六个原模型、48 个 canonical 例、解码拒绝及 softmax 边界；不据此猜测命令实际运行数 |
| cognitive-types `inventory_` | 3/3 通过 | 新 profile、双键、四步程序、负数 floor 和 checked arithmetic |
| 原 SQLite memory owner `inventory_` | 3/3 通过 | reopen、双地址、纠正、hold、tombstone、scope |
| Agentd `inventory_` 自动测试 | 13/13 通过 | 5 个参数/owner 运行测试、3 个 n-gram 测试、5 个新语义接口/worker 测试；忽略的真实 MiniLM 试验不计为执行成功 |
| 原有 Memory Cell release 回归组 | exit 0 | 精确测试数量及日志尾部待归档，不声称整个仓库测试通过 |
| 原 Torch 独立校验 | 48/48 typed 输出一致 | Torch 对冻结 NumPy 参考的最大 logit 误差为 `1.7166e-5` |
| `inventory_native_retraining_owner_cycle` | 实际执行，exit 0 | 纠正后真实 Torch 干净训练、generation 2 发布、独立选择、纠正值和另 7 个事实保留、撤回使旧选择失效 |
| Python encoder worker 协议 | 本地 3/3 通过 | 合成向量、消息和错误边界测试，不等于真实 MiniLM 语言测试 |
| 新隔离环境准备工具 | 本地 4/4 离线测试通过 | 未证明真实 PyPI/mirror 下载及实际安装已完成 |
| 直接 Torch/Rust logits 对比 | 工具已编写，未执行 | 新诊断导出真实 Rust logits，逐例对原 Torch batch 1 / batch 8 进行比较 |

**数值精度限定：** `1.7166e-5` 是原 Torch 与冻结 NumPy 参考的差异，不是直接测得的 Torch 与 Rust 差异。Rust 已按同一参考通过预先声明的 `1e-4 + 1e-5 × |reference|` 容差。48 个 typed 值的一致性可以通过共同参考核对；直接 Torch/Rust 最大误差仍待新增诊断，不能把两段验证合并成一个未实测的浮点误差。

## n-gram 基线：质量失败，保留负面结果

此基线使用 2048 维散列词、字符和 bigram 特征，加 4 类线性头与独立精确键。它不是原来的真实 MiniLM 语义编码器。训练仅使用 400 条 train，阈值仅由 144 条 dev 选择；seed 731，800 次优化，8196 个 f32 参数，模型序列化 182226 字节。

dev 为满足零 unknown 错接，选择阈值 0.8、最小 margin 0.4，只留下 24/64 个正确已知问题。冻结评估结果如下。

| 冻结集 | Semantic 正确 | Procedure 正确 | Apply 正确 | 已知合计 | Unknown 正确拒绝 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 原 formal held | 24/64 | 16/64 | 16/128 | **56/256，21.875%** | 64/64 |
| 首轮人工 challenge | 8/64 | 32/64 | 8/64 | **48/192，25%** | 192/192 |

多数已知问题被拒绝，因此 unknown 拒绝率高不能解释成语言质量通过。Rust 的冻结函数对照测试重现了这 704 例参考路由；它证明移植忠实，也保留了失败。默认路径未自动启用该候选。没有把参考测试的成功改写为 OOD 泛化成功，也没有未实测的延迟结论。

模型 SHA256：`56d649027191f7332a1783ec9b9a25acbaaff5aa04bf482e4c51ad7ae0c42d42`。完整数据和计数保留在 `native-routing/formal-01` 及 Agentd 的 `formal-held-reference.json`、`challenge-reference.json`。

## 新 MiniLM 候选：源码与边界已备，真实质量待验

候选固定使用 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` 的既有 revision `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`，读取原始完整问题，不先屏蔽实体或日期。训练数据逐字节复用原 400 条 train 和 144 条 dev；此前已查看的 held/challenge 只作回归。计划训练 8 个 intent 标签和 4 个 answer-shape 标签，共 4620 个 f32 参数；当前没有拟合完成的参数产物。

每个节点进程共享一个预热 Python/ONNX encoder worker 和一个 session；Rust 调用方用同一 Arc 共享，串行处理、batch 1，无 embedding 缓存。Python 只输出 384 维特征，Rust 计算两个头和双键。这里的“共享”是一个节点进程内共享，不是跨进程、跨机器已经部署的服务。

worker 约束请求 16 KiB、响应 32 KiB，并验证序号、原文摘要、编码器摘要及源码 pin；超时、取消或协议失配后杀掉对应 child，不将残余响应用于下一请求。真实 worker 的吞吐、常驻 RSS、冷启动及每请求 IPC 成本尚未测量。

ONNX 文件 `model_quint8_avx2.onnx` 为 118453870 字节，SHA256 `98a01d88b7de996cdea58c32ca71208c09968d143798814b2ea09d3439dc334f`；六个冻结资产合计 127536988 字节。这是磁盘字节数，不是 RSS 或总内存占用。

新增 512 例任务在运行前冻结：256 个已知任务、256 个未知任务，其中 88 例中文，并引入此前训练与 held 中未出现的组合。文件 SHA256 为 `2e5d2ba7d8cd4801d944bd5dc9ca7faa426bfa4bd7c69acf8d428ff4c6615a4f`。这是作者构造的有限注册领域评估，不是独立采集的开放世界基准；不能扩大解释。真实质量分数尚无结果。

原普通 pip 尝试受低速下载阻塞。新增准备工具在独立新 venv 复用既有 NumPy/SciPy，只安装缺少的固定版本依赖；镜像 wheel 必须按 PyPI 官方 JSON 的大小和 SHA256 验证，再离线安装。工具不修改原环境，也不重新下载 Torch。主任务已找到可用原生 PTY 通道继续执行；“待执行”是本快照的证据状态，不表示已永久受阻。

## 剩余验收与发布状态

先完成独立环境 bootstrap，固定 train/dev 拟合并冻结模型，再执行旧集合回归、新 512 例评估、真实 batch 1 worker 与 Rust 头等价性、真实签名发布/owner 集成及延迟/RSS/IPC 测量。若质量失败，保留失败模型和结果，不用已读冻结集反向调参。

直接 Torch/Rust 数值诊断亦已准备，需实际运行后才能记录最大误差。原始远端日志、format/fix 后文件摘要、最终 Git commit/PR 尚未在本快照确认。当前结论只覆盖明确通过的 native 数值和 owner 闭环；不会因预备源码齐全而把语言质量、部署或发表标成完成。
