//! Public Rust error ownership checks using receipts from the signed host fixture.

use std::error::Error as StdError;

use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::AgentdIntuitionDecisionReceiptV2;
use codex_hepta_agentd::AgentdIntuitionServiceErrorV1;

pub(super) fn assert_owned_receipt_contract(expected: AgentdIntuitionDecisionReceiptV2) {
    let changed = AgentdIntuitionServiceErrorV1::GenerationChangedAfterCommit {
        receipt: Box::new(expected.clone()),
    };
    let code = "agentd.intuition.service.generation_changed_after_commit";
    assert_eq!(changed.code(), code);
    let borrowed: Option<&AgentdIntuitionDecisionReceiptV2> = changed.acknowledged_policy_receipt();
    assert_eq!(borrowed, Some(&expected));
    assert!(changed.source().is_none());
    let changed = AgentdError::from(changed);
    assert_eq!(changed.to_string(), code);
    assert!(changed.source().is_none());
    let AgentdError::IntuitionPolicy(changed) = changed else {
        panic!("lost typed generation failure");
    };
    assert_eq!(changed.acknowledged_policy_receipt(), Some(&expected));
    let AgentdIntuitionServiceErrorV1::GenerationChangedAfterCommit { receipt } = *changed else {
        panic!("lost generation failure receipt");
    };
    let owned: AgentdIntuitionDecisionReceiptV2 = *receipt;
    assert_eq!(owned, expected);

    let source = Box::new(AgentdError::Io(std::io::Error::new(
        std::io::ErrorKind::BrokenPipe,
        "context attachment unavailable",
    )));
    let source_address = std::ptr::from_ref(source.as_ref());
    let failed = AgentdIntuitionServiceErrorV1::AdmissionFailedAfterPolicy {
        receipt: Box::new(expected.clone()),
        source,
    };
    let code = "agentd.intuition.service.admission_failed_after_policy";
    assert_eq!(failed.code(), code);
    assert_eq!(failed.acknowledged_policy_receipt(), Some(&expected));
    assert_eq!(
        failed
            .source()
            .and_then(|source| source.downcast_ref::<AgentdError>())
            .map(std::ptr::from_ref),
        Some(source_address)
    );
    let failed = AgentdError::from(failed);
    // The control wire uses this Display string, never the owned evidence.
    assert_eq!(failed.to_string(), code);
    assert_eq!(
        failed
            .source()
            .and_then(|source| source.downcast_ref::<AgentdError>())
            .map(std::ptr::from_ref),
        Some(source_address)
    );
    let AgentdError::IntuitionPolicy(failed) = failed else {
        panic!("lost typed admission failure");
    };
    assert_eq!(failed.acknowledged_policy_receipt(), Some(&expected));
    let AgentdIntuitionServiceErrorV1::AdmissionFailedAfterPolicy { receipt, source } = *failed
    else {
        panic!("lost acknowledged receipt or admission cause");
    };
    let owned: AgentdIntuitionDecisionReceiptV2 = *receipt;
    assert_eq!(owned, expected);
    let AgentdError::Io(source) = *source else {
        panic!("lost concrete admission I/O error");
    };
    assert_eq!(source.kind(), std::io::ErrorKind::BrokenPipe);
    assert_eq!(source.to_string(), "context attachment unavailable");
}
