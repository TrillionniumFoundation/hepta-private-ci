# PRED：真实 owner 只读接入说明

本文件是后续接入说明，不是一次已执行的真实 owner 采集或策略实验。
它自身增加的真实 owner 记录、独立业务效果标签和确认单位均为 0。
只能使用当前已确认的服务、数据库和观察者；不能以 fixture 补齐缺少的来源。
历史 pocket4 请求的 UNKNOWN 终态另行保留，本说明不授权重放该请求或业务动作。

## 1. 固定源码依据

以下链接全部固定到 `10629bab4d5f948854e7c59fed331213956fb974`。
相关路径已通过该提交的 Git 对象只读核对；远端运行前还须核对实际部署版本。

- [fleet 路径几何](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/10629bab4d5f948854e7c59fed331213956fb974/codex-rs/hepta-paths/src/fleet.rs)
- [Agentd 环境及代际校验](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/10629bab4d5f948854e7c59fed331213956fb974/codex-rs/hepta-agentd/src/config.rs)
- [AutomationStore 打开行为](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/10629bab4d5f948854e7c59fed331213956fb974/codex-rs/hepta-automation/src/store.rs)
- [只读采集及结构校验](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/10629bab4d5f948854e7c59fed331213956fb974/scripts/hepta_pred1/native_ledger.py)
- [有界分页入口](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/10629bab4d5f948854e7c59fed331213956fb974/scripts/hepta_pred1/owner_capture.py)
- [冻结决策和独立效果连接](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/10629bab4d5f948854e7c59fed331213956fb974/scripts/hepta_pred1/owner_bridge.py)
- [原独立 ActionSkillObserver 契约](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/10629bab4d5f948854e7c59fed331213956fb974/codex-rs/hepta-automation/src/action_skill.rs)

## 2. 从实际服务定位已有数据库

`AgentdConfig::from_process_environment` 要求实际 agentd 进程提供：

```text
HEPTA_FLEET_ROOT
HEPTA_AGENT_ID
HEPTA_AGENT_GENERATION
HEPTA_AGENT_HOME
HEPTA_AGENT_RUN_ROOT
```

配置还会核对 registry 中的 agent、generation、home、run root 与工作目录。
应从当前已验证服务身份提取上述白名单字段，不打印完整环境或命令行。
新 operator shell 没有这些变量，不能证明已运行服务没有配置。

```text
<实际 fleet-root>/fleet.toml
<实际 fleet-root>/agents/<实际 agent-id>/agent.toml
<实际 fleet-root>/agents/<实际 agent-id>/run/generation.json
<实际 fleet-root>/agents/<实际 agent-id>/automation/automation_1.sqlite3
```

路径类的默认 root 是服务 HOME 下 `.local/share/hepta-vnext/fleet-v1`；
它不能替代实际 agentd 所需的显式 `HEPTA_FLEET_ROOT`。
配置文件与进程名只提供定位线索，不能认证数据库或证明真实业务来源。
不得调用 `AutomationStore::open` 探测：它会创建目录、迁移库并写入 metadata。

## 3. 最小只读预检

下面命令仅对已确认的精确现有路径运行；替换示例路径，保留原始退出码和输出。
它使用标准库，不加载生产 Store，不创建或迁移数据库。

```bash
python3 - /exact/existing/automation_1.sqlite3 <<'PY'
from contextlib import closing
from pathlib import Path
import json
import sqlite3
import sys

path = Path(sys.argv[1]).resolve(strict=True)
tables = (
    "taskflow_effect_dispatch_attempts",
    "taskflow_effect_dispatch_observations",
    "taskflow_effect_dispatch_reconciliations",
)
with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
    db.execute("PRAGMA query_only = ON")
    db.execute("BEGIN")
    result = {
        "meta": db.execute(
            "SELECT schema_version, owner_agent_id "
            "FROM automation_meta WHERE singleton=1"
        ).fetchone(),
        "tables": {
            table: {
                "columns": [r[1] for r in db.execute(f"PRAGMA table_info({table})")],
                "bounded_rows": db.execute(
                    f"SELECT COUNT(*) FROM (SELECT 1 FROM {table} LIMIT 257)"
                ).fetchone()[0],
            }
            for table in tables
        },
    }
    db.rollback()
print(json.dumps(result, ensure_ascii=False))
PY
```

`bounded_rows=257` 表示至少 257 行，不是全表总数。
核对 `automation_meta.owner_agent_id` 与真实服务身份及目录；表缺失保留失败原件。
只读连接仍可能管理 SQLite WAL 的 SHM reader locks；不用 `immutable=1` 读活跃 WAL。

## 4. 复用现有采集入口

前提：目标 host 已具备精确固定的 Python 源码及 NumPy；记录源码与运行时身份。
`ACTUAL_HOST_BOOT_CLOCK_ID` 和 `RESERVED_ARRIVAL_CURSOR` 必须替换为实际来源值。

```bash
PYTHONPATH=/exact/pinned/source/scripts \
python3 -m hepta_pred1.owner_capture \
  --database /exact/existing/automation_1.sqlite3 \
  --output /exact/new/research-capture-directory \
  --clock-id ACTUAL_HOST_BOOT_CLOCK_ID \
  --start-cursor RESERVED_ARRIVAL_CURSOR \
  --limit 64
```

output 必须不存在；失败或部分产物不能覆盖重跑。
保留 `CAPTURE.json`、全部 `collection-*.json`、host/source/config 身份和完整终态。
下一页采用前页精确 `next_after` 作为 `--after-json`，`next_cursor` 作为起始到达序号。
真实 inventory 记录可单列计数；不计入训练标签、前决策预测或独立确认单位。
绝对路径和 owner identity 属私有原件；发布前审阅，不能把脱敏副本当原字节摘要。

## 5. 身份、时钟与 cursor

每条 identity 固定八项，前四项组成联合 key：

```text
owner_agent_id, run_id, step_id, attempt,
intent_digest, payload_digest, binding_digest, destination_id
```

attempt 另保留 authority_epoch、grant_id、grant_nonce_digest、record_command_id、started_at_ms。
observation/reconciliation 分别保留联合 key、observation、evidence_digest、observed_at_ms。
不要只导出 COALESCE 后结果而丢掉原 `indeterminate` 与后续 reconciliation。

- `clock_id` 绑定已验证 host 与本次 boot；Linux 可记录实际 boot_id 和 CLOCK_MONOTONIC。
- collector 的 `available_at` 是本 host 读完后的 monotonic；原生毫秒时间仅作原始 metadata。
- 不把 Unix ms 与 monotonic 相减，不跨 host/boot 直接排序；重启后必须换时钟域。
- cursor 来自与历史编码器共享的实际到达 sequencer；rowid、时间戳和 MCP cursor 均不能替代。
- 独立研究 inventory 序列必须单列身份和范围，不能声称已接入生产到达序列。
- `next_after` 是联合 key 排序分页，漏看旧 key 的晚到 observation 或排在之前的新插入。
- 晚到读回应按原 identity 重新 `collect_native`，分配新 cursor、写新 artifact，不修改旧件。
- 发现分页和逐条采集是不同事务；每条可一致，一整页并非同一数据库瞬间的原子快照。

## 6. 独立效果及不能推断的标签

`join_owner_effect` 要求下列完整字段；目标定义、单位和身份须与冻结决策一致：

```text
schema=pred1-independent-effect-v1, target_domain=independent_task_effect,
decision_digest, snapshot_digest, identity, clock_id, chosen_action,
executed_action, executed_at, execution_ref, observer_ref, evidence,
costs, full_wall_seconds, source, target_schema_sha256
```

`evidence` 保留完整 Evidence，包括 receipt_missing、awaiting、cancel_requested、时间 bounds 与 witness。
右截尾要求实际执行起点、独立非发生见证及 cutoff；timeout 或取消 ACK 不能替代。
`source=declared_owner`、`evidence.source=real` 是声明，不能自行打开 provenance authentication。
完整成本逐项保留 action/preparation/inference/training/validation/failures/recovery/transport；未知写 null。
full_wall_seconds 覆盖任务开始到效果读回，包括推理、排队和等待，不用短 effect duration 顶替。

| 已有 owner 或 transport 事实 | 不能直接生成的标签 |
| --- | --- |
| dispatch attempt 存在 | 实际开始、完成或业务成功 |
| succeeded / failed | 任务质量 1 / 0、完整成本 |
| proven_absent | 任意业务目标的失败或已执行结果 |
| 缺回执、timeout、取消请求 | 失败、零成本或有效右截尾 |
| observed_at_ms 减 started_at_ms | 完整墙钟、同源效果时长 |
| 新模型离线预测更好 | 未执行动作的因果结果、新策略实际净收益 |

原 `ActionSkillObserver` 要求独立目标观察者保留 evidence_digest 对应原件；TaskFlow只存摘要。
实际 provider host 配置可提供 lookup 来源线索，但其中可能含 headers，只读必要白名单字段。
已有历史记录无法补造当时未冻结的前决策 snapshot；此时只做来源 inventory，保留缺口。
完成真实接线、新 train/dev 采集和独立实际策略试验前，资格维持 HOLD / NoUpdate。
