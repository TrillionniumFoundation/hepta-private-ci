# B 批次：精确源码对齐与串行验收顺序

状态：**静态重建通过，B 尚未编译或运行。** 本目录不包含对 native 工作树、target、Cargo 或 Git ref 的修改。

## 已核实的源码对齐

直接读取当前 A 的 Git tree `f8251e1d14fa8524ab469281296cd4cf708f173c`，确认 B 的 16 个唯一路径首次 preimage 或新增文件的不存在状态全部匹配。state 子树为 `cea0fd676bf8bb9771aea2a8c16f3d746dac42dd`，Memory 子树为 `34e3ebcde71af34b16a606aede989a6385fa6f03`。这是已观察到的 A 快照；A 终态后的实际源码仍须由唯一执行者重新核对。

在独立的普通文件副本中，51 个原对象共 838,542 字节全部通过 Git blob 与 SHA-256 校验。实际执行了 19 次 `git apply --check` 加 `git apply --whitespace=error-all`，包括六个完整补丁、串行负控/修复/恢复，以及 R2c V2→V3 观测增量。25 次文件变更均得到原 manifest 的精确 postimage；直接全补丁路线与因果串行路线最终 16 文件逐字一致。没有创建 Git 仓库、commit 或 ref，也没有编译 Rust。

完整结果在 `static-verification.json`；可复核脚本为 `verify_static_sequence.py`。脚本拒绝复用已有静态副本目录，避免覆盖本次原始证据。

## R2c V3 的必要对齐

R2d 的原 manifest 仍引用旧 R2c manifest `081aa0f…` 和测试 `e1ea6d…`；R2e1 也保留旧 manifest 引用。这是元数据陈旧，不是生产源码冲突：

- 当前有效 R2c manifest 是 `a33a305d001eed9b2aa2a3d3c916dfd5a9924a47`。
- V2 与 V3 的生产 `sqlite.rs` 同为 `4a147f593ef580de5d79b1dd47b0234437c629ca`。
- 有效测试是 `31b26a78bffe40815aa8a5b55e61b5139e7bca96`，保留在真实 SQLx pool 上读取 `sqlite_version()` 的四行观测。
- R2d 及其后续补丁从未修改该测试文件。全部串行步骤都实际保留了 `31b26…`。
- 原 manifest 不重写；`serial-plan.json` 的 corrections 表记录三个字段的旧值与实际有效值。

不要把旧 `e1ea…` 测试覆盖回来，也不要把 SQLite 版本观测解释成动态链接方式或另一宿主 SQLite 的证明。

## 执行顺序

所有 native 工作由 CI 单一执行者在 A 终态、root 核准精确源之后进行。以下是待执行门槛，尚无任何 B PASS。

| 阶段 | 精确源码操作 | 必须取得的实际结果 |
|---|---|---|
| R2c V3 | 应用完整两文件补丁 `62a94bf9…` | 四个真实 COMMIT/checkout 控制；保留实际 SQLite 版本；原 state 回归 |
| R2d 负控 | 完整 `4582d690…` 后仅去掉 close_on_drop：`4f6b0999…` | 取消用例须先经过真实 progress gate/Pending/cancel，再命中物理状态断言失败 |
| R2d 正控 | 精确恢复 `1a2fefb5…` | 五个新控制通过；原 state 回归含未改 R2c 四例 |
| R2e1 负控 | 只加原 fixture：`2909207b…` | 四例各在真实 COMMIT 531 断言失败；原写入实际成功的诊断须保留 |
| R2e1 正控 | 仅应用 repair-after-baseline `69c4991b…` | 四个物理写入控制通过；原 Memory/state 回归、独立 read ACK 与 AlreadyRetained 语义保留 |
| R2e2a | 完整 `9743a504…` | 三个真实序列化帧正负输入控制；原 Memory 包回归 |
| R2e2b | 完整 `cbeca259…` | codec 七例，包含新增四个完整 head/CAS 控制；原 Memory 包回归 |
| R2e3 负控 | 只加 custody fixture：`d6d9de20…` | 四例须先证明物理连接存活，再在实际文件锁竞争断言失败 |
| R2e3 anchor 负控 | repair-after-baseline `e9653333…` 后仅去 native anchor：`7b931b63…` | 原 teardown 用例先阻止竞争；真实移除 commit hook、SELECT 成功后竞争错误地成功，才算命中负控 |
| R2e3 正控 | 精确恢复 `e14e9093…` | 四个 custody 控制通过；原 Memory/state 回归，最终 fix/fmt 及源码差异收据 |

完整 24 个新增用例名称、原始命令、每步补丁身份与预期/无效负控条件均在 `serial-plan.json`。不预估原包总用例数；从实际 catalog 与完整 JUnit 获取。反事实重复执行与 codec 前后阶段重叠不计为新增独立用例。

测试 fixture baseline 之后必须使用对应的 **repair-after-baseline**，不能再次套完整补丁。负控之后必须精确恢复。每次实际阶段都记录完整源码身份、fresh 原始输出/JUnit、selected/ignored/filtered、重试数和控制器终态。编译失败、权限/setup 错误、gate 未进入或超时，都不等于预期物理断言的负控成功。

## 编译依赖与门槛

源码顺序为 R2c→R2d→R2e1→R2e3；协议支线 R2e2a→R2e2b 可独立编译，在此串行方案中放于 e1 与 e3 之间。六批不直接依赖 R1、R2a 或 R2b，没有新增 Cargo/BUILD/锁输入。实际应用基线的 Cargo.lock 与 MODULE.bazel.lock 仍必须原样核对；若真的引入依赖变化，应运行仓库原生成器，不能手改锁。

原始 owning 命令在机器清单中逐项保留。codec 七例已覆盖其新增四例。是否在相邻纯协议阶段合并重复的 owning 调用，须由 root 按阶段资格要求明确安排，不能预先当作已完成。最终按原 `just fix -p codex-hepta-memory -p codex-state` 与 `just fmt` 审查真实差异；若提前做格式化导致后续 preimage 变化，应明确重对齐，不覆盖源以强行匹配哈希。

## 仍然开放的生产边界

这些控制即使 native 全通过，也不等于 B16 的完整普通入口通过：

- R1 同步 preflight 在 Tokio 之前；R2a inherited registration 需要 entered runtime。后续真实 caller 必须保持两阶段，不能把两个 API 的分别通过当作接线完成。
- R2e2 的 ReadHead 只校验内容身份与单调性；它不认证 Root，不验证活跃租约，也不构造 Current。
- R2e1 的 commit gate 保护其实际 writer pools；provided cold-image pool 依靠物理 READONLY，而非新 hook。
- R2e3 只覆盖注册后的物理连接 custody。建立连接、初始 PRAGMA 与注册之前的取消缝隙仍开放，另由 SQLx 原生 lifetime-token 候选研究。
- 真实三库 Current binder、独立 shared-open/跨进程所有者、transport/peer 授权与 FinalUse 仍需要后续生产消费者接线和实证。
- 本批 custody 控制的文件锁竞争使用同一测试进程内独立打开的真实 File；不冒称已经执行新的第二进程验收。

没有原平台资格或全组合产品绿灯由本次静态重建推导。
