# 冻结训练 RR 模型的真实原生特征桥接

## 已执行的结果

真实 `rr_full` seed101 训练检查点已经通过未修改的 Hepta `InferenceControlModelPort` 执行。6 个实际 SIGKILL 窗口及 19 项拒绝检查全部通过；恢复并继续运行后的全部 RR 状态、PCG64 状态、导出 Q24 值与不中断执行一致。这里的“真实”指模型参数运算、CTMC 事件采样、正式模型请求／回执和原生 journal/witness 持久化路径都实际执行，而不是把模拟回执当作已执行结果。

| 绑定对象 | SHA-256 |
|---|---|
| 发布的 validation selection | `dbad2690403992f75c46105722670026e7e13acb523f4973f4726a91d6e5d6bd` |
| 训练检查点 `rr_full/seed_101/model.pt` | `32d23ba4e030beb5850b25faff1fd119c08da4af2035ca70ba40aa4c0d5af651` |
| 完成训练回执 | `d06b5dbe957092369d0b324c6702c5fb815cedcf77c080564d310c5e886cfeac` |
| 桥接 manifest | `f0607664a599aabc3a8390f148f865a26ebf9a843a1f269133058e47365219ec` |
| 原生 broker 二进制 | `f7ea42df3b9e55aa0d3d01a67bd363dee25641a05db54e7907a30fac5092cc87` |
| 训练模型桥接证明 | `ea46a817da890d049e2a88870df91f54a475b51e4b7a9c4bfe94f258a056fd6c` |

选择记录在不可变提交 `ff2925c115a00b348ac1e46016b4a9130447e695` 中发布。桥接通过冻结的 `evaluate.validate_selection` 和 `evaluate.load_policy` 验证候选成员、训练回执摘要、训练／预数据协议以及检查点内 variant/seed/protocol 身份。这里没有读取 holdout 任务、质量标签或未来效用；测试输入是单独构造的三个数值观测。

独立审核分为两个不可互相替代的记录：`independent_rr_bridge_review.json` 审查源码和开发权重证据，另有 `independent_rr_bridge_trained_addendum.json` 对照已发布选择记录、训练检查点成员身份及完成的训练桥接证据。审核方没有修改实现。训练 addendum 的 SHA-256 为 `f1b470f71345529159c5977b2ab7a0dfa7dd46696972913236c5f9c5b1ce77d4`。

## 接口和数据流

`rr_bridge_artifact.py` 固定模型、来源代码、Python/NumPy/PyTorch 版本、原生 broker 和导出规则。`rr_bridge_native/src/main.rs` 负责从真实 admitted input 构造正式请求，校验回执，并调用上游 `NeuronRuntime`、`SparseJournal`、`FileAnchorWitnessStore`。`rr_bridge_backend.py` 在 CPU 上执行冻结 `RRPolicy.step`；`rr_bridge_worker.py` 负责研究宿主的外部状态和原生提交之间的协调。

每次请求输入是 22 个 Q24 特征，加上显式的 `dt_micros`、`neural_time_micros`、`event_mask`、前一个 native checkpoint 和已知的联合状态前沿。native 时钟使用正的固定偏移，因而初始神经时间可以为零，又满足原生单调时钟约束。完整 admission 字节摘要进入原生输入身份。后端再次调用已固定二进制的无 journal `describe` 模式，要求完整正式请求及其摘要逐字匹配，然后才能生成新状态。

输出是 8 个真实指数脉冲迹线经 `tanh` 后的值，按 nearest-even 量化到 Q24。8 维 prediction 固定为零，没有预测质量主张。冻结模型的 81 动作 head 在 `step` 内确实计算，但仅记录为 `head_logits_not_routed`；它没有成为原生动作策略或下游执行请求。模型 width8/top_k1 配合严格研究 fixture 接受条件，使全部 native tick 都 abstain，且 authority 始终为 DENY_ALL。

## 两层状态及幂等提交

原生 V1 sparse checkpoint 保持原有格式。RR 的完整状态与 RNG 存在外部内容寻址文件中，由联合前沿同时绑定其摘要和原生 anchor。没有把神经状态悄悄塞入 V1 状态键，也没有宣称原生 anchor 单独包含整个 RR 状态。

持久化覆盖 `CoupledState` 的十个字段：`indices`、`trace`、`context`、`drift`、`boundary`、`time`、`total_counts`、`observed`、`pending_initial_score`、`initial_resource`。每个字段保存种类、dtype、shape 和原始数值字节，不经过十进制浮点格式重建。PCG64 的 128 位 state/inc 以规范十进制字符串存储，`has_uint32` 和 `uinteger` 缓存也保存。完整 RNG 不通过可能损失整数精度的 Rust JSON 数字通道，只传递文件路径和摘要。

一次事务先从独立固定的前态计算候选 RR 后态和特征。宿主通过纯 native kernel 预测该输入及输出所对应的下一 anchor，形成 pending 提案。外部控制器先持久化并独立固定提案摘要，然后才允许原生提交。原生提交成功后，宿主发布同时指向 native anchor 和 RR 状态的联合前沿，控制器记录该前沿，最后结束事务。

如果已有独立固定的 pending，恢复先检查当前联合前沿只能是其前态或后态，再进行 native anchored recovery。native 已到后态时仅发布匹配的 RR 前沿；native 仍在前态时重复提交同一份已固定特征，后端不再次推进模型或 RNG。已知发布到后态的控制器会拒绝回滚到前态的联合文件。

如果计算出了 prepared 文件，但控制器还没有固定它，则该文件只是孤立产物。后端不会扫描目录后自动接受它；重试从可信前态及 RNG 重新计算。物理计算可能发生两次，这一开销被如实计入执行次数；最终已提交的 RR 状态及 RNG 只推进一次。

## 实际故障验证

训练证明文件为 `rr_bridge_results/trained_latest.json`，时间戳原件为 `rr_bridge_results/selected-trained-1793287054645308057/proof.json`。每个故障由 SIGKILL 杀死本次拥有的 worker/native/backend 进程组，退出码为 -9，控制器保留在故障域之外。

| 故障窗口 | 恢复行为 | 全部三个提交的实际模型调用数 |
|---|---|---:|
| prepared 已生成，pending 尚未独立固定 | 忽略孤立 prepared，从可信前态重新计算 | 4 |
| pending 已独立固定，native 尚未提交 | 重用固定的 prepared，完成一次 native 提交 | 3 |
| native journal 已写，witness 尚未发布 | 常规 anchored recovery 完成原生恢复，协调 RR 前沿 | 3 |
| native witness 已发布 | 核对原生 anchor，协调 RR 前沿 | 3 |
| 联合文件已写，控制器尚未确认发布 | 以独立 pending 绑定的后态完成发布 | 3 |
| 控制器已经确认联合前沿 | 保持已知后态，幂等完成确认 | 3 |

三个训练模型观测的实际内部脉冲数为 `[0, 0, 1]`；第三次观测中的脉冲时间为 `0.8352915384406105` 秒。训练证明在第二次事务注入故障，并验证恢复后的第三次事务确实产生相同脉冲及全状态。开发权重证明 `[0, 1, 0]` 在含真实脉冲的第二次事务注入同样六种故障。独立 codec 测试另外用两次真实脉冲后的状态验证全部字段、下一条采样路径及后续 64 个 uint32 随机数一致。

19 项拒绝检查覆盖：缺失独立 pending pin；错误 manifest/current-frontier pin；实际 native/backend/Python 文件不匹配；prepared、PCG64、pending 和当前前沿篡改；正式 request ID、generation、encoder/head/input digest 及 request digest 不匹配；host dt 与时钟不一致；当前源文件或冻结权重不匹配。所有拒绝均没有新增模型执行。当前前沿篡改在 native recovery 之前被拒绝，测试核对 journal/witness 字节完全不变。

## 信任和覆盖范围

独立当前控制器前沿和 pending pin 是前提。这里测试的是故障 worker 及其子进程，控制器自身的崩溃恢复、丢失其可信证据或生产身份认证没有获得证明。若 pending 文件已经落盘，但独立 pin 尚未来得及持久保存，当前入口拒绝该文件；六个命名故障屏障不等于穷尽所有字节级交错，也没有自动推断丢失 pin 的许可。

桥接证明先成功建立第一个联合 checkpoint，故障从第二次事务开始。原生第一次 journal 落盘到第一次 witness 发布之间的缺口由另一个显式 bootstrap 补丁和独立生命周期前提处理，见 README 与 PR #4274。桥接没有自动调用该初始化恢复入口。

这是一条真实执行的训练特征后端参考路径，尚无生产模型注册／校准、Agentd/CNS 路由、完整 DecisionCell slot 编址、81 动作策略接管、真实未来窗口收益、负迁移或 dot 主机证明。所有这些 scope flag 保持 false。模型性能结论必须引用独立冻结任务比较；本证明只处理执行身份、状态、故障及拒绝语义。

后端记录的 RSS 是整个 Python 进程 RSS；`transient_upper_bound_bytes` 是整个进程 VmHWM 的保守驻留上界，不是孤立临时分配计量。原生运行 wall time 包含 Python 启动和测试屏障，不能作为模型吞吐或 p95/p99。README 的 64／256／1024／4096 规模表执行的是另一个固定 Q24 投影后端，单位是原生 owner 组件实例，不能把这些成本赋给训练 RR 桥接或完整 Cell。

## 本地复现

源码使用已经冻结的 V4 `models.py`、`operators.py`、`evaluate.py`，没有修改它们。原生 broker 离线构建引用 commit `f8c9419df6ddeb36ff8b522a50219981fb8d9345` 的三个 crate；62 个上游源文件按原始 manifest 验证字节数、Git blob SHA 及 SHA-256。构建依赖现有 V2 目录中的独立 crate manifests、vendored crates、Rust 1.95.0 和 just，不会自动下载依赖。脚本中的工具链和 Python 路径记录的是本次环境；跨宿主复现需要显式提供等价依赖，并生成新的运行 manifest，不能把新二进制冒充已证明二进制。

```bash
python3 rrsnn_v4/hepta/build_rr_bridge.py
python3 rrsnn_v4/hepta/validate_rr_bridge.py --development
python3 rrsnn_v4/hepta/validate_rr_bridge.py \
  --artifact /workspace/scratch/38ad1e295a60/rrsnn_v4/results/rr_full/seed_101/model.pt \
  --training-receipt /workspace/scratch/38ad1e295a60/rrsnn_v4/results/rr_full/seed_101/training.json \
  --selection /workspace/scratch/38ad1e295a60/rrsnn_v4/selection.json \
  --selection-pin dbad2690403992f75c46105722670026e7e13acb523f4973f4726a91d6e5d6bd
```

原有 broker 已保留时直接运行证明命令；构建脚本拒绝覆盖保留的二进制。每次证明创建新时间戳目录，保留旧源码快照和旧证据，不将开发权重证明重新标记成训练权重证明。CPU 固定为 8；没有 dot 身份或生产权限推断。
