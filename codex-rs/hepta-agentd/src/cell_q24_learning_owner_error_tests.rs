use super::*;

#[test]
fn original_model_pending_survives_factory_io_and_owner_wrappers() {
    for original in [
        CellQ24ModelProposalErrorV1::Pending,
        CellQ24ModelProposalErrorV1::CommitUncertain,
    ] {
        let factory = crate::AgentdError::Io(std::io::Error::other(original));
        assert!(matches!(owner_error(factory), Error::CommitUncertain));
    }
    let training =
        crate::OriginalCellQ24TrainingReceiptErrorV1::Owner(LearningOriginalOwnerErrorV1::Pending);
    assert!(matches!(owner_error(training), Error::CommitUncertain));
    assert!(matches!(
        owner_error(LearningOriginalOwnerErrorV1::CommitUncertain),
        Error::CommitUncertain
    ));
}

#[test]
fn missing_and_error_text_do_not_forge_a_durable_pending_state() {
    assert!(matches!(
        owner_error(ProductEvaluationExecutionStoreErrorV1::Missing),
        Error::OwnerUnavailable(_)
    ));
    assert!(matches!(
        owner_error(std::io::Error::other("Pending CommitUncertain")),
        Error::OwnerUnavailable(_)
    ));
    assert!(matches!(
        owner_error(CellQ24ModelProposalErrorV1::Binding("wrong original scope")),
        Error::OwnerUnavailable(_)
    ));
}
