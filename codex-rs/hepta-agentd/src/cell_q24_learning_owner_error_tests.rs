use codex_hepta_intelligence_eval::ProductEvaluationError;

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

#[test]
fn evaluation_uncertainty_survives_original_receipt_and_factory_wrappers() {
    for original in [
        ProductEvaluationExecutionErrorV1::Pending,
        ProductEvaluationExecutionErrorV1::Store(
            ProductEvaluationExecutionStoreErrorV1::Indeterminate,
        ),
        ProductEvaluationExecutionErrorV1::Evaluation(ProductEvaluationError::Provider(
            ProductProviderErrorV1::Indeterminate,
        )),
        ProductEvaluationExecutionErrorV1::Evaluation(ProductEvaluationError::Sink(
            ProductEvidenceSinkErrorV1::Indeterminate,
        )),
        ProductEvaluationExecutionErrorV1::Evaluation(ProductEvaluationError::Holdout(
            FencedHoldoutError::Indeterminate,
        )),
        ProductEvaluationExecutionErrorV1::Evaluation(ProductEvaluationError::Holdout(
            FencedHoldoutError::Store(FinalHoldoutCasStoreError::Indeterminate),
        )),
    ] {
        let cell = crate::CellEvaluationErrorV1::Execution(original);
        let receipt = crate::OriginalCellEvaluationReceiptErrorV1::Cell(cell);
        let factory = crate::AgentdError::Io(std::io::Error::other(receipt));
        assert!(matches!(owner_error(factory), Error::CommitUncertain));
    }

    for cell in [
        crate::CellEvaluationErrorV1::Journal(CellGenerationErrorV2::Pending),
        crate::CellEvaluationErrorV1::Journal(CellGenerationErrorV2::CommitUncertain),
        crate::CellEvaluationErrorV1::Product(ProductEvaluationError::Sink(
            ProductEvidenceSinkErrorV1::Indeterminate,
        )),
    ] {
        let receipt = crate::OriginalCellEvaluationReceiptErrorV1::Cell(cell);
        assert!(matches!(owner_error(receipt), Error::CommitUncertain));
    }
}

#[test]
fn known_evaluation_failures_do_not_become_uncertain_through_wrappers() {
    for original in [
        ProductEvaluationExecutionErrorV1::MissingExecution,
        ProductEvaluationExecutionErrorV1::Store(ProductEvaluationExecutionStoreErrorV1::Missing),
        ProductEvaluationExecutionErrorV1::Store(ProductEvaluationExecutionStoreErrorV1::Rejected),
        ProductEvaluationExecutionErrorV1::Store(ProductEvaluationExecutionStoreErrorV1::Unavailable),
        ProductEvaluationExecutionErrorV1::Store(ProductEvaluationExecutionStoreErrorV1::Corrupt),
        ProductEvaluationExecutionErrorV1::Evaluation(ProductEvaluationError::Binding(
            "Pending Indeterminate",
        )),
        ProductEvaluationExecutionErrorV1::Evaluation(ProductEvaluationError::Provider(
            ProductProviderErrorV1::Unavailable,
        )),
        ProductEvaluationExecutionErrorV1::Evaluation(ProductEvaluationError::Sink(
            ProductEvidenceSinkErrorV1::Rejected,
        )),
        ProductEvaluationExecutionErrorV1::Evaluation(ProductEvaluationError::Holdout(
            FencedHoldoutError::Poisoned,
        )),
        ProductEvaluationExecutionErrorV1::Evaluation(ProductEvaluationError::Holdout(
            FencedHoldoutError::StaleFence,
        )),
        ProductEvaluationExecutionErrorV1::Evaluation(ProductEvaluationError::Holdout(
            FencedHoldoutError::Store(FinalHoldoutCasStoreError::Rejected),
        )),
    ] {
        let cell = crate::CellEvaluationErrorV1::Execution(original);
        let receipt = crate::OriginalCellEvaluationReceiptErrorV1::Cell(cell);
        let factory = crate::AgentdError::Io(std::io::Error::other(receipt));
        assert!(matches!(owner_error(factory), Error::OwnerUnavailable(_)));
    }
}
