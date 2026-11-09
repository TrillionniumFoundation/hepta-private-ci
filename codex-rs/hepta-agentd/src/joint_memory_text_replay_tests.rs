//! Pure mapping checks. These untrusted record fixtures do not construct a
//! LedgerWriter, Memory use, verified signature or admitted materialization.

use codex_hepta_learning_ledger::AuthenticatedDecisionRecordV2;
use codex_hepta_learning_ledger::AuthenticatedOutcomeRecordV2;
use codex_hepta_learning_ledger::AuthenticatedOutcomeTerminality;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::LogicalSequence;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("test identity")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn decision(episode: &str, support: Digest32) -> LedgerRecord {
    LedgerRecord {
        sequence: LogicalSequence::new(/*value*/ 1).expect("test sequence"),
        predecessor_chain_digest: digest("predecessor"),
        event_digest: digest(episode),
        chain_digest: digest("chain"),
        event: LedgerEvent::AuthenticatedDecisionV2(AuthenticatedDecisionRecordV2 {
            record_id: id("decision"),
            episode_id: id(episode),
            run_snapshot_digest: digest("actual-run-snapshot-field"),
            objective_digest: digest("objective"),
            policy_digest: digest("policy"),
            generator_id: id("generator"),
            generator_controller_id: id("controller"),
            generator_credential_chain_digest: digest("credential"),
            generator_signing_key_digest: digest("key"),
            generator_scope_digest: digest("scope"),
            generator_authority_epoch: 1,
            candidate_ids: vec![id("candidate")],
            selected_candidate_id: id("candidate"),
            selected_propensity: ProbabilityQ32::ONE,
            candidate_completeness_digest: digest("completeness"),
            support_digest: support,
            authentication_digest: digest("untrusted-unit-fixture-not-signature-proof"),
        }),
    }
}

fn outcome(episode: &str) -> LedgerRecord {
    LedgerRecord {
        sequence: LogicalSequence::new(/*value*/ 2).expect("test sequence"),
        predecessor_chain_digest: digest("chain"),
        event_digest: digest("outcome-event"),
        chain_digest: digest("outcome-chain"),
        event: LedgerEvent::AuthenticatedOutcomeV2(AuthenticatedOutcomeRecordV2 {
            record_id: id("outcome-record"),
            outcome_id: id("outcome"),
            episode_id: id(episode),
            observer_id: id("observer"),
            observer_controller_id: id("observer-controller"),
            observer_credential_chain_digest: digest("observer-credential"),
            observer_signing_key_digest: digest("observer-key"),
            observer_scope_digest: digest("observer-scope"),
            observer_authority_epoch: 1,
            observed_at: Some(12),
            value: Some(FixedQ32::ONE),
            unit_profile_digest: digest("outcome-units"),
            support_digest: digest("independent-observer-support"),
            latest_observable_at: 13,
            expected_delay_profile_digest: digest("outcome-delay"),
            terminality: AuthenticatedOutcomeTerminality::Terminal,
            censoring_reason: None,
            correction_predecessor: None,
            finalized_at: Some(14),
            authentication_digest: digest("untrusted-observer-fixture-not-signature-proof"),
        }),
    }
}

#[test]
fn utf8_mapping_preserves_full_source_and_exact_continuation() {
    let prefix = "真实 source\0\n";
    let continuation = "🙂\n".repeat(/*n*/ 64);
    let source = format!("{prefix}{continuation}");
    assert_eq!(
        split_text(&source, source.len()).expect("bounded text"),
        (prefix.to_owned(), continuation)
    );
    let short = "  原文🙂\n";
    assert_eq!(
        split_text(short, short.len()).expect("short source"),
        (String::new(), short.to_owned())
    );
}

#[test]
fn utf8_mapping_rejects_overflow_without_truncating_the_prefix() {
    let prefix = "文".repeat(/*n*/ 1365);
    let continuation = "🙂".repeat(/*n*/ 128);
    let source = format!("{prefix}{continuation}");
    assert_eq!(
        split_text(&source, MAX_TEXT_BYTES).expect("4095-byte prefix"),
        (prefix, continuation)
    );
    assert!(matches!(
        split_text(&"a".repeat(4097 + 128), MAX_TEXT_BYTES),
        Err(JointMemoryTextReplayErrorV1::Binding(
            "complete prefix bound"
        ))
    ));
    assert!(matches!(
        split_text(&source, source.len() - 1),
        Err(JointMemoryTextReplayErrorV1::Binding("complete text bound"))
    ));
    assert!(matches!(
        split_text("", MAX_TEXT_BYTES),
        Err(JointMemoryTextReplayErrorV1::Binding("complete text bound"))
    ));
}

#[test]
fn dataset_mapping_rejects_one_mixed_source_or_objective_among_valid_rows() {
    let support = digest("source-one");
    let first = decision("episode-one", support);
    let mut second = decision("episode-two", digest("source-two"));
    assert!(matches!(
        validate_records(&[&first, &second], digest("objective"), support),
        Err(JointMemoryTextReplayErrorV1::Binding(
            "decision source or objective"
        ))
    ));
    let LedgerEvent::AuthenticatedDecisionV2(value) = &mut second.event else {
        panic!("decision fixture");
    };
    value.support_digest = support;
    value.objective_digest = digest("another-objective");
    assert!(matches!(
        validate_records(&[&first, &second], digest("objective"), support),
        Err(JointMemoryTextReplayErrorV1::Binding(
            "decision source or objective"
        ))
    ));
}

#[test]
fn dataset_mapping_accepts_pending_and_independent_outcome_evidence() {
    let support = digest("source-one");
    let first = decision("episode-one", support);
    let mut observation = outcome("episode-one");
    validate_records(&[&first, &observation], digest("objective"), support)
        .expect("same episode with independent scalar evidence");
    let LedgerEvent::AuthenticatedOutcomeV2(value) = &mut observation.event else {
        panic!("outcome fixture");
    };
    value.value = None;
    value.observed_at = None;
    value.finalized_at = None;
    value.terminality = AuthenticatedOutcomeTerminality::Pending;
    validate_records(&[&first, &observation], digest("objective"), support)
        .expect("pending is retained rather than interpreted as zero reward");
}

#[test]
fn dataset_mapping_rejects_unlinked_observations_and_no_decision_source() {
    let support = digest("source-one");
    let first = decision("episode-one", support);
    let observation = outcome("unlinked-episode");
    assert!(matches!(
        validate_records(&[&first, &observation], digest("objective"), support),
        Err(JointMemoryTextReplayErrorV1::Binding(
            "unlinked dataset episode"
        ))
    ));
    assert!(matches!(
        validate_records(&[&observation], digest("objective"), support),
        Err(JointMemoryTextReplayErrorV1::Binding(
            "authenticated decisions required"
        ))
    ));
}
