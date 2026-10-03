//! Join original G/O, live baseline CURRENT and authenticated public cuts.
use crate::fixed_parameter_generator_v3::validate_parameter_generator_baseline_v3;
use crate::initial_neuron_operational_host::Config as SourceConfig;
use crate::initial_neuron_operational_source::HostResult;
use crate::operational_model_lease_policy_v2::Inputs as SourceInputs;
use crate::operational_model_lease_policy_v2::inspect_inputs;
use crate::operational_registered_model_v3::RegisteredArtifactCurrentFactsV3;
use crate::operational_registered_model_v3::inspect_registered_artifact_current_material_v3;
use crate::parameter_pre_registration_v1::*;
use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::ReviewTrustWireV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::activate_learning_trust;
use codex_hepta_learning_ledger::decode_review_payload_hex;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use codex_hepta_neuron::MAX_NEURON_GENERATION_MATERIAL_BYTES_V2;
use codex_hepta_neuron::NeuronGenerationMaterialV2;
use codex_hepta_neuron::decode_neuron_generation_material_v2;
use codex_hepta_plasticity::PlasticityAdmissionEvidenceV1;
use codex_hepta_plasticity::decode_untrusted_parameter_generator_profile_v3;
use codex_hepta_plasticity::decode_untrusted_plasticity_admission_v1;
use codex_hepta_plasticity::parameter_generator_signing_payload_v3;
use codex_hepta_plasticity::plasticity_admission_signing_payload_v1;
use codex_hepta_plasticity::validate_parameter_admission_binding_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

pub(super) struct Inputs {
    pub source: SourceInputs,
    pub plan: NeuronGenerationMaterialV2,
    pub baseline: RegisteredArtifactCurrentFactsV3,
    pub admission: PlasticityAdmissionEvidenceV1,
    pub trust: ActivatedLearningTrustV1,
    pub reviewer: TrustedLearningSignerV1,
    pub selectors: Vec<TrustedLearningSignerV1>,
    pub generator: VerifiedLearningEvidenceV1,
    pub observer: VerifiedLearningEvidenceV1,
    pub expiry: u64,
}
pub(super) fn inspect(
    config: &FixedParameterPreRegistrationConfigV1,
    now: u64,
) -> HostResult<Inputs> {
    config.round.validate(now)?;
    if config.schema != "hepta.fixed-parameter-pre-registration-evaluator-config.v1"
        || config.uid == 0
        || config.gid == 0
        || config.inaccessible_paths.len() != 5
        || config.maximum_resident_bytes == 0
        || config.maximum_resident_bytes > 256 * 1024 * 1024
        || config.program_digest.parse::<Digest32>()?.is_zero()
    {
        return Err("bounded independent pre-registration E profile".into());
    }
    let original: SourceConfig =
        serde_json::from_slice(&config.source_configuration.read(32 * 1024)?)?;
    let source = inspect_inputs(&original, now)?;
    let material = |source: &crate::fixed_parameter_generator_v3::ParameterRoleSourceV3| {
        decode_neuron_generation_material_v2(
            &source.read(MAX_NEURON_GENERATION_MATERIAL_BYTES_V2 as u64)?,
        )
        .map_err(|e| Box::<dyn std::error::Error>::from(e))
    };
    let baseline_material = material(&config.baseline_material)?;
    let plan = material(&config.prospective_material)?;
    let profile =
        decode_untrusted_parameter_generator_profile_v3(&config.profile.read(16 * 1024 * 1024)?)?;
    let admission =
        decode_untrusted_plasticity_admission_v1(&config.admission.read(16 * 1024 * 1024)?)?;
    let generated = validate_parameter_generator_baseline_v3(
        &profile,
        &baseline_material,
        baseline_material.scope.scope_digest,
        admission.objective_digest,
    )?;
    validate_parameter_admission_binding_v1(&profile, &generated, &admission)?;
    validate_parameter_pre_registration_material_v1(
        &baseline_material,
        &plan,
        &generated,
        &admission,
        &StableId::new(config.candidate_id.clone())?,
        config.purpose,
    )?;
    let old = &source.binding;
    if baseline_material.runtime.model_manifest_digest != old.model_manifest_digest
        || baseline_material.runtime.weights_digest != old.weights_digest
        || baseline_material.runtime.normalization_digest != old.normalization_digest
        || baseline_material.runtime.encoder_digest != old.encoder_manifest_digest
        || baseline_material.runtime.tokenizer_digest != old.tokenizer_digest
        || baseline_material.native.width != source.policy.runtime_profile.state_width as usize
    {
        return Err("pre-registration changed authenticated original numeric head/input".into());
    }
    let gates = &source.native.policy.gates;
    let calibration = &plan.runtime.calibration;
    if u64::try_from(calibration.zero_confidence_error_q24)? != gates.zero_confidence_error_q24
        || u64::try_from(calibration.maximum_in_domain_error_q24)?
            != gates.maximum_in_domain_error_q24
        || calibration.minimum_confidence_ppm != gates.minimum_confidence_ppm
        || calibration.maximum_ood_ppm != gates.maximum_ood_ppm
        || calibration.maximum_ece_ppm != gates.maximum_ece_ppm
        || calibration.maximum_false_acceptance_ppm != gates.maximum_false_acceptance_ppm
    {
        return Err(
            "runtime calibration gates differ from actual authenticated head measurement".into(),
        );
    }
    let baseline = inspect_registered_artifact_current_material_v3(
        &config.baseline_registration.path,
        config.baseline_registration.digest.parse()?,
        &baseline_material,
        &StableId::new(config.subject.clone())?,
        now,
    )?;
    if baseline.current_head().binding != admission.artifact_registry_binding
        || baseline.current_view().receipt().head_digest != admission.artifact_registry_head_digest
        || baseline.manifests()[0].manifest.artifact_id != admission.baseline_id
    {
        return Err(
            "actual original baseline CURRENT id/generation/head differs from O admission".into(),
        );
    }
    let wire: ReviewTrustWireV1 =
        serde_json::from_slice(&config.current_learning_trust.read(128 * 1024)?)?;
    if wire.root_verifying_key_hex != config.root_verifying_key_hex
        || wire.scope_digest != plan.scope.scope_digest.to_string()
        || wire.objective_digest != plan.scope.objective_digest.to_string()
    {
        return Err("Root-pinned pre-registration role trust scope/objective".into());
    }
    let (root, distribution) = wire.native()?;
    let reviewer = distribution
        .distribution
        .trust
        .signers
        .iter()
        .find(|s| s.principal.principal_id.as_str() == config.reviewer_id)
        .ok_or("original independent pre-registration E roster")?
        .clone();
    let selectors = distribution
        .distribution
        .trust
        .signers
        .iter()
        .filter(|s| s.roles.contains(&LearningEvidenceRoleV1::Selector))
        .cloned()
        .collect();
    let trust = activate_learning_trust(&root, distribution, None, now)?;
    let g = config.generator_evidence.native()?;
    let o = config.observer_evidence.native()?;
    if g.principal_id.as_str() != "native-unprivileged-generator"
        || o.principal_id.as_str() != "fixed-custody-observer"
        || g.issued_at < config.round.admitted_at_ms
        || o.issued_at < config.round.admitted_at_ms
    {
        return Err("actual independent G/O original purpose/admitted Round".into());
    }
    let generator = trust.verifier().verify(
        LearningEvidenceRoleV1::Generator,
        &g,
        &parameter_generator_signing_payload_v3(&generated),
        now,
    )?;
    let observer = trust.verifier().verify(
        LearningEvidenceRoleV1::Observer,
        &o,
        &plasticity_admission_signing_payload_v1(&admission),
        now,
    )?;
    verify_signed_actor_separation(&generator, &observer, now)?;
    let mut expiry = config
        .round
        .deadline_ms
        .min(baseline.expires_at())
        .min(trust.expires_at())
        .min(g.expires_at)
        .min(o.expires_at)
        .min(reviewer.principal.expires_at);
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
    if now >= expiry {
        return Err("original E1 source/current/role expiry".into());
    }
    Ok(Inputs {
        source,
        plan,
        baseline,
        admission,
        trust,
        reviewer,
        selectors,
        generator,
        observer,
        expiry,
    })
}
pub(super) fn validate_reviewer(
    config: &FixedParameterPreRegistrationConfigV1,
    inputs: &Inputs,
) -> HostResult<()> {
    let root: [u8; 32] = decode_review_payload_hex(&config.root_verifying_key_hex)?
        .try_into()
        .map_err(|_| "Root verifying key width")?;
    crate::fixed_calibration_cycle_evaluator::verify_actual_reviewer(
        &inputs.reviewer,
        config.program_digest.parse()?,
        &root,
        config.uid,
        config.gid,
        None,
    )
}
