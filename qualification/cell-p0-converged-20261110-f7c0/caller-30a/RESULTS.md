# 已发布 30a697c 的完整 caller 核查

**PASS_HEPTA_CALLER_CLOSED_SET，exit 0，authorityGranted=false。**

本次实际运行完整 `verify`，固定 source `30a697c50e10abd56e61b6b84f28ac9ae9f32f5d`、tree `b2a21d98380340b1c091006f4130aafdbeabca50`、parent `cb0598a9099a0d828ce73aedb51e397e600e49d1`。这是静态源码 gate；未启动 native 构建或测试，也不表示获得生产权限、完成 ordinary StageOwner 全链或增加独立科学收益证据。

## 本次原始结果

| 项目 | 实际数量 |
|---|---:|
| Rust 文件 | 6302 |
| boundary records | 223 |
| privileged inventory | 223 |
| protected file records | 218 |
| 去重 protected paths | 173 |
| 实际 verifier 调用 | 1 |

原始 stdout：`stdout.raw`，103,063 B，SHA-256 `83201a799a7be1e04116ad1b089b32761ae6d37ed77de35885e12d441f825c7c`。
原始 stderr：`stderr.raw`，0 B，SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`。两者保持原字节，没有重排 JSON 或用摘要替代。

## 调用与源码身份

Invocation：`p0-30a697c-full-caller-scan-20261111-v1`。

```text
python3 scripts/verify_hepta_callers.py verify --root /workspace/scratch/f7c0ded86bcc/hepta-p0-learn-merge
```

CWD：`/workspace/scratch/f7c0ded86bcc/hepta-p0-learn-merge`。
审计分支：`codex/cell-p0-final-caller-30a697-f7c0`。
开始：`2026-11-11T03:15:00.059278+00:00`。
结束：`2026-11-11T03:26:48.045787+00:00`。

BEFORE.json 与 AFTER.json 记录 exact HEAD/tree/parent、clean 状态、9 个已审变更文件哈希、CALLERS、verifier、Rust 路径 inventory 以及旧分支/receipt。前后所有比较均一致。

CALLERS SHA-256：`e24624826d94bd7726e55c5ffb3ffc55f182819949dbe7b66c92879441e38b19`。
Verifier SHA-256：`8899ec2b328125b2049b808cac0eeda3f57bfc6db89348512a58777101ae6dfa`。

manifest 配置的 source_roots 是 codex-rs。该范围内 tracked 与实际 rglob 均为 6,302 个 Rust 文件，没有缺失或新增文件。原有 qualification/archive/docs/assets sparse 排除被完整记录；未展开的 Markdown 从固定 Git blob 取哈希，其余 8 个变更文件从工作树原字节取哈希。本结果不声称扫描 manifest 范围外的所有 Rust 文件。

## 原证据保留与 preflight

旧分支 `codex/cell-p0-final-caller-audit-f7c0` 保持 cb0598a。`/workspace/scratch/f7c0ded86bcc/p0_final_caller_audit_cb0598_20261111` 的全部 19 个文件前后哈希一致。

首次元数据 preflight 在创建 ATTEMPT 或启动 verifier 之前，因为尝试读取原本被 sparse 排除的 Markdown 而失败。PREFLIGHT_NOTE.json 与原 helper 保留这次事件；修正仅改为读取固定 Git blob，并注明字节来源。实际 verifier 只启动一次。

本次 stdout 与旧 `SCAN.stdout.json` 字节相同。scanner 输出列举静态边界且不内嵌 source commit，因此本次新源码绑定来自独立 ATTEMPT/BEFORE/AFTER/EXECUTION、调用时间与原始输出。本包没有把旧运行成功移用于新 source。

## 可测成本

| 项目 | 秒 |
|---|---:|
| wall | 707.986497116 |
| child user CPU | 688.900055 |
| child system CPU | 3.479340 |
| child CPU total | 692.379395 |

wall 为单次 verifier 子进程周围的 monotonic 差值；CPU 为执行该子进程期间的 RUSAGE_CHILDREN 差值，在 post-run Git 读取前采集。它们不包含 fetch/switch、失败的元数据 preflight、前后快照、助手编排/通信、其他 agent/CI 及归档。金钱、能耗和整个会话成本保持未知。HEARTBEATS.jsonl 保留每 30 秒运行记录，静默 stdout 未被视为失败。
