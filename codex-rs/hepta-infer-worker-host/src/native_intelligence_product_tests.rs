use super::*;
use crate::native_app_server::NativeOwnerAuthority;
use codex_hepta_infer_core::durable_control::native::NativeBoundaryStatus;

fn physical(status: NativeRunStatus) -> NativeRunOutput {
    NativeRunOutput {
        thread_id: "thread-terminal".to_string(),
        turn_id: "turn-terminal".to_string(),
        model: "model".to_string(),
        model_provider: "provider".to_string(),
        status,
        boundary_status: match status {
            NativeRunStatus::Completed => NativeBoundaryStatus::Succeeded,
            NativeRunStatus::Failed => NativeBoundaryStatus::Failed,
            NativeRunStatus::Interrupted => NativeBoundaryStatus::Interrupted,
            NativeRunStatus::Indeterminate => NativeBoundaryStatus::Indeterminate,
        },
        output: "exact durable provider observation".to_string(),
        observed_output_tokens: Some(17),
        terminal_observed: status != NativeRunStatus::Indeterminate,
        stop_reason: None,
        owner_authority: NativeOwnerAuthority::ObservedReady,
        codex_terminal_correlation_digest: Some("a".repeat(64)),
    }
}

fn owner(phase: AgentRunPhase) -> AgentRunReceipt {
    AgentRunReceipt {
        run_id: "run-terminal".to_string(),
        revision: 4,
        phase,
        context_digest: Some("b".repeat(64)),
        authority_epoch: 7,
        generation: 2,
        fence_digest: "c".repeat(64),
        deadline_ms: 19_000,
        cancel_reason: None,
        cancel_ack_deadline_ms: None,
        compilation_receipt_digest: Some("d".repeat(64)),
        terminal_observed: true,
        idempotent: true,
    }
}

#[test]
fn only_matching_physical_and_agentd_terminal_phases_reach_outcome_evidence() {
    for (status, owner_phase, phase) in [
        (
            NativeRunStatus::Completed,
            AgentRunPhase::Succeeded,
            RunPhase::Succeeded,
        ),
        (
            NativeRunStatus::Failed,
            AgentRunPhase::Failed,
            RunPhase::Failed,
        ),
        (
            NativeRunStatus::Interrupted,
            AgentRunPhase::Cancelled,
            RunPhase::Cancelled,
        ),
    ] {
        let execution = physical(status);
        let observed = owner(owner_phase);
        let expected = RunReceipt {
            run_id: observed.run_id.clone(),
            revision: observed.revision,
            phase,
            context_digest: observed.context_digest.clone(),
            authority_epoch: observed.authority_epoch,
            generation: observed.generation,
            fence_digest: observed.fence_digest.clone(),
            deadline_ms: observed.deadline_ms,
            cancel_reason: observed.cancel_reason.clone(),
            cancel_ack_deadline_ms: observed.cancel_ack_deadline_ms,
            compilation_receipt_digest: observed.compilation_receipt_digest.clone(),
            terminal_observed: observed.terminal_observed,
            idempotent: observed.idempotent,
        };
        assert_eq!(
            local_terminal_receipt_v1(observed, &execution),
            Ok(expected)
        );
    }
}

#[test]
fn conflicting_terminal_phases_stop_outcome_evidence_and_preserve_physical_truth() {
    for (status, matching) in [
        (NativeRunStatus::Completed, AgentRunPhase::Succeeded),
        (NativeRunStatus::Failed, AgentRunPhase::Failed),
        (NativeRunStatus::Interrupted, AgentRunPhase::Cancelled),
    ] {
        for phase in [
            AgentRunPhase::Succeeded,
            AgentRunPhase::Failed,
            AgentRunPhase::Cancelled,
        ] {
            if phase == matching {
                continue;
            }
            let execution = physical(status);
            let original = execution.clone();
            assert_eq!(
                local_terminal_receipt_v1(owner(phase), &execution),
                Err("terminal Agentd phase differs from physical observation"),
            );
            assert_eq!(execution, original);
        }
    }
}

#[test]
fn nonterminal_physical_or_agentd_observations_cannot_reach_outcome_evidence() {
    let mut execution = physical(NativeRunStatus::Completed);
    execution.terminal_observed = false;
    assert_eq!(
        local_terminal_receipt_v1(owner(AgentRunPhase::Succeeded), &execution),
        Err("physical terminal observation unavailable"),
    );
    assert_eq!(
        local_terminal_receipt_v1(
            owner(AgentRunPhase::Succeeded),
            &physical(NativeRunStatus::Indeterminate),
        ),
        Err("physical terminal observation unavailable"),
    );
    for phase in [
        AgentRunPhase::Admitted,
        AgentRunPhase::ContextAttached,
        AgentRunPhase::Dispatched,
        AgentRunPhase::Cancelling,
        AgentRunPhase::Indeterminate,
    ] {
        assert_eq!(
            local_terminal_receipt_v1(owner(phase), &physical(NativeRunStatus::Completed)),
            Err("terminal Agentd receipt not verified"),
        );
    }
    let mut unobserved = owner(AgentRunPhase::Succeeded);
    unobserved.terminal_observed = false;
    assert_eq!(
        local_terminal_receipt_v1(unobserved, &physical(NativeRunStatus::Completed)),
        Err("terminal Agentd receipt not verified"),
    );
}
