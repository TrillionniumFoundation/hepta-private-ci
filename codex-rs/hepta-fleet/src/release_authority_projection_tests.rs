//! The current-use projection reuses only the state inside its exclusive
//! owner guard. Every observation still needs a fresh signed external frontier,
//! exact local journal hash and current policy at the trusted time.

use pretty_assertions::assert_eq;

use crate::FleetRegistryError;
use crate::QualificationResult;
use crate::ReleaseIntentPhaseV1;
use crate::release_intent_anchor_tests::advance;
use crate::release_intent_anchor_tests::prepared;
use crate::release_intent_anchor_tests::setup;
use crate::release_qualification_trust::NOW;

#[test]
fn held_protocol_projection_rechecks_policy_expiry_and_verified_decision_window()
-> QualificationResult<()> {
    let (f, id, policy) = setup()?;
    let expected = f.registry.resolve_release_binding(&f.agent, &id)?;
    let before = (f.publisher.frontier()?, f.publisher.cas_attempts());
    let guard = f
        .registry
        .admit_protocol_configuration(policy)?
        .with_verified_decision_window(NOW * 1000, (NOW + 2) * 1000)?;
    assert_eq!(
        f.registry
            .release_binding_with_protocol_configuration(&guard, &f.agent, &id)?,
        expected
    );
    f.publisher.advance_clock_to(NOW + 2);
    assert!(
        f.registry
            .release_binding_with_protocol_configuration(&guard, &f.agent, &id)
            .is_err()
    );
    drop(guard);
    let guard = f.registry.admit_protocol_configuration(policy)?;
    assert_eq!(
        f.registry
            .release_binding_with_protocol_configuration(&guard, &f.agent, &id)?,
        expected
    );
    f.publisher.advance_clock_to(NOW + 60);
    assert!(
        f.registry
            .release_binding_with_protocol_configuration(&guard, &f.agent, &id)
            .is_err()
    );
    assert_eq!(
        (f.publisher.frontier()?, f.publisher.cas_attempts()),
        before
    );
    Ok(())
}

#[test]
fn held_protocol_projection_refuses_local_journal_and_signed_frontier_drift()
-> QualificationResult<()> {
    let (f, id, policy) = setup()?;
    let expected = f.registry.resolve_release_binding(&f.agent, &id)?;
    let original = std::fs::read(f.journal())?;
    let guard = f.registry.admit_protocol_configuration(policy)?;
    let count = f.publisher.cas_attempts();
    let mut changed = original.clone();
    changed.push(b' ');
    std::fs::write(f.journal(), &changed)?;
    std::fs::File::open(f.journal())?.sync_all()?;
    assert!(matches!(
        f.registry
            .release_binding_with_protocol_configuration(&guard, &f.agent, &id),
        Err(FleetRegistryError::ReleaseAuthorityRollback)
    ));
    std::fs::write(f.journal(), &original)?;
    std::fs::File::open(f.journal())?.sync_all()?;
    assert_eq!(
        f.registry
            .release_binding_with_protocol_configuration(&guard, &f.agent, &id)?,
        expected
    );
    let mut future = f.publisher.frontier()?.ok_or("missing signed frontier")?;
    future.generation += 1;
    std::fs::write(
        &f.publisher.trust.frontier_path,
        serde_json::to_vec(&future)?,
    )?;
    std::fs::File::open(&f.publisher.trust.frontier_path)?.sync_all()?;
    assert!(matches!(
        f.registry
            .release_binding_with_protocol_configuration(&guard, &f.agent, &id),
        Err(FleetRegistryError::ReleaseAuthorityRollback)
    ));
    assert_eq!(std::fs::read(f.journal())?, original);
    assert_eq!(f.publisher.cas_attempts(), count);
    Ok(())
}

#[test]
fn refreshed_protocol_projection_preserves_current_use_and_expired_historical_reads()
-> QualificationResult<()> {
    let (f, id, policy) = setup()?;
    let expected = f.registry.resolve_release_binding(&f.agent, &id)?;
    let initial = prepared(&f, policy, 31, 1);
    let guard = f
        .registry
        .admit_protocol_configuration(policy)?
        .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
        .anchor_intent(None, &initial)?;
    assert_eq!(guard.intent_anchor(&f.agent)?, Some(initial.clone()));
    assert_eq!(
        f.registry
            .release_binding_with_protocol_configuration(&guard, &f.agent, &id)?,
        expected
    );
    let queued = advance(&initial, ReleaseIntentPhaseV1::Queued);
    let guard = guard.anchor_intent(Some(&initial), &queued)?;
    assert_eq!(guard.intent_anchor(&f.agent)?, Some(queued.clone()));
    assert_eq!(
        f.registry
            .release_binding_with_protocol_configuration(&guard, &f.agent, &id)?,
        expected
    );
    let before = (f.publisher.frontier()?, f.publisher.cas_attempts());
    f.publisher.advance_clock_to(NOW + 60);
    assert!(
        f.registry
            .release_binding_with_protocol_configuration(&guard, &f.agent, &id)
            .is_err()
    );
    // Reading already-anchored history is not new authorization. Historical
    // readers retain separate fresh commitment and time-floor checks without
    // current-policy expiry requirements.
    assert_eq!(guard.intent_anchor(&f.agent)?, Some(queued));
    assert_eq!(guard.previous_closed_intent_anchor(&f.agent)?, None);
    assert_eq!(
        (f.publisher.frontier()?, f.publisher.cas_attempts()),
        before
    );
    Ok(())
}
