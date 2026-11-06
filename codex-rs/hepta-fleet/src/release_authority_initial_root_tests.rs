//! The prepared initial root never substitutes for replay or current ownership.

use std::sync::Arc;

use pretty_assertions::assert_eq;

use super::ReleaseAuthority;
use crate::FleetRegistryError;
use crate::QualificationResult;
use crate::ReleaseId;
use crate::release_authority_state::Journal;
use crate::release_authority_state::JournalEntry;
use crate::release_authority_tests::Fixture;
use crate::release_authority_wire::AuthorityEventRecord;
use crate::release_registry::ReleaseMode;

fn prepared_owner() -> QualificationResult<(Fixture, ReleaseId, Arc<ReleaseAuthority>)> {
    let mut fixture = Fixture::new()?;
    let id = fixture.install("prepared-initial-root")?;
    fixture.allow(&id)?;
    let owner = match &fixture.registry.release_authority {
        ReleaseMode::Pq(owner) => Arc::clone(owner),
        _ => return Err("expected the real PQ release owner".into()),
    };
    Ok((fixture, id, owner))
}

#[test]
fn prepared_root_replay_still_binds_complete_root_and_each_initialization_time()
-> QualificationResult<()> {
    let (fixture, id, owner) = prepared_owner()?;
    let original: Journal = serde_json::from_slice(&std::fs::read(fixture.journal())?)?;
    let frontier = fixture
        .publisher
        .frontier()?
        .ok_or("missing signed frontier")?;
    let material = owner
        .initial_root_material
        .get()
        .ok_or("missing preparation")?;
    let state = original
        .clone()
        .rebuild(&owner.config, frontier, &owner.initial_root_material)?;
    assert_eq!(state.authority.checkpoint(), frontier.checkpoint_sha256);

    let mut changed = original.clone();
    changed.initial_root.expires_at += 1;
    assert!(matches!(
        changed.rebuild(&owner.config, frontier, &owner.initial_root_material),
        Err(FleetRegistryError::Invalid(message)) if message.contains("RootPin")
    ));

    let mut changed = original.clone();
    changed.initialized_at = changed.initial_root.expires_at;
    assert!(matches!(
        changed.rebuild(&owner.config, frontier, &owner.initial_root_material),
        Err(FleetRegistryError::Invalid(message)) if message.contains("InvalidRoot")
    ));

    let replayed = original.rebuild(&owner.config, frontier, &owner.initial_root_material)?;
    assert_eq!(
        (
            replayed.authority.checkpoint(),
            replayed.time_floor,
            replayed.admissions
        ),
        (
            state.authority.checkpoint(),
            state.time_floor,
            state.admissions
        )
    );
    assert!(std::ptr::eq(
        material,
        owner
            .initial_root_material
            .get()
            .ok_or("lost preparation")?
    ));
    assert!(
        fixture
            .registry
            .resolve_release(&fixture.agent, &id)
            .is_ok()
    );
    Ok(())
}

#[test]
fn prepared_root_replay_reverifies_the_actual_signed_history() -> QualificationResult<()> {
    let (mut fixture, _, owner) = prepared_owner()?;
    let id = fixture.install("prepared-second-publication")?;
    fixture.allow(&id)?;
    let original: Journal = serde_json::from_slice(&std::fs::read(fixture.journal())?)?;
    let frontier = fixture
        .publisher
        .frontier()?
        .ok_or("missing signed frontier")?;
    let _ = original
        .clone()
        .rebuild(&owner.config, frontier, &owner.initial_root_material)?;

    // Alter the first, historical publication so rejection must come from
    // its actual quorum, not the latest bundle's signature-digest binding.
    let mut changed = original.clone();
    let signatures = changed
        .entries
        .iter_mut()
        .find_map(|entry| {
            if let JournalEntry::Authority {
                event: AuthorityEventRecord::ReleaseSet { signatures, .. },
            } = entry
            {
                Some(signatures)
            } else {
                None
            }
        })
        .ok_or("missing actual signed release")?;
    signatures[0].signature[0] ^= 1;
    assert!(matches!(
        changed.rebuild(&owner.config, frontier, &owner.initial_root_material),
        Err(FleetRegistryError::Invalid(message))
            if message.contains("M15 recovery publication rejected:")
                && message.contains("SignatureRejected")
    ));

    let mut missing = original.clone();
    let signatures = missing
        .entries
        .iter_mut()
        .find_map(|entry| {
            if let JournalEntry::Authority {
                event: AuthorityEventRecord::ReleaseSet { signatures, .. },
            } = entry
            {
                Some(signatures)
            } else {
                None
            }
        })
        .ok_or("missing actual signed release")?;
    signatures.clear();
    assert!(matches!(
        missing.rebuild(&owner.config, frontier, &owner.initial_root_material),
        Err(FleetRegistryError::Invalid(message))
            if message.contains("M15 recovery publication rejected:")
                && message.contains("InsufficientSignatures")
    ));

    let replayed = original.rebuild(&owner.config, frontier, &owner.initial_root_material)?;
    assert_eq!(replayed.authority.checkpoint(), frontier.checkpoint_sha256);
    assert!(
        fixture
            .registry
            .resolve_release(&fixture.agent, &id)
            .is_ok()
    );
    Ok(())
}

#[test]
fn prepared_root_does_not_reuse_current_authority_after_revocation_or_local_rollback()
-> QualificationResult<()> {
    let (fixture, id, owner) = prepared_owner()?;
    let material = owner
        .initial_root_material
        .get()
        .ok_or("missing preparation")?;
    let old = std::fs::read(fixture.journal())?;
    assert!(
        fixture
            .registry
            .resolve_release(&fixture.agent, &id)
            .is_ok()
    );
    fixture.registry.revoke_release(&fixture.agent, &id)?;
    assert!(matches!(
        fixture.registry.resolve_release(&fixture.agent, &id),
        Err(FleetRegistryError::ReleaseRevoked { .. })
    ));
    let retained = (
        fixture.publisher.frontier()?,
        fixture.publisher.cas_attempts(),
    );
    std::fs::write(fixture.journal(), &old)?;
    std::fs::File::open(fixture.journal())?.sync_all()?;
    assert!(matches!(
        fixture.registry.resolve_release(&fixture.agent, &id),
        Err(FleetRegistryError::ReleaseAuthorityRollback)
    ));
    assert_eq!(
        (
            fixture.publisher.frontier()?,
            fixture.publisher.cas_attempts(),
            std::fs::read(fixture.journal())?
        ),
        (retained.0, retained.1, old)
    );
    assert!(std::ptr::eq(
        material,
        owner
            .initial_root_material
            .get()
            .ok_or("lost preparation")?
    ));
    Ok(())
}
