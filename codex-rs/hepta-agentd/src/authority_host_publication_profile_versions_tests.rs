//! Profile-data compatibility and substitution tests only. These do not
//! construct a Root owner or qualify an actual process restart.

use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use pretty_assertions::assert_eq;

use super::*;
use crate::neuron_generation_current::test_support::RECORDS;
use crate::neuron_generation_current::test_support::config;

fn profile(version: PublicationVersion) -> anyhow::Result<PublicationProfile> {
    let previous_config = config()?;
    let mut target_config = previous_config.clone();
    target_config
        .initial
        .scope
        .run_id
        .push_str("-publication-data-next");
    target_config.initial.generation += 1;
    let previous = CellGenerationOwnerBindingV1::new(&previous_config, RECORDS)?;
    let target = CellGenerationOwnerBindingV1::new(&target_config, RECORDS)?;
    let digest = |value: &str| Digest32::of_bytes(value.as_bytes()).to_string();
    let mut profile = PublicationProfile {
        purpose: version.purpose().into(),
        learning_operation: "publication-data-test".into(),
        initial: digest("initial"),
        scope: digest("scope"),
        writer: digest("original-writer"),
        identity: digest("original-process"),
        decision: digest("decision"),
        previous_files: digest("previous-files"),
        target_files: digest("target-files"),
        artifacts: ArtifactRegistrationPin {
            root: "/profile-data-only/artifacts".into(),
            trust: digest("artifact-trust"),
            storage: digest("storage"),
            retained_current: digest("current-floor"),
            withdrawal_floor: digest("withdrawal-floor"),
            selection: digest("selection"),
            selector_trust: digest("selector-trust"),
        },
        consumer_trust: digest("consumer-trust"),
        consumer_slot: RootPublicationFinalUseConsumerV1::Device,
        local_consumer: "/profile-data-only/device".into(),
        intent: UpdateIntent {
            operation_id: "publication-data-intent".into(),
            supersedes: None,
            previous,
            previous_checkpoint: [1; 32],
            previous_observation: [2; 32],
            target,
            genesis_checkpoint: [3; 32],
            selection: [4; 32],
            completion: crate::NeuronGenerationPredecessorCompletionV1::OwnerDrainedSameModel,
        },
        binding: String::new(),
    };
    profile.binding = profile.digest()?;
    Ok(profile)
}

#[test]
fn legacy_record_encoding_and_incarnation_equality_remain_exact() -> anyhow::Result<()> {
    let original = profile(PublicationVersion::LegacyV1)?;
    let reserved = ReservedPublicationProfile::retain_original(original.clone())?;
    assert_eq!(
        serde_json::to_vec(&reserved)?,
        serde_json::to_vec(&original)?
    );
    reserved.require_live_profile(&original)?;
    let mut changed = original.clone();
    changed.writer = Digest32::of_bytes(b"new-writer").to_string();
    changed.identity = Digest32::of_bytes(b"new-process").to_string();
    changed.binding = changed.digest()?;
    assert!(reserved.require_live_profile(&changed).is_err());
    assert!(
        reserved
            .original_for_version(PublicationVersion::DurableV2)
            .is_err()
    );
    Ok(())
}

#[test]
fn explicit_durable_record_retains_origin_while_checking_new_live_data() -> anyhow::Result<()> {
    let original = profile(PublicationVersion::DurableV2)?;
    let reserved = ReservedPublicationProfile::retain_original(original.clone())?;
    let before = serde_json::to_vec(&reserved)?;
    let reopened: ReservedPublicationProfile = serde_json::from_slice(&before)?;
    let mut live = original.clone();
    live.writer = Digest32::of_bytes(b"new-writer").to_string();
    live.identity = Digest32::of_bytes(b"new-process").to_string();
    live.binding = live.digest()?;
    reopened.require_live_profile(&live)?;
    assert_eq!(serde_json::to_vec(&reopened)?, before);
    assert_eq!(
        reopened.original_for_version(PublicationVersion::DurableV2)?,
        &original
    );
    assert!(
        reopened
            .original_for_version(PublicationVersion::LegacyV1)
            .is_err()
    );
    Ok(())
}

#[test]
fn live_rebinding_cannot_change_durable_decision_custody_or_intent() -> anyhow::Result<()> {
    let original = profile(PublicationVersion::DurableV2)?;
    let reserved = ReservedPublicationProfile::retain_original(original.clone())?;
    let mut value = serde_json::to_value(&original)?;
    // Every listed field remains well-typed after substitution; rejection is
    // an equality obligation, not a malformed-input parser shortcut.
    for pointer in [
        "/learning_operation",
        "/initial",
        "/scope",
        "/decision",
        "/previous_files",
        "/target_files",
        "/consumer_trust",
        "/local_consumer",
        "/artifacts/root",
        "/artifacts/trust",
        "/artifacts/storage",
        "/artifacts/retained_current",
        "/artifacts/withdrawal_floor",
        "/artifacts/selection",
        "/artifacts/selector_trust",
        "/intent/operation_id",
    ] {
        value.clone_from(&serde_json::to_value(&original)?);
        let slot = value
            .pointer_mut(pointer)
            .ok_or_else(|| anyhow::anyhow!("missing field {pointer}"))?;
        *slot = serde_json::Value::String("different-durable-value".into());
        let mut changed: PublicationProfile = serde_json::from_value(value.clone())?;
        changed.binding = changed.digest()?;
        assert!(
            reserved.require_live_profile(&changed).is_err(),
            "{pointer}"
        );
    }
    let mut changed = original;
    changed.intent.genesis_checkpoint[0] ^= 1;
    changed.binding = changed.digest()?;
    assert!(reserved.require_live_profile(&changed).is_err());
    Ok(())
}

#[test]
fn versioned_record_rejects_hybrid_unknown_fields_and_invalid_live_binding() -> anyhow::Result<()> {
    let original = profile(PublicationVersion::DurableV2)?;
    let reserved = ReservedPublicationProfile::retain_original(original.clone())?;
    let mut value = serde_json::to_value(&reserved)?;
    value["writer"] = serde_json::Value::String(original.writer.clone());
    assert!(serde_json::from_value::<ReservedPublicationProfile>(value).is_err());
    let mut changed = original;
    changed.writer = Digest32::ZERO.to_string();
    changed.binding = changed.digest()?;
    assert!(reserved.require_live_profile(&changed).is_err());
    changed.writer = Digest32::of_bytes(b"new-writer").to_string();
    assert!(reserved.require_live_profile(&changed).is_err());
    Ok(())
}
