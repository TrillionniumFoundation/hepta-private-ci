# 独立只读复核：H2 在线反馈、资格链和成本

复核者：`control_next`。准确源码、元数据 SHA 与复核时间见 [CONTROL_REVIEW_SOURCES.json](CONTROL_REVIEW_SOURCES.json)。本复核没有修改实验源码，没有加载模型、执行 owner、运行 ASR/codec，也没有打开任何新的来源质量结果。审查过程中发现的问题由实现者在新的来源冻结前修复，再由本复核逐项检查差异。

**结论：在清单所列版本中，未发现剩余的阻断性静态代码问题。这个结论不授予新资格，不证明数值动作一致，也不证明原生策略的质量或成本收益。** 两次历史 64/64 pilot 的失败必须保留；新 100/1,000/128 来源角色能否进入后续阶段，仍取决于既定阶段门及实际结果。

## 本次关闭的实现缺口

| 问题 | 修复后证据 |
| --- | --- |
| 获得资格后，package 原先可能重新加载当前 encoder/sensor，而未复验原资格的完整函数身份 | `qualified_dependencies` 在 package、descriptor、execution freeze 和 run 的实际模型使用前，重新核验原 `QUALIFICATION_PROTOCOL` 全部 pins；实际 MODEL、SENSOR、TEACHER、OBSERVER、predictor、calibration 实参的 resolve 路径和 SHA 必须属于该资格清单。 |
| 原 pins 没覆盖定义实际资产路径的 `native/common.py` 及 encoder 的本地 Python 依赖 | `common.pins` 使用 stdlib AST 递归追踪真实本地 import，包含父包初始化、public features、observer、sensor、generator 等依赖。独立枚举得到 62 份源码/配置身份，另外由生产 pins 固定四个模型文件；没有带入并发变化的 `next/media`、`next/control` 或 `next/action_value` 源码。 |
| qualification freeze 原先只看校准文件的 predictor SHA 和统计，可能误用 legacy 任意 NPZ 生成的校准文件 | 现在必须匹配登记的 `CALIBRATION_PROTOCOL`，复核实际 100-writer collection 的 results/access/data/rows 身份与 census，重算固定 bin 概率和统计，与记录精确比较，再复验原校准源码及模型 pins；这些 collection 依赖还会进入 qualification pins。 |
| 执行分析缺少 allocation 与 protocol 的显式 SHA 比较 | `analyze.audit` 先核验 allocation SHA，随后继续逐 request 检查 source IDs、writer、pair 和两策略共同初始 prefix。 |
| 记录声称 private truth 在 owner 关闭后才“可用”，但 task constructor 已在 host 中构造 Target | 字段改为 `private_truth_scoring_started_after_all_owners_closed`；METHOD 明确区分 host 内存在 Target 与实际在线数据流没有读取或传递 Target。 |
| 扩大旧开发沿用 `selected()` 的 `writers` 名称，实际分组是旧 source pair | 该份诊断改为 `source_pairs` 并写 `unit_is_writer=false`；没有改变任何结果或门槛。 |

关键修复后版本：

| 文件 | SHA256 |
| --- | --- |
| `common.py` | `a1518a844e8bb3a1df7b166997d2f209ff35b6f30a1c0c5fbabba295bda13618` |
| `model_package.py` | `0d271908a88f996940925315353f6d7e53ed33690c9ce583bcb794ef87390c10` |
| `freeze_execution.py` | `ea83992591e2301d94b051dbdef3b6a029cb5d03eab4c6c0d7a334ba73f7214e` |
| `prospective.py` | `4e0589ab85e9e7df0fe10302f0554e01947d5c847ded1159b8497fd5320e3147` |
| `run.py` | `b9d5d41919003ed2e01ab2fbbb19ca5a1c29532bdb96fd5e1bb4c9565fa11138` |
| `analyze.py` | `3d420769f561733c47ca343da0b3cbdbd0d11414d53cf6f6f22048a673479756` |
| `old_feasibility.py` | `ffd0fa4ed44a0ffd184b2992ffc1cbee003d7ab8146458b1db49efb02d7ca4b4` |

## H2 到 H1 的信息边界

`run` 的实际顺序是：生成初始公开状态；从 observation 与当前 draft 构造公共特征；提交 owner 决策并持久化；使用该动作对应的未来 RNG 做真实 transition；写入并重读实际图文；由现有 public sensor 观察；提交并持久化 outcome；之后才进入 H1。`episodes.rs` 把 H1 请求绑定到同一个 episode、前一步 outcome digest 和结果的 public-state digest。错误 parent、prefix、episode、horizon、重复 request 及未完成 outcome 都有在 native tick 前拒绝的分支。恢复会同时核验 owner frontier、controller history 和 NDU projection，未完整提交时 fail closed。

公共观察器只接收冻结 public sensor、实际重读像素和 caption。它不接收 Target 或 private observer，使用的有界 proxy 是 `1 - invalid_caption - image_text_disagreement`。私有 reward observer 的实际加载与评分位于所有 owner process 关闭之后。静态调用路径未发现 private truth、私有评分、未来 RNG 状态或未实现 counterfactual 被送入第二步决策。

这项结论有明确边界。Target 对象本来就在研究 host 内，隔离依靠所审查且固定的调用路径；它不是 Python 安全沙箱。Rust 检查 receipt 身份、media 文件、时间关系、episode、声明和数值边界，但不会自行重跑 public sensor 来证明 proxy。METHOD 已明确写出可信研究 model-service host 的范围。该 proxy 可以奖励一致但错误的输出，也没有被称为真实效用或全局 NDU。

## 103 维实际模型与原 owner

公共 ABI 是四个缺失输入坐标、两个 action flag、一个 horizon、32 个冻结 teacher activation 与 64 个 correctness activation，共 103 维。输入前缀、hidden 和 horizon 在五个候选之间必须一致，只有 action flag 不同。两组 activation 均来自实际公开状态，经过固定 Q24 边界；Rust 执行对应 horizon 的 32→5 conditional-moment 最后一层及 64→5 correctness 最后一层。

正确性头接收的公共 763 维原始特征经过 fit-only normalizer；sensor 的输入是 observation 或当前真实 draft。源码不把 source ID、Target、private score、未来噪声放入这些层。预测器、calibrator 和实际 native 层的数组与身份在 bootstrap 交叉核验。correctness carrier 的其余 32 个坐标明确为零，没有被伪称为旧 future-state forecast 或旧校准。

build 复用原 `AgentdNeuronOwner`，并核对其固定源码 SHA；runtime calibration/resource 配置保持原门槛。bootstrap 变更仅涉及本模型维度、身份、有限序列期限，以及已有的 bounded dynamics profile。配置仍使用 `confidence >= .75`、ECE 不超过 `.03`、FAR 不超过 `.004999`，没有通过改 active/resource ceiling 来绕开新模型准入。具体编译与资源结果仍须由实际运行提供。

## 新资格的实际输出与统计单位

实际 collector 覆盖 H2 root 以及 semantic/image/text/couple 之后的四个 H1 state；每个状态在任何该步未来生成之前先持久化公共预测，再枚举五个真实动作输出。标签是这一步实际 emitted output 的 joint correctness。这里没有用 hindsight 最大值或 eventual-best 标签替代即时 correctness。

新校准计划为 100 个 writer，每人一对来源、六个 view、两个 future draw、五个状态和五个动作，共 30,000 条输出。独立资格为 1,000 个不同 writer，每人一个 ID view 和 absent view、一个 draw、同一状态/动作树，共 50,000 条输出。`load_census` 检查数量、分组、horizon、每个 state/action 和分配的 source IDs/writer。重复 view、draw、state 与 action 不是额外独立样本。

新资格的四道原门保持：校准和验证 ECE 点估计上限 `.03`；两者 OOD FAR 上限 `.004999`；ID acceptance 至少 `.25`；验证的 writer-level OOD 一侧 95% 上界不超过 `.004999`。`verification` 必须是新的 H2 schema、固定 1,000 writer/50,000 行、对应新校准和资格 protocol，不能直接拿原 H1 报告通过 package 或 bootstrap。pooled ECE 不被包装成 population bound、每个 action 的资格保证或 selected-policy 校准；这些是另报的诊断。

## stop、mask、investment 和费用

五动作顺序在 Python 和 Rust 中一致。stop 保留当前实际 draft；无候选通过门时的 null action 是 rejection，按 `utility=-1` 计分，不是成功停止。H1 的 semantic 动作保持同一输出并额外收费，因此保留原 dominance mask；H2 semantic 仍在可行集合里，但还需通过即时 correctness 准入。

即时准入可能限制所有“当前输出不足、下一步才改善”的 investment 动作，不只 semantic。对 H2 semantic 尤其直观：当前 draft 与 stop 相同，即时正确性不足时可能被挡住，尽管随后生成还有收益。这是当前约束问题的实际定义，没有在本轮改成 eventual-terminal correctness 来争取通过。

因此，完整 teacher 的数值层移植不等于原来未加该准入约束的 teacher 策略。每步分别记录 unmasked teacher、同 admission 集合下 teacher 与实际选择；主要效益比较是 native NDU 对同样准入规则的 correctness argmax。原独立 control 研究的 unrestricted-teacher 收益不能继承给此原生比较。原始浮点 teacher 的 `3e-6` 数值容差也不能自动保证全部 near-tie 动作相同，实际 action parity 必须单独报告。

teacher 的 conditional targets 已含每个非 stop 动作 `.002` 的 nominal cost，因此 Rust argmin 不再次加费；实际评价在 terminal utility 上减去 `.002 × continuation_actions`，每个实际非 stop transition 只计一次。训练预测内的成本与现实结果的计费属于两个对应环节，没有在同一次最终计分里重复扣款。request 成本从 task/initialization 开始，包含公共编码、owner candidate ticks、真实生成、持久化/读回、公共感知、数值核验和 feedback，仅减去单独计时的故障/负向探针；最终 row 序列化与后置 private audit 另在 whole-child 成本中保留。

## 扩大旧开发与后续冻结

新增旧开发保持第二个候选的 weights/cuts，排除其 256 个 fit pair 与两次 pilot 涉及的 128 个 selection pair，按固定 hash 从其余历史 `forecast_calibration` 选 400/400 pair。校准先落盘，再实际生成 held 阶段；阈值与新角色没有改动。它是另立的旧开发可行性阶段，不能被称为新的独立 writer 资格，也不能覆盖两次原失败。未分配的 72 个旧 pair 不是继续追逐 pass 的储备。

源码身份清单允许最终 freeze 前只对差异再复核。若代码或依赖变动，应保留这份版本化记录并另作 addendum，不能把本审查结论无条件转给新版本。实际编译、旧开发结果、新校准、独立资格、smoke/recovery 和独立执行都仍是各自的证据阶段。
