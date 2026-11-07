//! Both unresolved publications are real owner attempts. The proposal-only
//! cut stops the actual store writer before an attempt or CAS ever exists.

use crate::FleetRegistry;
use crate::PendingIntentReconciliationAdmission;
use crate::QualificationResult;
use crate::ReleaseIntentAnchorV1 as Anchor;
use crate::release_authority_store::fail_once_after_reconciliation_proposal;
use crate::release_intent_reconciliation_tests::ColdPending;
use crate::release_qualification_trust::NOW;

pub(super) fn retain_replacement(f: &ColdPending, proposal_only: bool) -> QualificationResult<()> {
    let mode = f.mode()?;
    let guard = mode
        .admit_pending_intent_reconciliation(f.policy)?
        .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?;
    if proposal_only {
        fail_once_after_reconciliation_proposal();
    } else {
        f.publisher.drop_next_cas_without_commit();
    }
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
    drop(mode);
    assert_eq!(f.publisher.frontier()?, f.attempt.expected);
    assert!(
        f.directory
            .join("intent-reconciliation-proposal.v1.json")
            .is_file()
    );
    assert_eq!(
        f.directory
            .join("intent-reconciliation-attempt.v1.json")
            .exists(),
        !proposal_only
    );
    Ok(())
}

pub(super) fn observations(
    guard: &PendingIntentReconciliationAdmission,
) -> QualificationResult<([u8; 32], [u8; 32], [u8; 32])> {
    Ok((
        guard.pending_publication_sha256()?,
        guard
            .replacement_publication_sha256()?
            .ok_or("replacement pending digest missing")?,
        guard
            .retained_reconciliation_sha256()?
            .ok_or("retained state digest missing")?,
    ))
}

#[test]
fn actual_second_cas_error_requires_fresh_exact_retry_and_preserves_original_material()
-> QualificationResult<()> {
    let f = ColdPending::first(false)?;
    retain_replacement(&f, false)?;
    let original = f.pending_bytes()?;
    let proposal = std::fs::read(f.directory.join("intent-reconciliation-proposal.v1.json"))?;
    let attempt = std::fs::read(f.directory.join("intent-reconciliation-attempt.v1.json"))?;
    let count = f.publisher.cas_attempts();
    assert!(
        FleetRegistry::recover_completed_release_update(f.root.clone(), f.publisher.config())
            .is_err()
    );
    assert!(f.ordinary().is_err());
    let mode = f.mode()?;
    let guard = mode.admit_pending_intent_reconciliation(f.policy)?;
    let observed = observations(&guard)?;
    // A mere current-policy observation cannot authorize a retry.
    assert!(
        guard
            .retry_retained_publication(
                [111; 32],
                Anchor::absent_sha256(&f.agent),
                observed.0,
                observed.1,
                observed.2
            )
            .is_err()
    );
    for (decision, wrong_state) in [([91; 32], false), ([111; 32], true)] {
        let guard = mode
            .admit_pending_intent_reconciliation(f.policy)?
            .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?;
        let mut state = observed.2;
        if wrong_state {
            state[0] ^= 1;
        }
        assert!(
            guard
                .retry_retained_publication(
                    decision,
                    Anchor::absent_sha256(&f.agent),
                    observed.0,
                    observed.1,
                    state
                )
                .is_err()
        );
    }
    assert_eq!(f.publisher.cas_attempts(), count);
    assert_eq!(f.pending_bytes()?, original);
    assert_eq!(
        std::fs::read(f.directory.join("intent-reconciliation-proposal.v1.json"))?,
        proposal
    );
    assert_eq!(
        std::fs::read(f.directory.join("intent-reconciliation-attempt.v1.json"))?,
        attempt
    );
    let guard = mode
        .admit_pending_intent_reconciliation(f.policy)?
        .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?;
    assert_eq!(guard.replacement_intent_anchor(), Some(&f.unknown(None)));
    assert_eq!(guard.release_binding(&f.agent, &f.release)?, f.binding);
    guard.retry_retained_publication(
        [111; 32],
        Anchor::absent_sha256(&f.agent),
        observed.0,
        observed.1,
        observed.2,
    )?;
    assert_eq!(f.publisher.cas_attempts(), count + 1);
    assert!(mode.resolve_release(&f.agent, &f.release).is_err());
    drop(mode);
    let reopened = f.ordinary()?;
    assert_eq!(
        reopened.release_intent_anchor(&f.agent)?,
        Some(f.unknown(None))
    );
    assert_eq!(
        std::fs::read(f.directory.join("journal.v1.json"))?,
        proposal
    );
    assert_eq!(
        reopened.resolve_release_binding(&f.agent, &f.release)?,
        f.binding
    );
    Ok(())
}

#[test]
fn actual_proposal_fsync_cut_cold_retry_creates_only_the_missing_exact_attempt()
-> QualificationResult<()> {
    let f = ColdPending::first(false)?;
    let before = f.publisher.cas_attempts();
    retain_replacement(&f, true)?;
    assert_eq!(f.publisher.cas_attempts(), before);
    let original = f.pending_bytes()?;
    let proposal = std::fs::read(f.directory.join("intent-reconciliation-proposal.v1.json"))?;
    assert!(f.ordinary().is_err());
    let mode = f.mode()?;
    let guard = mode
        .admit_pending_intent_reconciliation(f.policy)?
        .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?;
    let observed = observations(&guard)?;
    f.publisher.drop_next_committed_cas_reply();
    assert!(
        guard
            .retry_retained_publication(
                [112; 32],
                Anchor::absent_sha256(&f.agent),
                observed.0,
                observed.1,
                observed.2
            )
            .is_err()
    );
    assert_eq!(f.pending_bytes()?, original);
    assert_eq!(
        std::fs::read(f.directory.join("intent-reconciliation-proposal.v1.json"))?,
        proposal
    );
    let update: crate::release_authority::PendingUpdate = serde_json::from_slice(&std::fs::read(
        f.directory.join("intent-reconciliation-attempt.v1.json"),
    )?)?;
    assert_eq!(update.expected, f.attempt.expected);
    assert_eq!(Some(update.proposed), f.publisher.frontier()?);
    assert_eq!(f.publisher.cas_attempts(), before + 1);
    drop(mode);
    // A known winner is completed without reviving the expired retry or the
    // now-expired old policy. No further external CAS is issued.
    f.publisher.advance_clock_to(NOW + 61);
    let reopened =
        FleetRegistry::recover_completed_release_update(f.root.clone(), f.publisher.config())?;
    assert_eq!(
        reopened.release_intent_anchor(&f.agent)?,
        Some(f.unknown(None))
    );
    assert_eq!(
        std::fs::read(f.directory.join("journal.v1.json"))?,
        proposal
    );
    assert_eq!(f.publisher.cas_attempts(), before + 1);
    Ok(())
}

#[test]
fn retry_uncertain_no_commit_retains_the_same_two_proposals_for_another_explicit_decision()
-> QualificationResult<()> {
    let f = ColdPending::first(false)?;
    retain_replacement(&f, false)?;
    let original = f.pending_bytes()?;
    let proposal = std::fs::read(f.directory.join("intent-reconciliation-proposal.v1.json"))?;
    let attempt = std::fs::read(f.directory.join("intent-reconciliation-attempt.v1.json"))?;
    let count = f.publisher.cas_attempts();
    let mode = f.mode()?;
    let guard = mode
        .admit_pending_intent_reconciliation(f.policy)?
        .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?;
    let observed = observations(&guard)?;
    f.publisher.drop_next_cas_without_commit();
    assert!(
        guard
            .retry_retained_publication(
                [113; 32],
                Anchor::absent_sha256(&f.agent),
                observed.0,
                observed.1,
                observed.2
            )
            .is_err()
    );
    drop(mode);
    assert_eq!(f.publisher.frontier()?, f.attempt.expected);
    assert_eq!(f.pending_bytes()?, original);
    assert_eq!(
        std::fs::read(f.directory.join("intent-reconciliation-proposal.v1.json"))?,
        proposal
    );
    assert_eq!(
        std::fs::read(f.directory.join("intent-reconciliation-attempt.v1.json"))?,
        attempt
    );
    let mode = f.mode()?;
    let guard = mode
        .admit_pending_intent_reconciliation(f.policy)?
        .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?;
    assert_eq!(observations(&guard)?, observed);
    guard.retry_retained_publication(
        [114; 32],
        Anchor::absent_sha256(&f.agent),
        observed.0,
        observed.1,
        observed.2,
    )?;
    drop(mode);
    assert_eq!(f.publisher.cas_attempts(), count + 2);
    assert_eq!(
        f.ordinary()?.release_intent_anchor(&f.agent)?,
        Some(f.unknown(None))
    );
    Ok(())
}
