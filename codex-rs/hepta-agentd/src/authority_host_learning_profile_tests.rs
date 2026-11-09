//! Synthetic iteration metadata with actual profile and Root CAS code.
//! Qualification here grants no production role, training or evaluation claim.

use super::*;
use crate::learning_iteration_checkpoint::learning_test_support::fixture;
use crate::learning_iteration_checkpoint::learning_test_support::record_experience;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

#[test]
fn learning_profile_requires_same_agent_and_nonzero_writer_pin() -> anyhow::Result<()> {
    let (_directory, identity, coordinator) = fixture()?;
    let initial = coordinator.snapshot();
    assert!(
        HostAuthorityLearningProfileV1::new(
            &identity,
            [7; 32],
            initial.request.clone(),
            initial.owners.clone(),
        )
        .is_ok()
    );
    assert!(
        HostAuthorityLearningProfileV1::new(
            &identity,
            [0; 32],
            initial.request.clone(),
            initial.owners.clone(),
        )
        .is_err()
    );
    let mut foreign = initial.request.clone();
    foreign.agent_id = StableId::new("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13")?;
    assert!(
        HostAuthorityLearningProfileV1::new(&identity, [7; 32], foreign, initial.owners.clone(),)
            .is_err()
    );
    Ok(())
}

#[test]
fn learning_profile_roundtrip_retains_exact_scope_and_original_writer() -> anyhow::Result<()> {
    let (_directory, identity, coordinator) = fixture()?;
    let initial = coordinator.snapshot();
    let writer = Digest32::from_array([7; 32]).to_string();
    let profile = HostAuthorityLearningProfileV1::new(
        &identity,
        [7; 32],
        initial.request.clone(),
        initial.owners.clone(),
    )?;
    let encoded = serde_json::to_vec(&profile)?;
    let recovered: HostAuthorityLearningProfileV1 = serde_json::from_slice(&encoded)?;
    assert_eq!(recovered.require_binding(&identity, &writer)?, *initial);
    assert_eq!(recovered.encoded_initial(), profile.encoded_initial());
    assert!(
        recovered
            .require_binding(&identity, &Digest32::from_array([8; 32]).to_string())
            .is_err()
    );
    let mut successor = identity.clone();
    successor.spawn_generation += 1;
    assert!(recovered.require_binding(&successor, &writer).is_err());
    let mut other_workspace = identity.clone();
    other_workspace.workspace = identity.workspace.join("other");
    assert!(
        recovered
            .require_binding(&other_workspace, &writer)
            .is_err()
    );
    Ok(())
}

#[test]
fn learning_profile_refuses_a_progress_checkpoint_as_initial_registration() -> anyhow::Result<()> {
    let (_directory, identity, mut coordinator) = fixture()?;
    let initial = coordinator.snapshot().clone();
    let mut profile =
        HostAuthorityLearningProfileV1::new(&identity, [7; 32], initial.request, initial.owners)?;
    record_experience(&mut coordinator)?;
    profile.initial_snapshot = STANDARD_NO_PAD.encode(codec::encode(coordinator.snapshot())?);
    assert!(
        profile
            .require_binding(&identity, &Digest32::from_array([7; 32]).to_string())
            .is_err()
    );
    Ok(())
}

#[test]
fn learning_profile_refuses_unknown_storage_fields_and_incompatible_schema() -> anyhow::Result<()> {
    let (_directory, identity, coordinator) = fixture()?;
    let initial = coordinator.snapshot();
    let mut profile = HostAuthorityLearningProfileV1::new(
        &identity,
        [7; 32],
        initial.request.clone(),
        initial.owners.clone(),
    )?;
    let mut encoded = serde_json::to_value(&profile)?;
    encoded["state_dir"] = serde_json::json!("/unregistered/learning");
    assert!(serde_json::from_value::<HostAuthorityLearningProfileV1>(encoded).is_err());
    profile.schema_version += 1;
    assert!(
        profile
            .require_binding(&identity, &Digest32::from_array([7; 32]).to_string())
            .is_err()
    );
    Ok(())
}

#[test]
fn scoped_learning_profile_roundtrips_and_refuses_scope_substitution() -> anyhow::Result<()> {
    let (_directory, identity, coordinator) = fixture()?;
    let initial = coordinator.snapshot();
    let writer = Digest32::from_array([7; 32]).to_string();
    let rule = Digest32::of_bytes(b"frozen-rule");
    for scope in [LearningUpdateScopeV2::Cell, LearningUpdateScopeV2::Organ] {
        let profile = HostAuthorityLearningProfileV1::new_scoped_v2(
            &identity,
            [7; 32],
            initial.request.clone(),
            initial.owners.clone(),
            scope,
            rule,
        )?;
        let expected =
            FrozenLearningScopeV2::freeze(&initial.request, &initial.owners, scope, rule)?;
        let encoded = serde_json::to_value(&profile)?;
        let roundtrip: HostAuthorityLearningProfileV1 = serde_json::from_value(encoded.clone())?;
        assert_eq!(roundtrip.require_binding(&identity, &writer)?, *initial);
        assert_eq!(roundtrip.frozen_scope(initial)?, Some(expected));
        for mutation in 0..6 {
            let mut changed = encoded.clone();
            match mutation {
                0 => changed["schema_version"] = serde_json::json!(1),
                1 => changed["update_scope"] = serde_json::Value::Null,
                2 => {
                    changed["update_scope"]["scope"] =
                        serde_json::json!(if scope == LearningUpdateScopeV2::Cell {
                            "organ"
                        } else {
                            "cell"
                        })
                }
                3 => {
                    changed["update_scope"]["update_rule"] =
                        serde_json::json!(Digest32::of_bytes(b"other-rule").to_string())
                }
                4 => {
                    changed["update_scope"]["binding"] =
                        serde_json::json!(Digest32::of_bytes(b"other-binding").to_string())
                }
                5 => changed["update_scope"]["scope"] = serde_json::json!("base_release"),
                _ => unreachable!(),
            }
            let changed: HostAuthorityLearningProfileV1 = serde_json::from_value(changed)?;
            assert!(
                changed.require_binding(&identity, &writer).is_err(),
                "mutation {mutation}"
            );
        }
    }
    assert!(
        HostAuthorityLearningProfileV1::new_scoped_v2(
            &identity,
            [7; 32],
            initial.request.clone(),
            initial.owners.clone(),
            LearningUpdateScopeV2::BaseRelease,
            rule,
        )
        .is_err()
    );
    Ok(())
}
