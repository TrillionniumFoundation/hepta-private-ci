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

fn sequence(value: u64) -> LogicalSequence {
    LogicalSequence::new(value).unwrap_or_else(|error| panic!("valid sequence: {error}"))
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
fn only_verified_candidates_can_enter_the_live_ledger() {
    for (verification, expected) in [
        (
            MemoryVerificationState::Unverified,
            CognitiveStoreV2Error::UnverifiedCandidate,
        ),
        (
            MemoryVerificationState::Contradicted,
            CognitiveStoreV2Error::ContradictedCandidate,
        ),
        (
            MemoryVerificationState::Revoked,
            CognitiveStoreV2Error::RevokedCandidate,
        ),
    ] {
        let mut store = store();
        let mut value = candidate("memory:verification", "content", MemoryAdmissionKind::Inference);
        value.verification = verification;
        let write_intent = intent(&store, "intent:verification", &value);
        assert_eq!(
            store.append_admitted(&Verifier, value, write_intent),
            Err(expected)
        );
        assert!(store.current_head(&id("memory:verification")).is_none());
        assert_eq!(store.sequence(), sequence(1));
    }
}

#[test]
fn revocation_reserve_allows_forget_after_ordinary_capacity_is_full() {
    let mut store =
        AdmittedCognitiveStoreV2::new(snapshot_key(), digest("writer-fence"), 1)
            .unwrap_or_else(|error| panic!("valid tiny store: {error}"));
    let first = candidate("memory:1", "content:v1", MemoryAdmissionKind::Observation);
    store
        .append_admitted(&Verifier, first.clone(), intent(&store, "intent:1", &first))
        .unwrap_or_else(|error| panic!("fill ordinary capacity: {error}"));

    let second = candidate("memory:2", "content:v1", MemoryAdmissionKind::Observation);
    let second_intent = intent(&store, "intent:2", &second);
    assert_eq!(
        store.append_admitted(&Verifier, second, second_intent),
        Err(CognitiveStoreV2Error::CapacityExceeded)
    );

    let tombstone = store
        .forget(
            &Verifier,
            ForgetIntentV2 {
                intent_id: id("forget:1"),
                record_id: id("memory:1"),
                expected_snapshot: store.snapshot_key().clone(),
                writer_fence_digest: digest("writer-fence"),
                authorization_digest: digest("authorization"),
                reason_digest: digest("capacity-safe-delete"),
            },
        )
        .unwrap_or_else(|error| panic!("revocation reserve must remain writable: {error}"));
    assert_eq!(tombstone.disposition, MemoryWriteDisposition::Inserted);
    assert_eq!(store.history(&id("memory:1")).expect("history").len(), 2);
    assert_eq!(
        store.current_head(&id("memory:1")).expect("head").state,
        RecordState::Tombstone
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
fn image_validation_rejects_journal_receipt_identity_drift_even_after_rehash() {
    let mut store = store();
    let first = candidate("memory:1", "content:v1", MemoryAdmissionKind::Observation);
    store
        .append_admitted(&Verifier, first.clone(), intent(&store, "intent:1", &first))
        .unwrap_or_else(|error| panic!("append: {error}"));

    let mut image = store.export_image().expect("image");
    image.journal[0].receipt.intent_id = id("intent:forged");
    image.image_digest = image.compute_image_digest();
    assert_eq!(
        image.validate(),
        Err(CognitiveStoreV2Error::JournalReceiptMismatch("intent_id"))
    );
}

#[test]
fn image_validation_rejects_sequence_and_frontier_drift_even_after_rehash() {
    let mut store = store();
    let first = candidate("memory:1", "content:v1", MemoryAdmissionKind::Observation);
    store
        .append_admitted(&Verifier, first.clone(), intent(&store, "intent:1", &first))
        .unwrap_or_else(|error| panic!("append: {error}"));

    let mut sequence_drift = store.export_image().expect("image");
    sequence_drift.sequence = sequence(1);
    sequence_drift.image_digest = sequence_drift.compute_image_digest();
    assert_eq!(
        sequence_drift.validate(),
        Err(CognitiveStoreV2Error::ImageSequenceMismatch)
    );

    let mut frontier_drift = store.export_image().expect("image");
    let mut vector = frontier_drift.snapshot_key.vector.clone();
    vector.memory_ledger_frontier = 1;
    frontier_drift.snapshot_key =
        CognitiveSnapshotKeyV1::new(vector).expect("structurally valid forged frontier");
    frontier_drift.image_digest = frontier_drift.compute_image_digest();
    assert_eq!(
        frontier_drift.validate(),
        Err(CognitiveStoreV2Error::ImageFrontierMismatch("memory"))
    );
}


#[test]
fn paged_snapshot_binds_one_ledger_root_and_rejects_midstream_mutation() {
    let mut store = store();
    for index in 0..5 {
        let record_id = format!("memory:{index}");
        let content = format!("content:{index}");
        let candidate = candidate(&record_id, &content, MemoryAdmissionKind::Observation);
        let intent_id = format!("intent:{index}");
        let write_intent = intent(&store, &intent_id, &candidate);
        store
            .append_admitted(&Verifier, candidate, write_intent)
            .unwrap_or_else(|error| panic!("append {index}: {error}"));
    }

    let base_request = SnapshotOpenRequestV2 {
        request_id: id("snapshot-page:1"),
        scope_id: id("scope:store"),
        purpose_id: id("purpose:memory"),
        minimum_memory_frontier: store.snapshot_key().vector.memory_ledger_frontier,
        minimum_tombstone_frontier: store.snapshot_key().vector.tombstone_frontier,
        authority_epoch: 1,
        deadline_unix_ms: 1_000,
        lease_duration_ms: 100,
    };
    let first = store
        .open_snapshot_page(
            10,
            SnapshotPageOpenRequestV2 {
                snapshot: base_request.clone(),
                cursor: 0,
                maximum_records: 2,
                expected_ledger_digest: None,
            },
        )
        .expect("first page");
    assert_eq!(first.records.len(), 2);
    assert_eq!(first.cursor, 0);
    assert_eq!(first.next_cursor, Some(2));
    assert_eq!(first.total_records, 5);
    assert!(first.previous_record_digest.is_none());

    let second = store
        .open_snapshot_page(
            10,
            SnapshotPageOpenRequestV2 {
                snapshot: base_request.clone(),
                cursor: 2,
                maximum_records: 2,
                expected_ledger_digest: Some(first.ledger_digest),
            },
        )
        .expect("second page");
    assert_eq!(
        second.previous_record_digest,
        first.records.last().map(MemoryRecord::record_digest)
    );
    assert_eq!(second.next_cursor, Some(4));
    assert_eq!(second.ledger_digest, first.ledger_digest);

    let extra = candidate("memory:5", "content:5", MemoryAdmissionKind::Observation);
    let extra_intent = intent(&store, "intent:5", &extra);
    store
        .append_admitted(&Verifier, extra, extra_intent)
        .expect("mutate between pages");
    assert_eq!(
        store.open_snapshot_page(
            10,
            SnapshotPageOpenRequestV2 {
                snapshot: SnapshotOpenRequestV2 {
                    minimum_memory_frontier: 1,
                    ..base_request
                },
                cursor: 4,
                maximum_records: 2,
                expected_ledger_digest: Some(first.ledger_digest),
            },
        ),
        Err(CognitiveStoreV2Error::DigestMismatch("ledger_root"))
    );
}
