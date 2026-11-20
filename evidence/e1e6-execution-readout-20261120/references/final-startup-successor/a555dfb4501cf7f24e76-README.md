# 41a：prepare-before-delivery 与初始 A 的静态时序边界

## 结论

在精确 `41a0fd9bbbc30051f1e7492cd17eeeb5337aa7a0` 的 `ordinary_main_retains_after_completed_independent_b_and_executes_original_c` 路径中，**新增 `prepare_original_delivery` 不会在初始 A 的 Root Initial 装配、Objective ACK、独立 Observer 或 A 进程退出检查中执行。它必须等 `run_original_a` 整体成功返回，随后启动明确的 `q24-post-a` 进程，且该进程完成 post-A 装配后才可能执行。**

这不是从函数名推断的时序：父函数同步调用顺序和生产入口的 `PrimaryInputs` 分派分别提供边界。即使 A 的 Objective 与 Observer 已成功、仅在等待 A Root 成功退出时失败，仍未越过该边界。

此结论限定直接调用可达性。它不证明当前 header-write/Unavailable 的底层原因，不把未执行的修复算成通过，也不以静态分析排除编译布局、运行环境或调度等非局部影响。当前六份 stdio 的实际首错归因由另一独立审查处理；本包没有把新日志摘要当作自己已读回的执行证据。

## 两道顺序边界与实际入口

下表路径均相对于 `codex-rs/hepta-agentd/src/`；本包 `source/` 保存完整精确字节。所有 14 份源码逐项匹配实际 15,813 文件库存（完整库存 SHA-256 `997faa5b40ccacd8f24de5f6d7ee7d4efed77b7487cb3c3f9bbf08c14cf9781d`），而不是仅用旧提交名声明相同。

| 源码锚点 | 可证事实 |
| --- | --- |
| `ordinary_q24_post_a_process_tests.rs:28–54` | NoUpdate 主测试调用 `run_original_business_case`；其 41–42 行先执行同步的 `super::run_original_a(...)?`，随后才创建 post-A deadline、reserve resources、B 输入与 `RunningOrdinaryPostA::start`。`?` 使 A 失败直接返回。 |
| `ordinary_q24_process_tests.rs:138–147, 180–218, 222–230` | A 先启动并 promote，调用 `objective_start_once_until` 与 completion；再等待独立 Observer、核实际 observation；随后请求 daemon shutdown，等待 daemon 和 Root 成功退出、验证两者死亡，读回非零且稳定的 Root Source pin，最后才能返回 `RetainedOriginalAPhase`。 |
| `ordinary_q24_process_launch_tests.rs:33–54, 95–120` | A Root 使用 `serve-fresh-material-session` 和 Initial handoff；A daemon 明确传 `--root-production-profile q24-initial` 与 `--q24-initial-deployment-fd`。 |
| `ordinary_q24_process_fixture_tests.rs:287–299` | A 的 sealed deployment schema 为 `hepta.agentd.original_initial_q24_launch.v1`；不是 post-A deployment。 |
| `production_launcher_inputs.rs:134–147, 413–425` | CLI 的 `q24-initial` 与 `q24-post-a` 先映射不同 `Profile`，再分别构造不同 `PrimaryInputs` enum variant。 |
| `main.rs:236–247` | 生产 main 顺序 await Initial assembler、Post-A assembler、launch.run；因此不能仅因为 main 文本中调用了两个 assembler，就认为二者都会执行其业务分支。 |
| `production_initial_q24.rs:32–41, 155–175` | Initial assembler 仅消费 `PrimaryInputs::InitialQ24` 内的 deployment；原 enum variant 保持 Initial。其实际返回的是 Source/Cell/Circuit 与可选 ledger 组成的初始任务 runtime。完整函数中没有切换为 PostAQ24。 |
| `production_post_a_q24.rs:41–50` | Post-A assembler 只在 `PrimaryInputs::PostAQ24` 时继续；所有其他 variant 立即 `return Ok((self, config))`。因此 A 的 main 对它的调用是早返，不构造 continuation。 |
| `ordinary_q24_post_a_plan_tests.rs:46–71, 90–103` | post-A resources 消费已经返回的 `RetainedOriginalAPhase`，再次要求原 daemon/root 已死，并构造独立后继 deployment。 |
| `ordinary_q24_post_a_deployment_tests.rs:148–188`；`ordinary_q24_post_a_launch_tests.rs:26–45, 77–124, 258–268` | 后继使用明确 `original_post_a_q24_launch` schema、独立 `serve-recovered-material-session` Root 和 `q24-post-a` daemon；不是 A Initial 进程内提前启动的一条 continuation。 |
| `production_post_a_q24.rs:87–136, 249–282` | 后继先取得真实 historical task/trust、freeze/ACK/owner handoffs，最后才构造 `OriginalPostAContinuationV1` 并安装到 learning bootstrap。完成历史专用分支 67–85 行也会早返。 |
| `learning_iteration_historical_source.rs:297–334` | 只有 `self.continuation` 存在才进入新增 prepare；无 continuation 直接沿原 delivery 分支。prepare `.await` 成功后才创建 delivery future 和 prepared consumer future。 |
| `production_post_a_continuation.rs:146–209, 213–240` | 新 prepare 等同一后继 admission，随后核实际 historical source 和原 trust/receipt，返回私有 prepared owner；prepared consumer 随后才等待 decision。它不是 A Initial/Objective 的 ACK 实现。 |

## 身份、范围与未执行项

- `SOURCE_PINS.json` 保存 14 个完整源码的 SHA-256、Git blob、原路径、实际库存逐行和不可变 GitHub URL。
- 原始 commit object 已本云重算 Git SHA，等于上述 41a；tree 为 `ea62214ae90a4b1f5e47d9690694c234521746dd`。`provenance/source-commit.raw` 保留原 726 字节。
- 12 份源码复用本云既存原件；只有缺少的 `production_launcher_inputs.rs` 和 `production_initial_q24.rs` 进行了两次 exact-41a GitHub 文件只读获取，完整工具返回保存在 `api/`，内容同时匹配实际 inventory 与服务返回的 Git blob。
- 本包只运行本云文件复制/哈希/身份核对，未执行被审查 Rust、Python 源码控制、native、模型、编译、宿主 API 或任何 Git 写入；不修改正式报告、旧证据、实验预算、产品或 policy。
- 可严格写为：**如果本轮失败发生在上述 A 路径返回之前，新增 prepare-before-delivery 分支尚未执行。** 不可据此写为“已证明一切源码变动与当前失败无关”或“本轮已经验证 post-A 修复”。
