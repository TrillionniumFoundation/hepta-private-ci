# P1–P5 阻断与原 owner 交接

**本清单保留 DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO。** 它只压缩四个冻结证据包，不宣称 P0、全仓 CI 或生产验收通过。新的 Operations/P0 修改、编译和 CI 动态由主协调者另记。这里的 owner 指既有 PR 或模块职责，不代表人员排班或本机任务状态。

表内短 SHA 便于阅读；[OWNERS.jsonl](OWNERS.jsonl) 的 20 条记录包含完整 head/base/observed merge、关键 source blob、日志/receipt SHA256、资格边界与下一动作。证据路径以整个审计包根目录为基准；旧 source green 不继承给新 merge。

## 可以按原 owner 继续的软件工作

| ID / 原 owner | 冻结证据确认的阻断 | 最短下一动作 |
| --- | --- | --- |
| **P1-BACKEND** · HEPTA #2918 `ca5b70d`；#2695 `ecc4f8c`、#2734 `dc271d4` | 共享 encoder 和 signed batch seam 已有；所审 reference 非 learned，AppServer worker 入口尚未接 Neuron 实际 batch 闭环。 | 选唯一特征合同，分阶段接 bounded dequeue→SDK batch→校验→持久 ack；原 FinalUse 覆盖效果。真实权重/目标机见外部前提。 |
| **P1-TELEMETRY** · #2734 `dc271d4` | CPU 缺失被写成 wall elapsed、RSS 缺失写成 0，无法区分未知与实测零。 | 映射 #2918 Option/availability 到 Cell writer/replay/export，保留版本化解码并验证重开；不整文件替换不同 API。单批 p95=p99 不另判算法 bug。 |
| **P4-VALIDATOR** · #2734 → 既有 #2850 `05cf9bb` | 当前脚本接受无签名 observer、重复 case、非法 factor、错误最终 digest 四类坏输入；donor 全拒绝。 | 复用 #2850 完整 script+tests，审查 ahead 1 / behind 2 的合流；保留 27 tests 和全门禁。超过 800 行分有依赖的小阶段，不开同义 PR。 |
| **P5-TASKFLOW** · #1311 `dfac717`；#1063 `91cdb16`、#1256 `d50b021` | 真阻断是两支 SQL 20–22 同号不同内容，main 仅到 19；旧 NoTask 在当前 #1311/main 已是 Idle。 | 原 automation owner 查真实 applied history，设计唯一升级/恢复路径；不拼接编号、不再修已消失旧接口。保留 scheduler/恢复门禁。 |
| **P5-OPS-ORACLE** · #996 `b5b31f8` | 原 361 tests 为 338 pass / 23 fail；其中 22 个来自生产 oracle 实际 `2d85becf…` 与 expected `f76aecab…` 不符。 | 审完整 compiled migrations、required objects 和 SQLite catalog 后修根因；保留篡改及 UPDATE/DELETE/REPLACE 负例。仅记录冻结状态，不吸收后续候选结果。 |
| **P5-OPS-TURN** · #996 `b5b31f8` | 剩余原例未见 physical turn start，根因独立未明。 | 生产库可打开后重跑原 `cognitive_final_use_revalidation_follows_durable_dispatch_and_precedes_turn_start`，核对最早 dispatch/FinalUse/turn 事件；不直接归入 oracle。 |
| **P5-AUTHBUS** · #1272 `7794771` → #1176 `5f6a717` | source caller gate 编译前拒绝 Bao 公共 `operation_id` 字段；这是 staging 合同不符。 | 收敛 sealed entered handle、原 durable identity 和 FinalUse；保留禁令与原负例，分别验证 source/merge。main 已有 relay，不能概括为全未接通。 |
| **P5-ORGAN-A05** · Desktop main `dd1478e`，A05/A06 | QueryAbi 已实现；ReadUsage、InstallBudget、QueryDelivery、RetireThrough 明确 EOPNOTSUPP。 | 在原资源 owner 上逐项实现四操作，先闭合真实 grant 与锁内准入/撤销；保留现有 CPU 账务与 Process/session 身份。 |
| **P5-ORGAN-A07** · Desktop main `dd1478e`，A07 + 原 Operations | 服务是只读投影与单次、非 crash-durable ObjectiveStart；缺真实持久 K↔D→kernel effect 闭环。 | 依赖 A05，在原 ledger 中做 K 查找、D 比较、fsync、唯一 dispatch/reconcile 和最后准入；HistoryAck 不自赋退役权，不建第二 ledger。 |
| **P5-BROKER** · Desktop #210 `bb71c17` | 缓存 key 把 digest 并入 K，与 durable K=(scope, operation) 合同不同；当前效果仍永远拒绝。 | 在既有候选修映射/命名/查找，保留同 K 改 D 冲突；不能原样将缓存升成 durable owner。五条 API success 尚非原始日志资格。 |
| **P5-CODEQL** · Desktop main `dd1478e` | 原 JS/TS 提取 exit 32，原因仍待定位；日志的通用磁盘提示不证明 ENOSPC。 | 沿精确 workflow/extractor 和原始日志定位无 JS/TS 被处理的原因，再验证原门禁；不虚构磁盘修复结论。 |

## 已有修复与唯一执行 owner

| ID / 保留的组合 | 已有证据及尚缺的资格 | 下一动作 |
| --- | --- | --- |
| **CELL-WAL** · 独立 #2734 → 既有 #2909 `5993cb9` | 四路径 109+/7− 已完整投影；真实 Windows job `118059888568` 为 **7 pass / 0 fail**。required scoped `118069853019` 编译 ENOSPC；Unix 两项攻击测试未由该 Windows job 执行。 | 继续既有 #2909，保留 Unix alias/0600、Windows 持锁 seek 与旧恢复/代际合同；验证当前 scope、Unix 和 source/merge。不导入 #2917，不新开 Cell owner。模块本身不证明独立 DACL/reparse 权限闭包。 |
| **P2-CALLER-PARITY** · 保留 #2918 `ca5b70d` | #2920 `20bf22b` 漏两个实际 caller，job `118411015933` 真失败；#2918 的独立 B4 与 Rust 81/89/7 各组有原始通过。#2921 `22293e5` 组合较窄。 | 保留 #2918 的完整 caller + independent B4 + Q24，不再新修同义问题。组件 green 不等于独立 signer、模型或全仓资格。 |
| **P2-CANONICAL** · #2684 `b5d3200` | 原 canonical owner 和 69 项 source 回归已在；#2734 第二执行 seam 正确拒绝。真实 Control/CNS/TaskFlow 效果组合未证明。 | 只在 #2684 映射真实原 adapter，保留四效果、Ambiguous 和最后入场；审既有 #2597 `91a662a` 三项 CI/style 差异，保留 full-suite 与六项 post-effect 回归。祖先漂移不是已复现当前 bug。 |

## 需要外部数据、设备或独立资格的事项

| ID / 原 owner | 软件已有部分与真实缺口 | 允许向前推进的精确动作 |
| --- | --- | --- |
| **P3-FUTURE** · #2734 `dc271d4`；#2695 `ecc4f8c` | 同 head 已有 2–32 typed windows、signed freeze、独立角色、product qualifier/rollback caller。缺真实 preregistered 未来数据、可信时间、独立密钥与负迁移对照。 | 复用现有 longitudinal runner/verified receipt 映射真实消费链，再收实际数据。不要再造 future schema，也不要把签名或 advisory digest 当经验有效性。 |
| **P4-TARGET-MATRIX** · #2734 / #2918 / #2695 / #2684 | 本冻结包没有真实 64-case 目标矩阵或独立生产接受；4 个参考规模、64 行结构、27 pytest 都不是 64 个 workload。P1 还需有许可且固定 hash 的模型/tokenizer。 | 软件基线后，在指定 binary/model/workload/driver/host 上跑 **64/256/1024/4096 Cells × 16 factors**，留分布、unknown mask、故障恢复及同预算 split/no-change receipts；独立 observer/operator 接受。 |
| **P5-TARGETS** · Desktop A01/A04/A08/A09/A10，main `dd1478e` | Linux 只读客户端已在；非 Linux 路径明确 UnsupportedPlatform，这是软件缺口。真实多平台、新内核与原生存储断电 G2 则是独立设备/验收缺口。 | 各原平台 owner 补真实通路，再绑定 image/source/binary/host 做 revoke、kill、reboot、持久恢复和独立接受。历史文档/QEMU 记录不继承为当前 G1/G2 全绿。 |
| **P5-UI-TERMINAL** · HEPTA #2885 `89933fd` | 主 source UI 5 pass / 1 fail；证据支持已获 Chromium `62473ad…` 修复的 no-store 终态缺陷。主 Chrome153 和已审 Chrome156 源仍缺，Chrome157 仅 diagnosticOnly。20 次诊断不是产品验收。 | 原 UI owner 选择受支持的含修复主浏览器，核对 revision/binary 后审 pin，跑原 **6 source + 6 base** 和 engine/platform/Blocking。保留 no-store、bounded body、cancel/overflow/truncation 与真实 terminal，不加时、不放宽断言。 |

## 保留分流

**P5-CODEX-SPLIT** 延期给现有 Codex execution owner（HEPTA main `f8c9419`）：先取得 source-bound IPC/权限/冷启动与 paired perf/failure profile，再决定拆分。**P5-AGENTD** 继续既有 #2915 `1045570`；冻结 P5 仅绑定其身份，本清单不重复修复或声称安全门禁已过。Chain/Game 不进入这里的 release gate。

## 冻结结论入口

完整日志与源码等式由 OWNERS 的 evidence/source_bindings 逐条索引；gzip 日志同时记录压缩文件与解压原文 SHA256。缺失的真实外部 receipt 明记 NOT_COLLECTED，不生成占位成功。

| 冻结报告 | SHA256 |
| --- | --- |
| `p1_p4_audit/README.md` | `a4ab6de0e9a9087bda28014b586b4aadd45275f237549a278a41723034715868` |
| `cell_p0/README.md` | `2b41ab153916da2518bde72746e5e01d6ea0eb48cf0c4c572008245e7616a8be` |
| `p5_inventory/REPORT.md` | `4476a5e915aba756c46052ec10626cb8dac3d28b4be5324a8377327ec4db8f85` |
| `ui_p0/FINDINGS.md` | `d8729ff7b2b5121e4c42455c75dffd7d45e1b7912420f364712ccaeeba0b1d9c` |
