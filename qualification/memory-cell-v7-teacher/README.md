# Memory Cell V7 Teacher：冻结语义对照与原证据复核

发布目录为 `qualification/memory-cell-v7-teacher`。本轮比较一个冻结教师路由参考与原 V5、V6、确定性候选，使用同一套独立代理编写的合成英文输入。**四条路径均未通过资格门；本目录保留完整失败、未知结果和已记录成本，不构成生产语义入口或通用智能的验证。** 详细结论见[阶段二报告](analysis/REPORT.md)。

## 实际结果

新 held 共 180 条：120 条合法输入、60 条 OOD。允许输入只有 `utterance`、`series_name`、`date`；标签和审计 family 只在评价器侧。六个合法操作为 `at`、`previous`、`change`、`mean3`、`range3`、`peak3`，本轮只评估操作寻址，不执行数值任务、真实工具或 Cell 结构变更。[held 说明](holdout/README.md) · [冻结评价协议](baselines/EVALUATION_PROTOCOL.json)

| 路径 | 合法正确 | 合法错路由 | 合法拒绝 | 全部 unknown | OOD 错接受 | 资格门 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 原 V5，完整第二轮 | 7/120 | 0 | 113 | 0 | 0/60 | 未通过 |
| 原 V6 | 74/120 | 1 | 45 | 0 | 3/60 | 未通过 |
| 确定性对照 | 92/120 | 8 | 20 | 0 | 8/60 | 未通过 |
| 教师，一次性正式运行 | 50/120 | 0 | 0 | 111 | 0/60 已观测 | 未通过 |

教师的 111 条 unknown 包括合法 70 条、OOD 41 条；另外 19 条 OOD 得到有效拒绝。有效 completed 为 69/180，不能把这个完成子集的正确结果写成整轮 100% 成功，也不能将 OOD unknown 记成正确拒绝。预先规定的门要求合法正确至少 96/120、OOD 错接受最多 3/60，并且全部 180 个原请求终态完整、身份正确、unknown 为零。[第二轮 baseline 原汇总](analysis/remote_evidence/baselines-v2-summary.json) · [教师独立评价](analysis/remote_evidence/teacher-evaluation.json)

原 V6 held 的正确覆盖是 12/120（10.0%），新 held 为 74/120（61.7%）。模型、参数和阈值未变；两套独立代理合成数据的表达分布不同，这个差异不能记为能力提升。两套集合都不是人类研究或真实业务分布，发布后也不能继续作为未见资格集。[完整并列结果](analysis/REPORT.md)

V5 首次因缺 SciPy 而没有产生有效预测，120 条合法及 60 条 OOD 全部 unknown；这属于环境失败，不能写成 V5 的 0% 语义能力。依赖安装另有一次 480 秒下载 deadline 失败，后续利用缓存完成原依赖环境并成功运行原候选。失败尝试、缓存恢复及未测准备成本均保留；第二轮 baseline 的 exit 0 仅表示三路输出协议完整，`all_gates_pass` 仍为 false。[第一轮 baseline](analysis/remote_evidence/baselines-v1-summary.json) · [第二轮 baseline](analysis/remote_evidence/baselines-v2-summary.json)

## 冻结范围与模型身份限制

教师的源码、prompt、协议和来源文件在执行前冻结；正式运行对每个原输入最多提交一次 POST，最多四个并发、每请求 30 秒期限和 256 个输出 token。[教师冻结记录](teacher/FREEZE.json) · [教师协议](teacher/PROTOCOL.json)

教师 model 字段固定为 `qwen38-flash-next-uc`，这是供应商服务标识。相同标签不保证供应商内部权重、服务修订或采样默认值固定；本实验没有取得可验证的权重快照。因此，固定 prompt、代码和模型名称不等于未来联网调用能够逐字复现本次结果。原 V5/V6 的本地模型资产另由其冻结清单和 SHA 校验，两种身份保证不能混为一谈。[模型身份限制](teacher/PROTOCOL.json) · [原基线核验](baselines/README.md)

**冻结教师正式运行不可重试。** 已提交但没有完整响应的 operation 保持未知，不通过新目录、新 operation 或新 POST 补齐，也不通过重算 freeze SHA 重新定义原候选。`Idempotency-Key` 不是供应商去重保证。本轮可复现工作是读取原始字节、重新判分和核对成本；未来新的模型或 prompt 研究需要另立实验和新的冻结 held，不覆盖本次结果。

## 归档与只读复核

可读汇总、RUN、ENVIRONMENT、成本审计及报告留在仓库；完整 admission、request body、SSE、逐 case result、两轮 baseline、评价输出和环境安装失败日志保存在以下归档中：

- [ARCHIVE_INDEX.json](evidence/ARCHIVE_INDEX.json)：归档身份、内容和复原依据。
- [raw-runs-20261028.tar.gz](evidence/raw-runs-20261028.tar.gz)：原运行目录与日志，保持归档内路径。
- [COST_AUDIT.json](evidence/cost-audit-v1/COST_AUDIT.json)：独立原证据成本审计。

先按索引核对归档 SHA256 和字节数，然后解压到新目录，保留发布目录和原归档。下面示例假设归档条目保留 `evidence/` 前缀，并且当前目录为仓库根；所有重算输出都写入新目录。

```bash
HEPTA_V7_SOURCE="$PWD/qualification/memory-cell-v7-teacher"
HEPTA_V7_REVIEW="$(mktemp -d /tmp/hepta-v7-review.XXXXXX)"

sha256sum "$HEPTA_V7_SOURCE/evidence/raw-runs-20261028.tar.gz"
python3 -m json.tool "$HEPTA_V7_SOURCE/evidence/ARCHIVE_INDEX.json"

cp -a "$HEPTA_V7_SOURCE/teacher" "$HEPTA_V7_SOURCE/holdout" \
  "$HEPTA_V7_SOURCE/baselines" "$HEPTA_V7_SOURCE/analysis" "$HEPTA_V7_REVIEW/"
tar -xzf "$HEPTA_V7_SOURCE/evidence/raw-runs-20261028.tar.gz" -C "$HEPTA_V7_REVIEW"

python3 "$HEPTA_V7_REVIEW/baselines/score_teacher.py" \
  --held "$HEPTA_V7_REVIEW/holdout" \
  --results "$HEPTA_V7_REVIEW/evidence/teacher-held-v1/results.jsonl" \
  --output "$HEPTA_V7_REVIEW/recomputed-teacher-evaluation"

python3 "$HEPTA_V7_REVIEW/analysis/audit_costs.py" \
  --v7-root "$HEPTA_V7_REVIEW" \
  --output "$HEPTA_V7_REVIEW/recomputed-cost-audit"
```

教师评分器重新得到不合格结果时返回 1；这不是补发请求的理由。成本审计返回 0 只表示可核查证据没有发现绑定错误，不表示全部费用已知或语义门通过。若索引提供原 smoke 输入文件路径，可向成本脚本追加 `--smoke-input` 进行原文件 SHA 核验；未提供时明确保留该项 unavailable，并报告从原 body 重建的 canonical 输入是否匹配 RUN 中指纹。[评分器说明](baselines/README.md) · [成本审计说明](analysis/README.md)

重算结果包含运行路径或耗时时，不能用整个新 JSON 与旧 JSON 的逐字相等替代语义计数、请求身份和原源文件 SHA 的核对。不要改动冻结 `teacher/`、`holdout/`、`baselines/` 文件来消除失败，也不要重新运行教师网络提交命令。若使用原教师 `--observe-only`，仅在解压副本上观察；它不能补齐任何 unknown，也不会调用模型。

## 已记录成本与未测部分

root 在远程原工作树使用未修改的事后成本审计脚本，核对 held 180 条加 smoke 1 条，共 181 个案例：73 条有可用 usage、108 条仍未知。已记录输入 139,257、输出 12,425，共 **151,682 token**；其中三条非 completed 的用量为 6,484 token。只统计 69 条 held completed 会漏掉这三条，不能以成功率过滤成本。[成本原审计](evidence/cost-audit-v1/COST_AUDIT.json) · [教师原汇总](analysis/remote_evidence/teacher-summary.json) · [smoke 原汇总](analysis/remote_evidence/smoke-summary.json)

核验错误为零，无重复终态、用量冲突或帧解析问题；九项审计边界测试在远程全部通过。零绑定错误不会消除用量缺失。151,682 是已有记录的小计，不是总费用；缓存输入是 input 的子项，不能重复相加。供应商算力、权重、内存、未返回 usage 和环境准备成本没有完整测量，因此不能用客户端大小或路由耗时宣称 native agent 比 Codex 更轻。[完整成本与限制](analysis/REPORT.md)

## 发布文件与拼写检查

原 SSE 和 case 明细以归档保存，不作为源码 lint。代码、报告与可读索引仍按仓库规则检查；不要将模型错误输出自动修正成新证据。冻结 V5 公开源快照有一处已确认的专业词汇误报；只对以下精确发布路径排除，不修改快照，也不扩大全局词典：

```text
*qualification/memory-cell-v7-teacher/holdout/source/v5/selection_language.py
```

本轮没有训练或蒸馏紧凑模型，没有改数值执行器，也没有新增自适应结构资格证据。原结构实验中同信息静态对照不劣的结论继续成立；语言入口、执行替换和结构收益需要各自的可归因验证。[阶段二报告](analysis/REPORT.md)
