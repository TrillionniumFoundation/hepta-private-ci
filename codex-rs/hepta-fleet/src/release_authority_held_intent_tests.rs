//! A held owner may extend only its verified intent projection. Fresh external
//! trust and actual durable publication still decide every operation.
use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;
use serde_json::Value;

use crate::CurrentReleaseAdmission;
use crate::FleetRegistry;
use crate::FleetRegistryError;
use crate::QualificationResult;
use crate::ReleaseId;
use crate::ReleaseIntentPhaseV1 as Phase;
use crate::ReleaseIntentWitnessKindV1 as WitnessKind;
use crate::release_authority::ReleaseUse;
use crate::release_authority_state::Admission;
use crate::release_authority_tests::Fixture;
use crate::release_intent_anchor_tests::advance;
use crate::release_intent_anchor_tests::prepared;
use crate::release_intent_anchor_tests::queue;
use crate::release_intent_anchor_tests::setup;
use crate::release_intent_anchor_tests::witness;
use crate::release_qualification_trust::AFTER_CAS_FRONTIER_DRIFT;
use crate::release_qualification_trust::AFTER_CAS_LOAD_UNAVAILABLE;
use crate::release_qualification_trust::NOW;

fn held(f: &Fixture, release: &ReleaseId) -> QualificationResult<CurrentReleaseAdmission> {
    Ok(f.registry
        .admit_release(&f.agent, release)?
        .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?)
}

fn projection(admitted: &ReleaseUse) -> Value {
    let publication = &admitted.publication;
    let state = &publication.state;
    let allowances = state
        .admissions
        .iter()
        .map(|(key, value)| match value {
            Admission::Allowed(digest) => (key, "allowed", digest),
            Admission::Revoked(digest) => (key, "revoked", digest),
        })
        .collect::<Vec<_>>();
    serde_json::json!({
        "journal": &state.journal,
        "frontier": state.frontier,
        "held_frontier": publication.frontier,
        "checkpoint": state.authority.checkpoint(),
        "permission_sha256": admitted.permission_sha256,
        "metadata": &admitted.metadata,
        "agent_id": &admitted.agent_id,
        "allowances": allowances,
        "intent_anchors": state.intent_anchors.iter().collect::<Vec<_>>(),
        "previous_closed_intents": state.previous_closed_intents.iter().collect::<Vec<_>>(),
        "consumed_grants": state.consumed_grants.iter().collect::<Vec<_>>(),
        "time_floor": state.time_floor,
    })
}

#[test]
fn held_intent_append_matches_cold_rebuild_with_complete_history_projection()
-> QualificationResult<()> {
    let (f, id, policy) = setup()?;
    let first = prepared(&f, policy, /*grant*/ 51, /*generation*/ 1);
    let queued = queue(&f, &id, policy, &first)?;
    let mut completed = advance(&queued, Phase::Committed);
    completed.terminal_witness = Some(witness(
        WitnessKind::CompletedReleaseCas,
        /*decision*/ None,
    ));
    f.registry.record_intent_history(&queued, &completed)?;
    let mut guard = held(&f, &id)?;
    f.publisher.advance_clock_to(NOW + 5);
    let next = prepared(&f, policy, /*grant*/ 52, completed.generation + 1);
    let next_queued = advance(&next, Phase::Queued);
    let expected = {
        let (owner, admitted) = guard.authority.as_mut().ok_or("missing actual PQ owner")?;
        let before_permission = admitted.permission_sha256;
        let checkpoint = admitted.publication.state.authority.checkpoint();
        owner.anchor_release_intent(&mut admitted.publication, policy, Some(&completed), &next)?;
        owner.anchor_release_intent(
            &mut admitted.publication,
            policy,
            Some(&next),
            &next_queued,
        )?;
        assert_eq!(
            admitted
                .publication
                .state
                .previous_closed_intents
                .get(&f.agent),
            Some(&completed)
        );
        assert!(
            admitted
                .publication
                .state
                .consumed_grants
                .contains(&(f.agent.clone(), first.grant_sha256))
        );
        assert!(
            admitted
                .publication
                .state
                .consumed_grants
                .contains(&(f.agent.clone(), next.grant_sha256))
        );
        assert_eq!(admitted.publication.state.time_floor, NOW + 5);
        assert_eq!(
            admitted.publication.state.authority.checkpoint(),
            checkpoint
        );
        assert_eq!(admitted.permission_sha256, before_permission);
        let expected = projection(admitted);
        let attempts = f.publisher.cas_attempts();
        owner.anchor_release_intent(
            &mut admitted.publication,
            policy,
            Some(&next_queued),
            &next_queued,
        )?;
        assert_eq!(projection(admitted), expected);
        let reused = prepared(&f, policy, /*grant*/ 51, next_queued.generation + 1);
        assert!(matches!(
            owner.anchor_release_intent(&mut admitted.publication, policy, Some(&next_queued), &reused),
            Err(FleetRegistryError::Invalid(message))
                if message == "PQ release authority: release grant was already consumed in protected history"
        ));
        let invalid = advance(&next_queued, Phase::Prepared);
        assert!(matches!(
            owner.anchor_release_intent(&mut admitted.publication, policy, Some(&next_queued), &invalid),
            Err(FleetRegistryError::Invalid(message))
                if message == "PQ release authority: intent anchor transition is not authorized for this path"
        ));
        assert!(matches!(
            owner.anchor_release_intent(
                &mut admitted.publication,
                policy,
                Some(&next),
                &next_queued
            ),
            Err(FleetRegistryError::ReleaseAuthorityRollback)
        ));
        assert_eq!(projection(admitted), expected);
        assert_eq!(f.publisher.cas_attempts(), attempts);
        expected
    };
    drop(guard);
    // Reopen through the ordinary loader, which must rebuild all M15 history.
    let cold =
        FleetRegistry::open_existing_with_release_authority(f.root.clone(), f.publisher.config())?;
    let cold_guard = cold.admit_release(&f.agent, &id)?;
    let (_, cold_use) = cold_guard
        .authority
        .as_ref()
        .ok_or("missing cold PQ owner")?;
    assert_eq!(projection(cold_use), expected);
    Ok(())
}

#[test]
fn held_intent_append_rejects_local_and_signed_frontier_drift_before_cas() -> QualificationResult<()>
{
    let (f, id, policy) = setup()?;
    let next = prepared(&f, policy, /*grant*/ 53, /*generation*/ 1);
    let mut guard = held(&f, &id)?;
    let (owner, admitted) = guard.authority.as_mut().ok_or("missing actual PQ owner")?;
    let expected = projection(admitted);
    let bytes = std::fs::read(f.journal())?;
    let original = f.publisher.frontier()?.ok_or("missing frontier")?;
    let attempts = f.publisher.cas_attempts();
    let mut changed = bytes.clone();
    changed.push(b' ');
    std::fs::write(f.journal(), &changed)?;
    std::fs::File::open(f.journal())?.sync_all()?;
    assert!(matches!(
        owner.anchor_release_intent(
            &mut admitted.publication,
            policy,
            /*expected*/ None,
            &next
        ),
        Err(FleetRegistryError::ReleaseAuthorityRollback)
    ));
    assert_eq!(projection(admitted), expected);
    std::fs::write(f.journal(), &bytes)?;
    std::fs::File::open(f.journal())?.sync_all()?;
    for field in 0..3 {
        let mut changed = original;
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
            owner.anchor_release_intent(
                &mut admitted.publication,
                policy,
                /*expected*/ None,
                &next
            ),
            Err(FleetRegistryError::ReleaseAuthorityRollback)
        ));
        assert_eq!(projection(admitted), expected);
    }
    assert_eq!(f.publisher.cas_attempts(), attempts);
    assert_eq!(std::fs::read(f.journal())?, bytes);
    assert!(!f.journal().with_file_name("attempt.v1.json").exists());
    Ok(())
}

#[test]
fn held_idempotent_intent_still_requires_current_policy_and_exact_window() -> QualificationResult<()>
{
    let (f, id, policy) = setup()?;
    let next = prepared(&f, policy, /*grant*/ 54, /*generation*/ 1);
    let mut guard = f
        .registry
        .admit_release(&f.agent, &id)?
        .with_verified_decision_window(NOW * 1000, (NOW + 1) * 1000)?;
    let (owner, admitted) = guard.authority.as_mut().ok_or("missing actual PQ owner")?;
    owner.anchor_release_intent(
        &mut admitted.publication,
        policy,
        /*expected*/ None,
        &next,
    )?;
    let expected = projection(admitted);
    let attempts = f.publisher.cas_attempts();
    f.publisher.advance_clock_to(NOW + 1);
    assert!(matches!(
        owner.anchor_release_intent(&mut admitted.publication, policy, Some(&next), &next),
        Err(FleetRegistryError::Invalid(message))
            if message == "PQ release authority: verified decision is outside its exact validity window"
    ));
    f.publisher.advance_clock_to(NOW + 60);
    assert!(matches!(
        owner.anchor_release_intent(&mut admitted.publication, policy, Some(&next), &next),
        Err(FleetRegistryError::Invalid(message))
            if message.starts_with("PQ release authority: M15 intent policy rejected:")
    ));
    assert_eq!(projection(admitted), expected);
    assert_eq!(f.publisher.cas_attempts(), attempts);
    Ok(())
}

#[test]
fn held_intent_post_cas_clock_regression_fences_without_installing_new_state()
-> QualificationResult<()> {
    let (f, id, policy) = setup()?;
    let next = prepared(&f, policy, /*grant*/ 55, /*generation*/ 1);
    let mut guard = held(&f, &id)?;
    let (owner, admitted) = guard.authority.as_mut().ok_or("missing actual PQ owner")?;
    let expected = projection(admitted);
    let attempts = f.publisher.cas_attempts();
    // Initial snapshot, initial window and pre-CAS read remain valid; the
    // actual post-publication signed clock is behind the new entry's floor.
    f.publisher
        .advance_clock_after_reads(/*successful_reads*/ 3, NOW - 1)?;
    assert!(
        owner
            .anchor_release_intent(
                &mut admitted.publication,
                policy,
                /*expected*/ None,
                &next
            )
            .is_err()
    );
    assert_eq!(f.publisher.cas_attempts(), attempts + 1);
    assert_eq!(projection(admitted), expected);
    assert!(owner.fenced.load(Ordering::Acquire));
    f.publisher.advance_clock_to(NOW);
    assert!(matches!(
        owner.intent_anchor_held(&admitted.publication, &f.agent),
        Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
    ));
    assert!(owner.recheck(&admitted.publication).is_err());
    drop(guard);
    let cold =
        FleetRegistry::open_existing_with_release_authority(f.root.clone(), f.publisher.config())?;
    assert_eq!(cold.release_intent_anchor(&f.agent)?, Some(next));
    assert_eq!(f.publisher.cas_attempts(), attempts + 1);
    Ok(())
}

#[test]
fn held_intent_post_cas_unavailable_read_fences_without_installing_new_state()
-> QualificationResult<()> {
    let (f, id, policy) = setup()?;
    let next = prepared(&f, policy, /*grant*/ 56, /*generation*/ 1);
    let mut guard = held(&f, &id)?;
    let (owner, admitted) = guard.authority.as_mut().ok_or("missing actual PQ owner")?;
    let expected = projection(admitted);
    let attempts = f.publisher.cas_attempts();
    f.publisher
        .trust
        .cas_mode
        .store(AFTER_CAS_LOAD_UNAVAILABLE, Ordering::Release);
    assert!(
        owner
            .anchor_release_intent(
                &mut admitted.publication,
                policy,
                /*expected*/ None,
                &next
            )
            .is_err()
    );
    assert_eq!(f.publisher.cas_attempts(), attempts + 1);
    assert_eq!(projection(admitted), expected);
    assert!(owner.fenced.load(Ordering::Acquire));
    assert!(matches!(
        owner.intent_anchor_held(&admitted.publication, &f.agent),
        Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
    ));
    drop(guard);
    let cold =
        FleetRegistry::open_existing_with_release_authority(f.root.clone(), f.publisher.config())?;
    assert_eq!(cold.release_intent_anchor(&f.agent)?, Some(next));
    assert_eq!(f.publisher.cas_attempts(), attempts + 1);
    Ok(())
}

#[test]
fn held_intent_post_cas_future_frontier_fences_and_cold_loader_rejects_local_state()
-> QualificationResult<()> {
    let (f, id, policy) = setup()?;
    let next = prepared(&f, policy, /*grant*/ 57, /*generation*/ 1);
    let mut guard = held(&f, &id)?;
    let (owner, admitted) = guard.authority.as_mut().ok_or("missing actual PQ owner")?;
    let expected = projection(admitted);
    let attempts = f.publisher.cas_attempts();
    f.publisher
        .trust
        .cas_mode
        .store(AFTER_CAS_FRONTIER_DRIFT, Ordering::Release);
    assert!(matches!(
        owner.anchor_release_intent(
            &mut admitted.publication,
            policy,
            /*expected*/ None,
            &next
        ),
        Err(FleetRegistryError::ReleaseAuthorityRollback)
    ));
    assert_eq!(projection(admitted), expected);
    assert!(owner.fenced.load(Ordering::Acquire));
    assert!(owner.recheck(&admitted.publication).is_err());
    drop(guard);
    assert!(
        FleetRegistry::open_existing_with_release_authority(f.root.clone(), f.publisher.config())
            .is_err()
    );
    assert_eq!(f.publisher.cas_attempts(), attempts + 1);
    Ok(())
}
