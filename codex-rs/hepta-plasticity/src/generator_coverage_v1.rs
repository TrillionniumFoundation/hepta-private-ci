//! Deterministic coverage proof for governed parameter generation.
//!
//! The V3 generator proves completeness only relative to the supplied search
//! profile. This module binds that profile to the host-declared learnable
//! parameter universe and records every omitted parameter with a typed,
//! evidence-backed reason. It grants no authority to select or apply a candidate.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::ParameterGeneratorProfileV3;
use crate::ParameterMutationPolicyErrorV1;
use crate::ParameterPlasticitySignalV3;
use crate::ProposalWindowV2;
use crate::verify_parameter_mutation_policy_v1;

const MAX_COVERAGE_PARAMETERS_V1: usize = 4_096;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum GeneratorCoverageMissingReasonV1 {
    OwnerUnavailable,
    MissingEligibility,
    MissingModulator,
    MissingNormLayer,
    PolicyProtected,
    PolicyDisabled,
    OutOfBounds,
}

impl GeneratorCoverageMissingReasonV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::OwnerUnavailable => 0,
            Self::MissingEligibility => 1,
            Self::MissingModulator => 2,
            Self::MissingNormLayer => 3,
            Self::PolicyProtected => 4,
            Self::PolicyDisabled => 5,
            Self::OutOfBounds => 6,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GeneratorCoverageMissingParameterV1 {
    pub parameter_id: StableId,
    pub reason: GeneratorCoverageMissingReasonV1,
    /// Owner- or policy-produced evidence for the exact omission reason.
    pub reason_evidence_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum GeneratorCoverageTerminalV1 {
    Ready,
    ZeroEligibleSignals,
    PolicyDisabledUpdates,
}

impl GeneratorCoverageTerminalV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Ready => 0,
            Self::ZeroEligibleSignals => 1,
            Self::PolicyDisabledUpdates => 2,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GeneratorCoverageReceiptV1 {
    pub selected_artifact_digest: Digest32,
    pub window: ProposalWindowV2,
    pub mutation_grammar_digest: Digest32,
    pub owner_frontier_digest: Digest32,
    pub expected_parameter_ids: Vec<StableId>,
    pub actual_parameter_ids: Vec<StableId>,
    pub missing_parameters: Vec<GeneratorCoverageMissingParameterV1>,
    pub expected_learnable_parameter_set_digest: Digest32,
    pub actual_signal_set_digest: Digest32,
    pub missing_parameter_set_digest: Digest32,
    pub scale_policy_digest: Digest32,
    pub terminal: GeneratorCoverageTerminalV1,
    pub coverage_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum GeneratorCoverageErrorV1 {
    EmptyDigest(&'static str),
    ParameterLimit,
    DuplicateExpected(String),
    DuplicateSignal(String),
    DuplicateMissing(String),
    UnexpectedSignal(String),
    MissingPartition,
    EmptyReasonEvidence(String),
    InvalidScale,
    DuplicateScale,
    ContextMismatch,
    MutationPolicy(ParameterMutationPolicyErrorV1),
    DigestMismatch,
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
    mut expected_parameter_ids: Vec<StableId>,
    mut missing_parameters: Vec<GeneratorCoverageMissingParameterV1>,
    owner_frontier_digest: Digest32,
) -> Result<GeneratorCoverageReceiptV1, GeneratorCoverageErrorV1> {
    verify_parameter_mutation_policy_v1(&profile.mutation_policy)?;
    if profile.selected_artifact_digest.is_zero() {
        return Err(GeneratorCoverageErrorV1::EmptyDigest("selected artifact"));
    }
    if profile.window.window_digest.is_zero() {
        return Err(GeneratorCoverageErrorV1::EmptyDigest("window"));
    }
    if owner_frontier_digest.is_zero() {
        return Err(GeneratorCoverageErrorV1::EmptyDigest("owner frontier"));
    }
    if profile.mutation_policy.mutation_grammar_digest.is_zero() {
        return Err(GeneratorCoverageErrorV1::EmptyDigest("mutation grammar"));
    }
    if profile.mutation_policy.selected_artifact_digest != profile.selected_artifact_digest
        || profile.mutation_policy.window != profile.window
    {
        return Err(GeneratorCoverageErrorV1::ContextMismatch);
    }
    if expected_parameter_ids.len() > MAX_COVERAGE_PARAMETERS_V1
        || profile.signals.len() > MAX_COVERAGE_PARAMETERS_V1
        || missing_parameters.len() > MAX_COVERAGE_PARAMETERS_V1
    {
        return Err(GeneratorCoverageErrorV1::ParameterLimit);
    }

    expected_parameter_ids.sort();
    reject_duplicate_ids(
        &expected_parameter_ids,
        GeneratorCoverageErrorV1::DuplicateExpected,
    )?;

    let mut signals = profile.signals.clone();
    signals.sort_by(|left, right| {
        left.parameter_id
            .cmp(&right.parameter_id)
            .then_with(|| left.layer_id.cmp(&right.layer_id))
    });
    let actual_parameter_ids = signals
        .iter()
        .map(|signal| signal.parameter_id.clone())
        .collect::<Vec<_>>();
    reject_duplicate_ids(
        &actual_parameter_ids,
        GeneratorCoverageErrorV1::DuplicateSignal,
    )?;

    missing_parameters.sort_by(|left, right| left.parameter_id.cmp(&right.parameter_id));
    let missing_ids = missing_parameters
        .iter()
        .map(|missing| missing.parameter_id.clone())
        .collect::<Vec<_>>();
    reject_duplicate_ids(&missing_ids, GeneratorCoverageErrorV1::DuplicateMissing)?;
    for missing in &missing_parameters {
        if missing.reason_evidence_digest.is_zero() {
            return Err(GeneratorCoverageErrorV1::EmptyReasonEvidence(
                missing.parameter_id.to_string(),
            ));
        }
    }

    let expected = expected_parameter_ids.iter().cloned().collect::<BTreeSet<_>>();
    let actual = actual_parameter_ids.iter().cloned().collect::<BTreeSet<_>>();
    for parameter_id in &actual_parameter_ids {
        if !expected.contains(parameter_id) {
            return Err(GeneratorCoverageErrorV1::UnexpectedSignal(
                parameter_id.to_string(),
            ));
        }
    }
    let missing = missing_ids.iter().cloned().collect::<BTreeSet<_>>();
    if !actual.is_disjoint(&missing)
        || actual.union(&missing).cloned().collect::<BTreeSet<_>>() != expected
    {
        return Err(GeneratorCoverageErrorV1::MissingPartition);
    }

    let mut scales = profile.update_scales.clone();
    scales.sort();
    if scales.windows(2).any(|pair| pair[0] == pair[1]) {
        return Err(GeneratorCoverageErrorV1::DuplicateScale);
    }
    if scales
        .iter()
        .any(|scale| *scale <= FixedQ32::ZERO || *scale > FixedQ32::ONE)
    {
        return Err(GeneratorCoverageErrorV1::InvalidScale);
    }

    let terminal = if scales.is_empty() {
        GeneratorCoverageTerminalV1::PolicyDisabledUpdates
    } else if signals.is_empty() {
        GeneratorCoverageTerminalV1::ZeroEligibleSignals
    } else {
        GeneratorCoverageTerminalV1::Ready
    };
    let expected_learnable_parameter_set_digest = digest_parameter_ids(
        b"hepta.plasticity.generator-coverage.expected.v1\0",
        &expected_parameter_ids,
    )?;
    let actual_signal_set_digest = digest_signals(&signals)?;
    let missing_parameter_set_digest = digest_missing(&missing_parameters)?;
    let scale_policy_digest = digest_scales(&scales)?;

    let mut receipt = GeneratorCoverageReceiptV1 {
        selected_artifact_digest: profile.selected_artifact_digest,
        window: profile.window.clone(),
        mutation_grammar_digest: profile.mutation_policy.mutation_grammar_digest,
        owner_frontier_digest,
        expected_parameter_ids,
        actual_parameter_ids,
        missing_parameters,
        expected_learnable_parameter_set_digest,
        actual_signal_set_digest,
        missing_parameter_set_digest,
        scale_policy_digest,
        terminal,
        coverage_digest: Digest32::ZERO,
    };
    receipt.coverage_digest = digest_receipt(&receipt)?;
    Ok(receipt)
}

pub fn verify_generator_coverage_receipt_v1(
    profile: &ParameterGeneratorProfileV3,
    receipt: &GeneratorCoverageReceiptV1,
) -> Result<(), GeneratorCoverageErrorV1> {
    let expected = build_generator_coverage_receipt_v1(
        profile,
        receipt.expected_parameter_ids.clone(),
        receipt.missing_parameters.clone(),
        receipt.owner_frontier_digest,
    )?;
    if &expected != receipt {
        return Err(GeneratorCoverageErrorV1::DigestMismatch);
    }
    Ok(())
}

/// Exact bytes signed by the independent Observer before product submission.
pub fn generator_coverage_signing_payload_v1(receipt: &GeneratorCoverageReceiptV1) -> Vec<u8> {
    let mut bytes = b"hepta.plasticity.generator-coverage-observer.v1\0".to_vec();
    bytes.extend_from_slice(receipt.coverage_digest.as_array());
    bytes
}

fn reject_duplicate_ids(
    ids: &[StableId],
    error: fn(String) -> GeneratorCoverageErrorV1,
) -> Result<(), GeneratorCoverageErrorV1> {
    if let Some(pair) = ids.windows(2).find(|pair| pair[0] == pair[1]) {
        return Err(error(pair[0].to_string()));
    }
    Ok(())
}

fn digest_parameter_ids(
    domain: &[u8],
    ids: &[StableId],
) -> Result<Digest32, GeneratorCoverageErrorV1> {
    let mut bytes = domain.to_vec();
    push_len(&mut bytes, ids.len())?;
    for id in ids {
        push_id(&mut bytes, id)?;
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_signals(
    signals: &[ParameterPlasticitySignalV3],
) -> Result<Digest32, GeneratorCoverageErrorV1> {
    let mut bytes = b"hepta.plasticity.generator-coverage.signals.v1\0".to_vec();
    push_len(&mut bytes, signals.len())?;
    for signal in signals {
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
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_missing(
    missing_parameters: &[GeneratorCoverageMissingParameterV1],
) -> Result<Digest32, GeneratorCoverageErrorV1> {
    let mut bytes = b"hepta.plasticity.generator-coverage.missing.v1\0".to_vec();
    push_len(&mut bytes, missing_parameters.len())?;
    for missing in missing_parameters {
        push_id(&mut bytes, &missing.parameter_id)?;
        bytes.push(missing.reason.tag());
        bytes.extend_from_slice(missing.reason_evidence_digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_scales(scales: &[FixedQ32]) -> Result<Digest32, GeneratorCoverageErrorV1> {
    let mut bytes = b"hepta.plasticity.generator-coverage.scales.v1\0".to_vec();
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
        receipt.owner_frontier_digest,
        receipt.expected_learnable_parameter_set_digest,
        receipt.actual_signal_set_digest,
        receipt.missing_parameter_set_digest,
        receipt.scale_policy_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.push(receipt.terminal.tag());
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
    use crate::LayerNormDenominatorV2;
    use crate::ParameterMutationRuleV1;
    use crate::ParameterMutationSurfaceV1;
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
    fn profile(
        signals: Vec<ParameterPlasticitySignalV3>,
        scales: Vec<FixedQ32>,
    ) -> ParameterGeneratorProfileV3 {
        let artifact = digest(b"artifact");
        let mutation_policy = build_parameter_mutation_policy_v1(
            id("policy:coverage"),
            digest(b"grammar"),
            artifact,
            window(),
            vec![
                ParameterMutationRuleV1 {
                    parameter_id: id("parameter:a"),
                    layer_id: id("layer:a"),
                    surface: ParameterMutationSurfaceV1::LearnableParameter,
                    minimum_delta: FixedQ32::from_raw(-100),
                    maximum_delta: FixedQ32::from_raw(100),
                },
                ParameterMutationRuleV1 {
                    parameter_id: id("parameter:b"),
                    layer_id: id("layer:a"),
                    surface: ParameterMutationSurfaceV1::LearnableParameter,
                    minimum_delta: FixedQ32::from_raw(-100),
                    maximum_delta: FixedQ32::from_raw(100),
                },
            ],
        )
        .expect("policy");
        ParameterGeneratorProfileV3 {
            selected_artifact_digest: artifact,
            window: window(),
            norm_layers: vec![LayerNormDenominatorV2 {
                layer_id: id("layer:a"),
                baseline_squared_l2_raw_q64: 1_000_000,
            }],
            mutation_policy,
            update_scales: scales,
            signals,
        }
    }
    fn signal(parameter: &str) -> ParameterPlasticitySignalV3 {
        ParameterPlasticitySignalV3 {
            layer_id: id("layer:a"),
            parameter_id: id(parameter),
            eligibility: FixedQ32::ONE,
            modulator: FixedQ32::ONE,
            learning_rate: FixedQ32::from_raw(1),
            lower_bound: FixedQ32::from_raw(-100),
            upper_bound: FixedQ32::from_raw(100),
            evidence_digest: digest(parameter.as_bytes()),
        }
    }
    fn missing(parameter: &str) -> GeneratorCoverageMissingParameterV1 {
        GeneratorCoverageMissingParameterV1 {
            parameter_id: id(parameter),
            reason: GeneratorCoverageMissingReasonV1::MissingEligibility,
            reason_evidence_digest: digest(format!("missing:{parameter}").as_bytes()),
        }
    }

    #[test]
    fn coverage_is_canonical_and_partitions_expected_parameters() {
        let left = build_generator_coverage_receipt_v1(
            &profile(vec![signal("parameter:a")], vec![FixedQ32::ONE]),
            vec![id("parameter:b"), id("parameter:a")],
            vec![missing("parameter:b")],
            digest(b"frontier"),
        )
        .expect("coverage");
        let right = build_generator_coverage_receipt_v1(
            &profile(vec![signal("parameter:a")], vec![FixedQ32::ONE]),
            vec![id("parameter:a"), id("parameter:b")],
            vec![missing("parameter:b")],
            digest(b"frontier"),
        )
        .expect("coverage");
        assert_eq!(left, right);
        assert_eq!(left.terminal, GeneratorCoverageTerminalV1::Ready);
        verify_generator_coverage_receipt_v1(
            &profile(vec![signal("parameter:a")], vec![FixedQ32::ONE]),
            &left,
        )
        .expect("verify");
    }

    #[test]
    fn zero_signals_and_disabled_scales_are_distinct_terminals() {
        let zero = build_generator_coverage_receipt_v1(
            &profile(Vec::new(), vec![FixedQ32::ONE]),
            vec![id("parameter:a")],
            vec![missing("parameter:a")],
            digest(b"frontier"),
        )
        .expect("zero");
        assert_eq!(
            zero.terminal,
            GeneratorCoverageTerminalV1::ZeroEligibleSignals
        );

        let disabled = build_generator_coverage_receipt_v1(
            &profile(vec![signal("parameter:a")], Vec::new()),
            vec![id("parameter:a")],
            Vec::new(),
            digest(b"frontier"),
        )
        .expect("disabled");
        assert_eq!(
            disabled.terminal,
            GeneratorCoverageTerminalV1::PolicyDisabledUpdates
        );
        assert_ne!(zero.coverage_digest, disabled.coverage_digest);
    }

    #[test]
    fn coverage_rejects_unaccounted_or_tampered_parameters() {
        let result = build_generator_coverage_receipt_v1(
            &profile(vec![signal("parameter:a")], vec![FixedQ32::ONE]),
            vec![id("parameter:a"), id("parameter:b")],
            Vec::new(),
            digest(b"frontier"),
        );
        assert_eq!(result, Err(GeneratorCoverageErrorV1::MissingPartition));

        let mut receipt = build_generator_coverage_receipt_v1(
            &profile(vec![signal("parameter:a")], vec![FixedQ32::ONE]),
            vec![id("parameter:a")],
            Vec::new(),
            digest(b"frontier"),
        )
        .expect("receipt");
        receipt.actual_signal_set_digest = digest(b"tampered");
        assert_eq!(
            verify_generator_coverage_receipt_v1(
                &profile(vec![signal("parameter:a")], vec![FixedQ32::ONE]),
                &receipt,
            ),
            Err(GeneratorCoverageErrorV1::DigestMismatch)
        );
    }
}
