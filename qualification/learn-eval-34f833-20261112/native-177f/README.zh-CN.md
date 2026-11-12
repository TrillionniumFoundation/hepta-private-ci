# LEARN 原始原生验收与请求恢复记录

这里保存的是独立整合源码 `177f7f4d975f06fbf7dd01c87cc0f75b3a73a5d6`、tree `17f3172d6c7e751af97acaaec6a9318c44b5effe` 的实际结果。源码前后相同且 clean。该远端 Git 对象尚未推送到 GitHub；不能把本结果改标为本 PR 或后继联合候选的验收。

真实 native 构建通过，实际运行 **13 例：12 pass / 1 fail**，1273 skipped，job `1a1ce46368f-2564-15e8` 权威终态 failed/exit 100、非 timeout。完整原日志和 JUnit 分别为 39808 B / 5982 B，SHA256 见 metadata/manifest。JUnit 独立解析确认 13 testcase、1 failure。

通过范围是 7 个原 execution-owner 机制、4 个已签名经历 intake、1 个 holdout physical CURRENT。失败位于共享 `preregistered()` 的原目标 digest 等式，在新的 unsorted-policy case 到达其被测逻辑之前停止。根因为两次独立 Admission 的 requestId/采样上下文不同，Objective 按设计必须不同。后继修复保留同一真实 Admission 贯穿预注册与 A 构造，原断言没有删除。原失败保留。

原命令中的 `neuron_cell_learning_evaluation::tests` **没有匹配到测试**，不能算 #6095 的覆盖。正确模块为 `neuron_cell_evaluation::tests::learning::`，7 项所需方法列表保留在恢复请求中后继 v4 filter 的范围说明。后继 v4 的启动/执行状态仍为 **UNKNOWN**。

`request-recovery.json` 明确区分已知终态与三个未确认请求。code-mode host generation 切换使原 pending RPC 和内存 stores 丢失。所有原始 key、已知参数和状态保留；command 字段是从提交时的字面模板及固定 patch 重构的文本，**不是原始请求字节或回执**。未取得原始 command fingerprint 时不得把重构当作原件，也不得换 key 自动重放。后续目录不存在的观察不能证明 v4 没有启动。

三文件编译修复是原 fixture 的窄 signer tuple accessor 与同一 boxed candidate 的 `as_ref()` 比较；不公开原 Credentials 字段，不改生产签名、权限、模型或门槛。附原修复 diff、原 blob binding 和 same-Admission 后继 diff。

当前联合实现见 [#6135](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6135)，Root 持续拒绝见 [#6128](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6128)。本批原件不授予两个后继 exact-head native PASS。普通正向采用、完整 NoUpdate/回退、daemon + Root 真冷重启计数均保持 **0**。
