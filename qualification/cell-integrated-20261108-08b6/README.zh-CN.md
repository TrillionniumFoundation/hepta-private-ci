# Cell 共同候选与独立实验：08b6

本目录把同一条提交链的工程候选、实际受测源码、完整源码归档和独立 PRED-1 研究分开记录。**当前科学与生产资格保持 HOLD；普通任务学习闭环尚未完成。**

## 唯一来源与发布边界

候选从 `b040333617ed493944ae028bfb502c94d3b10991`（tree `08e4b2962ad42dfdb544719b5837407bde31498a`）的唯一子提交 `f2b178bff6955647738d895450d97d229a816b24`（tree `a772e5d3f1a90958bad2f56f02a7e72523553652`）继续开发。f2b 提供实际训练调用点的 admission、结果校验与只读恢复；本轮补上父进程监督、完整归档比对和训练／开发诊断。

本轮不把 #5346、#5358、#5357 或其他活动工作树的测试成绩计作本候选成绩。其他分支的 ingress、签名、终局学习与分层机制，只能作为下一阶段评审输入。

| 身份 | 固定规则 |
|---|---|
| 源码发布 ref | `engineering/cell-integrated-20261108-08b6`；最终验证前冻结，发布后以 GitHub readback 核对完整 commit/tree |
| 实际受测源码 | 原生独立干净工作树的完整 commit/tree；测试前后必须一致，不用仅源文件相同替代完整树身份 |
| 归档源码 | 对上述受测 commit 生成完整 tar；逐 tracked blob、Git 类型、可执行分类和符号链接比对，另记归档 bytes/SHA-256 |
| 实际验证配置 | `VALIDATION_PROFILE.json`；实际解释器、包版本、线程环境、命令、限制和成本另记原始回执 |
| 证据发布 ref | `engineering/cell-integrated-20261108-08b6-evidence`；只追加观察记录，不能冒充受测源码 ref |
| 完整学习运行配置 | 尚未具备；缺少生产 owner、受保护 CAS、独立 holdout custody 和真实下一任务绑定，不以本验证配置替代 |

源码提交不能包含自己的最终 commit SHA 和事后测试回执。因此观察记录放在单独证据 ref；该 ref 的 commit/tree 与源码 ref 必须分别展示。代码和协议先冻结，执行结果随后记录。

## 本轮实现

`pipeline.run_training_job` 已接入真实子进程 supervisor。stdout/stderr 独占创建、流式写入，每路上限 8 MiB；独立 POSIX 进程组、原始 wait 身份、最后组清理和实际退出码分别记录。原 660 秒外层预算不增加，1 秒清理预留从执行时间中扣除。超时、输出超限、持管或 I/O 异常不会伪装成某个退出码；无法完全观察的清理保持 unresolved，同一 operation 不自动重跑。

新 admission 独立绑定 supervision policy 和父进程代码字节，旧 trainer/model lineage 不改。新 completed 回执必须与 supervision 相符；旧 v2 admission 没有该增量字段时，保留原只读核验语义。该实现依赖 POSIX waitid/WNOWAIT，不覆盖脱离进程组的后代或 supervisor 自身掉电；这些仍要求外部持久 owner。

`scripts/hepta_source_archive.py` 比较完整归档与干净 Git 树，包括遗漏、重复、额外路径、内容、可执行分类和链接。`export-ignore` 或 `export-subst` 造成的差异会拒绝。该结果只证明完整性，不认证测试执行、发布、配置实际使用或科学收益。CLI 和边界见 `ARCHIVE_INTEGRITY.md`。

`scripts/hepta_pred1/diagnose_training.py` 只读取明确列举的训练／开发元数据与归档 runner 源码，拒绝确认结果、非有限数字、不完整成本、路径替换和超限输入。源码按语法分析，不导入执行；checkpoint SHA 仅作为已声明元数据，不冒充权重核验。

## 共同验证门禁

本轮 Python 门禁在同一个最终候选上执行，共要求 **74 项测试、零跳过**：23 项共同配置、6 项状态恢复、18 项训练结果和监督、13 项完整归档、14 项训练／开发诊断。CI 对该源码分支启用同样增量测试，并保留既有 native owner、lint 和组合门禁；没有通过删掉失败测试取得资格。

```bash
PYTHONPATH=scripts:. PYTHONDONTWRITEBYTECODE=1 \
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
VECLIB_MAXIMUM_THREADS=1 python -B -m unittest -v \
  test_hepta_cell_joint_config ndu_real_runtime.test_state_codec \
  ndu_real_runtime.test_subprocess_supervisor \
  ndu_real_runtime.test_training_job_result test_hepta_source_archive \
  hepta_pred1.test_diagnose_training
```

实际解释器必须符合验证配置。工程测试中的模型／协议 fixture 不作为真实学习 fit 或生产采用证据。native/CI 的最终退出状态、跳过与筛选分母只以对应 head 的原始回执为准。

## PRED-1：保留历史 HOLD，单独确认

原 48 份训练记录消费 46,080 个 optimizer steps、5,898,240 次训练样本呈现。被选择 checkpoint 的 21,088 步不是实际训练成本。seed 202 的 GRU 在第 30 epoch 取得最佳开发 NLL，第 20→30 epoch 开发 NLL 改善约 0.032138；其他四个原评价训练种子的最佳 epoch 为 13、11、13、13。源码同时用 seed 控制数据和初始化、seed+911 控制批次次序，因此无法把差异因果归于其中一个因素。

原确认结论不变。新方案冻结 16 个与原确认种子不重叠的种子、三枚既有家族选择种子、六个 arm、114 次 fit、109,440 optimizer steps、14,008,320 次训练样本呈现；主统计单位是 16 个独立训练种子，不是 98,304 次模型 episode 评价。采用固定均值增益阈值与 exact paired sign-flip 检验，不删失败 seed，不换 seed，不按确认结果提前停止。

`pred1/training-dev-inputs.tar.gz` 包含原 11 个 Python 源码、48 份训练元数据和冻结协议，**不含旧确认结果或 checkpoint 权重**。`pred1/guard-supplement-001.tar.gz` 保存单独冻结的执行 guard、13 项纯控制测试和执行补充说明；归档中的源码不格式化、不改写。原研究 runner 与本轮集成源码是不同身份。

| 冻结对象 | SHA-256 |
|---|---|
| 原独立方案 FREEZE | `19e6d61565d7d8fadf695a9a5814819197ac98835c80ad19d162e61db846b724` |
| 新 registered config | `c3574166b2043e3e4b4ac167e35f81a1003ff8d916a4f446010bf6a94ec77667` |
| 输入包 | `3611e8f2032e28abe9ee2b77c7650d16d12aed20eb79d0c2987c0b2db4c91129` |
| 执行 guard | `099b6272c981e87a078c3962f138334539b6d76a4cbd93a156ffe87ec066b17c` |
| 执行补充说明 | `2d5d197b4825de1951f0301c6c59bed5ec849eebe0fa1c2d167985580626d37d` |

执行前先将两个 tar.gz 分别解包到新建目录；原 `pred1/REPRODUCE.md` 中的交付布局需按该映射指定路径。实际过程使用 Python 3.12、NumPy 2.3.5、单 BLAS/OMP 线程；guard 在首次确认数据生成前检查 GRU 家族、全部 114 个 checkpoint 的实际字节、训练记录、源码和配置。训练／确认总墙时、CPU、依赖准备、失败、环境修复分别保留；费用、能耗或缺失的恢复计量不能填零。

即使独立模拟实验通过，它也不证明记忆—决策—验证组合的真实任务收益，不产生生产采用权限，不推进 S0。实际结果和失败记录在证据 ref 上单独发布。

## 下一阶段与当前阻断

`PRODUCTION_GAPS.zh-CN.md` 记录本候选的实际 owner 与启动接线核查、可复用 API、缺少的能力对象，以及普通任务→学习 outbox→独立评价→采用或 NoUpdate→下一任务的依赖顺序。完整 native 搜索回执随证据 ref 保存。

MEM-1、VERIFY-1、NDU 和 HCSN 的下一实验需要先冻结真实任务与独立数据来源；设计说明与缺少的输入会单独记录。未取得固定图上的稳定一阶收益前，不把 Cell 分裂合并、技能层级、学习规则变化或改进器继承合入这次科学归因。
