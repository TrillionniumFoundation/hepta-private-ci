# B16：拒绝 COMMIT 后的池复用独立候选

本候选只恢复两个显式 guarded pool 入口在 SQLite 拒绝 COMMIT 后的读可用性，不修改冻结 B16 payload、SQLx driver 或 Current/权限/提交否决规则。当前状态是 **静态候选，未编译、未运行**。

## 已固定的源码关系

Donor 测试源 `3466a3074ab2df88bfae3519f453aa4672c536e5` 是修复 `f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55` 的直接父；修复仅改变 State 的 before_acquire。当前 `f6905bf16e0b6395648e377c6fa444e026c4d3a1` 在它之后 13 commits，State 没有净变更，修复与回归用例 blob 均相同。该修复早于上轮 e65a 观察，不能写成本轮新增生产代码。

PR 正文报告匹配 RED→GREEN 和 1288 PASS，但完整 native raw 未取到；研究员检查讨论原 API、本文检查完整树后仍是 `RAW_NOT_RETRIEVED`。这些数字不转移为我们的资格。

## 源码因果与修复边界

SQLite commit hook 拒绝会自动回滚。SQLx 0.9 worker 只在 COMMIT/ROLLBACK 成功时减少 depth，失败 Transaction 的 Drop 继续排队 ROLLBACK；此时 SQLite 已无事务，ROLLBACK 失败可留下非零 depth。随后 ping 只确认队列经过，不重置 depth，下一次自定义 BEGIN IMMEDIATE 因而可报 InvalidSavePointStatement。冻结 vendor 的 worker/transaction.rs 与实际原包字节相同。

两个 guarded 入口分别实现，不能整文件照搬 donor。新 before_acquire 仅将非零 SQLx depth 的闲置连接正常关闭并取得 replacement；coordinated 仍在干净连接上执行原 before_checkout。每个 replacement 原样安装同一 commit hook、custody collation 和 native lifetime token。未重开 owner gate、未重试 COMMIT、未重置深度、更未授予 Current。默认普通 pool 和只读入口完全不改。

## 两个物理控制

各占住五个实际 pool slots 中的四个，在第五连接创建 TEMP marker。对第五连接执行真实事务写入并关闭 owner gate，要求 COMMIT 返回 SQLite 531；ping 后在 lock_handle 保护下对照真实 sqlite3_get_autocommit 与 SQLx tracked state。释放它后再取得唯一可用 slot，观察 TEMP marker 并开启原 BEGIN IMMEDIATE。

反事实必须在每个精确用例中实际出现 `sqlite_autocommit=true tracked_transaction=true`，再出现 `old_temp_marker=1 read_begin_error=Some(InvalidSavePointStatement)`，最后命中原 read-availability expect 的普通 assertion panic；早期错误、超时、泄漏、跳过不算因果。修后要求 marker=0、读事务成功且原数据仍空、coordinated 原 callback 仍被调用，replacement 的下一次隐式写入仍返回 531。

该风险不推翻 Foundation 的物理否决结果：原 Memory 控制用 raw SQL BEGIN/COMMIT，不走这次触发 stale depth 的 SQLx Transaction bookkeeping。新控制补的是不同的真实入口。

## 原生执行前置

本 patch 精确基于冻结最终 B State `85984c8c0fb1f699ad761de7383f920decad4808`。实际后续 source/locks/metadata 尚须重新绑定，不能把 provider unknown 当成该源码已到位。两个新增 controls 先作 tests-only 负控，再只改生产 11+/1−，exact restore，0 retries；仍经原 just test。原完整 State/Memory owning gates、已有 14 recovery tests 和 fix/fmt 规则保留。当前无 Cargo/BUILD/锁变更；新 sibling test 由原 module/BUILD glob 收入。
