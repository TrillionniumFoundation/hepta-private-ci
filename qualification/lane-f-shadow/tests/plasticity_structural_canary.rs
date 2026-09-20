use std::fs::OpenOptions;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use codex_hepta_intelligence::{
    AuthenticatedStructuralCanaryErrorV1, observe_authenticated_structural_canary_v1,
    structural_canary_observation_signing_payload_v1,
};
use codex_hepta_learning_ledger::{
    AuthenticatedPrincipalV1, LearningEvidenceRoleV1, LearningEvidenceTrustV1,
    LearningEvidenceVerifierV1, SignedEvidenceError, SignedLearningEvidenceV1,
    TrustedLearningSignerV1,
};
use codex_hepta_plasticity::{
    DurableTopologyProposalRegistryV1, GovernedTopologyProposalV1, ProposalWindowV2,
    StructuralCanaryControllerV1, StructuralCanaryObservationV1, StructuralCanaryStateV1,
    TopologyChangeV2, TopologyOperationV2, TopologyProposalRequestV2, WriterHandoffPlanV1,
    admit_governed_topology_v1, build_structural_canary_plan_v1, build_writer_handoff_plan_v1,
    propose_topology_v2,
};
use codex_hepta_types::{Digest32, Generation, StableId};
use ed25519_dalek::{Signer, SigningKey};

struct TestFile {
    path: PathBuf,
}

impl TestFile {
    fn new(label: &str) -> Self {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        Self {
            path: std::env::temp_dir().join(format!(
                "hepta-plasticity-{label}-{}-{nonce}.journal",
                std::process::id()
            )),
        }
    }

    fn create(&self) -> std::fs::File {
        OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(&self.path)
            .expect("create qualification registry")
    }

    fn open(&self) -> std::fs::File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(&self.path)
            .expect("open qualification registry")
    }
}

impl Drop for TestFile {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.path);
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).expect("valid id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("valid generation")
}

fn canary_observer() -> (LearningEvidenceVerifierV1, SigningKey, AuthenticatedPrincipalV1) {
    let key = SigningKey::from_bytes(&[23_u8; 32]);
    let scope = digest("canary:scope");
    let objective = digest("canary:objective");
    let principal = AuthenticatedPrincipalV1 {
        principal_id: id("observer:structural-canary"),
        credential_chain_digest: digest("canary:credential"),
        signing_key_digest: Digest32::of_bytes(key.verifying_key().as_bytes()),
        scope_digest: scope,
        authority_epoch: 7,
        authenticated_at: 40,
        expires_at: 80,
    };
    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: scope,
        objective_digest: objective,
        authority_epoch: 7,
        signers: vec![TrustedLearningSignerV1 {
            principal: principal.clone(),
            controller_id: id("controller:structural-canary"),
            verifying_key: key.verifying_key().to_bytes(),
            roles: vec![LearningEvidenceRoleV1::Observer],
            revoked_at: None,
        }],
    })
    .expect("canary verifier");
    (verifier, key, principal)
}

fn sign_canary_observation(
    verifier: &LearningEvidenceVerifierV1,
    key: &SigningKey,
    principal: &AuthenticatedPrincipalV1,
    plan_digest: Digest32,
    observation: &StructuralCanaryObservationV1,
    sequence: u64,
) -> SignedLearningEvidenceV1 {
    let payload = structural_canary_observation_signing_payload_v1(plan_digest, observation)
        .expect("canary signing payload");
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(&format!("canary:evidence:{sequence}")),
        principal_id: principal.principal_id.clone(),
        role: LearningEvidenceRoleV1::Observer,
        trust_digest: verifier.trust_digest(),
        scope_digest: principal.scope_digest,
        objective_digest: digest("canary:objective"),
        authority_epoch: principal.authority_epoch,
        issued_at: 45,
        expires_at: 70,
        payload_digest: Digest32::of_bytes(&payload),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    evidence
}

fn governed_topology() -> (GovernedTopologyProposalV1, WriterHandoffPlanV1) {
    let handoff = build_writer_handoff_plan_v1(
        id("module:adaptive-head"),
        id("owner:current"),
        id("owner:next"),
        12,
        13,
        digest("source-store"),
        digest("migration"),
        digest("rollback"),
        digest("ack-contract"),
    )
    .expect("writer handoff");
    let selected_artifact = digest("selected-artifact");
    let proposal = propose_topology_v2(TopologyProposalRequestV2 {
        proposal_id: id("topology:qualification:1"),
        proposer_id: id("learning.plasticity.generator"),
        evaluator_id: id("learning.eval.independent"),
        selected_artifact_digest: selected_artifact,
        window: ProposalWindowV2 {
            window_id: id("window:qualification:1"),
            window_digest: digest("window"),
        },
        baseline_generation: generation(12),
        candidate_generation: generation(13),
        evaluation_digest: digest("independent-evaluation"),
        rollback_predecessor_digest: selected_artifact,
        changes: vec![TopologyChangeV2 {
            module_id: id("module:adaptive-head"),
            operation: TopologyOperationV2::Rewire,
            predecessor_digest: Some(digest("topology:12")),
            candidate_digest: Some(digest("topology:13")),
            capability_typing_digest: digest("capability-typing"),
            compatibility_plan_digest: digest("compatibility"),
            lesion_ablation_digest: digest("lesion-ablation"),
            resource_review_digest: digest("resource-review"),
            security_review_digest: digest("security-review"),
            migration_digest: handoff.migration_digest,
            rollback_digest: handoff.rollback_digest,
            writer_handoff_digest: handoff.plan_digest,
            evidence_digest: digest("topology-evidence"),
        }],
    })
    .expect("typed topology proposal");
    let governed = admit_governed_topology_v1(
        proposal,
        vec![handoff.clone()],
        digest("observer-authentication"),
        digest("evaluator-authentication"),
    )
    .expect("governed topology");
    (governed, handoff)
}

fn persist_and_reopen(
    fixture: &TestFile,
    governed: GovernedTopologyProposalV1,
) -> DurableTopologyProposalRegistryV1 {
    let scope = digest("topology-registry-scope");
    let anchor = {
        let mut registry =
            DurableTopologyProposalRegistryV1::bootstrap_empty(fixture.create(), scope, 41, 8)
                .expect("bootstrap registry");
        let append = registry
            .append(Digest32::ZERO, governed.clone())
            .expect("append governed topology");
        assert!(!append.authority.grants_any());
        let anchor = registry
            .current_anchor()
            .expect("anchor read")
            .expect("anchor exists");
        (anchor, append)
    };
    let (anchor, _append) = anchor;
    let reopened =
        DurableTopologyProposalRegistryV1::reopen_anchored(fixture.open(), scope, 41, 8, anchor)
            .expect("anchored reopen");
    assert_eq!(reopened.record_count(), Ok(1));
    reopened
}

#[test]
fn pls3_governed_topology_persists_then_accepts_bounded_canary() {
    let fixture = TestFile::new("pls3-accept");
    let (governed, _handoff) = governed_topology();
    let candidate_id = governed
        .proposal
        .candidates
        .iter()
        .find(|candidate| candidate.kind == codex_hepta_plasticity::TopologyCandidateKindV2::Update)
        .expect("update candidate")
        .candidate_id
        .clone();
    let proposal_id = governed.proposal.proposal_id.clone();
    let registry = persist_and_reopen(&fixture, governed);
    let plan = build_structural_canary_plan_v1(
        &registry,
        &proposal_id,
        candidate_id,
        digest("baseline-health"),
        2,
        0,
        2,
    )
    .expect("durable-bound canary plan");
    let mut controller = StructuralCanaryControllerV1::new(plan).expect("canary controller");
    let (verifier, key, observer) = canary_observer();
    for sequence in 1..=2 {
        let observation = StructuralCanaryObservationV1 {
            sequence,
            health_digest: digest(&format!("health:{sequence}")),
            evidence_digest: digest(&format!("evidence:{sequence}")),
            regression_count: 0,
            safety_violation: false,
            lineage_mismatch: false,
            rollback_verified: true,
        };
        let attestation = sign_canary_observation(
            &verifier,
            &key,
            &observer,
            controller.plan_digest(),
            &observation,
            u64::from(sequence),
        );
        let receipt = observe_authenticated_structural_canary_v1(
            &mut controller,
            observation,
            &attestation,
            &verifier,
            50,
        )
        .expect("authenticated canary observation");
        assert_eq!(receipt.canary.state, StructuralCanaryStateV1::Running);
        assert_eq!(receipt.observer_id, observer.principal_id);
        assert!(!receipt.observer_authentication_digest.is_zero());
    }
    let accepted = controller.finish().expect("finish canary");
    assert_eq!(accepted.state, StructuralCanaryStateV1::Accepted);
    assert_eq!(accepted.observed_steps, 2);
    assert!(!accepted.observation_chain_digest.is_zero());
    assert!(!accepted.receipt_digest.is_zero());
}

#[test]
fn pls3_safety_violation_aborts_after_durable_admission() {
    let fixture = TestFile::new("pls3-abort");
    let (governed, _handoff) = governed_topology();
    let candidate_id = governed
        .proposal
        .candidates
        .iter()
        .find(|candidate| candidate.kind == codex_hepta_plasticity::TopologyCandidateKindV2::Update)
        .expect("update candidate")
        .candidate_id
        .clone();
    let proposal_id = governed.proposal.proposal_id.clone();
    let registry = persist_and_reopen(&fixture, governed);
    let plan = build_structural_canary_plan_v1(
        &registry,
        &proposal_id,
        candidate_id,
        digest("baseline-health"),
        4,
        0,
        2,
    )
    .expect("durable-bound canary plan");
    let mut controller = StructuralCanaryControllerV1::new(plan).expect("canary controller");
    let (verifier, key, observer) = canary_observer();

    let safe_claim = StructuralCanaryObservationV1 {
        sequence: 1,
        health_digest: digest("unsafe-health"),
        evidence_digest: digest("unsafe-evidence"),
        regression_count: 0,
        safety_violation: false,
        lineage_mismatch: false,
        rollback_verified: true,
    };
    let stale_attestation = sign_canary_observation(
        &verifier,
        &key,
        &observer,
        controller.plan_digest(),
        &safe_claim,
        1,
    );
    let mut tampered = safe_claim;
    tampered.safety_violation = true;
    assert!(matches!(
        observe_authenticated_structural_canary_v1(
            &mut controller,
            tampered.clone(),
            &stale_attestation,
            &verifier,
            50,
        ),
        Err(AuthenticatedStructuralCanaryErrorV1::Evidence(
            SignedEvidenceError::PayloadMismatch
        ))
    ));
    assert_eq!(controller.state(), StructuralCanaryStateV1::Prepared);

    let unsafe_attestation = sign_canary_observation(
        &verifier,
        &key,
        &observer,
        controller.plan_digest(),
        &tampered,
        2,
    );
    let aborted = observe_authenticated_structural_canary_v1(
        &mut controller,
        tampered,
        &unsafe_attestation,
        &verifier,
        50,
    )
    .expect("authenticated terminal abort receipt");
    assert_eq!(aborted.canary.state, StructuralCanaryStateV1::Aborted);
    assert_eq!(
        controller.finish().expect("finish preserves abort").state,
        StructuralCanaryStateV1::Aborted
    );
}
