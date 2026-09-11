use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid test id: {error}"))
}

fn generation(value: u64) -> Generation {
    Generation::new(value).unwrap_or_else(|error| panic!("valid generation: {error}"))
}

fn revision(value: u64) -> Revision {
    Revision::new(value).unwrap_or_else(|error| panic!("valid revision: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn vector() -> LaneCGenerationVectorV1 {
    LaneCGenerationVectorV1 {
        scope_id: id("scope:tenant-a"),
        purpose_id: id("purpose:reasoning"),
        memory_ledger_frontier: 10,
        knowledge_fact_frontier: 8,
        tombstone_frontier: 3,
        source_ledger_frontier: 12,
        knowledge_graph_generation: generation(4),
        compact_checkpoint_generation: generation(2),
        prompt_registry_revision: revision(7),
        retrieval_profile_digest: digest("retrieval-profile"),
        encoder_preprocessor_digest: digest("encoder-profile"),
        authority_epoch: 9,
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
    }
}

fn snapshot_key() -> CognitiveSnapshotKeyV1 {
    CognitiveSnapshotKeyV1::new(vector())
        .unwrap_or_else(|error| panic!("valid snapshot key: {error}"))
}

#[test]
fn generation_vector_digest_binds_every_generation() {
    let original = vector();
    original
        .validate()
        .unwrap_or_else(|error| panic!("valid vector: {error}"));
    let original_digest = original.digest();

    let mut changed = original.clone();
    changed.authority_epoch += 1;
    assert_ne!(original_digest, changed.digest());

    let mut changed = original.clone();
    changed.tombstone_frontier += 1;
    assert_ne!(original_digest, changed.digest());

    let mut changed = original;
    changed.tokenizer_digest = digest("other-tokenizer");
    assert_ne!(original_digest, changed.digest());
}

#[test]
fn snapshot_key_rejects_digest_drift() {
    let mut key = snapshot_key();
    key.vector.prompt_registry_revision = revision(8);
    assert_eq!(
        key.validate(),
        Err(LaneCContractError::DigestMismatch("generation_vector"))
    );
}

#[test]
fn memory_admission_requires_unique_bounded_support() {
    let support = MemoryAdmissionEvidenceV1 {
        evidence_id: id("evidence:1"),
        source_id: id("source:1"),
        source_digest: digest("source"),
        observation_digest: digest("observation"),
        privacy_scope_digest: digest("privacy"),
        redaction_manifest_digest: digest("redaction"),
        observed_at_unix_ms: 1,
    };
    let candidate = MemoryAdmissionCandidateV1 {
        candidate_id: id("candidate:1"),
        proposed_by: id("proposer:1"),
        kind: MemoryAdmissionKind::Observation,
        content_digest: digest("content"),
        policy_digest: digest("policy"),
        verification: MemoryVerificationState::Verified,
        supports: vec![support.clone()],
    };
    candidate
        .validate()
        .unwrap_or_else(|error| panic!("valid candidate: {error}"));
    assert!(!candidate.digest().is_zero());

    let mut duplicate = candidate;
    duplicate.supports.push(support);
    assert_eq!(
        duplicate.validate(),
        Err(LaneCContractError::DuplicateIdentity("evidence_id"))
    );
}

#[test]
fn federation_result_binds_coverage_snapshot_and_items() {
    let mut result = FederatedEvidenceResultV1 {
        query_id: id("query:1"),
        peer_id: id("peer:1"),
        observed_snapshot: snapshot_key(),
        items: vec![FederatedEvidenceItemV1 {
            source_owner_id: id("owner:1"),
            record_id: id("record:1"),
            record_revision: revision(2),
            record_digest: digest("record"),
            support_digest: digest("support"),
            validity_digest: digest("validity"),
        }],
        coverage: FederatedCoverageV1 {
            requested_peers: 2,
            completed_peers: 1,
            failed_peers: 1,
            truncated_items: 0,
        },
        completeness: FederatedCompletenessV1::Partial,
        validity: FederatedValidityV1::Valid,
        expires_unix_ms: 10,
        result_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    result.result_digest = result.compute_result_digest();
    result
        .validate()
        .unwrap_or_else(|error| panic!("valid federation result: {error}"));

    result.coverage.truncated_items = 1;
    assert_eq!(
        result.validate(),
        Err(LaneCContractError::DigestMismatch("federated_result"))
    );
}

#[test]
fn projection_publication_requires_exact_predecessor() {
    let generation_record = KnowledgeGraphGenerationV1 {
        generation: generation(2),
        source_snapshot: snapshot_key(),
        source_manifest_digest: digest("manifest"),
        graph_profile_digest: digest("profile"),
        node_count: 3,
        edge_count: 4,
        graph_digest: digest("graph"),
    };
    let mut receipt = ProjectionReceiptV1 {
        projection_id: id("projection:1"),
        predecessor_generation: Some(generation(1)),
        generation: generation_record,
        publication_digest: Digest32::ZERO,
        disposition: ProjectionDispositionV1::Published,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.publication_digest = receipt.compute_publication_digest();
    receipt
        .validate()
        .unwrap_or_else(|error| panic!("valid projection: {error}"));

    receipt.predecessor_generation = Some(generation(3));
    assert_eq!(
        receipt.validate(),
        Err(LaneCContractError::InvalidState(
            "projection_predecessor_generation"
        ))
    );
}

#[test]
fn compact_checkpoint_and_proof_are_non_authoritative() {
    let mut checkpoint = CompactCheckpointV1 {
        checkpoint_id: id("checkpoint:1"),
        generation: generation(1),
        source_snapshot: snapshot_key(),
        support_manifest_digest: digest("support-manifest"),
        algorithm_digest: digest("algorithm"),
        payload_digest: digest("payload"),
        omitted_information_digest: digest("omitted"),
        tombstone_cutoff: 3,
        predecessor_digest: None,
        compatibility_digest: digest("compatibility"),
        checkpoint_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    checkpoint.checkpoint_digest = checkpoint.compute_checkpoint_digest();
    checkpoint
        .validate()
        .unwrap_or_else(|error| panic!("valid checkpoint: {error}"));

    let mut proof = CompactionProofV1 {
        checkpoint_digest: checkpoint.checkpoint_digest,
        retained_query_suite_digest: digest("queries"),
        reconstruction_obligation_digest: digest("reconstruction"),
        contradiction_holdout_digest: digest("contradictions"),
        deletion_cutoff: 3,
        source_count: 100,
        retained_count: 30,
        proof_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    proof.proof_digest = proof.compute_proof_digest();
    proof
        .validate()
        .unwrap_or_else(|error| panic!("valid proof: {error}"));

    proof.authority = AuthorityPosture {
        runtime: true,
        ..AuthorityPosture::DENY_ALL
    };
    assert_eq!(proof.validate(), Err(LaneCContractError::AuthorityGranted));
}

#[test]
fn prompt_snapshot_and_delivery_observation_reject_stale_semantics() {
    let mut prompt = PromptRegistrySnapshotV1 {
        revision: revision(4),
        registry_digest: digest("registry"),
        lifecycle_frontier: 10,
        revocation_frontier: 8,
        model_compatibility_digest: digest("model-compat"),
        snapshot_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    prompt.snapshot_digest = prompt.compute_snapshot_digest();
    prompt
        .validate()
        .unwrap_or_else(|error| panic!("valid prompt snapshot: {error}"));

    let mut delivery = ContextDeliveryObservationV1 {
        observation_id: id("delivery:1"),
        compilation_receipt_digest: digest("compilation"),
        attachment_digest: digest("attachment"),
        delivered_payload_digest: digest("delivered-payload"),
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
        delivered_segment_count: 2,
        terminal_observed: true,
        disposition: ContextDeliveryDispositionV1::Delivered,
        observed_unix_ms: 10,
        observation_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    delivery.observation_digest = delivery.compute_observation_digest();
    delivery
        .validate()
        .unwrap_or_else(|error| panic!("valid delivery: {error}"));

    delivery.terminal_observed = false;
    assert_eq!(
        delivery.validate(),
        Err(LaneCContractError::InvalidState(
            "delivered_without_terminal_observation"
        ))
    );
}
