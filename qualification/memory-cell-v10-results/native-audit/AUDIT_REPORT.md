# Run04 native actual：保存证据的独立 JSON 审计

## 结论与审计性质

对 run04 的保存数据作事后独立核对，**47 个阶段×类型×地址中，reference 接受 47 个、Rust 接受 47 个；与对应 owner 当前真值一致分别为 47/47 和 47/47。五组 socket 单值读出共 79/79 与真值一致。** 迁移后混合 worker 保存的一条 Apply 读出，其完整值和 trace 也与源值按公开 opcode 规则重放的结果一致。

这些是三项分别重算的指标：数值 parity、参数答案质量、真实 owner socket 的保存读出质量。没有由“parity 通过”推断“知识全正确”。本次只读 JSON 并计算文件 SHA、数值差和来源程序结果，没有加载参数模型、运行 encoder、训练或重新执行测试，也没有修改原始 CI 证据。独立审计共 1064 项一致性检查，发现 0 项不一致；检查次数不是独立科学样本量。

输入为 root 已认证并恢复的 run04 包，GitHub run 为 [40909855139](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40909855139)，request 为 `native-formal-04`，被测 source commit 为 `4131172a07fdf5bf5fe84f0397800bf900248ab8`。本报告记录所使用文件的 SHA，不冒称重新执行了 GitHub ZIP 来源认证或全部 tar 成员验证。输入身份完整列在 [INPUTS.json](INPUTS.json)；机器可读结论在 [AUDIT.json](AUDIT.json)。

## 1. 47 个阶段地址：先看执行一致性，再看源真值

| 阶段 | 类型 | 地址数 | Reference 接受 | Reference 等于 owner 真值 | Rust 等于 owner 真值 |
| --- | --- | --- | --- | --- | --- |
| original-checkpoint | semantic | 8 | 8 | 8 | 8 |
| original-checkpoint | procedure | 8 | 8 | 8 | 8 |
| corrected-training | semantic | 8 | 8 | 8 | 8 |
| corrected-training | procedure | 8 | 8 | 8 | 8 |
| deleted-rebuild | semantic | 7 | 7 | 7 | 7 |
| deleted-rebuild | procedure | 8 | 8 | 8 | 8 |

每行以 `SHA256(key)` 定位 reference／native 预测，以对应 owner snapshot 的 `(kind,key)` 取得真值。Semantic 按 reserve、pack、limit 顺序比较三个整数；procedure 比较四个 opcode。除答案外，还核对 source IDs、完整 lineage、artifact 字节摘要、parameter digest、owner／scope／cut、reference 文件 SHA 及 producer／fresh reader 进程收据。

共 948 个保存的 logit 坐标重新比较，Rust receipt 中记录的最大绝对差为 `7.1054273576010019e-15`；以 receipt 嵌入的 reference 重算时，47 行最大差都与原记录精确一致。全部满足原声明 `1e-4 + 1e-5 * abs(reference)`；margin 符合容差，typed 值完全一致。这是重算保存的数值，不是再次执行模型。

这里有一个需保留的 JSON 浮点边界：receipt 内的 reference 是外部文件经 Rust JSON 解析后再序列化的副本。其中 43/47 行合计 137/948 个 logit，以及 14/47 个 margin，与外部原 JSON 经 Python 解析的值存在 1 ULP 差异；最大观测差为 1 ULP，最大绝对差 `7.1054273576010019e-15`，原 reference 文件 SHA 全部匹配。AUDIT.json 逐行保留每个差异的零起始坐标、外部值、嵌入值、绝对差与 ULP 数。

本审计最初的“该浮点副本应严格相等”假设不成立，故明确记录这些差异，并按 `abs(a-b) <= max(ulp(a), ulp(b))` 检查副本；原模型 parity 的 1e-4/1e-5 容差完全不变。若直接将外部 reference JSON 与 saved native logits 都在 Python 中解析，最大差为 `0`。这两个最大差的参照对象不同，不应混写，也不应将 JSON 副本描述成位级完全相同；整数答案和 source-truth 比较仍要求完全相等。

47 是三个阶段的 16+16+15 个地址位置，不是 47 条新事实。更正与删除重建阶段的 procedure 参数 SHA 相同，因此按 `(parameter_digest,address)` 去重只有 39 对；按整个 artifact digest 去重为 47 对，因为 owner cut／封套身份不同。所有 source-truth 结果应限定到这批小规模 canonical 地址。

## 2. 79 次 socket 单值读出：保存行齐全

| 保存 observation | 模型阶段 | 读出数 | 等于 owner 真值 | 不同 query_id 数 |
| --- | --- | --- | --- | --- |
| original_parameters_on_actual_owner | original-checkpoint | 16 | 16 | 2 |
| fresh_process_original_parameters | original-checkpoint | 16 | 16 | 2 |
| actual_new_training_and_retention | corrected-training | 16 | 16 | 2 |
| fresh_process_new_training | corrected-training | 16 | 16 | 2 |
| delete_and_rebuild_from_remaining_sources | deleted-rebuild | 15 | 15 | 2 |

逐项检查 `status=ok`、完整值与 owner 源值相同、唯一 source ID、operation／prediction_kind、对应模型 artifact、bundle digest 和 generation。每组来源集合与该阶段全部 parameter records 精确一致，没有遗漏或重复。79 次包含原参数和新参数的冷重开重复，不能视为 79 个独立知识任务。

单值 helper 的 query_id 按 operation 重复；保存 readout 没有每条完整请求。因此本审计以单一 source ID 绑定 owner key，再检查完整覆盖，没有将 query_id 当作逐地址唯一标识。源请求的构造关系仍依赖被测 helper 代码身份；本文不声称单凭这些重复 query_id 复原了全部原始 request frame。

## 3. 迁移后 mixed worker：新增的事后真值比对

这条请求的完整 request 保存在 worker response 中，实体为 `inventory:semantic:1`，流程为 `inventory:procedure:0`，最大步数为 4。对应删除后 owner 快照给出：Event=5，policy={"limit":11,"pack":4,"reserve":5}，program={"opcodes":[1,2,3,6]}，Hold=false。

依据公开规则逐步计算：

| 操作 | 之前 | 之后 |
| --- | --- | --- |
| reserve_gap | 5 | 0 |
| pack | 0 | 0 |
| cap | 0 | 0 |
| stop | 0 | 0 |

预期结果为 completed／value=0，保存 readout 的完整 trace 与该结果一致。四个 source IDs、两个删除重建 artifact digests、generation=3、bundle digest、owner cut、worker request/query/model 身份及迁移恢复 pin 也相符。

**原 CI 对这条迁移后请求直接断言的是 status=Ok 和两个 cell digests；完整 source-truth 比对是本报告在保存证据上的事后派生，不是新跑的原生测试。** 本审计使用独立的小型七 opcode 源值解释函数，未导入原生或研究模型实现。

另有五份保存的原始组合读出（四个 entity/workflow 配对及一次 sleep/reload 后读取），已全部按相应源值重放并比较完整 value/trace。测试代码另外两次调用了组合强断言，但没有把返回 readout 存入 `NATIVE_ACTUAL.json`；本审计不把它们算进逐行保存证据。两次分别是坏 artifact 拒绝后的读取和更正参数冷重开后的读取。

## 4. 其他保存边界

五个保存的拒绝读出（步预算、未查询源更正后的 stale、hold、删除地址、歧义请求）均为预期状态，且 value=null、source_ids/cell_digests 为空。五个 owner PID 不同且保存了回收标志；第五个进程记录冷撤销拒绝。这里核对保存的结果与身份，不重新执行并发时序、停止或撤销，也不由空 payload 推断未计量的内部模型调用次数。

Numeric parity helper本身不做源真值门槛；native_train_worker 完成 fit/export 也不要求所有目标正确。此次 47/47 的质量结论来自本报告将保存预测与 owner 源值重新关联。它不代表未见措辞泛化、长期维护质量或通用系统优势。原生实际运行仍采用明确的 oracle／混合寻址边界、测试身份、同宿主 TCP 和独立保留的撤销见证；完整限制见 [实现报告](../IMPLEMENTATION.md)。

## 5. 关键输入身份与复核方法

| 输入 | SHA-256 |
| --- | --- |
| receipt.json | `25a4ffad028f5061b2c26cc6e38221f0a6f90a7de210a1acc7bcbd533c0cde9e` |
| NATIVE_ACTUAL.json | `93396743dac2303a81b7a72a23ed974f805051758c523912b7f56b42af25cb66` |
| owner-before.json | `fac4329ebc11c560383dd179a8335e72fa78ac5c78b5ccf9103cded15ccb071f` |
| owner-corrected.json | `eeb22a33f4fcfde581d5a5f24c916847e56d1d6dc25694829b70cc616e243cdf` |
| owner-deleted.json | `fb1ce83d7f8adec92b5ec16608073b7196772677916e85119032b62e7ac7b506` |

脚本 [audit.py](audit.py) 仅使用 Python 标准库。对已恢复的 run04 evidence root 执行 `python audit.py --input-root /absolute/path/to/restored-run04 --output /absolute/path/to/audit-output` 可重做同一事后统计；它不启动子进程、不访问网络、不解码权重张量或计算神经网络输出。输出目录必须在原始证据目录之外。

原始来源认证与此次派生审计应分别保留。此处 [AUDIT_PACKAGE.json](AUDIT_PACKAGE.json) 记录脚本、输入清单、派生 JSON 与本报告的字节数／SHA；原始证据不会被写回或补造缺失行。
