## 当前状态：实际 b608 对齐已闭合，65a 原源码验收在预检失败

本 PR 处理证据不足被误记成比较结论、原 owner 到实际消费者的接线，以及恢复证据缺口。现已把已审候选与实际执行原件连接起来，并保留一次完整的失败验收窗口。

**真实合格任务链仍为 0，qualification=false，PR 保持 draft。** 源分支仍为 `cc57c7198db6293ccca562253c42fffbe2a04633`；实际隔离候选为 `b6084394a4a38ab495c16eaba09e879f04a96f8e`，tree `8ebb37e523ad3932a58cf016af0a9f4e0eeb6638`，sole parent `d25675445c39f76db69a7bd8e71a1a72e1cd5b9f`。

### 已完成的实际结果

| 项目 | 实际结果 | 结论范围 |
| --- | --- | --- |
| 41e 维护、50f 最终格式化 | 原 scoped just fix / just fmt 正常退出 0；17 个实际 Rust 变更、四个已审 non-Rust 文件；末次 fmt 没有再改源码 | 不改写旧 fix101 失败；不等于行为或资格通过 |
| 5a9 canonical 对齐 | 29 个 typed Git objects，94 条命令，33 项 mutation intent；实际 HEAD/index 对齐 b608/8ebb | 完整 15,243 文件、两份 raw index、uid/gid 与原 ns metadata 已核；无物理源码改写或测试 |
| 465e 精确 source 请求 | 原 bootstrap / 8 payloads、代码与 HOLD→READY 字节层、独立审查及 Root exact 审批均固定；仅启动一次 job 65a | 原 600/300/4800 source budgets、7200 outer 与原门槛保持 |
| 65a 实际终态 | failed / exit 1，非 timeout/cancel/retry；driver_main_entered=false | 三个 source gates 与 native phases 均 0；没有本版本资格通过 |
| 完整失败读回 | 94 归档文件全部完整 Git GET；37 成功 chunks 恢复 30 native 路径；11 staging 原件与原请求逐字相等 | 同一路径原 helper255 失败与首次成功 version 后的补齐分别保留；未重派 main |

### 失败原因的证据边界

Primary 是读取历史 3bb RESULT 路径时的 FileNotFoundError。该路径与原 3bb 成功完整 SDK 的路径和 body pins 一致，没有证据支持“路径拼错”。哪一级路径不可用、原因与行为人保持 **Unknown**。

finally 还记录了 SourceChanged：当时 initial_git 尚为 None。原 secondary 错误保留，但它不能证明源码发生变更，也不是确定性欺诈。实际 partial after Git 与 5a9 终点逐字相同；本次没有走到完整物理 inventory 或 live environment preflight，不能扩大为当前全部源码和环境不变。

后继输入只在隔离本地准备：完整原历史字节、原 job/path/pins 与新 transport path 显式分离，不回填旧路径或改写原收据。当前 source、HEAD/index、完整 uid/gid 元数据、真实材料、权限、环境与锁继续检查原活态对象。尚无新的 source/native 运行审批或结果。

### 普通产品路径的剩余工作

实际 b608 的有限调用审查确认：12 个新增 custody 公共 API 尚无 non-test 普通调用者。E1 Root typed assembly 正在独立 proposal 中补实际函数体与原工厂出口；尚未进入本候选或完成 Rust 验收。grant 验签不能代替当前 revoked/head/frontier 检查，lease 前后观察也不能冒称跨 publication 连续原子保护。发生不确定副作用后只保留同 operation readback/recovery。

E2 实际 Root task service 与 sealed daemon client、E3 真实角色通道、E4 消费者与真实 daemon/Root 进程冷恢复、E5 独立评价与完整成本仍需完成。原 14 phases、全部包/filters/预算，以及 **48 个 exact Root FQN/JUnit 名称**保留；skip 不算通过，同进程 reopen 不算进程冷恢复。

最终仍须完成 **真实授权 A → 原 Training owner → 独立 B → Adopt 或完整 NoUpdate → 实际新消费者 C → daemon 与 Root 冷恢复**。完整部署组合、最强可部署对照、旧/稀有/必过任务和所有冻结成本账不能由 commit 或内容根替代。缺结果、成本、材料、来源、独立性或原 owner 授权保持 InsufficientEvidence/Unknown；完整不采用与可复现的确定性欺诈分别保留自己的语义。工程审批 JSON 不构成 Hepta 运行时授权。

完整原件与当前限制：[证据索引](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c3eb33b7f60c3b9ea2ed3724f585d30b20ff8f9e/qa/evidence/utility-evaluation-20261112-36fa/README.md)；[功能矩阵](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c3eb33b7f60c3b9ea2ed3724f585d30b20ff8f9e/qa/evidence/utility-evaluation-20261112-36fa/section6-functional-completion-matrix-v1/FUNCTIONAL_COMPLETION_MATRIX.md)；[Root 65a 完整重放](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c3eb33b7f60c3b9ea2ed3724f585d30b20ff8f9e/qa/evidence/utility-evaluation-20261112-36fa/root-source65a-complete-closure/ROOT_SOURCE65A_COMPLETE_FAILED_WINDOW_REVIEW.json)。
