# E1–E6 v3：真实来源核查与开发任务交付

## 结论和可用数量

本轮找到了可实际执行的 SQLite 工作流环境和明确的项目需求，但没有核验到可作为新独立来源的外部用户 coding-agent 轨迹。当前新增材料全部归为开发材料；没有新建 A/B/C 确认划分，没有构造或查看新的 v3 C。

| 对象 | 本轮实际核查数量 | 可以支持的用途 |
| --- | ---: | --- |
| 指定仓库 | 2 | 源码、问题和历史资格材料核查；两个仓库不等于两个独立用户或项目 |
| Chain 原始 issue | 3 | 核验真实项目需求；均由同一 GitHub 账户发布 |
| issue 作者账户 | 1 | `ProfHepta` / ID `102159240`；没有把账户数改称已认证独立人类用户数 |
| 新核验的外部用户动作轨迹 | 0 | 不足以建立多用户、来源外泛化或未来时间验证 |
| H7 实际数据库行 | 未知 | 读取的是 schema/guard；实际数据库行读取数量为 0 |
| ACT-2 历史训练轨迹 | 80 | 可做受控工作流开发；一个标准化 SQLite 环境家族，脚本策略示范 |
| ACT-2 训练轨迹中的原语事件 | 448 | 真正记录的执行动作；不增加独立任务或来源数 |
| 新开发任务实例 | 3 | 丢失回复、已有暂存、部分完成；全部保留同一派生 lineage |
| 本轮新 SQLite 执行 | 4 | 三项参考完成和一项预期失败对照；没有模型或训练调用 |
| 新的独立来源、新用户、新 C | 0 / 0 / 0 | 没有补造不足的实验规模 |

核查范围是指定线索、可访问问题/PR、精确源码和保留的 ACT-2 原件。以上“0”是本轮核验到的数量；它不是全仓、全磁盘或所有服务中不存在其他轨迹的证明。机器可读结论、来源身份和字节摘要见 [provenance_v3.json](provenance_v3.json)。

## 固定来源和时间

本轮读取的主分支身份为 Hepta `732e934ba496d90fbe042b8d41d479ef901643e5`、Chain `59bd6ae4223caff6695dc9cf2ee2cdcdc6df5e88`。历史实验按各自 PR 的精确 head 读取，不能把历史实验结果转移为当前主分支的通过。

| 原始记录 | 创建时间 UTC | 本轮用途及 lineage |
| --- | --- | --- |
| [Chain #786](https://github.com/TrillionniumFoundation/Trillionnium-Chain/issues/786) | 2026-11-08 05:04:58 | 七组冷路径优化需求；workstream 3 明确涉及 SQLite prepare/batch/durability。作为三项开发任务的共同需求上游；七个 workstream 不计为七个来源。 |
| [Chain #596](https://github.com/TrillionniumFoundation/Trillionnium-Chain/issues/596) | 2026-10-31 01:37:36 | PoN、Cell、学习验收总账。保留作需求背景，没有派生成额外独立样本。 |
| [Chain #562](https://github.com/TrillionniumFoundation/Trillionnium-Chain/issues/562) | 2026-10-30 14:12:34 | 整链资格追踪。范围过大，本轮没有纳入模型任务，也没有执行攻防复现。 |
| [Hepta #5669](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5669) | 2026-11-10 07:49:15 | ACT-2 受控 SQLite 原件，head `0584b3344f70ed51d9e09224e105bfa4d1a4635f`。 |
| [Hepta #5735](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5735) | 2026-11-10 13:15:31 | 普通 Q24 原 CURRENT、候选使用和恢复组件，head `f97f3c90ac1ac3d5171fd9f25b3e34431f44a367`；只读原报告和缺口文件。 |
| [Hepta #6440](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6440) | 2026-11-16 15:51:46 | v2 已发布结果，head `42e32825ae20d460cb782856e00816661536853a`；旧 A/B/C 全部已曝光。 |

issue 的正文、作者 ID、创建/更新时间以及 PR 的原正文和 head 保存在 `source-records/` 的 API 字段快照中。快照不是原始 HTTP 序列化字节。九份源码、归档和原资格文档则保存了精确 Git blob 字节，并逐一核对 Git SHA-1 与 SHA-256。`provenance_v3.json` 列出了每份文件的路径、大小、摘要、原 commit 和原 URL。

开发任务的 `curated_at` 来自本轮实际写入时间，和上游 issue 创建时间分开记录。ACT-2 文件名中的 `20261110`、任务 replicate 和 goal hash 都不能替代原用户事件时间；没有取得这一类时间证明，相关字段保持未知。

## H7：有受限 journal 约束，尚未证明有可训练的真实轨迹集合

在 Hepta 主分支精确读取了 `0008_h7_trajectory_events.sql` 和 `0009_h7_trajectory_observation_guard.sql`。表级联合约束要求 `external_effect_executed = 0`、`kg_write_authority = 0`、`production_caller = 0`。后续 trigger 只允许 `turn_start` 和 `terminal`，要求 `reward_bps = 0`，并约束后续事件必须有 causal parent。原注释明确将这条写入路径限定为 observation-only，typed feedback/reward contract 尚未由这两份文件建立。[原 schema](source-records/h7_schema.sql)、[原 guard](source-records/h7_guard.sql)。

因此，可以确认存在具有来源字段和约束的影子事件结构；不能从建表语句推出实际入库数量、真实工具动作、用户授权监督目标或在线训练反馈已经存在。本轮没有打开 H7 数据库，没有读取凭据、隐藏推理或无关私人数据，也没有把数据库行数未知改写成零行。

## ACT-2：80 条原件确实存在，但不是 80 个用户或 3200 个独立经验

从 #5669 精确 head 重新取回并解压了 `training-trajectories.jsonl.gz`。10012 字节压缩文件解压后为 106947 字节，80 个 JSONL 记录有 80 个不同 task ID，集合与冻结清单的 80 个训练任务完全相同。全部来自 `B1_macro` 脚本策略；训练记录包含四种不同 decision 序列、448 次原语事件，终局实际 complete 72 次、success claim 64 次。[原轨迹](source-records/training-trajectories.jsonl.gz)、[本轮只读核验](source-records/ACT2_TRAJECTORY_READOUT.json)。

这些训练实例覆盖 schema 0/1、`train-a`/`train-b` 标签、五种故障和长度 1/2。原独立复核已经指出：schema 是同一家族的表/列重命名，destination 是实例标签，replicate 主要改 goal hash。B0 和 B2 调用相同控制器，B1 也来自同一确定性启发式；五个 arm 标签不能算五个独立教师。[原复核](source-records/act2_review.md)。

历史 16 次拟合来自两类学习器和八个初始化种子，每次 220 步；3200 次 confirmation episode 是 80 个确认任务实例 × 8 个种子 × 5 个 arm。它们没有增加独立用户或环境家族。run2 重用了已曝光 pilot 的任务集合，不能重新登记成未来时间或未见来源确认。原报告中 head 与固定策略完成率均为 512/640，GRU 为 464/640；这些是原固定实验的受限负结果，本轮没有重新运行或转移其资格。[冻结清单](source-records/act2_frozen_manifest.json)、[原 runner](source-records/act2_run.py.txt)。

复用环境还有一个能力边界：`stage()` 内部复制预先规定的 goal，`apply()` 内部同样查询 task goals。actor 只选择动作顺序，不生成 SQL 或目标 payload。SQLite 事务、持久文件和只读 readback 是真实执行，但这种成功不能称为通用 coding、模型编写 payload 或对用户真实仓库完成修复。最终 scorer 是同进程同权限中的另一只读连接，不是已认证的独立外部评价方。[原 destination](source-records/act2_sqlite_destination.py.txt)。

## 普通 Q24 历史线索没有关闭 E6

`learn-ordinary-20261110-14cc` 对应 #5735，本轮重新读取其 round2 README 与 `OWNER_ASSEMBLY_GAPS.md`，没有读取 custody 档案或密钥。原报告记录真实训练 heads 改变、版本机制发布、不同输入任务读取候选以及文件重开等组件行为；同时明确保留 `HOLD_ORDINARY_CHAIN_NOT_ESTABLISHED`，完整普通链、正向采用链和完整 NoUpdate/回退链均为 0。[原 round2 报告](source-records/learn-ordinary-round2-readme.md)。

原文件明确将 issuer、Dataset target 和 artifact-selection credential 标为测试夹具。缺少的原材料包括真实 source→target Dataset 与签名冻结、独立 B/retention、完整比较成本、适配冻结 Q24 SGD 的原 Model Proposal 路径或重新冻结的合法 Parameter V3 路径、生产 stage-owner 装配，以及真实 daemon/Root 两个 OS 进程的冷重启。当前 Proposal 的 Parameter/Topology 生成规则不能由事后补几个摘要替代。[原 owner 缺口](source-records/learn-ordinary-owner-gaps.md)。

这些历史组件结果提供工程方向，不为本轮学生权重、SQLite 开发环境或候选采用背书。组件用例中的 C 也不是本轮新的 v3 C。

## 已交付的三个可执行开发场景

新增 `scripts/cell_experiments/repo_tasks_v3_sqlite.py`，对固定 ACT-2 destination 源码做 SHA-256 校验后，在新的本地数据库上保持跨动作状态。接口 `DevelopmentSession.step(action)` 接受 `inspect`、`stage`、`apply`、`stop`，保存实际前后观察、原语调用数、写事务数和生效次数。模型接入者仍须保存其原始生成和解析结果；适配器自身没有调用模型，也不把脚本参考行为写成学生经验。

三个场景及参考动作、实际数据库、动作回执和结果保存在 [tasks/sqlite-dev-v3](tasks/sqlite-dev-v3/README.md)。它们共同使用 `derived:chain-786-workstream-3:act2-sqlite-family`，是需求相关的局部工作流开发，不是已完成 #786 性能优化，也不产生三个新需求或用户。

| 本轮实际执行 | 任务成功 | 原语调用 | 实际生效 | 业务检查 |
| --- | --- | ---: | ---: | --- |
| 丢失提交回复后重复 apply，再读回 | 是 | 5 | 1 | 数据到达目标，重复 apply 没有重复效果 |
| 已有首项暂存，再完成第二项 | 是 | 6 | 2 | 两项最终值正确，无重复效果 |
| 部分完成后先执行一次无效 apply，再恢复 | 是 | 5 | 1 | 未暂存的 apply 无效果；原已满足项 revision 保持 0 |
| 缺少 stage 的失败对照 | 否，符合预期 | 2 | 0 | 动作语法有效，但数据库仍为 old，业务判定失败 |

四次执行都完成了预定的结果检查，其中成功任务为三次，故意不完整的对照为一次。没有把“预期结果检查 4/4”写成“任务成功率 100%”。最终数据库重新打开后核验了实际值、revision 和 effects；没有执行 daemon/Root 冷重启。

v3 的 stop 只接受最后一次实际可见的 complete readback，不隐式代为 inspect。该语义区别于旧 ACT-2 runner，环境/verifier identity 在回执中独立记录，不能把 SQLite 原语计数套入 v2 `test_patch` 子进程指标。当前隔离目录没有 `codex-rs` 或 `justfile`；本次已执行上述业务检查，原仓库集成与要求的 `just fmt` 由 root 协调，不能将未执行的维护写成通过。

## 新 cohort 与 split 的执行约束

当前材料全部曝光，旧 v2 的 12 个任务以及 A/B/C=6/3/3 只作开发回归。#6440 已报告九个 B/C 分支任务成功均为 0/3、两个采用分支均为 NO_UPDATE；后续修复不得清除这些负结果，也不得将旧 C 重新称为确认集。[v2 原 PR 字段快照](source-records/hepta-pr-6440.json)。

下一组真实 cohort 应先记录原 request/issue、项目、可验证用户来源、事件时间、父子 lineage、授权范围、原始环境快照和可执行验收。可见动作、工具反馈、最后业务结果和用户修正可以作为经验；凭据、隐藏推理与无关私有内容不进入训练材料。失败、取消、超时和 UNKNOWN 保留原状态，不通过删除难例或重复执行提高独立样本数。

在任何训练前冻结任务群和时间截止线：同一请求的重放、种子、子代理分支、PR 派生与修订保留同一 cluster；事件时间使用原发生时间，不能用本轮导出/整理时间制造未来任务。A 用于训练，B 仅按预先冻结规则选择；候选、解析器、执行预算和选择规则冻结后再释放 C。C 若由另一 agent 整理，只能称为操作上的答案隔离；共享操作者和组织不能被改称独立认证的 custody。

| 实验 | 当前来源允许的进展 | 仍缺什么 |
| --- | --- | --- |
| E1 | 暴露开发任务上的轨迹/答案训练和语义执行准备 | 未见来源、未来时间、真实 coding-agent 轨迹及足够独立任务 |
| E2 | 持续同一 SQLite 状态的实际动作与业务回执接口 | 真正学生生成、受控执行、失败后修正和与示范/影子预测的匹配比较 |
| E3 | 一种脚本教师来源已被明确标记 | 多个实际外部教师及准确身份、相同任务和成本约束 |
| E4 | 可保留动作和成本的局部环境 | 实际 Cell/边连接、匹配活动参数与成本的比较、逐 Cell/逐边消融 |
| E5 | 一个标准化 SQLite 家族的开发数据 | 经认证并去重的真实来源群；不能把现有材料扩写成 1/4/16/64 个用户 |
| E6 | 原候选发布/使用组件的明确历史边界 | 同一次真实 A、独立 B、原 Selector、全新 C、原 owner 与真实进程冷恢复 |

用户对本轮仓库审计和实验的指令授权了这些指定材料的读取与隔离开发执行；它不自动提供外部私人轨迹的训练许可、第三方模型条款资格或原生产 owner 的签名能力。未取得的来源、用户、授权、费用和阶段证明继续标为未知或缺失。当前可以继续开发和测量，尚不能据此声称用户增长收益、真实采用、proof-of-useful-work 或新 foundation model 已成立。
