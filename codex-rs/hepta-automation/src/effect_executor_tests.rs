use super::*;

#[derive(Debug)]
struct Driver {
    terminal: bool,
    succeeded: bool,
}

impl EffectDriver for Driver {
    fn dispatch(
        &mut self,
        _occurrence: &Occurrence,
        _claim: &Claim,
        _intent: &StepIntent,
    ) -> Result<EffectObservation, Error> {
        Ok(EffectObservation {
            terminal_observed: self.terminal,
            succeeded: self.succeeded,
            outcome_digest: self.terminal.then(|| "9".repeat(64)),
        })
    }
}

fn occurrence() -> Occurrence {
    Occurrence {
        occurrence_id: "occurrence.1".to_string(),
        schedule_id: "schedule.1".to_string(),
        schedule_revision: 1,
        scheduled_unix_ms: 1_000,
        graph_generation: 2,
    }
}

fn claim(fence: u64) -> Claim {
    Claim {
        occurrence_id: "occurrence.1".to_string(),
        fence,
        claimant_id: "scheduler.1".to_string(),
        expires_at_ms: 10_000,
    }
}

fn intent(operation: &str, step: &str) -> StepIntent {
    StepIntent {
        step_id: step.to_string(),
        operation_id: operation.to_string(),
        authority_epoch: 4,
        semantic_digest: "1".repeat(64),
        final_payload_digest: "2".repeat(64),
        grant_payload_digest: "2".repeat(64),
        deadline_ms: 9_000,
        dependencies: Vec::new(),
        compensation_for: None,
    }
}

#[test]
fn current_fence_executes_once() {
    let mut executor = TaskFlowExecutor::new(Driver {
        terminal: true,
        succeeded: true,
    });
    executor
        .register_occurrence(occurrence())
        .expect("occurrence");
    executor.claim_occurrence(100, claim(7)).expect("claim");
    let first = executor
        .execute_step(100, "occurrence.1", 7, intent("operation.1", "step.1"))
        .expect("execute");
    assert_eq!(first.state, StepState::Succeeded);
    let second = executor
        .execute_step(100, "occurrence.1", 7, intent("operation.1", "step.1"))
        .expect("idempotent");
    assert!(second.idempotent);
}

#[test]
fn stale_fence_and_unknown_effect_fail_closed() {
    let mut executor = TaskFlowExecutor::new(Driver {
        terminal: false,
        succeeded: false,
    });
    executor
        .register_occurrence(occurrence())
        .expect("occurrence");
    executor.claim_occurrence(100, claim(3)).expect("claim");
    assert_eq!(
        executor.execute_step(100, "occurrence.1", 2, intent("operation.1", "step.1")),
        Err(Error::StaleFence)
    );
    let result = executor
        .execute_step(100, "occurrence.1", 3, intent("operation.1", "step.1"))
        .expect("execute");
    assert_eq!(result.state, StepState::Indeterminate);
    let mut dependent = intent("operation.2", "step.2");
    dependent.dependencies.push("step.1".to_string());
    assert_eq!(
        executor.execute_step(100, "occurrence.1", 3, dependent),
        Err(Error::DependencyNotTerminal)
    );
}
