use super::*;

use codex_hepta_intelligence::IntelligenceHostEnvelopeInputV1;
use codex_hepta_types::StableId;

use crate::RunSnapshot;
use crate::RuntimeComposition;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn composition() -> RuntimeComposition {
    RuntimeComposition {
        agent_id: "agent.one".to_string(),
        supervisor_generation: 1,
        agentd_generation: 1,
        configuration_digest: digest("configuration").to_string(),
        ports_digest: digest("ports").to_string(),
    }
}

fn snapshot() -> RunSnapshot {
    RunSnapshot {
        run_id: "run.v3".to_string(),
        request_digest: digest("request").to_string(),
        objective_digest: digest("objective").to_string(),
        body_digest: digest("body").to_string(),
        artifact_set_digest: digest("artifacts").to_string(),
        authority_epoch: 1,
        deadline_ms: 10_000,
    }
}

fn attachment() -> ContextAttachment {
    let snapshot = snapshot();
    ContextAttachment {
        run_id: snapshot.run_id,
        request_digest: snapshot.request_digest,
        objective_digest: snapshot.objective_digest,
        body_digest: snapshot.body_digest,
        artifact_set_digest: snapshot.artifact_set_digest,
        context_digest: digest("context").to_string(),
        compilation_receipt_digest: digest("context-receipt").to_string(),
    }
}

fn envelope() -> IntelligenceHostEnvelopeV1 {
    IntelligenceHostEnvelopeV1::new(IntelligenceHostEnvelopeInputV1 {
        run_id: StableId::new("run.v3").expect("run id"),
        request_digest: digest("request"),
        snapshot_digest: digest("intelligence-snapshot"),
        objective_digest: digest("objective"),
        legal_candidate_set_digest: digest("candidate-set"),
        utility_digest: digest("utility"),
        evaluation_digest: digest("evaluation"),
        intuition_digest: digest("intuition"),
        context_digest: digest("context"),
        composition_trace_digest: digest("composition-trace"),
    })
    .expect("envelope")
}

fn attached_coordinator() -> AgentRunCoordinator {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("runtime");
    coordinator.start_run(1, snapshot()).expect("start");
    coordinator
        .attach_context(1, attachment())
        .expect("attach context");
    coordinator
}

#[test]
fn intelligence_handoff_is_proposal_only_and_preserves_lane_b_phase() {
    let mut coordinator = attached_coordinator();
    let envelope = envelope();
    let proposal = prepare_intelligence_dispatch_v1(
        &mut coordinator,
        2,
        &attachment(),
        &envelope,
    )
    .expect("dispatch proposal");

    assert_eq!(proposal.envelope_digest, envelope.envelope_digest);
    assert_eq!(proposal.context_digest, digest("context"));
    assert!(!proposal.authority.grants_any());
    assert!(!proposal.proposal_digest.is_zero());
    let current = coordinator.run("run.v3").expect("run");
    assert_eq!(current.phase, RunPhase::ContextAttached);
    assert_eq!(current.revision, 2);

    let dispatched = coordinator
        .mark_dispatched("run.v3", 2)
        .expect("real dispatch entry");
    assert_eq!(dispatched.phase, RunPhase::Dispatched);
}

#[test]
fn envelope_objective_drift_is_rejected_without_dispatch_transition() {
    let mut coordinator = attached_coordinator();
    let mut envelope = envelope();
    envelope.objective_digest = digest("different-objective");
    envelope.envelope_digest = IntelligenceHostEnvelopeV1::new(IntelligenceHostEnvelopeInputV1 {
        run_id: envelope.run_id.clone(),
        request_digest: envelope.request_digest,
        snapshot_digest: envelope.snapshot_digest,
        objective_digest: envelope.objective_digest,
        legal_candidate_set_digest: envelope.legal_candidate_set_digest,
        utility_digest: envelope.utility_digest,
        evaluation_digest: envelope.evaluation_digest,
        intuition_digest: envelope.intuition_digest,
        context_digest: envelope.context_digest,
        composition_trace_digest: envelope.composition_trace_digest,
    })
    .expect("resigned envelope")
    .envelope_digest;

    assert_eq!(
        prepare_intelligence_dispatch_v1(&mut coordinator, 2, &attachment(), &envelope),
        Err(IntelligenceHandoffErrorV1::Binding(
            "run/request/objective/context"
        ))
    );
    assert_eq!(
        coordinator.run("run.v3").expect("run").phase,
        RunPhase::ContextAttached
    );
}

#[test]
fn forged_attachment_is_checked_against_the_stored_run_snapshot() {
    let mut coordinator = attached_coordinator();
    let mut forged = attachment();
    forged.request_digest = digest("different-request").to_string();

    assert_eq!(
        prepare_intelligence_dispatch_v1(&mut coordinator, 2, &forged, &envelope()),
        Err(IntelligenceHandoffErrorV1::Run(
            AgentRunError::MixedSnapshot
        ))
    );
    assert_eq!(
        coordinator.run("run.v3").expect("run").phase,
        RunPhase::ContextAttached
    );
}
