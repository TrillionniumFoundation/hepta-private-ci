# CTRL/NDU：本轮实现、证据与晋级结论

**结论：新身份链的原生 fixture 集成已通过；复杂控制仍为 HOLD / no-update。**
本轮完成身份链、历史审计入口、动作落实／局部效果头、STOP 相对净收益头、
严格检查点，以及冻结强对照后读取 future 的研究入口。没有建立真实策略收益。

## 可审查的提交栈

| PR | 范围 |
| --- | --- |
| [#5472](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5472) | 候选选择、原始 wire、交付与 evaluator 身份绑定 |
| [#5488](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5488) | 完整原生 fixture、强制隔离与专用 CI |
| [#5489](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5489) | 落实／效果概率与控制净收益头 |
| [#5490](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5490) | 冻结检查点、成本资格与数值边界 |
| [#5491](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5491) | 原始历史文件的只读审计入口 |
| [#5492](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5492) | 同状态、已观测动作的冻结策略回放 |
| [#5493](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5493) | 完整研究测试与精确旧版 fixture 证据包 |

均为 draft，按前一分支叠加，每个 PR 的增删文本行数不超过 800。
本报告所在的最后一层只保存资格结论与原始 CI 证据，不改变策略。

## 真实完成的验证

| 验证 | 观察结果 | 能说明什么 |
| --- | --- | --- |
| 首轮回归 | 87 项通过 | 含既有 Torch 恢复、STOP、成本计量和首版新增模块 |
| 最后实质修改后的机制＋研究入口 | 21/21 通过：14＋7 | 新校准／检查点契约、冷恢复、future 冻结和缺失数据处理 |
| 历史审计入口 | 6/6 通过 | 原始证据一致性、未知标签、重复来源及输出不覆盖输入 |
| 本地完整原生执行 | 0 executed / 1 setup error | 本地内核的 Landlock 不可用，保留原失败记录 |
| Ubuntu 原生 CI | 3/3 通过，零跳过，4.494 秒 | 实际 OCR／actor／host／delivery／scorer 身份链集成 |

以上测试批次有重叠，不相加为独立实验样本。`just fmt` 已完成；没有为格式变化重复测试。

原生 CI [run 42613427363](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42613427363)
使用非 root UID 1001、Landlock ABI 8、Python 3.11.18、Torch 2.5.1+cpu。
source head 为 `b8535a67bead9545e16448f77559fcb1c6f6f8ed`；实际测试的是合成
merge `28e3cb68bb19afc7b9ae783e1723ea9a46f5e62c`，两者 tree 相同。
原 ZIP 已回收并核对 GitHub digest；见 `NATIVE_CI_STATUS.json` 和 `NATIVE_CI_EVIDENCE.zip`。
没有绕过隔离或跳过 Linux。完整测试断言已通过，原始 episode 临时文件没有保留在 CI artifact 中。

通用 CI 不能标为全绿：#5472 的 `cargo-deny` 失败，而 base 上最近观察为通过；
失败日志多次返回 Transport closed，具体根因未取得。见 `GENERAL_CI_STATUS.json`。
没有重跑、取消检查或修改依赖来掩盖结果。

## 实现的关键边界

`selected_used` 表示选定对象被实际使用；`effect_occurred` 表示另行定义的局部效果发生。
二者都不等于终局语义正确。缺证据为 null，不作负例；只有单类标签时明确报告平滑基率。
价值目标是观测 continuation 质量减对应 STOP 质量再减增量成本，不再次乘落实概率。

公开状态保留 context belief、pending evidence、freshness、合法动作和预算。
非 STOP 动作需要成本上界及终止预算；真实 dispatch 前仍须由 owner 再检查。
数值异常会拒绝预测／回退，不把无穷大当收益；校准必须先于 future 诊断。
训练与校准分别保留来源、成本资格，研究候选始终不自动获得原生 admission。

研究对照包括 STOP、训练得到的廉价上下文表、校准选择的固定动作、同一个充分求解的
线性点 critic、无条件残差和有限公开分组的条件残差。线性拟合充分不等于已比较所有模型类。
只有完整同状态动作表才产生观测回放收益；缺动作、未知成本或不支持预测保留未知分母。
来源等权，区间为描述性 bootstrap；不声称条件覆盖定理或前瞻策略效果。

规划时间逐策略计费一次。训练、调参、能耗、provider 费用尚未核清，整体完整成本仍为 false。
当前只接受 runtime 已有合法动作，没有伪造 VERIFY／REPAIR 的执行或训练证据。
READ/PREPARE 后立即 STOP 不能改变已有交付；READ 加回答后缀必须另立明确且完整计费的宏实验。
有用、重复、噪声 READ 已做 fixture 语义检查，尚未做真实任务上的信息价值比较。

## 历史问题仍未关闭

#5450 固定为 `f6a7d5307f888d30faa8803d23487c78789b99fe`，原有 60/60 episode
与预测诊断结果继续只按原证据解释。V2 聚合记录缺少完整选择／交付身份链；本轮未取回
六次零分 WRITE_TEXT 的原始 trajectory、launch、delivery、evaluation，**根因仍未建立**。
新 fixture 通过不能回填旧实验的缺失字段，也不能据此判定是选择器或评分器出错。

#5451 固定为 `de9cf9d3eba7ac48706e030ed323ac72da10c1a3`，本轮没有修改该分支。
其 dynamic 0.398750 仍低于 light 0.471250，差为 -0.0725；3 次训练初始化共享
48 个 future 来源，不是 144 个独立任务。原生 dynamic 的 static-quota 回退未移除。

## 资源与证据续接

HeptaRuntime 已完成只读资源探测尝试。CPU evaluate 和同 key reconciliation 超时，
provider 账号就绪状态是 UNKNOWN；没有申请云资源或提交训练。原始轨迹检索超时，
direct SSH 明确返回 admitted capacity exhausted。见 `RESOURCE_STATUS.json` 中的原 key/job。
没有新 key 重复提交未知作业、轮换账号、抢占资源或改锁。

`STUDY_FIXTURE_EVIDENCE.tar.gz` 保留一次实际 CLI smoke 的全部 18 个文件和对应源码。
它早于最后的数值／校准加固及混合成本 guard，仅作该版本的 fixture 证据。
十个 fixture 来源 ID 不是十个真实独立任务；最终代码由上面的 21 项联合测试验证。
两篇研究的主张及工程推断边界见 `RESEARCH_SCOPE.json`。

## 晋级还需要的实际证据

1. 恢复原始文件，以固定 evaluator／rubric／normalizer 跑历史审计，定位第一处不一致与未知链节。
2. 从独立真实来源收集 STOP 与 continuation 的同状态对照及可验证落实／效果标签。
3. 冻结模型和强轻量基线后，执行真实原生 future 策略比较；明确 READ＋回答宏的所有调用。
4. 纳入规划、执行、训练／调参摊销和适用的能耗／provider 成本，再判断是否稳定超过强轻量基线。

在这些证据完成前，复杂控制保留为研究候选，部署 **no-update**。
