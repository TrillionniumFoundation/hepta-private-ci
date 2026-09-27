//! Deterministic coverage accounting for governed parameter generation.
//!
//! A generated candidate set can be complete relative to its declared profile while
//! the profile itself omits learnable parameters.  This module makes that distinction
//! explicit.  The receipt is derived from the mutation-policy projection, the exact
//! signal/scale profile and a current owner-frontier digest.  It grants no authority
//! and is intentionally reproducible from inputs already authenticated by the
//! Generator and Observer boundaries.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ParameterGeneratorErrorV3;
use crate::ParameterGeneratorProfileV3;
use crate::ParameterMutationPolicyErrorV1;
use crate::ParameterMutationPolicyV1;
use crate::ParameterMutationSurfaceV1;
use crate::ProposalWindowV2;
use crate::generate_parameter_candidates_v3;
use crate::verify_parameter_mutation_policy_v1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum GeneratorCoverageDispositionV1 {
    CompleteSearch,
    IncompleteSignalCoverage,
    ZeroEligibleSignals,
    PolicyDisabledUpdates,
}

impl GeneratorCoverageDispositionV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::CompleteSearch => 0,
            Self::IncompleteSignalCoverage => 1,
            Self::ZeroEligibleSignals => 2,
            Self::PolicyDisabledUpdates => 3,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum GeneratorCoverageGapReasonV1 {
    MissingSignal,
}

impl GeneratorCoverageGapReasonV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::MissingSignal => 0,
        }
    }
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct GeneratorCoverageGapV1 {
    pub parameter_id: StableId,
    pub layer_id: StableId,
    pub reason: GeneratorCoverageGapReasonV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GeneratorCoverageReceiptV1 {
    pub selected_artifact_digest: Digest32,
    pub window: ProposalWindowV2,
    pub expected_learnable_parameter_set_digest: Digest32,
    pub actual_signal_set_digest: Digest32,
    pub gaps: Vec<GeneratorCoverageGapV1>,
    pub scale_policy_digest: Digest32,
    pub mutation_grammar_digest: Digest32,
    pub owner_frontier_digest: Digest32,
    pub disposition: GeneratorCoverageDispositionV1,
    pub coverage_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum GeneratorCoverageErrorV1 {
    EmptyOwnerFrontier,
    Policy(ParameterMutationPolicyErrorV1),
    Generator(ParameterGeneratorErrorV3),
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
        Self::Policy(value)
    }
}
impl From<ParameterGeneratorErrorV3> for GeneratorCoverageErrorV1 {
    fn from(value: ParameterGeneratorErrorV3) -> Self {
        Self::Generator(value)
    }
}

/// Canonical digest of every parameter the admitted mutation-policy projection
/// marks learnable.  Bounds and layer mapping are part of the identity.
pub fn expected_learnable_parameter_set_digest_v1(
    policy: &ParameterMutationPolicyV1,
) -> Result<Digest32, GeneratorCoverageErrorV1> {
    verify_parameter_mutation_policy_v1(policy)?;
    let mut rules = policy
        .rules
        .iter()
        .filter(|rule| rule.surface == ParameterMutationSurfaceV1::LearnableParameter)
        .collect::<Vec<_>>();
    rules.sort_by(|left, right| left.parameter_id.cmp(&right.parameter_id));

    let mut bytes = b"hepta.plasticity.expected-learnable-parameter-set.v1\0".to_vec();
    bytes.extend_from_slice(policy.mutation_grammar_digest.as_array());
    bytes.extend_from_slice(policy.selected_artifact_digest.as_array());
    push_id(&mut bytes, &policy.window.window_id)?;
    bytes.extend_from_slice(policy.window.window_digest.as_array());
    push_len(&mut bytes, rules.len())?;
    for rule in rules {
        push_id(&mut bytes, &rule.parameter_id)?;
        push_id(&mut bytes, &rule.layer_id)?;
        bytes.extend_from_slice(&rule.minimum_delta.raw().to_be_bytes());
        bytes.extend_from_slice(&rule.maximum_delta.raw().to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

/// Derive the exact coverage receipt for one validated generator profile.
///
/// Calling the V3 generator first is deliberate: a coverage receipt cannot make an
/// invalid profile look admissible.  Empty signals and empty scales remain explicit,
/// separately classified terminal profiles rather than ordinary no-update outcomes.
pub fn derive_generator_coverage_receipt_v1(
    profile: &ParameterGeneratorProfileV3,
    owner_frontier_digest: Digest32,
) -> Result<GeneratorCoverageReceiptV1, GeneratorCoverageErrorV1> {
    if owner_frontier_digest.is_zero() {
        return Err(GeneratorCoverageErrorV1::EmptyOwnerFrontier);
    }
    let _ = generate_parameter_candidates_v3(profile.clone())?;

    let expected_learnable_parameter_set_digest =
        expected_learnable_parameter_set_digest_v1(&profile.mutation_policy)?;
    let actual_signal_set_digest = digest_actual_signal_set(profile)?;
    let scale_policy_digest = digest_scale_policy(profile)?;

    let signal_layers = profile
        .signals
        .iter()
        .map(|signal| (signal.parameter_id.clone(), signal.layer_id.clone()))
        .collect::<BTreeMap<_, _>>();
    let mut gaps = profile
        .mutation_policy
        .rules
        .iter()
        .filter(|rule| rule.surface == ParameterMutationSurfaceV1::LearnableParameter)
        .filter(|rule| !signal_layers.contains_key(&rule.parameter_id))
        .map(|rule| GeneratorCoverageGapV1 {
            parameter_id: rule.parameter_id.clone(),
            layer_id: rule.layer_id.clone(),
            reason: GeneratorCoverageGapReasonV1::MissingSignal,
        })
        .collect::<Vec<_>>();
    gaps.sort();

    let disposition = if profile.update_scales.is_empty() {
        GeneratorCoverageDispositionV1::PolicyDisabledUpdates
    } else if profile.signals.is_empty() {
        GeneratorCoverageDispositionV1::ZeroEligibleSignals
    } else if gaps.is_empty() {
        GeneratorCoverageDispositionV1::CompleteSearch
    } else {
        GeneratorCoverageDispositionV1::IncompleteSignalCoverage
    };

    let mut receipt = GeneratorCoverageReceiptV1 {
        selected_artifact_digest: profile.selected_artifact_digest,
        window: profile.window.clone(),
        expected_learnable_parameter_set_digest,
        actual_signal_set_digest,
        gaps,
        scale_policy_digest,
        mutation_grammar_digest: profile.mutation_policy.mutation_grammar_digest,
        owner_frontier_digest,
        disposition,
        coverage_digest: Digest32::ZERO,
    };
    receipt.coverage_digest = digest_receipt(&receipt)?;
    Ok(receipt)
}

pub fn verify_generator_coverage_receipt_v1(
    profile: &ParameterGeneratorProfileV3,
    receipt: &GeneratorCoverageReceiptV1,
) -> Result<(), GeneratorCoverageErrorV1> {
    let expected = derive_generator_coverage_receipt_v1(profile, receipt.owner_frontier_digest)?;
    if &expected != receipt || receipt.coverage_digest.is_zero() {
        return Err(GeneratorCoverageErrorV1::DigestMismatch);
    }
    Ok(())
}

fn digest_actual_signal_set(
    profile: &ParameterGeneratorProfileV3,
) -> Result<Digest32, GeneratorCoverageErrorV1> {
    let mut signals = profile.signals.clone();
    signals.sort_by(|left, right| {
        left.layer_id
            .cmp(&right.layer_id)
            .then_with(|| left.parameter_id.cmp(&right.parameter_id))
    });
    let mut bytes = b"hepta.plasticity.actual-signal-set.v1\0".to_vec();
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

fn digest_scale_policy(
    profile: &ParameterGeneratorProfileV3,
) -> Result<Digest32, GeneratorCoverageErrorV1> {
    let mut scales = profile.update_scales.clone();
    scales.sort();
    let mut bytes = b"hepta.plasticity.scale-policy.v1\0".to_vec();
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
        receipt.expected_learnable_parameter_set_digest,
        receipt.actual_signal_set_digest,
        receipt.scale_policy_digest,
        receipt.mutation_grammar_digest,
        receipt.owner_frontier_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_len(&mut bytes, receipt.gaps.len())?;
    for gap in &receipt.gaps {
        push_id(&mut bytes, &gap.parameter_id)?;
        push_id(&mut bytes, &gap.layer_id)?;
        bytes.push(gap.reason.tag());
    }
    bytes.push(receipt.disposition.tag());
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
    use crate::ParameterPlasticitySignalV3;
    use crate::build_parameter_mutation_policy_v1;

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
    fn rule(parameter: &str, layer: &str) -> ParameterMutationRuleV1 {
        ParameterMutationRuleV1 {
            parameter_id: id(parameter),
            layer_id: id(layer),
            surface: ParameterMutationSurfaceV1::LearnableParameter,
            minimum_delta: FixedQ32::from_raw(-100),
            maximum_delta: FixedQ32::from_raw(100),
        }
    }
    fn signal(parameter: &str, layer: &str, evidence: &[u8]) -> ParameterPlasticitySignalV3 {
        ParameterPlasticitySignalV3 {
            layer_id: id(layer),
            parameter_id: id(parameter),
            eligibility: FixedQ32::ONE,
            modulator: FixedQ32::ONE,
            learning_rate: FixedQ32::from_raw(1),
            lower_bound: FixedQ32::from_raw(-100),
            upper_bound: FixedQ32::from_raw(100),
            evidence_digest: digest(evidence),
        }
    }
    fn profile() -> ParameterGeneratorProfileV3 {
        let artifact = digest(b"artifact");
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
                vec![
                    rule("parameter:a", "layer:a"),
                    rule("parameter:b", "layer:a"),
                ],
            )
            .expect("policy"),
            update_scales: vec![FixedQ32::ONE],
            signals: vec![
                signal("parameter:a", "layer:a", b"a"),
                signal("parameter:b", "layer:a", b"b"),
            ],
        }
    }

    #[test]
    fn complete_coverage_is_order_independent_and_verifiable() {
        let left = derive_generator_coverage_receipt_v1(&profile(), digest(b"frontier"))
            .expect("coverage");
        let mut reordered = profile();
        reordered.signals.reverse();
        reordered.mutation_policy.rules.reverse();
        // A non-canonical policy is rejected rather than silently relabelled.
        assert!(derive_generator_coverage_receipt_v1(&reordered, digest(b"frontier")).is_err());
        assert_eq!(left.disposition, GeneratorCoverageDispositionV1::CompleteSearch);
        assert!(left.gaps.is_empty());
        verify_generator_coverage_receipt_v1(&profile(), &left).expect("verify");
    }

    #[test]
    fn incomplete_and_empty_profiles_have_distinct_terminal_reasons() {
        let mut incomplete = profile();
        incomplete.signals.pop();
        let receipt = derive_generator_coverage_receipt_v1(&incomplete, digest(b"frontier"))
            .expect("incomplete");
        assert_eq!(
            receipt.disposition,
            GeneratorCoverageDispositionV1::IncompleteSignalCoverage
        );
        assert_eq!(receipt.gaps.len(), 1);

        let mut empty = profile();
        empty.signals.clear();
        let receipt = derive_generator_coverage_receipt_v1(&empty, digest(b"frontier"))
            .expect("empty");
        assert_eq!(
            receipt.disposition,
            GeneratorCoverageDispositionV1::ZeroEligibleSignals
        );

        let mut disabled = profile();
        disabled.update_scales.clear();
        let receipt = derive_generator_coverage_receipt_v1(&disabled, digest(b"frontier"))
            .expect("disabled");
        assert_eq!(
            receipt.disposition,
            GeneratorCoverageDispositionV1::PolicyDisabledUpdates
        );
    }

    #[test]
    fn every_frontier_or_signal_change_changes_coverage_identity() {
        let first = derive_generator_coverage_receipt_v1(&profile(), digest(b"frontier-a"))
            .expect("first");
        let second = derive_generator_coverage_receipt_v1(&profile(), digest(b"frontier-b"))
            .expect("second");
        assert_ne!(first.coverage_digest, second.coverage_digest);

        let mut changed = profile();
        changed.signals[0].evidence_digest = digest(b"changed-evidence");
        let third = derive_generator_coverage_receipt_v1(&changed, digest(b"frontier-a"))
            .expect("third");
        assert_ne!(first.actual_signal_set_digest, third.actual_signal_set_digest);
        assert_ne!(first.coverage_digest, third.coverage_digest);
    }
}
