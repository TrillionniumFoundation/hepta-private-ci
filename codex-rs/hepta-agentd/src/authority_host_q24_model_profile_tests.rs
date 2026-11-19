//! Synthetic descriptor contexts. These tests construct data, never a Root
//! capability, live writer, independent owner or ordinary completion receipt.

use super::*;
use crate::learning_iteration_checkpoint::learning_test_support;
use codex_hepta_learning_artifacts::LearningUpdateScopeV2;
use pretty_assertions::assert_eq;

pub(crate) fn fixture() -> anyhow::Result<(
    tempfile::TempDir,
    AgentdIdentity,
    LearningIterationSnapshotV1,
    FrozenLearningScopeV2,
    HostAuthorityQ24ModelFactoryProfileV1,
)> {
    let (directory, identity, coordinator) = learning_test_support::fixture()?;
    let initial = coordinator.snapshot().clone();
    let scope = FrozenLearningScopeV2::freeze(
        &initial.request,
        &initial.owners,
        LearningUpdateScopeV2::Cell,
        Digest32::of_bytes(b"original-update-rule"),
    )?;
    let profile = HostAuthorityQ24ModelFactoryProfileV1::new(
        &identity,
        &Digest32::of_bytes(b"original-writer").to_string(),
        &initial,
        &scope,
        FilePin {
            device: 1,
            inode: 2,
        },
        FilePin {
            device: 3,
            inode: 4,
        },
        Digest32::of_bytes(b"original-witness-domain"),
        Digest32::of_bytes(b"precommitted-policy"),
    )?;
    Ok((directory, identity, initial, scope, profile))
}

#[test]
fn factory_description_rejects_cross_operation_identity_scope_and_policy() -> anyhow::Result<()> {
    let (_directory, identity, initial, scope, profile) = fixture()?;
    let proof = Digest32::of_bytes(b"original-writer").to_string();
    profile.require_context(&identity, &proof, &initial, &scope)?;
    let restored: HostAuthorityQ24ModelFactoryProfileV1 =
        serde_json::from_slice(&serde_json::to_vec(&profile)?)?;
    assert_eq!(restored, profile);
    let mut foreign_identity = identity.clone();
    foreign_identity.spawn_generation += 1;
    assert!(
        profile
            .require_context(&foreign_identity, &proof, &initial, &scope)
            .is_err()
    );
    assert!(
        profile
            .require_context(
                &identity,
                &Digest32::of_bytes(b"other-writer").to_string(),
                &initial,
                &scope
            )
            .is_err()
    );
    let mut foreign_initial = initial.clone();
    foreign_initial.request.source_run_id = codex_hepta_types::StableId::new("other-run")?;
    assert!(
        profile
            .require_context(&identity, &proof, &foreign_initial, &scope)
            .is_err()
    );
    let foreign_scope = FrozenLearningScopeV2::freeze(
        &initial.request,
        &initial.owners,
        LearningUpdateScopeV2::Cell,
        Digest32::of_bytes(b"other-update-rule"),
    )?;
    assert!(
        profile
            .require_context(&identity, &proof, &initial, &foreign_scope)
            .is_err()
    );
    assert!(
        profile
            .require_local_policy(Digest32::of_bytes(b"chosen-after-evaluation"))
            .is_err()
    );
    profile.require_local_policy(Digest32::of_bytes(b"precommitted-policy"))?;
    Ok(())
}

#[test]
fn factory_description_rejects_changed_purpose_epoch_and_reserved_objects() -> anyhow::Result<()> {
    let (_directory, identity, initial, scope, profile) = fixture()?;
    let proof = Digest32::of_bytes(b"original-writer").to_string();
    for field in [
        "schema_version",
        "purpose",
        "registry_epoch",
        "factory_binding",
        "journal_slot_binding",
        "witness_enrollment_binding",
        "local_policy_digest",
    ] {
        let mut value = serde_json::to_value(&profile)?;
        value[field] = match field {
            "schema_version" | "registry_epoch" => serde_json::json!(2),
            "purpose" => serde_json::json!(crate::HOST_AUTHORITY_LEARNING_BOOTSTRAP_V2),
            _ => serde_json::json!(Digest32::of_bytes(b"substituted").to_string()),
        };
        let substituted: HostAuthorityQ24ModelFactoryProfileV1 = serde_json::from_value(value)?;
        assert!(
            substituted
                .require_context(&identity, &proof, &initial, &scope)
                .is_err(),
            "{field}"
        );
    }
    let mut value = serde_json::to_value(&profile)?;
    value["journal"]["inode"] = serde_json::json!(99);
    let substituted: HostAuthorityQ24ModelFactoryProfileV1 = serde_json::from_value(value)?;
    assert!(
        substituted
            .require_context(&identity, &proof, &initial, &scope)
            .is_err()
    );
    let mut value = serde_json::to_value(&profile)?;
    value["writable_path"] = serde_json::json!("/not-an-owner");
    assert!(serde_json::from_value::<HostAuthorityQ24ModelFactoryProfileV1>(value).is_err());
    Ok(())
}

#[test]
fn factory_profile_cannot_upgrade_legacy_or_organ_learning() -> anyhow::Result<()> {
    let (_directory, identity, initial, _, _) = fixture()?;
    let legacy = HostAuthorityLearningProfileV1::new(
        &identity,
        [7; 32],
        initial.request.clone(),
        initial.owners.clone(),
    )?;
    assert!(legacy.require_cell_scope(&initial).is_err());
    let organ = HostAuthorityLearningProfileV1::new_scoped_v2(
        &identity,
        [7; 32],
        initial.request.clone(),
        initial.owners.clone(),
        LearningUpdateScopeV2::Organ,
        Digest32::of_bytes(b"organ-rule"),
    )?;
    assert!(organ.require_cell_scope(&initial).is_err());
    Ok(())
}
