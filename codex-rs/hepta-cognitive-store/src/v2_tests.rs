use super::*;

use std::collections::BTreeSet;

use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_cognitive_types::hnmf::MemoryEventV1;
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
fn admission_rejects_unverified_and_contradicted_candidates_before_materialization() {
    for (index, (verification, expected)) in [
        (
            MemoryVerificationState::Unverified,
            CognitiveStoreV2Error::UnverifiedCandidate,
        ),
        (
            MemoryVerificationState::Contradicted,
            CognitiveStoreV2Error::ContradictedCandidate,
        ),
    ]
    .into_iter()
    .enumerate()
    {
        let mut store = store();
        let mut value = candidate(
            &format!("memory:verification:{index}"),
            "content:v1",
            MemoryAdmissionKind::Inference,
        );
        value.verification = verification;
        let write_intent = intent(&store, &format!("intent:verification:{index}"), &value);
        let record_id = value.candidate_id.clone();
        assert_eq!(
            store.append_admitted(&Verifier, value, write_intent),
            Err(expected)
        );
        assert!(store.current_head(&record_id).is_none());
    }
}

#[test]
fn tombstone_uses_reserved_capacity_after_ordinary_capacity_is_full() {
    let mut store = AdmittedCognitiveStoreV2::new(snapshot_key(), digest("writer-fence"), 1)
        .unwrap_or_else(|error| panic!("valid one-record store: {error}"));
    let first = candidate(
        "memory:capacity:1",
        "content:v1",
        MemoryAdmissionKind::Observation,
    );
    let first_intent = intent(&store, "intent:capacity:1", &first);
    store
        .append_admitted(&Verifier, first, first_intent)
        .unwrap_or_else(|error| panic!("append within ordinary capacity: {error}"));

    let second = candidate(
        "memory:capacity:2",
        "content:v1",
        MemoryAdmissionKind::Observation,
    );
    let second_intent = intent(&store, "intent:capacity:2", &second);
    assert_eq!(
        store.append_admitted(&Verifier, second, second_intent),
        Err(CognitiveStoreV2Error::CapacityExceeded)
    );

    let forget = ForgetIntentV2 {
        intent_id: id("forget:capacity:1"),
        record_id: id("memory:capacity:1"),
        expected_snapshot: store.snapshot_key().clone(),
        writer_fence_digest: digest("writer-fence"),
        authorization_digest: digest("authorization"),
        reason_digest: digest("capacity-delete"),
    };
    store
        .forget(&Verifier, forget)
        .unwrap_or_else(|error| panic!("tombstone must use reserved capacity: {error}"));
    assert_eq!(
        store
            .current_head(&id("memory:capacity:1"))
            .expect("head exists")
            .state,
        RecordState::Tombstone
    );
}

#[test]
fn saturated_retry_journal_blocks_new_admission_but_not_forget() {
    let mut store = AdmittedCognitiveStoreV2::new(snapshot_key(), digest("writer-fence"), 1)
        .unwrap_or_else(|error| panic!("valid one-record store: {error}"));
    let value = candidate(
        "memory:journal:1",
        "content:v1",
        MemoryAdmissionKind::Observation,
    );
    let first_intent = intent(&store, "intent:journal:1", &value);
    let original = store
        .append_admitted(&Verifier, value.clone(), first_intent.clone())
        .unwrap_or_else(|error| panic!("append first: {error}"));

    for index in 2..=3 {
        let retry = intent(&store, &format!("intent:journal:{index}"), &value);
        store
            .append_admitted(&Verifier, value.clone(), retry)
            .unwrap_or_else(|error| panic!("retain bounded unchanged receipt: {error}"));
    }
    let overflow = intent(&store, "intent:journal:4", &value);
    assert_eq!(
        store.append_admitted(&Verifier, value.clone(), overflow),
        Err(CognitiveStoreV2Error::IntentJournalCapacityExceeded)
    );

    let forget = ForgetIntentV2 {
        intent_id: id("forget:journal:1"),
        record_id: id("memory:journal:1"),
        expected_snapshot: store.snapshot_key().clone(),
        writer_fence_digest: digest("writer-fence"),
        authorization_digest: digest("authorization"),
        reason_digest: digest("journal-delete"),
    };
    store
        .forget(&Verifier, forget)
        .unwrap_or_else(|error| panic!("forget must use reserved journal capacity: {error}"));

    let retry = store
        .append_admitted(&Verifier, value, first_intent)
        .unwrap_or_else(|error| panic!("original retry receipt must remain retained: {error}"));
    assert_eq!(retry, original);

    let image = store
        .export_image()
        .unwrap_or_else(|error| panic!("bounded image: {error}"));
    assert_eq!(image.journal.len(), 4);
}

#[test]
fn image_rejects_cross_object_receipt_tampering_even_with_recomputed_digest() {
    let mut store = store();
    let value = candidate(
        "memory:image:1",
        "content:v1",
        MemoryAdmissionKind::Inference,
    );
    let write_intent = intent(&store, "intent:image:1", &value);
    store
        .append_admitted(&Verifier, value, write_intent)
        .unwrap_or_else(|error| panic!("append: {error}"));
    let image = store
        .export_image()
        .unwrap_or_else(|error| panic!("export: {error}"));

    let mut wrong_intent = image.clone();
    wrong_intent.journal[0].receipt.intent_id = id("intent:image:forged");
    wrong_intent.image_digest = wrong_intent.compute_image_digest();
    assert!(matches!(
        wrong_intent.validate(),
        Err(CognitiveStoreV2Error::JournalReceiptMismatch(_))
    ));

    let mut wrong_record = image;
    wrong_record.journal[0].receipt.record_digest = digest("forged-record");
    wrong_record.image_digest = wrong_record.compute_image_digest();
    assert!(matches!(
        wrong_record.validate(),
        Err(CognitiveStoreV2Error::JournalRecordMismatch(_))
    ));
}

#[test]
fn image_rejects_sequence_and_frontier_claims_not_derived_from_history() {
    let mut store = store();
    let value = candidate(
        "memory:image:2",
        "content:v1",
        MemoryAdmissionKind::Observation,
    );
    let write_intent = intent(&store, "intent:image:2", &value);
    store
        .append_admitted(&Verifier, value, write_intent)
        .unwrap_or_else(|error| panic!("append: {error}"));
    let image = store
        .export_image()
        .unwrap_or_else(|error| panic!("export: {error}"));

    let mut wrong_sequence = image.clone();
    wrong_sequence.sequence =
        LogicalSequence::new(99).unwrap_or_else(|error| panic!("sequence: {error}"));
    wrong_sequence.image_digest = wrong_sequence.compute_image_digest();
    assert_eq!(
        wrong_sequence.validate(),
        Err(CognitiveStoreV2Error::ImageSequenceMismatch)
    );

    let mut inflated_frontier = image.clone();
    let mut vector = inflated_frontier.snapshot_key.vector.clone();
    vector.memory_ledger_frontier = vector.memory_ledger_frontier.saturating_add(5);
    inflated_frontier.snapshot_key =
        CognitiveSnapshotKeyV1::new(vector).unwrap_or_else(|error| panic!("snapshot key: {error}"));
    inflated_frontier.image_digest = inflated_frontier.compute_image_digest();
    assert_eq!(
        inflated_frontier.validate(),
        Err(CognitiveStoreV2Error::ImageReceiptCoverageMismatch)
    );

    let mut missing_receipt = image.clone();
    missing_receipt.journal.clear();
    missing_receipt.image_digest = missing_receipt.compute_image_digest();
    assert_eq!(
        missing_receipt.validate(),
        Err(CognitiveStoreV2Error::ImageReceiptCoverageMismatch)
    );

    let mut wrong_frontier = image;
    wrong_frontier.journal.clear();
    let mut vector = wrong_frontier.snapshot_key.vector.clone();
    vector.memory_ledger_frontier = 1;
    wrong_frontier.snapshot_key =
        CognitiveSnapshotKeyV1::new(vector).unwrap_or_else(|error| panic!("snapshot key: {error}"));
    wrong_frontier.image_digest = wrong_frontier.compute_image_digest();
    assert_eq!(
        wrong_frontier.validate(),
        Err(CognitiveStoreV2Error::ImageFrontierMismatch("memory"))
    );
}

fn page_request(
    store: &AdmittedCognitiveStoreV2,
    request_id: &str,
    after: Option<SnapshotCursorV2>,
    maximum_records: u32,
) -> SnapshotPageOpenRequestV2 {
    SnapshotPageOpenRequestV2 {
        request_id: id(request_id),
        scope_id: id("scope:store"),
        purpose_id: id("purpose:memory"),
        minimum_memory_frontier: store.snapshot_key().vector.memory_ledger_frontier,
        minimum_tombstone_frontier: store.snapshot_key().vector.tombstone_frontier,
        authority_epoch: store.snapshot_key().vector.authority_epoch,
        deadline_unix_ms: 100,
        lease_duration_ms: 10,
        maximum_records,
        after,
    }
}

#[test]
fn paged_snapshot_preserves_exact_ancestry_across_page_boundaries() {
    let mut store = store();
    let first = candidate(
        "memory:page:a",
        "content:v1",
        MemoryAdmissionKind::Observation,
    );
    let first_intent = intent(&store, "intent:page:1", &first);
    store
        .append_admitted(&Verifier, first, first_intent)
        .unwrap_or_else(|error| panic!("append first: {error}"));
    let correction = candidate(
        "memory:page:a",
        "content:v2",
        MemoryAdmissionKind::Observation,
    );
    let correction_intent = intent(&store, "intent:page:2", &correction);
    store
        .append_admitted(&Verifier, correction, correction_intent)
        .unwrap_or_else(|error| panic!("append correction: {error}"));
    let second = candidate(
        "memory:page:b",
        "content:v1",
        MemoryAdmissionKind::Observation,
    );
    let second_intent = intent(&store, "intent:page:3", &second);
    store
        .append_admitted(&Verifier, second, second_intent)
        .unwrap_or_else(|error| panic!("append second record: {error}"));

    let first_page = store
        .open_snapshot_page(10, page_request(&store, "page:1", None, 1))
        .unwrap_or_else(|error| panic!("first page: {error}"));
    assert_eq!(first_page.records.len(), 1);
    assert!(!first_page.complete);
    assert_eq!(first_page.records[0].revision, revision(1));
    let first_cursor = first_page.next.expect("next cursor");

    let second_page = store
        .open_snapshot_page(
            10,
            page_request(&store, "page:2", Some(first_cursor.clone()), 1),
        )
        .unwrap_or_else(|error| panic!("second page: {error}"));
    assert_eq!(second_page.records.len(), 1);
    assert_eq!(second_page.records[0].record_id, first_cursor.record_id);
    assert_eq!(second_page.records[0].revision, revision(2));
    assert_eq!(
        second_page.records[0].predecessor_digest,
        Some(first_cursor.record_digest)
    );
    assert!(!second_page.complete);

    let third_page = store
        .open_snapshot_page(10, page_request(&store, "page:3", second_page.next, 1))
        .unwrap_or_else(|error| panic!("third page: {error}"));
    assert_eq!(third_page.records.len(), 1);
    assert_eq!(third_page.records[0].record_id, id("memory:page:b"));
    assert!(third_page.complete);
    assert!(third_page.next.is_none());
}

#[test]
fn paged_snapshot_rejects_continuation_after_store_cut_changes() {
    let mut store = store();
    let first = candidate(
        "memory:page:stable:a",
        "content:v1",
        MemoryAdmissionKind::Observation,
    );
    let first_intent = intent(&store, "intent:page:stable:1", &first);
    store
        .append_admitted(&Verifier, first, first_intent)
        .unwrap_or_else(|error| panic!("append first: {error}"));
    let second = candidate(
        "memory:page:stable:b",
        "content:v1",
        MemoryAdmissionKind::Observation,
    );
    let second_intent = intent(&store, "intent:page:stable:2", &second);
    store
        .append_admitted(&Verifier, second, second_intent)
        .unwrap_or_else(|error| panic!("append second: {error}"));

    let first_page = store
        .open_snapshot_page(10, page_request(&store, "page:stable:1", None, 1))
        .unwrap_or_else(|error| panic!("first page: {error}"));
    let cursor = first_page.next.expect("continuation cursor");

    let third = candidate(
        "memory:page:stable:c",
        "content:v1",
        MemoryAdmissionKind::Observation,
    );
    let third_intent = intent(&store, "intent:page:stable:3", &third);
    store
        .append_admitted(&Verifier, third, third_intent)
        .unwrap_or_else(|error| panic!("append intervening mutation: {error}"));

    assert_eq!(
        store.open_snapshot_page(10, page_request(&store, "page:stable:2", Some(cursor), 1),),
        Err(CognitiveStoreV2Error::SnapshotCursorMismatch)
    );
}

#[test]
fn paged_snapshot_rejects_forged_cursor_and_broken_page_ancestry() {
    let mut store = store();
    let first = candidate(
        "memory:page:forged",
        "content:v1",
        MemoryAdmissionKind::Observation,
    );
    let first_intent = intent(&store, "intent:page:forged:1", &first);
    store
        .append_admitted(&Verifier, first, first_intent)
        .unwrap_or_else(|error| panic!("append first: {error}"));
    let correction = candidate(
        "memory:page:forged",
        "content:v2",
        MemoryAdmissionKind::Observation,
    );
    let correction_intent = intent(&store, "intent:page:forged:2", &correction);
    store
        .append_admitted(&Verifier, correction, correction_intent)
        .unwrap_or_else(|error| panic!("append correction: {error}"));

    let first_page = store
        .open_snapshot_page(10, page_request(&store, "page:forged:1", None, 1))
        .unwrap_or_else(|error| panic!("first page: {error}"));
    let mut forged = first_page.next.clone().expect("cursor");
    forged.record_digest = digest("forged-cursor");
    assert_eq!(
        store.open_snapshot_page(10, page_request(&store, "page:forged:2", Some(forged), 1),),
        Err(CognitiveStoreV2Error::SnapshotCursorMismatch)
    );

    let mut second_page = store
        .open_snapshot_page(
            10,
            page_request(&store, "page:forged:3", first_page.next, 1),
        )
        .unwrap_or_else(|error| panic!("second page: {error}"));
    second_page.records[0].predecessor_digest = Some(digest("wrong-predecessor"));
    second_page.page_digest = second_page.compute_page_digest();
    assert_eq!(
        second_page.validate(10),
        Err(CognitiveStoreV2Error::SnapshotPageAncestryMismatch)
    );
}

#[test]
fn canonical_event_shadow_binds_exact_admission_and_write_receipt() {
    let mut store = store();
    let candidate = candidate(
        "memory:canonical:1",
        "content:v1",
        MemoryAdmissionKind::Observation,
    );
    let event = canonical_event("memory:canonical:1");
    let write_intent = intent(&store, "intent:canonical:1", &candidate);
    let result = store
        .append_admitted_with_canonical_shadow(
            &Verifier,
            candidate.clone(),
            write_intent,
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
    let candidate = candidate(
        "memory:canonical:2",
        "content:v1",
        MemoryAdmissionKind::Observation,
    );

    let mut wrong_source = canonical_event("memory:canonical:2");
    wrong_source.provenance[0].source_sha256 = contract_digest("different-source");
    let write_intent = intent(&store, "intent:canonical:source", &candidate);
    assert_eq!(
        store.append_admitted_with_canonical_shadow(
            &Verifier,
            candidate.clone(),
            write_intent,
            wrong_source,
        ),
        Err(CognitiveStoreV2Error::CanonicalSourceProvenanceMismatch)
    );
    assert!(store.current_head(&id("memory:canonical:2")).is_none());

    let mut wrong_verification = canonical_event("memory:canonical:2");
    wrong_verification.verification = MemoryVerificationStateV1::Contradicted;
    let write_intent = intent(&store, "intent:canonical:verification", &candidate);
    assert_eq!(
        store.append_admitted_with_canonical_shadow(
            &Verifier,
            candidate,
            write_intent,
            wrong_verification,
        ),
        Err(CognitiveStoreV2Error::CanonicalVerificationMismatch)
    );
    assert!(store.current_head(&id("memory:canonical:2")).is_none());
}

#[test]
fn canonical_event_shadow_receipt_tamper_fails_closed() {
    let mut store = store();
    let candidate = candidate(
        "memory:canonical:3",
        "content:v1",
        MemoryAdmissionKind::Observation,
    );
    let write_intent = intent(&store, "intent:canonical:3", &candidate);
    let result = store
        .append_admitted_with_canonical_shadow(
            &Verifier,
            candidate,
            write_intent,
            canonical_event("memory:canonical:3"),
        )
        .unwrap_or_else(|error| panic!("canonical shadow append: {error}"));

    let mut tampered = result;
    tampered.shadow_receipt.record_digest = digest("tampered-record");
    assert_eq!(
        tampered.validate(),
        Err(CognitiveStoreV2Error::CanonicalShadowReceiptMismatch)
    );
}

#[test]
fn image_rejects_revision_commits_reordered_with_consistent_global_frontiers() {
    let mut store = store();
    for (operation, content) in [("intent:ordered:1", "v1"), ("intent:ordered:2", "v2")] {
        let value = candidate("memory:ordered", content, MemoryAdmissionKind::Observation);
        let write = intent(&store, operation, &value);
        store
            .append_admitted(&Verifier, value, write)
            .expect("append revision");
    }
    let mut image = store.export_image().expect("export image");
    let earlier = image.journal[0].receipt.snapshot_key.clone();
    let later = image.journal[1].receipt.snapshot_key.clone();
    image.journal[0].receipt.committed_frontier = later.vector.memory_ledger_frontier;
    image.journal[0].receipt.snapshot_key = later;
    image.journal[1].receipt.committed_frontier = earlier.vector.memory_ledger_frontier;
    image.journal[1].receipt.snapshot_key = earlier;
    image.image_digest = image.compute_image_digest();

    assert_eq!(
        image.validate(),
        Err(CognitiveStoreV2Error::ImageReceiptCoverageMismatch)
    );
}

#[test]
fn unchanged_image_receipt_must_name_the_live_head_at_its_exact_cut() {
    let mut store = store();
    let value = candidate("memory:retry-cut", "v1", MemoryAdmissionKind::Observation);
    for operation in ["intent:retry-cut:insert", "intent:retry-cut:unchanged"] {
        let write = intent(&store, operation, &value);
        store
            .append_admitted(&Verifier, value.clone(), write)
            .expect("append or unchanged");
    }
    let corrected = candidate("memory:retry-cut", "v2", MemoryAdmissionKind::Observation);
    let write = intent(&store, "intent:retry-cut:correct", &corrected);
    let correction = store
        .append_admitted(&Verifier, corrected, write)
        .expect("correct");
    let image = store.export_image().expect("export image");

    let mut future_revision = image.clone();
    let unchanged = future_revision
        .journal
        .iter_mut()
        .find(|entry| entry.receipt.disposition == MemoryWriteDisposition::Unchanged)
        .expect("unchanged receipt");
    unchanged.receipt.record_digest = correction.record_digest;
    future_revision.image_digest = future_revision.compute_image_digest();
    assert!(matches!(
        future_revision.validate(),
        Err(CognitiveStoreV2Error::JournalSnapshotMismatch(_))
    ));

    let mut superseded_revision = image;
    let unchanged = superseded_revision
        .journal
        .iter_mut()
        .find(|entry| entry.receipt.disposition == MemoryWriteDisposition::Unchanged)
        .expect("unchanged receipt");
    unchanged.receipt.committed_frontier = correction.committed_frontier;
    unchanged.receipt.snapshot_key = correction.snapshot_key;
    superseded_revision.image_digest = superseded_revision.compute_image_digest();
    assert!(matches!(
        superseded_revision.validate(),
        Err(CognitiveStoreV2Error::JournalSnapshotMismatch(_))
    ));
}

#[test]
fn unchanged_image_receipt_cannot_claim_a_tombstone_as_unchanged_admission() {
    let mut store = store();
    let value = candidate(
        "memory:retry-delete",
        "v1",
        MemoryAdmissionKind::Observation,
    );
    for operation in [
        "intent:retry-delete:insert",
        "intent:retry-delete:unchanged",
    ] {
        let write = intent(&store, operation, &value);
        store
            .append_admitted(&Verifier, value.clone(), write)
            .expect("append or unchanged");
    }
    let forgotten = store
        .forget(
            &Verifier,
            ForgetIntentV2 {
                intent_id: id("forget:retry-delete"),
                record_id: value.candidate_id,
                expected_snapshot: store.snapshot_key().clone(),
                writer_fence_digest: digest("writer-fence"),
                authorization_digest: digest("authorization"),
                reason_digest: digest("delete"),
            },
        )
        .expect("forget");
    let mut image = store.export_image().expect("export image");
    let unchanged = image
        .journal
        .iter_mut()
        .find(|entry| entry.receipt.disposition == MemoryWriteDisposition::Unchanged)
        .expect("unchanged receipt");
    unchanged.receipt.record_digest = forgotten.record_digest;
    unchanged.receipt.committed_frontier = forgotten.committed_frontier;
    unchanged.receipt.snapshot_key = forgotten.snapshot_key;
    image.image_digest = image.compute_image_digest();

    assert!(matches!(
        image.validate(),
        Err(CognitiveStoreV2Error::JournalSnapshotMismatch(_))
    ));
}

#[test]
fn reopen_capacity_reduction_preserves_the_tombstone_revision_and_journal_reserve() {
    let mut store = AdmittedCognitiveStoreV2::new(snapshot_key(), digest("writer-fence"), 2)
        .expect("store with two ordinary revisions");
    for (record, operation) in [
        ("memory:reserve:1", "intent:reserve:1"),
        ("memory:reserve:2", "intent:reserve:2"),
    ] {
        let value = candidate(record, "v1", MemoryAdmissionKind::Observation);
        let write = intent(&store, operation, &value);
        store
            .append_admitted(&Verifier, value, write)
            .expect("append");
    }
    let image = store.export_image().expect("export image");
    assert_eq!(
        AdmittedCognitiveStoreV2::reopen(image, 1),
        Err(CognitiveStoreV2Error::InvalidCapacity)
    );

    let mut store = AdmittedCognitiveStoreV2::new(snapshot_key(), digest("writer-fence"), 2)
        .expect("store with larger journal");
    let value = candidate(
        "memory:reserve:journal",
        "v1",
        MemoryAdmissionKind::Observation,
    );
    for operation in [
        "intent:reserve:journal:1",
        "intent:reserve:journal:2",
        "intent:reserve:journal:3",
        "intent:reserve:journal:4",
    ] {
        let write = intent(&store, operation, &value);
        store
            .append_admitted(&Verifier, value.clone(), write)
            .expect("append or unchanged");
    }
    let image = store.export_image().expect("export image");
    assert_eq!(
        AdmittedCognitiveStoreV2::reopen(image, 1),
        Err(CognitiveStoreV2Error::InvalidCapacity)
    );
}

#[test]
fn full_snapshot_rejects_rebinding_a_valid_record_set_to_an_unrelated_cut() {
    let mut store = store();
    let value = candidate(
        "memory:snapshot-cut",
        "v1",
        MemoryAdmissionKind::Observation,
    );
    let write = intent(&store, "intent:snapshot-cut", &value);
    store
        .append_admitted(&Verifier, value, write)
        .expect("append");
    let snapshot = store
        .open_snapshot(
            10,
            SnapshotOpenRequestV2 {
                request_id: id("snapshot:cut"),
                scope_id: id("scope:store"),
                purpose_id: id("purpose:memory"),
                minimum_memory_frontier: 1,
                minimum_tombstone_frontier: 1,
                authority_epoch: 1,
                deadline_unix_ms: 100,
                lease_duration_ms: 10,
            },
        )
        .expect("open snapshot");

    let mut wrong_generation = snapshot.clone();
    let mut vector = wrong_generation.snapshot_key.vector.clone();
    vector.memory_ledger_frontier += 1;
    wrong_generation.snapshot_key = CognitiveSnapshotKeyV1::new(vector).expect("valid key");
    wrong_generation.receipt_digest = wrong_generation.compute_receipt_digest();
    assert_eq!(
        wrong_generation.validate(10),
        Err(CognitiveStoreV2Error::SnapshotConflict)
    );

    let mut wrong_sequence = snapshot;
    wrong_sequence.sequence = LogicalSequence::new(3).expect("valid sequence");
    wrong_sequence.receipt_digest = wrong_sequence.compute_receipt_digest();
    assert_eq!(
        wrong_sequence.validate(10),
        Err(CognitiveStoreV2Error::ImageSequenceMismatch)
    );
}

#[test]
fn snapshot_envelopes_reject_future_opening_times_and_excessive_leases() {
    let store = store();
    let page = store
        .open_snapshot_page(10, page_request(&store, "page:lease", None, 1))
        .expect("open page");
    assert_eq!(
        page.validate(9),
        Err(CognitiveStoreV2Error::SnapshotLeaseExpired)
    );
    let mut extended = page;
    extended.lease_expires_unix_ms = extended.opened_at_unix_ms + MAX_V2_SNAPSHOT_LEASE_MS + 1;
    extended.page_digest = extended.compute_page_digest();
    assert_eq!(
        extended.validate(10),
        Err(CognitiveStoreV2Error::SnapshotLeaseExpired)
    );
}

#[test]
fn full_and_paged_snapshots_reject_a_successor_after_a_terminal_tombstone() {
    let mut store = store();
    let value = candidate(
        "memory:terminal-snapshot",
        "v1",
        MemoryAdmissionKind::Observation,
    );
    let write = intent(&store, "intent:terminal-snapshot", &value);
    store
        .append_admitted(&Verifier, value, write)
        .expect("append");
    store
        .forget(
            &Verifier,
            ForgetIntentV2 {
                intent_id: id("forget:terminal-snapshot"),
                record_id: id("memory:terminal-snapshot"),
                expected_snapshot: store.snapshot_key().clone(),
                writer_fence_digest: digest("writer-fence"),
                authorization_digest: digest("authorization"),
                reason_digest: digest("delete"),
            },
        )
        .expect("forget");
    let mut page = store
        .open_snapshot_page(10, page_request(&store, "page:terminal-snapshot", None, 8))
        .expect("open page");
    let tombstone = page.records.last().expect("terminal tombstone");
    let mut successor = tombstone.clone();
    successor.revision = revision(3);
    successor.predecessor_digest = Some(tombstone.record_digest());
    successor.content_digest = digest("changed tombstone");
    page.records.push(successor.clone());
    page.sequence = LogicalSequence::new(4).expect("valid sequence");
    let mut page_vector = page.snapshot_key.vector.clone();
    page_vector.memory_ledger_frontier += 1;
    page_vector.tombstone_frontier += 1;
    page.snapshot_key = CognitiveSnapshotKeyV1::new(page_vector).expect("valid page key");
    page.page_digest = page.compute_page_digest();
    assert_eq!(
        page.validate(10),
        Err(CognitiveStoreV2Error::SnapshotPageAncestryMismatch)
    );

    let mut snapshot = store
        .open_snapshot(
            10,
            SnapshotOpenRequestV2 {
                request_id: id("snapshot:terminal"),
                scope_id: id("scope:store"),
                purpose_id: id("purpose:memory"),
                minimum_memory_frontier: 1,
                minimum_tombstone_frontier: 1,
                authority_epoch: 1,
                deadline_unix_ms: 100,
                lease_duration_ms: 10,
            },
        )
        .expect("open snapshot");
    let mut vector = snapshot.snapshot_key.vector.clone();
    vector.memory_ledger_frontier += 1;
    vector.tombstone_frontier += 1;
    snapshot.snapshot_key = CognitiveSnapshotKeyV1::new(vector).expect("valid key");
    snapshot.sequence = LogicalSequence::new(4).expect("valid sequence");
    snapshot.snapshot.records.push(successor);
    snapshot.snapshot = build_snapshot(
        generation(snapshot.snapshot_key.vector.memory_ledger_frontier),
        snapshot.snapshot.records,
    )
    .expect("individually valid records");
    snapshot.receipt_digest = snapshot.compute_receipt_digest();
    assert_eq!(
        snapshot.validate(10),
        Err(CognitiveStoreV2Error::ResurrectionDenied(
            id("memory:terminal-snapshot").to_string()
        ))
    );
}

#[test]
fn page_rejects_impossible_sequence_frontiers_and_initial_tombstone() {
    let mut store = store();
    let value = candidate("memory:page-bounds", "v1", MemoryAdmissionKind::Inference);
    let write = intent(&store, "intent:page-bounds", &value);
    store
        .append_admitted(&Verifier, value, write)
        .expect("append fact");
    let page = store
        .open_snapshot_page(10, page_request(&store, "page:bounds", None, 8))
        .expect("open page");

    let mut wrong_sequence = page.clone();
    wrong_sequence.sequence = LogicalSequence::new(1).expect("valid sequence");
    wrong_sequence.page_digest = wrong_sequence.compute_page_digest();
    assert_eq!(
        wrong_sequence.validate(10),
        Err(CognitiveStoreV2Error::ImageSequenceMismatch)
    );

    let mut missing_fact_frontier = page.clone();
    let mut vector = missing_fact_frontier.snapshot_key.vector.clone();
    vector.knowledge_fact_frontier = 0;
    missing_fact_frontier.snapshot_key = CognitiveSnapshotKeyV1::new(vector).expect("valid key");
    missing_fact_frontier.page_digest = missing_fact_frontier.compute_page_digest();
    assert_eq!(
        missing_fact_frontier.validate(10),
        Err(CognitiveStoreV2Error::ImageFrontierMismatch(
            "knowledge_fact"
        ))
    );

    let mut initial_tombstone = page;
    initial_tombstone.records[0].state = RecordState::Tombstone;
    initial_tombstone.page_digest = initial_tombstone.compute_page_digest();
    assert_eq!(
        initial_tombstone.validate(10),
        Err(CognitiveStoreV2Error::SnapshotPageAncestryMismatch)
    );
}

#[test]
fn continuation_validation_retains_the_previous_tombstone_state_across_pages() {
    let mut store = store();
    let value = candidate(
        "memory:cross-page:a",
        "v1",
        MemoryAdmissionKind::Observation,
    );
    let write = intent(&store, "intent:cross-page:a", &value);
    store
        .append_admitted(&Verifier, value, write)
        .expect("append first memory");
    store
        .forget(
            &Verifier,
            ForgetIntentV2 {
                intent_id: id("forget:cross-page:a"),
                record_id: id("memory:cross-page:a"),
                expected_snapshot: store.snapshot_key().clone(),
                writer_fence_digest: digest("writer-fence"),
                authorization_digest: digest("authorization"),
                reason_digest: digest("delete"),
            },
        )
        .expect("forget first memory");
    let unrelated = candidate(
        "memory:cross-page:z",
        "v1",
        MemoryAdmissionKind::Observation,
    );
    let write = intent(&store, "intent:cross-page:z", &unrelated);
    store
        .append_admitted(&Verifier, unrelated, write)
        .expect("append next memory");

    let first = store
        .open_snapshot_page(10, page_request(&store, "page:cross-page:1", None, 2))
        .expect("page ending at the tombstone");
    let next = store
        .open_snapshot_page(
            10,
            page_request(&store, "page:cross-page:2", first.next.clone(), 1),
        )
        .expect("legitimate next memory");
    assert_eq!(next.validate_continuation(10, &first), Ok(()));

    let mut empty_continuation = next.clone();
    empty_continuation.records.clear();
    empty_continuation.page_digest = empty_continuation.compute_page_digest();
    assert_eq!(
        empty_continuation.validate_continuation(10, &first),
        Err(CognitiveStoreV2Error::SnapshotCursorMismatch),
    );

    let mut forged = next;
    let tombstone = first.records.last().expect("terminal record");
    let mut successor = tombstone.clone();
    successor.revision = revision(3);
    successor.predecessor_digest = Some(tombstone.record_digest());
    successor.state = RecordState::Live;
    successor.content_digest = digest("resurrected-content");
    forged.records = vec![successor];
    forged.page_digest = forged.compute_page_digest();
    // The standalone cursor cannot disclose whether its bound predecessor was
    // tombstoned; retaining the preceding page supplies that missing evidence.
    assert_eq!(forged.validate(10), Ok(()));
    assert_eq!(
        forged.validate_continuation(10, &first),
        Err(CognitiveStoreV2Error::SnapshotPageAncestryMismatch),
    );
}
