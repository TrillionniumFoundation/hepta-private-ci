//! Component tests use real signed M15 publications and the ordinary Registry
//! owner. H7's independent tests bind these digests to its actual intent bytes.

use sha2::Digest;

use crate::FleetRegistry;
use crate::FleetRegistryError;
use crate::QualificationResult;
use crate::ReleaseId;
use crate::ReleaseIntentAnchorV1 as Anchor;
use crate::ReleaseIntentPhaseV1 as Phase;
use crate::ReleaseIntentTerminalWitnessV1 as Witness;
use crate::ReleaseIntentWitnessKindV1 as WitnessKind;
use crate::release_authority_tests::Fixture;
use crate::release_qualification_trust::NOW;

pub(super) fn setup() -> QualificationResult<(Fixture, ReleaseId, [u8; 32])> {
    let mut fixture = Fixture::new()?;
    let id = fixture.install("anchor-release")?;
    fixture.allow(&id)?;
    let policy = b"H7 anchor component policy";
    fixture
        .publisher
        .publish_protocol_configuration(&fixture.registry, policy, NOW + 60)?;
    Ok((fixture, id, sha2::Sha256::digest(policy).into()))
}

pub(super) fn prepared(f: &Fixture, policy: [u8; 32], grant: u8, generation: u64) -> Anchor {
    Anchor {
        schema_version: 1,
        agent_id: f.agent.clone(),
        generation,
        phase: Phase::Prepared,
        intent_sha256: [grant + 10; 32],
        grant_sha256: [grant; 32],
        original_grant_policy_sha256: Some(policy),
        terminal_witness: None,
    }
}

pub(super) fn advance(old: &Anchor, phase: Phase) -> Anchor {
    let mut next = old.clone();
    next.generation += 1;
    next.intent_sha256[0] += 1;
    next.phase = phase;
    next
}

pub(super) fn witness(kind: WitnessKind, decision: Option<[u8; 32]>) -> Witness {
    Witness {
        kind,
        transaction_sha256: [71; 32],
        release_state_sha256: [72; 32],
        release_state_generation: 1,
        recovery_decision_sha256: decision,
        publication_confirmation_sha256: None,
    }
}

pub(super) fn queue(
    f: &Fixture,
    id: &ReleaseId,
    policy: [u8; 32],
    value: &Anchor,
) -> QualificationResult<Anchor> {
    drop(
        f.registry
            .admit_protocol_configuration(policy)?
            .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
            .anchor_intent(None, value)?,
    );
    let queued = advance(value, Phase::Queued);
    let release = f
        .registry
        .admit_release(&f.agent, id)?
        .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
        .anchor_intent(policy, Some(value), &queued)?;
    assert_eq!(release.intent_anchor()?, Some(queued.clone()));
    release.revalidate_with_protocol_configuration(policy)?;
    Ok(queued)
}

#[test]
fn intent_cas_changes_full_frontier_but_preserves_exact_release_permission_projection()
-> QualificationResult<()> {
    let (mut f, id, policy) = setup()?;
    let second = f.install("anchor-second")?;
    let before = f.registry.resolve_release_binding(&f.agent, &id)?;
    let frontier = f.publisher.frontier()?.ok_or("missing frontier")?;
    let prepared = prepared(&f, policy, 1, 1);
    f.publisher.advance_clock_to(NOW + 1);
    let queued = queue(&f, &id, policy, &prepared)?;
    let future = f.publisher.frontier()?.ok_or("missing future frontier")?;
    assert!(future.generation > frontier.generation);
    assert_ne!(future.state_sha256, frontier.state_sha256);
    assert_eq!(future.checkpoint_sha256, frontier.checkpoint_sha256);
    assert_eq!(f.registry.resolve_release_binding(&f.agent, &id)?, before);
    let count = f.publisher.cas_attempts();
    let guard = f
        .registry
        .admit_protocol_configuration(policy)?
        .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?;
    assert_eq!(guard.intent_anchor(&f.agent)?, Some(queued.clone()));
    drop(guard.anchor_intent(Some(&queued), &queued)?);
    assert_eq!(f.publisher.cas_attempts(), count);
    assert!(
        f.registry
            .admit_protocol_configuration(policy)?
            .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
            .anchor_intent(Some(&prepared), &queued)
            .is_err()
    );
    assert_eq!(f.publisher.cas_attempts(), count);
    f.allow(&second)?;
    let allowed = f.registry.resolve_release_binding(&f.agent, &id)?;
    assert_ne!(allowed, before);
    f.registry.revoke_release(&f.agent, &second)?;
    assert_ne!(f.registry.resolve_release_binding(&f.agent, &id)?, allowed);
    let old = f.registry.resolve_release_binding(&f.agent, &id)?;
    f.publisher
        .publish_protocol_configuration(&f.registry, b"replacement policy", NOW + 60)?;
    assert_ne!(f.registry.resolve_release_binding(&f.agent, &id)?, old);
    assert!(f.registry.admit_protocol_configuration(policy).is_err());
    Ok(())
}

#[test]
fn retained_terminal_history_survives_policy_expiry_without_authorizing_a_new_grant()
-> QualificationResult<()> {
    let (f, id, policy) = setup()?;
    let first = prepared(&f, policy, 2, 1);
    let queued = queue(&f, &id, policy, &first)?;
    f.publisher.advance_clock_to(NOW + 60);
    assert!(f.registry.admit_protocol_configuration(policy).is_err());
    let mut terminal = advance(&queued, Phase::Committed);
    terminal.terminal_witness = Some(witness(WitnessKind::CompletedReleaseCas, None));
    f.registry.record_intent_history(&queued, &terminal)?;
    let reopened =
        FleetRegistry::open_existing_with_release_authority(f.root.clone(), f.publisher.config())?;
    assert_eq!(
        reopened.release_intent_anchor(&f.agent)?,
        Some(terminal.clone())
    );
    reopened.admit_release(&f.agent, &id)?.revalidate()?;
    let next = prepared(&f, policy, 3, terminal.generation + 1);
    assert!(reopened.admit_protocol_configuration(policy).is_err());
    assert!(reopened.record_intent_history(&terminal, &next).is_err());
    assert_eq!(reopened.release_intent_anchor(&f.agent)?, Some(terminal));
    Ok(())
}

#[test]
fn local_abort_stays_fenced_and_consumed_grants_survive_explicit_unknown_closure_and_reopen()
-> QualificationResult<()> {
    let (f, id, policy) = setup()?;
    let first = prepared(&f, policy, 4, 1);
    let queued = queue(&f, &id, policy, &first)?;
    let quarantine = advance(&queued, Phase::RecoveryRequired);
    f.registry.record_intent_history(&queued, &quarantine)?;
    let abort = advance(&quarantine, Phase::Aborted);
    f.registry.record_intent_history(&quarantine, &abort)?;
    assert!(!abort.is_closed_history());
    let next = prepared(&f, policy, 5, abort.generation + 1);
    assert!(
        f.registry
            .admit_protocol_configuration(policy)?
            .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
            .anchor_intent(Some(&abort), &next)
            .is_err()
    );
    let mut closed = advance(&abort, Phase::Aborted);
    closed.terminal_witness = Some(witness(WitnessKind::AbandonUnknown, Some([81; 32])));
    assert!(f.registry.record_intent_history(&abort, &closed).is_err());
    drop(
        f.registry
            .admit_protocol_configuration(policy)?
            .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
            .recover_intent(Some(&abort), &closed, [81; 32])?,
    );
    assert!(closed.is_closed_history());
    let next = prepared(&f, policy, 5, closed.generation + 1);
    drop(
        f.registry
            .admit_protocol_configuration(policy)?
            .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
            .anchor_intent(Some(&closed), &next)?,
    );
    let quarantined = advance(&next, Phase::RecoveryRequired);
    f.registry.record_intent_history(&next, &quarantined)?;
    let mut closed_again = advance(&quarantined, Phase::Aborted);
    closed_again.terminal_witness = Some(witness(WitnessKind::AbandonUnknown, Some([82; 32])));
    drop(
        f.registry
            .admit_protocol_configuration(policy)?
            .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
            .recover_intent(Some(&quarantined), &closed_again, [82; 32])?,
    );
    let reopened =
        FleetRegistry::open_existing_with_release_authority(f.root.clone(), f.publisher.config())?;
    let replay = prepared(&f, policy, 4, closed_again.generation + 1);
    let count = f.publisher.cas_attempts();
    assert!(
        reopened
            .admit_protocol_configuration(policy)?
            .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
            .anchor_intent(Some(&closed_again), &replay)
            .is_err()
    );
    assert_eq!(f.publisher.cas_attempts(), count);
    assert_eq!(
        reopened.release_intent_anchor(&f.agent)?,
        Some(closed_again)
    );
    Ok(())
}

#[test]
fn stale_generation_zero_terminal_cas_and_forged_completion_do_not_replace_prepared_anchor()
-> QualificationResult<()> {
    let (f, _id, policy) = setup()?;
    let first = prepared(&f, policy, 6, 1);
    drop(
        f.registry
            .admit_protocol_configuration(policy)?
            .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
            .anchor_intent(None, &first)?,
    );
    let mut forged = advance(&first, Phase::Committed);
    forged.terminal_witness = Some(witness(WitnessKind::CompletedReleaseCas, None));
    let before = (
        f.publisher.frontier()?,
        f.publisher.cas_attempts(),
        std::fs::read(f.journal())?,
    );
    assert!(f.registry.record_intent_history(&first, &forged).is_err());
    assert!(
        f.registry
            .admit_protocol_configuration(policy)?
            .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
            .anchor_intent(Some(&first), &forged)
            .is_err()
    );
    let mut zero = forged;
    zero.terminal_witness
        .as_mut()
        .ok_or("witness missing")?
        .release_state_generation = 0;
    assert!(zero.validate().is_err());
    assert!(
        f.registry
            .admit_protocol_configuration(policy)?
            .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
            .recover_intent(Some(&first), &zero, [83; 32])
            .is_err()
    );
    let mut stale = advance(&first, Phase::Queued);
    stale.generation = first.generation;
    assert!(
        f.registry
            .admit_protocol_configuration(policy)?
            .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
            .anchor_intent(Some(&first), &stale)
            .is_err()
    );
    assert_eq!(
        (
            f.publisher.frontier()?,
            f.publisher.cas_attempts(),
            std::fs::read(f.journal())?
        ),
        before
    );
    assert_eq!(f.registry.release_intent_anchor(&f.agent)?, Some(first));
    Ok(())
}

#[test]
fn local_journal_terminal_forgery_and_complete_pre_anchor_rollback_fail_against_future_owner()
-> QualificationResult<()> {
    let (f, _id, policy) = setup()?;
    let journal = f.journal();
    let previous = std::fs::read(&journal)?;
    let first = prepared(&f, policy, 7, 1);
    drop(
        f.registry
            .admit_protocol_configuration(policy)?
            .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
            .anchor_intent(None, &first)?,
    );
    let mut altered: serde_json::Value = serde_json::from_slice(&std::fs::read(&journal)?)?;
    let entry = altered["entries"]
        .as_array_mut()
        .ok_or("entries missing")?
        .last_mut()
        .ok_or("anchor missing")?;
    entry["anchor"]["phase"] = "committed".into();
    let forged = serde_json::to_vec(&altered)?;
    let future = (f.publisher.frontier()?, f.publisher.cas_attempts());
    let Fixture {
        registry,
        publisher,
        root,
        _temp,
        ..
    } = f;
    drop(registry); // actual local owner is closed before either snapshot restore
    for bytes in [forged, previous] {
        std::fs::write(&journal, &bytes)?;
        std::fs::File::open(&journal)?.sync_all()?;
        assert!(matches!(
            FleetRegistry::open_existing_with_release_authority(root.clone(), publisher.config()),
            Err(FleetRegistryError::ReleaseAuthorityRollback)
        ));
        assert_eq!((publisher.frontier()?, publisher.cas_attempts()), future);
        assert_eq!(std::fs::read(&journal)?, bytes);
    }
    Ok(())
}
