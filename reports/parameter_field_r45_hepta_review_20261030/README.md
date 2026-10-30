# R45 参数场论文与 Hepta：理论评论、判定矩阵与发布凭据

公开副本准备时间：**2026-10-29 23:19:18 EDT**（2026-10-30T03:19:18.293347+00:00）。公开副本的人类可见日期使用 America/New_York；机器时间、原 commit 历史日期及登记路径／episode 身份沿用原值。本目录的执行状态观察固定在 **2026-10-29 23:13:29 America/New_York**（2026-10-30T03:13:29+00:00）。

这里保存对 R45 论文及冻结 Hepta 实现的源码审阅、五项优先级的判定说明，以及已完成的源码发布凭据。实验效果仍须由已登记的完整执行产生；本文的实验分母均为计划人口。

## 文件与范围

- [THEORY_TO_HEPTA_REVIEW.md](THEORY_TO_HEPTA_REVIEW.md)：理论评论的科学正文保持原样，仅将审阅日期按 America/New_York 显示；覆盖完整 optimizer state、closure、决策信息、actuation、advantage、系数误差、成本与架构交互的适用条件。
- [DECISION_MATRIX_DRAFT.zh-CN.md](DECISION_MATRIX_DRAFT.zh-CN.md)：原判定矩阵的公开副本，仅更新两段操作状态，并按 America/New_York 显示编制日期。科学解释、统计阈值、数据分割、动作空间、计划分母及原有阴性结案规则保持原文。
- [SOURCE_PUBLICATION_VERIFIED.json](SOURCE_PUBLICATION_VERIFIED.json)：主代理实际关闭源码发布准入门的原始收据副本。
- [REMOTE_BYTES_VERIFIED.json](REMOTE_BYTES_VERIFIED.json)：固定公开提交下 7 个文件、371,916 bytes 的真实 HTTP 读回凭据，包含 131,578-byte 二进制 bundle 的实际字节校验。
- [PROVENANCE.json](PROVENANCE.json)：来源身份、字节变换范围、状态时间与收据绑定；它是来源说明，不是新的科学结果收据。

## 固定来源与原始身份

| 来源 | 固定身份与解释 |
| --- | --- |
| R45 论文 | `TrillionniumFoundation/ICLR-2027`，commit `f8df0a6075f58f3ab9431a889b773cdf8d6e771d`，`revision_2026-09-26-r45/` |
| 原科学研究 | `TrillionniumFoundation/hepta-private-ci`，base `e38a2311c0fd3eecc7f95be00c29be970a3b7a34`，`experiments/parameter_field_fullstudy_20261029/` |
| 源码机械快照 | `cbfbab1c831e9e9e4c33e0eed7091ffcb71c6208`，tree 与原 C3 相同 |
| 已核验源码发布 | `51749cfc93452ba7c235543c1529568a75368f2d`，tree `876efbc456b07b8bdffbb055feb6ad754928dd9b` |
| 原始 C2 freeze | `bf59ac45860884d770dfd437d8a447068c5ef9a9`；该身份由已公开真实 Git bundle 恢复，不冒称为上述远端 snapshot commit |

原 C1、C2、C3 的精确对象与 12 个原始提交保存在 [LOCAL_EXECUTION04_HISTORY.bundle](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/51749cfc93452ba7c235543c1529568a75368f2d/operational/parameter_field_recovery04/publication/LOCAL_EXECUTION04_HISTORY.bundle)。该文件为 **131,578 bytes**，SHA-256 **`96e136232f68b5eba1ec4122ecfb1aee9d263b7fd892091f19d373f37727931e`**，Git blob **`0e4535bf1065a42890cc71d19ae3cafa304d58b4`**。恢复需要其声明的精确公开 base；操作方法与独立恢复验证见同一固定提交中的 [publication README](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/51749cfc93452ba7c235543c1529568a75368f2d/operational/parameter_field_recovery04/publication/README.md)。

论文来源在原审阅时是 private 仓库，正文通过已授权的 GitHub 连接读取。报告中的固定论文链接仍受该仓库访问权限约束；本目录公开评论与来源身份，不包含那 20 个 TeX 原文件。报告的论文分支观察限于原审阅时间，不宣称遍历所有其他草稿或证明此后分支未变。

## 有时点限制的执行状态

源码发布和 7 项实际字节读回已完成；这只关闭源码发布准入门。真实导入收据记录了 2026-10-30T02:17:18.526531+00:00 的原始 loaded-source closure PASS，运行时为 Python 3.12.14、Torch 2.8.0+cpu、NumPy 2.3.5、Pillow 12.3.0。这个历史成功事实不代替新的资源准入或科学任务内存资格。

截至 2026-10-30T03:13:29+00:00 的主代理观察，science 为 0，当前资源窗口未通过，共享 OOM / OOM-kill 计数为 4 / 4；计数的进程归因未被识别。本公开副本未读取 RAW/endpoint payload，未运行科学实验，未发布模型或数据，未改变冻结源码、阈值或任何检验人口。P1–P5 的本轮实证结果仍待完整执行和原 26/30-seal、literal restore 及已登记补充分析的实际凭据。
