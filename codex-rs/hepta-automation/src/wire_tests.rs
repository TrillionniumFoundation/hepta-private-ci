use crate::AuthorizedEffectIntent;
use crate::AutomationCalendarScheduleV2;
use crate::AutomationTaskDraft;
use serde_json::json;

#[test]
fn task_and_calendar_round_trip_without_storage() -> Result<(), serde_json::Error> {
    let task = json!({
        "task_id": "01900000-0000-7000-8000-000000000001",
        "thread_id": "01900000-0000-7000-8000-000000000002", "prompt": "retained prompt",
        "schedule": {"kind": "fixed_interval", "interval_ms": 1000},
        "first_run_at_ms": 2000, "created_at_ms": 1000
    });
    let decoded: AutomationTaskDraft = serde_json::from_value(task.clone())?;
    assert_eq!(serde_json::to_value(decoded)?, task);
    let digest = "a".repeat(64);
    let calendar = json!({
        "timezone_id": "UTC", "tzdb_digest": digest, "start_at_utc_ms": 1000,
        "end_at_utc_ms": null, "every_days": 1, "local_time_ms": 0,
        "dst_gap_policy": "skip", "dst_overlap_policy": "first",
        "clock_profile": {"timezone_id": "UTC", "tzdb_digest": digest,
            "valid_from_utc_ms": 0, "valid_until_utc_ms": 86400000,
            "initial_offset_seconds": 0, "transitions": []}
    });
    let decoded: AutomationCalendarScheduleV2 = serde_json::from_value(calendar.clone())?;
    assert_eq!(serde_json::to_value(decoded)?, calendar);
    Ok(())
}

#[test]
fn effect_transport_keeps_binding_fields_and_rejects_unknown_fields()
-> Result<(), serde_json::Error> {
    let digest = "b".repeat(64);
    let mut value = json!({
        "run_id": "run.1", "step_id": "step.1", "attempt": 1,
        "operation_id": "operation.1", "subject_id": "agent.1", "destination_id": "timer.1",
        "payload_digest": digest, "final_use_scope_digest": digest, "policy_generation": 7,
        "expected_predecessor_digest": null,
        "dependencies": [{"step_id": "step.0", "state_digest": digest}],
        "compensation_for": null
    });
    let decoded: AuthorizedEffectIntent = serde_json::from_value(value.clone())?;
    assert_eq!(serde_json::to_value(decoded)?, value);
    value["grant_authority"] = json!(true);
    assert!(serde_json::from_value::<AuthorizedEffectIntent>(value).is_err());
    Ok(())
}
