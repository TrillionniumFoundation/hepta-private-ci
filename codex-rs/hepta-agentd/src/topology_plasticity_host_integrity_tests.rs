use super::*;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_plasticity::ProposalWindowV2;
use ed25519_dalek::SigningKey;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

fn image(file: &mut File) -> Vec<u8> {
    file.seek(SeekFrom::Start(0)).expect("seek image");
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes).expect("read image");
    bytes
}

#[test]
fn read_discovered_corruption_closes_topology_writer_and_preserves_both_files() {
    let mut registry_file = tempfile::tempfile().expect("registry file");
    let mut anchor_file = tempfile::tempfile().expect("anchor file");
    let scope = Digest32::of_bytes(b"topology-integrity-scope");
    // Retain the same open-file description before locking. Independent reopen
    // is not used: Windows range locks prohibit its reads and writes.
    let (mut writer, mut anchor_store) = bootstrap_agentd_topology_writer_v1(
        registry_file.try_clone().expect("registry clone"),
        anchor_file.try_clone().expect("anchor clone"),
        scope,
        /*maximum_records*/ 8,
    )
    .expect("bootstrap");
    assert_eq!(writer.state(), AgentdTopologyWriterStateV1::Healthy);
    assert!(matches!(writer.current_anchor(), Ok(None)));
    let retained_anchor = (anchor_store.fence(), anchor_store.anchor());
    let mut damaged = image(&mut registry_file);
    assert!(!damaged.is_empty());
    damaged[0] ^= 1;
    registry_file
        .seek(SeekFrom::Start(0))
        .expect("seek corruption");
    registry_file.write_all(&damaged).expect("corrupt header");
    registry_file.sync_all().expect("sync corruption");
    let retained_bytes = (image(&mut registry_file), image(&mut anchor_file));

    assert!(matches!(
        writer.current_anchor(),
        Err(AgentdTopologyHostErrorV1::Registry(
            DurableTopologyRegistryErrorV1::Corrupt
        ))
    ));
    assert_eq!(writer.state(), AgentdTopologyWriterStateV1::Poisoned);
    assert!(matches!(
        writer.current_anchor(),
        Err(AgentdTopologyHostErrorV1::Poisoned)
    ));

    let objective = Digest32::of_bytes(b"topology-integrity-objective");
    let artifact = Digest32::of_bytes(b"topology-integrity-artifact");
    let principal_id = StableId::new("topology-integrity-generator").expect("id");
    let key = SigningKey::from_bytes(&[31; 32]);
    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: scope,
        objective_digest: objective,
        authority_epoch: 7,
        signers: vec![TrustedLearningSignerV1 {
            principal: AuthenticatedPrincipalV1 {
                principal_id: principal_id.clone(),
                credential_chain_digest: Digest32::of_bytes(b"topology-integrity-credential"),
                signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                scope_digest: scope,
                authority_epoch: 7,
                authenticated_at: 10,
                expires_at: 100,
            },
            controller_id: StableId::new("topology-integrity-controller").expect("id"),
            verifying_key: key.verifying_key().to_bytes(),
            roles: vec![LearningEvidenceRoleV1::Generator],
            revoked_at: None,
        }],
    })
    .expect("host verifier");
    let evidence = |role| SignedLearningEvidenceV1 {
        evidence_id: StableId::new(&format!("topology-integrity-{role:?}")).expect("id"),
        principal_id: principal_id.clone(),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: scope,
        objective_digest: objective,
        authority_epoch: 7,
        issued_at: 20,
        expires_at: 90,
        payload_digest: Digest32::of_bytes(b"untrusted-request-payload"),
        signature: [0; 64],
    };
    let window = ProposalWindowV2 {
        window_id: StableId::new("topology-integrity-window").expect("id"),
        window_digest: Digest32::of_bytes(b"topology-integrity-window"),
    };
    let baseline_generation = Generation::new(/*value*/ 1).expect("generation");
    let candidate_generation = baseline_generation.next().expect("successor");
    // Even untrusted request contents cannot reopen the poisoned host or reach
    // external artifact/evidence checks and anchor persistence.
    let request = TopologyPlasticityProductRequestV1 {
        proposal_id: StableId::new("topology-integrity-new-request").expect("id"),
        proposer_generation_id: principal_id.clone(),
        selected_artifact_digest: artifact,
        window: window.clone(),
        baseline_generation,
        candidate_generation,
        rollback_predecessor_digest: artifact,
        changes: Vec::new(),
        handoffs: Vec::new(),
        admission: TopologyAdmissionEvidenceV1 {
            baseline_id: StableId::new("topology-integrity-baseline").expect("id"),
            objective_digest: objective,
            selected_artifact_digest: artifact,
            artifact_registry_head_digest: Digest32::of_bytes(b"artifact-head"),
            qualification_evidence_head_digest: Digest32::of_bytes(b"evidence-head"),
            window,
            baseline_generation,
            candidate_generation,
            generation_digest: Digest32::of_bytes(b"generation"),
            evaluation_receipt_digest: Digest32::of_bytes(b"evaluation"),
        },
        generator_attestation: evidence(LearningEvidenceRoleV1::Generator),
        observer_attestation: evidence(LearningEvidenceRoleV1::Observer),
        evaluator_attestation: evidence(LearningEvidenceRoleV1::Evaluator),
        expected_registry_predecessor: Digest32::ZERO,
    };
    let ledger = DurableLedger::create(
        tempfile::tempfile().expect("ledger file"),
        Digest32::of_bytes(b"topology-integrity-ledger"),
        /*max_records*/ 8,
    )
    .expect("ledger");
    assert!(matches!(
        propose_agentd_topology_plasticity_v1(
            request,
            &ArtifactRegistry::new(),
            &ledger,
            &verifier,
            &mut writer,
            &mut anchor_store,
            /*now*/ 50,
        ),
        Err(AgentdTopologyHostErrorV1::Poisoned)
    ));
    assert_eq!(writer.state(), AgentdTopologyWriterStateV1::Poisoned);
    assert_eq!(
        (anchor_store.fence(), anchor_store.anchor()),
        retained_anchor
    );
    assert_eq!(
        (image(&mut registry_file), image(&mut anchor_file)),
        retained_bytes
    );
}
