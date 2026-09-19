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
fn admitted_store_rejects_non_verified_candidates_before_mutation() {
    let mut store = store();

    let mut unverified = candidate(
        "memory:unverified",
        "content:v1",
        MemoryAdmissionKind::Inference,
    );
    unverified.verification = MemoryVerificationState::Unverified;
    let unverified_intent = intent(&store, "intent:unverified", &unverified);
    assert_eq!(
        store.append_admitted(&Verifier, unverified, unverified_intent),
        Err(CognitiveStoreV2Error::UnverifiedCandidate)
    );
    assert!(store.current_head(&id("memory:unverified")).is_none());

    let mut contradicted = candidate(
        "memory:contradicted",
        "content:v1",
        MemoryAdmissionKind::Inference,
    );
    contradicted.verification = MemoryVerificationState::Contradicted;
    let contradicted_intent = intent(&store, "intent:contradicted", &contradicted);
    assert_eq!(
        store.append_admitted(&Verifier, contradicted, contradicted_intent),
        Err(CognitiveStoreV2Error::ContradictedCandidate)
    );
    assert!(store.current_head(&id("memory:contradicted")).is_none());

    let mut revoked = candidate(
        "memory:revoked",
        "content:v1",
        MemoryAdmissionKind::Observation,
    );
    revoked.verification = MemoryVerificationState::Revoked;
    let revoked_intent = intent(&store, "intent:revoked", &revoked);
    assert_eq!(
        store.append_admitted(&Verifier, revoked, revoked_intent),
        Err(CognitiveStoreV2Error::RevokedCandidate)
    );
    assert!(store.current_head(&id("memory:revoked")).is_none());
}

#[test]
fn terminal_forget_survives_ordinary_record_and_journal_capacity() {
    let mut store = AdmittedCognitiveStoreV2::new(snapshot_key(), digest("writer-fence"), 1)
        .unwrap_or_else(|error| panic!("valid bounded store: {error}"));
    let first = candidate(
        "memory:capacity",
        "content:v1",
        MemoryAdmissionKind::Observation,
    );
    store
        .append_admitted(
            &Verifier,
            first.clone(),
            intent(&store, "intent:capacity:first", &first),
        )
        .unwrap_or_else(|error| panic!("append first: {error}"));

    let unchanged = candidate(
        "memory:capacity",
        "content:v1",
        MemoryAdmissionKind::Observation,
    );
    store
        .append_admitted(
            &Verifier,
            unchanged.clone(),
            intent(&store, "intent:capacity:unchanged", &unchanged),
        )
        .unwrap_or_else(|error| panic!("journal unchanged: {error}"));
    let overflow_intent = intent(&store, "intent:capacity:overflow", &unchanged);
    assert_eq!(
        store.append_admitted(&Verifier, unchanged, overflow_intent),
        Err(CognitiveStoreV2Error::IntentJournalCapacityExceeded)
    );

    let before = store.snapshot_key().vector.tombstone_frontier;
    store
        .forget(
            &Verifier,
            ForgetIntentV2 {
                intent_id: id("intent:capacity:forget"),
                record_id: id("memory:capacity"),
                expected_snapshot: store.snapshot_key().clone(),
                writer_fence_digest: digest("writer-fence"),
                authorization_digest: digest("authorization"),
                reason_digest: digest("capacity-delete"),
            },
        )
        .unwrap_or_else(|error| panic!("terminal forget must remain available: {error}"));
    let history = store.history(&id("memory:capacity")).expect("history");
    assert_eq!(history.len(), 2);
    assert_eq!(history[1].state, RecordState::Tombstone);
    assert_eq!(store.snapshot_key().vector.tombstone_frontier, before + 1);
}

#[test]
fn intent_retention_is_monotonic_bounded_and_survives_reopen() {
    let mut store = AdmittedCognitiveStoreV2::new(snapshot_key(), digest("writer-fence"), 2)
        .unwrap_or_else(|error| panic!("valid bounded store: {error}"));
    let first = candidate(
        "memory:retention:1",
        "one",
        MemoryAdmissionKind::Observation,
    );
    store
        .append_admitted(
            &Verifier,
            first.clone(),
            intent(&store, "intent:retention:1", &first),
        )
        .unwrap_or_else(|error| panic!("first: {error}"));
    let second = candidate(
        "memory:retention:2",
        "two",
        MemoryAdmissionKind::Observation,
    );
    store
        .append_admitted(
            &Verifier,
            second.clone(),
            intent(&store, "intent:retention:2", &second),
        )
        .unwrap_or_else(|error| panic!("second: {error}"));

    for suffix in ["a", "b"] {
        store
            .append_admitted(
                &Verifier,
                second.clone(),
                intent(
                    &store,
                    &format!("intent:retention:unchanged:{suffix}"),
                    &second,
                ),
            )
            .unwrap_or_else(|error| panic!("fill journal: {error}"));
    }
    let overflow = intent(&store, "intent:retention:overflow", &second);
    assert_eq!(
        store.append_admitted(&Verifier, second.clone(), overflow),
        Err(CognitiveStoreV2Error::IntentJournalCapacityExceeded)
    );

    let frontier = store.snapshot_key().vector.memory_ledger_frontier;
    assert_eq!(frontier, 3);
    assert_eq!(
        store
            .retain_intents_at_or_after(frontier)
            .unwrap_or_else(|error| panic!("retain: {error}")),
        1
    );
    assert_eq!(store.intent_retention_floor(), frontier);
    assert_eq!(
        store.retain_intents_at_or_after(frontier - 1),
        Err(CognitiveStoreV2Error::IntentRetentionFrontierRegression)
    );
    store
        .append_admitted(
            &Verifier,
            second.clone(),
            intent(&store, "intent:retention:after-prune", &second),
        )
        .unwrap_or_else(|error| panic!("journal slot was not reclaimed: {error}"));

    let image = store
        .export_image()
        .unwrap_or_else(|error| panic!("export: {error}"));
    let reopened = AdmittedCognitiveStoreV2::reopen(image, 2)
        .unwrap_or_else(|error| panic!("reopen: {error}"));
    assert_eq!(reopened.intent_retention_floor(), frontier);
}

#[test]
fn image_validation_rejects_semantically_forged_journal_and_sequence() {
    let mut store = store();
    let first = candidate(
        "memory:image",
        "content:v1",
        MemoryAdmissionKind::Observation,
    );
    store
        .append_admitted(
            &Verifier,
            first.clone(),
            intent(&store, "intent:image", &first),
        )
        .unwrap_or_else(|error| panic!("append: {error}"));
    let image = store
        .export_image()
        .unwrap_or_else(|error| panic!("export: {error}"));

    let mut mismatched_intent = image.clone();
    mismatched_intent.journal[0].receipt.intent_id = id("intent:image:forged");
    mismatched_intent.image_digest = mismatched_intent.compute_image_digest();
    assert!(matches!(
        mismatched_intent.validate(),
        Err(CognitiveStoreV2Error::JournalReceiptMismatch(_))
    ));

    let mut rejected_receipt = image.clone();
    rejected_receipt.journal[0].receipt.disposition = MemoryWriteDisposition::Rejected;
    rejected_receipt.image_digest = rejected_receipt.compute_image_digest();
    assert_eq!(
        rejected_receipt.validate(),
        Err(CognitiveStoreV2Error::InvalidJournalDisposition)
    );

    let mut wrong_sequence = image;
    wrong_sequence.sequence =
        LogicalSequence::new(99).unwrap_or_else(|error| panic!("sequence: {error}"));
    wrong_sequence.image_digest = wrong_sequence.compute_image_digest();
    assert_eq!(
        wrong_sequence.validate(),
        Err(CognitiveStoreV2Error::ImageSequenceMismatch)
    );
}
