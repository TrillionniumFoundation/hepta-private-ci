# Cell / RSI 统一候选与真实恢复接线

这份集成组合保留来源提交及各自证据身份，供同一源码版本的原生测试和 CI 验证。它不把来源分支的通过结果自动归给组合版本，也不将状态恢复机制检查记为真实学习采用或收益实验。

## 不可变来源

| 来源 | 原提交 | 原 tree |
| --- | --- | --- |
| Cell 后继与 joint-config v1 | `6ddfca2406e4d01416cd2f7ab1655a0dc16f8da5` | `491eace326f335498334fb051c9e8f298ca7a04c` |
| NDU v4 持续状态、训练目标与原生生成 | `9c6c18cec8c56260d633de5a6adf321de2a4e3d4` | `023c017618563a08fe5043551e26f89efd313fa6` |
| 五个基线 Python 文件格式修复 | `b4af5773b4984d735af32ae95643cdcd3b00b58f` | `d16b595295f3374279d8ed9c7e5b529e22cd1831` |

来源以真实 merge parents 保留。后续提交分别承载配置绑定、actor 恢复和 CI 接线；精确最终 HEAD、tree、命令、原始日志和新 JUnit 由执行回执及 CI 工件给出。旧训练 receipt 和旧源码摘要不重写。

## 新增的可执行合同

`scripts/hepta_cell_joint_config.py` 的 v2 将原八类输入扩充为十四类：除运行时、两份模型、trainer、数据、evaluator、预算和采用规则外，分别绑定候选与 incumbent 的 state schema、encoder 和 backend。迁移时还必须有迁移工件。内容摘要覆盖源码、角色字节、兼容声明和必需 CI 集合，跨主机路径变化不改变身份。

消费者检查要求外部指定下一 task 和模型角色。NoUpdate 使用 incumbent 的完整组件；模型权重改变不能直接 carry。声明迁移并不等于已执行迁移；模型实际执行、消费者真实性、owner 授权和采用状态仍需各自的原始证明。详见 [README.md](README.md)。

`scripts/ndu_real_runtime/state_codec.py` 为研究 actor 增加受输入摘要约束的 checkpoint 与冷进程恢复。绑定包含模型和参数、case、控制与部署 profile、相关源码、运行时及 OCR 工件；快照保留四类核心状态、随机数、公开观察和交付状态。恢复必须提供 checkpoint 摘要和下一输入摘要，并拒绝错 case、错 operation、错 step、错交付、预算回填、终止态及异常状态张量。

状态恢复消费的是 host 提供的下一输入。checkpoint 记录 actor proposal，不证明 proposal 已由 host 提交；真实 journal ACK、单调时间预算、冷加载全成本、撤回和 FinalUse 仍由 host owner 执行。它不是跨模型状态迁移器，也不允许把旧 reset 训练权重称为 persistent 训练权重。

## b040 之后的训练结果接缝

独立分支 `engineering/training-result-bridge-858e` 以 `b040333617ed493944ae028bfb502c94d3b10991` 为唯一父版本，在已有 `pipeline.run_training_job` 接入实际参数、训练源码、数据、控制、memory 模式及训练记录/回执 schema、预训练 lineage、started/receipt、部署 profile、权重摘要和原始 meter 的交叉核验。索引中的 job 身份必须与真正执行的参数一致；同权重摘要不能掩盖不同的控制或部署 profile。该接缝不重新反序列化权重；完整张量状态结构仍需由真实 runtime 与已有 state codec 核验。

现有 660 秒 supervisor 上限保持，超过 600 秒的 child fit 配置在启动前拒绝。准入和结果校验的时间进入实际外层观测；60 秒开销保留量不代表已经证明完整实验预算等价。只读恢复必须提供原 admission 摘要；缺少原外层终态、旧 v1 admission、保留错误或未知结果均不能凭可读权重升级为生产完成。

准入成功只返回 `VALIDATED_UNAUTHENTICATED`，`native_owner_authentication` 仍为 `SEPARATE_REQUIRED`，没有产生签名阶段证据、采用决定或新任务消费。此后续只运行显式合成协议控制和独立的只读 CLI；没有启动真实训练、云 provider 或新科学 episode，没有将合成历史 admission 当作旧 pilot 原件。实际 native job 映射、独立评价与 owner 签名接线仍待实现。新的 7 项协议测试已接入该分支的 CI；新 HEAD 的 CI 结论必须由其自己的实际运行给出。

## 旧 b040 原生测试的证据口径

`b040333617ed493944ae028bfb502c94d3b10991` 的原 scoped nextest 执行了 374 项，全部在首轮通过；对应 JUnit 的 skipped 节点为 0。原 nextest 同时另报 736 项 skipped/filtered。该命令使用 `--lib` 和 `-E` 选择范围，因此不是完整 workspace 测试，“JUnit skipped 为 0”也不表示没有过滤项目。这是对旧 b040 证据口径的明确说明；这些旧运行不作为本后续新 HEAD 的验证结果。

## 六级验收状态

| 门槛 | 本组合增加的具体能力 | 仍需取得的验收证据 |
| --- | --- | --- |
| P0 统一候选 | 来源合并；模型、schema、encoder、backend 和实验输入的完整绑定；新组合的测试/CI 入口 | 同一最终 HEAD 的全部必需 CI；真实训练与评价材料的完整联合冻结 |
| P0 真实后继 | 显式下一 task 的完整组件检查；真实 actor checkpoint/恢复；保留原生后继机制 | 生产 learning ports、可信入口与真实 Cell worker；真实任务到训练、独立评价、采用或 NoUpdate、下一任务、恢复的原 owner 链 |
| P1 因果收益 | 保留 NDU v4 的状态、训练目标、全成本和对照入口 | Cell、NDU、持续状态与匹配 agent 的预注册配对实验；实用收益阈值、保持与塑性、完整失败和成本统计 |
| P1 多代兼容 | 完整版本身份与显式 carry/reset/migrate 声明；拒绝旧 task 回执 | 多任务、多代际和组合采用的真实消费记录；实际迁移或重置、遗忘和恢复轨迹 |
| P2 组织可塑性 | 保留既有 topology 提案与 owner 机制 | 拆分、合并、休眠、退休、重连相对固定图加优秀调度的净收益实验 |
| P2 RSI | 保留可训练递归目标及改进器组件的版本绑定能力 | 冻结与可继承改进器在完整匹配预算下的直接比较；后继改进效率的可靠增益 |

生产 owner 接线有可继续实现的工程，不能统称为权限阻断。当前源码中 `LearningIterationOwnerPortsV1` 的唯一实现仍在测试模块；ordinary main 尚未安装 learning bootstrap。真实 checkpoint 委托、durable stage jobs、提案、选择和后继读取需组成生产 ports，再通过可信宿主注入现有 channel。启用和采用时还需原注册 owner、受保护 frontier store、正确签名域的阶段证据、独立评价 custody 及原 CURRENT/journal/FinalUse。普通 stdout、哈希或另造签名不能替代这些证据。

## 实验与失败保留

现有 170-run 的原 job 与预算不变。S81 的原请求仍按其 UNKNOWN / MAY_HAVE_BEEN_SENT 状态保留，不能换 key 重启。旧真实 NDU pilot 的四次独立 fit、11,680 个 episodes 和 234 个锁定文件继续属于其原源码与原计划，科学结论保持 Inconclusive / HOLD。

本次公开 development 材料和旧权重的恢复检查是额外、计量的工程观察；不训练、不读取确认或 retention 标签，不把诊断进程计作独立 fit，也不补造原 pilot 未保存的 step stdin。后续实验必须先冻结实际新 source、数据划分、预算、随机种子、evaluator、停止规则和实用收益门槛，再启动新的完整执行身份。
