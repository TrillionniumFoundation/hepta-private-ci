//! Real publication owners retain only mathematical initial-root material.
//! Every observation below still enters the ordinary signed journal loader.
use std::sync::Arc;

use pretty_assertions::assert_eq;
use serde_json::Value;
use sha2::Digest;
use sha2::Sha256;
use trnm_release_bundle::pq_release::PqReleaseAuthorityV1;
use trnm_release_bundle::pq_release::PqReleaseErrorV1;
use trnm_release_bundle::pq_release::PqReleaseRoleV1;
use trnm_release_bundle::pq_release::PqReleaseRootV1;

use super::super::ReleaseAuthority;
use super::super::ReleaseUse;
use super::InitialRootMaterial;
use crate::FleetRegistry;
use crate::FleetRegistryError;
use crate::QualificationResult;
use crate::ReleaseId;
use crate::ReleaseIntentPhaseV1 as Phase;
use crate::ReleaseIntentWitnessKindV1 as WitnessKind;
use crate::release_authority_state::Admission;
use crate::release_authority_state::Journal;
use crate::release_authority_state::JournalEntry;
use crate::release_authority_tests::Fixture;
use crate::release_authority_wire::AuthorityEventRecord;
use crate::release_intent_anchor_tests::advance;
use crate::release_intent_anchor_tests::prepared;
use crate::release_intent_anchor_tests::queue;
use crate::release_intent_anchor_tests::setup;
use crate::release_intent_anchor_tests::witness;
use crate::release_qualification_trust::NOW;
use crate::release_registry::ReleaseMode;

#[path = "release_authority_initial_root_fault_tests.rs"]
mod faults;

fn owner(registry: &FleetRegistry) -> QualificationResult<Arc<ReleaseAuthority>> {
    match &registry.release_authority {
        ReleaseMode::Pq(owner) => Ok(Arc::clone(owner)),
        _ => Err("missing actual PQ publication owner".into()),
    }
}

fn projection(admitted: &ReleaseUse) -> Value {
    let state = &admitted.publication.state;
    let allowances = state
        .admissions
        .iter()
        .map(|(key, value)| match value {
            Admission::Allowed(digest) => (key, "allowed", digest),
            Admission::Revoked(digest) => (key, "revoked", digest),
        })
        .collect::<Vec<_>>();
    let roles = [
        PqReleaseRoleV1::NodeSoftware,
        PqReleaseRoleV1::ProtocolConfiguration,
        PqReleaseRoleV1::CellManifest,
        PqReleaseRoleV1::CellActivation,
    ]
    .map(|role| {
        (
            role as u8,
            state.authority.role_version(role),
            state.authority.current_content(role),
        )
    });
    serde_json::json!({
        "journal": &state.journal,
        "frontier": state.frontier,
        "held_frontier": admitted.publication.frontier,
        "checkpoint": state.authority.checkpoint(),
        "root_digest": state.authority.root_digest(),
        "root_generation": state.authority.root_generation(),
        "roles": roles,
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

fn observe(f: &Fixture, registry: &FleetRegistry, id: &ReleaseId) -> QualificationResult<Value> {
    let guard = registry.admit_release(&f.agent, id)?;
    let (_, admitted) = guard.authority.as_ref().ok_or("missing current PQ owner")?;
    Ok(projection(admitted))
}

fn write_synced(path: &std::path::Path, bytes: &[u8]) -> QualificationResult<()> {
    std::fs::write(path, bytes)?;
    std::fs::File::open(path)?.sync_all()?;
    Ok(())
}

#[test]
fn initial_root_slot_is_owner_bound_and_never_replaces_a_valid_other_root()
-> QualificationResult<()> {
    let (f, id, _) = setup()?;
    let original = observe(&f, &f.registry, &id)?;
    let first = owner(&f.registry)?;
    let cloned = f.registry.clone();
    assert!(Arc::ptr_eq(&first, &owner(&cloned)?));
    let material = first
        .initial_root_material
        .keys
        .get()
        .ok_or("unprepared root")?;
    let root = PqReleaseRootV1::try_from(&f.publisher.root)?;
    let pin = f.publisher.config().initial_root_sha256;
    assert!(material.matches_root(&root, pin));
    let empty = InitialRootMaterial::default();
    let mut malformed = root.clone();
    malformed.offline_root.threshold = 0;
    assert_eq!(
        empty.bootstrap(malformed, pin, NOW).err(),
        Some(PqReleaseErrorV1::InvalidThreshold)
    );
    assert!(empty.keys.get().is_none());
    empty.bootstrap(root.clone(), pin, NOW)?;
    let mut other = root.clone();
    other.expires_at -= 1;
    let other_pin = other.digest()?;
    assert!(PqReleaseAuthorityV1::bootstrap_pinned(other.clone(), other_pin, NOW).is_ok());
    assert_eq!(
        first
            .initial_root_material
            .bootstrap(other, other_pin, NOW)
            .err(),
        Some(PqReleaseErrorV1::RootPin)
    );
    assert_eq!(
        first
            .initial_root_material
            .bootstrap(root, [7; 32], NOW)
            .err(),
        Some(PqReleaseErrorV1::RootPin)
    );
    assert!(std::ptr::eq(
        material,
        first.initial_root_material.keys.get().ok_or("lost root")?
    ));
    assert_eq!(observe(&f, &cloned, &id)?, original);
    let cold =
        FleetRegistry::open_existing_with_release_authority(f.root.clone(), f.publisher.config())?;
    let second = owner(&cold)?;
    assert!(!Arc::ptr_eq(&first, &second));
    assert!(!std::ptr::eq(
        material,
        second
            .initial_root_material
            .keys
            .get()
            .ok_or("missing cold root")?
    ));
    assert_eq!(observe(&f, &cold, &id)?, original);
    Ok(())
}

#[test]
fn initial_root_warm_replay_matches_cold_after_rotation_and_complete_intent_history()
-> QualificationResult<()> {
    let (mut f, id, policy) = setup()?;
    let original = prepared(&f, policy, 101, 1);
    let queued = queue(&f, &id, policy, &original)?;
    let mut closed = advance(&queued, Phase::Committed);
    closed.terminal_witness = Some(witness(WitnessKind::CompletedReleaseCas, None));
    f.registry.record_intent_history(&queued, &closed)?;
    let same_owner = owner(&f.registry)?;
    let material = same_owner
        .initial_root_material
        .keys
        .get()
        .ok_or("unprepared root")?;
    let before = observe(&f, &f.registry, &id)?;
    f.publisher.rotate_publisher_root(&f.registry)?;
    assert!(f.registry.admit_release(&f.agent, &id).is_err());
    f.publisher
        .publish_member_ids(&f.registry, std::slice::from_ref(&id), NOW + 3600)?;
    f.publisher.publish_protocol_configuration(
        &f.registry,
        b"H7 anchor component policy",
        NOW + 60,
    )?;
    f.publisher.advance_clock_to(NOW + 5);
    let next = prepared(&f, policy, 102, closed.generation + 1);
    drop(
        f.registry
            .admit_protocol_configuration(policy)?
            .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
            .anchor_intent(Some(&closed), &next)?,
    );
    let next_queued = advance(&next, Phase::Queued);
    let guard = f
        .registry
        .admit_release(&f.agent, &id)?
        .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
        .anchor_intent(policy, Some(&next), &next_queued)?;
    let (_, admitted) = guard.authority.as_ref().ok_or("missing current owner")?;
    let state = &admitted.publication.state;
    assert_eq!(state.authority.root_generation(), 2);
    assert_eq!(state.intent_anchors.get(&f.agent), Some(&next_queued));
    assert_eq!(state.previous_closed_intents.get(&f.agent), Some(&closed));
    assert!(
        state
            .consumed_grants
            .contains(&(f.agent.clone(), original.grant_sha256))
    );
    assert!(
        state
            .consumed_grants
            .contains(&(f.agent.clone(), next.grant_sha256))
    );
    assert_eq!(state.time_floor, NOW + 5);
    let expected = projection(admitted);
    assert_ne!(expected["checkpoint"], before["checkpoint"]);
    assert_ne!(expected["permission_sha256"], before["permission_sha256"]);
    drop(guard);
    assert!(std::ptr::eq(
        material,
        same_owner
            .initial_root_material
            .keys
            .get()
            .ok_or("lost root")?
    ));
    assert_eq!(observe(&f, &f.registry, &id)?, expected);
    let cold =
        FleetRegistry::open_existing_with_release_authority(f.root.clone(), f.publisher.config())?;
    assert_eq!(observe(&f, &cold, &id)?, expected);
    Ok(())
}
