use super::*;

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier must be valid");
    };
    value
}

fn execution() -> ExecutionProvenance {
    ExecutionProvenance {
        source_sha: "0123456789abcdef0123456789abcdef01234567".to_string(),
        source_tree: "89abcdef0123456789abcdef0123456789abcdef".to_string(),
        executable_digest: Digest32::of_bytes(b"authbus-test-binary"),
        command_digest: Digest32::of_bytes(b"cargo test -p codex-hepta-authbus"),
        runner_id: id("runner:native-ci"),
        started_at_ms: 1_000,
        completed_at_ms: 2_000,
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
        execution: execution(),
    })
    .collect()
}

#[test]
fn complete_negative_matrix_qualifies_without_authority() {
    let Ok(receipt) = qualify(cases()) else {
        panic!("complete matrix must qualify");
    };
    assert_eq!(receipt.case_count, 4);
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
fn qualification_rejects_mixed_execution_provenance() {
    let mut value = cases();
    value[0].execution.executable_digest = Digest32::of_bytes(b"different-binary");
    assert_eq!(qualify(value), Err(Error::MixedExecutionProvenance));
}

#[test]
fn qualification_rejects_failed_or_unbound_execution() {
    let mut failed = cases();
    for case in &mut failed {
        case.execution.exit_code = 1;
    }
    assert_eq!(qualify(failed), Err(Error::ExecutionFailed(1)));

    let mut invalid = cases();
    for case in &mut invalid {
        case.execution.source_sha = "not-a-git-sha".to_string();
    }
    assert_eq!(qualify(invalid), Err(Error::InvalidExecutionProvenance));
}


#[test]
fn native_negative_matrix_executes_before_qualification() {
    let receipt = execute_native_negative_qualification(execution())
        .expect("native negative matrix must execute and qualify");
    assert_eq!(receipt.case_count, 4);
    assert_eq!(receipt.source_sha, execution().source_sha);
    assert!(!receipt.authority.grants_any());
}
