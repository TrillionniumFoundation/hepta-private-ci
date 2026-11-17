# E1–E6 下一轮来源接入

## 本次新增结果

本次核查两仓 11 月 16 日以来的新 issue、全部开放 issue 元数据、11 月 17 日以来全部 151 个 PR 元数据，并读回两个 main 的固定身份。Hepta 新 issue 和开放 issue 均为 0；Chain 新 issue 为 0，开放 issue 为 20。Chain 开放 issue 涉及三个账户，其中一个是 github-actions[bot]；另外两个账户不等于已认证的两个独立人类用户。全部 151 个 PR 来自 ProfHepta，其中包括上轮分段发布，PR 数不增加任务、来源或用户数。

main 仍为 Hepta `732e934ba496d90fbe042b8d41d479ef901643e5`、Chain `59bd6ae4223caff6695dc9cf2ee2cdcdc6df5e88`。各次查询并非原子快照；时间、查询 URL、范围和投影后的字段保存在 SOURCE_OBSERVATIONS_03.jsonl。该文件保存 API 字段投影，不冒称原始 HTTP 字节。

## 一个新检索到的历史需求

[Chain #150](https://github.com/TrillionniumFoundation/Trillionnium-Chain/issues/150) 是此前三-issue 来源清单未列出的标准候选验证需求。原事件时间为 2026-09-13T09:30:33Z，作者账户为 ProfHepta / 102159240。候选 commit `e6464bb48d43468fbd90ea6531f378246801a9f3` 和 tree `abb45c3f35f0f9758756f47a9bed43a3e6da0331` 已通过 GitHub GET 核对；toolchain 和功能开关也有真实 manifest。测试文件的 Git blob 身份已取得，但测试正文和修复 patch 没有读取，也没有运行测试。

该项可以进入“历史真实需求的隔离验证入口”。它与此前 #786 派生族分开登记，仍属于同一账户和同一项目，原发生时间早于本研究，不能称未来 C。该 issue 原文说明的是已有候选的验证需求，不能重写成后来发生的新 bug 报告。当前还缺教师动作轨迹、完整环境与执行原件、实际验收和数据切分；因此只是一个未分配的任务候选，正式训练记录仍为 0。账户范围内是否曾在其他会话曝光也未知。

[Chain #68](https://github.com/TrillionniumFoundation/Trillionnium-Chain/issues/68) 要求外部多操作者、设备和持续验收，不是首批局部可复位 coding 任务；作者不同也不能替代真实动作轨迹。[Chain #118](https://github.com/TrillionniumFoundation/Trillionnium-Chain/issues/118) 要求跨仓组件 owner 接受，当前没有独立的输入、环境和业务 oracle，暂不纳入。

## 立即可复用的执行环境

已有的三个 SQLite development 场景仍可接入更新后学生的受控执行：

`cell_experiments.repo_tasks_v3_sqlite.DevelopmentSession(task_id, new_output_directory)`

它们全部保留 `derived:chain-786-workstream-3:act2-sqlite-family`，重放不增加 N。环境真实执行 SQLite 动作，但 actor 只选择 inspect/stage/apply/stop，payload 由环境提供。这个接口适合开发 E2 状态偏离与恢复，不能被描述为学生编写通用 SQL 或完成开放式仓库修复。本次没有再次执行该环境。

## 可运行的接入示例

`intake_existing_data.py` 直接复用现有 `scripts/cell_experiments/data.py`，没有另建一套数据验证框架。它先核对现有模块的 SHA，再计算实际清单计数；仅在显式提供已批准的 train-only JSONL 时调用 `load_records` 和 `build_sft_examples`。不选择 B/C，不运行模型或业务 verifier，不把结构通过当作来源认证。B/C 必须是独立文件，不能拿含保留答案的混合文件试探训练入口。

无新原始轨迹时可以直接运行：

```sh
python3 -B intake_existing_data.py \
  --inventory SOURCE_INTAKE_03.json \
  --observations SOURCE_OBSERVATIONS_03.jsonl \
  --repository-root /path/to/reviewed/hepta-checkout \
  --output-new /new/path/INTAKE_READOUT.json
```

该路径产生 INPUT_REQUIRED，退出码 2，正式训练记录 0。这是如实报告缺少输入，不是任务成功率或实验通过。

以后已有真实、授权、单独冻结的 A 轨迹时，增加 `--train-records /path/to/approved-A.jsonl --mode trajectory`；答案对照使用 `--mode final_answer`。示例只准备训练输入；正式 runner 仍需核验所有原始回执、隔离权限和实际资源预算。该示例没有认证外部来源的权限。

### 纳入记录前应保存的原件和字段

- 原 request/issue 的 URI、完整原件、真实事件时间、可用时间；导出时间另记，不能制造未来任务。
- task、lineage、family、project、source 身份，父子分支与近重复关系。
- 明确训练与评估授权范围；环境/source/target 的固定身份及可重置方式。
- 可见、有顺序的 action / observation / correction；失败、取消、超时和未知状态原样保留。
- 教师模型版本和原始 request/output；教师非空时，提供 model_digest、teacher_output_receipt_sha256 及各 teacher event 的 receipt_sha256。
- 学生执行事件提供真实 policy_sha256、receipt_sha256、receipt_actor=student；影子预测不得设置 executed=true。
- 已注册语义 verifier 的 name/version/parameters、真实业务结果和完整验证回执；语法通过不能代替。
- final_answer 与成功任务绑定；未成功尝试仍保留在原经验日志，不能伪装成正向 SFT。
- 在训练前冻结 source/time 切分。当前 intake 没有替你分配 A/B/C，也没有生成新的 C。

SOURCE_INTAKE_03.json 已逐字段列出 `hepta.cell-experiments.record.v1` 所需字段及缺口。该 schema 会校验结构、组间重复和时间声明；其通过仍不能认证来源真实性或评价独立性。

## 教师材料现状

保留模型材料能够固定 Qwen/Qwen2.5-Coder-1.5B-Instruct 的 revision `2e1fd397ee46e1388853d2af2c993145b0f1098a`，权重 3,087,467,144 B，SHA256 `c1b9b30e907950516ba3c646bdf570d8084c25a6410a0cdca80cf04b11bc13a8`。Smol 的旧 parent freeze 也有 model digest。它们当前是本研究的既有模型／学生身份，本次没有产生新任务的教师输出，也未把旧 manifest 当成实时模型服务观察。

ACT-2 的 B1_macro 是一种脚本参考策略；换种子、换 arm 名称或派生 adapter 不增加外部教师。Qwen、Smol 或其他既有服务若随后承担教师角色，需要各自真实生成、成本和业务结果，之后才能做 E3 的同任务对照。

## 结果范围

本次没有 Git/API 写入、模型调用、训练、业务 verifier 调用或生产操作。只创建了新的来源清单、接入示例和实际输入检查记录；原包、原数据与原失败没有修改。新确认集、用户增长收益、E3 教师互补及 E6 采用资格仍未由本清单建立。root 可据此继续当前学生执行与 Circuit 开发，不需要等待本清单假装有新来源。
