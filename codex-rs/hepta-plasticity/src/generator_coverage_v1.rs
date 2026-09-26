//! Auditable coverage proof for the bounded parameter generator.
//!
//! A coverage receipt proves that every parameter expected by the frozen
//! control.engineering grammar is either represented by an exact generator signal
//! or has one explicit, evidence-bound exclusion reason. It grants no authority to
//! select, train, install, activate, promote or release a candidate.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::ProposalWindowV2;

const MAX_COVERAGE_PARAMETERS_V1: usize = 4_096;
const MAX_COVERAGE_SCALES_V1: usize = 31;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum GeneratorCoverageExclusionReasonV1 {
    OwnerEvidenceUnavailable,
    PolicyProtected,
    BoundsEmpty,
    ExplicitlyDisabled,
    MissingOwnerBinding,
}

impl GeneratorCoverageExclusionReasonV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::OwnerEvidenceUnavailable => 0,
            Self::PolicyProtected => 1,
            Self::BoundsEmpty => 2,
            Self::ExplicitlyDisabled => 3,
            Self::MissingOwnerBinding => 4,
        }
    }
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct GeneratorCoverageExclusionV1 {
    pub parameter_id: StableId,
    pub reason: GeneratorCoverageExclusionReasonV1,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum GeneratorCoverageDispositionV1 {
    Covered,
    ZeroEligibleSignals,
    PolicyDisabledUpdates,
}

impl GeneratorCoverageDispositionV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Covered => 0,
            Self::ZeroEligibleSignals => 1,
            Self::PolicyDisabledUpdates => 2,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GeneratorCoverageReceiptV1 {
    pub coverage_id: StableId,
    pub selected_artifact_digest: Digest32,
    pub window: ProposalWindowV2,
    pub mutation_grammar_digest: Digest32,
    pub expected_parameters: Vec<StableId>,
    pub expected_parameter_set_digest: Digest32,
    pub actual_signal_parameters: Vec<StableId>,
    pub actual_signal_set_digest: Digest32,
    pub missing_parameters: Vec<GeneratorCoverageExclusionV1>,
    pub update_scales: Vec<FixedQ32>,
    pub scale_policy_digest: Digest32,
    pub owner_frontier_digest: Digest32,
    pub disposition: GeneratorCoverageDispositionV1,
    pub coverage_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum GeneratorCoverageErrorV1 {
    EmptyDigest(&'static str),
    ParameterLimit,
    ScaleLimit,
    DuplicateExpected(String),
    DuplicateActual(String),
    DuplicateExclusion(String),
    UnexpectedActual(String),
    MissingCoverage(String),
    UnexpectedExclusion(String),
    EmptyExclusionEvidence(String),
    InvalidScale,
    DuplicateScale,
    InvalidDisposition,
    DigestMismatch,
    Arithmetic,
}

impl fmt::Display for GeneratorCoverageErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for GeneratorCoverageErrorV1 {}

#[allow(clippy::too_many_arguments)]
pub fn build_generator_coverage_receipt_v1(
    coverage_id: StableId,
    selected_artifact_digest: Digest32,
    window: ProposalWindowV2,
    mutation_grammar_digest: Digest32,
    mut expected_parameters: Vec<StableId>,
    mut actual_signal_parameters: Vec<StableId>,
    mut missing_parameters: Vec<GeneratorCoverageExclusionV1>,
    mut update_scales: Vec<FixedQ32>,
    owner_frontier_digest: Digest32,
    disposition: GeneratorCoverageDispositionV1,
) -> Result<GeneratorCoverageReceiptV1, GeneratorCoverageErrorV1> {
    validate_context(
        selected_artifact_digest,
        &window,
        mutation_grammar_digest,
        owner_frontier_digest,
    )?;
    canonicalize_parameters(
        &mut expected_parameters,
        &mut actual_signal_parameters,
        &mut missing_parameters,
        &mut update_scales,
    )?;
    validate_partition(
        &expected_parameters,
        &actual_signal_parameters,
        &missing_parameters,
    )?;
    validate_disposition(
        disposition,
        &expected_parameters,
        &actual_signal_parameters,
        &update_scales,
    )?;

    let expected_parameter_set_digest = digest_parameter_set(
        b"hepta.plasticity.generator-coverage.expected.v1\0",
        &expected_parameters,
    )?;
    let actual_signal_set_digest = digest_parameter_set(
        b"hepta.plasticity.generator-coverage.actual.v1\0",
        &actual_signal_parameters,
    )?;
    let scale_policy_digest = digest_scales(&update_scales)?;

    let mut receipt = GeneratorCoverageReceiptV1 {
        coverage_id,
        selected_artifact_digest,
        window,
        mutation_grammar_digest,
        expected_parameters,
        expected_parameter_set_digest,
        actual_signal_parameters,
        actual_signal_set_digest,
        missing_parameters,
        update_scales,
        scale_policy_digest,
        owner_frontier_digest,
        disposition,
        coverage_digest: Digest32::ZERO,
    };
    receipt.coverage_digest = digest_coverage(&receipt)?;
    Ok(receipt)
}

pub fn verify_generator_coverage_receipt_v1(
    receipt: &GeneratorCoverageReceiptV1,
) -> Result<(), GeneratorCoverageErrorV1> {
    let expected = build_generator_coverage_receipt_v1(
        receipt.coverage_id.clone(),
        receipt.selected_artifact_digest,
        receipt.window.clone(),
        receipt.mutation_grammar_digest,
        receipt.expected_parameters.clone(),
        receipt.actual_signal_parameters.clone(),
        receipt.missing_parameters.clone(),
        receipt.update_scales.clone(),
        receipt.owner_frontier_digest,
        receipt.disposition,
    )?;
    if &expected != receipt || receipt.coverage_digest.is_zero() {
        return Err(GeneratorCoverageErrorV1::DigestMismatch);
    }
    Ok(())
}

/// Exact bytes signed by the independent Observer at the product boundary.
#[must_use]
pub fn generator_coverage_signing_payload_v1(
    receipt: &GeneratorCoverageReceiptV1,
) -> Vec<u8> {
    let mut bytes = b"hepta.plasticity.generator-coverage-signing.v1\0".to_vec();
    bytes.extend_from_slice(receipt.coverage_digest.as_array());
    bytes
}

fn validate_context(
    selected_artifact_digest: Digest32,
    window: &ProposalWindowV2,
    mutation_grammar_digest: Digest32,
    owner_frontier_digest: Digest32,
) -> Result<(), GeneratorCoverageErrorV1> {
    for (name, digest) in [
        ("selected artifact", selected_artifact_digest),
        ("window", window.window_digest),
        ("mutation grammar", mutation_grammar_digest),
        ("owner frontier", owner_frontier_digest),
    ] {
        if digest.is_zero() {
            return Err(GeneratorCoverageErrorV1::EmptyDigest(name));
        }
    }
    Ok(())
}

fn canonicalize_parameters(
    expected: &mut Vec<StableId>,
    actual: &mut Vec<StableId>,
    exclusions: &mut Vec<GeneratorCoverageExclusionV1>,
    scales: &mut Vec<FixedQ32>,
) -> Result<(), GeneratorCoverageErrorV1> {
    if expected.len() > MAX_COVERAGE_PARAMETERS_V1
        || actual.len() > MAX_COVERAGE_PARAMETERS_V1
        || exclusions.len() > MAX_COVERAGE_PARAMETERS_V1
    {
        return Err(GeneratorCoverageErrorV1::ParameterLimit);
    }
    if scales.len() > MAX_COVERAGE_SCALES_V1 {
        return Err(GeneratorCoverageErrorV1::ScaleLimit);
    }

    expected.sort();
    actual.sort();
    exclusions.sort();
    scales.sort();

    reject_duplicate_ids(expected, |id| {
        GeneratorCoverageErrorV1::DuplicateExpected(id.to_string())
    })?;
    reject_duplicate_ids(actual, |id| {
        GeneratorCoverageErrorV1::DuplicateActual(id.to_string())
    })?;
    if exclusions
        .windows(2)
        .any(|pair| pair[0].parameter_id == pair[1].parameter_id)
    {
        return Err(GeneratorCoverageErrorV1::DuplicateExclusion(
            exclusions
                .windows(2)
                .find(|pair| pair[0].parameter_id == pair[1].parameter_id)
                .map(|pair| pair[0].parameter_id.to_string())
                .unwrap_or_else(|| "unknown".to_string()),
        ));
    }
    for exclusion in exclusions.iter() {
        if exclusion.evidence_digest.is_zero() {
            return Err(GeneratorCoverageErrorV1::EmptyExclusionEvidence(
                exclusion.parameter_id.to_string(),
            ));
        }
    }
    if scales.windows(2).any(|pair| pair[0] == pair[1]) {
        return Err(GeneratorCoverageErrorV1::DuplicateScale);
    }
    if scales
        .iter()
        .any(|scale| *scale <= FixedQ32::ZERO || *scale > FixedQ32::ONE)
    {
        return Err(GeneratorCoverageErrorV1::InvalidScale);
    }
    Ok(())
}

fn reject_duplicate_ids(
    values: &[StableId],
    error: impl Fn(&StableId) -> GeneratorCoverageErrorV1,
) -> Result<(), GeneratorCoverageErrorV1> {
    if let Some(pair) = values.windows(2).find(|pair| pair[0] == pair[1]) {
        return Err(error(&pair[0]));
    }
    Ok(())
}

fn validate_partition(
    expected: &[StableId],
    actual: &[StableId],
    exclusions: &[GeneratorCoverageExclusionV1],
) -> Result<(), GeneratorCoverageErrorV1> {
    let expected_set = expected.iter().cloned().collect::<BTreeSet<_>>();
    let actual_set = actual.iter().cloned().collect::<BTreeSet<_>>();
    let exclusion_set = exclusions
        .iter()
        .map(|value| value.parameter_id.clone())
        .collect::<BTreeSet<_>>();

    if let Some(unexpected) = actual_set.difference(&expected_set).next() {
        return Err(GeneratorCoverageErrorV1::UnexpectedActual(
            unexpected.to_string(),
        ));
    }
    if let Some(unexpected) = exclusion_set.difference(&expected_set).next() {
        return Err(GeneratorCoverageErrorV1::UnexpectedExclusion(
            unexpected.to_string(),
        ));
    }
    if let Some(overlap) = actual_set.intersection(&exclusion_set).next() {
        return Err(GeneratorCoverageErrorV1::UnexpectedExclusion(
            overlap.to_string(),
        ));
    }
    let covered = actual_set
        .union(&exclusion_set)
        .cloned()
        .collect::<BTreeSet<_>>();
    if let Some(missing) = expected_set.difference(&covered).next() {
        return Err(GeneratorCoverageErrorV1::MissingCoverage(
            missing.to_string(),
        ));
    }
    Ok(())
}

fn validate_disposition(
    disposition: GeneratorCoverageDispositionV1,
    expected: &[StableId],
    actual: &[StableId],
    scales: &[FixedQ32],
) -> Result<(), GeneratorCoverageErrorV1> {
    let valid = match disposition {
        GeneratorCoverageDispositionV1::Covered => {
            !expected.is_empty() && !actual.is_empty() && !scales.is_empty()
        }
        GeneratorCoverageDispositionV1::ZeroEligibleSignals => {
            !expected.is_empty() && actual.is_empty() && !scales.is_empty()
        }
        GeneratorCoverageDispositionV1::PolicyDisabledUpdates => {
            actual.is_empty() && scales.is_empty()
        }
    };
    valid
        .then_some(())
        .ok_or(GeneratorCoverageErrorV1::InvalidDisposition)
}

fn digest_parameter_set(
    domain: &[u8],
    values: &[StableId],
) -> Result<Digest32, GeneratorCoverageErrorV1> {
    let mut bytes = domain.to_vec();
    push_len(&mut bytes, values.len())?;
    for value in values {
        push_id(&mut bytes, value)?;
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

fn digest_coverage(
    receipt: &GeneratorCoverageReceiptV1,
) -> Result<Digest32, GeneratorCoverageErrorV1> {
    let mut bytes = b"hepta.plasticity.generator-coverage.v1\0".to_vec();
    push_id(&mut bytes, &receipt.coverage_id)?;
    bytes.extend_from_slice(receipt.selected_artifact_digest.as_array());
    push_id(&mut bytes, &receipt.window.window_id)?;
    bytes.extend_from_slice(receipt.window.window_digest.as_array());
    for digest in [
        receipt.mutation_grammar_digest,
        receipt.expected_parameter_set_digest,
        receipt.actual_signal_set_digest,
        receipt.scale_policy_digest,
        receipt.owner_frontier_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.push(receipt.disposition.tag());
    push_len(&mut bytes, receipt.missing_parameters.len())?;
    for exclusion in &receipt.missing_parameters {
        push_id(&mut bytes, &exclusion.parameter_id)?;
        bytes.push(exclusion.reason.tag());
        bytes.extend_from_slice(exclusion.evidence_digest.as_array());
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

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid id")
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
    fn exclusion(parameter: &str) -> GeneratorCoverageExclusionV1 {
        GeneratorCoverageExclusionV1 {
            parameter_id: id(parameter),
            reason: GeneratorCoverageExclusionReasonV1::OwnerEvidenceUnavailable,
            evidence_digest: digest(parameter.as_bytes()),
        }
    }

    #[test]
    fn covered_receipt_is_canonical_and_verifiable() {
        let first = build_generator_coverage_receipt_v1(
            id("coverage:1"),
            digest(b"artifact"),
            window(),
            digest(b"grammar"),
            vec![id("parameter:b"), id("parameter:a")],
            vec![id("parameter:a")],
            vec![exclusion("parameter:b")],
            vec![FixedQ32::ONE, FixedQ32::from_raw(1)],
            digest(b"owner-frontier"),
            GeneratorCoverageDispositionV1::Covered,
        )
        .expect("coverage");
        let second = build_generator_coverage_receipt_v1(
            id("coverage:1"),
            digest(b"artifact"),
            window(),
            digest(b"grammar"),
            vec![id("parameter:a"), id("parameter:b")],
            vec![id("parameter:a")],
            vec![exclusion("parameter:b")],
            vec![FixedQ32::from_raw(1), FixedQ32::ONE],
            digest(b"owner-frontier"),
            GeneratorCoverageDispositionV1::Covered,
        )
        .expect("coverage");
        assert_eq!(first, second);
        verify_generator_coverage_receipt_v1(&first).expect("verify");
        assert!(!first.coverage_digest.is_zero());
    }

    #[test]
    fn empty_profiles_require_explicit_terminal_dispositions() {
        let zero_signals = build_generator_coverage_receipt_v1(
            id("coverage:zero-signals"),
            digest(b"artifact"),
            window(),
            digest(b"grammar"),
            vec![id("parameter:a")],
            Vec::new(),
            vec![exclusion("parameter:a")],
            vec![FixedQ32::ONE],
            digest(b"owner-frontier"),
            GeneratorCoverageDispositionV1::ZeroEligibleSignals,
        )
        .expect("zero signals");
        assert_eq!(
            zero_signals.disposition,
            GeneratorCoverageDispositionV1::ZeroEligibleSignals
        );

        let disabled = build_generator_coverage_receipt_v1(
            id("coverage:disabled"),
            digest(b"artifact"),
            window(),
            digest(b"grammar"),
            vec![id("parameter:a")],
            Vec::new(),
            vec![exclusion("parameter:a")],
            Vec::new(),
            digest(b"owner-frontier"),
            GeneratorCoverageDispositionV1::PolicyDisabledUpdates,
        )
        .expect("disabled");
        assert_eq!(
            disabled.disposition,
            GeneratorCoverageDispositionV1::PolicyDisabledUpdates
        );
    }

    #[test]
    fn unexplained_omission_and_ambiguous_no_update_fail_closed() {
        assert!(matches!(
            build_generator_coverage_receipt_v1(
                id("coverage:missing"),
                digest(b"artifact"),
                window(),
                digest(b"grammar"),
                vec![id("parameter:a")],
                Vec::new(),
                Vec::new(),
                vec![FixedQ32::ONE],
                digest(b"owner-frontier"),
                GeneratorCoverageDispositionV1::ZeroEligibleSignals,
            ),
            Err(GeneratorCoverageErrorV1::MissingCoverage(_))
        ));
        assert!(matches!(
            build_generator_coverage_receipt_v1(
                id("coverage:ambiguous"),
                digest(b"artifact"),
                window(),
                digest(b"grammar"),
                vec![id("parameter:a")],
                Vec::new(),
                vec![exclusion("parameter:a")],
                Vec::new(),
                digest(b"owner-frontier"),
                GeneratorCoverageDispositionV1::ZeroEligibleSignals,
            ),
            Err(GeneratorCoverageErrorV1::InvalidDisposition)
        ));
    }
}
