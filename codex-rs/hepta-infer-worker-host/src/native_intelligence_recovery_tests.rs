use super::*;

use codex_hepta_agentd::AgentRunReceipt;
use codex_hepta_agentd::AgentRunReconciliationState;
use codex_hepta_agentd::AgentRunSnapshot;

struct TerminalPublicationHook {
    reached: tokio::sync::Notify,
    release: tokio::sync::Notify,
}

static TERMINAL_PUBLICATION_HOOK: std::sync::Mutex<
    Option<std::sync::Arc<TerminalPublicationHook>>,
> = std::sync::Mutex::new(None);

pub(super) async fn pause_before_terminal_publication() {
    let hook = TERMINAL_PUBLICATION_HOOK
        .lock()
        .expect("terminal publication hook lock")
        .take();
    if let Some(hook) = hook {
        hook.reached.notify_one();
        hook.release.notified().await;
    }
}

fn output() -> NativeRunOutput {
    NativeRunOutput {
        thread_id: "thread.1".to_string(),
        turn_id: "turn.1".to_string(),
        model: "model".to_string(),
        model_provider: "provider".to_string(),
        status: NativeRunStatus::Completed,
        boundary_status: NativeBoundaryStatus::Succeeded,
        output: "observed response".to_string(),
        observed_output_tokens: Some(17),
        terminal_observed: true,
        stop_reason: None,
        owner_authority: NativeOwnerAuthority::ObservedReady,
        codex_terminal_correlation_digest: Some("c".repeat(64)),
    }
}

#[test]
fn terminal_publication_preserves_local_boundary_and_authority_loss() {
    let observed = output();
    for (boundary, phase) in [
        (NativeBoundaryStatus::Succeeded, AgentRunPhase::Succeeded),
        (NativeBoundaryStatus::Failed, AgentRunPhase::Failed),
        (NativeBoundaryStatus::TimedOut, AgentRunPhase::Failed),
        (NativeBoundaryStatus::Quarantined, AgentRunPhase::Failed),
        (NativeBoundaryStatus::Interrupted, AgentRunPhase::Cancelled),
        (NativeBoundaryStatus::Cancelled, AgentRunPhase::Cancelled),
    ] {
        let mut value = observed.clone();
        value.boundary_status = boundary;
        assert_eq!(terminal_phase(&value).unwrap(), Some(phase));
    }
    for status in [NativeRunStatus::Failed, NativeRunStatus::Interrupted] {
        let mut value = observed.clone();
        value.status = status;
        assert!(terminal_phase(&value).is_err());
        value.boundary_status = NativeBoundaryStatus::Cancelled;
        assert_eq!(
            terminal_phase(&value).unwrap(),
            Some(AgentRunPhase::Cancelled)
        );
    }
    for authority in [
        NativeOwnerAuthority::Unverified,
        NativeOwnerAuthority::Lost {
            reason: "previous owner lost".to_string(),
        },
    ] {
        let mut value = observed.clone();
        value.owner_authority = authority;
        assert!(terminal_phase(&value).is_err());
    }
    for correlation in [None, Some("0".repeat(64)), Some("invalid".to_string())] {
        let mut value = observed.clone();
        value.codex_terminal_correlation_digest = correlation;
        assert!(terminal_phase(&value).is_err());
    }
    let mut annotated_success = observed.clone();
    annotated_success.stop_reason = Some("success qualification not established".to_string());
    assert!(terminal_phase(&annotated_success).is_err());
    let mut unknown = observed;
    unknown.terminal_observed = false;
    unknown.status = NativeRunStatus::Indeterminate;
    unknown.codex_terminal_correlation_digest = None;
    assert_eq!(terminal_phase(&unknown).unwrap(), None);
}

#[test]
fn current_revision_does_not_relax_original_snapshot_binding() {
    let binding = NativeIntelligenceRunBinding {
        snapshot: AgentRunSnapshot {
            run_id: "intelligence.run".to_string(),
            request_digest: "1".repeat(64),
            objective_digest: "2".repeat(64),
            body_digest: "3".repeat(64),
            artifact_set_digest: "4".repeat(64),
            authority_epoch: 9,
            generation: 2,
            fence_digest: "d".repeat(64),
            deadline_ms: 10_000,
        },
        expected_revision: 2,
        context_digest: "a".repeat(64),
        envelope_digest: "b".repeat(64),
    };
    let current = AgentRunReconciliationState {
        snapshot: binding.snapshot.clone(),
        receipt: AgentRunReceipt {
            run_id: binding.snapshot.run_id.clone(),
            revision: 5,
            phase: AgentRunPhase::Indeterminate,
            context_digest: Some(binding.context_digest.clone()),
            compilation_receipt_digest: Some(binding.envelope_digest.clone()),
            authority_epoch: binding.snapshot.authority_epoch,
            generation: binding.snapshot.generation,
            fence_digest: binding.snapshot.fence_digest.clone(),
            deadline_ms: binding.snapshot.deadline_ms,
            cancel_reason: None,
            cancel_ack_deadline_ms: None,
            terminal_observed: false,
            idempotent: false,
        },
    };
    binding.validate_current(&current).unwrap();
    for field in 0..9 {
        let mut changed = current.clone();
        match field {
            0 => changed.snapshot.run_id.push_str(".other"),
            1 => changed.snapshot.request_digest = "e".repeat(64),
            2 => changed.snapshot.objective_digest = "e".repeat(64),
            3 => changed.snapshot.body_digest = "e".repeat(64),
            4 => changed.snapshot.artifact_set_digest = "e".repeat(64),
            5 => changed.snapshot.authority_epoch += 1,
            6 => changed.snapshot.generation += 1,
            7 => changed.snapshot.fence_digest = "e".repeat(64),
            _ => changed.snapshot.deadline_ms += 1,
        }
        assert!(binding.validate_current(&changed).is_err());
    }
    for field in 0..9 {
        let mut changed = current.clone();
        match field {
            0 => changed.receipt.run_id.push_str(".other"),
            1 => changed.receipt.generation += 1,
            2 => changed.receipt.revision = binding.expected_revision - 1,
            3 => changed.receipt.context_digest = Some("e".repeat(64)),
            4 => changed.receipt.compilation_receipt_digest = Some("f".repeat(64)),
            5 => changed.receipt.compilation_receipt_digest = None,
            6 => changed.receipt.authority_epoch += 1,
            7 => changed.receipt.fence_digest = "e".repeat(64),
            _ => changed.receipt.deadline_ms += 1,
        }
        assert!(binding.validate_current(&changed).is_err());
    }
}
