use super::*;

use std::collections::BTreeSet;

use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_cognitive_types::hnmf::MemoryLifecycleV1;
use codex_hepta_cognitive_types::hnmf::MemoryScopeV1;
use codex_hepta_cognitive_types::hnmf::MemoryVerificationStateV1;
use codex_hepta_cognitive_types::hnmf::ModalityKindV1;
use codex_hepta_cognitive_types::hnmf::ModalitySpanRefV1;
use codex_hepta_cognitive_types::hnmf::ObservedIntervalV1;
use codex_hepta_cognitive_types::hnmf::PrivacyClassV1;
use codex_hepta_cognitive_types::hnmf::ProvenanceRefV1;
use codex_hepta_cognitive_types::hnmf::RetentionPolicyV1;
use codex_hepta_cognitive_types::hnmf::SpanRangeV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_cognitive_types::lane_c::MemoryAdmissionEvidenceV1;

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
) -> MemoryAdmissionCandidateV1 {
    MemoryAdmissionCandidateV1 {
        candidate_id: id(record_id),
        proposed_by: id("proposer:1"),
        kind,
        content_digest: digest(content),
        policy_digest: digest("admission-policy"),
        verification: MemoryVerificationState::Verified,
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

fn contract_id(value: &str) -> ContractIdV1 {
    ContractIdV1::new(value).unwrap_or_else(|error| panic!("valid contract id: {error}"))
}

fn contract_digest(value: &str) -> ContractDigestV1 {
    ContractDigestV1::from_digest(digest(value))
        .unwrap_or_else(|error| panic!("valid contract digest: {error}"))
}

fn canonical_event(record_id: &str) -> MemoryEventV1 {
    MemoryEventV1 {
        event_id: contract_id(&format!("event:{record_id}")),
        episode_id: contract_id("episode:1"),
        scope: MemoryScopeV1::AgentPrivate {
            agent_id: contract_id("agent:a"),
        },
        observed_interval: ObservedIntervalV1 {
            start_unix_ms: 1,
            end_unix_ms: None,
        },
        modality_spans: vec![ModalitySpanRefV1 {
            span_id: contract_id("span:1"),
            modality: ModalityKindV1::Text,
            asset_sha256: contract_digest("asset"),
            range: SpanRangeV1::ByteRange { start: 0, end: 4 },
            preprocessor_manifest_sha256: contract_digest("preprocessor"),
            feature_blob_sha256: None,
            symbolic_projection_sha256: None,
            uncertainty_ppm: 0,
            privacy_class: PrivacyClassV1::AgentPrivate,
            redaction_mask_sha256: None,
        }],
        cross_modal_bindings: Vec::new(),
        semantic_keys: BTreeSet::from(["door".to_string()]),
        provenance: vec![ProvenanceRefV1 {
            source_id: contract_id(&format!("source:{record_id}")),
            source_revision: 1,
            source_sha256: contract_digest(&format!("source-digest:{record_id}")),
            observed_at_unix_ms: 1,
        }],
        verification: MemoryVerificationStateV1::Verified,
        retention_policy: RetentionPolicyV1::Persistent {
            retain_until_unix_ms: None,
        },
        objective_digest: contract_digest("objective"),
        ndu_state_digest: contract_digest("ndu"),
        causal_parents: BTreeSet::new(),
        temporal_neighbors: BTreeSet::new(),
        behavior_propensity_ppm: None,
        lifecycle: MemoryLifecycleV1::Active,
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

fn store() -> AdmittedCognitiveStoreV2 {
    AdmittedCognitiveStoreV2::new(snapshot_key(), digest("writer-fence"), 128)
        .unwrap_or_else(|error| panic!("valid store: {error}"))
}

#[test]
fn admission_appends_full_revision_history_and_advances_frontiers() {
    let mut store = store();
    let first = candidate("memory:1", "content:v1", MemoryAdmissionKind::Inference);
    let first_receipt = store
        .append_admitted(&Verifier, first.clone(), intent(&store, "intent:1", &first))
        .unwrap_or_else(|error| panic!("append first: {error}"));
    assert_eq!(first_receipt.committed_frontier, 2);
    assert_eq!(first_receipt.snapshot_key.vector.knowledge_fact_frontier, 2);

    let second = candidate("memory:1", "content:v2", MemoryAdmissionKind::Inference);
    let second_receipt = store
        .append_admitted(
            &Verifier,
            second.clone(),
            intent(&store, "intent:2", &second),
        )
        .unwrap_or_else(|error| panic!("append correction: {error}"));
    assert_eq!(second_receipt.committed_frontier, 3);
    let history = store.history(&id("memory:1")).expect("history exists");
    assert_eq!(history.len(), 2);
    assert_eq!(history[0].revision, revision(1));
    assert_eq!(history[1].revision, revision(2));
    assert_eq!(
        history[1].predecessor_digest,
        Some(history[0].record_digest())
    );
}

#[test]
fn stale_snapshot_and_wrong_authorization_fail_before_mutation() {
    let mut store = store();
    let first = candidate("memory:1", "content:v1", MemoryAdmissionKind::Observation);
    let stale_key = store.snapshot_key().clone();
    store
        .append_admitted(&Verifier, first.clone(), intent(&store, "intent:1", &first))
        .unwrap_or_else(|error| panic!("append first: {error}"));

    let second = candidate("memory:2", "content:v1", MemoryAdmissionKind::Observation);
    let mut stale_intent = intent(&store, "intent:2", &second);
    stale_intent.expected_snapshot = stale_key;
    assert_eq!(
        store.append_admitted(&Verifier, second.clone(), stale_intent),
        Err(CognitiveStoreV2Error::SnapshotConflict)
    );
    assert!(store.current_head(&id("memory:2")).is_none());

    let mut unauthorized = intent(&store, "intent:3", &second);
    unauthorized.authorization_digest = digest("wrong-authorization");
    assert_eq!(
        store.append_admitted(&Verifier, second, unauthorized),
        Err(CognitiveStoreV2Error::AuthorizationRejected)
    );
    assert!(store.current_head(&id("memory:2")).is_none());
}

#[test]
fn tombstone_is_terminal_and_advances_deletion_frontier() {
    let mut store = store();
    let first = candidate("memory:1", "content:v1", MemoryAdmissionKind::Observation);
    store
        .append_admitted(&Verifier, first.clone(), intent(&store, "intent:1", &first))
        .unwrap_or_else(|error| panic!("append first: {error}"));
    let before_tombstone = store.snapshot_key().vector.tombstone_frontier;
    let forget = ForgetIntentV2 {
        intent_id: id("forget:1"),
        record_id: id("memory:1"),
        expected_snapshot: store.snapshot_key().clone(),
        writer_fence_digest: digest("writer-fence"),
        authorization_digest: digest("authorization"),
        reason_digest: digest("privacy-delete"),
    };
    store
        .forget(&Verifier, forget)
        .unwrap_or_else(|error| panic!("forget: {error}"));
    assert_eq!(
        store.snapshot_key().vector.tombstone_frontier,
        before_tombstone + 1
    );

    let resurrected = candidate("memory:1", "content:v2", MemoryAdmissionKind::Observation);
    let resurrect_intent = intent(&store, "intent:resurrect", &resurrected);
    assert_eq!(
        store.append_admitted(&Verifier, resurrected, resurrect_intent),
        Err(CognitiveStoreV2Error::ResurrectionDenied(
            "memory:1".to_string()
        ))
    );
}

#[test]
fn intent_retry_returns_original_receipt_after_unrelated_commit() {
    let mut store = store();
    let first = candidate("memory:1", "content:v1", MemoryAdmissionKind::Observation);
    let first_intent = intent(&store, "intent:1", &first);
    let original = store
        .append_admitted(&Verifier, first.clone(), first_intent.clone())
        .unwrap_or_else(|error| panic!("append first: {error}"));
    let unrelated = candidate("memory:2", "content:v1", MemoryAdmissionKind::Observation);
    store
        .append_admitted(
            &Verifier,
            unrelated.clone(),
            intent(&store, "intent:2", &unrelated),
        )
        .unwrap_or_else(|error| panic!("append unrelated: {error}"));
    let retry = store
        .append_admitted(&Verifier, first, first_intent)
        .unwrap_or_else(|error| panic!("retry: {error}"));
    assert_eq!(retry, original);
}

#[test]
fn export_reopen_and_snapshot_preserve_history_and_tombstones() {
    let mut store = store();
    let first = candidate("memory:1", "content:v1", MemoryAdmissionKind::Observation);
    store
        .append_admitted(&Verifier, first.clone(), intent(&store, "intent:1", &first))
        .unwrap_or_else(|error| panic!("append first: {error}"));
    store
        .forget(
            &Verifier,
            ForgetIntentV2 {
                intent_id: id("forget:1"),
                record_id: id("memory:1"),
                expected_snapshot: store.snapshot_key().clone(),
                writer_fence_digest: digest("writer-fence"),
                authorization_digest: digest("authorization"),
                reason_digest: digest("delete"),
            },
        )
        .unwrap_or_else(|error| panic!("forget: {error}"));

    let image = store
        .export_image()
        .unwrap_or_else(|error| panic!("export image: {error}"));
    let reopened = AdmittedCognitiveStoreV2::reopen(image, 128)
        .unwrap_or_else(|error| panic!("reopen: {error}"));
    assert_eq!(reopened.snapshot_key(), store.snapshot_key());
    assert_eq!(reopened.history(&id("memory:1")).expect("history").len(), 2);
    assert_eq!(
        reopened.current_head(&id("memory:1")).expect("head").state,
        RecordState::Tombstone
    );

    let snapshot = reopened
        .open_snapshot(
            10,
            SnapshotOpenRequestV2 {
                request_id: id("snapshot:1"),
                scope_id: id("scope:store"),
                purpose_id: id("purpose:memory"),
                minimum_memory_frontier: reopened.snapshot_key().vector.memory_ledger_frontier,
                minimum_tombstone_frontier: reopened.snapshot_key().vector.tombstone_frontier,
                authority_epoch: 1,
                deadline_unix_ms: 100,
                lease_duration_ms: 10,
            },
        )
        .unwrap_or_else(|error| panic!("open snapshot: {error}"));
    assert_eq!(snapshot.snapshot.records.len(), 2);
    snapshot
        .validate(10)
        .unwrap_or_else(|error| panic!("validate snapshot: {error}"));
}

#[test]
fn canonical_event_shadow_binds_exact_admission_and_write_receipt() {
    let mut store = store();
    let candidate = candidate("memory:1", "content:v1", MemoryAdmissionKind::Observation);
    let event = canonical_event("memory:1");
    let result = store
        .append_admitted_with_canonical_shadow(
            &Verifier,
            candidate.clone(),
            intent(&store, "intent:canonical:1", &candidate),
            event.clone(),
        )
        .unwrap_or_else(|error| panic!("canonical shadow append: {error}"));

    result
        .validate()
        .unwrap_or_else(|error| panic!("canonical shadow receipt: {error}"));
    assert_eq!(result.shadow_receipt.event_id, event.event_id);
    assert_eq!(result.shadow_receipt.candidate_digest, candidate.digest());
    assert_eq!(
        result.shadow_receipt.record_digest,
        result.write_receipt.record_digest
    );
    assert_eq!(
        result.shadow_receipt.snapshot_vector_digest,
        result.write_receipt.snapshot_key.vector_digest
    );
    assert!(!result.shadow_receipt.authority.grants_any());
}

#[test]
fn canonical_event_shadow_rejects_provenance_or_verification_drift_before_write() {
    let mut store = store();
    let candidate = candidate("memory:1", "content:v1", MemoryAdmissionKind::Observation);

    let mut wrong_source = canonical_event("memory:1");
    wrong_source.provenance[0].source_sha256 = contract_digest("different-source");
    assert_eq!(
        store.append_admitted_with_canonical_shadow(
            &Verifier,
            candidate.clone(),
            intent(&store, "intent:canonical:source", &candidate),
            wrong_source,
        ),
        Err(CognitiveStoreV2Error::CanonicalSourceProvenanceMismatch)
    );
    assert!(store.current_head(&id("memory:1")).is_none());

    let mut wrong_verification = canonical_event("memory:1");
    wrong_verification.verification = MemoryVerificationStateV1::Contradicted;
    assert_eq!(
        store.append_admitted_with_canonical_shadow(
            &Verifier,
            candidate.clone(),
            intent(&store, "intent:canonical:verification", &candidate),
            wrong_verification,
        ),
        Err(CognitiveStoreV2Error::CanonicalVerificationMismatch)
    );
    assert!(store.current_head(&id("memory:1")).is_none());
}

#[test]
fn canonical_event_shadow_receipt_tamper_fails_closed() {
    let mut store = store();
    let candidate = candidate("memory:1", "content:v1", MemoryAdmissionKind::Observation);
    let result = store
        .append_admitted_with_canonical_shadow(
            &Verifier,
            candidate.clone(),
            intent(&store, "intent:canonical:1", &candidate),
            canonical_event("memory:1"),
        )
        .unwrap_or_else(|error| panic!("canonical shadow append: {error}"));

    let mut tampered = result.clone();
    tampered.shadow_receipt.record_digest = digest("tampered-record");
    assert_eq!(
        tampered.validate(),
        Err(CognitiveStoreV2Error::CanonicalShadowReceiptMismatch)
    );
}
