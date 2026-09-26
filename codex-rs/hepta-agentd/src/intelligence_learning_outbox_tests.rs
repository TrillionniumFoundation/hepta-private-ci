use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn intent(payload: &[u8]) -> IntelligenceLearningIntentV1 {
    IntelligenceLearningIntentV1 {
        intent_id: id("learning-intent:run-1:decision"),
        run_id: id("run-1"),
        kind: IntelligenceLearningIntentKindV1::Decision,
        expected_predecessor: digest("ledger-head"),
        run_snapshot_digest: digest("run-snapshot"),
        decision_digest: digest("decision"),
        selected_candidate_id: id("candidate-1"),
        payload_digest: Digest32::of_bytes(payload),
        payload: payload.to_vec(),
    }
}

#[test]
fn prepared_intent_survives_reopen_and_exact_retry_is_idempotent() {
    let temp = tempfile::tempdir().expect("tempdir");
    let path = temp.path().join("intelligence-learning.outbox");
    let first = intent(b"decision-payload");
    {
        let mut outbox = IntelligenceLearningOutboxV1::open(path.clone()).expect("open");
        let prepared = outbox.prepare(first.clone()).expect("prepare");
        assert_eq!(prepared.revision, 1);
        assert_eq!(prepared.state, IntelligenceLearningOutboxStateV1::Prepared);
        assert_eq!(outbox.backlog(), 1);
        assert_eq!(outbox.prepare(first.clone()).expect("idempotent"), prepared);
    }

    let mut reopened = IntelligenceLearningOutboxV1::open(path.clone()).expect("reopen");
    assert_eq!(reopened.backlog(), 1);
    assert_eq!(reopened.reconcileable().len(), 1);
    let prepared = reopened
        .record(&first.intent_id)
        .expect("replayed prepared row");
    let acknowledged = reopened
        .transition(
            &first.intent_id,
            prepared.revision,
            IntelligenceLearningOutboxStateV1::Acknowledged,
            digest("append-receipt"),
        )
        .expect("acknowledge");
    assert_eq!(acknowledged.revision, 2);
    assert_eq!(reopened.backlog(), 0);
    drop(reopened);

    let final_view = IntelligenceLearningOutboxV1::open(path).expect("terminal reopen");
    assert_eq!(final_view.backlog(), 0);
    assert_eq!(
        final_view
            .record(&first.intent_id)
            .expect("terminal row")
            .state,
        IntelligenceLearningOutboxStateV1::Acknowledged
    );
}

#[test]
fn semantic_drift_for_same_intent_is_rejected() {
    let temp = tempfile::tempdir().expect("tempdir");
    let path = temp.path().join("intelligence-learning.outbox");
    let mut outbox = IntelligenceLearningOutboxV1::open(path).expect("open");
    let original = intent(b"decision-payload");
    outbox.prepare(original.clone()).expect("prepare");
    let drifted = intent(b"different-payload");
    assert!(matches!(
        outbox.prepare(drifted),
        Err(IntelligenceLearningOutboxError::Conflict)
    ));
}

#[test]
fn indeterminate_append_reconciles_only_to_an_explicit_terminal_state() {
    let temp = tempfile::tempdir().expect("tempdir");
    let path = temp.path().join("intelligence-learning.outbox");
    let mut outbox = IntelligenceLearningOutboxV1::open(path).expect("open");
    let value = intent(b"decision-payload");
    let prepared = outbox.prepare(value.clone()).expect("prepare");
    let unknown = outbox
        .transition(
            &value.intent_id,
            prepared.revision,
            IntelligenceLearningOutboxStateV1::Indeterminate,
            digest("ambiguous-write"),
        )
        .expect("indeterminate");
    assert_eq!(outbox.backlog(), 1);
    let acknowledged = outbox
        .transition(
            &value.intent_id,
            unknown.revision,
            IntelligenceLearningOutboxStateV1::Acknowledged,
            digest("reconciled-receipt"),
        )
        .expect("reconciled");
    assert_eq!(
        acknowledged.state,
        IntelligenceLearningOutboxStateV1::Acknowledged
    );
    assert!(matches!(
        outbox.transition(
            &value.intent_id,
            acknowledged.revision,
            IntelligenceLearningOutboxStateV1::Rejected,
            digest("late-rejection"),
        ),
        Err(IntelligenceLearningOutboxError::InvalidTransition)
    ));
}
