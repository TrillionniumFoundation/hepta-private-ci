use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("test identifier must be valid")
}

fn provenance(index: usize) -> ExecutionProvenance {
    ExecutionProvenance {
        source_commit_sha1: "d7af096f28fa9989388939efa0e6600b52a43952".to_string(),
        source_tree_sha1: "789fa2ea88e8a6e787a0fb838a8dda3cf2e20701".to_string(),
        binary_digest: Digest32::of_bytes(b"authbus qualification binary"),
        command_digest: Digest32::of_bytes(format!("command:{index}").as_bytes()),
        runner_identity_digest: Digest32::of_bytes(b"native-ci-runner"),
        execution_receipt_digest: Digest32::of_bytes(
            format!("execution-receipt:{index}").as_bytes(),
        ),
        started_at_ms: 1_000 + index as u64,
        completed_at_ms: 2_000 + index as u64,
        exit_code: 0,
    }
}

fn cases() -> Vec<CaseEvidence> {
    [
        NegativeCase::Expired,
        NegativeCase::Revoked,
        NegativeCase::Replay,
        NegativeCase::PayloadDrift,
    ]
    .into_iter()
    .enumerate()
    .map(|(index, case)| CaseEvidence {
        case,
        case_id: id(&format!("case:{index}")),
        rejected: true,
        evidence_digest: Digest32::of_bytes(format!("evidence:{index}").as_bytes()),
        execution: provenance(index),
    })
    .collect()
}

#[test]
fn complete_negative_matrix_binds_one_exact_candidate_without_authority() {
    let receipt = qualify(cases()).expect("complete matrix must qualify");
    assert_eq!(receipt.case_count, 4);
    assert_eq!(
        receipt.source_commit_sha1,
        "d7af096f28fa9989388939efa0e6600b52a43952"
    );
    assert!(!receipt.authority.grants_any());
}

#[test]
fn missing_case_is_rejected() {
    let mut value = cases();
    value.pop();
    assert_eq!(qualify(value), Err(Error::MissingRequiredCase));
}

#[test]
fn unexpected_success_fails_qualification() {
    let mut value = cases();
    value[0].rejected = false;
    assert_eq!(
        qualify(value),
        Err(Error::CaseDidNotReject("case:0".to_string()))
    );
}

#[test]
fn mixed_source_candidate_is_rejected() {
    let mut value = cases();
    value[3].execution.source_commit_sha1 =
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".to_string();
    assert_eq!(
        qualify(value),
        Err(Error::CandidateMismatch("case:3".to_string()))
    );
}

#[test]
fn failed_or_unbound_execution_is_rejected() {
    let mut failed = cases();
    failed[1].execution.exit_code = 1;
    assert_eq!(
        qualify(failed),
        Err(Error::InvalidExecutionProvenance("case:1".to_string()))
    );

    let mut missing = cases();
    missing[2].execution.execution_receipt_digest = Digest32::ZERO;
    assert_eq!(
        qualify(missing),
        Err(Error::InvalidExecutionProvenance("case:2".to_string()))
    );
}
