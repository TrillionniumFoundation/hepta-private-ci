# Cell P1 实测更新：数值通过，语义质量未通过，原 owner 结果待回读

记录日期：2026-10-29。基线为 `0f41c4968eea63727c69e2b979491e94a99a9dbb`。本更新补充 PR #4290 已冻结发布的 77 个源码文件和 3 个状态文件；不改写该历史快照。当前完整源码是原 77 文件加 5 个环境、官方元数据缓存和直接数值诊断文件，共 **82 个文件**。这些仍是执行 `just fix` / `just fmt` 之前的精确字节。

## 当前结论

直接原始 Torch 与实际 Rust 的数值对照已通过。固定 multilingual MiniLM 的真实安装、拟合和三组冻结路由评估也已完成；其已知问题覆盖高于此前失败的 n-gram 基线，但未知请求仍有误接，**语言质量未通过验收，不默认启用**。

Rust live worker 路由等价性与真实签名发布/SQLite owner 试验已通过原生 PTY 启动。后续回读被 Runtime 的 `request audit unavailable; dispatch refused` 拒绝，原进程当前终态尚未取回。这是调用调度的审计服务故障，不能据此把测试记为成功、失败或未执行。没有绕过审计，也没有另起一个任务伪装原调用的重试。

本次可发表内容是精确源码、已收到并可校验的实际原始 PTY 响应、分析结果和后续执行描述。远端逐例 Python/Rust 结果、拟合权重文件、完整 stdout/stderr、格式修复后的源码和原 owner 终态仍需按已保存的原路径收集。**当前证据包不是最终完整远端 raw archive。**

## 直接 Torch ↔ Rust 数值验证

实际运行对照了 3 个 seed、2 个原始 profile、每个 profile 8 个输入，共 **48 个不同案例**。同一批案例分别使用原 Torch 的 batch 1 和 batch 8，与实际 Rust 导出的 logits 和类型化输出比较：

| 指标 | 实测结果 |
| --- | --- |
| 类型化输出 | 两种 batch 下全部与 Rust 相等 |
| 最大直接 logit 绝对误差 | `4.1961669921875e-05` |
| 预声明容差 | `1e-4 + 1e-5 × abs(Torch logit)`，全部通过 |
| 原 TensorCell 源码 SHA256 | `2421dc985a74b7b4edb80029a2b486d599ab8cf4409263e894aeb15878c289b4` |
| 原 owner 终态 | exit 0 |

这证明指定 48 个输入上的容差内数值一致和类型化输出一致，不是任意输入或浮点逐位相同的证明。不能把两种 batch 合并写成 96 个独立案例。历史 `1.7166e-5` 是 Torch 与 NumPy 参考的差异，本更新没有将其冒充直接 Torch/Rust 误差。

完整已收到的比较 receipt 及其原始 PTY 字节、chunk SHA、终态在 `DIRECT_NUMERIC_RESULT.json` 和本地观察归档中。远端 `native-logits.json` 与逐模型原始文件由收集脚本继续归档。

## 真实语义训练及冻结评分

固定编码器为 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`，revision `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`。安装在新建的隔离环境，使用 tokenizers 0.22.1、onnxruntime 1.23.2 和 scikit-learn 1.8.0；原 NumPy/SciPy 环境只读复用。所有新下载 wheel 以官方 PyPI JSON 所绑定的大小和 SHA256 验证。

拟合仅使用冻结的 400 条 train 和 144 条 dev，二者均为英文。8 类 intent 与 4 类 answer-shape 两个线性头有 4620 个 f32 参数，参数原始字节为 18480 B，序列化产物为 93657 B。最终模型 SHA256 为：

```text
c0b5c43fbaf7f1d2ea88355ba0a6a42eecbe45983050932419bc73b6ca7ca491
```

dev 选择阈值 0.5、最小 margin 0.05，得到 48/64 个正确已知路由、0 个错误已知路由和 0 个 unknown 误接。实际拟合 wall time 为 11.6781 s，CPU time 为 11.2910 s。之后固定参数和阈值，分别执行新任务评分和两个旧集合的回归，没有用其结果重新训练或校准。

下表统计的是**完整路由与 gold 相等**，不是这些查询全部已经通过签名发布、SQLite owner 和参数值读出的端到端任务成功率。unknown 的正确拒绝也会计入总体正确，因此不将总体正确数解释成返回了同样多的正确答案。

| 冻结集合 | 已知正确路由 | 已知拒绝 | unknown 正确拒绝 | unknown 误接 |
| --- | ---: | ---: | ---: | ---: |
| 新 512 例 | **231/256，90.2344%** | 25 | 219/256 | **37** |
| 原 held 320 例 | **177/256，69.1406%** | 79 | 64/64 | 0 |
| 原 challenge 384 例 | **153/192，79.6875%** | 39 | 186/192 | **6** |

这批已知错误均是拒绝，而非接受了错误的已知路由。未知请求的误接仍然说明 dev 的零误接不能推广为可靠的域外拒绝。冻结协议明确声明了训练/校准隔离及 dev 的选择规则；本记录不虚构另一个预先登记的 held/new 数值阈值。

### 新集合的语言和误接分布

| 语言 | 已知正确路由 | 已知拒绝 | unknown 正确拒绝 | unknown 误接 |
| --- | ---: | ---: | ---: | ---: |
| 英文 | 186/192，96.875% | 6 | 195/232 | 37 |
| 中文 | 45/64，70.3125% | 19 | 24/24 | 0 |

新集合的 88 条中文实际由 64 条 known 和 24 条 unknown 组成。中文指令中仍使用英文注册名称，地址解析仍是 ASCII 精确键匹配；这些结果没有证明中文实体名称识别。37 个新误接均来自英文：aggregation 11/16、mutation 8/32、multiple_outputs 8/16、external 6/32、temporal 4/16。

“mutation 家族误接”是本应拒绝的文本被选为读取或库存算术路由，**不是执行了修改、删除或外部副作用**。该路径只有 semantic、procedure 和 apply；apply 的 opcode 是有界整数运算、no-op 和 stop，仅返回数值 readout。

新集在运行前冻结，SHA256 为 `2e5d2ba7d8cd4801d944bd5dc9ca7faa426bfa4bd7c69acf8d428ff4c6615a4f`。其文本不与 train/dev 完全重复，并保留不同 entity/workflow 组合，但仍使用相同的 8 个 entity 和 8 个 workflow。这是作者构造的有限注册领域评估，不是独立开放世界测试、未见实体泛化或通用智能证据。

### 编码器和运行成本的边界

4620 个参数仅属于两个小头。六个冻结编码器资产合计 **127536988 B**，其中 ONNX 为 118453870 B，SHA256 为 `98a01d88b7de996cdea58c32ca71208c09968d143798814b2ea09d3439dc334f`。这些是磁盘大小，不包括 tokenizer 运行内存、Python/ORT、RSS 或 IPC，不能拿小头参数量代替系统总成本。

候选每个节点进程内让两个 resolver 以同一 Arc 共享一个 worker/session，batch 1、无 embedding 缓存。三个冻结组分别启动一个评估程序；即使各组的 process_starts 都为 1，也不能写成整个主机或三组总计永远只有一个 session。

后续 Rust parity 比较完整 `Option<InventoryCellRouteV1>`，不逐位比较 embeddings、logits 或概率。其请求计时包括地址预检、IPC 和头计算，有些无有效地址的请求可提前拒绝。因此全部请求的延迟不能直接标成全部 encoder 推理的延迟。本记录尚未收到该阶段的真实计时与 RSS 结果。

## 失败和恢复记录

第一个新隔离实验在读取资产时即因 `config.json` 长度不符失败，尚未拟合。核查发现原先提供目录的 5/6 文件属于另一份英文 MiniLM-L6 模型；ONNX 实际 23046789 B，而冻结的多语言模型应为 118453870 B。原错误目录未修改，manifest 没有为迁就错误模型而变更。

随后从同一冻结 Hugging Face revision 下载到独立新目录，六文件全部通过原 SHA/长度校验，实际用时 39.264 s，之后才执行本次真实拟合和评分。两个尝试的原始日志与模型身份记录均保留。

更早的 n-gram 负面结果仍为 held 已知 56/256、challenge 已知 48/192，没有因本次 MiniLM 覆盖提高而删除，也未被默认启用。

旧 semantic 操作 `hepta-cell-semantic-native-full-v1-20261029` 没有收到 acknowledgment；其精确派生 owner 目录在原先核对时不存在，状态仍保留 unknown。当前 r2 是另外明确授权、采用全新源码树、venv、资产及证据目录的独立实验，不是假装恢复旧操作。

## 原 owner、格式门和后续操作

已启动的真实 Rust/owner stage 016 原 session：

```text
dpty-1850661469cff3cdb5328199ee910e8ad138a0f0ff249b0c206f17ae1be20704
```

其当前终态因 Runtime 审计服务不可用而待回读。随后 018、019、020 的完整 argv、脚本、idempotency key 和 SHA 已落盘，但**从未调度**：

1. 018 按原基线的精确 Git blob 补齐隔离树遗漏的 `just` 包装脚本和 buildifier 描述；仅当先前 owner 未产生报告、且错误确为缺原包装脚本时，在新证据路径运行原 owner 测试。不会重新拟合。
2. 019 对六个相关 crate 执行 scoped `just fix`，再 `just fmt`，保存源码前后摘要、实际最终字节和完整 diff。遵守仓库 AGENTS，fix/fmt 后不再运行测试。
3. 020 只在原 owner 的终态和 style 阶段可验证时收集完整 raw archive：包括失败和成功尝试、逐例路由、实际 owner 输出、数值数据、模型 head、环境锁、原 PTY 请求/输出/终态及最终源码。只排除完整 venv、Cargo target 和已固定的公共预训练资产，保留全部输入 pins；不能用当前摘要包冒充这个尚未收集的最终归档。

此前原 native 参数、类型、SQLite owner、13 个 Agentd 定向测试和一次真实纠正后重新训练/发布/选择/撤回闭环的结果仍按 v1 快照的证据范围保留。该历史验证没有被扩写成新语义阶段通过、全仓测试通过或生产部署。
