# 原 CPU 连续性诊断：冻结产物与运行时修复

## 本次修复

源码基于 `ce6b9fe9dcb7d6bb8e78978c8b81a001ac7e2ea2`。
工作流只调整两处 runner 为 `ubuntu-24.04`，并将安装版本恢复为原独立 CPU profile 要求的 `torch==2.8.0+cpu`。
Python 3.12.3、NumPy 2.3.5、mpmath 1.3.0、原 worker/helpers、两 worker、每 worker 一线程、600/660 秒、8 GiB 和失败拒绝条件均保留。
原 `CPU-ARTIFACT.json` 的 MISSING 已被原产物出版和完整字节核验推翻，本次精确指向原 immutable commit `917e4886658ae9f0c342eb1fa0f545d79c39e2c8`。
没有更换原 archive、冻结模型 checkpoint、数据、种子或科学判据。

## 原产物实际核验

原 archive 为 11,397,159 字节，SHA256 `37d387507ec150abfdad4065c23612e18fca6643d489f3555874c8e57a514b75`。
重新计算的 Git blob 为 `2afc4e810f1c75a1ff5b9fb85464f6dda6c43245`，与原提交的路径元数据一致。
Git API 的两次下载均发生 HTTP/2 CANCEL；原 FAILED 回执、stderr 和不完整响应全部保留，未改写为下载成功。
后续只读核验使用仍在 desktop 上的同一原 ZIP，核验前后身份保持不变。
实际核验 556 个安全、唯一的普通 ZIP 成员：555 个原文件及 INDEX；每个文件 SHA256/CRC 均相符。
原 PREEXECUTION 与全部 555 项输入绑定精确相符，六个 checkpoint 及各自 37 份模型源码的字节身份均已核对。
checkpoint 只作字节核对，没有解释 pickle、加载 Torch 或执行模型。
唯一 native custody 结果为 `PASS_ORIGINAL_ARCHIVE_CUSTODY`，wall 0.470607036 秒、CPU 0.470572432 秒。
原 RESULT SHA256 为 `22078f6f20c2a21ee2a8e68e5309118617e1aeaf537bdd0265d517446c9505c8`。

## CPU profile 与完整训练预算的范围纠正

原 PR #6130、#6188 登记的是六个后期 checkpoint 的两步连续性诊断及两个负对照。
一次完整成功的该诊断核计 26 次 optimizer 调用；新增独立完整训练重放仍为 0。
原 PR #6362 的 current-budget admission 针对 46/47 epoch 父状态的 six-fit 完整训练重放，不能用来否决另行登记的短诊断。
本轮曾制作并机械验证了一个要求该完整训练门禁的候选：7 项 stdlib 检查通过，但适用范围过宽。
该候选从未发布为活动源码；本次明确撤回该设计。原候选、注册、执行日志和 PASS 结果仍在归档中，不删除，也不冒充有效资源授权。
原完整训练 admission 继续 HOLD；E1–E6 的 16/16 训练额度及 E6 compile 剩余额度均不变。

此前 52 次已核诊断调用来自 4092 与 d706 两个原 attempt，各 26 次。
两者均是 Python 3.12.3 / Torch 2.8.0+cu128 在 CPU 上执行，不能充当本次 2.8.0+cpu 独立 profile 的成功证据。
每个旧 attempt 内均为六组 reference/resume 完整状态一致；不同 attempt 的六个 semantic SHA 不相同，不作跨 attempt 同一状态声明。
历史被中断的原 controller lifetime 总调用数仍为 UNKNOWN，本次不改写这个事实。

## 本次普通 push 的执行边界

本分支仅发布一次，不创建重复 PR，不 dispatch、重跑或取消 CI。
原 CPU workflow 按普通 push 执行；精确 source head、pointer、artifact commit、运行环境与每个 worker 回执必须从新 run 读取。
26 次只描述 CPU recovery lane 的完整成功诊断，不是整个 push 所有 CI 的总调用数。
原路径触发器还会触发独立的 differentiable source/event CI；其测试、模型调用和结果另行记录，不沿用旧九次 fixture 更新作计数。
若 worker 没有完整回执，其实际 optimizer 调用按原规则记 UNKNOWN，不自动再次执行。
本次发布时尚无新 CPU 诊断的终态，不能预写成功。源码和原 custody 成功不等于新运行已完成。

## 证据包与只读复核

`CPU_ORIGINAL_CUSTODY_01.tar.xz` 保留原 INDEX、PREEXECUTION、完整成员核验表、实际 RESULT 和独立 auditor。
`CPU_DOWNLOAD_FAILURES_01.index.json` 指定两段失败下载归档的连接顺序与整体 SHA256；归档内 MEMBERS.json 含完整原文件清单。
`CPU_SCOPE_AND_SOURCE_01.index.json` 指定来源、原 profile/PR、52 次分账、修复候选及已撤回门禁的原始材料。
先按各索引核对字节数和 SHA256；分段档案必须按 orderedparts 原顺序连接后再解包到新空目录。
原回执中的路径、失败状态和历史 README 均原样保留；当前结论以本说明和独立 scope review 为准。
原 11.4 MB checkpoint ZIP 已在固定 Git commit，不在本分支复制一份，也不需要重跑诊断来复核 custody。

## 资格状态

本次消除的是产物定位、runner 漂移及安装版本与原 profile 不一致三个工程阻塞。
新 CPU run 的真实连续性、负对照和 hosted CI 仍须读取实际结果。
任何该诊断的成功只适用于固定 checkpoint 与短轨迹；原科学状态 `HOLD_NO_GO`、完整训练重放资格与全仓资格不由此改变。
