# PRED：完整历史、连续目标 GRU 与独立校准入口

本轮以 #5759 的 `aeb34582ac8a6bbb6c1e79b0722daead1aadb377` 为基线。
最终实现源码为 `10629bab4d5f948854e7c59fed331213956fb974`。
本目录是独立证据后继；没有修改旧的 47 个 PRED Python 文件、历史训练源码或已使用的 confirmation 集。

**结论：工程接口与定向验证已推进，科学资格仍为 HOLD，采用仍为 NoUpdate。**
新增真实 owner 记录、真实策略比较、独立确认单元均为 0。本轮没有认证原生来源、启用生产预测或建立递归世界模型。

## 一、本轮实际修复了什么

旧 owner 快照包含完整历史，但 `freeze_owner_decision` 只把最后一行特征写入决策样本。
旧连续目标 runner 只有 empirical/MLP；模拟器中的 GRU 不能据此算作连续 owner 目标的第三个模型。

本轮采用新增模块接续原始 artifact，保留旧模型及 checkpoint 的源码身份：

| 阶段 | 交付 | 具体变化 |
| --- | --- | --- |
| 1 | [#6033](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6033) | 原 snapshot、冻结 decision、joined sample 三方绑定；恢复完整实际留存历史 |
| 2 | [#6039](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6039) | FP64 GRU 连续目标训练、真实长度分组 BPTT、完整 Adam 保存与精确恢复 |
| 3 | [#6040](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6040) | 独立离线校准、缺失分母、来源分组、混合预算契约拒绝 |
| 4 | [#6045](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6045) | 三模型共同 train/dev 入口、原生身份隔离、源码及输入保留、失败收据、新进程重放 |

四个实现阶段分别为 254、468、267、421 行，都是独立可审查的 draft。

### 完整历史与数据隔离

`history_model_row` 校验三份原件的摘要、owner identity、clock、arrival cursor、输入 cutoff、
feature schema、最后一行、ordered action panel、目标定义、预算及原始预测。
缺失 snapshot 直接拒绝，不复制最后一行来制造序列，也不回填晚到的结果。
原始 evidence 中的时间区间、删失下界、nonoccurrence witness 和成本下界继续保留。

独立审阅复现了一个具体泄漏：同一原生 attempt 换一个 decision SHA 和 task_group 后，仍可能跨 train/dev。
新入口拒绝重复 `(owner_agent_id, run_id, step_id, attempt)`；同一 `(owner_agent_id, run_id)` 的不同 step 也必须在同一 split。
这些是结构检查，不能认证 task_group 独立性、真实 owner 身份或数据来源。

### 三个预测器的精确含义

| 模型 | 输入及输出 | 边界 |
| --- | --- | --- |
| empirical | 动作条件经验频率；完整历史仍纳入数据承诺 | 不以历史内容作条件，不是因果基线 |
| 小 MLP | 同一历史的最后一行、逐列均值与实际长度；成功/时延/动作成本边缘 | 固定摘要丢失顺序；与 GRU 的差异同时包含表示方法差异 |
| GRU | 1..256 条实际历史，按真实长度分组；候选动作只进最后的 head | 不 padding 出虚构观察，不执行递归 latent rollout |

神经目标为二元成功 BCE，加 `log1p(duration)` 与 `log1p(action_cost)` 回归；
时延/成本边缘来自训练残差。训练只使用 terminal、exact duration、observed final action cost 的完整样本。
其他记录仍在输入承诺与排除分母中，不能称为已经完成 survival fitting 或缺失偏差修正。
三个边缘分布也不构成联合尾部风险模型。

当前比较还包含归一化口径和梯度处理差异：GRU 用所有实际训练历史 step 计算统计并将梯度全局范数裁至 5.0；
MLP 用每条历史的摘要向量计算统计且没有对应的梯度裁剪。相同训练样本数或 optimizer 调用数不代表参数量、
计算量或优化过程已经配平，模型差异不能单独归因于 GRU 递归核。

### 校准与实际决策收益

新模型只对同一 dev chosen action 产生离线预测；需要实际执行引用才可评分。
每项 Brier/CRPS 都输出总体 `count`、实际可评分 `eligible`、`missing` 和均值。
另有固定 10 格可靠性分箱、0.1/0.5/0.9 分位覆盖、原始 observation/time status、
unsupported action、完整成本账本缺项及 full-wall 缺失计数，并按 source/split/action 分组。

普通 duration CRPS 只接受确切完成时延。失联、取消请求、interval 和右删失不会被填成 0 或完成时间。
成本 CRPS 评价 final action cost；它与完整物理成本账本是不同对象。
混合 budget contract 在评分前拒绝，共同目标含义与单位由 manifest 固定。

原 frozen-policy score 与新 forecast 分开保存。新 forecast 不继承旧 decision timestamp，
不能产生新的真实策略比较或采用资格。所有新的科学/生产资格仍为 false。

## 二、验证与可复现证据

最终冻结源码的本地 PRED suite：**182 项通过，0 跳过**，测试时间 18.203 秒，外层 wall 18.726 秒。
测试前后 55 个 Python 文件 SHA-256 完全一致。原始日志见 `local-tests.log`；身份见 `SOURCE_SHA256.json`。
23 项新增测试覆盖全参数有限差分、变长梯度、精确 Adam 恢复、缺历史/未知动作拒绝、
重新计算摘要后的损坏 checkpoint、缺失/删失、跨 split 原生身份、源码漂移、部分失败收据与隔离新进程重放。

三平台 hosted PRED 工作流必须按各阶段精确 head 判断，原始日志及摘要随证据归档。
前三个阶段的三平台 PRED 工作流均成功；摘要见 `HOSTED_STAGES.json`，原始日志见 `hosted-stages.tar.xz`。
macOS/Windows 的 `Ran N` 包含 6 项 `Linux research execution wrapper` 跳过，不能表述为 N 项实际执行通过。
最终源码对应 [Actions run 43127994207](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43127994207)。
截至 2026-11-12 00:40:34 UTC，Windows/macOS 均成功：182 项中实际执行通过 176 项、跳过 6 项；Ubuntu 仍排队，没有推断测试结论。详见 `HOSTED_CI.json` 的原始回读与日志摘要。
这不表示整个仓库所有 CI 都通过。

当前环境缺少 `just`；`just fmt` 返回 command not found，离线 Ruff 也不在缓存中。
本轮没有修改 Rust；没有把未执行的格式或全仓检查记成通过。

### 留存工程运行

在最终源码上保留一次明确的 **12 train / 6 dev fixture** 工程运行，实际历史长度为 1、2、3 行。
三个 checkpoint 均保存、载入并重放预测；MLP 和 GRU 各 8 次 optimizer 调用、96 次 sample presentations。
经验模型没有 optimizer 调用。这些数值不是实际 owner 训练或独立任务收益。

`engineering-fixture.tar.xz` 为 81,776 bytes，215 个常规文件全部独立读回并验证 SHA-256。
包含原始 fixture 输入、三模型 checkpoint、原策略分数、逐条离线预测、校准报告、源码、收据与日志。
完整成员清单及 archive SHA-256 见 `ARCHIVE.json`。

一次前置源码 HEAD 检查曾在本地分支对齐仍未完成时失败；它在模型执行之前结束，0 次 fit。
该失败及其原先生成的 fixture 输入保留，随后使用相同输入和已核实源码执行。
`PREFLIGHT_FAILURE.json` 与 `ENGINEERING_EXECUTION.json` 不把这次失败改写为成功，也不补造未保留的实际 HEAD 值。
executor 中断造成的早期测试 UNKNOWN 与后续完整验证也分别记录。

## 三、仍未闭合的真实数据入口

本轮实际调用 `h.host_list` 和 `h.effective_config` 均返回 `MCP -32603: MCP request timed out`。
尚未取得当前 owner 数据库、真实 host clock/arrival sequencer 和独立业务 effect observer。
这不证明所有机器离线或数据库不存在；详见 `OWNER_SOURCE_OBSERVATION.json`。

历史 pocket4 请求 `pred-owner-audit-9e3156-service-source-pocket4-01` 原件仍是没有 session ID 的 UNKNOWN。
本轮核对了其原身份，没有用新幂等键重放，也没有宣称完成 live reconciliation。

已有 `owner_capture.next_after` 是回顾性主键分页，不是实时变更 cursor。
找到数据库之后仍需核实真实单一到达序列、重启/boot 身份、独立终态观察及成本来源。
owner succeeded/failed 只结算 owner 契约，不能直接生成业务成功标签。

## 四、下一次真实验收的入口与判据

命令：

```sh
PYTHONPATH=scripts python -m hepta_pred1.observed_history_run \
  --manifest /absolute/path/HISTORY_MANIFEST.json \
  --output /absolute/path/new-study-directory
```

manifest schema 为 `pred1-observed-history-study-v1`。沿用原 study 的 feature_names、action_ids、
success_definition、utility_contract、seed、hidden_size、epochs、learning_rate 和 train/dev 字段；
每个 train/dev entry 都有 `sample`、`decision`、`snapshot` 三个 `{path, sha256}` 引用。
action_ids 必须保持冻结决策的原始 panel 顺序。新入口不接受 confirm 字段。

输出的 `REPLAY_INPUT.json` 只引用已保留的输入。新进程可从保留源码重放：

```sh
PYTHONPATH=/absolute/path/prior-study/source python -m hepta_pred1.observed_history_run \
  --manifest /absolute/path/prior-study/REPLAY_INPUT.json \
  --output /absolute/path/new-replay-directory
```

接续顺序是：核实真实 owner/时钟/到达序列/独立 observer；记录完整缺失与失败分母；
在新的任务组上评估预测与校准；另行冻结新策略、完整预算、随机化机制和终点，执行前瞻实际策略试验。
已使用的历史 confirmation 集保持封存。未执行动作没有事实标签，模型外推不能代替支持条件或随机化。
只有小预测器建立可重复的真实净收益后，才有依据扩大内核或增加递归规划。

## 五、研究对照

- [DreamerV3 / Nature 2025](https://pmc.ncbi.nlm.nih.gov/articles/PMC12003158/)：world model 预测后续潜在表示，actor/critic 从想象轨迹学习；本轮 GRU 历史编码不具备该资格。
- [Rindt et al., AISTATS 2022](https://proceedings.mlr.press/v151/rindt22a.html)：删失监督及其条件必须单独建立，不能把 receipt missing 当作已证实存活至 cutoff。
- [Kvamme & Borgan, JMLR 2023](https://jmlr.org/papers/v24/19-1030.html)：行政删失下评分存在专门的假设与偏差问题；本轮没有声称修正这种偏差。
- [Khan et al., ICML 2024](https://proceedings.mlr.press/v235/khan24b.html)：无 overlap 的策略评估需要额外假设并常得到部分识别界；chosen-action 预测不自动识别反事实价值。
