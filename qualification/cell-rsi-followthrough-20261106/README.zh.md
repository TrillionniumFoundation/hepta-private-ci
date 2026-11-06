# Cell RSI P0–P5：本次恢复修复与证据核对

基底为 [#4935](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4935) 的固定提交 `9f73f82ca7454d9d00e4fc71af43fdffba14c5e3`。本次交付修复 Memory 运行记录和恢复记账，保留原实验、模型、owner、采用门及历史证据。本文的阶段编号对应用户的产品 / Cell RSI 目标。

## 当前结论

| 阶段 | 本次可验证进展 | 尚未达到的完成条件 |
|---|---|---|
| P0 统一候选 | 固定来源、逐模块冲突与身份要求已形成具体归并规格；#4935 修复有独立测试 | 尚未组装一个产品 / resident / Cell / HCSN 共同候选，不能拼接 donor 通过数 |
| P1 Memory 正向闭环 | 恢复验证与 phase 等待 / 记账修复，本地 23/23 测试通过 | 原候选历史任务由 59/72 降至 55/72，仍不采用；没有采用后重启并用于下一真实任务 |
| P2 联合计算与恢复 | 核回 HCSN `bbe995c` 两个成功作业和原始 artifact，保留真实 worker / 块间状态 / 取消恢复进展 | 普通产品 daemon、AuthBus ingress、独立托管身份及优化阶段取消证据仍未完成 |
| P3 分化收益 | 对原 11,520 条测试记录及全部 10 trials 做只读审计，发现强对照不匹配 | 同容量、同完整预算、同选择性更新的固定专家及不分裂对照尚不满足，HOLD |
| P4 递归效率 | 明确与分化、恢复的工程通过分开判断 | 没有同初始系统 / 完整预算、多种子、未见任务下新改进器稳定胜出证据 |
| P5 规模与持续服务 | 保留既有 HCSN / resident 工程来源与预算 | 没有同一候选的质量、p99、吞吐、RAM/VRAM、恢复、状态增长和真实成本联合通过 |

`authority=DENY_ALL` 用于这些研究与审计结论。本次没有模型加载、优化更新、候选采用、生产部署，也没有重复启动既有 CUDA campaign。

## 修复一：恢复必须核回原始 worker 记录

原驱动仅核保存的结果摘要，存在将 `False` / `0.0` 当作整数零退出码、修改摘要提升失败、没有原 stdout/stderr 仍接受完成，以及汇总未访问 phase 的风险。本次先在原驱动复现反例，再加入同一个严格 verifier，供 resume 与最后汇总共同使用。

新的验证绑定冻结协议、phase、完整 worker result、原始 stdout/stderr 字节数及 SHA256、正整数 PID 和进程实例 ID；拒绝重复 JSON 键、非有限值和含糊类型。已有 attempt 或 TRAINING_STARTED 标记缺少可核完成记录时，保留未知与既有成本，不自动再做一次模型任务。它是本地记录一致性检查，不是密码学 authority 或候选采用门。

原始反例与修复测试见 `../cell-learning-loop-v1/receipt_validation_20261106/`。本次新模块参与源冻结；旧冻结源码实验不会被静默续跑。

## 修复二：phase 有时限，未知成本不能变成零

原 `decision_replay/run_replay.py` 的阻塞 `wait4(pid, 0)` 不能由子进程 CPU 限额限制 I/O 卡住。本次每个 phase 冻结 60 秒观察期限，发起终止请求后另有 5 秒回收观察预算；只观察本次直接子进程，超过期限请求终止其进程组。

发起前先登记未知 attempt。已回收状态、实际退出码、CPU、RSS、超时及信号 / 等待 / 日志异常均保留；缺失成本保持 null。晚于原期限才观察到退出零仍算超时。丢失等待所有权后不向可能重用的 PID 发信号，回收后也不发信号。任何错误或不确定结果阻断后续 phase 和采用，原质量门不变。

该期限仅覆盖子 phase 的等待与回收。外层 `measure.py`、准备步骤以及文件系统 I/O 没有获得全驱动硬期限；不能据此宣称整个服务有界或 p99 已达标。

## 本次实际验证

`validation/RESULTS.json` 记录实际命令、退出码、原日志哈希及八个实现 / 测试文件的字节哈希。

| 范围 | 实际结果 | 能说明什么 |
|---|---|---|
| Memory receipts | 13 passed，0 skipped | 原始记录绑定、拒绝含糊 / 篡改 / 缺失记录、未知 attempt 不重放 |
| phase process 与真实 caller | 10 passed，0 skipped | 成功 / 失败 / timeout / 丢失等待 / 信号与 fsync 异常，以及派发失败落盘和后续停止 |
| 合计 | 23 passed，0 skipped | 本次 Python 恢复修复的行为；不包含真实模型或 native worker 运行 |

按仓库要求执行 `just fmt` 返回成功，输出为无须格式化的变更；该 recipe 不覆盖本次 qualification Python，不能把它算作 Python 风格校验。没有 Rust 源码修改，也没有在本地缺失 Rust toolchain 的情况下声称跑过 native 门。

新增 `.github/workflows/hepta-cell-receipt-recovery.yml` 对 PR 实际 head 跑同一组 23 项测试，保留 source/tree 与原日志，检查运行后跟踪源码和旧证据不变。远程结果以该 PR 的实际 Actions 回执为准，不能沿用 #4935 的旧 native 结果。

## P1 原实验为什么仍未采用

原候选是同一 MiniLM 父模型从 step 240 到 256 的一次 16 更新：288 次训练呈现、124 个唯一行。手工纠错任务 0/2 → 2/2，但历史任务 59/72 → 55/72，包含 5 个回退与 1 个改善。原运行的冻结 callback 因缺少完整九臂和成本证据而固定拒绝，不能写成原门动态发现了 retention delta。后续独立 decision replay 才用原候选结果触发动态 retention veto，未新增训练；父模型保持 epoch 1。

未发布候选的 cold shadow 下一任务正确，不等于采用、重启后被普通入口实际使用。后续来源修订也使原 release 被 fence。恢复修复没有放宽这些约束，没有把手工任务改称自然新任务。

## P0 的具体审批边界

自动审批审核先拒绝获取 #4963 执行 checkout，后拒绝将 #4938 merge 到当前 #4935 基底；审核将可执行范围限定在 #4935，其他分支只读。被拒后没有 donor merge、构建或采用；工作树确认没有 MERGE_HEAD 或半合并状态。

`P0-CANDIDATE-INTEGRATION-SPEC.md` 给出固定 donor SHA、必须合并的 owner / artifact / role / intent / checkpoint 语义，以及最终树的必要门。`P0-SOURCE-REVIEW.json` 保存 27 个只读 Rust 快照的原 Git blob 和 SHA256。后续需要明确准许在隔离候选中整合 #4938、#4944、#4963、#5067 与产品 #4855，并执行必要构建和测试；这些审阅材料本身没有执行权限。

## 原始资料与完整交付包

`P3-AUDIT-SUMMARY.json` 和 `P3-FAIRNESS.zh.md` 是新附录，不覆盖旧报告。完整 `hepta-cell-rsi-20261106.zip` 包含已提交恢复源码 / patch / 日志及 P0 规格的固定 GitHub 链接和哈希、P0 来源审阅记录、P3 审计程序 / 16 项测试 / 全量报告 / 原档案，以及 HCSN 两个原始 ZIP 与独立审计。仓库已有的源码与文档由固定 commit 提供；离线复核所需的冻结来源以原始证据附件明确标识，不作为第二份工作仓库。

包内另外保留 HCSN optimizer-entry 待审 patch：仅在第一次真实梯度返回、第一次参数更新之前写入可核阶段记录。其纯 stdlib 10 项测试通过，但尚未合入、Rust 编译或跑 native / 模型测试；它不构成 `optimizer_entry_proven=true` 的回执。完整交付包的最终文件清单与哈希用于复核，不能代替产品资格。
