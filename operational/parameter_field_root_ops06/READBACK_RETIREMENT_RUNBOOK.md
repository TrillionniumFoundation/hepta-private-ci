# Execution06：已接受 stage 的回读大分片退役

本工具只退役一个明确选择、且 supervisor 已真正接受的 stage 中 `root_archive_io/STAGE/readback/part-NNNN.tar.gz` 独立副本。原位压缩分片、全部小型文件、实际 ACK/ACK_VERIFIED、原始响应、命令/WAIT4/进程凭据、RAW/CAS、冻结源码以及远端文件全部保留。

源码和测试当前位于独立 `execution06_retirement_development`。生产入口应在 root 完成预启动快照后，以原样字节交付到 `execution06_recovery_20261030/retire_accepted_readbacks06.py`。本交付没有执行生产 prepare、退役、上传或 ACK 操作。

## 固定身份与准入

工具固定绑定 `execution06_detached_20261030`、C2 `bc4e757f5c90f6365f383c1127be710d2ded874a` 及实际 pipeline SHA `d16bac3194b36d286f180976ddbc7dff16e544763e195d408a135b30af4fb86e`。它核验实际 cwd-policy 的全部 source files、14 个审阅过的冻结消费者、4 个已下载的官方 helper。没有生产路径或阈值覆盖参数。

准备和执行都要求：

- 该 stage 的 REQUEST、ACK、supervisor 写出的 ACK_VERIFIED 及此前 ACK 链完全对应；实际 STATUS 的 durable_acks 已包含它，且已离开该 stage 的等待状态。
- START_POLICY 的完整整数 supervisor 身份（含原 parent PID）、原 12 小时绝对 deadline 与原 OOM baseline 不变；活动流程必须仍是原进程和 PID namespace。等待只读 `/proc` 覆盖期间也持续检查这些门。
- 若 primary 已结束，必须有匹配的实际 COMPLETE、成功的 outer WAIT4 及七份 daemon 凭据；直接复用冻结 `prepare_pins.detached_provenance` 的原元数据函数。终结后不要求已退出进程仍存在，原 deadline 和 OOM baseline 仍受检查。失败 episode 不适用本工具。
- 原件和回读副本各自为无 symlink 的 regular file、nlink 1、不同 device/inode 组合，SHA/大小匹配真实 ACK，Library ID/version 对应实际远端记录；分别记录并保持原件与副本的全部 xattrs。执行必须与 PLAN 的 inode、mode、UID/GID、size、atime/mtime/ctime、nlink、allocated blocks 全部一致。
- 实际上传/回读的 ordered input、完整 ToolResponse、transfer、原 external_step INTENT/WAIT4、stdin、stdout/stderr 与纯文本输出路径均能重核。保留 `_engineering/STAGE_*` 和 stage 工作目录的全部小型凭据。
- 当前完整 `/proc` FD/maps 观察无目标 inode/路径引用。发现已知引用或其他错误立即停止；仅明确的新 PID 或访问缺口可在 10 秒内、每次最多 0.2 秒重新只读观察，完整原门 PASS 后才继续。没有 unlink 或其他 mutation 重试。
- 写凭据前保持原 256 MiB 物理保留额和至少 2,000 可用 inode。这里的容量检查不能替代 supervisor 的原启动/分析/finalization 门。

只读 `/proc` 扫描是观察快照，不是内核提供的持续独占租约。dirfd 固定删除目录，真正 unlink 前再核验原件、副本与父目录身份。工具没有权限把其他进程或文件系统使用者全局冻结。

## 1. root 先读取实际接受状态

root 另读本次真实 `ACK_VERIFIED.json` 与已推进 STATUS。`publish` helper 成功并不代替 supervisor 接受。不要对仍在等待 ACK 的 stage、缺失 ACK_VERIFIED 的 stage 或失败 episode 做准备。

下面路径是生产位置。把 `STAGE` 和 `REQUEST_SHA` 替换为该次真实值；不能从过去 stage 推测 hash。每个测量目录必须不存在。为保证阶段目录的独占性，测量目录在 `_engineering`，不要预先创建 `readback_retirement06/STAGE`。

```bash
/workspace/scratch/178ced6a501f/runtime_recovery_20261030/venv/bin/python -B \
  /workspace/scratch/178ced6a501f/fullstudy_recovery06_git/operational/parameter_field_recovery04/external_step.py \
  --directory /workspace/scratch/178ced6a501f/execution06_recovery_20261030/readback_retirement06/_engineering/STAGE_prepare \
  --cwd /workspace/scratch/178ced6a501f/fullstudy_execution06_ops/empty_cwd \
  -- \
  /workspace/scratch/178ced6a501f/runtime_recovery_20261030/venv/bin/python -B \
  /workspace/scratch/178ced6a501f/execution06_recovery_20261030/retire_accepted_readbacks06.py prepare \
  --stage STAGE \
  --expected-request-sha256 REQUEST_SHA \
  --reason '已接受归档的独立回读副本；为后续原容量门保留磁盘空间'
```

prepare 会重新运行原冻结 ACK 字节验证器，再校验精确原件/副本并记录缓存提示；不删除任何文件。它独占创建 `readback_retirement06/STAGE/`，写 PREPARE_INTENT、PREPARE_JOURNAL 和 PLAN。PLAN 列出每个目标的 descriptor、完整 stat/xattrs、保留文件清单、actual chain 和观察结果。输出中的 allocated_bytes 是可回收上界，不是保证的全局可用空间增量。

全 SHA 读取使用 O_RDONLY/O_NOFOLLOW/O_NOATIME。每次最后一遍已验证的分片读取后，对同一个已验证 FD 做 POSIX_FADV_DONTNEED，记录前后 stat/xattrs；不修改文件字节，也不声称提示一定释放页或已满足资源门。

## 2. root 审阅 PLAN 后显式执行一次

核实 prepare 外层实际 WAIT4 exit 0、无 FAILED，PLAN hash 与打印结果完全一致。准备生成 PLAN 后修改任何目标或凭据都要求停止。然后以同一份工具字节执行：

```bash
/workspace/scratch/178ced6a501f/runtime_recovery_20261030/venv/bin/python -B \
  /workspace/scratch/178ced6a501f/fullstudy_recovery06_git/operational/parameter_field_recovery04/external_step.py \
  --directory /workspace/scratch/178ced6a501f/execution06_recovery_20261030/readback_retirement06/_engineering/STAGE_execute \
  --cwd /workspace/scratch/178ced6a501f/fullstudy_execution06_ops/empty_cwd \
  -- \
  /workspace/scratch/178ced6a501f/runtime_recovery_20261030/venv/bin/python -B \
  /workspace/scratch/178ced6a501f/execution06_recovery_20261030/retire_accepted_readbacks06.py execute \
  --plan /workspace/scratch/178ced6a501f/execution06_recovery_20261030/readback_retirement06/STAGE/PLAN.json \
  --expected-plan-sha256 PLAN_SHA \
  --execute
```

execute 独占创建 `STAGE/execution/`，持本 stage 的协作锁。完整重核后逐项执行：fsynced UNLINK_INTENT → 一次 dirfd unlink → fsynced UNLINK_RETURNED → 父目录 fsync → 观察路径缺失并 fsynced UNLINK_DURABLE_AND_ABSENT。所有原件随后再次全 SHA/xattrs 核验，并再次对同一只读 FD 作最终 DONTNEED；全部小型凭据再次核验字节/身份/文件人口。

只有外层真实 WAIT4 成功、`execution/RESULT.json` 完整、无 FAILED 且所有列出的回读副本缺失，才记录本次退役完成。完整保留这些工程测量，计为外部 root 工程成本；不能再把 nested CPU 相加，也不能从工程完成推断科学结果通过。

## 失败或歧义必须保留现场

既有 stage 计划目录、执行目录、临时 `.writing` 文件、FAILED、非零外层退出或不明返回都不会自动继续/覆盖。不要删标记后重跑，也不要改 hash 接受当前文件。

若 unlink 返回后，在写后续日志或 fsync 时失败，FAILED 中的 `known_unlinks_returned` 可能落后于真实缺失状态。必须对最后一条已 fsync 的 UNLINK_INTENT、实际目录项与原件做人工/独立核对；工具明确记录这一歧义。路径若后来重新出现，即使 SHA 相同也属于新身份，不能再次删除旧计划里的名字。

当前代码没有跨 stage 自动循环，也不生成修补 ACK、替换 readback descriptor 或 hardlink。之后若人工重新运行旧 verify_ack，需要从实际远端重新 materialize 真正独立的回读副本，不能拿原件或 hardlink 冒充。

## 后续消费者和终态保留

源码静态审计已确认：接受后的旧 stage 大型回读分片不再由后续 final_closure、原 RAW/CAS finalizer 或 postseal gate 重读；它们依赖保留的 REQUEST/ACK/ACK_VERIFIED/MANIFEST/VERIFIED/ARCHIVE_COST 及原科学证据。当前尚未接受的 stage 仍必须具有真实独立回读字节。

最终独立终态归档应包含工具源、测试/审阅/验证报告、本 stage 的 PLAN、prepare/execution journals、INTENT/RESULT/FAILED（如有），以及两次真实 external_step 的全部支持文件。其路径由 root 显式纳入终态 payload；它们不会自动变成前面 17 个 ACK 的组成部分。不增加第 18 个科学 ACK，也不声称终态归档已完成。
