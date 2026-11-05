//! The real PQ clock crosses the exact signed-decision boundary after durable
//! preparation. Longer-lived M15 metadata cannot extend that decision.

use crate::FleetRegistryError;
use crate::QualificationResult;
use crate::ReleaseIntentAnchorV1 as Anchor;
use crate::release_intent_anchor_tests::prepared;
use crate::release_intent_anchor_tests::setup;
use crate::release_intent_reconciliation_retry_tests::observations;
use crate::release_intent_reconciliation_retry_tests::retain_replacement;
use crate::release_intent_reconciliation_tests::ColdPending;
use crate::release_qualification_trust::NOW;

#[test]
fn ordinary_intent_requires_a_window_and_rechecks_it_after_actual_proposal_fsync()
-> QualificationResult<()> {
    let (f, _release, policy) = setup()?;
    let next = prepared(&f, policy, 41, 1);
    let before = (f.publisher.frontier()?, f.publisher.cas_attempts());
    assert!(
        f.registry
            .admit_protocol_configuration(policy)?
            .anchor_intent(None, &next)
            .is_err()
    );
    assert_eq!(
        (f.publisher.frontier()?, f.publisher.cas_attempts()),
        before
    );
    assert!(!f.journal().with_file_name("attempt.v1.json").exists());
    assert!(
        f.registry
            .admit_protocol_configuration(policy)?
            .with_verified_decision_window(NOW * 1000, NOW * 1000)
            .is_err()
    );
    let guard = f
        .registry
        .admit_protocol_configuration(policy)?
        .with_verified_decision_window(NOW * 1000, (NOW + 1) * 1000)?;
    // load_locked and the initial exact-window read see NOW. The real check
    // after proposal+attempt fsync sees the expiry instant and refuses CAS.
    f.publisher.advance_clock_after_reads(2, NOW + 1)?;
    assert!(matches!(
        guard.anchor_intent(None, &next),
        Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
    ));
    assert_eq!(
        (f.publisher.frontier()?, f.publisher.cas_attempts()),
        before
    );
    assert!(f.journal().with_file_name("proposal.v1.json").is_file());
    assert!(f.journal().with_file_name("attempt.v1.json").is_file());
    Ok(())
}

#[test]
fn reconciliation_expiry_after_fsync_preserves_both_proposals_without_issuing_cas()
-> QualificationResult<()> {
    let f = ColdPending::first(false)?;
    let before = (
        f.publisher.frontier()?,
        f.publisher.cas_attempts(),
        f.pending_bytes()?,
    );
    let mode = f.mode()?;
    let guard = mode
        .admit_pending_intent_reconciliation(f.policy)?
        .with_verified_decision_window(NOW * 1000, (NOW + 1) * 1000)?;
    f.publisher.advance_clock_after_reads(1, NOW + 1)?;
    assert!(
        guard
            .reconcile_abandon_unknown(
                &f.unknown(None),
                [91; 32],
                None,
                Anchor::absent_sha256(&f.agent)
            )
            .is_err()
    );
    assert_eq!(
        (
            f.publisher.frontier()?,
            f.publisher.cas_attempts(),
            f.pending_bytes()?
        ),
        before
    );
    assert!(
        f.directory
            .join("intent-reconciliation-proposal.v1.json")
            .is_file()
    );
    assert!(
        f.directory
            .join("intent-reconciliation-attempt.v1.json")
            .is_file()
    );
    drop(mode);
    assert!(f.ordinary().is_err());
    let mode = f.mode()?;
    let guard = mode
        .admit_pending_intent_reconciliation(f.policy)?
        .with_verified_decision_window((NOW + 1) * 1000, (NOW + 2) * 1000)?;
    let observed = observations(&guard)?;
    f.publisher.advance_clock_after_reads(1, NOW + 2)?;
    assert!(
        guard
            .retry_retained_publication(
                [115; 32],
                Anchor::absent_sha256(&f.agent),
                observed.0,
                observed.1,
                observed.2
            )
            .is_err()
    );
    assert_eq!(
        (
            f.publisher.frontier()?,
            f.publisher.cas_attempts(),
            f.pending_bytes()?
        ),
        before
    );
    let guard = mode
        .admit_pending_intent_reconciliation(f.policy)?
        .with_verified_decision_window((NOW + 2) * 1000, (NOW + 3) * 1000)?;
    assert_eq!(observations(&guard)?, observed);
    guard.retry_retained_publication(
        [116; 32],
        Anchor::absent_sha256(&f.agent),
        observed.0,
        observed.1,
        observed.2,
    )?;
    drop(mode);
    assert_eq!(
        f.ordinary()?.release_intent_anchor(&f.agent)?,
        Some(f.unknown(None))
    );
    Ok(())
}

#[test]
fn proposal_only_retry_expiry_retains_the_new_attempt_and_requires_its_new_observation()
-> QualificationResult<()> {
    let f = ColdPending::first(false)?;
    retain_replacement(&f, true)?;
    let before = (
        f.publisher.frontier()?,
        f.publisher.cas_attempts(),
        f.pending_bytes()?,
    );
    let proposal = std::fs::read(f.directory.join("intent-reconciliation-proposal.v1.json"))?;
    let mode = f.mode()?;
    let guard = mode
        .admit_pending_intent_reconciliation(f.policy)?
        .with_verified_decision_window(NOW * 1000, (NOW + 1) * 1000)?;
    let old = observations(&guard)?;
    f.publisher.advance_clock_after_reads(1, NOW + 1)?;
    assert!(
        guard
            .retry_retained_publication(
                [117; 32],
                Anchor::absent_sha256(&f.agent),
                old.0,
                old.1,
                old.2
            )
            .is_err()
    );
    assert_eq!(
        (
            f.publisher.frontier()?,
            f.publisher.cas_attempts(),
            f.pending_bytes()?
        ),
        before
    );
    assert_eq!(
        std::fs::read(f.directory.join("intent-reconciliation-proposal.v1.json"))?,
        proposal
    );
    assert!(
        f.directory
            .join("intent-reconciliation-attempt.v1.json")
            .is_file()
    );
    drop(mode);
    let mode = f.mode()?;
    let guard = mode
        .admit_pending_intent_reconciliation(f.policy)?
        .with_verified_decision_window((NOW + 1) * 1000, (NOW + 2) * 1000)?;
    let current = observations(&guard)?;
    assert_eq!((old.0, old.1), (current.0, current.1));
    assert_ne!(old.2, current.2);
    assert!(
        guard
            .retry_retained_publication(
                [118; 32],
                Anchor::absent_sha256(&f.agent),
                old.0,
                old.1,
                old.2
            )
            .is_err()
    );
    assert_eq!(f.publisher.cas_attempts(), before.1);
    let guard = mode
        .admit_pending_intent_reconciliation(f.policy)?
        .with_verified_decision_window((NOW + 1) * 1000, (NOW + 2) * 1000)?;
    guard.retry_retained_publication(
        [119; 32],
        Anchor::absent_sha256(&f.agent),
        current.0,
        current.1,
        current.2,
    )?;
    drop(mode);
    assert_eq!(
        f.ordinary()?.release_intent_anchor(&f.agent)?,
        Some(f.unknown(None))
    );
    Ok(())
}
