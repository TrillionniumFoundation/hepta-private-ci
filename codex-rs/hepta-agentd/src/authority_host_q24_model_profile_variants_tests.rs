//! Strict wire/data compatibility tests; no Root or custody authority claimed.

use pretty_assertions::assert_eq;

use super::*;

#[test]
fn factory_legacy_wire_and_cross_spawn_rejection_are_unchanged() -> anyhow::Result<()> {
    let (_directory, identity, initial, scope, original) = super::super::tests::fixture()?;
    let proof = Digest32::of_bytes(b"original-writer").to_string();
    let bytes = serde_json::to_vec(&original)?;
    let live: LiveFactoryProfile = serde_json::from_slice(&bytes)?;
    let retained: ReservedFactoryProfile = serde_json::from_slice(&bytes)?;
    assert_eq!(live, LiveFactoryProfile::LegacyV1(original.clone()));
    assert_eq!(retained, ReservedFactoryProfile::LegacyV1(original.clone()));
    assert_eq!(serde_json::to_vec(&live)?, bytes);
    assert_eq!(serde_json::to_vec(&retained)?, bytes);
    assert_eq!(live.reserved(), retained);
    live.require_context(&identity, &proof, &initial, &scope)?;
    let mut successor = identity.clone();
    successor.spawn_generation += 1;
    assert!(
        live.require_context(&successor, &proof, &initial, &scope)
            .is_err()
    );
    assert!(
        live.require_context(
            &identity,
            &Digest32::of_bytes(b"new-writer").to_string(),
            &initial,
            &scope
        )
        .is_err()
    );
    let mut relabeled = serde_json::to_value(&original)?;
    relabeled["schema_version"] = serde_json::json!(2);
    let relabeled: LiveFactoryProfile = serde_json::from_value(relabeled)?;
    assert!(
        relabeled
            .require_context(&identity, &proof, &initial, &scope)
            .is_err()
    );
    Ok(())
}

#[test]
fn factory_v2_transfers_live_admission_but_persists_only_original_reservation() -> anyhow::Result<()>
{
    let (_directory, identity, initial, scope, legacy) = super::super::tests::fixture()?;
    let reserved = DurableQ24ModelFactoryProfileV2::reserve_description(
        &initial,
        &scope,
        legacy.journal,
        legacy.witness,
        legacy.witness_domain.parse()?,
        legacy.local_policy_digest.parse()?,
        Generation::new(identity.spawn_generation)?,
    )?;
    let mut successor = identity.clone();
    successor.spawn_generation += 1;
    let proof = Digest32::of_bytes(b"new-writer").to_string();
    let live = LiveFactoryProfile::SessionV2(LiveQ24ModelFactoryProfileV2::admit_current_session(
        &successor,
        &proof,
        &initial,
        &scope,
        reserved.clone(),
    )?);
    live.require_context(&successor, &proof, &initial, &scope)?;
    assert_eq!(
        live.reserved(),
        ReservedFactoryProfile::DurableV2(reserved.clone())
    );
    assert_eq!(
        live.witness_generation(successor.spawn_generation)?.get(),
        identity.spawn_generation
    );
    assert_eq!(live.witness_binding(), reserved.durable_binding());
    assert_ne!(live.witness_binding(), live.binding());
    let bytes = serde_json::to_vec(&live)?;
    assert_eq!(serde_json::from_slice::<LiveFactoryProfile>(&bytes)?, live);
    assert!(serde_json::from_slice::<ReservedFactoryProfile>(&bytes).is_err());
    let persisted = serde_json::to_vec(&live.reserved())?;
    assert!(serde_json::from_slice::<LiveFactoryProfile>(&persisted).is_err());
    let value = serde_json::to_value(live.reserved())?;
    assert!(value.get("process_identity_digest").is_none());
    assert!(value.get("writer_proof_digest").is_none());
    assert!(serde_json::from_slice::<HostAuthorityQ24ModelFactoryProfileV1>(&bytes).is_err());
    Ok(())
}
