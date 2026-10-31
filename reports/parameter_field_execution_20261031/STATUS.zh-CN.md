# 五项研究目标的执行状态，2026-10-31

## 已完成与未完成

本次完成了两阶段增量实现、独立交叉审查、21 项本地合成测试、未获准入口拒绝检查，以及原实验输入和资源恢复检查。P0 阶段已提交为 PR #4522，提交 `518fa5e4445b7085f23ccbe6c8b3f56a13ca4f1a`；其 GitHub Actions run `41200153294` 已成功完成。统一入口的后续阶段及本报告与同一提交栈一起交付，独立 CI 状态应以实际 Actions run 为准。

**原 execution06 全量科学执行仍未启动。本次新增科学 worker、训练微步、独立样本和 stage ACK 均为零。** 旧 A17 的继承不能计为本次新实验。工程通过没有填补五个问题的实证结论，原 V4/V5 的阴性或未定证据、历史失败和未知成本均保留。

| 用户优先级与问题 | 已交付的具体工作 | 尚缺的实证范围 |
| --- | --- | --- |
| P0：field 改善真实更新 | 将 A 实际 gated 选择接到完整同 parent 后继；分别报告请求、guard 接受、物理状态相等、参数/optimizer 组件变化和原数值范数。 | 原完整研究的真实执行、独立终点和成本闭环；动作活动本身不等于正收益。 |
| P0：advantage 是否可靠 | 补 C 48 行 gated calibration、严格 threshold/tie、实际 regret、attainable gain、配对标签及完整 baseline-tail 链。 | 校准行参与过 threshold 选择且存在依赖；它们不是新的 deployment-distribution 校准保证。 |
| P1：field 是否保留必要信息 | 原 history/full-current-state 比较和 W 诊断保留，新增解释限制。 | 真实结果、可达性/占用分布证据；学习出的 full-state ridge 不是信息 oracle。 |
| P1：解析 cell 额外贡献 | 原 C 两个 simple effects、interaction、跨架构比较和四项 retention 全部保留；正交互但双负简单效应有单独分类。 | 原 C 全部测试种子的真实结果；有限解析事件律对照不能外推为完整 Hepta/NDU 优势。 |
| P1：值得采用的系统能力 | 原 ordinary/taper 对照、当前已声明成本覆盖审计与统一解释入口已连接。 | 新任务族、规模验证、部署活动和完整历史/摊销成本；当前同任务新 schedule/source-pair 不能替代跨任务外推。 |

## 科学身份与分析入口

原科学提交仍为 `bc4e757f5c90f6365f383c1127be710d2ded874a`，原分析扩展基线为 `800f34f4a869c83d6f6b33d96b7153daa0fa6e97`。本次没有更改原协议、冻结科学源码、样本、动作、baseline、训练预算、bootstrap、阈值或既有结果。

新增统一入口为 `supplements.parameter_field_execution_20261031.run_review`。它需要真实原 review completion 和外部持有的 SHA256，重新进入原全量 source/seal/literal-restore gate 后，才读取科学 payload。缺少凭据的实际 smoke check 返回 `2 / NOT_EVALUATED`。

新增源码身份见 [SOURCE_IDENTITIES.json](../../supplements/parameter_field_execution_20261031/SOURCE_IDENTITIES.json)，使用方式及解释范围见 [README](../../supplements/parameter_field_execution_20261031/README.md)。它不替代原 REVIEW、aggregate、statistical gates，也不声称原训练已安装新 finite-head overlay。

## 本次工程验证

- [本地测试凭据](synthetic_tests.json)及[完整日志](synthetic_tests.log)：21/21，退出 0；合成算术及证据边界测试，未读取真实科学 payload。
- [未获准 CLI 检查](unadmitted_cli.json)：正确拒绝，未解码科学数据。
- [仓库格式命令](format.json)：`just fmt` 退出 0；当前 formatter 不负责 supplements 目录，不能据此声称 Python 格式器验证。
- [依赖恢复凭据](dependency_materialization.json)：两个本地下载文件仅去除多余终末换行，AST 及位置完全相同，恢复到既有基线的准确 Git blob；它们不作为改动上传。
- P0、P1、统一入口均经过另一位审阅者检查；真实科学结论仍须等待原全流程封存。

## 全局 CI 与本次文档修正

本次两个专用 CI 已分别实际通过：[P0 9 项](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41200153294)及[完整增量 21 项](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41200449604)。后者验证提交 `0c017a9dab2ed770a1e3557e30d56c9b42bd3ac5` 的实际代码；随后修正仅涉及文档和新增核验记录，六个 Python 实现/测试文件保持不变。

同一提交的仓库全局检查没有全部通过。v8-canary 成功；Codespell 和 architecture source-head 失败。精确归因见 [spelling 证据](global_ci_inherited_findings.json)及[锁文件评估](lock_reconciliation_assessment.json)。

Codespell 实际输出 29 次诊断：9 次已登记历史诊断、18 次继承未登记诊断，以及本次两个中文文档中的技术缩写误报。本次只把这两处新增缩写改成准确的中文表述。其余 27 次诊断所在 18 个文件的 base/head Git blob 完全一致。现有精确登记器同时约束单一历史来源、完整 inventory digest 和逐条 multiplicity，不能只追加 JSON 就接纳后续冻结材料；本次没有修改该检查规则或原科学文字。修正后的实际 CI 状态应读取新 run，不把预计的 27 次诊断当作已经重测。

架构 source-head 的原 Cargo 锁与既有 manifests 不一致。已找到准确输入匹配、实际生成成功的旧 artifact，但其候选还包含兼容范围内的额外生产依赖重选，原产物自身保留 `dependency_graph_approved=false`。本次保存候选来源与差异审查，不把该候选直接覆盖到研究分支，也不把 x86_64 的 metadata 成功当作当前 arm64 或整个系统资格通过。两个 PR 保持 draft；专用合成测试通过不等于全仓库可合并。

## 原实验恢复与资源阻塞

[静态恢复核验](../restored_inputs_static_verification_20261031.json)确认九个原始模型/数据/observer 文件 SHA256 均一致，Python build 和十项包 metadata 与冻结记录匹配。原配置的 21 个直接 descriptor 均匹配。此项检查未 import Torch，**不等于重新取得动态 runtime digest**。

已按[清理凭据](../cache_cleanup_20261031.json)移除九处已核实的可重建编译缓存，释放 1,421,053,952 B；未删除科学输入、RAW、既有失败或验收证据。随后按原 `supervisor.capacity()`、原 10 秒间隔取得三次样本，见[资源凭据](resource_readiness.json)：

| 项目 | 三次实测范围 | 原门槛 |
| --- | --- | --- |
| 有效可用 RAM | 607,387,648–625,033,216 B | 1,879,048,192 B |
| 可用磁盘 | 1,686,994,944–1,687,048,192 B | 2,415,919,104 B |
| RAM 与磁盘联合通过 | 0/3 | 连续 3/3 |

OOM/kill 计数在三次观察内保持 41/9；这是共享环境累计值，不能归因于本次研究。前后均没有 execution06 启动标记。本次没有消耗原登记科学窗口，也没有启动一个无人处理 17 道 durable ACK 的后台研究。

12:18:54 UTC 的追加单次必要条件检查仍不通过：有效可用内存 716,984,320 B、可用磁盘 1,384,656,896 B，启动标记仍为空。该单次复查不替代原三次连续 admission。

[干净文件缓存检查](clean_page_cache_inventory.json)仅查询本项目 103 个大型文件的内核页驻留元数据，未读取 payload；所报告驻留约 53 MB，不能解决缺口，因此没有执行缓存驱逐。[旧 archive 退役检查](archive_retirement_readonly_audit.json)确认 execution04 可退役大副本已不在；execution05 虽有约 129 MB 回读副本，但失败 episode、已有结果及 inode 变化均不满足原退役入口，未删除。公开报告省略私有服务对象身份，原收据未修改。

## 可用 CI 与全研究 executor 的区别

标准 GitHub Actions runner 已实际运行并通过 P0 工程测试，不能笼统表述为没有外部计算资源。[迁移评估](runtime_migration_assessment.json)列出全研究还需要满足的真实条件：原完整 Python build、Torch build/AVX512 与状态绑定 digest，完整 A17/失败成本证据，原容量和进程计量语义，以及实际每阶段上传、独立回读、ACK 和终封闭。

当前已记录精确 Torch wheel 和包 pins，但没有找到原托管 Python build 的完整公共下载配方；复制 venv 本身只会留下绝对 symlink。新 operational registration 可以记录新路径和进程，不能使一个不同 runtime 自动兼容原 A17，也不能用普通 CI artifact 替代原 durable ACK。尚未证明另一个可直接接续原研究的 executor。

下一科学动作仍是：在真正满足原资源与 runtime 条件的已登记 executor 上，运行原入口并完整处理全部封存/回读门；随后使用已登记的新增解释层。若必须换 runtime，应明确作为新的科学 provenance 决策登记，不能静默改写原 digest 或混接历史结果。
