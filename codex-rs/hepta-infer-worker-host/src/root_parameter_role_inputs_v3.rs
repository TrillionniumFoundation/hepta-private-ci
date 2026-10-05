//! Pure per-sealed-round role inputs from independently obtained original facts.
//! This builder neither resolves CURRENT nor opens stores or a role signing key.
use codex_hepta_agent_components::intelligence_eval::FixedParameterGeneratorInputsV3;
use codex_hepta_agent_components::intelligence_eval::FixedParameterObserverInputsV1;
use codex_hepta_agent_components::intelligence_eval::ParameterRoleSourceV3;
use codex_hepta_agent_components::intelligence_eval::RegisteredArtifactCurrentFactsV3;
use codex_hepta_agent_components::intelligence_eval::validate_current_parameter_admission_v1;
use codex_hepta_agent_components::intelligence_eval::validate_parameter_generator_baseline_v3;
use codex_hepta_agent_components::learning_ledger::ReviewEvidenceWireV1;
use codex_hepta_agent_components::learning_ledger::ReviewTrustWireV1;
use codex_hepta_agent_components::plasticity::ParameterGeneratorProfileV3;
use codex_hepta_agent_components::plasticity::PlasticityAdmissionEvidenceV1;
use codex_hepta_agent_components::plasticity::encode_untrusted_parameter_generator_profile_v3;
use codex_hepta_agent_components::plasticity::encode_untrusted_plasticity_admission_v1;
use codex_hepta_agent_components::plasticity::validate_parameter_admission_binding_v1;
use codex_hepta_agentd::AgentdSelfIterationRoundV1;
use codex_hepta_agentd::CanonicalIterationEnvelopeV1;
use codex_hepta_neuron::NeuronGenerationMaterialV2;
use codex_hepta_neuron::encode_neuron_generation_material_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
fn check(
    round: &AgentdSelfIterationRoundV1,
    canonical: &CanonicalIterationEnvelopeV1,
    baseline: &NeuronGenerationMaterialV2,
    profile: &ParameterGeneratorProfileV3,
    trust: &ReviewTrustWireV1,
    profile_source: &ParameterRoleSourceV3,
    baseline_source: &ParameterRoleSourceV3,
) -> Result<()> {
    let generated = validate_parameter_generator_baseline_v3(
        profile,
        baseline,
        baseline.scope.scope_digest,
        baseline.scope.objective_digest,
    )?;
    if round.canonical_policy_digest() != canonical.digest()
        || canonical.policy().objective_digest != baseline.scope.objective_digest.to_string()
        || trust.scope_digest != baseline.scope.scope_digest.to_string()
        || trust.objective_digest != baseline.scope.objective_digest.to_string()
        || generated.candidates.len() > round.candidate_admissions() as usize
        || round.deadline_ms() > canonical.policy().expires_unix_ms
        || profile_source.digest.parse::<Digest32>()?
            != Digest32::of_bytes(&encode_untrusted_parameter_generator_profile_v3(profile)?)
        || baseline_source.digest.parse::<Digest32>()?
            != Digest32::of_bytes(&encode_neuron_generation_material_v2(baseline)?)
    {
        return Err("whole original sealed Round/profile/baseline/policy/source binding".into());
    }
    Ok(())
}
/// Root obtains baseline/current owner facts before calling this pure builder.
/// The resulting source is immutable and published by the original Root recipe
/// slot before the actual admitted G process consumes it.
pub fn prepare_root_parameter_generator_inputs_v3(
    round: &AgentdSelfIterationRoundV1,
    canonical: &CanonicalIterationEnvelopeV1,
    baseline: &NeuronGenerationMaterialV2,
    profile: &ParameterGeneratorProfileV3,
    trust: ReviewTrustWireV1,
    profile_source: ParameterRoleSourceV3,
    baseline_source: ParameterRoleSourceV3,
) -> Result<FixedParameterGeneratorInputsV3> {
    check(
        round,
        canonical,
        baseline,
        profile,
        &trust,
        &profile_source,
        &baseline_source,
    )?;
    Ok(FixedParameterGeneratorInputsV3 {
        schema: "hepta.fixed-parameter-generator-inputs.v3".into(),
        trust,
        profile: profile_source,
        baseline_material: baseline_source,
        round_digest: round.identity_digest().to_string(),
        canonical_policy_digest: canonical.digest().to_string(),
        admitted_at_ms: round.admitted_at_ms(),
        deadline_ms: round.deadline_ms(),
    })
}
/// Admission must be the whole output of the same original current input-context
/// owner. Its public codec/source pin by itself does not prove that provenance.
pub fn prepare_root_parameter_observer_inputs_v1(
    round: &AgentdSelfIterationRoundV1,
    canonical: &CanonicalIterationEnvelopeV1,
    baseline: &NeuronGenerationMaterialV2,
    profile: &ParameterGeneratorProfileV3,
    admission: &PlasticityAdmissionEvidenceV1,
    trust: ReviewTrustWireV1,
    sources: [ParameterRoleSourceV3; 3],
    generator_evidence: ReviewEvidenceWireV1,
) -> Result<FixedParameterObserverInputsV1> {
    prepare_observer_inputs(
        round,
        canonical,
        RootParameterObserverBaselineV1 {
            material: baseline,
            profile,
            admission,
        },
        trust,
        sources,
        generator_evidence,
        ObserverCurrentAdmission::Initial,
    )
}

/// Complete read-only CURRENT facts and their protected configuration. These
/// inputs grant no role or model use; the actual O process reopens the same source.
pub struct RootParameterObserverCurrentV1<'a> {
    pub facts: &'a RegisteredArtifactCurrentFactsV3,
    pub source: ParameterRoleSourceV3,
    pub subject: &'a StableId,
}

/// The same original full baseline, deterministic profile and owner admission.
/// Borrowing them together creates no authenticated fact or mutation authority.
pub struct RootParameterObserverBaselineV1<'a> {
    pub material: &'a NeuronGenerationMaterialV2,
    pub profile: &'a ParameterGeneratorProfileV3,
    pub admission: &'a PlasticityAdmissionEvidenceV1,
}

/// Build a finite O request using the original selected parameter/head artifact
/// independently from the stable model identity and operational weight manifest.
pub fn prepare_root_parameter_observer_current_inputs_v1(
    round: &AgentdSelfIterationRoundV1,
    canonical: &CanonicalIterationEnvelopeV1,
    baseline: RootParameterObserverBaselineV1<'_>,
    trust: ReviewTrustWireV1,
    sources: [ParameterRoleSourceV3; 3],
    generator_evidence: ReviewEvidenceWireV1,
    current: RootParameterObserverCurrentV1<'_>,
) -> Result<FixedParameterObserverInputsV1> {
    prepare_observer_inputs(
        round,
        canonical,
        baseline,
        trust,
        sources,
        generator_evidence,
        ObserverCurrentAdmission::Registered(current),
    )
}

enum ObserverCurrentAdmission<'a> {
    Initial,
    Registered(RootParameterObserverCurrentV1<'a>),
}
fn prepare_observer_inputs(
    round: &AgentdSelfIterationRoundV1,
    canonical: &CanonicalIterationEnvelopeV1,
    baseline: RootParameterObserverBaselineV1<'_>,
    trust: ReviewTrustWireV1,
    sources: [ParameterRoleSourceV3; 3],
    generator_evidence: ReviewEvidenceWireV1,
    current: ObserverCurrentAdmission<'_>,
) -> Result<FixedParameterObserverInputsV1> {
    let RootParameterObserverBaselineV1 {
        material: baseline,
        profile,
        admission,
    } = baseline;
    let [profile_source, baseline_source, admission_source] = sources;
    check(
        round,
        canonical,
        baseline,
        profile,
        &trust,
        &profile_source,
        &baseline_source,
    )?;
    let generated = validate_parameter_generator_baseline_v3(
        profile,
        baseline,
        baseline.scope.scope_digest,
        baseline.scope.objective_digest,
    )?;
    validate_parameter_admission_binding_v1(profile, &generated, admission)?;
    if admission.baseline_generation != baseline.runtime.generation
        || admission_source.digest.parse::<Digest32>()?
            != Digest32::of_bytes(&encode_untrusted_plasticity_admission_v1(admission)?)
    {
        return Err("original admission/profile/baseline/whole source binding".into());
    }
    let (current_artifact_material, subject) = match current {
        ObserverCurrentAdmission::Initial
            if baseline.runtime.generation.get() == 1
                && admission.baseline_id == baseline.runtime.model_id =>
        {
            (None, None)
        }
        ObserverCurrentAdmission::Initial => {
            return Err("legacy O inputs require original initial model artifact".into());
        }
        ObserverCurrentAdmission::Registered(current) => {
            validate_current_parameter_admission_v1(current.facts, admission, baseline)?;
            if current.source.digest.parse::<Digest32>()?.is_zero()
                || !current.source.path.is_absolute()
            {
                return Err("Root O full current source/pin".into());
            }
            (Some(current.source), Some(current.subject.to_string()))
        }
    };
    Ok(FixedParameterObserverInputsV1 {
        schema: "hepta.fixed-parameter-observer-inputs.v1".into(),
        trust,
        profile: profile_source,
        baseline_material: baseline_source,
        admission: admission_source,
        current_artifact_material,
        subject,
        generator_evidence,
        round_digest: round.identity_digest().to_string(),
        canonical_policy_digest: canonical.digest().to_string(),
        admitted_at_ms: round.admitted_at_ms(),
        deadline_ms: round.deadline_ms(),
    })
}
