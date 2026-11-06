//! Real PQ history-owner controls; no signature or frontier admission is stubbed.
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use codex_hepta_contracts::AgentId;

use crate::FleetRegistry;
use crate::FleetRegistryError;
use crate::QualificationResult;
use crate::ReleaseIntentAnchorV1 as Anchor;
use crate::ReleaseIntentPhaseV1 as Phase;
use crate::ReleaseIntentWitnessKindV1 as WitnessKind;
use crate::release_authority_tests::Fixture;
use crate::release_intent_anchor_tests::advance;
use crate::release_intent_anchor_tests::prepared;
use crate::release_intent_anchor_tests::queue;
use crate::release_intent_anchor_tests::setup;
use crate::release_intent_anchor_tests::witness;
use crate::release_qualification_trust::NOW;

fn anchored() -> QualificationResult<(Fixture, Anchor)> {
    let (f, _id, policy) = setup()?;
    let initial = prepared(&f, policy, /*grant*/ 61, /*generation*/ 1);
    drop(
        f.registry
            .admit_protocol_configuration(policy)?
            .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
            .anchor_intent(/*expected*/ None, &initial)?,
    );
    Ok((f, initial))
}

fn queued() -> QualificationResult<(Fixture, Anchor)> {
    let (f, id, policy) = setup()?;
    let initial = prepared(&f, policy, /*grant*/ 62, /*generation*/ 1);
    let next = queue(&f, &id, policy, &initial)?;
    Ok((f, next))
}

#[test]
fn historical_owner_quarantine_survives_policy_expiry_and_cold_reopen() -> QualificationResult<()> {
    let (f, initial) = queued()?;
    let history = f.registry.observe_release_intent_history(&f.agent)?;
    assert_eq!(history.observed_anchor(), Some(&initial));
    f.publisher.advance_clock_to(NOW + 60);
    assert_eq!(history.refresh_anchor()?, Some(initial.clone()));
    let next = advance(&initial, Phase::RecoveryRequired);
    let attempts = f.publisher.cas_attempts();
    history.record_quarantine(&initial, &next)?;
    let cold =
        FleetRegistry::open_existing_with_release_authority(f.root.clone(), f.publisher.config())?;
    assert_eq!(cold.release_intent_anchor(&f.agent)?, Some(next.clone()));
    assert_eq!(f.publisher.cas_attempts(), attempts + 1);
    assert!(
        cold.admit_protocol_configuration(initial.original_grant_policy_sha256.ok_or("policy")?)
            .is_err()
    );
    let unchanged = (
        std::fs::read(f.journal())?,
        f.publisher.frontier()?,
        f.publisher.cas_attempts(),
    );
    for other in [next.clone(), advance(&next, Phase::Aborted)] {
        assert!(matches!(
            cold.observe_release_intent_history(&f.agent)?.record_quarantine(&next, &other),
            Err(FleetRegistryError::Invalid(message))
                if message == "PQ release authority: historical owner only records strict cold quarantine"
        ));
        assert_eq!(
            (
                std::fs::read(f.journal())?,
                f.publisher.frontier()?,
                f.publisher.cas_attempts()
            ),
            unchanged
        );
    }
    Ok(())
}

#[test]
fn historical_owner_refresh_rejects_journal_full_frontier_and_clock_drift()
-> QualificationResult<()> {
    let (f, initial) = anchored()?;
    let history = f.registry.observe_release_intent_history(&f.agent)?;
    let bytes = std::fs::read(f.journal())?;
    let frontier = f.publisher.frontier()?.ok_or("frontier")?;
    let attempts = f.publisher.cas_attempts();
    let mut changed = bytes.clone();
    changed.push(b' ');
    std::fs::write(f.journal(), &changed)?;
    assert!(matches!(
        history.refresh_anchor(),
        Err(FleetRegistryError::ReleaseAuthorityRollback)
    ));
    assert_eq!(
        (
            std::fs::read(f.journal())?,
            f.publisher.frontier()?,
            f.publisher.cas_attempts()
        ),
        (changed, Some(frontier), attempts)
    );
    std::fs::write(f.journal(), &bytes)?;
    for field in 0..3 {
        let mut changed = frontier;
        match field {
            0 => changed.generation += 1,
            1 => changed.initial_root_sha256[0] ^= 1,
            _ => changed.checkpoint_sha256[0] ^= 1,
        }
        std::fs::write(
            &f.publisher.trust.frontier_path,
            serde_json::to_vec(&changed)?,
        )?;
        assert!(matches!(
            history.refresh_anchor(),
            Err(FleetRegistryError::ReleaseAuthorityRollback)
        ));
        assert_eq!(
            (
                std::fs::read(f.journal())?,
                f.publisher.frontier()?,
                f.publisher.cas_attempts()
            ),
            (bytes.clone(), Some(changed), attempts)
        );
    }
    std::fs::write(
        &f.publisher.trust.frontier_path,
        serde_json::to_vec(&frontier)?,
    )?;
    f.publisher.advance_clock_to(NOW - 1);
    let result = history.refresh_anchor();
    assert!(
        matches!(&result, Err(FleetRegistryError::Invalid(message))
        if message == "PQ release authority: release clock unavailable: Invalid"),
        "{result:?}"
    );
    assert_eq!(
        (
            std::fs::read(f.journal())?,
            f.publisher.frontier()?,
            f.publisher.cas_attempts()
        ),
        (bytes.clone(), Some(frontier), attempts)
    );
    f.publisher.advance_clock_to(NOW);
    assert_eq!(history.refresh_anchor()?, Some(initial));
    assert_eq!(
        (
            std::fs::read(f.journal())?,
            f.publisher.frontier()?,
            f.publisher.cas_attempts()
        ),
        (bytes, Some(frontier), attempts)
    );
    Ok(())
}

#[test]
fn historical_owner_consuming_record_rechecks_each_original_load_boundary()
-> QualificationResult<()> {
    let (f, initial) = anchored()?;
    let next = advance(&initial, Phase::RecoveryRequired);
    let bytes = std::fs::read(f.journal())?;
    let frontier = f.publisher.frontier()?.ok_or("frontier")?;
    let attempts = f.publisher.cas_attempts();
    for fault in 0..3 {
        let history = f.registry.observe_release_intent_history(&f.agent)?;
        assert_eq!(history.refresh_anchor()?, Some(initial.clone()));
        match fault {
            0 => {
                let mut changed = bytes.clone();
                changed.push(b' ');
                std::fs::write(f.journal(), changed)?;
            }
            1 => {
                let mut changed = frontier;
                changed.generation += 1;
                std::fs::write(
                    &f.publisher.trust.frontier_path,
                    serde_json::to_vec(&changed)?,
                )?;
            }
            _ => f.publisher.advance_clock_to(NOW - 1),
        }
        let unchanged = (
            std::fs::read(f.journal())?,
            f.publisher.frontier()?,
            f.publisher.cas_attempts(),
        );
        let result = history.record_quarantine(&initial, &next);
        if fault < 2 {
            assert!(
                matches!(&result, Err(FleetRegistryError::ReleaseAuthorityRollback)),
                "{result:?}"
            );
        } else {
            assert!(
                matches!(&result, Err(FleetRegistryError::Invalid(message))
                if message == "PQ release authority: release clock unavailable: Invalid"),
                "{result:?}"
            );
        }
        assert_eq!(
            (
                std::fs::read(f.journal())?,
                f.publisher.frontier()?,
                f.publisher.cas_attempts()
            ),
            unchanged
        );
        std::fs::write(f.journal(), &bytes)?;
        std::fs::write(
            &f.publisher.trust.frontier_path,
            serde_json::to_vec(&frontier)?,
        )?;
        f.publisher.advance_clock_to(NOW);
        assert_eq!(f.publisher.cas_attempts(), attempts);
        assert!(!f.journal().with_file_name("attempt.v1.json").exists());
    }
    assert_eq!(f.registry.release_intent_anchor(&f.agent)?, Some(initial));
    Ok(())
}

#[test]
fn historical_owner_preserves_pending_marker_and_named_lock_refusals() -> QualificationResult<()> {
    let (f, initial) = anchored()?;
    let next = advance(&initial, Phase::RecoveryRequired);
    let attempts = f.publisher.cas_attempts();
    for name in ["attempt.v1.json", "proposal.v1.json"] {
        let history = f.registry.observe_release_intent_history(&f.agent)?;
        let path = f.journal().with_file_name(name);
        std::fs::write(&path, b"retained unknown")?;
        assert!(matches!(
            history.refresh_anchor(),
            Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
        ));
        assert!(matches!(
            history.record_quarantine(&initial, &next),
            Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
        ));
        assert_eq!(std::fs::read(&path)?, b"retained unknown");
        std::fs::remove_file(&path)?;
    }
    let history = f.registry.observe_release_intent_history(&f.agent)?;
    let lock = f.journal().with_file_name("owner.lock");
    let retained = lock.with_file_name("retained-owner.lock");
    std::fs::rename(&lock, &retained)?;
    std::fs::copy(&retained, &lock)?;
    assert!(
        matches!(history.refresh_anchor(), Err(FleetRegistryError::Invalid(message))
        if message == "PQ release authority: held release owner lock was replaced")
    );
    assert!(
        matches!(history.record_quarantine(&initial, &next), Err(FleetRegistryError::Invalid(message))
        if message == "PQ release authority: held release owner lock was replaced")
    );
    std::fs::remove_file(&lock)?;
    std::fs::rename(&retained, &lock)?;
    assert_eq!(f.registry.release_intent_anchor(&f.agent)?, Some(initial));
    assert_eq!(f.publisher.cas_attempts(), attempts);
    Ok(())
}

#[test]
fn historical_owner_cannot_change_agent_or_authorize_new_grant_or_completion()
-> QualificationResult<()> {
    let (f, initial) = anchored()?;
    let attempts = f.publisher.cas_attempts();
    let bytes = std::fs::read(f.journal())?;
    let frontier = f.publisher.frontier()?;
    let mut foreign = advance(&initial, Phase::RecoveryRequired);
    foreign.agent_id = AgentId::parse("22222222-2222-4222-8222-222222222222")?;
    assert_ne!(foreign.agent_id, f.agent);
    assert!(matches!(
        f.registry.observe_release_intent_history(&f.agent)?.record_quarantine(&initial, &foreign),
        Err(FleetRegistryError::Invalid(message))
            if message == "PQ release authority: historical intent belongs to another agent"
    ));
    let mut new_grant = advance(&initial, Phase::RecoveryRequired);
    new_grant.grant_sha256[0] ^= 1;
    assert!(matches!(
        f.registry.observe_release_intent_history(&f.agent)?.record_quarantine(&initial, &new_grant),
        Err(FleetRegistryError::Invalid(message))
            if message == "PQ release authority: new intent requires a fresh grant or explicit legacy recovery"
    ));
    assert_eq!(
        (
            std::fs::read(f.journal())?,
            f.publisher.frontier()?,
            f.publisher.cas_attempts()
        ),
        (bytes, frontier, attempts)
    );
    let (queued_fixture, queued_anchor) = queued()?;
    let unchanged = (
        std::fs::read(queued_fixture.journal())?,
        queued_fixture.publisher.frontier()?,
        queued_fixture.publisher.cas_attempts(),
    );
    for phase in [Phase::Committed, Phase::RolledBack] {
        let mut completed = advance(&queued_anchor, phase);
        completed.terminal_witness = Some(witness(
            WitnessKind::CompletedReleaseCas,
            /*decision*/ None,
        ));
        completed.validate()?;
        assert!(matches!(
            queued_fixture.registry.observe_release_intent_history(&queued_fixture.agent)?
                .record_quarantine(&queued_anchor, &completed),
            Err(FleetRegistryError::Invalid(message))
                if message == "PQ release authority: historical owner only records strict cold quarantine"
        ));
        assert_eq!(
            (
                std::fs::read(queued_fixture.journal())?,
                queued_fixture.publisher.frontier()?,
                queued_fixture.publisher.cas_attempts()
            ),
            unchanged
        );
    }
    Ok(())
}

#[test]
fn historical_owner_uncertain_cas_retains_proposal_and_fences_cold_reopen()
-> QualificationResult<()> {
    let (f, initial) = anchored()?;
    let next = advance(&initial, Phase::RecoveryRequired);
    let history = f.registry.observe_release_intent_history(&f.agent)?;
    assert_eq!(history.refresh_anchor()?, Some(initial.clone()));
    let frontier = f.publisher.frontier()?;
    let bytes = std::fs::read(f.journal())?;
    let attempts = f.publisher.cas_attempts();
    f.publisher.drop_next_cas_without_commit();
    assert!(matches!(
        history.record_quarantine(&initial, &next),
        Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
    ));
    assert_eq!(
        (
            std::fs::read(f.journal())?,
            f.publisher.frontier()?,
            f.publisher.cas_attempts()
        ),
        (bytes, frontier, attempts + 1)
    );
    assert!(f.journal().with_file_name("attempt.v1.json").is_file());
    assert!(f.journal().with_file_name("proposal.v1.json").is_file());
    assert!(matches!(
        f.registry.observe_release_intent_history(&f.agent),
        Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
    ));
    assert!(matches!(
        FleetRegistry::open_existing_with_release_authority(f.root.clone(), f.publisher.config()),
        Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
    ));
    Ok(())
}
