//! Deterministic coverage proof for governed parameter generation.
//!
//! A generator-complete candidate set is complete only relative to its declared
//! profile. This module additionally proves that the profile accounts for the
//! complete host-declared learnable-parameter set: every expected parameter is
//! either represented by one exact signal or excluded with a typed reason and
//! evidence. The receipt is authority-free and grants no selection, training,
//! installation, promotion, release, or runtime-mutation power.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ParameterGeneratorProfileV3;
use crate::ParameterMutationPolicyErrorV1;
use crate::ProposalWindowV2;
use crate::verify_parameter_mutation_policy_v1;

const MAX_COVERAGE_PARAMETERS_V1: usize = 4_096;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum GeneratorCoverageDispositionV1 {
    Complete,
    ZeroEligibleSignals,
    PolicyDisabledUpdates,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct GeneratorCoverageExclusionV1 {
    pub parameter_id: StableId,
    pub reason_id: StableId,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GeneratorCoverageRequestV1 {
    pub expected_parameter_ids: Vec<StableId>,
    pub exclusions: Vec<GeneratorCoverageExclusionV1>,
    /// Exact current owner-frontier cut used to enumerate expected parameters,
    /// signals and exclusions. A detached or zero frontier is never accepted.
    pub owner_frontier_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GeneratorCoverageReceiptV1 {
    pub selected_artifact_digest: Digest32,
    pub window: ProposalWindowV2,
    pub mutation_grammar_digest: Digest32,
    pub expected_parameter_set_digest: Digest32,
    pub signal_parameter_set_digest: Digest32,
    pub exclusion_set_digest: Digest32,
    pub scale_policy_digest: Digest32,
    pub owner_frontier_digest: Digest32,
    pub expected_parameter_count: u32,
    pub signal_parameter_count: u32,
    pub excluded_parameter_count: u32,
    pub disposition: GeneratorCoverageDispositionV1,
    pub coverage_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum GeneratorCoverageErrorV1 {
    MutationPolicy(ParameterMutationPolicyErrorV1),
    ContextMismatch,
    EmptyDigest(&'static str),
    ExpectedParameterCountOutOfRange,
    DuplicateExpectedParameter(String),
    DuplicateSignalParameter(String),
    DuplicateExclusion(String),
    UnknownSignalParameter(String),
    UnknownExclusion(String),
    SignalExclusionOverlap(String),
    MissingCoverage(String),
    InvalidDisposition,
    CoverageDigestMismatch,
    Arithmetic,
}

impl fmt::Display for GeneratorCoverageErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for GeneratorCoverageErrorV1 {}
impl From<ParameterMutationPolicyErrorV1> for GeneratorCoverageErrorV1 {
    fn from(value: ParameterMutationPolicyErrorV1) -> Self {
        Self::MutationPolicy(value)
    }
}

pub fn build_generator_coverage_receipt_v1(
    profile: &ParameterGeneratorProfileV3,
    mut request: GeneratorCoverageRequestV1,
) -> Result<GeneratorCoverageReceiptV1, GeneratorCoverageErrorV1> {
    verify_parameter_mutation_policy_v1(&profile.mutation_policy)?;
    if profile.selected_artifact_digest.is_zero() {
        return Err(GeneratorCoverageErrorV1::EmptyDigest("selected artifact"));
    }
    if profile.window.window_digest.is_zero() {
        return Err(GeneratorCoverageErrorV1::EmptyDigest("window"));
    }
    if profile.mutation_policy.selected_artifact_digest != profile.selected_artifact_digest
        || profile.mutation_policy.window != profile.window
    {
        return Err(GeneratorCoverageErrorV1::ContextMismatch);
    }
    if request.owner_frontier_digest.is_zero() {
        return Err(GeneratorCoverageErrorV1::EmptyDigest("owner frontier"));
    }
    if !(1..=MAX_COVERAGE_PARAMETERS_V1).contains(&request.expected_parameter_ids.len()) {
        return Err(GeneratorCoverageErrorV1::ExpectedParameterCountOutOfRange);
    }

    request.expected_parameter_ids.sort();
    if let Some(duplicate) = request
        .expected_parameter_ids
        .windows(2)
        .find(|pair| pair[0] == pair[1])
        .map(|pair| pair[0].to_string())
    {
        return Err(GeneratorCoverageErrorV1::DuplicateExpectedParameter(
            duplicate,
        ));
    }
    let expected = request
        .expected_parameter_ids
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>();

    let mut signals = profile
        .signals
        .iter()
        .map(|signal| {
            (
                signal.parameter_id.clone(),
                signal.layer_id.clone(),
                signal.evidence_digest,
            )
        })
        .collect::<Vec<_>>();
    signals.sort_by(|left, right| left.0.cmp(&right.0));
    if let Some(duplicate) = signals
        .windows(2)
        .find(|pair| pair[0].0 == pair[1].0)
        .map(|pair| pair[0].0.to_string())
    {
        return Err(GeneratorCoverageErrorV1::DuplicateSignalParameter(
            duplicate,
        ));
    }
    for (parameter_id, _, evidence_digest) in &signals {
        if !expected.contains(parameter_id) {
            return Err(GeneratorCoverageErrorV1::UnknownSignalParameter(
                parameter_id.to_string(),
            ));
        }
        if evidence_digest.is_zero() {
            return Err(GeneratorCoverageErrorV1::EmptyDigest("signal evidence"));
        }
    }

    request.exclusions.sort();
    if let Some(duplicate) = request
        .exclusions
        .windows(2)
        .find(|pair| pair[0].parameter_id == pair[1].parameter_id)
        .map(|pair| pair[0].parameter_id.to_string())
    {
        return Err(GeneratorCoverageErrorV1::DuplicateExclusion(duplicate));
    }
    let signal_ids = signals
        .iter()
        .map(|(parameter_id, _, _)| parameter_id.clone())
        .collect::<BTreeSet<_>>();
    let mut excluded_ids = BTreeSet::new();
    for exclusion in &request.exclusions {
        if !expected.contains(&exclusion.parameter_id) {
            return Err(GeneratorCoverageErrorV1::UnknownExclusion(
                exclusion.parameter_id.to_string(),
            ));
        }
        if signal_ids.contains(&exclusion.parameter_id) {
            return Err(GeneratorCoverageErrorV1::SignalExclusionOverlap(
                exclusion.parameter_id.to_string(),
            ));
        }
        if exclusion.evidence_digest.is_zero() {
            return Err(GeneratorCoverageErrorV1::EmptyDigest(
                "exclusion evidence",
            ));
        }
        excluded_ids.insert(exclusion.parameter_id.clone());
    }
    for parameter_id in &expected {
        if !signal_ids.contains(parameter_id) && !excluded_ids.contains(parameter_id) {
            return Err(GeneratorCoverageErrorV1::MissingCoverage(
                parameter_id.to_string(),
            ));
        }
    }

    let disposition = if profile.update_scales.is_empty() {
        GeneratorCoverageDispositionV1::PolicyDisabledUpdates
    } else if signals.is_empty() {
        GeneratorCoverageDispositionV1::ZeroEligibleSignals
    } else {
        GeneratorCoverageDispositionV1::Complete
    };
    if disposition == GeneratorCoverageDispositionV1::ZeroEligibleSignals
        && excluded_ids.len() != expected.len()
    {
        return Err(GeneratorCoverageErrorV1::InvalidDisposition);
    }

    let expected_parameter_set_digest = digest_expected(&request.expected_parameter_ids)?;
    let signal_parameter_set_digest = digest_signals(&signals)?;
    let exclusion_set_digest = digest_exclusions(&request.exclusions)?;
    let scale_policy_digest = digest_scales(profile)?;
    let expected_parameter_count = u32::try_from(expected.len())
        .map_err(|_| GeneratorCoverageErrorV1::Arithmetic)?;
    let signal_parameter_count =
        u32::try_from(signals.len()).map_err(|_| GeneratorCoverageErrorV1::Arithmetic)?;
    let excluded_parameter_count = u32::try_from(request.exclusions.len())
        .map_err(|_| GeneratorCoverageErrorV1::Arithmetic)?;

    let mut receipt = GeneratorCoverageReceiptV1 {
        selected_artifact_digest: profile.selected_artifact_digest,
        window: profile.window.clone(),
        mutation_grammar_digest: profile.mutation_policy.mutation_grammar_digest,
        expected_parameter_set_digest,
        signal_parameter_set_digest,
        exclusion_set_digest,
        scale_policy_digest,
        owner_frontier_digest: request.owner_frontier_digest,
        expected_parameter_count,
        signal_parameter_count,
        excluded_parameter_count,
        disposition,
        coverage_digest: Digest32::ZERO,
    };
    receipt.coverage_digest = digest_receipt(&receipt)?;
    Ok(receipt)
}

pub fn verify_generator_coverage_receipt_v1(
    profile: &ParameterGeneratorProfileV3,
    request: GeneratorCoverageRequestV1,
    receipt: &GeneratorCoverageReceiptV1,
) -> Result<(), GeneratorCoverageErrorV1> {
    let expected = build_generator_coverage_receipt_v1(profile, request)?;
    if &expected != receipt
        || receipt.coverage_digest.is_zero()
        || digest_receipt(receipt)? != receipt.coverage_digest
    {
        return Err(GeneratorCoverageErrorV1::CoverageDigestMismatch);
    }
    Ok(())
}

/// Exact bytes signed by the independent Observer for the coverage decision.
#[must_use]
pub fn generator_coverage_signing_payload_v1(receipt: &GeneratorCoverageReceiptV1) -> Vec<u8> {
    let mut bytes = b"hepta.plasticity.generator-coverage-signing.v1\0".to_vec();
    bytes.extend_from_slice(receipt.coverage_digest.as_array());
    bytes
}

fn digest_expected(values: &[StableId]) -> Result<Digest32, GeneratorCoverageErrorV1> {
    let mut bytes = b"hepta.plasticity.generator-coverage-expected.v1\0".to_vec();
    push_len(&mut bytes, values.len())?;
    for value in values {
        push_id(&mut bytes, value)?;
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_signals(
    values: &[(StableId, StableId, Digest32)],
) -> Result<Digest32, GeneratorCoverageErrorV1> {
    let mut bytes = b"hepta.plasticity.generator-coverage-signals.v1\0".to_vec();
    push_len(&mut bytes, values.len())?;
    for (parameter_id, layer_id, evidence_digest) in values {
        push_id(&mut bytes, parameter_id)?;
        push_id(&mut bytes, layer_id)?;
        bytes.extend_from_slice(evidence_digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_exclusions(
    values: &[GeneratorCoverageExclusionV1],
) -> Result<Digest32, GeneratorCoverageErrorV1> {
    let mut bytes = b"hepta.plasticity.generator-coverage-exclusions.v1\0".to_vec();
    push_len(&mut bytes, values.len())?;
    for value in values {
        push_id(&mut bytes, &value.parameter_id)?;
        push_id(&mut bytes, &value.reason_id)?;
        bytes.extend_from_slice(value.evidence_digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_scales(
    profile: &ParameterGeneratorProfileV3,
) -> Result<Digest32, GeneratorCoverageErrorV1> {
    let mut scales = profile.update_scales.clone();
    scales.sort();
    let mut bytes = b"hepta.plasticity.generator-coverage-scales.v1\0".to_vec();
    push_len(&mut bytes, scales.len())?;
    for scale in scales {
        bytes.extend_from_slice(&scale.raw().to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_receipt(
    receipt: &GeneratorCoverageReceiptV1,
) -> Result<Digest32, GeneratorCoverageErrorV1> {
    let mut bytes = b"hepta.plasticity.generator-coverage-receipt.v1\0".to_vec();
    bytes.extend_from_slice(receipt.selected_artifact_digest.as_array());
    push_id(&mut bytes, &receipt.window.window_id)?;
    bytes.extend_from_slice(receipt.window.window_digest.as_array());
    for digest in [
        receipt.mutation_grammar_digest,
        receipt.expected_parameter_set_digest,
        receipt.signal_parameter_set_digest,
        receipt.exclusion_set_digest,
        receipt.scale_policy_digest,
        receipt.owner_frontier_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&receipt.expected_parameter_count.to_be_bytes());
    bytes.extend_from_slice(&receipt.signal_parameter_count.to_be_bytes());
    bytes.extend_from_slice(&receipt.excluded_parameter_count.to_be_bytes());
    bytes.push(match receipt.disposition {
        GeneratorCoverageDispositionV1::Complete => 0,
        GeneratorCoverageDispositionV1::ZeroEligibleSignals => 1,
        GeneratorCoverageDispositionV1::PolicyDisabledUpdates => 2,
    });
    Ok(Digest32::of_bytes(&bytes))
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), GeneratorCoverageErrorV1> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| GeneratorCoverageErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

fn push_len(bytes: &mut Vec<u8>, value: usize) -> Result<(), GeneratorCoverageErrorV1> {
    let value = u32::try_from(value).map_err(|_| GeneratorCoverageErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&value.to_be_bytes());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_types::FixedQ32;

    use crate::LayerNormDenominatorV2;
    use crate::ParameterMutationRuleV1;
    use crate::ParameterMutationSurfaceV1;
    use crate::ParameterPlasticitySignalV3;
    use crate::build_parameter_mutation_policy_v1;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }
    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }
    fn window() -> ProposalWindowV2 {
        ProposalWindowV2 {
            window_id: id("window:coverage"),
            window_digest: digest(b"window"),
        }
    }
    fn profile(with_signal: bool, with_scale: bool) -> ParameterGeneratorProfileV3 {
        let artifact = digest(b"artifact");
        let rules = ["parameter:a", "parameter:b"]
            .into_iter()
            .map(|parameter| ParameterMutationRuleV1 {
                parameter_id: id(parameter),
                layer_id: id("layer:a"),
                surface: ParameterMutationSurfaceV1::LearnableParameter,
                minimum_delta: FixedQ32::from_raw(-100),
                maximum_delta: FixedQ32::from_raw(100),
            })
            .collect();
        ParameterGeneratorProfileV3 {
            selected_artifact_digest: artifact,
            window: window(),
            norm_layers: vec![LayerNormDenominatorV2 {
                layer_id: id("layer:a"),
                baseline_squared_l2_raw_q64: 1_000_000,
            }],
            mutation_policy: build_parameter_mutation_policy_v1(
                id("policy:coverage"),
                digest(b"grammar"),
                artifact,
                window(),
                rules,
            )
            .expect("policy"),
            update_scales: if with_scale {
                vec![FixedQ32::from_raw(1)]
            } else {
                Vec::new()
            },
            signals: if with_signal {
                vec![ParameterPlasticitySignalV3 {
                    layer_id: id("layer:a"),
                    parameter_id: id("parameter:a"),
                    eligibility: FixedQ32::from_raw(1),
                    modulator: FixedQ32::from_raw(1),
                    learning_rate: FixedQ32::from_raw(1),
                    lower_bound: FixedQ32::from_raw(-10),
                    upper_bound: FixedQ32::from_raw(10),
                    evidence_digest: digest(b"signal"),
                }]
            } else {
                Vec::new()
            },
        }
    }
    fn request(exclude_a: bool) -> GeneratorCoverageRequestV1 {
        let mut exclusions = vec![GeneratorCoverageExclusionV1 {
            parameter_id: id("parameter:b"),
            reason_id: id("reason:held-back"),
            evidence_digest: digest(b"excluded-b"),
        }];
        if exclude_a {
            exclusions.push(GeneratorCoverageExclusionV1 {
                parameter_id: id("parameter:a"),
                reason_id: id("reason:no-current-signal"),
                evidence_digest: digest(b"excluded-a"),
            });
        }
        GeneratorCoverageRequestV1 {
            expected_parameter_ids: vec![id("parameter:b"), id("parameter:a")],
            exclusions,
            owner_frontier_digest: digest(b"frontier"),
        }
    }

    #[test]
    fn complete_coverage_is_canonical_and_verifiable() {
        let profile = profile(true, true);
        let receipt = build_generator_coverage_receipt_v1(&profile, request(false))
            .expect("coverage receipt");
        assert_eq!(receipt.disposition, GeneratorCoverageDispositionV1::Complete);
        assert_eq!(receipt.expected_parameter_count, 2);
        assert_eq!(receipt.signal_parameter_count, 1);
        assert_eq!(receipt.excluded_parameter_count, 1);
        verify_generator_coverage_receipt_v1(&profile, request(false), &receipt)
            .expect("verify");

        let mut reordered = request(false);
        reordered.expected_parameter_ids.reverse();
        let reordered = build_generator_coverage_receipt_v1(&profile, reordered)
            .expect("reordered coverage");
        assert_eq!(receipt, reordered);
    }

    #[test]
    fn zero_signal_and_disabled_scale_are_distinct_terminals() {
        let zero = build_generator_coverage_receipt_v1(&profile(false, true), request(true))
            .expect("zero eligible");
        assert_eq!(
            zero.disposition,
            GeneratorCoverageDispositionV1::ZeroEligibleSignals
        );

        let disabled = build_generator_coverage_receipt_v1(&profile(true, false), request(false))
            .expect("policy disabled");
        assert_eq!(
            disabled.disposition,
            GeneratorCoverageDispositionV1::PolicyDisabledUpdates
        );
        assert_ne!(zero.coverage_digest, disabled.coverage_digest);
    }

    #[test]
    fn every_expected_parameter_must_be_accounted_for() {
        let mut incomplete = request(false);
        incomplete.exclusions.clear();
        assert!(matches!(
            build_generator_coverage_receipt_v1(&profile(true, true), incomplete),
            Err(GeneratorCoverageErrorV1::MissingCoverage(_))
        ));
    }

    #[test]
    fn receipt_digest_binds_frontier_grammar_scales_and_exclusions() {
        let profile = profile(true, true);
        let baseline = build_generator_coverage_receipt_v1(&profile, request(false))
            .expect("baseline");

        let mut frontier = request(false);
        frontier.owner_frontier_digest = digest(b"other-frontier");
        assert_ne!(
            baseline.coverage_digest,
            build_generator_coverage_receipt_v1(&profile, frontier)
                .expect("frontier")
                .coverage_digest
        );

        let mut grammar = profile.clone();
        grammar.mutation_policy = build_parameter_mutation_policy_v1(
            id("policy:coverage"),
            digest(b"other-grammar"),
            grammar.selected_artifact_digest,
            grammar.window.clone(),
            grammar.mutation_policy.rules.clone(),
        )
        .expect("grammar policy");
        assert_ne!(
            baseline.coverage_digest,
            build_generator_coverage_receipt_v1(&grammar, request(false))
                .expect("grammar")
                .coverage_digest
        );

        let mut exclusion = request(false);
        exclusion.exclusions[0].reason_id = id("reason:security-hold");
        assert_ne!(
            baseline.coverage_digest,
            build_generator_coverage_receipt_v1(&profile, exclusion)
                .expect("exclusion")
                .coverage_digest
        );
    }
}
