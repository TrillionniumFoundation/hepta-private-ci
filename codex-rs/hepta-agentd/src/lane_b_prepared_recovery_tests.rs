//! Pure reducer validation only. Real ledger proof refusal and Core/Queue
//! same-turn recovery are tested through their original owners; these tests
//! do not manufacture ProductionUnusedScope or a sealed journal handoff.

use pretty_assertions::assert_eq;

use super::*;

fn digest(label: &str) -> String {
    codex_hepta_types::Digest32::of_bytes(label.as_bytes()).to_string()
}

fn original() -> (RunSnapshot, RunReceipt, RunRecord) {
    let snapshot = RunSnapshot {
        run_id: "run.original.prepared".to_owned(), request_digest: digest("request"),
        objective_digest: digest("objective"), body_digest: digest("body"),
        artifact_set_digest: digest("artifacts"), authority_epoch: 9, generation: 7,
        fence_digest: digest("fence"), deadline_ms: 20_000,
    };
    let mut record = RunRecord {
        snapshot: snapshot.clone(), revision: 2, phase: RunPhase::ContextAttached,
        context_digest: Some(digest("context")), compilation_receipt_digest: Some(digest("compilation")),
        cancel_reason: None, cancel_ack_deadline_ms: None, canonical_queued: None,
    };
    let attached = receipt(&record, /*idempotent*/ false);
    record.phase = RunPhase::Dispatched;
    record.revision = 3;
    (snapshot, attached, record)
}

#[test]
fn replacing_an_attached_plan_skips_its_already_reserved_first_dispatch_revision() {
    for attached in [0, 2, 17, u64::MAX - 2] {
        let old_initial_revision = attached + 1;
        assert_eq!(replacement_attachment_revision(attached), Ok(old_initial_revision + 1));
    }
    for attached in [u64::MAX - 1, u64::MAX] {
        assert_eq!(replacement_attachment_revision(attached), Err(AgentRunError::ArithmeticOverflow));
    }
}

#[test]
fn retained_preparation_preserves_identity_and_advances_each_new_core_attempt() {
    let (snapshot, attached, mut record) = original();
    assert_eq!(prepared_repair_transition(1_000, &snapshot, &attached, &record),
        Ok(PreparedRepairTransition { revision: 4 }));
    record.revision = 17;
    assert_eq!(prepared_repair_transition(1_000, &snapshot, &attached, &record),
        Ok(PreparedRepairTransition { revision: 18 }),
        "the journal's old attachment revision cannot overwrite a later dispatched revision");
    record.phase = RunPhase::Indeterminate;
    assert_eq!(prepared_repair_transition(1_000, &snapshot, &attached, &record),
        Ok(PreparedRepairTransition { revision: 18 }));
    assert_eq!(record.revision, 17, "read-only validation must not itself apply a transition");
    assert_eq!(record.phase, RunPhase::Indeterminate);
}

#[test]
fn dispatched_preparation_repair_rejects_cancelled_and_terminal_observations() {
    let (snapshot, attached, record) = original();
    for phase in [RunPhase::Admitted, RunPhase::ContextAttached, RunPhase::Cancelling,
        RunPhase::Cancelled, RunPhase::Succeeded, RunPhase::Failed]
    {
        let mut observed = record.clone();
        observed.phase = phase;
        observed.revision = 10;
        assert_eq!(prepared_repair_transition(1_000, &snapshot, &attached, &observed),
            Err(AgentRunError::InvalidTransition), "phase {phase:?}");
    }
    for phase in [RunPhase::Dispatched, RunPhase::Indeterminate] {
        let mut observed = record.clone();
        observed.phase = phase;
        observed.cancel_reason = Some("original turn cancelled".to_owned());
        assert_eq!(prepared_repair_transition(1_000, &snapshot, &attached, &observed),
            Err(AgentRunError::InvalidTransition));
        observed.cancel_reason = None;
        observed.cancel_ack_deadline_ms = Some(4_000);
        assert_eq!(prepared_repair_transition(1_000, &snapshot, &attached, &observed),
            Err(AgentRunError::InvalidTransition), "an outstanding cancellation cannot be erased");
    }
}

#[test]
fn retained_preparation_rejects_changed_original_snapshot_and_compiled_context() {
    let (snapshot, attached, record) = original();
    let mutations: [fn(&mut RunSnapshot); 9] = [
        |value| value.run_id = "run.other".to_owned(),
        |value| value.request_digest = digest("other.request"),
        |value| value.objective_digest = digest("other.objective"),
        |value| value.body_digest = digest("other.body"),
        |value| value.artifact_set_digest = digest("other.artifacts"),
        |value| value.authority_epoch += 1,
        |value| value.generation += 1,
        |value| value.fence_digest = digest("other.fence"),
        |value| value.deadline_ms += 1,
    ];
    for mutate in mutations {
        let mut changed = record.clone();
        mutate(&mut changed.snapshot);
        assert_eq!(prepared_repair_transition(1_000, &snapshot, &attached, &changed),
            Err(AgentRunError::MixedSnapshot));
    }
    let mut changed = record.clone();
    changed.context_digest = Some(digest("other.context"));
    assert_eq!(prepared_repair_transition(1_000, &snapshot, &attached, &changed),
        Err(AgentRunError::MixedSnapshot));
    let mut changed = record;
    changed.compilation_receipt_digest = None;
    assert_eq!(prepared_repair_transition(1_000, &snapshot, &attached, &changed),
        Err(AgentRunError::MixedSnapshot));
}

#[test]
fn retained_preparation_rejects_expiry_old_revision_and_revision_exhaustion() {
    let (snapshot, attached, mut record) = original();
    for now in [snapshot.deadline_ms, snapshot.deadline_ms + 1] {
        assert_eq!(prepared_repair_transition(now, &snapshot, &attached, &record),
            Err(AgentRunError::InvalidDeadline));
    }
    for phase in [RunPhase::Dispatched, RunPhase::Indeterminate] {
        record.phase = phase;
        record.revision = attached.revision;
        assert_eq!(prepared_repair_transition(1_000, &snapshot, &attached, &record),
            Err(AgentRunError::StaleRevision), "an attachment cannot supply a missing dispatch revision");
    }
    record.phase = RunPhase::Indeterminate;
    record.revision = u64::MAX;
    assert_eq!(prepared_repair_transition(1_000, &snapshot, &attached, &record),
        Err(AgentRunError::ArithmeticOverflow));
    let mut impossible_attachment = attached;
    impossible_attachment.revision = u64::MAX;
    assert_eq!(prepared_repair_transition(1_000, &snapshot, &impossible_attachment, &record),
        Err(AgentRunError::ArithmeticOverflow));
}
