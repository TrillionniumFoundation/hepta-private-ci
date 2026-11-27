//! Explicit fixture signatures exercise exact original execution readback.
//! These cohorts, principals and CAS owners are mechanism tests, not a
//! deployed independent evaluation or evidence of learning efficacy.

use super::*;
use pretty_assertions::assert_eq;

use crate::OriginalProductEvaluationExecutionEvidenceV1;

fn original(
    test: &mut Harness,
    clock: &dyn Fn() -> Result<u64, ProductProviderErrorV1>,
) -> Result<
    (
        ProductTemporalEvaluationReceiptV1,
        OriginalProductEvaluationExecutionEvidenceV1,
    ),
    Error,
> {
    test.runner.readback_temporal_comparison_evidence(
        &ProductEvaluationExecutionRequestV1 {
            plan: &test.frozen,
            candidate_plan: &test.fixture.candidate_plan,
            baseline_plan: &test.fixture.baseline_plan,
            evaluator: &test.context.evaluator,
            verifier: &test.verifier,
            clock,
        },
        &mut test.executions,
    )
}

#[test]
fn original_execution_evidence_survives_recovery_without_work_or_renewal() {
    let mut test = Harness::new();
    let completed = test.run().expect("actual original execution");
    let before = (test.runner.holdout_anchor(), test.executions.state.clone());
    let first = original(&mut test, &|| Ok(50)).expect("actual original record");
    assert_eq!(first.0, completed);
    test.reopen();
    let recovered_anchor = test.runner.holdout_anchor();
    assert_eq!(
        original(&mut test, &|| Ok(60)).expect("same original signature window"),
        first
    );
    assert_eq!(test.executions.state, before.1);
    assert_eq!(test.runner.holdout_anchor(), recovered_anchor);
    assert_eq!(
        (test.fixture.provider.release_count, test.attestor.calls),
        (1, 1)
    );
    assert!(!first.1.authority().grants_any());
    assert_eq!(first.1.attestation().issued_at, 10);
    assert_eq!(first.1.attestation().expires_at, 90);
}

#[test]
fn original_execution_evidence_rechecks_expiry_after_owner_reads() {
    let mut test = Harness::new();
    test.run().expect("actual original execution");
    let before = (test.runner.holdout_anchor(), test.executions.state.clone());
    let calls = std::cell::Cell::new(0);
    let clock = || {
        let count = calls.get();
        calls.set(count + 1);
        Ok(if count == 0 { 50 } else { 91 })
    };
    assert!(matches!(
        original(&mut test, &clock),
        Err(Error::Evaluation(ProductEvaluationError::Signed(_)))
    ));
    assert_eq!(calls.get(), 2);
    assert_eq!(
        (test.runner.holdout_anchor(), test.executions.state.clone()),
        before
    );
    assert_eq!(
        (test.fixture.provider.release_count, test.attestor.calls),
        (1, 1)
    );
}

#[test]
fn equal_execution_with_validly_renewed_signature_has_different_original_evidence() {
    let mut test = Harness::new();
    test.run().expect("actual original execution");
    let first = original(&mut test, &|| Ok(50)).expect("original evidence");
    let (_, State::Completed(bytes)) = test
        .executions
        .state
        .as_mut()
        .expect("actual completed bytes")
    else {
        panic!("completed original");
    };
    let (mut signed, body) = execution_codec::decode_envelope(bytes).expect("original envelope");
    let body = body.to_vec();
    signed.issued_at = 51;
    signed.expires_at = 99;
    signed.signature = test.attestor.key.sign(&signed.signing_bytes()).to_bytes();
    *bytes = execution_codec::encode_envelope(&signed, &body).expect("explicit fixture renewal");
    let renewed = original(&mut test, &|| Ok(60)).expect("individually valid renewed evidence");
    assert_eq!(renewed.0, first.0);
    assert_ne!(renewed.1, first.1);
    assert_ne!(renewed.1.record_digest(), first.1.record_digest());
    assert!(first.1.revalidate(&test.verifier, /*now*/ 95).is_err());
    renewed
        .1
        .revalidate(&test.verifier, /*now*/ 95)
        .expect("new fixture window");
    assert_eq!(
        (test.fixture.provider.release_count, test.attestor.calls),
        (1, 1)
    );
}

#[test]
fn original_execution_evidence_missing_and_pending_never_claim() {
    for pending in [false, true] {
        let mut test = Harness::new();
        if pending {
            test.executions.lost = LostAck::Claim;
            assert_eq!(test.run(), Err(Error::Store(StoreError::Indeterminate)));
        }
        let before = (test.runner.holdout_anchor(), test.executions.state.clone());
        let expected = if pending {
            Error::Pending
        } else {
            Error::Store(StoreError::Missing)
        };
        assert_eq!(original(&mut test, &|| Ok(50)), Err(expected));
        assert_eq!(
            (test.runner.holdout_anchor(), test.executions.state),
            before
        );
        assert_eq!(
            (test.fixture.provider.release_count, test.attestor.calls),
            (0, 0)
        );
    }
}
