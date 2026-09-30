//! Stable, versioned failure identity for durable product-evaluation attempts.
//!
//! The V1 implementation hashed Rust `Debug` text. That text is diagnostic and
//! intentionally not a compatibility contract, so refactors could change a
//! durable terminal digest without changing the failure semantics. V2 encodes a
//! bounded class/detail pair. Historical V1 journal entries remain readable as
//! opaque terminal digests; recovery never reinterprets or rewrites them.

use codex_hepta_types::Digest32;

use crate::ProductEvaluationError;
use crate::ProductEvidenceSinkErrorV1;
use crate::ProductProviderErrorV1;

const DOMAIN_V2: &[u8] = b"hepta.learning-eval.product-evaluation-failure.v2";

#[repr(u16)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum FailureClassV2 {
    Binding = 1,
    Integrity = 2,
    FrozenPlan = 3,
    TemporalEvaluation = 4,
    FinalHoldout = 5,
    Provider = 6,
    SignedEvidence = 7,
    EvidenceSink = 8,
}

#[repr(u16)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum FailureDetailV2 {
    Unspecified = 0,
    BoundEstimand = 1,
    TemporalPlan = 2,
    ProductPlan = 3,
    QualificationContext = 4,
    CandidateIdentity = 5,
    BaselineIdentity = 6,
    Objective = 7,
    Dataset = 8,
    Timing = 9,
    Publication = 10,
    Rejected = 100,
    Unavailable = 101,
    Indeterminate = 102,
}

pub(super) fn product_evaluation_failure_digest_v2(error: &ProductEvaluationError) -> Digest32 {
    let (class, detail) = classify(error);
    let mut bytes = DOMAIN_V2.to_vec();
    bytes.extend_from_slice(&(class as u16).to_be_bytes());
    bytes.extend_from_slice(&(detail as u16).to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn classify(error: &ProductEvaluationError) -> (FailureClassV2, FailureDetailV2) {
    match error {
        ProductEvaluationError::Binding(context) => {
            (FailureClassV2::Binding, stable_context(context))
        }
        ProductEvaluationError::Integrity(context) => {
            (FailureClassV2::Integrity, stable_context(context))
        }
        ProductEvaluationError::Frozen(_) => {
            (FailureClassV2::FrozenPlan, FailureDetailV2::Unspecified)
        }
        ProductEvaluationError::Temporal(_) => {
            (FailureClassV2::TemporalEvaluation, FailureDetailV2::Unspecified)
        }
        ProductEvaluationError::Holdout(_) => {
            (FailureClassV2::FinalHoldout, FailureDetailV2::Unspecified)
        }
        ProductEvaluationError::Provider(error) => (
            FailureClassV2::Provider,
            match error {
                ProductProviderErrorV1::Rejected => FailureDetailV2::Rejected,
                ProductProviderErrorV1::Unavailable => FailureDetailV2::Unavailable,
                ProductProviderErrorV1::Indeterminate => FailureDetailV2::Indeterminate,
            },
        ),
        ProductEvaluationError::Signed(_) => {
            (FailureClassV2::SignedEvidence, FailureDetailV2::Unspecified)
        }
        ProductEvaluationError::Sink(error) => (
            FailureClassV2::EvidenceSink,
            match error {
                ProductEvidenceSinkErrorV1::Rejected => FailureDetailV2::Rejected,
                ProductEvidenceSinkErrorV1::Unavailable => FailureDetailV2::Unavailable,
                ProductEvidenceSinkErrorV1::Indeterminate => FailureDetailV2::Indeterminate,
            },
        ),
    }
}

fn stable_context(context: &str) -> FailureDetailV2 {
    match context {
        "bound estimand" => FailureDetailV2::BoundEstimand,
        "temporal plan" => FailureDetailV2::TemporalPlan,
        "product plan" | "frozen product plan" => FailureDetailV2::ProductPlan,
        "qualification context" => FailureDetailV2::QualificationContext,
        "candidate" | "candidate identity" => FailureDetailV2::CandidateIdentity,
        "baseline" | "baseline identity" => FailureDetailV2::BaselineIdentity,
        "objective" | "objective digest" => FailureDetailV2::Objective,
        "dataset" | "dataset digest" => FailureDetailV2::Dataset,
        "timing" | "timing evidence" => FailureDetailV2::Timing,
        "publication" | "publication result" => FailureDetailV2::Publication,
        _ => FailureDetailV2::Unspecified,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn v2_golden_vector_is_independent_of_debug_rendering() {
        let digest = product_evaluation_failure_digest_v2(&ProductEvaluationError::Binding(
            "temporal plan",
        ));
        assert_eq!(
            digest,
            Digest32::from_array([
                201, 103, 50, 170, 200, 10, 209, 212, 194, 244, 139, 18, 190, 238, 247,
                196, 101, 53, 178, 204, 99, 19, 157, 216, 49, 48, 122, 197, 161, 251,
                81, 166,
            ])
        );
    }

    #[test]
    fn provider_terminal_classes_are_distinct() {
        let rejected = product_evaluation_failure_digest_v2(&ProductEvaluationError::Provider(
            ProductProviderErrorV1::Rejected,
        ));
        let unavailable = product_evaluation_failure_digest_v2(&ProductEvaluationError::Provider(
            ProductProviderErrorV1::Unavailable,
        ));
        let indeterminate = product_evaluation_failure_digest_v2(
            &ProductEvaluationError::Provider(ProductProviderErrorV1::Indeterminate),
        );
        assert_ne!(rejected, unavailable);
        assert_ne!(unavailable, indeterminate);
        assert_ne!(rejected, indeterminate);
    }

    #[test]
    fn unknown_diagnostic_text_does_not_enter_the_preimage() {
        let left = product_evaluation_failure_digest_v2(&ProductEvaluationError::Binding(
            "unregistered diagnostic A",
        ));
        let right = product_evaluation_failure_digest_v2(&ProductEvaluationError::Binding(
            "unregistered diagnostic B",
        ));
        assert_eq!(left, right);
    }
}
