use codex_hepta_learning_ledger::AppendDisposition;
use codex_hepta_learning_ledger::DurableLedgerError;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LedgerError;
use codex_hepta_learning_ledger::decision_signing_payload_v2;
use codex_hepta_types::FixedQ32;
use pretty_assertions::assert_eq;

use super::tests as support;
use super::*;

type CreditMutation = fn(&mut CreditAllocationBatchV1);

#[test]
fn invalid_credit_does_not_commit_an_otherwise_valid_terminal_outcome() {
    let fixture = support::Fixture::new();
    let mut writer = fixture.writer();
    let decision = support::append_decision(&mut writer);
    let request = support::closure_request(
        &writer,
        decision.chain_digest,
        support::outcome(
            "outcome-record",
            "outcome",
            /*predecessor*/ None,
            /*value*/ 100,
        ),
        support::credit("outcome", /*value*/ 100),
    );
    let before = writer.snapshot().expect("snapshot");
    let witness = writer.witness_frontier().expect("witness");
    let cases: [(CreditMutation, CausalV2Error); 4] = [
        (
            |batch| batch.conservation_residual = FixedQ32::from_raw(1),
            CausalV2Error::CreditConservation,
        ),
        (
            |batch| batch.allocations.clear(),
            CausalV2Error::CreditLimit,
        ),
        (
            |batch| batch.allocations.push(batch.allocations[0].clone()),
            CausalV2Error::DuplicateCreditTarget("artifact-a".to_owned()),
        ),
        (
            |batch| batch.allocator.expires_at = 49,
            CausalV2Error::AuthenticationWindow,
        ),
    ];
    for (change, expected) in cases {
        let mut invalid = request.clone();
        change(&mut invalid.credit);
        match append_outcome_credit_v2(&mut writer, invalid, /*now*/ 50) {
            Err(OutcomeCreditClosureErrorV2::InvalidCredit(actual)) => {
                assert_eq!(actual, expected);
            }
            other => panic!("expected preflight credit rejection, got {other:?}"),
        }
        assert_eq!(writer.snapshot().expect("unchanged snapshot"), before);
        assert_eq!(
            writer.witness_frontier().expect("unchanged witness"),
            witness
        );
    }

    let closed = append_outcome_credit_v2(&mut writer, request, /*now*/ 50)
        .expect("valid original request after preflight failures");
    assert_eq!(closed.outcome.disposition, AppendDisposition::Appended);
    assert_eq!(closed.credit.disposition, AppendDisposition::Appended);
    assert!(!closed.authority.grants_any());
}

#[test]
fn partial_credit_recovery_and_replay_allow_unrelated_intervening_facts() {
    let fixture = support::Fixture::new();
    let mut writer = fixture.writer();
    let decision = support::append_decision(&mut writer);
    let request = support::closure_request(
        &writer,
        decision.chain_digest,
        support::outcome(
            "outcome-record",
            "outcome",
            /*predecessor*/ None,
            /*value*/ 100,
        ),
        support::credit("outcome", /*value*/ 100),
    );
    let mut invalid = request.clone();
    invalid.credit_evidence.signature[0] ^= 1;
    let partial = match append_outcome_credit_v2(&mut writer, invalid, /*now*/ 50) {
        Err(OutcomeCreditClosureErrorV2::Credit { outcome, .. }) => outcome,
        other => panic!("expected partial commit, got {other:?}"),
    };
    let mut closure = None;
    for index in 0..2 {
        let mut unrelated = support::decision();
        unrelated.record_id = support::id(&format!("unrelated-run-{index}"));
        unrelated.episode_id = support::id(&format!("unrelated-episode-{index}"));
        let payload = decision_signing_payload_v2(&unrelated).expect("decision payload");
        let evidence = support::sign(
            writer.verifier(),
            "generator",
            LearningEvidenceRoleV1::Generator,
            &payload,
        );
        let predecessor = writer
            .witness_frontier()
            .expect("witness")
            .anchor
            .chain_digest;
        writer
            .append_decision(predecessor, unrelated, &evidence, /*now*/ 50)
            .expect("unrelated authenticated decision");
        let result = append_outcome_credit_v2(&mut writer, request.clone(), /*now*/ 50)
            .expect("reconcile original credit after unrelated progress");
        assert_eq!(
            result.outcome.disposition,
            AppendDisposition::IdempotentReplay
        );
        assert_eq!(result.outcome.chain_digest, partial.chain_digest);
        if let Some(expected) = closure {
            assert_eq!(result.closure_digest, expected);
            assert_eq!(
                result.credit.disposition,
                AppendDisposition::IdempotentReplay
            );
        } else {
            assert_eq!(result.credit.disposition, AppendDisposition::Appended);
            closure = Some(result.closure_digest);
        }
    }
    assert_eq!(writer.records().expect("records").len(), 5);
}

#[test]
fn partial_credit_recovery_cannot_use_an_outcome_that_has_been_corrected() {
    let fixture = support::Fixture::new();
    let mut writer = fixture.writer();
    let decision = support::append_decision(&mut writer);
    let request = support::closure_request(
        &writer,
        decision.chain_digest,
        support::outcome(
            "outcome-record",
            "outcome",
            /*predecessor*/ None,
            /*value*/ 100,
        ),
        support::credit("outcome", /*value*/ 100),
    );
    let mut invalid = request.clone();
    invalid.credit_evidence.signature[0] ^= 1;
    let partial = match append_outcome_credit_v2(&mut writer, invalid, /*now*/ 50) {
        Err(OutcomeCreditClosureErrorV2::Credit { outcome, .. }) => outcome,
        other => panic!("expected partial commit, got {other:?}"),
    };
    let corrected = support::observed_request(
        &writer,
        partial.chain_digest,
        support::outcome(
            "correction-record",
            "corrected-outcome",
            Some("outcome"),
            /*value*/ 80,
        ),
    );
    append_observed_outcome_v2(&mut writer, corrected, /*now*/ 50).expect("correction");
    let before = writer.snapshot().expect("snapshot");
    let witness = writer.witness_frontier().expect("witness");
    assert!(matches!(
        append_outcome_credit_v2(&mut writer, request, /*now*/ 50),
        Err(OutcomeCreditClosureErrorV2::Credit {
            error: ProductionLedgerError::Durable(DurableLedgerError::Semantic(
                LedgerError::OutcomeRevoked(outcome)
            )),
            ..
        }) if outcome == "outcome"
    ));
    assert_eq!(writer.snapshot().expect("unchanged snapshot"), before);
    assert_eq!(
        writer.witness_frontier().expect("unchanged witness"),
        witness
    );
}
