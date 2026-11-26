use super::*;
use crate::ArtifactKind;
use crate::ArtifactManifest;
use crate::ArtifactState;
use codex_hepta_cell_roles::PlasticityCandidateQualificationReceiptV1;
use codex_hepta_cell_roles::RoleMetricDecisionDispositionV1;
use codex_hepta_cell_roles::RoleMetricDecisionReceiptV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Generation;
use ed25519_dalek::SigningKey;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn parent() -> ArtifactManifest {
    ArtifactManifest {
        artifact_id: id("plasticity.parent"),
        kind: ArtifactKind::Parameters,
        generation: Generation::new(1).expect("generation"),
        predecessor_id: None,
        content_digest: digest("parent-payload"),
        objective_digest: digest("objective"),
        support_digest: digest("support"),
        producer_id: id("parent-producer"),
        compatibility_digest: digest("compatibility"),
        encoded_size_bytes: 14,
    }
}

fn candidate(payload: &[u8]) -> ArtifactManifest {
    ArtifactManifest {
        artifact_id: id("plasticity.candidate"),
        kind: ArtifactKind::Parameters,
        generation: Generation::new(2).expect("generation"),
        predecessor_id: Some(id("plasticity.parent")),
        content_digest: Digest32::of_bytes(payload),
        objective_digest: digest("objective"),
        support_digest: digest("support-next"),
        producer_id: id("plasticity.producer"),
        compatibility_digest: digest("compatibility"),
        encoded_size_bytes: payload.len() as u64,
    }
}

fn registry() -> ArtifactRegistry {
    let mut registry = ArtifactRegistry::new();
    registry
        .append(ArtifactEvent::Register {
            event_id: id("register.parent"),
            manifest: parent(),
        })
        .expect("parent registry");
    registry
}

fn root(label: &str) -> std::path::PathBuf {
    let root = std::env::temp_dir().join(format!(
        "hepta-plasticity-owner-{label}-{}",
        std::process::id()
    ));
    std::fs::create_dir_all(&root).expect("root");
    root
}

#[test]
fn materialize_retain_quarantine_and_rollback_bind_exact_candidate_bytes() {
    let payload = b"candidate-parameters-v1";
    let mut registry = registry();
    let expected_head = registry.snapshot().head_digest;
    let mut owner = PlasticityCandidateOwnerV1::begin(
        id("plasticity.operation"),
        id("plasticity.producer"),
        id("plasticity.evaluator"),
        candidate(payload),
        expected_head,
    )
    .expect("begin");
    let cas = ArtifactCasOwnerV1::new(
        id("plasticity.cas-owner"),
        SigningKey::from_bytes(&[71; 32]),
    )
    .expect("cas owner");
    let root = root("lifecycle");
    let materialized = owner
        .materialize(
            &mut registry,
            &cas,
            &root,
            "candidate.bin",
            payload,
            None,
            None,
        )
        .expect("materialize");
    assert_eq!(owner.phase(), PlasticityCandidatePhaseV1::Materialized);
    assert_eq!(materialized.artifact_digest, Digest32::of_bytes(payload));
    assert_eq!(
        registry.state(&id("plasticity.candidate")),
        Some(ArtifactState::Candidate)
    );
    let forged_qualification = PlasticityCandidateQualificationReceiptV1 {
        schema: "hepta.cell-role.plasticity-candidate-qualification.v1",
        candidate_id: id("plasticity.candidate"),
        cell_id: id("plasticity.cell"),
        baseline_generation: Generation::new(1).expect("generation"),
        candidate_generation: Generation::new(2).expect("generation"),
        selected_snapshot_digest: digest("parent-payload"),
        candidate_snapshot_digest: Digest32::ZERO,
        candidate_artifact_receipt_digest: digest("artifact-receipt"),
        trust_region_digest: digest("trust"),
        rollback_predecessor_digest: digest("parent-payload"),
        no_change_baseline_digest: digest("baseline"),
        retention_receipt_digest: digest("retention"),
        forgetting_receipt_digest: digest("forgetting"),
        rollback_receipt_digest: digest("rollback"),
        resource_receipt_digest: digest("resource"),
        future_window_digest: digest("future"),
        metric_profile_digest: digest("profile"),
        metric_receipt_digest: digest("metrics"),
        proposer_id: id("plasticity.producer"),
        evaluator_id: id("plasticity.evaluator"),
        authority: AuthorityPosture::DENY_ALL,
        qualification_digest: Digest32::ZERO,
    };
    let forged_decision = RoleMetricDecisionReceiptV1 {
        schema: "hepta.cell-role.metric-decision.v1",
        cell_id: id("plasticity.cell"),
        generation: Generation::new(2).expect("generation"),
        role: codex_hepta_types::CellRoleV1::Plasticity,
        profile_digest: digest("profile"),
        policy_digest: digest("policy"),
        metric_receipt_digest: digest("metrics"),
        disposition: RoleMetricDecisionDispositionV1::Pass,
        failed_metrics: vec![],
        insufficient_metrics: vec![],
        authority: AuthorityPosture::DENY_ALL,
        decision_digest: digest("decision"),
    };
    assert_eq!(
        owner.retain_evaluated(&registry, &forged_qualification, &forged_decision),
        Err(PlasticityCandidateOwnerErrorV1::QualificationBinding)
    );
    assert_eq!(
        owner.retain(
            &registry,
            id("plasticity.producer"),
            digest("self-evidence")
        ),
        Err(PlasticityCandidateOwnerErrorV1::EvaluatorIsProducer)
    );

    let retained = owner
        .retain(
            &registry,
            id("plasticity.evaluator"),
            digest("future-window"),
        )
        .expect("retain");
    assert_eq!(retained.disposition, PlasticityCandidatePhaseV1::Retained);
    assert!(registry.is_eligible(&id("plasticity.candidate")));

    let quarantined = owner
        .quarantine(
            &mut registry,
            id("plasticity.evaluator"),
            digest("negative-transfer"),
        )
        .expect("quarantine");
    assert_eq!(
        quarantined.disposition,
        PlasticityCandidatePhaseV1::Quarantined
    );
    assert_eq!(
        registry.state(&id("plasticity.candidate")),
        Some(ArtifactState::Quarantined)
    );

    let rollback = owner.rollback(&registry).expect("rollback");
    assert!(rollback.rollback_verified);
    assert_eq!(rollback.predecessor_id, id("plasticity.parent"));
    assert!(registry.is_eligible(&id("plasticity.parent")));
    assert!(!registry.is_eligible(&id("plasticity.candidate")));
    let _ = std::fs::remove_dir_all(root);
}

#[test]
fn failed_payload_does_not_commit_registry_and_producer_cannot_evaluate() {
    let payload = b"candidate-parameters-v1";
    let mut registry = registry();
    let expected_head = registry.snapshot().head_digest;
    let mut owner = PlasticityCandidateOwnerV1::begin(
        id("plasticity.operation.failed"),
        id("plasticity.producer"),
        id("plasticity.evaluator"),
        candidate(payload),
        expected_head,
    )
    .expect("begin");
    let cas = ArtifactCasOwnerV1::new(
        id("plasticity.cas-owner.failed"),
        SigningKey::from_bytes(&[72; 32]),
    )
    .expect("cas owner");
    let root = root("failed");
    let result = owner.materialize(
        &mut registry,
        &cas,
        &root,
        "candidate.bin",
        b"wrong-payload",
        None,
        None,
    );
    assert!(result.is_err());
    assert_eq!(owner.phase(), PlasticityCandidatePhaseV1::Prepared);
    assert!(registry.manifest(&id("plasticity.candidate")).is_none());
    assert_eq!(
        owner.retain(&registry, id("plasticity.producer"), digest("evidence")),
        Err(PlasticityCandidateOwnerErrorV1::EvaluatorIsProducer)
    );
    let _ = std::fs::remove_dir_all(root);
}
