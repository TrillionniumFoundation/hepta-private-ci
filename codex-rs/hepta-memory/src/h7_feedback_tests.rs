use super::h7_feedback::H7_FEEDBACK_DEFAULT_WEIGHT_CAP_SCALED;
use super::h7_feedback::H7_FEEDBACK_EXTERNAL_EFFECTS;
use super::h7_feedback::H7_FEEDBACK_KG_WRITE_AUTHORITY;
use super::h7_feedback::H7_FEEDBACK_PRODUCTION_CALLER;
use super::h7_feedback::H7_FEEDBACK_REPLAY_ONLY;
use super::h7_feedback::H7AttemptLeaseScope;
use super::h7_feedback::H7CreditLedger;
use super::h7_feedback::H7FeedbackAppend;
use super::h7_feedback::H7FeedbackBinding;
use super::h7_feedback::H7FeedbackError;
use super::h7_feedback::H7FeedbackKey;
use super::h7_feedback::H7FeedbackOracle;
use super::h7_feedback::H7FeedbackRecord;
use super::h7_feedback::H7PolicyAction;
use super::h7_feedback::H7Propensity;
use super::h7_feedback::H7Support;
use codex_hepta_contracts::Sha256Digest;

fn digest(label: &str) -> Sha256Digest {
    Sha256Digest::for_bytes(label.as_bytes())
}

fn scope(attempt_id: &str) -> H7AttemptLeaseScope {
    H7AttemptLeaseScope::new(attempt_id, "lease-1", 7, 3, digest("fence-1")).unwrap()
}

fn action(attempt_id: &str) -> H7PolicyAction {
    let binding = H7FeedbackBinding::new(
        "trajectory-1",
        "turn-1",
        scope(attempt_id),
        digest("state-1"),
        digest("policy-1"),
        digest("receipt-1"),
    )
    .unwrap();
    H7PolicyAction::new("action-1", binding).unwrap()
}

fn record(
    seq: u32,
    event_id: &str,
    parent_seq: u32,
    parent_digest: Sha256Digest,
    attempt_id: &str,
    reward_bps: i32,
    credit_units: i64,
    behavior_scaled: u64,
    target_scaled: u64,
    in_support: bool,
) -> H7FeedbackRecord {
    H7FeedbackRecord::new(
        seq,
        event_id,
        parent_seq,
        parent_digest,
        action(attempt_id),
        H7Propensity::new(behavior_scaled, target_scaled).unwrap(),
        H7Support::new(in_support, digest("support-1")).unwrap(),
        reward_bps,
        credit_units,
        true,
        false,
    )
    .unwrap()
}

#[test]
fn append_and_fixed_point_evaluation_are_deterministic() {
    let mut oracle = H7FeedbackOracle::new("trajectory-1").unwrap();
    let first = record(
        2,
        "feedback-1",
        1,
        digest("turn-start"),
        "attempt-1",
        1_000,
        20,
        500_000,
        1_000_000,
        true,
    );
    let second = record(
        3,
        "feedback-2",
        2,
        first.feedback_digest.clone(),
        "attempt-1",
        -500,
        -7,
        1_000_000,
        500_000,
        true,
    );
    oracle.append(first).unwrap();
    oracle.append(second).unwrap();

    assert_eq!(oracle.ledger().total_credit_units, 13);
    assert!(oracle.ledger().validate().is_ok());
    let evaluation = oracle
        .evaluate(H7_FEEDBACK_DEFAULT_WEIGHT_CAP_SCALED)
        .unwrap();
    // weights are 2.0 and 0.5 in 1e6 fixed point: (2*1000 - .5*500)/2.5 = 700.
    assert_eq!(evaluation.total_weight_scaled, 2_500_000);
    assert_eq!(evaluation.weighted_reward_sum, 1_750_000_000);
    assert_eq!(evaluation.estimate_reward_bps, 700);
    assert_eq!(evaluation.direct_reward_bps, 250);
    assert_eq!(evaluation.coverage_bps, 10_000);
    assert_eq!(
        evaluation,
        oracle
            .evaluate(H7_FEEDBACK_DEFAULT_WEIGHT_CAP_SCALED)
            .unwrap()
    );
    assert!(!evaluation.production_effects);
    assert!(!evaluation.kg_write_authority);
    assert!(!evaluation.production_caller);
    assert!(evaluation.replay_only);
}

#[test]
fn duplicate_is_replay_and_different_content_is_conflict() {
    let mut oracle = H7FeedbackOracle::new("trajectory-1").unwrap();
    let first = record(
        2,
        "feedback-1",
        1,
        digest("turn-start"),
        "attempt-1",
        100,
        4,
        1_000_000,
        1_000_000,
        true,
    );
    let replay_digest = first.feedback_digest.clone();
    assert!(matches!(
        oracle.append(first.clone()).unwrap(),
        H7FeedbackAppend::Inserted { .. }
    ));
    let replay = oracle.append(first).unwrap();
    assert!(matches!(replay, H7FeedbackAppend::Replay { .. }));
    assert_eq!(
        replay_digest,
        match replay {
            H7FeedbackAppend::Replay {
                feedback_digest, ..
            } => feedback_digest,
            H7FeedbackAppend::Inserted { .. } => unreachable!(),
        }
    );

    let conflicting = record(
        2,
        "feedback-1",
        1,
        digest("turn-start"),
        "attempt-1",
        101,
        4,
        1_000_000,
        1_000_000,
        true,
    );
    assert!(matches!(
        oracle.append(conflicting),
        Err(H7FeedbackError::Conflict(_))
    ));
    assert_eq!(oracle.records().len(), 1);
}

#[test]
fn attempt_scope_and_causal_parent_digest_are_fenced() {
    let mut oracle = H7FeedbackOracle::new("trajectory-1").unwrap();
    let first = record(
        2,
        "feedback-1",
        1,
        digest("turn-start"),
        "attempt-1",
        100,
        1,
        1_000_000,
        1_000_000,
        true,
    );
    oracle.append(first.clone()).unwrap();

    let bad_parent = record(
        3,
        "feedback-2",
        2,
        digest("wrong-parent"),
        "attempt-1",
        100,
        1,
        1_000_000,
        1_000_000,
        true,
    );
    assert!(matches!(
        oracle.append(bad_parent),
        Err(H7FeedbackError::BindingMismatch("causal parent digest"))
    ));
    assert_eq!(oracle.records().len(), 1);

    let stale_attempt = record(
        3,
        "feedback-2",
        2,
        first.feedback_digest,
        "attempt-2",
        100,
        1,
        1_000_000,
        1_000_000,
        true,
    );
    assert!(matches!(
        oracle.append(stale_attempt),
        Err(H7FeedbackError::BindingMismatch("attempt/lease scope"))
    ));
    assert_eq!(oracle.records().len(), 1);
}

#[test]
fn unsupported_and_zero_behavior_fail_closed() {
    assert!(matches!(
        H7Propensity::new(0, 1),
        Err(H7FeedbackError::Invalid(_))
    ));
    let mut oracle = H7FeedbackOracle::new("trajectory-1").unwrap();
    oracle
        .append(record(
            2,
            "feedback-1",
            1,
            digest("turn-start"),
            "attempt-1",
            100,
            1,
            1_000_000,
            1_000_000,
            false,
        ))
        .unwrap();
    assert!(matches!(
        oracle.evaluate(H7_FEEDBACK_DEFAULT_WEIGHT_CAP_SCALED),
        Err(H7FeedbackError::OutOfSupport)
    ));
}

#[test]
fn authority_flags_and_digest_tampering_are_rejected() {
    let action = action("attempt-1");
    let mut effectful = action;
    effectful.external_effect_executed = true;
    assert_eq!(effectful.validate(), Err(H7FeedbackError::ExternalEffect));

    let record = record(
        2,
        "feedback-1",
        1,
        digest("turn-start"),
        "attempt-1",
        100,
        1,
        1_000_000,
        1_000_000,
        true,
    );
    let mut tampered = record.clone();
    tampered.feedback_digest = digest("tampered");
    assert_eq!(
        tampered.validate(),
        Err(H7FeedbackError::DigestMismatch("feedback"))
    );

    let mut oracle = H7FeedbackOracle::new("trajectory-1").unwrap();
    oracle.append(record).unwrap();
    oracle.production_caller = true;
    assert_eq!(oracle.validate(), Err(H7FeedbackError::ProductionCaller));
    assert!(!H7_FEEDBACK_EXTERNAL_EFFECTS);
    assert!(!H7_FEEDBACK_KG_WRITE_AUTHORITY);
    assert!(!H7_FEEDBACK_PRODUCTION_CALLER);
    assert!(H7_FEEDBACK_REPLAY_ONLY);
}

#[test]
fn serde_round_trip_preserves_digests_and_credit_conservation() {
    let mut oracle = H7FeedbackOracle::new("trajectory-1").unwrap();
    oracle
        .append(record(
            2,
            "feedback-1",
            1,
            digest("turn-start"),
            "attempt-1",
            100,
            9,
            1_000_000,
            1_000_000,
            true,
        ))
        .unwrap();
    let encoded = serde_json::to_string(&oracle).unwrap();
    let decoded: H7FeedbackOracle = serde_json::from_str(&encoded).unwrap();
    assert_eq!(decoded, oracle);
    decoded.validate().unwrap();
    assert_eq!(decoded.ledger().total_credit_units, 9);
}

#[test]
fn ledger_and_oracle_cardinality_are_fail_closed_and_atomic() {
    let mut ledger = H7CreditLedger::new("trajectory-1").unwrap();
    let key = H7FeedbackKey {
        trajectory_id: "trajectory-1".to_string(),
        event_seq: 2,
        event_id: "feedback-1".to_string(),
    };
    ledger.append(key.clone(), 3).unwrap();
    ledger.total_credit_units = 99;
    let before_entries = ledger.entries.clone();
    assert_eq!(
        ledger.append(key, 3),
        Err(H7FeedbackError::BindingMismatch("credit conservation"))
    );
    assert_eq!(ledger.entries, before_entries);
    assert_eq!(ledger.total_credit_units, 99);

    let mut oracle = H7FeedbackOracle::new("trajectory-1").unwrap();
    let first = record(
        2,
        "feedback-1",
        1,
        digest("turn-start"),
        "attempt-1",
        100,
        1,
        1_000_000,
        1_000_000,
        true,
    );
    oracle.append(first.clone()).unwrap();
    oracle
        .ledger
        .append(
            H7FeedbackKey {
                trajectory_id: "trajectory-1".to_string(),
                event_seq: 99,
                event_id: "orphan-credit".to_string(),
            },
            5,
        )
        .unwrap();
    let before = oracle.clone();
    let second = record(
        3,
        "feedback-2",
        2,
        first.feedback_digest,
        "attempt-1",
        100,
        1,
        1_000_000,
        1_000_000,
        true,
    );
    assert_eq!(
        oracle.append(second),
        Err(H7FeedbackError::BindingMismatch(
            "oracle ledger cardinality"
        ))
    );
    assert_eq!(oracle, before);
}

#[test]
fn feedback_sequence_gaps_fail_closed_and_leave_oracle_unchanged() {
    let mut oracle = H7FeedbackOracle::new("trajectory-1").unwrap();
    let first = record(
        2,
        "feedback-1",
        1,
        digest("turn-start"),
        "attempt-1",
        100,
        1,
        1_000_000,
        1_000_000,
        true,
    );
    oracle.append(first).unwrap();
    let before = oracle.clone();
    let gap = record(
        4,
        "feedback-3",
        3,
        digest("missing-feedback-2"),
        "attempt-1",
        100,
        1,
        1_000_000,
        1_000_000,
        true,
    );
    assert_eq!(
        oracle.append(gap),
        Err(H7FeedbackError::NonContiguousSequence {
            expected: 3,
            actual: 4,
        })
    );
    assert_eq!(oracle, before);
}

#[test]
fn feedback_causal_parent_must_be_immediate_predecessor() {
    let mut oracle = H7FeedbackOracle::new("trajectory-1").unwrap();
    let first = record(
        2,
        "feedback-1",
        1,
        digest("turn-start"),
        "attempt-1",
        100,
        1,
        1_000_000,
        1_000_000,
        true,
    );
    oracle.append(first).unwrap();
    let before = oracle.clone();

    // Sequence three is contiguous, but its parent claims the external
    // turn-start row rather than the immutable sequence-two record.  This
    // must not be accepted as a valid replay chain.
    let forged_parent = record(
        3,
        "feedback-2",
        1,
        digest("turn-start"),
        "attempt-1",
        100,
        1,
        1_000_000,
        1_000_000,
        true,
    );
    assert_eq!(
        oracle.append(forged_parent),
        Err(H7FeedbackError::BindingMismatch("causal parent sequence"))
    );
    assert_eq!(oracle, before);
    oracle.validate().unwrap();
}
