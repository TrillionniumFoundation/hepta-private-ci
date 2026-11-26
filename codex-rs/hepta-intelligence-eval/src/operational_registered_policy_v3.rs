//! Protected V3 policy joins the original public source with independently
//! registered successor material and the current actual reviewer roster.
use crate::initial_neuron_operational_host::Config as SourceConfig;
use crate::initial_neuron_operational_source::HostResult;
use crate::initial_neuron_operational_source::Source;
use crate::operational_model_lease_policy_v2::Inputs as SourceInputs;
use crate::operational_model_lease_policy_v2::inspect_inputs;
use crate::operational_registered_model_v3::RegisteredOperationalModelBindingV3;
use crate::operational_registered_model_v3::Registration;
use crate::operational_registered_model_v3::inspect_registration;
use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::ReviewTrustWireV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_learning_ledger::activate_learning_trust;
use codex_hepta_neuron::MAX_NEURON_GENERATION_MATERIAL_BYTES_V2;
use codex_hepta_neuron::NeuronGenerationMaterialV2;
use codex_hepta_neuron::decode_neuron_generation_material_v2;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use std::path::PathBuf;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Config {
    pub schema: String,
    pub uid: u32,
    pub gid: u32,
    pub program_digest: String,
    pub private_key_path: PathBuf,
    pub reviewer_id: String,
    pub source_configuration: Source,
    pub material: Source,
    pub registration: Registration,
    pub current_learning_trust: Source,
    pub root_verifying_key_hex: String,
    pub frozen_at_ms: u64,
    pub expires_at_ms: u64,
    pub maximum_resident_bytes: u64,
    pub inaccessible_paths: Vec<PathBuf>,
}
pub(super) struct Inputs {
    pub source: SourceInputs,
    pub plan: NeuronGenerationMaterialV2,
    pub binding: RegisteredOperationalModelBindingV3,
    pub current_trust: ActivatedLearningTrustV1,
    pub reviewer: TrustedLearningSignerV1,
    pub selectors: Vec<TrustedLearningSignerV1>,
    pub expiry: u64,
}
pub(super) fn inspect(config: &Config, now: u64) -> HostResult<Inputs> {
    if config.schema != "hepta.fixed-registered-operational-model-evaluator-config.v3"
        || config.uid == 0
        || config.gid == 0
        || config.inaccessible_paths.len() != 5
        || config.frozen_at_ms == 0
        || config.frozen_at_ms > now
        || config.expires_at_ms <= now
        || config.expires_at_ms.saturating_sub(config.frozen_at_ms) > 86_400_000
        || config.maximum_resident_bytes == 0
        || config.maximum_resident_bytes > 256 * 1024 * 1024
    {
        return Err("bounded independent registered model evaluator policy".into());
    }
    let original: SourceConfig =
        serde_json::from_slice(&config.source_configuration.read(32 * 1024)?)?;
    let source = inspect_inputs(&original, now)?;
    let plan = decode_neuron_generation_material_v2(
        &config
            .material
            .read(MAX_NEURON_GENERATION_MATERIAL_BYTES_V2 as u64)?,
    )?;
    let old = &source.binding;
    // Only sparse parameters may differ. The original physical model/input
    // implementation remains exactly the authenticated source producer's.
    if plan.runtime.model_manifest_digest != old.model_manifest_digest
        || plan.runtime.weights_digest != old.weights_digest
        || plan.runtime.normalization_digest != old.normalization_digest
        || plan.runtime.encoder_digest != old.encoder_manifest_digest
        || plan.runtime.tokenizer_digest != old.tokenizer_digest
        || plan.native.width != source.policy.runtime_profile.state_width as usize
    {
        return Err(
            "registered parameter-only successor changed authenticated original head/input".into(),
        );
    }
    let (binding, registered_expiry) = inspect_registration(&config.registration, &plan, now)?;
    let wire: ReviewTrustWireV1 =
        serde_json::from_slice(&config.current_learning_trust.read(128 * 1024)?)?;
    if wire.root_verifying_key_hex != config.root_verifying_key_hex {
        return Err("current independently Root-pinned role trust".into());
    }
    let (root, distribution) = wire.native()?;
    let trust = &distribution.distribution.trust;
    if trust.scope_digest != plan.scope.scope_digest
        || trust.objective_digest != plan.scope.objective_digest
    {
        return Err("current role trust differs from actual runtime scope/objective".into());
    }
    let reviewer = trust
        .signers
        .iter()
        .find(|s| s.principal.principal_id.as_str() == config.reviewer_id)
        .ok_or("current registered model E principal")?
        .clone();
    let selectors = trust
        .signers
        .iter()
        .filter(|s| s.roles.contains(&LearningEvidenceRoleV1::Selector))
        .cloned()
        .collect();
    let current_trust = activate_learning_trust(&root, distribution, None, now)?;
    let mut expiry = config
        .expires_at_ms
        .min(registered_expiry)
        .min(reviewer.principal.expires_at)
        .min(current_trust.expires_at());
    for cut in [&source.native.calibration, &source.native.ood] {
        for actor in &cut.actors {
            expiry = expiry.min(actor.principal().expires_at);
        }
        for evidence in [
            cut.publication.cut.generator_evidence.native()?,
            cut.publication.cut.freeze_evidence.native()?,
            cut.publication.observer_evidence.native()?,
        ] {
            expiry = expiry.min(evidence.expires_at);
        }
    }
    if expiry <= now || config.program_digest.parse::<Digest32>()?.is_zero() {
        return Err("current registered E lifetime/program".into());
    }
    Ok(Inputs {
        source,
        plan,
        binding,
        current_trust,
        reviewer,
        selectors,
        expiry,
    })
}
