# E2：权重冻结后的新来源评测预注册

本目录固定两名学生完成自身失败状态训练之后的评测选择规则。原始训练证据已发布于 [`c1ce4de7`](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/c1ce4de7c9bd6c48bae155aeedbfe04f7ccf3196/qualification/cell-current-student-correction-20261121/training-success-20261121)：两个原学生各完成 8 次既定更新，总计 16/16 次。这里没有增加训练预算。

## 冻结内容

- `WEIGHTS_FROZEN.json` 绑定两份实际新权重、原父模型和完整训练终态。
- `SELECTION.json` 固定原 8 个仓库及顺序、Git 截止日期、预算、请求策略和独立 owner。
- `EXCLUDED_INVENTORY.json.part000` 至 `part002` 必须按序无分隔拼接；完整 721,451 字节，SHA-256 `dac49a908669ef870d1efce1117699e13698cded0a3098df895a8749f0d90f2c`。排除 47 个旧仓库、40 个 owner、9,905 个具有明确来源的 SHA 值。部分值是保守保留的原收据绑定哈希，不能称为函数 AST。
- `jaraco/inflect` 与 `agronholm/exceptiongroup` 在扫描前拒绝。其余 6 个来源仍按原顺序；不增加仓库、不替换失败任务、不放宽限额。不能凑齐 4 个独立 owner 时，面板以 `PANEL_REFUSED` 结束。

实际选取代码和原预算见 [固定协议 4641310](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/464131053063339ae4c6dbd254ee3c0a27b532b4)。本目录 JSON 中的 pending 字样是冻结时的事实快照；实际发布凭据必须另外绑定真实 Git commit、ref 读回和观察时间，不能改写本目录数据来填入自身 commit。

## 去重与证据边界

旧 E5 原材料已用实际 CPython 3.12.3 重放 AST 提取。相较本地 3.12.14，两个非测试函数及所在模块的 AST 哈希不同；原始字节、owner 和测试指纹不变。实际版本输出用于本次排除清单，两个版本及差异原件均保留。一个旧 loguru 文件仍有真实 SyntaxError；其原始 SHA 和 owner 被保留，AST 完整覆盖为 false。去重不证明不存在预训练污染或语义重复。

旧材料与历史收证见 [E5 排除原件](../../../evidence/e5-old-material-exclusions-20261121-ac5459/README.md)，准备阶段快照见 [checkpoint](../fresh-preparation-checkpoint-20261121/README.md)。这些历史快照保留当时的 pending 和失败，不由本次进展回填。

## 后续实际比较

面板必须先单独发布，再执行 2 个父模型模式 × 3 个条件：原父模型、同一父模型加检索、完成 8 次更新的子模型。没有额外的 base-only 条件。固定 4 个任务对应最多 24 次生成，不是 24 个独立任务；两段历史训练不是两次独立随机训练重复。

这是权重冻结之后才接触的新来源评测。源提交的截止时间仍是原定 `2026-11-21T03:00:00Z`，不能把它称为训练之后才产生的真实用户任务。最多 4 个独立任务即使全部同向，也不足以建立强统计确认。旧验证环境恢复、完整环境清单、真实选择发布凭据和面板发布凭据仍须分别满足；本次预注册本身不证明泛化、真实采用、下一任务收益或 PoUW。
