//! Typed coverage proof for deterministic parameter-candidate generation.
//!
//! A generator digest proves completeness only relative to its supplied profile.
//! This record additionally proves that the profile accounts for every learnable
//! parameter declared by the artifact/window-bound mutation policy. Missing signals
//! are explicit, reasoned and evidence-bound; empty signal or scale sets have
//! distinct terminal dispositions rather than being collapsed into a generic
//! no-admissible-update result.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ParameterGeneratorProfileV3;
use crate::ParameterMutationSurfaceV1;
use crate::ProposalWindowV2;
use crate::verify_parameter_mutation_policy_v1;

const MAX_COVERAGE_PARAMETERS_V1: usize = 4_096;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum GeneratorCoverageDispositionV1 {
    SearchActive,
    ZeroEligibleSignals,
    PolicyDisabledUpdates,
    ZeroEligibleSignalsAndPolicyDisabledUpdates,
}

impl GeneratorCoverageDispositionV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::SearchActive => 0,
            Self::ZeroEligibleSignals => 1,
            Self::PolicyDisabledUpdates => 2,
            Self::ZeroEligibleSignalsAndPolicyDisabledUpdates => 3,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum GeneratorCoverageDisableReasonV1 {
    OwnerEvidenceUnavailable,
    SignalUnavailable,
    EligibilityZero,
    ModulatorZero,
    ExplicitPolicyDisable,
}

impl GeneratorCoverageDisableReasonV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::OwnerEvidenceUnavailable => 0,
            Self::SignalUnavailable => 1,
            Self::EligibilityZero => 2,
            Self::ModulatorZero => 3,
            Self::ExplicitPolicyDisable => 4,
        }
    }
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct GeneratorCoverageGapV1 {
    pub parameter_id: StableId,
    pub reason: GeneratorCoverageDisableReasonV1,
    pub reason_evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GeneratorCoverageReceiptV1 {
    pub expected_parameters: Vec<StableId>,
    pub gaps: Vec<GeneratorCoverageGapV1>,
    pub expected_parameter_set_digest: Digest32,
    pub actual_signal_set_digest: Digest32,
    pub missing_parameter_set_digest: Digest32,
    pub scale_policy_digest: Digest32,
    pub grammar_manifest_digest: Digest32,
    pub selected_artifact_digest: Digest32,
    pub window: ProposalWindowV2,
    pub owner_frontier_digest: Digest32,
    pub disposition: GeneratorCoverageDispositionV1,
    pub receipt_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum GeneratorCoverageErrorV1 {
    MutationPolicy(crate::ParameterMutationPolicyErrorV1),
    ContextMismatch,
    EmptyExpectedLearnableSet,
    ParameterLimit,
    DuplicateExpectedParameter(String),
    DuplicateSignal(String),
    UnexpectedSignal(String),
    DuplicateGap(String),
    MissingGap(String),
    UnexpectedGap(String),
    EmptyGapEvidence(String),
    EmptyOwnerFrontier,
    DigestMismatch,
    Arithmetic,
}

impl fmt::Display for GeneratorCoverageErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for GeneratorCoverageErrorV1 {}
impl From<crate::ParameterMutationPolicyErrorV1> for GeneratorCoverageErrorV1 {
    fn from(value: crate::ParameterMutationPolicyErrorV1) -> Self {
        Self::MutationPolicy(value)
    }
}

pub fn build_generator_coverage_receipt_v1(
    profile: &ParameterGeneratorProfileV3,
    gaps: Vec<GeneratorCoverageGapV1>,
    owner_frontier_digest: Digest32,
) -> Result<GeneratorCoverageReceiptV1, GeneratorCoverageErrorV1> {
    let derived = derive(profile, gaps, owner_frontier_digest)?;
    let mut receipt = GeneratorCoverageReceiptV1 {
        expected_parameters: derived.expected_parameters,
        gaps: derived.gaps,
        expected_parameter_set_digest: derived.expected_parameter_set_digest,
        actual_signal_set_digest: derived.actual_signal_set_digest,
        missing_parameter_set_digest: derived.missing_parameter_set_digest,
        scale_policy_digest: derived.scale_policy_digest,
        grammar_manifest_digest: profile.mutation_policy.mutation_grammar_digest,
        selected_artifact_digest: profile.selected_artifact_digest,
        window: profile.window.clone(),
        owner_frontier_digest,
        disposition: derived.disposition,
        receipt_digest: Digest32::ZERO,
    };
    receipt.receipt_digest = digest_receipt(&receipt)?;
    Ok(receipt)
}

pub fn verify_generator_coverage_receipt_v1(
    profile: &ParameterGeneratorProfileV3,
    receipt: &GeneratorCoverageReceiptV1,
) -> Result<(), GeneratorCoverageErrorV1> {
    let derived = derive(
        profile,
        receipt.gaps.clone(),
        receipt.owner_frontier_digest,
    )?;
    if receipt.expected_parameters != derived.expected_parameters
        || receipt.expected_parameter_set_digest != derived.expected_parameter_set_digest
        || receipt.actual_signal_set_digest != derived.actual_signal_set_digest
        || receipt.missing_parameter_set_digest != derived.missing_parameter_set_digest
        || receipt.scale_policy_digest != derived.scale_policy_digest
        || receipt.grammar_manifest_digest
            != profile.mutation_policy.mutation_grammar_digest
        || receipt.selected_artifact_digest != profile.selected_artifact_digest
        || receipt.window != profile.window
        || receipt.disposition != derived.disposition
        || receipt.receipt_digest.is_zero()
        || receipt.receipt_digest != digest_receipt(receipt)?
    {
        return Err(GeneratorCoverageErrorV1::DigestMismatch);
    }
    Ok(())
}

pub fn generator_coverage_signing_payload_v1(receipt: &GeneratorCoverageReceiptV1) -> Vec<u8> {
    let mut bytes = b"hepta.plasticity.generator-coverage-signing.v1\0".to_vec();
    bytes.extend_from_slice(receipt.receipt_digest.as_array());
    bytes
}

struct DerivedCoverageV1 {
    expected_parameters: Vec<StableId>,
    gaps: Vec<GeneratorCoverageGapV1>,
    expected_parameter_set_digest: Digest32,
    actual_signal_set_digest: Digest32,
    missing_parameter_set_digest: Digest32,
    scale_policy_digest: Digest32,
    disposition: GeneratorCoverageDispositionV1,
}

fn derive(
    profile: &ParameterGeneratorProfileV3,
    mut gaps: Vec<GeneratorCoverageGapV1>,
    owner_frontier_digest: Digest32,
) -> Result<DerivedCoverageV1, GeneratorCoverageErrorV1> {
    verify_parameter_mutation_policy_v1(&profile.mutation_policy)?;
    if profile.mutation_policy.selected_artifact_digest != profile.selected_artifact_digest
        || profile.mutation_policy.window != profile.window
    {
        return Err(GeneratorCoverageErrorV1::ContextMismatch);
    }
    if owner_frontier_digest.is_zero() {
        return Err(GeneratorCoverageErrorV1::EmptyOwnerFrontier);
    }

    let mut expected_rules = profile
        .mutation_policy
        .rules
        .iter()
        .filter(|rule| rule.surface == ParameterMutationSurfaceV1::LearnableParameter)
        .collect::<Vec<_>>();
    expected_rules.sort_by(|left, right| left.parameter_id.cmp(&right.parameter_id));
    if expected_rules.is_empty() {
        return Err(GeneratorCoverageErrorV1::EmptyExpectedLearnableSet);
    }
    if expected_rules.len() > MAX_COVERAGE_PARAMETERS_V1 {
        return Err(GeneratorCoverageErrorV1::ParameterLimit);
    }
    if expected_rules
        .windows(2)
        .any(|pair| pair[0].parameter_id == pair[1].parameter_id)
    {
        return Err(GeneratorCoverageErrorV1::DuplicateExpectedParameter(
            expected_rules[0].parameter_id.to_string(),
        ));
    }
    let expected_parameters = expected_rules
        .iter()
        .map(|rule| rule.parameter_id.clone())
        .collect::<Vec<_>>();
    let expected_set = expected_parameters.iter().cloned().collect::<BTreeSet<_>>();

    let mut signals = profile.signals.iter().collect::<Vec<_>>();
    signals.sort_by(|left, right| left.parameter_id.cmp(&right.parameter_id));
    if signals.len() > MAX_COVERAGE_PARAMETERS_V1 {
        return Err(GeneratorCoverageErrorV1::ParameterLimit);
    }
    let mut actual = BTreeSet::new();
    for signal in &signals {
        if !actual.insert(signal.parameter_id.clone()) {
            return Err(GeneratorCoverageErrorV1::DuplicateSignal(
                signal.parameter_id.to_string(),
            ));
        }
        if !expected_set.contains(&signal.parameter_id) {
            return Err(GeneratorCoverageErrorV1::UnexpectedSignal(
                signal.parameter_id.to_string(),
            ));
        }
    }

    gaps.sort_by(|left, right| left.parameter_id.cmp(&right.parameter_id));
    let mut gap_by_parameter = BTreeMap::new();
    for gap in &gaps {
        if gap.reason_evidence_digest.is_zero() {
            return Err(GeneratorCoverageErrorV1::EmptyGapEvidence(
                gap.parameter_id.to_string(),
            ));
        }
        if gap_by_parameter
            .insert(gap.parameter_id.clone(), gap)
            .is_some()
        {
            return Err(GeneratorCoverageErrorV1::DuplicateGap(
                gap.parameter_id.to_string(),
            ));
        }
        if actual.contains(&gap.parameter_id) || !expected_set.contains(&gap.parameter_id) {
            return Err(GeneratorCoverageErrorV1::UnexpectedGap(
                gap.parameter_id.to_string(),
            ));
        }
    }
    for expected in expected_set.difference(&actual) {
        if !gap_by_parameter.contains_key(expected) {
            return Err(GeneratorCoverageErrorV1::MissingGap(
                expected.to_string(),
            ));
        }
    }
    if gap_by_parameter.len() != expected_set.len().saturating_sub(actual.len()) {
        return Err(GeneratorCoverageErrorV1::UnexpectedGap(
            "coverage partition".to_string(),
        ));
    }

    let disposition = match (signals.is_empty(), profile.update_scales.is_empty()) {
        (false, false) => GeneratorCoverageDispositionV1::SearchActive,
        (true, false) => GeneratorCoverageDispositionV1::ZeroEligibleSignals,
        (false, true) => GeneratorCoverageDispositionV1::PolicyDisabledUpdates,
        (true, true) => {
            GeneratorCoverageDispositionV1::ZeroEligibleSignalsAndPolicyDisabledUpdates
        }
    };

    Ok(DerivedCoverageV1 {
        expected_parameter_set_digest: digest_expected_rules(&expected_rules)?,
        actual_signal_set_digest: digest_signals(&signals)?,
        missing_parameter_set_digest: digest_gaps(&gaps)?,
        scale_policy_digest: digest_scales(profile)?,
        expected_parameters,
        gaps,
        disposition,
    })
}

fn digest_expected_rules(
    rules: &[&crate::ParameterMutationRuleV1],
) -> Result<Digest32, GeneratorCoverageErrorV1> {
    let mut bytes = b"hepta.plasticity.coverage-expected.v1\0".to_vec();
    push_len(&mut bytes, rules.len())?;
    for rule in rules {
        push_id(&mut bytes, &rule.parameter_id)?;
        push_id(&mut bytes, &rule.layer_id)?;
        bytes.extend_from_slice(&rule.minimum_delta.raw().to_be_bytes());
        bytes.extend_from_slice(&rule.maximum_delta.raw().to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_signals(
    signals: &[&crate::ParameterPlasticitySignalV3],
) -> Result<Digest32, GeneratorCoverageErrorV1> {
    let mut bytes = b"hepta.plasticity.coverage-signals.v1\0".to_vec();
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

fn digest_gaps(gaps: &[GeneratorCoverageGapV1]) -> Result<Digest32, GeneratorCoverageErrorV1> {
    let mut bytes = b"hepta.plasticity.coverage-gaps.v1\0".to_vec();
    push_len(&mut bytes, gaps.len())?;
    for gap in gaps {
        push_id(&mut bytes, &gap.parameter_id)?;
        bytes.push(gap.reason.tag());
        bytes.extend_from_slice(gap.reason_evidence_digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_scales(
    profile: &ParameterGeneratorProfileV3,
) -> Result<Digest32, GeneratorCoverageErrorV1> {
    let mut scales = profile.update_scales.clone();
    scales.sort();
    let mut bytes = b"hepta.plasticity.coverage-scales.v1\0".to_vec();
    push_len(&mut bytes, scales.len())?;
    for scale in scales {
        bytes.extend_from_slice(&scale.raw().to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_receipt(
    receipt: &GeneratorCoverageReceiptV1,
) -> Result<Digest32, GeneratorCoverageErrorV1> {
    let mut bytes = b"hepta.plasticity.generator-coverage.v1\0".to_vec();
    for digest in [
        receipt.expected_parameter_set_digest,
        receipt.actual_signal_set_digest,
        receipt.missing_parameter_set_digest,
        receipt.scale_policy_digest,
        receipt.grammar_manifest_digest,
        receipt.selected_artifact_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_id(&mut bytes, &receipt.window.window_id)?;
    bytes.extend_from_slice(receipt.window.window_digest.as_array());
    bytes.extend_from_slice(receipt.owner_frontier_digest.as_array());
    bytes.push(receipt.disposition.tag());
    push_len(&mut bytes, receipt.expected_parameters.len())?;
    for parameter in &receipt.expected_parameters {
        push_id(&mut bytes, parameter)?;
    }
    bytes.extend_from_slice(receipt.missing_parameter_set_digest.as_array());
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
    fn profile(signals: bool, scales: bool) -> ParameterGeneratorProfileV3 {
        let artifact = digest(b"artifact");
        let window = ProposalWindowV2 {
            window_id: id("window:coverage"),
            window_digest: digest(b"window"),
        };
        let policy = build_parameter_mutation_policy_v1(
            id("policy:coverage"),
            digest(b"grammar"),
            artifact,
            window.clone(),
            vec![ParameterMutationRuleV1 {
                parameter_id: id("parameter:1"),
                layer_id: id("layer:1"),
                surface: ParameterMutationSurfaceV1::LearnableParameter,
                minimum_delta: FixedQ32::from_raw(-100),
                maximum_delta: FixedQ32::from_raw(100),
            }],
        )
        .expect("policy");
        ParameterGeneratorProfileV3 {
            selected_artifact_digest: artifact,
            window,
            norm_layers: vec![LayerNormDenominatorV2 {
                layer_id: id("layer:1"),
                baseline_squared_l2_raw_q64: 1_000_000,
            }],
            mutation_policy: policy,
            update_scales: scales.then(|| FixedQ32::ONE).into_iter().collect(),
            signals: signals
                .then(|| ParameterPlasticitySignalV3 {
                    layer_id: id("layer:1"),
                    parameter_id: id("parameter:1"),
                    eligibility: FixedQ32::ONE,
                    modulator: FixedQ32::ONE,
                    learning_rate: FixedQ32::from_raw(1),
                    lower_bound: FixedQ32::from_raw(-100),
                    upper_bound: FixedQ32::from_raw(100),
                    evidence_digest: digest(b"signal"),
                })
                .into_iter()
                .collect(),
        }
    }

    #[test]
    fn active_coverage_is_exact_and_tamper_evident() {
        let profile = profile(true, true);
        let receipt = build_generator_coverage_receipt_v1(
            &profile,
            Vec::new(),
            digest(b"owner-frontier"),
        )
        .expect("coverage");
        assert_eq!(
            receipt.disposition,
            GeneratorCoverageDispositionV1::SearchActive
        );
        verify_generator_coverage_receipt_v1(&profile, &receipt).expect("verify");
        let mut changed = receipt;
        changed.owner_frontier_digest = digest(b"other-frontier");
        assert_eq!(
            verify_generator_coverage_receipt_v1(&profile, &changed),
            Err(GeneratorCoverageErrorV1::DigestMismatch)
        );
    }

    #[test]
    fn zero_signal_and_disabled_scale_are_distinct_terminals() {
        let zero_signal = profile(false, true);
        let receipt = build_generator_coverage_receipt_v1(
            &zero_signal,
            vec![GeneratorCoverageGapV1 {
                parameter_id: id("parameter:1"),
                reason: GeneratorCoverageDisableReasonV1::SignalUnavailable,
                reason_evidence_digest: digest(b"missing-signal"),
            }],
            digest(b"owner-frontier"),
        )
        .expect("coverage");
        assert_eq!(
            receipt.disposition,
            GeneratorCoverageDispositionV1::ZeroEligibleSignals
        );

        let disabled = profile(true, false);
        let receipt = build_generator_coverage_receipt_v1(
            &disabled,
            Vec::new(),
            digest(b"owner-frontier"),
        )
        .expect("coverage");
        assert_eq!(
            receipt.disposition,
            GeneratorCoverageDispositionV1::PolicyDisabledUpdates
        );
    }
}
