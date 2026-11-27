//! Synthetic coordinator vectors test only the scope transition, not original
//! owner custody, independent evaluation or ordinary successor consumption.

use super::*;
use pretty_assertions::assert_eq;

#[test]
fn root_publication_preserves_completed_protocol_results_and_refuses_missing_decision()
-> anyhow::Result<()> {
    let original = no_update(learning_test_baseline()?)?;
    let no_update = Decision::new(original.snapshot().clone())?;
    no_update.require_root_publication()?;
    assert!(!no_update.adopts());
    let retained = qualified(
        &original,
        Some(LearningLocalDispositionV2::RetainParent),
        "policy",
    )?;
    let retained = Decision::new(retained.snapshot().clone())?;
    retained.require_root_publication()?;
    assert!(!retained.adopts());
    assert_eq!(retained.bundle, original.snapshot().request.selected_bundle);
    let deferred = qualified(
        &original,
        Some(LearningLocalDispositionV2::DeferCandidate),
        "policy",
    )?;
    let deferred = Decision::new(deferred.snapshot().clone())?;
    deferred.require_root_publication()?;
    assert!(!deferred.adopts());
    assert_eq!(deferred.bundle, original.snapshot().request.selected_bundle);
    assert!(
        matches!(deferred.snapshot.receipts.last().map(|receipt| &receipt.observation),
        Some(LearningIterationObservationV1::LocalDecisionV2(local))
            if local.disposition == LearningLocalDispositionV2::DeferCandidate)
    );
    let incomplete = qualified(&original, /*disposition*/ None, "policy")?;
    assert!(Decision::new(incomplete.snapshot().clone()).is_err());
    let adopted = qualified(
        &original,
        Some(LearningLocalDispositionV2::AdoptCandidate),
        "policy",
    )?;
    let adopted = Decision::new(adopted.snapshot().clone())?;
    adopted.require_root_publication()?;
    assert!(adopted.adopts());
    assert_ne!(adopted.operation, retained.operation);
    Ok(())
}
