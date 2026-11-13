//! Synthetic profile data only; the test storage and Root UID are actual.

use super::*;

pub(super) fn profile() -> anyhow::Result<(PublicationRefusalBinding, ReservedPublicationProfile)> {
    let previous_config = crate::neuron_generation_current::test_support::config()?;
    let mut target_config = previous_config.clone();
    target_config.initial.scope.run_id.push_str("-refusal-next");
    target_config.initial.generation += 1;
    target_config.initial.writer_epoch += 1;
    let previous = CellGenerationOwnerBindingV1::new(
        &previous_config,
        crate::neuron_generation_current::test_support::RECORDS,
    )?;
    let target = CellGenerationOwnerBindingV1::new(
        &target_config,
        crate::neuron_generation_current::test_support::RECORDS,
    )?;
    let digest = |value: &str| Digest32::of_bytes(value.as_bytes()).to_string();
    let mut profile = PublicationProfile {
        purpose: PublicationVersion::DurableV2.purpose().into(),
        learning_operation: "refusal-component-learning".into(),
        initial: digest("initial"),
        scope: digest("scope"),
        writer: digest("original-writer"),
        identity: digest("original-process"),
        decision: digest("decision"),
        previous_files: digest("previous-files"),
        target_files: digest("target-files"),
        artifacts: ArtifactRegistrationPin {
            root: "/refusal-data-only/artifacts".into(),
            trust: digest("artifact-trust"),
            storage: digest("storage"),
            retained_current: digest("current-floor"),
            withdrawal_floor: digest("withdrawal-floor"),
            selection: digest("selection"),
            selector_trust: digest("selector-trust"),
        },
        consumer_trust: digest("consumer-trust"),
        consumer_slot: RootPublicationFinalUseConsumerV1::Device,
        local_consumer: "/refusal-data-only/device".into(),
        intent: UpdateIntent {
            operation_id: "refusal-component-publication".into(),
            supersedes: None,
            previous: previous.clone(),
            previous_checkpoint: [1; 32],
            previous_observation: [2; 32],
            target: target.clone(),
            genesis_checkpoint: target.genesis_checkpoint().into_array(),
            selection: [4; 32],
            completion: crate::NeuronGenerationPredecessorCompletionV1::OwnerDrainedSameModel,
        },
        binding: String::new(),
    };
    profile.binding = profile.digest()?;
    let binding = PublicationRefusalBinding {
        schema: 1,
        purpose: PURPOSE.into(),
        publication_purpose: profile.purpose.clone(),
        learning_operation: profile.learning_operation.clone(),
        initial: profile.initial.clone(),
        scope: profile.scope.clone(),
        previous,
        target,
    };
    Ok((
        binding,
        ReservedPublicationProfile::retain_original(profile)?,
    ))
}
