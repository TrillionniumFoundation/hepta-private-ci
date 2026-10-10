use super::*;

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier must be valid");
    };
    value
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
