use super::*;
use codex_hepta_automation::AutomationSchedule;
use codex_hepta_automation::AutomationTaskState;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

fn owner() -> TestResult<AgentId> {
    Ok(AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dd3")?)
}

fn task(time: u64) -> TestResult<AutomationTask> {
    Ok(AutomationTask {
        task_id: AutomationTaskId::new(),
        owner_agent_id: owner()?,
        thread_id: "019153a4-3088-7e03-a56a-9b1964f75ddd".into(),
        prompt: "read-only listing".into(),
        schedule: AutomationSchedule::Once,
        state: AutomationTaskState::Completed,
        next_run_at_ms: None,
        next_occurrence: 1,
        created_at_ms: time,
        updated_at_ms: time,
    })
}

#[test]
fn live_page_accepts_only_complete_monotone_owner_bound_progress() -> TestResult {
    let previous = AutomationTaskCursorV1::from_task(&task(1)?);
    let row = task(2)?;
    let next = AutomationTaskCursorV1::from_task(&row);
    let valid = AutomationTaskPageV1 {
        tasks: vec![row],
        next_cursor: Some(next),
    };
    validate_page(&owner()?, Some(previous), 1, &valid)?;
    let terminal = AutomationTaskPageV1 {
        tasks: Vec::new(),
        next_cursor: None,
    };
    validate_page(&owner()?, Some(next), 1, &terminal)?;
    let mut invalid = valid.clone();
    invalid.next_cursor = Some(previous);
    assert!(validate_page(&owner()?, Some(previous), 1, &invalid).is_err());
    invalid = valid.clone();
    invalid.tasks.clear();
    assert!(validate_page(&owner()?, Some(previous), 1, &invalid).is_err());
    assert!(validate_page(&owner()?, Some(next), 1, &valid).is_err());
    assert!(validate_page(&owner()?, None, 0, &valid).is_err());
    invalid = valid.clone();
    invalid.tasks.push(invalid.tasks[0].clone());
    assert!(validate_page(&owner()?, None, 2, &invalid).is_err());
    invalid = valid;
    invalid.tasks[0].owner_agent_id = AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dd4")?;
    assert!(validate_page(&owner()?, None, 1, &invalid).is_err());
    Ok(())
}
