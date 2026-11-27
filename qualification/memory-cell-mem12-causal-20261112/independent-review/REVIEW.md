# MEM12 独立原件复核

状态：**VERIFIED_CONSISTENT**。复核 1420 个索引原件及 80 条生成行，原件复核前后 hash 一致。

## 主结论

冻结 full-output parser 保持原样：十个干预臂各 **0/8**，所有 80 条输出均不符合主格式。每个 on_bm25 对照均 **0 胜、0 负、8 平**。只有 8 个配对来源、1 个模板；`HOLD` 保持。

四个空送达臂在每个来源中的 request bytes、model-input bytes、tensors、渲染 prompt、输出文本和输出 token 均完全一致：**8/8 来源通过**。off 没有 reader store 或 memory 输入文件；其他空送达路径各保留自己的状态和开销。

## 主结果与探索性内容诊断

后两类内容观察为看到结果后定义的 post hoc 调试指标，不能改分或替换冻结 selector。

| 干预臂 | 主成功 | 合法主格式 | 正文提及真值（post hoc） | 相关 key 送达 | 输入 tokens | 输出 tokens |
|---|---:|---:|---:|---:|---:|---:|
| on_bm25 | 0/8 | 0/8 | 3/8 | 8/8 | 1094 | 80 |
| off | 0/8 | 0/8 | 0/8 | 0/8 | 785 | 152 |
| delete | 0/8 | 0/8 | 0/8 | 0/8 | 1092 | 94 |
| replace | 0/8 | 0/8 | 0/8 | 8/8 | 1094 | 80 |
| retrieval_off | 0/8 | 0/8 | 0/8 | 0/8 | 785 | 152 |
| delivery_off | 0/8 | 0/8 | 0/8 | 0/8 | 785 | 152 |
| exact_kv | 0/8 | 0/8 | 8/8 | 8/8 | 938 | 80 |
| finite_icl | 0/8 | 0/8 | 1/8 | 3/8 | 1094 | 80 |
| uniform_replay | 0/8 | 0/8 | 2/8 | 3/8 | 1093 | 80 |
| retention_off | 0/8 | 0/8 | 0/8 | 0/8 | 785 | 152 |

Exact-KV 的 8 条正文均提及真值，但全部回答完整句子，仍不满足 one-color-only。BM25 正文仅 3/8 提及真值；相关记录 8/8 已送达，其余正文错误不能归因于目标记录未被检索。

## 错误替换的探索性归因

replace 正文 3/8 提及替换值；on→replace 输出发生改变 3/8。只有 **2/8** 从原真值改成替换值。source-08 在 on 时已经错误输出 purple，替换后仍为 purple，不能当作替换引起的跟随；source-05 从正确 purple 改答 distractor red，也没有跟随 replacement pink。

| 来源 | 真值 → 替换值 | on 输出 | replace 输出 | 输出改变 | 新提及替换值 |
|---|---|---|---|---|---|
| source-01 | yellow → green | The courier must use a yellow badge. | The courier must use a green badge. | True | True |
| source-02 | white → red | The courier must use a blue badge. | The courier must use a blue badge. | False | False |
| source-03 | purple → pink | The courier must use a blue badge. | The courier must use a blue badge. | False | False |
| source-04 | orange → yellow | The courier must use a blue badge. | The courier must use a blue badge. | False | False |
| source-05 | purple → pink | The courier must use a purple badge. | The courier must use a red badge. | True | False |
| source-06 | yellow → green | The courier must use a purple badge. | The courier must use a purple badge. | False | False |
| source-07 | purple → pink | The courier must use a purple badge. | The courier must use a pink badge. | True | True |
| source-08 | blue → purple | The courier must use a purple badge. | The courier must use a purple badge. | False | False |

## 成本

输入 **9,545 tokens**；输出 **1,102 tokens**。Provider 含 setup 墙钟合计 **372.326902 秒**；arm 墙钟合计 **374.529526 秒**。公共 A writer **0.449167 秒**，只计一次。
Run 阶段 **375.179779 秒**；另行 prepare **13.333157 秒**。模型子进程 user CPU 合计 **455.914174 秒**、system CPU **20.216432 秒**；单进程峰值 RSS 的最大值 **1,203,180 KiB**，RSS 不相加。归档/readback 成本未独立确定。

同上限不等于同实际成本。输出长度和 setup 开销不同；全部主分为零，不能比较每正确答案效率。

## 核验范围与限制

脚本未导入或执行实验实现，未执行 tokenizer 或模型，未调用网络。核验 archive/索引、冻结源码、A 事实与 SQLite/snapshot、A 退出→C 新进程时序、actor 原输入/stdout、provider admission/request/log、model-input 字节与 tensor 形状、删除/替换与空送达、主分与成本。

- One generated task template, eight paired sources; 80 rows are not 80 independent episodes.
- All primary responses violate the frozen full-output format. No primary memory benefit is established.
- Post hoc lexical observations do not replace primary scoring or support adoption.
- Deterministic A ingestion; research Python SQLite, not production native owner.
- Local retained-byte consistency does not authenticate physical host or production owner.
- Recorded tokenizer tensors are verified against logs and receipt pins but not recomputed with tokenizer assets.
- Model.generate input is recorded; internal forward calls/cache accesses are not observed.
- Read-only system roots and frozen runtime remain mounted; isolation concerns known task-state paths.
- Equal limits do not imply equal actual cost; zero primary successes prevent cost-per-correct comparisons.
- No learned association or parameter consolidation was evaluated.

Source：`811e0e27190066e81a23eebed8ad559ae67d228e`；tree：`2043cbf11fd00662cc23562123c27ae4e6f72580`。
Protocol：`f623a23197fe94b3d5434ffac1f02cb3d99398ca4c69aad18716dbeeef1b2d82`。Archive：`29ab6cde66622dd76ebee5cf65ae51c6c17dbbbbe0a66b7b7626d77358782e05`。

逐行输出、检查类别、配对统计和成本见 REVIEW.json；独立复算实现为 review.py。
