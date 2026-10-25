# ABC3 native resident correctness experiment

本目录完成新 observed-output correctness head 的真实独立资格、原始 `NeuronRuntime` 执行、durable journal/recovery，以及同上下文原始 dynamic resolver → 非零参数候选 → 待独立验收 proposal。

**当前界限：** ID ECE 点估计 0.024466055；800/800 ID 非 abstaining，0/800 constructed-absence OOD 被接受；1,600 次实际恢复一致。产品 admission 真实返回 `ArtifactBinding`，状态 `RequiresIndependentAcceptance`、`DENY_ALL`，没有应用更新。不是未来 latent-dynamics predictor、Agentd/fleet 或生产资格。

- [REPORT.md](REPORT.md)：主要完整报告、效应与统计限制、实际 blocker。
- [RESULTS.json](RESULTS.json)：完整主要数值、冻结链、confidence bins、成本与测试摘要。
- [PROTOCOL.json](PROTOCOL.json)：首次保留来源访问前冻结的协议，保持原字节。
- [REPRODUCE.md](REPRODUCE.md)：实际原始源范围、命令、测试与格式化路径。
- [EXECUTED_SOURCE_PINS.json](EXECUTED_SOURCE_PINS.json)：真正被资格/执行使用的源码身份。
- [UPSTREAM_SOURCE_PINS.json](UPSTREAM_SOURCE_PINS.json)：固定原仓库 ref 的 428 文件身份。
- [EVIDENCE_INDEX.json](EVIDENCE_INDEX.json)：本地大证据的字节数与 SHA；不上传原始数据。

Python `collect/features/qualify` 处理真实输出、公共输入、一次性资格顺序；`packet` 只导出已经观察的验证输入用于 native 重放；Rust `head/runtime_profile/main` 执行实际 resident head 和原 runtime；`proposal` 调用原 resolver/候选/registry；`evaluate_candidate` 保留不利 development 结果；`audit` 复核来源、实际媒体与 native confidence；`upstream_cost/training_cost` 显示 native head 之外的成本；`build` 只准备隔离的原字节 library workspace。
