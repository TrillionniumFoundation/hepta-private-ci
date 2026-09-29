use super::*;

fn context() -> QualificationContext {
    QualificationContext {
        candidate_source_digest: Digest32::of_bytes(b"candidate-source"),
        merge_base_digest: Digest32::of_bytes(b"merge-base"),
        cargo_lock_digest: Digest32::of_bytes(b"cargo-lock"),
        target_triple: StableId::new("x86_64-unknown-linux-gnu").expect("target triple"),
    }
}

#[test]
fn runner_executes_the_complete_negative_matrix_without_authority() {
    let receipt = qualify(context()).expect("complete matrix qualifies");
    assert_eq!(
        receipt
            .cases
            .iter()
            .map(|case| (case.case, case.observed))
            .collect::<Vec<_>>(),
        vec![
            (NegativeCase::Expired, ObservedRejection::Expired),
            (NegativeCase::Revoked, ObservedRejection::Revoked),
            (NegativeCase::Replay, ObservedRejection::Replay),
            (
                NegativeCase::PayloadDrift,
                ObservedRejection::PayloadMismatch,
            ),
        ]
    );
    assert!(!receipt.authority.grants_any());
    assert!(!receipt.qualification_digest.is_zero());
}

#[test]
fn qualification_is_deterministic_and_source_bound() {
    let first = qualify(context()).expect("first qualification");
    let second = qualify(context()).expect("second qualification");
    assert_eq!(first, second);

    let mut changed = context();
    changed.candidate_source_digest = Digest32::of_bytes(b"other-candidate");
    assert_ne!(
        first.qualification_digest,
        qualify(changed)
            .expect("changed candidate qualification")
            .qualification_digest
    );
}

#[test]
fn empty_provenance_is_rejected_before_cases_run() {
    let mut invalid = context();
    invalid.cargo_lock_digest = Digest32::from_array([0; 32]);
    assert_eq!(qualify(invalid), Err(Error::InvalidContext));
}
