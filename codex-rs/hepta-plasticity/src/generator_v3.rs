//! Deterministic, generator-complete parameter candidate construction.
//!
//! V2 accepts a caller-supplied candidate set. This V3 generator closes that
//! source-level gap by defining a bounded search space and emitting every unique
//! candidate admitted by that deterministic search. It still grants no selection,
//! acceptance, training, installation, promotion, release or runtime-mutation authority.

use std::collections::{BTreeMap, BTreeSet};
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::{Digest32, FixedQ32, StableId};

use crate::{
    LayerNormDenominatorV2, MutationGrammarErrorV1, MutationGrammarManifestV1,
    ParameterCandidateKindV2, ParameterCandidateRequestV2, ParameterDeltaV2, ProposalWindowV2,
    authorize_parameter_mutation_v1, verify_mutation_grammar_manifest_v1,
};

const MAX_V3_CANDIDATES: usize = 32;
const MAX_V3_UPDATE_SCALES: usize = MAX_V3_CANDIDATES - 1;
const MAX_V3_PARAMETER_DELTAS: usize = 4_096;
const MAX_V3_NORM_LAYERS: usize = 256;
const PER_LAYER_MAX_RELATIVE_PPM: u32 = 5_000;
const GLOBAL_MAX_RELATIVE_PPM: u32 = 2_500;
const PPM_DENOMINATOR: u128 = 1_000_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParameterPlasticitySignalV3 {
    pub layer_id: StableId,
    pub parameter_id: StableId,
    pub eligibility: FixedQ32,
    pub modulator: FixedQ32,
    pub learning_rate: FixedQ32,
    pub lower_bound: FixedQ32,
    pub upper_bound: FixedQ32,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParameterGeneratorProfileV3 {
    pub selected_artifact_digest: Digest32,
    pub window: ProposalWindowV2,
    pub norm_layers: Vec<LayerNormDenominatorV2>,
    /// Typed allowlist/protected-surface policy bound to this artifact/window.
    pub mutation_grammar: MutationGrammarManifestV1,
    /// Positive deterministic multipliers in `(0, 1]`. Every admitted scale is
    /// evaluated; candidates that collapse to identical deltas are deduplicated.
    pub update_scales: Vec<FixedQ32>,
    /// Explicit parameter-group mapping. No implicit broadcast is performed.
    pub signals: Vec<ParameterPlasticitySignalV3>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GeneratedParameterCandidateSetV3 {
    pub selected_artifact_digest: Digest32,
    pub window: ProposalWindowV2,
    pub norm_layers: Vec<LayerNormDenominatorV2>,
    pub candidates: Vec<ParameterCandidateRequestV2>,
    pub generator_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ParameterGeneratorErrorV3 {
    EmptyDigest(&'static str),
    NormLayerCountOutOfRange,
    DuplicateNormLayer(String),
    ZeroNormDenominator(String),
    ScaleCountOutOfRange,
    InvalidScale,
    DuplicateScale,
    SignalLimitExceeded,
    DuplicateParameter(String),
    MissingNormLayer(String),
    EmptySignalEvidence(String),
    InvertedBounds(String),
    MutationGrammar(MutationGrammarErrorV1),
    Arithmetic,
    CandidateIdentity,
    GeneratorDigestMismatch,
}

impl fmt::Display for ParameterGeneratorErrorV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for ParameterGeneratorErrorV3 {}
impl From<MutationGrammarErrorV1> for ParameterGeneratorErrorV3 {
    fn from(value: MutationGrammarErrorV1) -> Self {
        Self::MutationGrammar(value)
    }
}

/// Generate the complete bounded candidate set for the declared V3 search profile.
///
/// Completeness is relative to this exact deterministic generator: one explicit
/// no-change candidate plus every unique trust-region-admissible candidate obtained
/// by applying each declared scale to every declared signal. It is not a claim that
/// this search profile spans every useful model update.
pub fn generate_parameter_candidates_v3(
    mut profile: ParameterGeneratorProfileV3,
) -> Result<GeneratedParameterCandidateSetV3, ParameterGeneratorErrorV3> {
    validate_header(&profile)?;
    canonicalize_profile(&mut profile)?;

    let denominator_by_layer = profile
        .norm_layers
        .iter()
        .map(|layer| (layer.layer_id.clone(), layer.baseline_squared_l2_raw_q64))
        .collect::<BTreeMap<_, _>>();
    let global_baseline = profile.norm_layers.iter().try_fold(0_u128, |sum, layer| {
        sum.checked_add(layer.baseline_squared_l2_raw_q64)
            .ok_or(ParameterGeneratorErrorV3::Arithmetic)
    })?;

    let mut candidates = vec![ParameterCandidateRequestV2 {
        candidate_id: context_no_change_id(profile.selected_artifact_digest, &profile.window)?,
        kind: ParameterCandidateKindV2::NoChange,
        parameter_deltas: Vec::new(),
    }];
    let mut seen_candidate_ids = BTreeSet::new();
    seen_candidate_ids.insert(candidates[0].candidate_id.clone());

    for scale in &profile.update_scales {
        let mut deltas = Vec::with_capacity(profile.signals.len());
        for signal in &profile.signals {
            let delta = signal
                .eligibility
                .checked_mul(signal.modulator)
                .and_then(|value| value.checked_mul(signal.learning_rate))
                .and_then(|value| value.checked_mul(*scale))
                .map_err(|_| ParameterGeneratorErrorV3::Arithmetic)?
                .clamp(signal.lower_bound, signal.upper_bound)
                .map_err(|_| ParameterGeneratorErrorV3::Arithmetic)?;
            if delta == FixedQ32::ZERO {
                continue;
            }
            deltas.push(ParameterDeltaV2 {
                layer_id: signal.layer_id.clone(),
                parameter_id: signal.parameter_id.clone(),
                delta,
                lower_bound: signal.lower_bound,
                upper_bound: signal.upper_bound,
                evidence_digest: signal.evidence_digest,
            });
        }
        if deltas.is_empty()
            || !within_trust_region(&deltas, &denominator_by_layer, global_baseline)?
        {
            continue;
        }
        let candidate_id =
            content_candidate_id(profile.selected_artifact_digest, &profile.window, &deltas)?;
        if !seen_candidate_ids.insert(candidate_id.clone()) {
            continue;
        }
        candidates.push(ParameterCandidateRequestV2 {
            candidate_id,
            kind: ParameterCandidateKindV2::Update,
            parameter_deltas: deltas,
        });
    }

    candidates.sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
    if candidates.len() > MAX_V3_CANDIDATES {
        return Err(ParameterGeneratorErrorV3::ScaleCountOutOfRange);
    }
    let generator_digest = digest_generated_set(&profile, &candidates)?;
    Ok(GeneratedParameterCandidateSetV3 {
        selected_artifact_digest: profile.selected_artifact_digest,
        window: profile.window,
        norm_layers: profile.norm_layers,
        candidates,
        generator_digest,
    })
}

pub fn verify_generated_parameter_candidates_v3(
    profile: ParameterGeneratorProfileV3,
    generated: &GeneratedParameterCandidateSetV3,
) -> Result<(), ParameterGeneratorErrorV3> {
    let expected = generate_parameter_candidates_v3(profile)?;
    if &expected != generated {
        return Err(ParameterGeneratorErrorV3::GeneratorDigestMismatch);
    }
    Ok(())
}

/// Exact bytes that an authenticated generator signs at the external trust boundary.
pub fn parameter_generator_signing_payload_v3(
    generated: &GeneratedParameterCandidateSetV3,
) -> Vec<u8> {
    let mut bytes = b"hepta.plasticity.parameter-generator.v3\0".to_vec();
    bytes.extend_from_slice(generated.generator_digest.as_array());
    bytes
}

fn validate_header(profile: &ParameterGeneratorProfileV3) -> Result<(), ParameterGeneratorErrorV3> {
    if profile.selected_artifact_digest.is_zero() {
        return Err(ParameterGeneratorErrorV3::EmptyDigest("selected artifact"));
    }
    if profile.window.window_digest.is_zero() {
        return Err(ParameterGeneratorErrorV3::EmptyDigest("window"));
    }
    if !(1..=MAX_V3_NORM_LAYERS).contains(&profile.norm_layers.len()) {
        return Err(ParameterGeneratorErrorV3::NormLayerCountOutOfRange);
    }
    if profile.update_scales.len() > MAX_V3_UPDATE_SCALES {
        return Err(ParameterGeneratorErrorV3::ScaleCountOutOfRange);
    }
    let product = profile
        .signals
        .len()
        .checked_mul(profile.update_scales.len().max(1))
        .ok_or(ParameterGeneratorErrorV3::Arithmetic)?;
    if profile.signals.len() > MAX_V3_PARAMETER_DELTAS || product > MAX_V3_PARAMETER_DELTAS {
        return Err(ParameterGeneratorErrorV3::SignalLimitExceeded);
    }
    Ok(())
}

fn canonicalize_profile(
    profile: &mut ParameterGeneratorProfileV3,
) -> Result<(), ParameterGeneratorErrorV3> {
    verify_mutation_grammar_manifest_v1(&profile.mutation_grammar)?;
    profile
        .norm_layers
        .sort_by(|left, right| left.layer_id.cmp(&right.layer_id));
    let mut layer_ids = BTreeSet::new();
    for layer in &profile.norm_layers {
        if !layer_ids.insert(layer.layer_id.clone()) {
            return Err(ParameterGeneratorErrorV3::DuplicateNormLayer(
                layer.layer_id.to_string(),
            ));
        }
        if layer.baseline_squared_l2_raw_q64 == 0 {
            return Err(ParameterGeneratorErrorV3::ZeroNormDenominator(
                layer.layer_id.to_string(),
            ));
        }
    }

    profile.update_scales.sort();
    if profile
        .update_scales
        .windows(2)
        .any(|pair| pair[0] == pair[1])
    {
        return Err(ParameterGeneratorErrorV3::DuplicateScale);
    }
    if profile
        .update_scales
        .iter()
        .any(|scale| *scale <= FixedQ32::ZERO || *scale > FixedQ32::ONE)
    {
        return Err(ParameterGeneratorErrorV3::InvalidScale);
    }

    profile.signals.sort_by(|left, right| {
        left.layer_id
            .cmp(&right.layer_id)
            .then_with(|| left.parameter_id.cmp(&right.parameter_id))
    });
    let mut parameter_ids = BTreeSet::new();
    for signal in &profile.signals {
        if !parameter_ids.insert(signal.parameter_id.clone()) {
            return Err(ParameterGeneratorErrorV3::DuplicateParameter(
                signal.parameter_id.to_string(),
            ));
        }
        if !layer_ids.contains(&signal.layer_id) {
            return Err(ParameterGeneratorErrorV3::MissingNormLayer(
                signal.layer_id.to_string(),
            ));
        }
        if signal.evidence_digest.is_zero() {
            return Err(ParameterGeneratorErrorV3::EmptySignalEvidence(
                signal.parameter_id.to_string(),
            ));
        }
        if signal.lower_bound > signal.upper_bound {
            return Err(ParameterGeneratorErrorV3::InvertedBounds(
                signal.parameter_id.to_string(),
            ));
        }
        authorize_parameter_mutation_v1(
            &profile.mutation_grammar,
            profile.selected_artifact_digest,
            &profile.window,
            &signal.layer_id,
            &signal.parameter_id,
            signal.lower_bound,
            signal.upper_bound,
        )?;
    }
    Ok(())
}

fn within_trust_region(
    deltas: &[ParameterDeltaV2],
    denominator_by_layer: &BTreeMap<StableId, u128>,
    global_baseline: u128,
) -> Result<bool, ParameterGeneratorErrorV3> {
    let mut delta_by_layer = BTreeMap::<StableId, u128>::new();
    let mut global_delta = 0_u128;
    for delta in deltas {
        let raw = i128::from(delta.delta.raw());
        let squared =
            u128::try_from(raw * raw).map_err(|_| ParameterGeneratorErrorV3::Arithmetic)?;
        let total = delta_by_layer.entry(delta.layer_id.clone()).or_default();
        *total = total
            .checked_add(squared)
            .ok_or(ParameterGeneratorErrorV3::Arithmetic)?;
        global_delta = global_delta
            .checked_add(squared)
            .ok_or(ParameterGeneratorErrorV3::Arithmetic)?;
    }
    for (layer_id, delta_squared) in delta_by_layer {
        let baseline = denominator_by_layer
            .get(&layer_id)
            .copied()
            .ok_or_else(|| ParameterGeneratorErrorV3::MissingNormLayer(layer_id.to_string()))?;
        if !within_relative_limit(delta_squared, baseline, PER_LAYER_MAX_RELATIVE_PPM)? {
            return Ok(false);
        }
    }
    within_relative_limit(global_delta, global_baseline, GLOBAL_MAX_RELATIVE_PPM)
}

fn within_relative_limit(
    delta_squared: u128,
    baseline_squared: u128,
    maximum_relative_ppm: u32,
) -> Result<bool, ParameterGeneratorErrorV3> {
    if baseline_squared == 0 {
        return Ok(false);
    }
    let ppm_squared = u128::from(maximum_relative_ppm)
        .checked_mul(u128::from(maximum_relative_ppm))
        .ok_or(ParameterGeneratorErrorV3::Arithmetic)?;
    let denominator_squared = PPM_DENOMINATOR
        .checked_mul(PPM_DENOMINATOR)
        .ok_or(ParameterGeneratorErrorV3::Arithmetic)?;
    let left = delta_squared
        .checked_mul(denominator_squared)
        .ok_or(ParameterGeneratorErrorV3::Arithmetic)?;
    let right = baseline_squared
        .checked_mul(ppm_squared)
        .ok_or(ParameterGeneratorErrorV3::Arithmetic)?;
    Ok(left <= right)
}

fn context_no_change_id(
    selected_artifact_digest: Digest32,
    window: &ProposalWindowV2,
) -> Result<StableId, ParameterGeneratorErrorV3> {
    let mut bytes = b"hepta.plasticity.parameter-candidate.no-change.v3\0".to_vec();
    push_candidate_context(&mut bytes, selected_artifact_digest, window)?;
    stable_id(&format!(
        "candidate:no-change:{}",
        Digest32::of_bytes(&bytes)
    ))
}

fn content_candidate_id(
    selected_artifact_digest: Digest32,
    window: &ProposalWindowV2,
    deltas: &[ParameterDeltaV2],
) -> Result<StableId, ParameterGeneratorErrorV3> {
    let mut bytes = b"hepta.plasticity.parameter-candidate.update.v3\0".to_vec();
    push_candidate_context(&mut bytes, selected_artifact_digest, window)?;
    push_deltas(&mut bytes, deltas)?;
    stable_id(&format!("candidate:update:{}", Digest32::of_bytes(&bytes)))
}

fn push_candidate_context(
    bytes: &mut Vec<u8>,
    selected_artifact_digest: Digest32,
    window: &ProposalWindowV2,
) -> Result<(), ParameterGeneratorErrorV3> {
    bytes.extend_from_slice(selected_artifact_digest.as_array());
    push_id(bytes, &window.window_id)?;
    bytes.extend_from_slice(window.window_digest.as_array());
    Ok(())
}

fn digest_generated_set(
    profile: &ParameterGeneratorProfileV3,
    candidates: &[ParameterCandidateRequestV2],
) -> Result<Digest32, ParameterGeneratorErrorV3> {
    let mut bytes = b"hepta.plasticity.parameter-generator-profile.v3\0".to_vec();
    bytes.extend_from_slice(profile.selected_artifact_digest.as_array());
    push_id(&mut bytes, &profile.window.window_id)?;
    bytes.extend_from_slice(profile.window.window_digest.as_array());
    push_len(&mut bytes, profile.norm_layers.len())?;
    for layer in &profile.norm_layers {
        push_id(&mut bytes, &layer.layer_id)?;
        bytes.extend_from_slice(&layer.baseline_squared_l2_raw_q64.to_be_bytes());
    }
    bytes.extend_from_slice(profile.mutation_grammar.manifest_digest.as_array());
    push_len(&mut bytes, profile.update_scales.len())?;
    for scale in &profile.update_scales {
        bytes.extend_from_slice(&scale.raw().to_be_bytes());
    }
    push_len(&mut bytes, profile.signals.len())?;
    for signal in &profile.signals {
        push_id(&mut bytes, &signal.layer_id)?;
        push_id(&mut bytes, &signal.parameter_id)?;
        for value in [
            signal.eligibility,
            signal.modulator,
            signal.learning_rate,
            signal.lower_bound,
            signal.upper_bound,
        ] {
            bytes.extend_from_slice(&value.raw().to_be_bytes());
        }
        bytes.extend_from_slice(signal.evidence_digest.as_array());
    }
    push_len(&mut bytes, candidates.len())?;
    for candidate in candidates {
        push_id(&mut bytes, &candidate.candidate_id)?;
        bytes.push(match candidate.kind {
            ParameterCandidateKindV2::NoChange => 0,
            ParameterCandidateKindV2::Update => 1,
        });
        push_deltas(&mut bytes, &candidate.parameter_deltas)?;
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn push_deltas(
    bytes: &mut Vec<u8>,
    deltas: &[ParameterDeltaV2],
) -> Result<(), ParameterGeneratorErrorV3> {
    push_len(bytes, deltas.len())?;
    for delta in deltas {
        push_id(bytes, &delta.layer_id)?;
        push_id(bytes, &delta.parameter_id)?;
        bytes.extend_from_slice(&delta.delta.raw().to_be_bytes());
        bytes.extend_from_slice(&delta.lower_bound.raw().to_be_bytes());
        bytes.extend_from_slice(&delta.upper_bound.raw().to_be_bytes());
        bytes.extend_from_slice(delta.evidence_digest.as_array());
    }
    Ok(())
}

fn stable_id(value: &str) -> Result<StableId, ParameterGeneratorErrorV3> {
    StableId::new(value).map_err(|_| ParameterGeneratorErrorV3::CandidateIdentity)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), ParameterGeneratorErrorV3> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| ParameterGeneratorErrorV3::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

fn push_len(bytes: &mut Vec<u8>, value: usize) -> Result<(), ParameterGeneratorErrorV3> {
    let value = u32::try_from(value).map_err(|_| ParameterGeneratorErrorV3::Arithmetic)?;
    bytes.extend_from_slice(&value.to_be_bytes());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{MutationSurfaceV1, ParameterMutationRuleV1, build_mutation_grammar_manifest_v1};

    fn id(value: &str) -> StableId {
        StableId::new(value).unwrap_or_else(|error| panic!("id {value}: {error}"))
    }
    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }
    fn profile() -> ParameterGeneratorProfileV3 {
        ParameterGeneratorProfileV3 {
            selected_artifact_digest: digest(b"artifact"),
            window: ProposalWindowV2 {
                window_id: id("window:1"),
                window_digest: digest(b"window"),
            },
            norm_layers: vec![LayerNormDenominatorV2 {
                layer_id: id("layer:1"),
                baseline_squared_l2_raw_q64: 1_u128 << 64,
            }],
            mutation_grammar: build_mutation_grammar_manifest_v1(
                id("grammar:generator-test"),
                digest(b"artifact"),
                ProposalWindowV2 {
                    window_id: id("window:1"),
                    window_digest: digest(b"window"),
                },
                vec![ParameterMutationRuleV1 {
                    parameter_id: id("parameter:1"),
                    layer_id: id("layer:1"),
                    surface: MutationSurfaceV1::LearnableParameter,
                    minimum_delta: FixedQ32::from_raw(-(1_i64 << 24)),
                    maximum_delta: FixedQ32::from_raw(1_i64 << 24),
                }],
            )
            .expect("grammar"),
            update_scales: vec![FixedQ32::ONE, FixedQ32::from_raw(1_i64 << 31)],
            signals: vec![ParameterPlasticitySignalV3 {
                layer_id: id("layer:1"),
                parameter_id: id("parameter:1"),
                eligibility: FixedQ32::ONE,
                modulator: FixedQ32::ONE,
                learning_rate: FixedQ32::from_raw(1_i64 << 20),
                lower_bound: FixedQ32::from_raw(-(1_i64 << 24)),
                upper_bound: FixedQ32::from_raw(1_i64 << 24),
                evidence_digest: digest(b"signal-evidence"),
            }],
        }
    }

    #[test]
    fn generator_is_deterministic_complete_and_content_identified() {
        let first = generate_parameter_candidates_v3(profile()).expect("generate");
        let second = generate_parameter_candidates_v3(profile()).expect("generate again");
        assert_eq!(first, second);
        assert_eq!(first.candidates.len(), 3);
        assert_eq!(
            first
                .candidates
                .iter()
                .filter(|candidate| candidate.kind == ParameterCandidateKindV2::NoChange)
                .count(),
            1
        );
        for candidate in first
            .candidates
            .iter()
            .filter(|candidate| candidate.kind == ParameterCandidateKindV2::Update)
        {
            assert!(
                candidate
                    .candidate_id
                    .as_str()
                    .starts_with("candidate:update:")
            );
            assert_eq!(candidate.parameter_deltas.len(), 1);
        }
        verify_generated_parameter_candidates_v3(profile(), &first).expect("verify");
        assert!(!first.generator_digest.is_zero());
    }

    #[test]
    fn candidate_identity_changes_with_artifact_or_window_context() {
        let base = generate_parameter_candidates_v3(profile()).expect("base");
        let base_update = base
            .candidates
            .iter()
            .find(|candidate| candidate.kind == ParameterCandidateKindV2::Update)
            .expect("base update")
            .candidate_id
            .clone();

        let mut artifact = profile();
        artifact.selected_artifact_digest = digest(b"other-artifact");
        let artifact_update = generate_parameter_candidates_v3(artifact)
            .expect("artifact")
            .candidates
            .into_iter()
            .find(|candidate| candidate.kind == ParameterCandidateKindV2::Update)
            .expect("artifact update")
            .candidate_id;
        assert_ne!(base_update, artifact_update);

        let mut window = profile();
        window.window.window_digest = digest(b"other-window");
        let window_update = generate_parameter_candidates_v3(window)
            .expect("window")
            .candidates
            .into_iter()
            .find(|candidate| candidate.kind == ParameterCandidateKindV2::Update)
            .expect("window update")
            .candidate_id;
        assert_ne!(base_update, window_update);
    }

    #[test]
    fn generator_rejects_duplicate_parameters_and_oversized_searches() {
        let mut duplicate = profile();
        duplicate.signals.push(duplicate.signals[0].clone());
        assert!(matches!(
            generate_parameter_candidates_v3(duplicate),
            Err(ParameterGeneratorErrorV3::DuplicateParameter(_))
        ));

        let mut oversized = profile();
        oversized.update_scales = (1..=32).map(FixedQ32::from_raw).collect();
        assert_eq!(
            generate_parameter_candidates_v3(oversized),
            Err(ParameterGeneratorErrorV3::ScaleCountOutOfRange)
        );
    }

    #[test]
    fn generator_filters_updates_outside_the_trust_region() {
        let mut value = profile();
        value.signals[0].learning_rate = FixedQ32::ONE;
        let generated = generate_parameter_candidates_v3(value).expect("generate");
        assert_eq!(generated.candidates.len(), 1);
        assert!(matches!(
            generated.candidates[0].kind,
            ParameterCandidateKindV2::NoChange
        ));
    }
}
