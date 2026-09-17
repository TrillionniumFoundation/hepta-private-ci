use super::*;

use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_cognitive_types::lane_c::MemoryAdmissionEvidenceV1;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    Generation::new(value).unwrap_or_else(|error| panic!("valid generation: {error}"))
}

fn revision(value: u64) -> Revision {
    Revision::new(value).unwrap_or_else(|error| panic!("valid revision: {error}"))
}

fn snapshot_key() -> CognitiveSnapshotKeyV1 {
    CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id("scope:store"),
        purpose_id: id("purpose:memory"),
        memory_ledger_frontier: 1,
        knowledge_fact_frontier: 1,
        tombstone_frontier: 1,
        source_ledger_frontier: 1,
        knowledge_graph_generation: generation(1),
        compact_checkpoint_generation: generation(1),
        prompt_registry_revision: revision(1),
        retrieval_profile_digest: digest("retrieval"),
        encoder_preprocessor_digest: digest("encoder"),
        authority_epoch: 1,
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
    })
    .unwrap_or_else(|error| panic!("valid snapshot key: {error}"))
}

fn candidate(
    record_id: &str,
    content: &str,
    kind: MemoryAdmissionKind,
    verification: MemoryVerificationState,
) -> MemoryAdmissionCandidateV1 {
    MemoryAdmissionCandidateV1 {
        candidate_id: id(record_id),
        proposed_by: id("proposer:1"),
        kind,
        content_digest: digest(content),
        policy_digest: digest("admission-policy"),
        verification,
        supports: vec![MemoryAdmissionEvidenceV1 {
            evidence_id: id(&format!("evidence:{record_id}:{content}")),
            source_id: id(&format!("source:{record_id}")),
            source_digest: digest(&format!("source-digest:{record_id}")),
            observation_digest: digest(&format!("observation:{content}")),
            privacy_scope_digest: digest("privacy"),
            redaction_manifest_digest: digest("redaction"),
            observed_at_unix_ms: 1,
        }],
    }
}

fn intent(
    store: &AdmittedCognitiveStoreV2,
    intent_id: &str,
    candidate: &MemoryAdmissionCandidateV1,
) -> MemoryWriteIntentV1 {
    MemoryWriteIntentV1 {
        intent_id: id(intent_id),
        candidate_digest: candidate.digest(),
        expected_snapshot: store.snapshot_key().clone(),
        writer_fence_digest: digest("writer-fence"),
        authorization_digest: digest("authorization"),
    }
}

struct Verifier;

impl StoreAuthorityVerifierV2 for Verifier {
    fn verify(
        &self,
        _operation_id: &StableId,
        _payload_digest: Digest32,
        authorization_digest: Digest32,
    ) -> Result<(), CognitiveStoreV2Error> {
        if authorization_digest == digest("authorization") {
            Ok(())
        } else {
            Err(CognitiveStoreV2Error::AuthorizationRejected)
        }
    }
}

fn store(maximum_record_revisions: usize) -> AdmittedCognitiveStoreV2 {
    AdmittedCognitiveStoreV2::new(
        snapshot_key(),
        digest("writer-fence"),
        maximum_record_revisions,
    )
    .unwrap_or_else(|error| panic!("valid store: {error}"))
}

#[test]
fn unverified_inference_cannot_become_live_fact() {
    let mut store = store(8);
    let candidate = candidate(
        "memory:fact",
        "claim",
        MemoryAdmissionKind::Inference,
        MemoryVerificationState::Unverified,
    );
    let result = store.append_admitted(
        &Verifier,
        candidate.clone(),
        intent(&store, "intent:unverified", &candidate),
    );
    assert_eq!(
        result,
        Err(CognitiveStoreV2Error::Contract(
            LaneCContractError::InvalidState("unverified_fact_admission")
        ))
    );
    assert!(store.current_head(&id("memory:fact")).is_none());
}

#[test]
fn contradicted_candidate_cannot_become_live_record() {
    let mut store = store(8);
    let candidate = candidate(
        "memory:contradicted",
        "claim",
        MemoryAdmissionKind::Observation,
        MemoryVerificationState::Contradicted,
    );
    let result = store.append_admitted(
        &Verifier,
        candidate.clone(),
        intent(&store, "intent:contradicted", &candidate),
    );
    assert_eq!(
        result,
        Err(CognitiveStoreV2Error::Contract(
            LaneCContractError::InvalidState("contradicted_memory_admission")
        ))
    );
    assert!(store.current_head(&id("memory:contradicted")).is_none());
}

#[test]
fn forget_succeeds_after_ordinary_admission_capacity_is_full() {
    let mut store = store(1);
    let first = candidate(
        "memory:1",
        "content:v1",
        MemoryAdmissionKind::Observation,
        MemoryVerificationState::Verified,
    );
    store
        .append_admitted(
            &Verifier,
            first.clone(),
            intent(&store, "intent:first", &first),
        )
        .unwrap_or_else(|error| panic!("first admission: {error}"));

    let second = candidate(
        "memory:2",
        "content:v1",
        MemoryAdmissionKind::Observation,
        MemoryVerificationState::Verified,
    );
    assert_eq!(
        store.append_admitted(
            &Verifier,
            second.clone(),
            intent(&store, "intent:second", &second),
        ),
        Err(CognitiveStoreV2Error::CapacityExceeded)
    );

    store
        .forget(
            &Verifier,
            ForgetIntentV2 {
                intent_id: id("forget:first"),
                record_id: id("memory:1"),
                expected_snapshot: store.snapshot_key().clone(),
                writer_fence_digest: digest("writer-fence"),
                authorization_digest: digest("authorization"),
                reason_digest: digest("privacy-delete"),
            },
        )
        .unwrap_or_else(|error| panic!("reserved tombstone capacity: {error}"));
    assert_eq!(
        store.current_head(&id("memory:1")).expect("head").state,
        RecordState::Tombstone
    );
}

#[test]
fn intent_journal_is_bounded_even_for_unchanged_retries_with_new_ids() {
    let mut store = store(1);
    let candidate = candidate(
        "memory:1",
        "content:v1",
        MemoryAdmissionKind::Observation,
        MemoryVerificationState::Verified,
    );
    store
        .append_admitted(
            &Verifier,
            candidate.clone(),
            intent(&store, "intent:1", &candidate),
        )
        .unwrap_or_else(|error| panic!("first admission: {error}"));
    for number in 2..=4 {
        let intent_id = format!("intent:{number}");
        let receipt = store
            .append_admitted(
                &Verifier,
                candidate.clone(),
                intent(&store, &intent_id, &candidate),
            )
            .unwrap_or_else(|error| panic!("unchanged journal entry: {error}"));
        assert_eq!(receipt.disposition, MemoryWriteDisposition::Unchanged);
    }

    let result = store.append_admitted(
        &Verifier,
        candidate.clone(),
        intent(&store, "intent:5", &candidate),
    );
    assert_eq!(
        result,
        Err(CognitiveStoreV2Error::Contract(
            LaneCContractError::LimitExceeded {
                field: "cognitive_store_intent_journal",
                actual: 5,
                maximum: 4,
            }
        ))
    );
}

#[test]
fn reopen_rejects_receipt_record_identity_drift_even_with_valid_image_digest() {
    let mut store = store(8);
    let candidate = candidate(
        "memory:1",
        "content:v1",
        MemoryAdmissionKind::Observation,
        MemoryVerificationState::Verified,
    );
    store
        .append_admitted(
            &Verifier,
            candidate.clone(),
            intent(&store, "intent:1", &candidate),
        )
        .unwrap_or_else(|error| panic!("admission: {error}"));
    let mut image = store
        .export_image()
        .unwrap_or_else(|error| panic!("export: {error}"));
    image.journal[0].receipt.record_id = id("memory:forged");
    // The legacy image digest does not bind receipt.record_id. Hardened reopen
    // must therefore reject the semantic cross-link independently.
    assert_eq!(image.image_digest, image.compute_image_digest());
    assert_eq!(
        AdmittedCognitiveStoreV2::reopen(image, 8),
        Err(CognitiveStoreV2Error::Contract(
            LaneCContractError::InvalidState("store_image_receipt_record_binding")
        ))
    );
}
