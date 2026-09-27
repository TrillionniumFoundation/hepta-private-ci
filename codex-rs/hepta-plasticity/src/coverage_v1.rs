//! Generator coverage receipts for governed parameter plasticity.
//!
//! The V3 generator proves completeness only relative to its declared profile.
//! This module binds that profile to the expected learnable-parameter inventory,
//! the exact signal set, the scale policy and the current owner frontier.  It is
//! authority-free: a receipt must still be authenticated by an independent
//! Observer at the Agentd product boundary before it can support admission.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ParameterGeneratorProfileV3;
use crate::ProposalWindowV2;

const MAX_COVERAGE_PARAMETERS_V1: usize = 4_096;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum MissingLearnableParameterReasonV1 {
    MissingOwnerEvidence,
    PolicyProtected,
    OutsideDeclaredBounds,
    MissingNormLayer,
    ExplicitlyDisabled,
}

impl MissingLearnableParameterReasonV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::MissingOwnerEvidence => 0,
            Self::PolicyProtected => 1,
            Self::OutsideDeclaredBounds => 2,
            Self::MissingNormLayer => 3,
            Self::ExplicitlyDisabled => 4,
        }
    }
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct MissingLearnableParameterV1 {
    pub parameter_id: StableId,
    pub reason: MissingLearnableParameterReasonV1,
    /// Owner- or policy-produced evidence explaining why this parameter did not
    /// enter the exact signal set.  A zero digest is never accepted.
    pub evidence_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum GeneratorCoverageDispositionV1 {
    Complete,
    /// The expected inventory was frozen, but no parameter had an eligible,
    /// owner-supported signal.  This is a dedicated terminal and is not folded
    /// into an ordinary no-admissible-update result.
    ZeroEligibleSignals,
    /// The selected scale policy intentionally contains no update scale.  This
    /// is a dedicated terminal and requires independent Observer evidence.
    PolicyDisabledUpdates,
    /// Some expected parameters are absent from a non-empty signal profile.
    /// This receipt is auditable but cannot authorize proposal submission.
    Incomplete,
}

impl GeneratorCoverageDispositionV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Complete => 0,
            Self::ZeroEligibleSignals => 1,
            Self::PolicyDisabledUpdates => 2,
            Self::Incomplete => 3,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GeneratorCoverageReceiptV1 {
    pub expected_learnable_parameter_set_digest: Digest32,
    pub expected_parameter_count: u32,
    pub actual_signal_set_digest: Digest32,
    pub actual_signal_count: u32,
    pub missing_parameters: Vec<MissingLearnableParameterV1>,
    pub scale_policy_digest: Digest32,
    pub mutation_grammar_digest: Digest32,
    pub selected_artifact_digest: Digest32,
    pub window: ProposalWindowV2,
    pub owner_frontier_digest: Digest32,
    pub disposition: GeneratorCoverageDispositionV1,
    pub receipt_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum GeneratorCoverageErrorV1 {
    EmptyDigest(&'static str),
    ParameterLimit,
    MissingCount,
    DuplicateMissingParameter(String),
    InvalidDisposition,
    ProfileBinding,
    ReceiptDigestMismatch,
    Arithmetic,
}

impl fmt::Display for GeneratorCoverageErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for GeneratorCoverageErrorV1 {}

pub fn build_generator_coverage_receipt_v1(
    profile: &ParameterGeneratorProfileV3,
    expected_learnable_parameter_set_digest: Digest32,
    expected_parameter_count: u32,
    owner_frontier_digest: Digest32,
    mut missing_parameters: Vec<MissingLearnableParameterV1>,
) -> Result<GeneratorCoverageReceiptV1, GeneratorCoverageErrorV1> {
    missing_parameters.sort();
    validate_missing(expected_parameter_count, &missing_parameters)?;
    let actual_signal_count = u32::try_from(profile.signals.len())
        .map_err(|_| GeneratorCoverageErrorV1::Arithmetic)?;
    let disposition = classify(profile, expected_parameter_count, &missing_parameters)?;
    let mut receipt = GeneratorCoverageReceiptV1 {
        expected_learnable_parameter_set_digest,
        expected_parameter_count,
        actual_signal_set_digest: digest_signal_set(profile)?,
        actual_signal_count,
        missing_parameters,
        scale_policy_digest: digest_scale_policy(profile)?,
        mutation_grammar_digest: profile.mutation_policy.mutation_grammar_digest,
        selected_artifact_digest: profile.selected_artifact_digest,
        window: profile.window.clone(),
        owner_frontier_digest,
        disposition,
        receipt_digest: Digest32::ZERO,
    };
    validate_header(&receipt)?;
    receipt.receipt_digest = digest_receipt(&receipt)?;
    Ok(receipt)
}

pub fn verify_generator_coverage_receipt_v1(
    profile: &ParameterGeneratorProfileV3,
    receipt: &GeneratorCoverageReceiptV1,
) -> Result<(), GeneratorCoverageErrorV1> {
    validate_header(receipt)?;
    validate_missing(receipt.expected_parameter_count, &receipt.missing_parameters)?;
    if receipt.selected_artifact_digest != profile.selected_artifact_digest
        || receipt.window != profile.window
        || receipt.mutation_grammar_digest
            != profile.mutation_policy.mutation_grammar_digest
        || receipt.actual_signal_count
            != u32::try_from(profile.signals.len())
                .map_err(|_| GeneratorCoverageErrorV1::Arithmetic)?
        || receipt.actual_signal_set_digest != digest_signal_set(profile)?
        || receipt.scale_policy_digest != digest_scale_policy(profile)?
        || receipt.disposition
            != classify(
                profile,
                receipt.expected_parameter_count,
                &receipt.missing_parameters,
            )?
    {
        return Err(GeneratorCoverageErrorV1::ProfileBinding);
    }
    if receipt.receipt_digest.is_zero() || receipt.receipt_digest != digest_receipt(receipt)? {
        return Err(GeneratorCoverageErrorV1::ReceiptDigestMismatch);
    }
    Ok(())
}

/// Exact payload signed by the independent Observer at the product boundary.
pub fn generator_coverage_signing_payload_v1(
    receipt: &GeneratorCoverageReceiptV1,
) -> Result<Vec<u8>, GeneratorCoverageErrorV1> {
    if receipt.receipt_digest.is_zero() || receipt.receipt_digest != digest_receipt(receipt)? {
        return Err(GeneratorCoverageErrorV1::ReceiptDigestMismatch);
    }
    let mut bytes = b"hepta.plasticity.generator-coverage-observer.v1\0".to_vec();
    bytes.extend_from_slice(receipt.receipt_digest.as_array());
    Ok(bytes)
}

fn validate_header(receipt: &GeneratorCoverageReceiptV1) -> Result<(), GeneratorCoverageErrorV1> {
    for (name, digest) in [
        (
            "expected learnable parameter set",
            receipt.expected_learnable_parameter_set_digest,
        ),
        ("actual signal set", receipt.actual_signal_set_digest),
        ("scale policy", receipt.scale_policy_digest),
        ("mutation grammar", receipt.mutation_grammar_digest),
        ("selected artifact", receipt.selected_artifact_digest),
        ("window", receipt.window.window_digest),
        ("owner frontier", receipt.owner_frontier_digest),
    ] {
        if digest.is_zero() {
            return Err(GeneratorCoverageErrorV1::EmptyDigest(name));
        }
    }
    let expected = usize::try_from(receipt.expected_parameter_count)
        .map_err(|_| GeneratorCoverageErrorV1::Arithmetic)?;
    let actual = usize::try_from(receipt.actual_signal_count)
        .map_err(|_| GeneratorCoverageErrorV1::Arithmetic)?;
    if expected > MAX_COVERAGE_PARAMETERS_V1 || actual > MAX_COVERAGE_PARAMETERS_V1 {
        return Err(GeneratorCoverageErrorV1::ParameterLimit);
    }
    if actual > expected {
        return Err(GeneratorCoverageErrorV1::MissingCount);
    }
    Ok(())
}

fn validate_missing(
    expected_parameter_count: u32,
    missing_parameters: &[MissingLearnableParameterV1],
) -> Result<(), GeneratorCoverageErrorV1> {
    if missing_parameters.len() > MAX_COVERAGE_PARAMETERS_V1
        || missing_parameters.len()
            > usize::try_from(expected_parameter_count)
                .map_err(|_| GeneratorCoverageErrorV1::Arithmetic)?
    {
        return Err(GeneratorCoverageErrorV1::MissingCount);
    }
    let mut seen = BTreeSet::new();
    for missing in missing_parameters {
        if !seen.insert(missing.parameter_id.clone()) {
            return Err(GeneratorCoverageErrorV1::DuplicateMissingParameter(
                missing.parameter_id.to_string(),
            ));
        }
        if missing.evidence_digest.is_zero() {
            return Err(GeneratorCoverageErrorV1::EmptyDigest(
                "missing-parameter evidence",
            ));
        }
    }
    Ok(())
}

fn classify(
    profile: &ParameterGeneratorProfileV3,
    expected_parameter_count: u32,
    missing_parameters: &[MissingLearnableParameterV1],
) -> Result<GeneratorCoverageDispositionV1, GeneratorCoverageErrorV1> {
    let actual = u32::try_from(profile.signals.len())
        .map_err(|_| GeneratorCoverageErrorV1::Arithmetic)?;
    if actual > expected_parameter_count {
        return Err(GeneratorCoverageErrorV1::MissingCount);
    }
    if profile.update_scales.is_empty() {
        return Ok(GeneratorCoverageDispositionV1::PolicyDisabledUpdates);
    }
    if profile.signals.is_empty() {
        if missing_parameters.len()
            != usize::try_from(expected_parameter_count)
                .map_err(|_| GeneratorCoverageErrorV1::Arithmetic)?
        {
            return Err(GeneratorCoverageErrorV1::MissingCount);
        }
        return Ok(GeneratorCoverageDispositionV1::ZeroEligibleSignals);
    }
    if actual == expected_parameter_count && missing_parameters.is_empty() {
        return Ok(GeneratorCoverageDispositionV1::Complete);
    }
    Ok(GeneratorCoverageDispositionV1::Incomplete)
}

fn digest_signal_set(
    profile: &ParameterGeneratorProfileV3,
) -> Result<Digest32, GeneratorCoverageErrorV1> {
    let mut signals = profile.signals.clone();
    signals.sort_by(|left, right| {
        left.parameter_id
            .cmp(&right.parameter_id)
            .then_with(|| left.layer_id.cmp(&right.layer_id))
    });
    let mut bytes = b"hepta.plasticity.generator-signal-set.v1\0".to_vec();
    push_len(&mut bytes, signals.len())?;
    for signal in signals {
        push_id(&mut bytes, &signal.parameter_id)?;
        push_id(&mut bytes, &signal.layer_id)?;
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

fn digest_scale_policy(
    profile: &ParameterGeneratorProfileV3,
) -> Result<Digest32, GeneratorCoverageErrorV1> {
    let mut scales = profile.update_scales.clone();
    scales.sort();
    let mut bytes = b"hepta.plasticity.generator-scale-policy.v1\0".to_vec();
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
    for digest in [
        receipt.expected_learnable_parameter_set_digest,
        receipt.actual_signal_set_digest,
        receipt.scale_policy_digest,
        receipt.mutation_grammar_digest,
        receipt.selected_artifact_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&receipt.expected_parameter_count.to_be_bytes());
    bytes.extend_from_slice(&receipt.actual_signal_count.to_be_bytes());
    push_id(&mut bytes, &receipt.window.window_id)?;
    bytes.extend_from_slice(receipt.window.window_digest.as_array());
    bytes.extend_from_slice(receipt.owner_frontier_digest.as_array());
    bytes.push(receipt.disposition.tag());
    push_len(&mut bytes, receipt.missing_parameters.len())?;
    for missing in &receipt.missing_parameters {
        push_id(&mut bytes, &missing.parameter_id)?;
        bytes.push(missing.reason.tag());
        bytes.extend_from_slice(missing.evidence_digest.as_array());
    }
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
        StableId::new(value).expect("valid id")
    }
    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }
    fn profile() -> ParameterGeneratorProfileV3 {
        let artifact = digest(b"artifact");
        let window = ProposalWindowV2 {
            window_id: id("window:coverage"),
            window_digest: digest(b"window"),
        };
        let rule = |parameter: &str, layer: &str| ParameterMutationRuleV1 {
            parameter_id: id(parameter),
            layer_id: id(layer),
            surface: ParameterMutationSurfaceV1::LearnableParameter,
            minimum_delta: FixedQ32::from_raw(-100),
            maximum_delta: FixedQ32::from_raw(100),
        };
        ParameterGeneratorProfileV3 {
            selected_artifact_digest: artifact,
            window: window.clone(),
            norm_layers: vec![LayerNormDenominatorV2 {
                layer_id: id("layer:1"),
                baseline_squared_l2_raw_q64: 1_000_000,
            }],
            mutation_policy: build_parameter_mutation_policy_v1(
                id("policy:coverage"),
                digest(b"grammar"),
                artifact,
                window,
                vec![rule("parameter:1", "layer:1"), rule("parameter:2", "layer:1")],
            )
            .expect("policy"),
            update_scales: vec![FixedQ32::ONE, FixedQ32::from_raw(1)],
            signals: vec![
                ParameterPlasticitySignalV3 {
                    layer_id: id("layer:1"),
                    parameter_id: id("parameter:2"),
                    eligibility: FixedQ32::ONE,
                    modulator: FixedQ32::ONE,
                    learning_rate: FixedQ32::ONE,
                    lower_bound: FixedQ32::from_raw(-100),
                    upper_bound: FixedQ32::from_raw(100),
                    evidence_digest: digest(b"signal-2"),
                },
                ParameterPlasticitySignalV3 {
                    layer_id: id("layer:1"),
                    parameter_id: id("parameter:1"),
                    eligibility: FixedQ32::ONE,
                    modulator: FixedQ32::ONE,
                    learning_rate: FixedQ32::ONE,
                    lower_bound: FixedQ32::from_raw(-100),
                    upper_bound: FixedQ32::from_raw(100),
                    evidence_digest: digest(b"signal-1"),
                },
            ],
        }
    }

    #[test]
    fn complete_coverage_is_canonical_and_profile_bound() {
        let profile = profile();
        let first = build_generator_coverage_receipt_v1(
            &profile,
            digest(b"expected-set"),
            2,
            digest(b"owner-frontier"),
            Vec::new(),
        )
        .expect("coverage");
        let mut reordered = profile.clone();
        reordered.signals.reverse();
        reordered.update_scales.reverse();
        let second = build_generator_coverage_receipt_v1(
            &reordered,
            digest(b"expected-set"),
            2,
            digest(b"owner-frontier"),
            Vec::new(),
        )
        .expect("coverage reordered");
        assert_eq!(first, second);
        assert_eq!(first.disposition, GeneratorCoverageDispositionV1::Complete);
        verify_generator_coverage_receipt_v1(&profile, &first).expect("verify");
        assert!(!generator_coverage_signing_payload_v1(&first)
            .expect("payload")
            .is_empty());
    }

    #[test]
    fn zero_signal_and_disabled_policy_are_distinct_terminals() {
        let mut zero = profile();
        zero.signals.clear();
        let missing = vec![
            MissingLearnableParameterV1 {
                parameter_id: id("parameter:1"),
                reason: MissingLearnableParameterReasonV1::MissingOwnerEvidence,
                evidence_digest: digest(b"missing-1"),
            },
            MissingLearnableParameterV1 {
                parameter_id: id("parameter:2"),
                reason: MissingLearnableParameterReasonV1::PolicyProtected,
                evidence_digest: digest(b"missing-2"),
            },
        ];
        let zero_receipt = build_generator_coverage_receipt_v1(
            &zero,
            digest(b"expected-set"),
            2,
            digest(b"owner-frontier"),
            missing,
        )
        .expect("zero receipt");
        assert_eq!(
            zero_receipt.disposition,
            GeneratorCoverageDispositionV1::ZeroEligibleSignals
        );

        let mut disabled = profile();
        disabled.update_scales.clear();
        let disabled_receipt = build_generator_coverage_receipt_v1(
            &disabled,
            digest(b"expected-set"),
            2,
            digest(b"owner-frontier"),
            Vec::new(),
        )
        .expect("disabled receipt");
        assert_eq!(
            disabled_receipt.disposition,
            GeneratorCoverageDispositionV1::PolicyDisabledUpdates
        );
        assert_ne!(zero_receipt.receipt_digest, disabled_receipt.receipt_digest);
    }

    #[test]
    fn incomplete_or_tampered_coverage_cannot_pass_as_complete() {
        let mut partial = profile();
        partial.signals.pop();
        let missing = vec![MissingLearnableParameterV1 {
            parameter_id: id("parameter:2"),
            reason: MissingLearnableParameterReasonV1::MissingOwnerEvidence,
            evidence_digest: digest(b"missing"),
        }];
        let receipt = build_generator_coverage_receipt_v1(
            &partial,
            digest(b"expected-set"),
            2,
            digest(b"owner-frontier"),
            missing,
        )
        .expect("partial");
        assert_eq!(receipt.disposition, GeneratorCoverageDispositionV1::Incomplete);
        let mut tampered = receipt;
        tampered.actual_signal_count = 2;
        assert!(verify_generator_coverage_receipt_v1(&partial, &tampered).is_err());
    }
}
