use super::AgentRunPhase;
use super::AgentRunReceipt;
use super::NativeIntelligenceRunBinding;
use super::matches_new_dispatch;

fn fixture() -> (
    AgentRunReceipt,
    AgentRunReceipt,
    NativeIntelligenceRunBinding,
) {
    let handoff = AgentRunReceipt {
        run_id: "run.objective.dispatch".to_string(),
        revision: 2,
        phase: AgentRunPhase::ContextAttached,
        context_digest: Some("a".repeat(64)),
        compilation_receipt_digest: Some("b".repeat(64)),
        authority_epoch: 11,
        generation: 2,
        fence_digest: "c".repeat(64),
        deadline_ms: 100_000,
        cancel_reason: None,
        cancel_ack_deadline_ms: None,
        terminal_observed: false,
        idempotent: true,
    };
    let dispatched = AgentRunReceipt {
        phase: AgentRunPhase::Dispatched,
        revision: 3,
        idempotent: false,
        ..handoff.clone()
    };
    let binding = NativeIntelligenceRunBinding {
        run_id: handoff.run_id.clone(),
        expected_revision: handoff.revision,
        context_digest: "a".repeat(64),
        envelope_digest: "b".repeat(64),
    };
    (handoff, dispatched, binding)
}

#[test]
fn runtime_generation_is_bound_to_handoff_not_process_spawn() {
    let process_spawn_generation = 1;
    let (handoff, dispatched, binding) = fixture();
    assert_ne!(dispatched.generation, process_spawn_generation);
    assert!(matches_new_dispatch(&dispatched, &handoff, &binding));
}

#[test]
fn dispatch_acknowledgement_cannot_drift_or_authorize_replay() {
    type Mutation = fn(&mut AgentRunReceipt);
    let cases: &[(&str, Mutation)] = &[
        ("run", |r| r.run_id.push('x')),
        ("phase", |r| r.phase = AgentRunPhase::ContextAttached),
        ("revision", |r| r.revision += 1),
        ("generation", |r| r.generation = 1),
        ("fence", |r| r.fence_digest = "d".repeat(64)),
        ("authority", |r| r.authority_epoch += 1),
        ("deadline", |r| r.deadline_ms += 1),
        ("context", |r| r.context_digest = Some("d".repeat(64))),
        ("envelope", |r| {
            r.compilation_receipt_digest = Some("d".repeat(64))
        }),
        ("terminal", |r| r.terminal_observed = true),
        ("replay", |r| r.idempotent = true),
        ("cancel", |r| {
            r.cancel_reason = Some("cancelled".to_string())
        }),
        ("cancel acknowledgement", |r| {
            r.cancel_ack_deadline_ms = Some(50)
        }),
    ];
    let (handoff, dispatched, binding) = fixture();
    for (name, mutate) in cases {
        let mut changed = dispatched.clone();
        mutate(&mut changed);
        assert_ne!(changed, dispatched, "mutation {name} must be effective");
        assert!(
            !matches_new_dispatch(&changed, &handoff, &binding),
            "accepted {name}"
        );
    }
}

#[test]
fn dispatch_revision_overflow_and_invalid_handoff_are_rejected() {
    let (mut handoff, dispatched, mut binding) = fixture();
    handoff.revision = u64::MAX;
    binding.expected_revision = u64::MAX;
    assert!(!matches_new_dispatch(&dispatched, &handoff, &binding));
    let (mut handoff, dispatched, binding) = fixture();
    handoff.phase = AgentRunPhase::Dispatched;
    assert!(!matches_new_dispatch(&dispatched, &handoff, &binding));
}
