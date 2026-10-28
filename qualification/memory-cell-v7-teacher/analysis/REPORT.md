# V7 语义寻址与教师路径：阶段二报告

> 来源与执行范围：教师、smoke 和两轮 baseline 数字来自本目录 `remote_evidence/` 的原始汇总副本；第二轮 baseline SUMMARY 已核对原 SHA。第二轮原候选运行及逐条 admission/body/result/SSE 的成本审计由 root 在远程原工作树完成，job 分别为 `1a18082212e-96a-2b10` 和 `1a1808d97d5-96a-2b41`。报告作者没有在本地重新执行真实 case 证据；远程成本产物及其 SHA 保留。审计源码保持交付时字节不变，冻结源、输入、评价器和原语义判分均未修改。[第二轮原汇总](remote_evidence/baselines-v2-summary.json) · [执行与产物记录](ANALYSIS_MANIFEST.json)

## 主要判断

**本轮没有取得可投入自动任务入口的语义路由资格，也没有证明自适应 Cell 结构产生独立收益。** 原冻结 V6 在两套独立合成英文留出集上的正确覆盖率分别为 10.0% 和 61.7%；同一模型没有重训，变化体现测试分布敏感性，不能记为能力从 10.0% 提升到 61.7%。教师只为 69/180 个请求取得经原 transport 验证的完成结果，111 个仍为 unknown/invalid；预先规定的完整性门未通过。[原 V6 报告](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/984baab7ad5ceebaf97f11d6c60c928d3b69f1b1/qualification/memory-cell-v6/REPORT.md) · [本轮教师独立评价](remote_evidence/teacher-evaluation.json)

## 两套独立 held 必须并列

两套集合都由与候选开发分离的助手编写，都是有限英文任务的合成数据，均为 120 条合法请求和 60 条 OOD。它们不是人类研究、真实业务样本或开放域能力证据。原 V6 报告没有提供足以判断哪一套“更难”或“更真实”的风格标定；本次 held 作者没有读取旧 held 的文本，所以不从成绩反推这种排序。[原 V6 数据限制](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/984baab7ad5ceebaf97f11d6c60c928d3b69f1b1/qualification/memory-cell-v6/REPORT.md) · [本轮 held 说明](../holdout/README.md)

新 held 的作者读取了公开的任务定义和 train/selection/development 接口，再手写多种表达；许多请求明确指定月份、计算方向、窗口或数值输出形式。utterance 长度为 12–32 个空格分词，中位数 19，平均 19.18。与 1,986 条公开语言输入的规范化精确重复为零，但这不保证语义、句法和词汇独立。该风格可能与既有 cue 解析更吻合，这只能是解释差异的假说，不能冒充已经隔离因果的实验。[读取范围](../holdout/ACCESS_LOG.json) · [构造与冻结](../holdout/README.md)

| 候选和集合 | 合法正确 | 合法错路由 | 合法拒绝 | 合法 unknown | 正确覆盖率 | OOD 错接受 | OOD unknown | 门 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| V6，原独立 held | 12/120 | 0 | 108 | 0 | 10.00% | 0/60 | 0 | 未通过 |
| V6，新独立 held | 74/120 | 1 | 45 | 0 | 61.67% | 3/60 | 0 | 未通过 |
| 确定性，原独立 held | 89/120 | 2 | 29 | 0 | 74.17% | 8/60 | 0 | 未通过 |
| 确定性，新独立 held | 92/120 | 8 | 20 | 0 | 76.67% | 8/60 | 0 | 未通过 |
| V5，原独立 held | 9/120 | 0 | 111 | 0 | 7.50% | 0/60 | 0 | 未通过 |
| V5，新独立 held，依赖修复后原候选 | 7/120 | 0 | 113 | 0 | 5.83% | 0/60 | 0 | 未通过 |

新 held 的 V6 只满足 OOD 错接受不超过 3/60 的一侧，仍未达到合法正确至少 96/120 的要求。确定性对照既未达到覆盖门，也超过 OOD 错接受门。V5 完整运行虽然拒绝全部 60 条 OOD，却也拒绝了 113/120 条合法请求，同样不合格。第二轮 V6 的 74 正确／1 错路由／45 拒绝、确定性的 92／8／20 及其 OOD 计数均与第一轮相同。不得只选取 61.7% 隐去原 10.0%，不得重新调阈值后把本轮样本继续称为未见测试集，也不应把两套集事后合并成一个更好看的单一分数。[第一轮 baseline 原汇总](remote_evidence/baselines-v1-summary.json) · [冻结评价协议](../baselines/EVALUATION_PROTOCOL.json)

V5 首次运行因缺少 SciPy 而没有取得有效预测，原记录是 120 条合法请求和 60 条 OOD 全部 unknown，不能把这次环境失败写成 V5 的“0% 语义能力”。补齐原 requirements 的 NumPy 2.3.5、SciPy 1.17.0、scikit-learn 1.8.0 后，执行方在原候选与冻结输入不变的条件下取得了完整 180 条结果：合法 7 正确、0 错路由、113 拒绝；OOD 0 错接受、60 拒绝；unknown 为零。没有重训或重新校准。第二轮 baseline 脚本 exit 0 只表示三个输出流的协议完整，`all_gates_pass` 仍为 false。[首次失败原记录](remote_evidence/baselines-v1-summary.json) · [第二轮完整原汇总](remote_evidence/baselines-v2-summary.json) · [评价器退出码定义](../baselines/EVALUATION_PROTOCOL.json)

运行准备还发生过一次独立失败：科学依赖安装 job `1a1807443ef-96a-2aba` 在 480 秒下载 deadline 到达时失败；之后利用已取得的缓存完成安装，恢复 job `1a18082212e-96a-2b10` 成功。这两次环境尝试和首次缺 SciPy 的服务失败均保留，不能只留下最终七条正确预测。下载、安装、失败进程、缓存占用和恢复工作的成本属于本轮实验账本；目前没有完整计时/资源账单，未测部分保持未知，不能按零处理，也不能混入模型语义错路由分数。以下 provider token 审计不涵盖这些环境准备成本。[执行方回报记录](ANALYSIS_MANIFEST.json)

## 教师：有效完成子集正确，完整请求链路未合格

正式 held 的 180 个原请求一次性执行，没有自动重试。原冻结评价器确认：合法正确 50/120，合法 unknown 70/120；OOD 明确正确拒绝 19/60，OOD unknown 41/60；合法错路由 0、合法错误拒绝 0、观测到的 OOD 错接受 0。全部 69 个有效完成结果在这个有限标签任务上正确，但剩余 111 个请求不能从分母中删除，OOD unknown 也不能算成正确拒绝。[教师独立评价](remote_evidence/teacher-evaluation.json)

| 本轮教师指标 | 结果 |
| --- | ---: |
| 原始请求数 | 180 |
| 通过原 transport 验证的 completed | 69 |
| unknown/invalid | 111 |
| 合法正确覆盖 | 50/120 = 41.67% |
| 合法 unknown | 70/120 |
| OOD 已确认正确拒绝 | 19/60 |
| OOD unknown | 41/60 |
| 预先规定的完整性要求 | 180 个原请求全部终态且 unknown = 0 |
| 实际资格门 | 未通过 |

不能把完成子集的 69/69 正确称作整体 100% 成功；也不能把传输断连或未获验证终态全部归因于模型不理解任务。模型标签正确性、provider/transport 完成率和整个入口的可用性需要分别报告。原 case 成本审计按保存的 `error_type` 记录了 92 个 `RemoteDisconnected`、10 个 `IncompleteRead`、3 个 `JSONDecodeError`、3 个 `TimeoutError` 和 3 个 `ValueError`，合计 111；这些是观察到的错误类型，不能直接代替根因或语义错误标签。教师端到端墙钟 1,225.493 秒，客户端 CPU 3.343 秒；这不是服务端模型的 CPU、GPU 或完整内存开销。[远程审计记录](ANALYSIS_MANIFEST.json) · [教师原运行汇总](remote_evidence/teacher-summary.json)

## 已记录成本不能只计成功请求

原教师 `SUMMARY.json` 只累加 69 个 completed 的 usage，记录输入 131,653、输出 11,581，共 143,234 token。独立语义评价器扫描所有 result 后，72 条携带可用 usage，记录输入 137,369、输出 12,349，共 149,718 token；其中三条 invalid/unknown 的用量为输入 5,716、输出 768，共 6,484 token。两种数字是在说明不同口径，后者不能被成功率过滤掉。[教师原汇总](remote_evidence/teacher-summary.json) · [独立评价用量](remote_evidence/teacher-evaluation.json)

| 已有 result 口径 | 有 usage 的条数 | 输入 token | 输出 token | 合计 token |
| --- | ---: | ---: | ---: | ---: |
| 正式 held，69 个 completed | 69 | 131,653 | 11,581 | 143,234 |
| 正式 held，所有结果中有 usage 的请求 | 72 | 137,369 | 12,349 | 149,718 |
| 上行中额外的 invalid/unknown | 3 | 5,716 | 768 | 6,484 |
| public-training smoke | 1 | 1,888 | 76 | 1,964 |
| 正式 held 与 smoke 合计已记录 | 73 | 139,257 | 12,425 | 151,682 |

表中第三行已经包含在第二行，不能重复相加。独立评价器另外记录 132,937 cached input token，它们是 input 的子项，不是应再加一次的 token。远程原始 SSE 审计确认已记录合计仍为 151,682 token，没有从 SSE 补出 result 之外的额外用量；但正式 held 仍有 108 条请求的 usage 未知，因此这只是已记录小计，不是总费用，也不是所有未知请求零消耗。完整成本仍未知；没有账单与价格核对，不推算金额。[独立评价](remote_evidence/teacher-evaluation.json) · [smoke 原汇总](remote_evidence/smoke-summary.json) · [审计产物指纹](ANALYSIS_MANIFEST.json)

## 原始证据成本审计已完成

root 在远程原工作树使用未修改的 `audit_costs.py` 完成了只读审计，job `1a1808d97d5-96a-2b41` 成功。审计源码 SHA256 为 `5f390cfeaf898fa7f65265b90d538525084badcb8d32ecf32cadd49c4b1a46b0`；九项合成边界测试在远程再次全部通过，耗时 0.194 秒。没有联网补发模型请求，没有修改原始证据或预冻结语义评分。[成本原审计](../evidence/cost-audit-v1/COST_AUDIT.json) · [审计规则](README.md) · [执行方回传记录](ANALYSIS_MANIFEST.json)

| 原证据审计口径 | 实际结果 |
| --- | ---: |
| 案例数 | 181 = 正式 held 180 + smoke 1 |
| 原结果 completed | 70 = 正式 held 69 + smoke 1 |
| 原结果 unknown/invalid | 111 |
| 有可用 usage 的案例 | 73 = 正式 held 72 + smoke 1 |
| usage 仍未知的案例 | 108 |
| 可核查绑定的错误总数 | 0 |
| 存在绑定核验错误的案例 | 0 |
| 已派发的终态 SSE 事件 | 76 |
| 携带可用 usage 的终态观察 | 73 |
| SSE provider `empty_terminal_response` | 3 |
| 重复终态／冲突用量／帧解析问题 | 均为 0 |
| 经 result 与 SSE 核对的已记录 token | 输入 139,257 + 输出 12,425 = 151,682 |
| 其中非 completed 案例的已记录 token | 输入 5,716 + 输出 768 = 6,484 |

76 个 SSE 终态事件不等于 76 个有效语义完成；其中能否解析出契约内最终结果仍由原 transport 与冻结评价器决定。合并口径中的 70 completed 包含一条 smoke，正式 held 的 completed 仍为 69。绑定核验零错误只表示已可核查的原 operation/request/body/response 等记录未发现不一致，不会消除 108 条用量缺失，也不把 unknown 变成成功或零成本。[审计结果与来源范围](ANALYSIS_MANIFEST.json)

独立产物已保存，`COST_AUDIT.json` 为 91,166 B。以下指纹由 root 从远程实际产物回传；本地报告作者没有重新下载或二次执行这些原始 case。

| 产物 | SHA256 |
| --- | --- |
| `COST_AUDIT.json` | `830592fc0ace739b181fa9520a9707dcb7d4eadc7092882c0d1bae1dd52a0c5d` |
| `CASE_COSTS.jsonl` | `0fa54e8d79c991bb7d5d5a231feb5bcc6770dbac6428af4431bcb41cca49da68` |
| `SOURCE_SHA256.json` | `10d3813b96f423a8b7608ed195c75660c9fc8fde46dc541b5520a6925fd9176f` |
| `USAGE_OBSERVATIONS.jsonl` | `7d008240cac76a4c34aa3dbe4379f1b1f9a8180b58a1abad0e7d60b382fba065` |

## 对下一阶段的约束

当前证据支持继续比较更适合的语义编码、训练路由和教师蒸馏，但教师链路必须先取得稳定的原 operation 终态和可审计用量。新的训练或校准需要新的开发资料与下一套冻结评估；本轮两个公开 held 都不能继续充当未见资格证明。

语言入口与结构实验仍需分开：原结构实验在 oracle 任务 ID 下完成了有限程序发现和真实结构变更，但同信息静态表同为 72/72，且状态更小、算子总调用更低。本轮教师和路由的结果没有改变这一结构结论，不能据此宣称 Cell 自发形成通用智能，也不构成 native agent 已能取代 Codex 的端到端证据。[原结构与完整成本结论](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/984baab7ad5ceebaf97f11d6c60c928d3b69f1b1/qualification/memory-cell-v6/REPORT.md)
