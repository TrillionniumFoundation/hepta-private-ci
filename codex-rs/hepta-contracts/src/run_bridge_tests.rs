use super::*;

type TestResult<T> = Result<T, Box<dyn std::error::Error>>;

fn identity() -> TestResult<RunBridgeIdentityV1> {
    Ok(RunBridgeIdentityV1 {
        schema_version: RUN_BRIDGE_SCHEMA_VERSION,
        agent_id: AgentId::parse("00000000-0000-4000-8000-000000000001")?,
        run_id: "run:one".to_string(),
        request_id: "request:one".to_string(),
        owner_generation: 2,
        owner_dispatch_revision: 3,
        source_dispatch_revision: 4,
        fence_sha256: Sha256Digest::for_bytes(b"fence"),
        context_sha256: Sha256Digest::for_bytes(b"context"),
        envelope_sha256: Sha256Digest::for_bytes(b"envelope"),
        execution_binding_sha256: Sha256Digest::for_bytes(b"execution"),
        dispatch_sha256: Sha256Digest::for_bytes(b"dispatch"),
    })
}
fn binding() -> TestResult<RunBridgeBindingV1> {
    let identity = identity()?;
    Ok(RunBridgeBindingV1 {
        abort_commitment_sha256: RunBridgeBindingV1::abort_commitment(&identity, &[7; 32])?,
        identity,
    })
}
fn primary(binding: &RunBridgeBindingV1) -> TestResult<RunBridgePrimaryV1> {
    Ok(RunBridgePrimaryV1 {
        schema_version: RUN_BRIDGE_SCHEMA_VERSION,
        binding_sha256: binding.digest()?,
        source_revision: 6,
        provider_outcome: RunBridgeProviderOutcomeV1::Completed,
        logical_outcome: RunBridgeLogicalOutcomeV1::Succeeded,
        qualification_sha256: Sha256Digest::for_bytes(b"normalized qualification"),
        terminal_correlation_sha256: Some(Sha256Digest::for_bytes(b"exact terminal")),
        abort_proof_sha256: None,
    })
}

#[test]
fn complete_binding_round_trip_is_strict_and_bounded() {
    let binding = binding().unwrap();
    let bytes = serde_json::to_vec(&binding).unwrap();
    assert_eq!(
        serde_json::from_slice::<RunBridgeBindingV1>(&bytes).unwrap(),
        binding
    );
    let mut value = serde_json::to_value(&binding).unwrap();
    value["identity"]["unexpected_authority"] = serde_json::json!(true);
    assert!(serde_json::from_value::<RunBridgeBindingV1>(value).is_err());
    for id in ["".to_string(), "bad id".to_string(), "x".repeat(129)] {
        let mut malformed = binding.clone();
        malformed.identity.request_id = id;
        assert!(malformed.validate().is_err());
    }
    let mut malformed = binding.clone();
    malformed.identity.owner_generation = 0;
    assert!(malformed.validate().is_err());
    malformed = binding.clone();
    malformed.identity.schema_version += 1;
    assert!(malformed.validate().is_err());
    let mut value = serde_json::to_value(binding).unwrap();
    value["identity"]["dispatch_sha256"] = serde_json::json!("not a digest");
    let malformed: RunBridgeBindingV1 = serde_json::from_value(value).unwrap();
    assert!(malformed.validate().is_err());
}

#[test]
fn identity_drift_changes_commitment_and_binding_digest() {
    let original = binding().unwrap();
    for index in 0..11 {
        let mut changed = original.clone();
        let replacement = Sha256Digest::for_bytes(b"different");
        match index {
            0 => changed.identity.run_id.push_str("-other"),
            1 => changed.identity.request_id.push_str("-other"),
            2 => changed.identity.owner_generation += 1,
            3 => changed.identity.owner_dispatch_revision += 1,
            4 => changed.identity.source_dispatch_revision += 1,
            5 => changed.identity.fence_sha256 = replacement,
            6 => changed.identity.context_sha256 = replacement,
            7 => changed.identity.envelope_sha256 = replacement,
            8 => changed.identity.execution_binding_sha256 = replacement,
            9 => changed.identity.dispatch_sha256 = replacement,
            10 => {
                changed.identity.agent_id =
                    AgentId::parse("00000000-0000-4000-8000-000000000002").unwrap()
            }
            _ => unreachable!(),
        }
        assert_ne!(changed.digest().unwrap(), original.digest().unwrap());
        assert_ne!(
            RunBridgeBindingV1::abort_commitment(&changed.identity, &[7; 32]).unwrap(),
            original.abort_commitment_sha256
        );
    }
}

#[test]
fn abort_proof_cannot_cross_nonce_or_bound_identity() {
    let binding = binding().unwrap();
    let proof = RunBridgeAbortProofV1 {
        schema_version: RUN_BRIDGE_SCHEMA_VERSION,
        binding_sha256: binding.digest().unwrap(),
        nonce: [7; 32],
        reason: "cancelled before physical send".to_string(),
    };
    proof.validate(&binding).unwrap();
    let encoded = serde_json::to_vec(&proof).unwrap();
    assert_eq!(
        serde_json::from_slice::<RunBridgeAbortProofV1>(&encoded).unwrap(),
        proof
    );
    let mut changed = proof.clone();
    changed.nonce[0] ^= 1;
    assert!(changed.validate(&binding).is_err());
    changed = proof.clone();
    changed.binding_sha256 = Sha256Digest::for_bytes(b"another binding");
    assert!(changed.validate(&binding).is_err());
    changed = proof.clone();
    changed.reason = "x".repeat(513);
    assert!(changed.validate(&binding).is_err());
    changed = proof.clone();
    changed.reason.push('\n');
    assert!(changed.validate(&binding).is_err());
    assert!(RunBridgeBindingV1::abort_commitment(&binding.identity, &[0; 32]).is_err());
}

#[test]
fn provider_completion_and_logical_denial_are_distinct() {
    let binding = binding().unwrap();
    let original = primary(&binding).unwrap();
    original.validate(&binding).unwrap();
    let mut denied = original.clone();
    denied.logical_outcome = RunBridgeLogicalOutcomeV1::Failed;
    denied.qualification_sha256 = Sha256Digest::for_bytes(b"over quota");
    denied.validate(&binding).unwrap();
    assert_eq!(denied.provider_outcome, original.provider_outcome);
    assert_ne!(
        denied.digest(&binding).unwrap(),
        original.digest(&binding).unwrap()
    );
    denied.provider_outcome = RunBridgeProviderOutcomeV1::Failed;
    denied.logical_outcome = RunBridgeLogicalOutcomeV1::Succeeded;
    assert!(denied.validate(&binding).is_err());
}

#[test]
fn primary_cannot_mix_not_sent_and_provider_terminal_evidence() {
    let binding = binding().unwrap();
    let mut publication = primary(&binding).unwrap();
    publication.provider_outcome = RunBridgeProviderOutcomeV1::ProvenNotSent;
    publication.logical_outcome = RunBridgeLogicalOutcomeV1::Cancelled;
    assert!(publication.validate(&binding).is_err());
    publication.terminal_correlation_sha256 = None;
    publication.abort_proof_sha256 = Some(Sha256Digest::for_bytes(b"persisted proof"));
    publication.validate(&binding).unwrap();
    publication.provider_outcome = RunBridgeProviderOutcomeV1::Interrupted;
    assert!(publication.validate(&binding).is_err());
    publication.abort_proof_sha256 = None;
    publication.terminal_correlation_sha256 =
        Some(Sha256Digest::for_bytes(b"interrupted terminal"));
    publication.validate(&binding).unwrap();
    publication.source_revision = binding.identity.source_dispatch_revision;
    assert!(publication.validate(&binding).is_err());
}

#[test]
fn qualification_conflict_binds_the_immutable_primary_and_later_revision() {
    let binding = binding().unwrap();
    let primary = primary(&binding).unwrap();
    let original = primary.clone();
    let notice = RunBridgeQualificationConflictV1 {
        schema_version: RUN_BRIDGE_SCHEMA_VERSION,
        binding_sha256: binding.digest().unwrap(),
        primary_sha256: primary.digest(&binding).unwrap(),
        source_revision: primary.source_revision + 1,
        qualification_sha256: Sha256Digest::for_bytes(b"later denied qualification"),
    };
    notice.validate(&binding, &primary).unwrap();
    assert_eq!(primary, original);
    let mut wrong = notice.clone();
    wrong.source_revision = primary.source_revision;
    assert!(wrong.validate(&binding, &primary).is_err());
    wrong = notice.clone();
    wrong.primary_sha256 = Sha256Digest::for_bytes(b"another terminal");
    assert!(wrong.validate(&binding, &primary).is_err());
    wrong = notice;
    wrong.qualification_sha256 = primary.qualification_sha256.clone();
    assert!(wrong.validate(&binding, &primary).is_err());
}

#[test]
fn stable_acknowledgement_round_trip_requires_exact_kind_binding_and_revision() {
    let binding = binding().unwrap();
    let primary = primary(&binding).unwrap();
    let digest = primary.digest(&binding).unwrap();
    let ack = RunBridgeAcknowledgementV1 {
        schema_version: RUN_BRIDGE_SCHEMA_VERSION,
        binding_sha256: binding.digest().unwrap(),
        publication_sha256: digest.clone(),
        kind: RunBridgePublicationKindV1::Primary,
        owner_revision: binding.identity.owner_dispatch_revision + 1,
    };
    ack.validate(&binding, &digest, RunBridgePublicationKindV1::Primary)
        .unwrap();
    let replayed: RunBridgeAcknowledgementV1 =
        serde_json::from_slice(&serde_json::to_vec(&ack).unwrap()).unwrap();
    assert_eq!(ack, replayed);
    assert!(
        ack.validate(
            &binding,
            &digest,
            RunBridgePublicationKindV1::QualificationConflict
        )
        .is_err()
    );
    assert!(
        ack.validate(
            &binding,
            &Sha256Digest::for_bytes(b"other"),
            RunBridgePublicationKindV1::Primary
        )
        .is_err()
    );
    let mut wrong = ack;
    wrong.owner_revision = binding.identity.owner_dispatch_revision;
    assert!(
        wrong
            .validate(&binding, &digest, RunBridgePublicationKindV1::Primary)
            .is_err()
    );
}
