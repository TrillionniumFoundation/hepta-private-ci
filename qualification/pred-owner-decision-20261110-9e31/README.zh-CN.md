# PRED：真实 owner 到预测、决策与效果评估的连接阶段

## 结论

本轮交付的是可以执行并重放的研究连接层。工程验证完成；真实 owner 采集、实际新策略对照和新增独立确认仍为 0，科学资格保持 **HOLD / NoUpdate**，没有生产采用。

受测源码为 `74d3fddbc6e6cf28184848558422a81711460dc8`，接续原证据 `a3aa398580cbd052f9decbc08af36deea25c6155`。没有从旧 `main` 重建另一套，也没有修改原注册冻结的九个训练源。旧189-fit新执行004及其模拟结论保留；本轮不重开两组已用确认集，不宣称找到旧缺失原件。

## 已实现并发布的五个阶段

| 阶段 | 交付 | PR |
| --- | --- | --- |
| 既有 owner 采集 | 有界身份发现、分页、只读 WAL 采集、不可覆盖的原件和清单 | [#5721](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5721) |
| 实际动作评价 | 连续真值评分、校准、完整成本与预算、实际配对采用门槛 | [#5737](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5737) |
| 轻量预测基线 | 仅训练组的动作条件经验分布、FP64 MLP、Adam 与 checkpoint | [#5738](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5738) |
| 决策与效果连接 | 真实模型加载/候选打分/冻结、独立效果读回、Fixed1 和信息价值函数 | [#5740](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5740) |
| 完整开发入口 | SHA 固定样本、训练/开发隔离、离线校准、成功/失败终态及成本记录 | [#5741](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5741) |

这些是逐层可审查的研究分支；尚未合并默认分支。完整发布身份见 [PUBLICATION.json](PUBLICATION.json)。

## 从原始记录到训练的准确语义

`owner_capture.py` 在已经存在的 TaskFlow 数据库发现身份，并复用原 `collect_native`。每条身份仍完整绑定 owner、run、step、attempt、intent、payload、binding、destination。原 owner 三张表分别保留，不把 `succeeded/failed` 当业务质量。

事后目录采集不产生决策前快照、效果标签或确认单位。分页发现与逐条采集是不同事务，不是全局原子快照，也不是完整增量日志。新输出目录必须不存在；错误和部分产物不会被自动覆盖重跑。

`freeze_owner_decision` 只接受当前身份尚未出现 dispatch attempt 的快照。它固定输入截止、真实预测完成与决策时刻、模型摘要、候选顺序、实际选择、任务分组和目标定义。信息摘要来自完整冻结数值历史、特征顺序、有序合法候选、预算与目标语义，不能直接填一个相同字符串冒充同输入。精确比较包含时间特征，是有意保守的；它仍不证明外部任务环境相同。

`predict_owner_choice` 实际读取并验证 checkpoint，运行一次候选面板，调用 Fixed1 并冻结选择。模型只消费声明的最后一个观察行及动作编码；原更复杂 GRU/SSM 实现保留。本阶段不增加 latent rollout。

随后由原 owner 执行动作。`join_owner_effect` 要求独立效果 artifact，匹配完整身份、旧决策/快照摘要、目标定义摘要、时钟、所选/所执行动作及执行时刻；原 owner settlement 不能替代该效果 artifact。终局质量当前明确限定为任务定义下的二元 0/1，时间为真实连续秒，动作成本采用明确的同一单位。

缺回执和取消请求保持未知。只有实际有执行起点和非发生见证的持续事件才保留右截尾。右截尾、区间时间或缺成本不变成零标签；训练入口保留其排除计数与原件。摘要和 observer/execution 引用是结构及完整性检查，本阶段没有认证外部 owner、观察者、随机分配或独立信任域。

## 模型、准备策略与评估

经验基线按实际动作保留训练样本的质量均值、时长和成本经验边缘分布。MLP 使用 FP64、tanh、二元 BCE 和 `log1p` 时长/成本回归；连续预测边缘来自训练组按动作保存的经验残差。不存在对旧 `{1,2,4,8}` 模拟支持集的偷偷取整。这些是观察关联和完整案例基线，不是已识别的反事实模型、联合成功/截止概率或缺失机制修正模型。

训练仅接受 `train`，重复样本或混入开发/确认行被拒绝。checkpoint 保存特征、动作、成功定义、单位、数据/分组摘要、源 SHA256、NumPy 版本、参数、完整 Adam、残差和 loss 历史。恢复还检查学习率范围及实际 optimizer/sample-presentation 账本。继续训练要求同一训练数据身份；未训练过的动作明确不可用。

Fixed1 只使用一次已经算出的面板。简单信息价值函数需要来自 train/dev、在决策前可用的条件场景，校验全期望一致性，扣除额外准备时间/成本，并拒绝不可能的质量效用上界与非有限结果。没有场景模型时停止准备。该函数目前验证声明场景的数学关系；尚未接上真实的新观察分布或证明准备的实际价值。

评价分为两个明确入口：

- `score_forecast` 只做明确标记的离线校准：质量 Brier、真实连续时长/成本 CRPS，以及0.1/0.5/0.9分位覆盖。
- `score_observed/evaluate_observed` 只评分原已冻结策略实际选择且实际执行的动作，保留 unknown/cancel/censor、完整成本及来源/分割/策略分组。未执行动作的事实收益保持空值。

`observed_run` 的新模型开发集预测存入独立 `offline-holdout` artifact，`prediction_deployed=false`。它没有将训练后的新预测时间倒填到旧决策，也不据此计算新策略实际净收益。开发集未覆盖动作保留在总样本数中，单列 `unsupported_action`，不使用池化伪替代。

## 完整预算与采用门槛

任务效用采用预先声明的标量定义：

`outcome − time_weight × full_wall_seconds − cost_weight × full_cost`

`full_wall_seconds` 是任务开始至效果 receipt 到达的完整墙钟时间，必须覆盖已知的决策后排队、调度、执行和等待。若有实际推理计量，还必须覆盖推理开始至 receipt 到达；不能只提交短暂的 effect duration。完整成本逐项包含 action、preparation、inference、training、validation、failures、recovery、transport，单位统一、不重叠，学习与验证的摊销规则必须在真实试验前固定。

任一成本项未知就保持未知，即使其效用权重为零。预算契约同时固定时间上限与总成本上限；仅有相同权重不足以通过。超支样本仍保留实际结果和成本，不能从分母删除。

配对 gate 要求新预注册、实际随机配对的独立任务副本、相同输入/预算、完整双臂覆盖、全体完整实际效用。它最多处理预先固定的16个独立配对组，用精确 sign-flip；没有实际组、缺成本、超支、跨时钟、重复 receipt 或复用已用组都返回 `NoUpdate`。实用净收益下限保持 `+0.02`，单侧 `p≤0.05`。不能解释为成功率增加两个百分点。

仅预测 loss 或校准变好、实际净收益更差时保留父版本。即便数值 gate 通过，输出也只是基于已声明来源/试验设计的 `CandidateEligible`，`production_activation` 始终为 false；外部真实性不能由数值门槛认证。

## 验证与可复现原件

本地 Python 3.12.14 / NumPy 2.3.5：**159/159通过**，其中新增41项风险与集成测试。受测过程中源码未改变。全部47个本地 PRED Python 源/测试文件与发布后的 Git tree 逐 blob 匹配；九个历史注册训练源 SHA256 完全未变。

同一源码 `74d3fdd...` 的 [PRED CPU Actions 42823757799](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42823757799) 已读回原始日志：

| 系统 | 结果 | unittest 报告时间 |
| --- | --- | --- |
| Ubuntu | 159/159 | 7.988秒 |
| Windows | 159/159 | 23.054秒 |
| macOS | 159/159 | 3.823秒 |

这些是正确性测试用时，不能作为跨系统性能比较。其它工作流状态单独见 CI 记录；没有把专用 PRED CI 成功等同于整个仓库所有 CI 通过。

保留的一次端到端工程 fixture 有12条训练、6条开发记录，两个预测模型，其中 MLP 为16次 Adam更新、192次样本呈现。所有 owner、任务、效果都是明确的合成 fixture；实际新增 owner 和独立确认为0，采用结果 `NoUpdate`。

- [TESTS.json](TESTS.json)、[python-tests.log](python-tests.log)：本地完整原日志及外层成本。
- [CI_READBACK.json](CI_READBACK.json)：精确源码对应的三系统 job、步骤和日志摘要。
- [SOURCE_SHA256.json](SOURCE_SHA256.json)、[REMOTE_SOURCE_READBACK.json](REMOTE_SOURCE_READBACK.json)：源码身份及远端逐文件验证。
- [FIXTURE_RUN.json](FIXTURE_RUN.json)：仅工程 fixture 的执行摘要。
- [ARCHIVE.json](ARCHIVE.json)、[engineering-fixture-001.tar.xz](engineering-fixture-001.tar.xz)：121个已逐项重新读取并校验SHA256的成员，包含全部fixture输入、冻结决策、输出、checkpoint和准确Python源；档案121,996字节。
- [FORMAT_STATUS.json](FORMAT_STATUS.json)：本环境缺少 `just`，该格式入口未运行成功；本轮没有修改Rust源码。

解包后的源根为 `source/`。在已具备 Python3.12 / NumPy2.3.5 的环境，可以对保留的fixture重跑一个新目录：

```sh
PYTHONPATH=source python -m hepta_pred1.observed_run \
  --manifest fixture/inputs/MANIFEST.json --output another-fixture-run
```

时间计量、完整文件SHA会随新运行而变化；参数、Adam计数和预测重放在同源同运行时内验证。不把新fixture执行计为真实确认。

## 当前真实 owner 阻塞

实际路径几何来自生产源码：`<fleet-root>/agents/<agent>/automation/automation_1.sqlite3`，fleet-root可由`HEPTA_FLEET_ROOT`指定。

本轮 mac/desktop 的精确默认 agents 路径返回不存在；这只说明那两个默认路径，不能排除其它配置根。ai395、pocket4、x230 的认证 SSH 健康检查成功，但对五台主机的 scoped fleet 查询均遭 Runtime MCP `-32603` 请求超时，没有返回可跟踪的 job ID。同键 reconciliation 没有恢复出ID；最后一次任务目录观察仍是 `validation_pending=true/inventory_complete=false`，不能用空列表证明任务不存在。

随后通过可用的PTY通道，对ai395、pocket4、x230完成了有界只读探测，均已实际读回退出码0及完整输出：此次operator进程环境的默认fleet根不存在、`HEPTA_FLEET_ROOT`未设、对应数据库数为0。这只覆盖精确默认根和此次进程环境，不排除长期服务使用其它override。pocket4的同UID进程名称中可见hepta工具进程，但名称本身不证明TaskFlow owner。

精简、去除私有home路径的观察记录在 [OWNER_SOURCE_PROBE.json](OWNER_SOURCE_PROBE.json)。因此最终阻塞是尚未定位真实owner来源及独立效果observer，不能说全部执行通道不可用。早先durable-job查询的底层结局仍未知；没有以新key重放业务动作，也没有写入owner数据库。成功PTY探测均已读回退出，没有新增业务后台任务。

### 已识别服务覆盖路径的追加检查

在原证据提交后，另向 pocket4 提交一次25秒有界的只读探测，仅限先前已识别的两个同UID Hepta进程，提取明确的 `HEPTA_FLEET_ROOT`、对应unit配置和 `automation_1.sqlite3` 文件描述符路径。此次 `h_pty_start` 返回 `-32603: Internal error`，没有session ID或输出读回，底层终态为 `UNKNOWN`。这次请求不算完成的来源检查，不增加owner记录，也不能推断配置覆盖路径不存在；没有重试或业务动作重放。

[追加失败回执](SERVICE_SOURCE_ATTEMPT.json)保留原始错误、准确范围和调用观测窗口；[原样探测源码](SERVICE_SOURCE_PROBE.py.txt)的SHA256为 `b7d55a1998a5126a203c193ffc0c40b6def280c8f7d1cb0275e7c1eea8593022`。它是未取得执行读回的探测请求源码，不是已验证的生产采集器；PRED受测源码与采用结论均未改变。

## 下一次真实运行的准入顺序

1. 在已存在的owner服务配置/运行身份中定位真实数据库、时钟域和序列游标，验证独立效果observer；用新采集入口保存原始记录。PTY可用于后续只读核对，durable-job回执通道另行修复。
2. 将前决策snapshot和`predict_owner_choice`接到该owner的实际入口，选定独立效果observer，绑定二元质量定义、秒和资源单位。
3. 收集新的训练/开发任务，完整保留失败、取消、截尾、推理/训练/验证/恢复成本；本轮两个模型只作为预定基线，不复用旧确认集调参。
4. 在打开新的确认任务前固定真正的任务/来源组、随机配对、动作集合、预算上限与学习成本摊销。当前文档是工程协议说明，不冒充已完成的真实预注册。
5. 通过完整成本下实际净收益门槛后才讨论采用及更长rollout。在此之前保留父版本。
