//! Description tests only: synthetic process/proof data does not establish
//! a live Root registration, file custody or a successful cold owner recovery.

use pretty_assertions::assert_eq;

use super::*;

fn fixture() -> anyhow::Result<(
    tempfile::TempDir,
    AgentdIdentity,
    LearningIterationSnapshotV1,
    FrozenLearningScopeV2,
    DurableQ24ModelFactoryProfileV2,
)> {
    let (directory, identity, initial, scope, legacy) = super::super::tests::fixture()?;
    let reservation = DurableQ24ModelFactoryProfileV2::reserve_description(
        &initial,
        &scope,
        legacy.journal,
        legacy.witness,
        legacy.witness_domain.parse()?,
        legacy.local_policy_digest.parse()?,
        Generation::new(identity.spawn_generation)?,
    )?;
    Ok((directory, identity, initial, scope, reservation))
}

#[test]
fn v2_description_keeps_original_generation_across_distinct_live_admissions() -> anyhow::Result<()>
{
    let (_directory, identity, initial, scope, reservation) = fixture()?;
    let proof = Digest32::of_bytes(b"first-actual-proof-description").to_string();
    let first = LiveQ24ModelFactoryProfileV2::admit_current_session(
        &identity,
        &proof,
        &initial,
        &scope,
        reservation.clone(),
    )?;
    first.require_live_context(&identity, &proof, &initial, &scope)?;
    let mut successor = identity.clone();
    successor.spawn_generation += 1;
    let next_proof = Digest32::of_bytes(b"next-actual-proof-description").to_string();
    let next = LiveQ24ModelFactoryProfileV2::admit_current_session(
        &successor,
        &next_proof,
        &initial,
        &scope,
        reservation.clone(),
    )?;
    next.require_live_context(&successor, &next_proof, &initial, &scope)?;
    assert_eq!(first.reservation, next.reservation);
    assert_eq!(next.reservation, reservation);
    assert_eq!(
        next.reservation.original_generation()?.get(),
        identity.spawn_generation
    );
    assert_ne!(first.admission_binding(), next.admission_binding());
    assert!(
        first
            .require_live_context(&successor, &next_proof, &initial, &scope)
            .is_err()
    );
    assert!(
        next.require_live_context(&identity, &proof, &initial, &scope)
            .is_err()
    );
    assert!(
        next.require_live_context(&successor, &proof, &initial, &scope)
            .is_err()
    );
    let restored: LiveQ24ModelFactoryProfileV2 =
        serde_json::from_slice(&serde_json::to_vec(&next)?)?;
    assert_eq!(restored, next);
    Ok(())
}

#[test]
fn v2_description_rejects_original_custody_scope_and_policy_substitution() -> anyhow::Result<()> {
    let (_directory, identity, initial, scope, reservation) = fixture()?;
    let proof = Digest32::of_bytes(b"proof").to_string();
    let profile = LiveQ24ModelFactoryProfileV2::admit_current_session(
        &identity,
        &proof,
        &initial,
        &scope,
        reservation,
    )?;
    for field in [
        "schema_version",
        "purpose",
        "registry_epoch",
        "witness_generation",
        "reservation_binding",
        "journal_slot_binding",
        "witness_enrollment_binding",
        "witness_domain",
        "local_policy_digest",
        "scope_binding",
        "initial_head",
    ] {
        let mut value = serde_json::to_value(&profile)?;
        value["reservation"][field] = match field {
            "schema_version" | "registry_epoch" => serde_json::json!(99),
            "witness_generation" => serde_json::json!(identity.spawn_generation + 1),
            "purpose" => serde_json::json!(PURPOSE),
            _ => serde_json::json!(Digest32::of_bytes(b"substituted").to_string()),
        };
        let changed: LiveQ24ModelFactoryProfileV2 = serde_json::from_value(value)?;
        assert!(
            changed
                .require_live_context(&identity, &proof, &initial, &scope)
                .is_err(),
            "{field}"
        );
    }
    for file in ["journal", "witness"] {
        let mut value = serde_json::to_value(&profile)?;
        value["reservation"][file]["inode"] = serde_json::json!(99);
        let changed: LiveQ24ModelFactoryProfileV2 = serde_json::from_value(value)?;
        assert!(
            changed
                .require_live_context(&identity, &proof, &initial, &scope)
                .is_err(),
            "{file}"
        );
    }
    let mut different = initial.clone();
    different.request.source_run_id = codex_hepta_types::StableId::new("different-source-run")?;
    assert!(
        profile
            .require_live_context(&identity, &proof, &different, &scope)
            .is_err()
    );
    Ok(())
}

#[test]
fn v2_description_rejects_changed_live_binding_and_unknown_authority_fields() -> anyhow::Result<()>
{
    let (_directory, identity, initial, scope, reservation) = fixture()?;
    let proof = Digest32::of_bytes(b"proof").to_string();
    let profile = LiveQ24ModelFactoryProfileV2::admit_current_session(
        &identity,
        &proof,
        &initial,
        &scope,
        reservation,
    )?;
    for field in [
        "schema_version",
        "purpose",
        "process_identity_digest",
        "writer_proof_digest",
        "factory_binding",
    ] {
        let mut value = serde_json::to_value(&profile)?;
        value[field] = match field {
            "schema_version" => serde_json::json!(1),
            "purpose" => serde_json::json!(PURPOSE),
            _ => serde_json::json!(Digest32::of_bytes(b"changed").to_string()),
        };
        let changed: LiveQ24ModelFactoryProfileV2 = serde_json::from_value(value)?;
        assert!(
            changed
                .require_live_context(&identity, &proof, &initial, &scope)
                .is_err(),
            "{field}"
        );
    }
    let mut value = serde_json::to_value(&profile)?;
    value["writable_path"] = serde_json::json!("/untrusted");
    assert!(serde_json::from_value::<LiveQ24ModelFactoryProfileV2>(value).is_err());
    let mut value = serde_json::to_value(&profile)?;
    value["reservation"]["retired"] = serde_json::json!(true);
    assert!(serde_json::from_value::<LiveQ24ModelFactoryProfileV2>(value).is_err());
    Ok(())
}
