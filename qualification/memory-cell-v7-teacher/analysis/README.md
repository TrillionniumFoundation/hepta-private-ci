# V7 事后只读成本审计

`audit_costs.py` 是在教师一次性正式运行结束后编写的独立成本审计。它不属于预冻结的语义评价器，不改变任何语义预测、标签、资格门或原始汇总。它不导入教师实现，不执行模型，不联网，也不补发请求。

脚本只需要 Python 标准库。输入是原 V7 根目录，读取下列两个原运行目录：

```text
evidence/teacher-held-v1/
evidence/public-training-smoke-v1/
```

每个目录包含原 `RUN.json`、`results.jsonl`、`SUMMARY.json` 和 `case-NNNN/{admission.json,request.body.json,response.sse,result.json}`。断连导致没有 `response.sse` 时，保留缺失状态。脚本读取原请求体的三个输入字段和正文指纹，但不会把请求文本、教师 instructions、模型回答或 endpoint 写到审计输出。

## 执行

```bash
python3 analysis/audit_costs.py \
  --v7-root /path/to/semantic_v7 \
  --smoke-input /path/to/original-public-training-smoke-input.jsonl \
  --output /path/to/semantic_v7/evidence/cost-audit-v1
```

`--output` 必须尚不存在，而且不能位于两个原始运行目录之内。相对 `--smoke-input` 按 V7 根目录解析。若不知道原 smoke 输入文件，可以省略该参数；此时原文件 SHA 检查明确标为 unavailable，并另外报告由已保存 body 请求重建的 canonical JSONL 是否恰好匹配 `RUN.input_sha256`。原 held 输入默认读取 `holdout/requests.jsonl`。

退出码：`0` 表示可核查的证据绑定没有发现不一致；`1` 表示生成了审计结果但存在绑定/库存不一致；`2` 表示输入或输出条件使审计无法完成。**退出码 0 不表示全部成本已知、语义资格门通过或教师请求全部成功。** 原语义判断仍以冻结评价器输出为准。

新输出包括：

| 文件 | 内容 |
| --- | --- |
| `COST_AUDIT.json` | 每轮和合并成本口径、已记录用量、未知项、去重组与审计错误 |
| `CASE_COSTS.jsonl` | 每个原 operation 的结果状态、用量分类、指纹核验与缺失项 |
| `USAGE_OBSERVATIONS.jsonl` | 每份 result/终态 SSE 的原 usage 和归一化计数；保留冲突观察 |
| `SOURCE_SHA256.json` | 本次读取的全部证据字节数/SHA256及读取前后不变核验 |

## 计数规则

原 `SUMMARY.json` 的 completed-only 用量，与所有 result 中存在的用量分别统计。语义结果为 invalid/unknown 的请求，如果有已记录的 provider usage，也纳入 result 用量。

SSE 独立检查 `response.completed`、`response.failed`、`response.incomplete` 和 `error`。同一 provider response 的一致用量只计一次；result 与 SSE 是同一响应的两份证据，不能相加。相同终态重复次数单独记录。同一响应出现冲突计数时，保留所有观察，不选较小值、不把它算成精确费用。缺 provider ID 时仅在该 operation 内去重；跨 operation 重复 provider ID 会额外报错并在全局只计一次。

完整 JSON 但缺 SSE 空行分隔的末尾帧保存为未派发观察，不作为精确终态小计。部分 usage 字段仍单列每个已记录计数；只有自洽的非负整数 input/output/total 才纳入可相加的小计。cache input 与 reasoning output 是各自父项的组成部分，不额外加到总 token。可选详情相互矛盾时单列冲突。

未知费用始终为未知。`recorded_token_sum` 是已记录 token 小计，`total_provider_cost` 和 `dollar_cost` 明确为 null；没有价格来源或账单核对，不推算实际付款。模型服务端算力、内存与未返回 usage 的消耗不在已知小计之内。

核对原请求 canonical UTF-8 SHA、body 原字节 SHA、基于 RUN/index/body SHA 的原 operation ID、SSE 原字节 SHA、字节数、case result 与 aggregate result 的一致性，以及原输入与 teacher FREEZE 文件 SHA。所有读取的证据在写输出前重新核对；不修改原运行、冻结文件或评价器。

## 本地验证

```bash
python3 -m unittest discover -s analysis -p 'test_audit_costs.py' -v
```

九个测试只使用临时合成证据，覆盖 failed/incomplete/invalid 的用量、相同终态去重、冲突与未派发帧、部分用量/cache 子项、operation/request/body/response 绑定篡改和禁止覆盖输出。它们不替代原远程证据审计。
