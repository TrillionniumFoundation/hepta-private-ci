# ACT2 原 Notes seed：finite-v2 候选

状态：**CANDIDATE_NOT_EXECUTED**。本包只保存可审查源码；没有 commit、ref、PR 更新、actor 调用或编译。测试、caller proof、格式化均未执行。
精确基线：`b02850c04dcd40f2703e95cc670df531468fd0e3`，tree `09d528e50446fac713736c5a1b2d099b97399a12`。
代码候选 tree：`88781d9f6dc0163fb1f2f4b5239947e004d71566`；8 路径，364 行增加、2 行替换。

## 原失败与原因

原 run `43163424939`、job `130999664797` 的 Notes seed 命名用例在真实 build 后失败；完整日志由父任务保全。
错误为 `original literal Notes: original Notes effective Core execution profile differs`。
测试写入原 finite 配置，要求 `hepta_memory=false` 与 `hepta_cognitive_write=false`，却以无参数的普通 Agentd 启动。
普通 `Standard` 分支强制 memory 开启，默认 Cargo profile 同时开启 cognitive write；原 `verify_effective` 正确拒绝。
现有 `OriginalNotes` 分支依赖实际 Root Notes 工具 runtime；该 runtime 又要求已存在的原 seed receipt，因此不能用它冒充预置阶段。

## 最小接口

普通 daemon 可显式选择 `--notes-thread-seed-profile finite-v2`；其它值、重复 flag、其它 Agentd 参数、Root launch 混用均拒绝，非 Linux 拒绝。
Linux 的 `AgentdConfig::with_original_notes_seed_profile()` 只设置私有布尔模式并调用原文件检查；不创建签名、grant、Root、工具 owner 或 receipt。
`run_with_shutdown` 在首个 `take_*` 前重验：绑定 socket、26 个可选配置/owner、非 Compatibility 检索模式均不可混入；再读取原 finite 文件。
内部 `OriginalNotesSeed` 独立返回 `false`，复用既有 CLI 覆盖、required feature states 和 mutation 过滤。
默认模式仍为 `Standard`；其原分支和原 Notes/Desktop 分支不变。

## 原边界保持

`notes_thread_execution.rs`、`notes_thread_seed.rs`、`notes_thread_tool.rs`、`notes_launch_mode.rs`、`production_launcher.rs`、`production_launcher_inputs.rs` 原 blob 不变。
finite 常量、有效配置拒绝、签名、Root handoff、原 receipt 生成/回读未改。
`CALLERS.toml` 原全文保持为逐字前缀，只追加 29 行新保护；没有删除原 marker、顺序约束或拒绝规则。
新模式只减少预置阶段 Core 能力，不能提供后续 Notes 执行所需的真实 owner。

## 待执行回归

| 用例 | 需证实的行为 |
| --- | --- |
| 原 named positive（保留原名与全部 receipt/thread 断言） | 显式 finite-v2 经真实 Agentd 与 launcher 创建一个未使用线程，provider 请求保持空 |
| 新 Standard negative | 默认模式仍以原有效配置错误拒绝同一 seed，stdout 不出现 receipt，provider 请求保持空 |
| 新文件/owner 正例 | 原 finite 文件可选；同一 config 仍被原 `require_finite_notes_profile` 拒绝，因为未取得执行 owner |
| 新配置混用反例 | objective、AuthBus、Hnmf 在 seed 前后配置均拒绝 |
| 新文件变更反例 | 选择后再开启 memory、cognitive write 或本地环境仍被原检查拒绝 |
| 新 embedding 回归 | 复用原真实 store/extension helper，确认重开 feature 的请求仍不能恢复通用 cognitive 工具状态 |

原 integration 1 方法；新增回归 5 方法；尚无运行结果，不能记录为 PASS。
计划命令详见 MANIFEST；原 workflow 未更改，整合者需显式运行 5 个新增方法，不能仅运行原命名正例就宣称回归完成。
Rust 1.96 编译、实际测试、caller proof、格式化都是后续门。通过预置测试也不等于 full Notes handler、Root、最终 effect 或学习增益通过。

## 完整性

MANIFEST 列出 8 个 base/post Git blob、原字节数与 SHA-256；均从 immutable tree 读回逐字核验。
DIFF.patch 是这些精确 postimage 对固定基线的统一差分。完整性检查只证明文件对应，不替代执行验证。
