#!/usr/bin/env python3
"""One-shot exact-source repair for the schema-22 TaskFlow qualification blockers."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if new in text:
        if old in text:
            raise SystemExit(f"both old and new forms are present in {relative}")
        return
    if text.count(old) != 1:
        raise SystemExit(f"expected exactly one old form in {relative}")
    path.write_text(text.replace(old, new), encoding="utf-8")


replace_once(
    "codex-rs/hepta-automation/src/taskflow_bounded.rs",
    '''    for table in ["taskflow_definitions", "taskflow_runs", "taskflow_events"] {
        let query = format!("SELECT COUNT(*) FROM {table} WHERE owner_agent_id != ?");
        let count: i64 = sqlx::query_scalar(&query)
            .bind(expected_owner.as_str())
            .fetch_one(&mut **tx)
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        if count != 0 {
            return Err(TaskFlowError::StaleFence);
        }
    }
''',
    '''    let foreign_definitions: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM taskflow_definitions WHERE owner_agent_id != ?",
    )
    .bind(expected_owner.as_str())
    .fetch_one(&mut **tx)
    .await
    .map_err(|_| TaskFlowError::Unavailable)?;
    let foreign_runs: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM taskflow_runs WHERE owner_agent_id != ?")
            .bind(expected_owner.as_str())
            .fetch_one(&mut **tx)
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
    let foreign_events: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM taskflow_events WHERE owner_agent_id != ?")
            .bind(expected_owner.as_str())
            .fetch_one(&mut **tx)
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
    if foreign_definitions != 0 || foreign_runs != 0 || foreign_events != 0 {
        return Err(TaskFlowError::StaleFence);
    }
''',
)

replace_once(
    "scripts/automation_taskflow_contract.py",
    '''    ".github/workflows/automation-taskflow-selected-host.yml": ("hepta-automation-selected-host", "expected_tzdb_sha256", "multi_scheduler_race", "runtime_crash_points", "PROVIDER_IDENTITY_SHA256", "automation-taskflow-selected-host-receipt.json"),
''',
    '''    ".github/workflows/automation-taskflow-selected-host.yml": ("hepta-automation-selected-host", "AUTOMATION_TIMEZONE_PROFILE_FILE", "--test durable_neural_circuit", "--test durable_neural_circuit_recovery", "automation-taskflow-selected-host-receipt.json"),
''',
)

focused = (ROOT / ".github/workflows/automation-taskflow-focused.yml").read_text(encoding="utf-8")
if "codex-rs/hepta-automation/src/taskflow_bounded.rs" not in focused:
    raise SystemExit("focused source export omits taskflow_bounded.rs")

print("automation.taskflow focused qualification blockers repaired")
