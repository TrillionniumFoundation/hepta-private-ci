use super::*;
use std::collections::BTreeSet;

#[test]
fn executable_negative_matrix_qualifies_without_authority() {
    let receipt = qualify().expect("real AuthBus negative matrix must qualify");
    assert_eq!(receipt.cases.len(), 4);
    assert_eq!(
        receipt
            .cases
            .iter()
            .map(|case| case.case)
            .collect::<Vec<_>>(),
        vec![
            NegativeCase::Expired,
            NegativeCase::Revoked,
            NegativeCase::Replay,
            NegativeCase::PayloadDrift,
        ]
    );
    assert!(!receipt.authority.grants_any());
    assert!(!receipt.positive_envelope_digest.is_zero());
    assert!(!receipt.qualification_digest.is_zero());
}

#[test]
fn executable_receipt_is_deterministic() {
    let first = qualify().expect("first qualification");
    let second = qualify().expect("second qualification");
    assert_eq!(first, second);
}

#[test]
fn case_evidence_binds_the_observed_typed_error() {
    let receipt = qualify().expect("qualification");
    assert_eq!(
        receipt
            .cases
            .iter()
            .map(|case| case.observed_error)
            .collect::<Vec<_>>(),
        vec!["expired", "revoked", "replay", "payload_mismatch"]
    );
    let unique = receipt
        .cases
        .iter()
        .map(|case| case.evidence_digest)
        .collect::<BTreeSet<_>>();
    assert_eq!(unique.len(), 4);
}
