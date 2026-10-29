# P1 下一轮：固定实际初始模型输入的最小方案

状态：**待实施方案，不是已经通过的实验。** 依据同目录 `LIVE_AUDIT_20261029.md` 与原始 24 个 live case。

## 1. 三种证据应分别命名

| 组 | 固定什么 | 可以回答什么 | 不能回答什么 |
|---|---|---|---|
| 现有 replay | 预设模型 proposal 序列；真实 owner/tool 执行与结果核验 | harness 是否执行规定动作、守住 owner/输出契约 | 模型推理质量或相同实际模型输入 |
| canonical-initial live | 发往 provider 的第一份完整请求字节；共同任务/工具/预算 | 消除首轮提示与工具协议差异后，三路实际后续行为 | 所有后续请求相同、一般架构优劣 |
| native-construction end-to-end live | 应用任务、服务身份、声明的预算和成功 oracle | 各 harness 自己构造上下文时的真实组合表现 | 单一模块的因果成本或独立模型能力 |

保留现有结果为第三类的初次样本，不改变其冻结标签或分数。将原 `individually_optimized` 称为 candidate：只有 native 两项非绑定上限改变，尚未验证优化收益。

## 2. 最小改动位置与实际输入契约

改动范围限定 qualification 的 `model_gateway.py` / `production-qualification/script_gateway.py`、`representative_compare.py` 与审计文件。原模型执行器、owner admission、job/receipt 和生产路径不需要为了本实验被重写。

为每个 corpus case 生成版本化 `CANONICAL_INITIAL_REQUEST.json`。内容由冻结任务文件产生，不能从某一路偶然出现的 skills/环境文本推导。它明确固定以下内容及顺序：

- model alias 与共用 instructions 的角色/位置；用户任务的完整文本及 content 表示法。
- 六个工具的 name、description、parameters、strict；固定 tool_choice、parallel_tool_calls、store、stream 和 max_output_tokens。
- reasoning/include 的共同政策，以及无 seed/temperature 时的明确说明。若服务支持确定采样配置，先核实实际接受并保留回执；不能把未知支持字段默默忽略。
- 是否包含统一的工作区文件清单、允许修改范围、测试入口、5-call 预算和任务完成条件。这是新 corpus 版本，三路一起使用。
- 不携带某路独有的 CODEX_HOME、安装/线程/turn ID 或 cache key；若保留缓存政策，应三路共同明确。服务端缓存本身仍需观测，不能由删除 key 推断没有缓存。

共同 `parallel_tool_calls=false` 可减少多 call batch 的交付差异，但这是一个新的受控策略，不应改写旧 `true` 组的含义。`strict` 与 `store` 也必须在预注册中选定并验证三路/provider 均接受；不要静默 fallback。特别是 store 影响后续响应取回能力，本组不以首次正常执行的通过代替故障恢复资格。

gateway 只在明确匹配的 qualification case 的第 1 次请求应用此政策。先核验原请求绑定了该 case、期望 model、允许工具集及无已有历史；若不符合则 hold，而非自由删改任意用户输入。使用同一确定性编码函数写出并发送 canonical UTF-8 bytes。

## 3. 必须保存的原件

每次请求至少保存：

```text
NN.original.request.json       原客户端 HTTP body 的完整字节
NN.effective.request.json      实际发送给 provider 的完整字节
NN.transform.json              policy/version/corpus SHA、original/effective SHA、变更字段
NN.request-metadata.json       可公开 headers 白名单、长度、单调/墙钟时间、operation/case/lane 关联
NN.response.sse                原始响应字节
NN.transport-result.json       HTTP status、bytes、终态、错误/超时阶段
```

记录 header 时只取明确的安全白名单，不采集 Authorization、Cookie、API key。body 中的 client_metadata 与 headers 分开存。白名单未含的字段不能在报告中声称已经逐项比对。

现有 native owner 的原 admission body/hash 保持原样。资格网关的变换必须有独立 manifest 将 original hash 关联到 effective hash；不得把 effective hash 伪装成 owner 原先接纳的字节，也不得偷偷修改原 admission/receipt。此实验测试的边界应准确写成“provider-facing canonical initial body”。

首轮硬门槛是每个 case 三路的 **effective body bytes 与 SHA 完全相等**，且 actual transport record 与文件的长度/SHA 一致。差异应在入模前直接 hold 并写原因；不能仅比较 tasks、工具名字或 JSON 数字就视为相同。

## 4. 后续轮次的边界

首轮相同以后，live 模型可能给出不同 proposal；tool call ID、工具返回内容、使用轮数和历史随后会不同。把下一轮不同历史强制改成同一 transcript，会变成另一种实验，也会破坏“各自真实推进”的解释。

因此，最小版本只宣称 **initial input identical**。仍逐次保存以后所有 original/effective body；若还要统一每轮 scaffold，可另设 canonical-scaffold 策略，仅统一固定 instructions/tool definitions/无关元数据，同时保留每路实际历史、call IDs 和真实反馈。它只能宣称 scaffold 相同，不能宣称 complete request 相同。

若用户要求每一轮模型输入都相同，应使用单个冻结 transcript/共同 proposal 流的控制实验；它隔离的是执行契约，不是独立 live 智能。不能用修改 call ID、伪造成功反馈或删除实际失败来制造同输入。

## 5. 先修观测，不先重跑分数

原 generic guard 应拆成结构化的 missing RPC ID / invalid call ID / unknown tool / duplicate call ID / budget exhausted，同时保留全部命中的原因。输出 `attempted_ordinal`、`admitted_count`、`limit`、name、call ID、thread/turn，并保留原 `LaneAbort.result`。

`run_case` 需要在 finally 中记录总墙钟与 phase timestamps，包括失败；当前 8 个失败 Codex case 的 `wall_ms` 缺失。成功模型调用、失败任务与拒绝 proposal 仍全部计入用量，不筛选有利样本。

为模型明确整段流 deadline；为工具明确从哪一步开始计时、完整输出读取/呈现是否在同一个工作预算内、取消清理有多少独立 grace。三路使用相同语义并以真实超时 case 验证。仅让配置字段数值一致不够。

长输出先加原 owner 上的阶段/每页计时，再在不减弱完整性校验的情况下评估完整 accessor 或大页。所有 output retention、model excerpt 与 checkpoint/fold 政策分别记录；不能把模型 excerpt 当成完整 terminal output。

## 6. 下一轮可接受的发布条件

发布前列出新 corpus/policy/source/binary SHA，并保存模型与 provider 前后验。说明服务是否共享及是否实际观测负载；固定或随机化 lane 次序和缓存政策，报告全部尝试。

先以一个任务验证三路实际 first effective bytes 相同、响应和工具回执能正常关联；再按预注册任务全集执行，不按首例成绩选取配置。更改提示、工具集、budget 或 normalization policy 时产生新组名/版本，旧失败原件原样保留。

报告分别列出协议/owner gate、任务 oracle、输入对齐 gate、usage 与 wall-time 完整度、恢复/取消/长输出门槛。任一未执行项写未执行；canonical-initial 通过不自动授予 production replacement 结论。
