//! The canonical evaluated read profile consumes actual opaque T/B results.
//! Fresh/cold publication origins remain distinct before explicit read-only
//! conversion. This private fixture neither exports fields nor grants work.

use pretty_assertions::assert_eq;

use super::*;
use crate::OriginalCircuitLearningReadContextV1;
use crate::OriginalCircuitRetainedPublicationErrorV1;

pub(crate) fn check_evaluated_profiles(
    fresh: OriginalCircuitEvaluatedRetentionContextV1,
    cold: OriginalCircuitEvaluatedRetentionContextV1,
    evaluation_expires_at: u64,
) -> anyhow::Result<()> {
    let at = now()?;
    // The original publication distinction is preserved before conversion.
    fresh.require_new_original_receipt(at)?;
    assert!(matches!(
        cold.require_new_original_receipt(at),
        Err(OriginalCircuitRetainedPublicationErrorV1::Binding(
            "recovered evaluated retention is read-only"
        ))
    ));
    let (scope, verifier, training_evidence) = fresh.receipt_configuration();
    let expired = training_evidence
        .expires_at
        .max(evaluation_expires_at)
        .saturating_add(1);
    let mut legacy = OriginalCircuitLearningReadContextV1 {
        prefix: fresh.snapshot().clone(),
        scope,
        verifier,
        training_evidence,
        selection_evidence: None,
    };
    let fresh = OriginalCircuitEvaluatedLearningReadContextV1::for_original_selection(fresh)?;
    let cold = OriginalCircuitEvaluatedLearningReadContextV1::for_original_selection(cold)?;
    for profile in [&fresh, &cold] {
        let OriginalCut::Selection(original) = &profile.original else {
            anyhow::bail!("Selection input became a NextUse capability");
        };
        assert!(matches!(
            original.require_new_original_receipt(at),
            Err(OriginalCircuitRetainedPublicationErrorV1::Binding(
                "recovered evaluated retention is read-only"
            ))
        ));
    }
    let fresh = ReadProfile::Evaluated(fresh);
    let cold = ReadProfile::Evaluated(cold);
    let binding = fresh.binding(at)?;
    // The public Selection read factory attenuates both origins to the same
    // read-only purpose; neither retains fresh publication or receipt authority.
    assert_eq!(binding, cold.binding(at)?);
    assert_eq!(fresh.mode()?, wire::Mode::Selection);
    assert_eq!(cold.mode()?, wire::Mode::Selection);
    assert_eq!(fresh.decision()?.snapshot(), fresh.prefix());
    assert_eq!(fresh.prefix(), cold.prefix());
    assert!(fresh.legacy().is_err());
    assert!(cold.legacy().is_err());

    let request = fresh.request(binding, /*request_id*/ 1)?;
    fresh.require_request(&request, binding, /*request_id*/ 1)?;
    cold.require_request(&request, binding, /*request_id*/ 1)?;
    let value = serde_json::to_value(&request)?;
    for (field, replacement) in [
        ("schema", serde_json::json!(2)),
        ("operation", serde_json::json!(wire::OPERATION)),
        ("request_id", serde_json::json!(2)),
        (
            "binding",
            serde_json::json!(Digest32::of_bytes(b"other-proof").to_string()),
        ),
        (
            "prefix_head",
            serde_json::json!(Digest32::of_bytes(b"other-cut").to_string()),
        ),
        ("operation_id", serde_json::json!("other-source-operation")),
        ("mode", serde_json::json!("next_use")),
    ] {
        let mut changed = value.clone();
        changed[field] = replacement;
        let changed: wire::Request = serde_json::from_value(changed)?;
        assert!(matches!(
            fresh.require_request(&changed, binding, /*request_id*/ 1),
            Err(Error::Binding("original fixed evaluated read request"))
        ));
    }
    let mut injected = value;
    injected["execute"] = serde_json::json!(true);
    assert!(serde_json::from_value::<wire::Request>(injected).is_err());

    // The public legacy DTO cannot relabel CandidateTraining/Evaluation as
    // TrainingNoUpdate, including a fabricated extra Selector hint.
    assert!(wire::context_binding(&legacy, at).is_err());
    legacy.selection_evidence = Some(legacy.training_evidence.clone());
    assert!(wire::context_binding(&legacy, at).is_err());
    assert!(fresh.binding(expired).is_err());
    assert!(cold.binding(expired).is_err());
    Ok(())
}
