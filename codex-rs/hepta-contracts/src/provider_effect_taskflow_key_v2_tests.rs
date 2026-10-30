use std::collections::BTreeSet;

use super::ProviderEffectBindingError;
use super::ProviderEffectKey;
use crate::AgentId;
use crate::ProviderEffectAck;
use crate::ProviderEffectAckStatus;
use crate::ProviderEffectIntent;
use crate::Sha256Digest;
use pretty_assertions::assert_eq;

fn owner() -> AgentId {
    AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("durable owner")
}

#[test]
fn taskflow_v2_separates_legacy_colon_collision_without_changing_old_keys() {
    let owner = owner();
    let first = ("run:part", "step");
    let second = ("run", "part:step");
    let legacy = |(run, step)| {
        ProviderEffectKey::for_logical_effect("provider", &format!("taskflow:{run}:{step}"))
            .expect("existing logical key")
    };
    // Existing persisted keys are still parseable and retain their old bytes.
    // Only an owner with no earlier operation may select the new derivation.
    assert_eq!(legacy(first), legacy(second));
    assert_eq!(
        ProviderEffectKey::parse(legacy(first).as_str()).expect("legacy key parses"),
        legacy(first)
    );
    let first_v2 = ProviderEffectKey::for_taskflow_v2("provider", &owner, first.0, first.1)
        .expect("first new logical effect");
    let second_v2 = ProviderEffectKey::for_taskflow_v2("provider", &owner, second.0, second.1)
        .expect("second new logical effect");
    assert_ne!(first_v2, second_v2);
    assert_ne!(first_v2, legacy(first));
    assert_ne!(
        first_v2,
        ProviderEffectKey::for_operation("provider", first.0, first.1)
            .expect("separate synchronous operation domain")
    );
}

#[test]
fn taskflow_v2_preserves_field_boundaries_and_exact_payload_conflict() {
    let owner = owner();
    let key = ProviderEffectKey::for_taskflow_v2("provider", &owner, "run", "step")
        .expect("TaskFlow key");
    let mut observed = BTreeSet::from([key.clone()]);
    for changed in [
        ("provider:run", "step", "tail"),
        ("provider", "run:step", "tail"),
        ("provider", "run", "step:tail"),
        ("provider", "step", "run"),
    ] {
        assert!(
            observed.insert(
                ProviderEffectKey::for_taskflow_v2(changed.0, &owner, changed.1, changed.2)
                    .expect("separate fields")
            )
        );
    }
    let original = ProviderEffectIntent::new(key.clone(), Sha256Digest::for_bytes(b"original"));
    let changed = ProviderEffectIntent::new(key.clone(), Sha256Digest::for_bytes(b"changed"));
    let ack = ProviderEffectAck::new(
        key,
        original.payload_sha256.clone(),
        Sha256Digest::for_bytes(b"provider-operation"),
        ProviderEffectAckStatus::Completed,
    );
    assert_eq!(ack.validate_for(&original), Ok(()));
    assert_eq!(
        ack.validate_for(&changed),
        Err(ProviderEffectBindingError::PayloadMismatch)
    );
    let restored: ProviderEffectAck =
        serde_json::from_slice(&serde_json::to_vec(&ack).expect("encode ACK")).expect("decode ACK");
    assert_eq!(restored, ack);
}

#[test]
fn taskflow_v2_separates_owners_with_the_same_provider_run_and_step() {
    let first_owner = owner();
    let second_owner =
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13").expect("second durable owner");
    let first = ProviderEffectKey::for_taskflow_v2("provider", &first_owner, "run", "step")
        .expect("first owner effect");
    let second = ProviderEffectKey::for_taskflow_v2("provider", &second_owner, "run", "step")
        .expect("second owner effect");
    assert_ne!(first, second);
    assert_eq!(
        first,
        ProviderEffectKey::for_taskflow_v2("provider", &first_owner, "run", "step")
            .expect("same logical effect")
    );
}

#[test]
fn taskflow_v2_rejects_missing_identity_fields() {
    let owner = owner();
    for (scope, run, step, label) in [
        (" ", "run", "step", "provider scope"),
        ("provider", "", "step", "run id"),
        ("provider", "run", "\t", "step id"),
    ] {
        assert_eq!(
            ProviderEffectKey::for_taskflow_v2(scope, &owner, run, step),
            Err(ProviderEffectBindingError::EmptyField(label))
        );
    }
}
