//! Reusing a held historical state never supplies current effect authority.
//! Fixtures still use the actual signed clock/frontier and real external CAS.
use pretty_assertions::assert_eq;

use crate::FleetRegistryError;
use crate::QualificationResult;
use crate::ReleaseIntentPhaseV1 as Phase;
use crate::ReleaseIntentWitnessKindV1 as WitnessKind;
use crate::release_intent_anchor_tests::advance;
use crate::release_intent_anchor_tests::prepared;
use crate::release_intent_anchor_tests::queue;
use crate::release_intent_anchor_tests::setup;
use crate::release_intent_anchor_tests::witness;
use crate::release_qualification_trust::NOW;

#[test]
fn held_history_survives_policy_and_window_expiry_but_rejects_clock_regression()
-> QualificationResult<()> {
    let (f, _id, policy) = setup()?;
    let initial = prepared(&f, policy, 41, 1);
    let guard = f
        .registry
        .admit_protocol_configuration(policy)?
        .with_verified_decision_window(NOW * 1000, (NOW + 2) * 1000)?
        .anchor_intent(None, &initial)?;
    let before = (f.publisher.frontier()?, f.publisher.cas_attempts());
    f.publisher.advance_clock_to(NOW + 60);
    assert!(guard.revalidate().is_err());
    assert_eq!(guard.intent_anchor(&f.agent)?, Some(initial.clone()));
    assert_eq!(guard.previous_closed_intent_anchor(&f.agent)?, None);
    f.publisher.advance_clock_to(NOW - 1);
    assert!(guard.intent_anchor(&f.agent).is_err());
    assert!(guard.previous_closed_intent_anchor(&f.agent).is_err());
    f.publisher.advance_clock_to(NOW + 60);
    assert_eq!(guard.intent_anchor(&f.agent)?, Some(initial));
    assert_eq!(guard.previous_closed_intent_anchor(&f.agent)?, None);
    assert!(guard.revalidate().is_err());
    assert_eq!(
        (f.publisher.frontier()?, f.publisher.cas_attempts()),
        before
    );
    Ok(())
}

#[test]
fn held_history_rejects_local_bytes_and_complete_signed_frontier_drift() -> QualificationResult<()>
{
    let (f, _id, policy) = setup()?;
    let initial = prepared(&f, policy, 42, 1);
    let guard = f
        .registry
        .admit_protocol_configuration(policy)?
        .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
        .anchor_intent(None, &initial)?;
    let original = std::fs::read(f.journal())?;
    let before = f.publisher.frontier()?.ok_or("missing frontier")?;
    let attempts = f.publisher.cas_attempts();
    let mut changed = original.clone();
    changed.push(b' ');
    std::fs::write(f.journal(), &changed)?;
    std::fs::File::open(f.journal())?.sync_all()?;
    assert!(matches!(
        guard.intent_anchor(&f.agent),
        Err(FleetRegistryError::ReleaseAuthorityRollback)
    ));
    assert!(matches!(
        guard.previous_closed_intent_anchor(&f.agent),
        Err(FleetRegistryError::ReleaseAuthorityRollback)
    ));
    std::fs::write(f.journal(), &original)?;
    std::fs::File::open(f.journal())?.sync_all()?;
    assert_eq!(guard.intent_anchor(&f.agent)?, Some(initial.clone()));
    assert_eq!(guard.previous_closed_intent_anchor(&f.agent)?, None);
    for field in 0..3 {
        let mut changed = before;
        match field {
            0 => changed.generation += 1,
            1 => changed.initial_root_sha256[0] ^= 1,
            _ => changed.checkpoint_sha256[0] ^= 1,
        }
        std::fs::write(
            &f.publisher.trust.frontier_path,
            serde_json::to_vec(&changed)?,
        )?;
        std::fs::File::open(&f.publisher.trust.frontier_path)?.sync_all()?;
        assert!(matches!(
            guard.intent_anchor(&f.agent),
            Err(FleetRegistryError::ReleaseAuthorityRollback)
        ));
        assert!(matches!(
            guard.previous_closed_intent_anchor(&f.agent),
            Err(FleetRegistryError::ReleaseAuthorityRollback)
        ));
    }
    std::fs::write(
        &f.publisher.trust.frontier_path,
        serde_json::to_vec(&before)?,
    )?;
    std::fs::File::open(&f.publisher.trust.frontier_path)?.sync_all()?;
    assert_eq!(guard.intent_anchor(&f.agent)?, Some(initial));
    assert_eq!(guard.previous_closed_intent_anchor(&f.agent)?, None);
    assert_eq!(std::fs::read(f.journal())?, original);
    assert_eq!(f.publisher.cas_attempts(), attempts);
    Ok(())
}

#[test]
fn refreshed_history_returns_exact_new_anchor_and_actual_closed_predecessor()
-> QualificationResult<()> {
    let (f, id, policy) = setup()?;
    let initial = prepared(&f, policy, 43, 1);
    let queued = queue(&f, &id, policy, &initial)?;
    let mut completed = advance(&queued, Phase::Committed);
    completed.terminal_witness = Some(witness(WitnessKind::CompletedReleaseCas, None));
    f.registry.record_intent_history(&queued, &completed)?;
    let guard = f
        .registry
        .admit_protocol_configuration(policy)?
        .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?;
    assert_eq!(guard.intent_anchor(&f.agent)?, Some(completed.clone()));
    assert_eq!(guard.previous_closed_intent_anchor(&f.agent)?, None);
    let next = prepared(&f, policy, 44, completed.generation + 1);
    let guard = guard.anchor_intent(Some(&completed), &next)?;
    assert_eq!(guard.intent_anchor(&f.agent)?, Some(next.clone()));
    assert_eq!(
        guard.previous_closed_intent_anchor(&f.agent)?,
        Some(completed.clone())
    );
    let next_queued = advance(&next, Phase::Queued);
    let guard = guard.anchor_intent(Some(&next), &next_queued)?;
    assert_eq!(guard.intent_anchor(&f.agent)?, Some(next_queued));
    assert_eq!(
        guard.previous_closed_intent_anchor(&f.agent)?,
        Some(completed)
    );
    Ok(())
}

#[test]
fn actual_failed_anchor_cas_fences_even_a_retained_historical_guard() -> QualificationResult<()> {
    let (f, id, policy) = setup()?;
    let initial = prepared(&f, policy, 45, 1);
    let mut guard = f
        .registry
        .admit_release(&f.agent, &id)?
        .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?;
    let before = f.publisher.frontier()?;
    let attempts = f.publisher.cas_attempts();
    f.publisher.drop_next_cas_without_commit();
    // Invoke the same internal owner method used by the consuming public API,
    // retaining its old guard solely to prove that a real failed CAS fences it.
    let (owner, admission) = guard.authority.as_mut().ok_or("missing PQ admission")?;
    assert!(
        owner
            .anchor_release_intent(&mut admission.publication, policy, None, &initial)
            .is_err()
    );
    assert_eq!(f.publisher.frontier()?, before);
    assert_eq!(f.publisher.cas_attempts(), attempts + 1);
    assert!(matches!(
        guard.intent_anchor(),
        Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
    ));
    assert!(matches!(
        guard.previous_closed_intent_anchor(),
        Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
    ));
    assert!(guard.revalidate().is_err());
    Ok(())
}
