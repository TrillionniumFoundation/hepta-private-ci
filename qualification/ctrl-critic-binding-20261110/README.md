# CTRL 2026-11-10：覆盖诊断、critic 绑定与原生终局

**本轮新增的真实结果是：原 fit40 的 74 个候选缺口全部落在日期和金额。**
另已关闭原 V3 的终局不确定性，并完成两条 critic 路径的依赖绑定。
V4 只派发了一次，但原生接口错误使其仍为 UNKNOWN；新日期／金额诊断
已经冻结、测试并推送，尚未提交原生执行。复杂控制继续 **HOLD_NO_GO / no-update**。

## 真实覆盖结果

[原始脱敏结果](FIT40_COVERAGE_RESULT.json)及[执行收据](FIT40_COVERAGE_EXECUTION.json)
来自一次已确认 durable terminal、exit 0 的原生只读诊断。
输入是原来同一份 9,496,351 字节训练文件；全部 60 个原源码文件在分析前后核验。
共 200 行、160 唯一状态、40 原训练来源，40 行为重复状态记录。

| 字段 | 实际观察来源 | 唯一状态 | 有正确候选 | 无正确候选 |
| --- | ---: | ---: | ---: | ---: |
| date | 17 | 68 | 34 | 34 |
| total | 23 | 92 | 52 | 40 |
| company | 0 | 0 | 0 | 0 |
| address | 0 | 0 | 0 | 0 |
| 合计 | 40 | 160 | 86 | 74 |

每个来源有四个状态，不代表每个来源观察了四个字段。整体候选上限为
86/160 = **0.5375**；字段各自的完整 40 来源均值仍为 null，不能丢掉未观察来源。
历史 selection 和 pre-cap 记录缺失，所以 selected accuracy、selection gap 和
截断判断仍未知。这个重放不重新测量 answer-head 准确率。
完整解释、成本范围和精确 pins 见 [DATA_FINDINGS.md](DATA_FINDINGS.md)。

公司名／地址三行扩展已独立实现，但不能被当作这 74 个 date/total 缺口的修复。
新的保留文本诊断先固定不接收标签的提案规则，再做离线评分分类：

- A：冻结 DATE/MONEY 正则的保留匹配。
- B：固定数字格式规则的保留匹配。
- C：同来源、同字段的另一个已记录状态中存在原始候选匹配。
- D：当前保留文本与固定探测仍证据不足。

C 不代表 READ 因果收益或可达性；D 不代表原图或新观察无法给出答案。
64 个新增提案、128 个总候选与 4096 次匹配扫描上限均明确计数。
[GAP_NATIVE_STATUS.json](GAP_NATIVE_STATUS.json)记录 NOT_SUBMITTED，真实 A/B/C/D 数量为 null。
没有用其他本地训练文件替代固定输入，也没有在看过真实分类结果后调规则。

## Critic 与动作语义

新 `CriticContext` 绑定 encoder、answer、generator、public state、action、settlement、
utility、tariff、evaluator 九个依赖。训练、校准、决策、检查点与冷加载都检查身份；
相同数值特征不再足以复用旧 critic。Native 缺失／漂移时选择合法 STOP 并要求重新拟合、
独立来源校准；shadow 路径也清除旧预测与残差。旧 v1 证据不能补几个 hash 就变成新 v2 证据。

STOP 相对价值仍是 continuation 终局质量减对应 STOP 质量，再减增量成本；
本轮没有用新的真实数据证明 critic 或策略收益。具体迁移与动作表见 [NATIVE.md](NATIVE.md)。
VERIFY 仍是独立终局 scorer；修复通过已有写入动作表达，没有虚构新增执行 primitive。

原生宏明确共享冻结的交付后缀：STOP 宏为 `WRITE_TEXT -> STOP`，READ 宏为
`PREPARE_ROI -> READ_ROI -> WRITE_TEXT -> STOP`。它们的净收益不能改名为
primitive `[action, STOP]` 的价值，全部宏动作和后缀都必须结算。

## 原生 V3 与 V4

原 V3 的权威终局是 failed / exit 1；完整 stderr 指向默认 reset 字段的解析检查。
根据冻结源码和 traceback，它未进入 episode loop。旧 UNKNOWN 历史文件没有改写；
见[追加对账](../ctrl-metacontrol-20261109/native-macros/V3_DISPATCH_RECONCILIATION_20261110.json)。

V4 保留原一条训练来源、original/repeat/noise 三对、六个计划 episode、模型及预算。
六个 stage 文件完成 create-only 写入和精确读回；执行前隔离新源码树、拒绝旧 bytecode，
并在前后核验固定输入。它执行的是原 60 个冻结模块加两个官方宏模块，
不是本轮新 critic 或候选模块的真实策略验证。

V4 业务派发只提交一次。接口未返回业务 job ID，随后任务登记、文件、主机清单等只读查询
也返回 `MCP -32603 Internal error`。目录准备作业成功不能当作业务作业成功。
当前未确认六分支、结果文件是否存在或原生终局；
[V4 状态](../ctrl-metacontrol-20261109/native-macros/V4_DISPATCH_STATUS_20261110.json)
保持 UNKNOWN，不能记为零收益、失败样本或三对已完成。没有重放或换 key 派发。

## 已推送的审查阶段

| PR | 具体范围 |
| --- | --- |
| [#5722](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5722) | 独立 shadow 栈的 critic 依赖绑定、35 项本地契约测试 |
| [#5749](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5749) | Native critic v2 身份、校准、冷加载与 STOP 回退 |
| [#5750](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5750) | 来源等权覆盖与缺失分母 |
| [#5751](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5751) | 独立三行候选扩展，无默认 actor 集成 |
| [#5752](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5752) | 冻结 fit40 的只读适配 |
| [#5757](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5757) | 精确 source head CI 与原始本地验证日志 |
| [#5758](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5758) | 真实覆盖结果、字段解释及 V3 追加终局 |
| [#5767](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5767) | 日期／金额固定诊断，8 项新增测试，CI 最低 63 项 |

各阶段都是 draft，未合并、未改生产默认。Native 可执行阶段各少于 800 增删行；
真实原始结果的证据阶段单独保留机器生成全文。Shadow 与 native 是不同基线栈，
不能把两套测试合称一次全仓通过。

## 验证与仍需取得的证据

Native 原联合运行是 55 项；新增 gap suite 是另一次 8 项运行，均无失败、错误或跳过。
测试后执行 `just fmt`，新五份相关源 AST 相同、原 16 份已发布源字节相同；
没有为格式变化重跑本地测试。63 是更新后 CI 的独立最低测试数，不能代替其实际结果。
参见 [NATIVE_LOCAL_VALIDATION.json](NATIVE_LOCAL_VALIDATION.json)与
[GAP_LOCAL_VALIDATION.json](GAP_LOCAL_VALIDATION.json)。Synthetic CLI 与 V4 准备测试
均不新增独立真实任务。原生覆盖诊断的 Python 3.12.16 与本地测试的 3.12.14 分别留有记录。

固定预算、greedy、bandit/actor-critic、适用小域 DP/MPC 与 NDU 的完整原生横评仍未完成。
现有 [Controller](../../scripts/ndu_real_runtime/controllers.py) 有 initial、tuned_fixed、
voi、light、mpc、ndu、ndu_policy 等入口；不能把这些名称直接当成所有算法类已做充分对照。
后续比较须冻结共享候选生成器、固定动作图、终局约定及来源划分；轻量参考保留，
不能因 NLL、更深推演或内部一致性单独晋级 NDU。

恢复执行后的顺序是：先对账唯一 V4 原请求；取得两个 postcheck、三对完整结果及六条轨迹；
再验证源码并执行已冻结的 date/total 诊断。根据真实分类选择提取或信息获取改动，
重新拟合、校准其依赖 critic，然后才冻结未见来源的策略比较。
实际净收益、风险与完整资源账本仍缺：规划、执行、训练／调参摊销以及适用的 provider、
能耗成本不能省略或按零处理。37 个预留 future 来源仍封存，没有生产采用结论。
