# 原始公开状态的归一化回归证据

## 结论与范围

本补充只新增独立回归、输入 fixture 和证据；生产修复已经存在于 [3c94ea8](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/3c94ea8252619ba3fa1f1821bef96a7f2b7f66fd)。
基线为 [ded3f65](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/ded3f65bd1f084d52e4cd14454f3469df549274c)，tree 为 `1ba1e1a7a80479235899e1f5394b27ce8c05fd28`。
本补充保留原始 72 条完整公开状态及 24 个匿名来源分组；相较上游 5 维常量用例，它覆盖实际 47 维输入和原有分组。
测试的结果、receipt 和校准样本使用现有制造 fixture；它们不是原研究训练凭证。

## 原运行与失败原因

原运行：`/home/qq/ctrl-real-study-20261112-1333/run-v1/frozen`。
原 source：`0696d242632bd1bad6668267c52b0bd791241504`；原 FROZEN SHA256：
`5ec574f35366cbffb12555832dc611a722e92d72ea3c709feaa838f6d619cf27`。
原 EXPORT 为 126/126、UNKNOWN 0；其字节 SHA256：
`1e686def4a809f40a96f56e3dc5ecbbcf90bc0df81bb51cf9a0164652d917a1f`。
原 126 条完整 EXPORT 没有复制进本补充，分支结果不在公开状态 fixture 内。

只读计算确认 72 条已知训练行构成 72×47 数组，24 个来源各 3 行，权重均为 1。
只有第 46 列越界：`log1p(40)` 的 observed minimum = maximum 为
`0x1.db565458eac4ep+1`，加权均值为 `0x1.db565458eac47p+1`，低 7 ULP。
原严格加载器因此拒绝 `Invalid normalization or observed envelope`；
原 fit terminal 仍为 exit 1，其 log SHA256：
`5feaf3de3cb64ec8f9ac1df824b85c83333c0379365bee02ba6ae6acefd5147a`。

正权重均值必须位于逐列原观测范围内。上游在 scale 计算前对 producer 均值执行 clip，
继续使用同一 observed minimum/maximum；它没有修改 parser 比较、放宽容差或扩大输入范围。
ded3 producer 字节 SHA256 为 `179bfcd6d436e7a28d1171d58715e96993cfc81b1e3c7af9fa08e037324d885b`。
严格 parser 与原版本逐字节相同：`829098d6eca3851ccc11eceaf7d8efdc468826f032a97ccb4ccc27c9654f371a`。

## 实际验证

| 验证 | 观察结果 | 边界 |
| --- | --- | --- |
| 原 0696 producer + 同一公开状态回归 | 1 项、1 个预期错误 | 复现原归一化异常 |
| ded3 + 新增实际输入回归 | policy 19 + checkpoint 7，26/26 通过 | 本地 Python 3.12.14 / NumPy 2.3.5 |
| 上游常量和篡改回归 | 保留并通过 | 覆盖 6、11、72 行和 71+1 不等来源；重算外层 hash 后 1 ULP 外部篡改仍拒绝 |
| 最终 just fmt | exit 0 | 之后核对被测源和 fixture 字节全部不变，未再跑测试 |

新增用例的 serializer/strict-loader 往返发生在同一进程。
用例名称里的 cold_load 不应解释为原 driver 的新进程恢复或真实模型 checkpoint 认证。
早先 formatter 因 PATH 中缺少递归调用的 just 返回 1，修正 PATH 后最终返回 0。

## 原始证据与完整性

`H_READBACK.json` 保留原 h 请求和返回 JSON 值，包括超时；`H_OUTPUT.jsonl` 是按字节重组的原始完整输出。
读取同一 session 的首尾页遇到超时后，从已观察到的 output.log 用异步只读路径取得尾页；没有重启 probe。
原任务 key 为 `neuro4-normalization-read-862531d-v1`，exit 0，output_complete = true。
它与旧 UNKNOWN probe 是不同只读任务，不合并状态。

- 原输出：27,051 B，SHA256 `9ae78ee81ad8dcfcdddca62cc758c9b0cffc65217a8387196ce25e3ad715d0be`。
- 完整公开状态投影：54,038 B，SHA256 `426ff918e7cf38defddecfbb4b92acb8e506dbda247da2b7534a4f7c615cc90f`。
- 测试 fixture 无损 zlib+base64 保存该投影，测试实际检查长度及 SHA256 后解析全部 72 行。
- `VALIDATION.json` 记录执行观察和精确源/文件摘要。scratch 在打包日志前再次断连；它明确标注原本地日志尚未归档，不冒充原日志字节。
- 完整原本地日志仍位于 `/workspace/scratch/862531d11598/neuro-normalization-work`，待环境恢复后可补存。

## 后续执行边界

原失败 run、START、EXPORT 和来源 pins 均保持不变；没有调用 host fit、collect 或 actor。
[上游 REFIT_DECISION](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ded3f65bd1f084d52e4cd14454f3469df549274c/qualification/ctrl-real-comparison-20261112/REFIT_DECISION.zh-CN.md)
要求 fresh create-only run-v2；macro_policy 源变化会改变 converter/fitter 来源摘要。
旧 126 EXPORT 不能靠换目录、换 hash、重造 receipt 或放宽 manifest 被承认为新版本训练输入。
本回归不关闭真实冷恢复、独立 B/C、功效/完整成本、科学收益或 native owner/cadence 门。
