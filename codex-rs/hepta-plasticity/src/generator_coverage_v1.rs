//! Generator coverage receipts for governed parameter plasticity.
//!
//! Candidate completeness is meaningful only relative to both a mutation grammar
//! and the owner-resolved signal frontier.  This module records the exact expected
//! learnable parameter set, the signals actually presented to the deterministic
//! generator, the scale policy, omissions and their fail-closed disposition.  It
//! grants no authority to select, train, install, activate, promote or release.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ParameterGeneratorProfileV3;
use crate::ParameterMutationPolicyErrorV1;
use crate::ParameterMutationSurfaceV1;
use crate::ProposalWindowV2;
use crate::verify_parameter_mutation_policy_v1;

const MAX_COVERAGE_OMISSIONS_V1: usize = 4_096;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum GeneratorCoverageDispositionV1 {
    Complete,
    IncompleteSignals,
    ZeroEligibleSignals,
    PolicyDisabledUpdates,
}

impl GeneratorCoverageDispositionV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Complete => 0,
            Self::IncompleteSignals => 1,
            Self::ZeroEligibleSignals => 2,
            Self::PolicyDisabledUpdates => 3,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum GeneratorCoverageOmissionReasonV1 {
    MissingOwnerSignal,
    UpdateScalesDisabled,
}

impl GeneratorCoverageOmissionReasonV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::MissingOwnerSignal => 0,
            Self::UpdateScalesDisabled => 1,
        }
    }
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct GeneratorCoverageOmissionV1 {
    pub parameter_id: StableId,
    pub reason: GeneratorCoverageOmissionReasonV1,
    /// Deterministic evidence binding the omission to the exact mutation policy.
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GeneratorCoverageReceiptV1 {
    pub expected_learnable_parameter_set_digest: Digest32,
    pub actual_signal_set_digest: Digest32,
    pub omissions: Vec<GeneratorCoverageOmissionV1>,
    pub scale_policy_digest: Digest32,
    pub mutation_grammar_digest: Digest32,
    pub selected_artifact_digest: Digest32,
    pub window: ProposalWindowV2,
    pub owner_frontier_digest: Digest32,
    pub disposition: GeneratorCoverageDispositionV1,
    pub coverage_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum GeneratorCoverageErrorV1 {
    MutationPolicy(ParameterMutationPolicyErrorV1),
    EmptyOwnerFrontier,
    EmptyArtifact,
    EmptyWindow,
    EmptyMutationGrammar,
    DuplicateSignal(String),
    UnexpectedSignal(String),
    OmissionLimit,
    NonCanonicalOmissions,
    EmptyOmissionEvidence(String),
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

/// Build the exact coverage receipt for one generator profile and one current
/// owner frontier.  The frontier is supplied by the selected host after it has
/// resolved every authoritative owner receipt; a caller-selected opaque digest is
/// not sufficient for product admission.
pub fn build_generator_coverage_receipt_v1(
    profile: &ParameterGeneratorProfileV3,
    owner_frontier_digest: Digest32,
) -> Result<GeneratorCoverageReceiptV1, GeneratorCoverageErrorV1> {
    verify_parameter_mutation_policy_v1(&profile.mutation_policy)?;
    if owner_frontier_digest.is_zero() {
        return Err(GeneratorCoverageErrorV1::EmptyOwnerFrontier);
    }
    if profile.selected_artifact_digest.is_zero() {
        return Err(GeneratorCoverageErrorV1::EmptyArtifact);
    }
    if profile.window.window_digest.is_zero() {
        return Err(GeneratorCoverageErrorV1::EmptyWindow);
    }
    if profile.mutation_policy.mutation_grammar_digest.is_zero() {
        return Err(GeneratorCoverageErrorV1::EmptyMutationGrammar);
    }

    let expected = profile
        .mutation_policy
        .rules
        .iter()
        .filter(|rule| rule.surface == ParameterMutationSurfaceV1::LearnableParameter)
        .map(|rule| (rule.parameter_id.clone(), rule.layer_id.clone()))
        .collect::<BTreeMap<_, _>>();

    let mut actual = BTreeMap::new();
    for signal in &profile.signals {
        if actual
            .insert(signal.parameter_id.clone(), signal)
            .is_some()
        {
            return Err(GeneratorCoverageErrorV1::DuplicateSignal(
                signal.parameter_id.to_string(),
            ));
        }
        if expected.get(&signal.parameter_id) != Some(&signal.layer_id) {
            return Err(GeneratorCoverageErrorV1::UnexpectedSignal(
                signal.parameter_id.to_string(),
            ));
        }
    }

    let expected_learnable_parameter_set_digest = digest_expected_set(&expected)?;
    let actual_signal_set_digest = digest_actual_signals(&actual)?;
    let scale_policy_digest = digest_scales(profile)?;

    let omission_reason = if profile.update_scales.is_empty() {
        GeneratorCoverageOmissionReasonV1::UpdateScalesDisabled
    } else {
        GeneratorCoverageOmissionReasonV1::MissingOwnerSignal
    };
    let mut omissions = expected
        .keys()
        .filter(|parameter_id| !actual.contains_key(*parameter_id))
        .map(|parameter_id| GeneratorCoverageOmissionV1 {
            parameter_id: parameter_id.clone(),
            reason: omission_reason,
            evidence_digest: omission_evidence_digest(
                parameter_id,
                omission_reason,
                profile.mutation_policy.policy_digest,
                owner_frontier_digest,
            ),
        })
        .collect::<Vec<_>>();
    omissions.sort();
    if omissions.len() > MAX_COVERAGE_OMISSIONS_V1 {
        return Err(GeneratorCoverageErrorV1::OmissionLimit);
    }

    let disposition = if expected.is_empty() || profile.update_scales.is_empty() {
        GeneratorCoverageDispositionV1::PolicyDisabledUpdates
    } else if actual.is_empty() {
        GeneratorCoverageDispositionV1::ZeroEligibleSignals
    } else if omissions.is_empty() {
        GeneratorCoverageDispositionV1::Complete
    } else {
        GeneratorCoverageDispositionV1::IncompleteSignals
    };

    let mut receipt = GeneratorCoverageReceiptV1 {
        expected_learnable_parameter_set_digest,
        actual_signal_set_digest,
        omissions,
        scale_policy_digest,
        mutation_grammar_digest: profile.mutation_policy.mutation_grammar_digest,
        selected_artifact_digest: profile.selected_artifact_digest,
        window: profile.window.clone(),
        owner_frontier_digest,
        disposition,
        coverage_digest: Digest32::ZERO,
    };
    receipt.coverage_digest = digest_receipt(&receipt)?;
    verify_generator_coverage_receipt_v1(&receipt)?;
    Ok(receipt)
}

pub fn verify_generator_coverage_receipt_v1(
    receipt: &GeneratorCoverageReceiptV1,
) -> Result<(), GeneratorCoverageErrorV1> {
    for digest in [
        receipt.expected_learnable_parameter_set_digest,
        receipt.actual_signal_set_digest,
        receipt.scale_policy_digest,
        receipt.mutation_grammar_digest,
        receipt.selected_artifact_digest,
        receipt.window.window_digest,
        receipt.owner_frontier_digest,
        receipt.coverage_digest,
    ] {
        if digest.is_zero() {
            return Err(GeneratorCoverageErrorV1::DigestMismatch);
        }
    }
    if receipt.omissions.len() > MAX_COVERAGE_OMISSIONS_V1
        || receipt
            .omissions
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
    {
        return Err(GeneratorCoverageErrorV1::NonCanonicalOmissions);
    }
    for omission in &receipt.omissions {
        if omission.evidence_digest.is_zero() {
            return Err(GeneratorCoverageErrorV1::EmptyOmissionEvidence(
                omission.parameter_id.to_string(),
            ));
        }
    }
    if digest_receipt(receipt)? != receipt.coverage_digest {
        return Err(GeneratorCoverageErrorV1::DigestMismatch);
    }
    Ok(())
}

pub fn verify_generator_coverage_against_profile_v1(
    profile: &ParameterGeneratorProfileV3,
    owner_frontier_digest: Digest32,
    receipt: &GeneratorCoverageReceiptV1,
) -> Result<(), GeneratorCoverageErrorV1> {
    let expected = build_generator_coverage_receipt_v1(profile, owner_frontier_digest)?;
    if &expected != receipt {
        return Err(GeneratorCoverageErrorV1::DigestMismatch);
    }
    Ok(())
}

/// Canonical bytes signed by the independent Observer after owner-frontier
/// resolution.  The signature authenticates coverage, not selection or activation.
pub fn generator_coverage_signing_payload_v1(
    receipt: &GeneratorCoverageReceiptV1,
) -> Result<Vec<u8>, GeneratorCoverageErrorV1> {
    verify_generator_coverage_receipt_v1(receipt)?;
    let mut bytes = b"hepta.plasticity.generator-coverage-attestation.v1\0".to_vec();
    bytes.extend_from_slice(receipt.coverage_digest.as_array());
    Ok(bytes)
}

fn digest_expected_set(
    expected: &BTreeMap<StableId, StableId>,
) -> Result<Digest32, GeneratorCoverageErrorV1> {
    let mut bytes = b"hepta.plasticity.generator-coverage.expected-set.v1\0".to_vec();
    push_len(&mut bytes, expected.len())?;
    for (parameter_id, layer_id) in expected {
        push_id(&mut bytes, parameter_id)?;
        push_id(&mut bytes, layer_id)?;
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_actual_signals(
    actual: &BTreeMap<StableId, &crate::ParameterPlasticitySignalV3>,
) -> Result<Digest32, GeneratorCoverageErrorV1> {
    let mut bytes = b"hepta.plasticity.generator-coverage.actual-signals.v1\0".to_vec();
    push_len(&mut bytes, actual.len())?;
    for (parameter_id, signal) in actual {
        push_id(&mut bytes, parameter_id)?;
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

fn digest_scales(
    profile: &ParameterGeneratorProfileV3,
) -> Result<Digest32, GeneratorCoverageErrorV1> {
    let mut scales = profile.update_scales.clone();
    scales.sort();
    let mut bytes = b"hepta.plasticity.generator-coverage.scale-policy.v1\0".to_vec();
    push_len(&mut bytes, scales.len())?;
    for scale in scales {
        bytes.extend_from_slice(&scale.raw().to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn omission_evidence_digest(
    parameter_id: &StableId,
    reason: GeneratorCoverageOmissionReasonV1,
    policy_digest: Digest32,
    owner_frontier_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.plasticity.generator-coverage.omission.v1\0".to_vec();
    bytes.extend_from_slice(parameter_id.as_str().as_bytes());
    bytes.push(reason.tag());
    bytes.extend_from_slice(policy_digest.as_array());
    bytes.extend_from_slice(owner_frontier_digest.as_array());
    Digest32::of_bytes(&bytes)
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
    push_id(&mut bytes, &receipt.window.window_id)?;
    bytes.extend_from_slice(receipt.window.window_digest.as_array());
    bytes.extend_from_slice(receipt.owner_frontier_digest.as_array());
    bytes.push(receipt.disposition.tag());
    push_len(&mut bytes, receipt.omissions.len())?;
    for omission in &receipt.omissions {
        push_id(&mut bytes, &omission.parameter_id)?;
        bytes.push(omission.reason.tag());
        bytes.extend_from_slice(omission.evidence_digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn push_id(
    bytes: &mut Vec<u8>,
    value: &StableId,
) -> Result<(), GeneratorCoverageErrorV1> {
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
    use crate::ParameterPlasticitySignalV3;
    use crate::build_parameter_mutation_policy_v1;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }
    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }
    fn profile(signal_count: usize, scale_count: usize) -> ParameterGeneratorProfileV3 {
        let artifact = digest(b"artifact");
        let window = ProposalWindowV2 {
            window_id: id("window:coverage"),
            window_digest: digest(b"window"),
        };
        let rules = (0..2)
            .map(|index| ParameterMutationRuleV1 {
                parameter_id: id(&format!("parameter:{index}")),
                layer_id: id("layer:coverage"),
                surface: ParameterMutationSurfaceV1::LearnableParameter,
                minimum_delta: FixedQ32::from_raw(-100),
                maximum_delta: FixedQ32::from_raw(100),
            })
            .collect();
        let signals = (0..signal_count)
            .map(|index| ParameterPlasticitySignalV3 {
                layer_id: id("layer:coverage"),
                parameter_id: id(&format!("parameter:{index}")),
                eligibility: FixedQ32::ONE,
                modulator: FixedQ32::ONE,
                learning_rate: FixedQ32::ONE,
                lower_bound: FixedQ32::from_raw(-100),
                upper_bound: FixedQ32::from_raw(100),
                evidence_digest: digest(format!("signal:{index}").as_bytes()),
            })
            .collect();
        ParameterGeneratorProfileV3 {
            selected_artifact_digest: artifact,
            window: window.clone(),
            norm_layers: vec![LayerNormDenominatorV2 {
                layer_id: id("layer:coverage"),
                baseline_squared_l2_raw_q64: 1_000_000,
            }],
            mutation_policy: build_parameter_mutation_policy_v1(
                id("policy:coverage"),
                digest(b"grammar"),
                artifact,
                window,
                rules,
            )
            .expect("policy"),
            update_scales: vec![FixedQ32::ONE; scale_count],
            signals,
        }
    }

    #[test]
    fn complete_coverage_is_deterministic_and_profile_bound() {
        let profile = profile(2, 1);
        let first = build_generator_coverage_receipt_v1(&profile, digest(b"frontier"))
            .expect("coverage");
        let second = build_generator_coverage_receipt_v1(&profile, digest(b"frontier"))
            .expect("coverage again");
        assert_eq!(first, second);
        assert_eq!(first.disposition, GeneratorCoverageDispositionV1::Complete);
        assert!(first.omissions.is_empty());
        verify_generator_coverage_against_profile_v1(&profile, digest(b"frontier"), &first)
            .expect("verify");
    }

    #[test]
    fn empty_signal_and_scale_profiles_have_distinct_terminal_dispositions() {
        let zero = build_generator_coverage_receipt_v1(&profile(0, 1), digest(b"frontier"))
            .expect("zero signals");
        assert_eq!(
            zero.disposition,
            GeneratorCoverageDispositionV1::ZeroEligibleSignals
        );
        let disabled = build_generator_coverage_receipt_v1(&profile(2, 0), digest(b"frontier"))
            .expect("disabled scales");
        assert_eq!(
            disabled.disposition,
            GeneratorCoverageDispositionV1::PolicyDisabledUpdates
        );
    }

    #[test]
    fn partial_signal_set_records_exact_missing_parameter() {
        let receipt = build_generator_coverage_receipt_v1(&profile(1, 1), digest(b"frontier"))
            .expect("partial");
        assert_eq!(
            receipt.disposition,
            GeneratorCoverageDispositionV1::IncompleteSignals
        );
        assert_eq!(receipt.omissions.len(), 1);
        assert_eq!(receipt.omissions[0].parameter_id, id("parameter:1"));
        assert_eq!(
            receipt.omissions[0].reason,
            GeneratorCoverageOmissionReasonV1::MissingOwnerSignal
        );
    }

    #[test]
    fn every_coverage_binding_changes_the_digest() {
        let profile = profile(2, 1);
        let base = build_generator_coverage_receipt_v1(&profile, digest(b"frontier"))
            .expect("base");
        let changed_frontier =
            build_generator_coverage_receipt_v1(&profile, digest(b"other-frontier"))
                .expect("changed frontier");
        assert_ne!(base.coverage_digest, changed_frontier.coverage_digest);

        let mut changed_profile = profile.clone();
        changed_profile.update_scales[0] = FixedQ32::from_raw(FixedQ32::ONE.raw() / 2);
        let changed_scale =
            build_generator_coverage_receipt_v1(&changed_profile, digest(b"frontier"))
                .expect("changed scale");
        assert_ne!(base.coverage_digest, changed_scale.coverage_digest);
    }
}
