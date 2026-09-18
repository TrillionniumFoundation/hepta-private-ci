use super::*;

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
        let write_intent = intent(
            &store,
            &format!("intent:verification:{index}"),
            &value,
        );
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
    let mut store =
        AdmittedCognitiveStoreV2::new(snapshot_key(), digest("writer-fence"), 1)
            .unwrap_or_else(|error| panic!("valid one-record store: {error}"));
    let first = candidate("memory:capacity:1", "content:v1", MemoryAdmissionKind::Observation);
    let first_intent = intent(&store, "intent:capacity:1", &first);
    store
        .append_admitted(&Verifier, first, first_intent)
        .unwrap_or_else(|error| panic!("append within ordinary capacity: {error}"));

    let second = candidate("memory:capacity:2", "content:v1", MemoryAdmissionKind::Observation);
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
    let mut store =
        AdmittedCognitiveStoreV2::new(snapshot_key(), digest("writer-fence"), 1)
            .unwrap_or_else(|error| panic!("valid one-record store: {error}"));
    let value = candidate("memory:journal:1", "content:v1", MemoryAdmissionKind::Observation);
    let first_intent = intent(&store, "intent:journal:1", &value);
    store
        .append_admitted(&Verifier, value.clone(), first_intent)
        .unwrap_or_else(|error| panic!("append first: {error}"));

    for index in 2..=4 {
        let retry = intent(&store, &format!("intent:journal:{index}"), &value);
        store
            .append_admitted(&Verifier, value.clone(), retry)
            .unwrap_or_else(|error| panic!("retain bounded unchanged receipt: {error}"));
    }
    let overflow = intent(&store, "intent:journal:5", &value);
    assert_eq!(
        store.append_admitted(&Verifier, value, overflow),
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
        .unwrap_or_else(|error| panic!("forget must shed retained retry receipt: {error}"));
    let image = store
        .export_image()
        .unwrap_or_else(|error| panic!("bounded image: {error}"));
    assert!(image.journal.len() <= 4);
}

#[test]
fn image_rejects_cross_object_receipt_tampering_even_with_recomputed_digest() {
    let mut store = store();
    let value = candidate("memory:image:1", "content:v1", MemoryAdmissionKind::Inference);
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
    let value = candidate("memory:image:2", "content:v1", MemoryAdmissionKind::Observation);
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

    let mut wrong_frontier = image;
    wrong_frontier.journal.clear();
    let mut vector = wrong_frontier.snapshot_key.vector.clone();
    vector.memory_ledger_frontier = 1;
    wrong_frontier.snapshot_key = CognitiveSnapshotKeyV1::new(vector)
        .unwrap_or_else(|error| panic!("snapshot key: {error}"));
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
    let first = candidate("memory:page:a", "content:v1", MemoryAdmissionKind::Observation);
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
    let second = candidate("memory:page:b", "content:v1", MemoryAdmissionKind::Observation);
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
    let first_cursor = first_page.next.clone().expect("next cursor");

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
        .open_snapshot_page(
            10,
            page_request(&store, "page:3", second_page.next.clone(), 1),
        )
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
    let cursor = first_page.next.clone().expect("continuation cursor");

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
        store.open_snapshot_page(
            10,
            page_request(&store, "page:stable:2", Some(cursor), 1),
        ),
        Err(CognitiveStoreV2Error::SnapshotCursorMismatch)
    );
}

#[test]
fn paged_snapshot_rejects_forged_cursor_and_broken_page_ancestry() {
    let mut store = store();
    let first = candidate("memory:page:forged", "content:v1", MemoryAdmissionKind::Observation);
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
        store.open_snapshot_page(
            10,
            page_request(&store, "page:forged:2", Some(forged), 1),
        ),
        Err(CognitiveStoreV2Error::SnapshotCursorMismatch)
    );

    let mut second_page = store
        .open_snapshot_page(
            10,
            page_request(&store, "page:forged:3", first_page.next.clone(), 1),
        )
        .unwrap_or_else(|error| panic!("second page: {error}"));
    second_page.records[0].predecessor_digest = Some(digest("wrong-predecessor"));
    second_page.page_digest = second_page.compute_page_digest();
    assert_eq!(
        second_page.validate(10),
        Err(CognitiveStoreV2Error::SnapshotPageAncestryMismatch)
    );
}
