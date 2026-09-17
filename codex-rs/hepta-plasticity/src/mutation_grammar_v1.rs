//! Typed mutation grammar for governed parameter plasticity.
//!
//! The grammar is an authority-free allowlist over one selected artifact. It
//! separates immutable/protected surfaces from parameters that may participate
//! in V3 candidate generation. A digest string alone is never treated as policy.

use std::collections::{BTreeMap, BTreeSet};
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::{Digest32, FixedQ32, StableId};

use crate::ParameterGeneratorProfileV3;

const MAX_MUTATION_RULES: usize = 4_096;
const MAX_PROTECTED_PARAMETERS: usize = 4_096;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum ProtectedParameterClassV1 {
    Authority,
    Evaluation,
    Deletion,
    Privacy,
    Secret,
    RuntimeTopology,
    ProviderOrTool,
}

impl ProtectedParameterClassV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Authority => 0,
            Self::Evaluation => 1,
            Self::Deletion => 2,
            Self::Privacy => 3,
            Self::Secret => 4,
            Self::RuntimeTopology => 5,
            Self::ProviderOrTool => 6,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct ParameterMutationRuleV1 {
    pub layer_id: StableId,
    pub parameter_id: StableId,
    pub minimum_delta: FixedQ32,
    pub maximum_delta: FixedQ32,
}

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct ProtectedParameterV1 {
    pub parameter_id: StableId,
    pub class: ProtectedParameterClassV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MutationGrammarManifestV1 {
    pub manifest_id: StableId,
    pub selected_artifact_digest: Digest32,
    /// Host/catalog revision. Zero is reserved for an invalid/unbound grammar.
    pub revision: u64,
    pub allowed_parameters: Vec<ParameterMutationRuleV1>,
    pub protected_parameters: Vec<ProtectedParameterV1>,
    pub manifest_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum MutationGrammarErrorV1 {
    EmptyArtifactDigest,
    InvalidRevision,
    RuleLimitExceeded,
    ProtectedLimitExceeded,
    DuplicateAllowedParameter(String),
    DuplicateProtectedParameter(String),
    ProtectedParameterAllowed(String),
    InvertedRuleBounds(String),
    DigestMismatch,
    ArtifactMismatch,
    SignalNotAllowed(String),
    SignalLayerMismatch(String),
    SignalBoundsWidened(String),
    Arithmetic,
}

impl fmt::Display for MutationGrammarErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for MutationGrammarErrorV1 {}

/// Construct a canonical grammar and bind every rule/class into its digest.
pub fn build_mutation_grammar_manifest_v1(
    manifest_id: StableId,
    selected_artifact_digest: Digest32,
    revision: u64,
    mut allowed_parameters: Vec<ParameterMutationRuleV1>,
    mut protected_parameters: Vec<ProtectedParameterV1>,
) -> Result<MutationGrammarManifestV1, MutationGrammarErrorV1> {
    canonicalize_and_validate(
        selected_artifact_digest,
        revision,
        &mut allowed_parameters,
        &mut protected_parameters,
    )?;
    let mut manifest = MutationGrammarManifestV1 {
        manifest_id,
        selected_artifact_digest,
        revision,
        allowed_parameters,
        protected_parameters,
        manifest_digest: Digest32::ZERO,
    };
    manifest.manifest_digest = digest_manifest(&manifest)?;
    Ok(manifest)
}

pub fn verify_mutation_grammar_manifest_v1(
    manifest: &MutationGrammarManifestV1,
) -> Result<(), MutationGrammarErrorV1> {
    let mut allowed = manifest.allowed_parameters.clone();
    let mut protected = manifest.protected_parameters.clone();
    canonicalize_and_validate(
        manifest.selected_artifact_digest,
        manifest.revision,
        &mut allowed,
        &mut protected,
    )?;
    if allowed != manifest.allowed_parameters || protected != manifest.protected_parameters {
        return Err(MutationGrammarErrorV1::DigestMismatch);
    }
    if manifest.manifest_digest.is_zero() || manifest.manifest_digest != digest_manifest(manifest)? {
        return Err(MutationGrammarErrorV1::DigestMismatch);
    }
    Ok(())
}

/// Enforce the grammar before the deterministic V3 generator is trusted.
///
/// Every signal must have an exact allowlist entry, must remain in the declared
/// layer, and may only narrow (never widen) the grammar's delta bounds.
pub fn verify_generator_profile_against_mutation_grammar_v1(
    profile: &ParameterGeneratorProfileV3,
    manifest: &MutationGrammarManifestV1,
) -> Result<(), MutationGrammarErrorV1> {
    verify_mutation_grammar_manifest_v1(manifest)?;
    if profile.selected_artifact_digest != manifest.selected_artifact_digest {
        return Err(MutationGrammarErrorV1::ArtifactMismatch);
    }
    let allowed = manifest
        .allowed_parameters
        .iter()
        .map(|rule| (rule.parameter_id.clone(), rule))
        .collect::<BTreeMap<_, _>>();
    let protected = manifest
        .protected_parameters
        .iter()
        .map(|entry| entry.parameter_id.clone())
        .collect::<BTreeSet<_>>();
    for signal in &profile.signals {
        if protected.contains(&signal.parameter_id) {
            return Err(MutationGrammarErrorV1::ProtectedParameterAllowed(
                signal.parameter_id.to_string(),
            ));
        }
        let Some(rule) = allowed.get(&signal.parameter_id) else {
            return Err(MutationGrammarErrorV1::SignalNotAllowed(
                signal.parameter_id.to_string(),
            ));
        };
        if rule.layer_id != signal.layer_id {
            return Err(MutationGrammarErrorV1::SignalLayerMismatch(
                signal.parameter_id.to_string(),
            ));
        }
        if signal.lower_bound < rule.minimum_delta || signal.upper_bound > rule.maximum_delta {
            return Err(MutationGrammarErrorV1::SignalBoundsWidened(
                signal.parameter_id.to_string(),
            ));
        }
    }
    Ok(())
}

fn canonicalize_and_validate(
    selected_artifact_digest: Digest32,
    revision: u64,
    allowed_parameters: &mut Vec<ParameterMutationRuleV1>,
    protected_parameters: &mut Vec<ProtectedParameterV1>,
) -> Result<(), MutationGrammarErrorV1> {
    if selected_artifact_digest.is_zero() {
        return Err(MutationGrammarErrorV1::EmptyArtifactDigest);
    }
    if revision == 0 {
        return Err(MutationGrammarErrorV1::InvalidRevision);
    }
    if allowed_parameters.len() > MAX_MUTATION_RULES {
        return Err(MutationGrammarErrorV1::RuleLimitExceeded);
    }
    if protected_parameters.len() > MAX_PROTECTED_PARAMETERS {
        return Err(MutationGrammarErrorV1::ProtectedLimitExceeded);
    }
    allowed_parameters.sort();
    protected_parameters.sort();

    let mut allowed_ids = BTreeSet::new();
    for rule in allowed_parameters.iter() {
        if !allowed_ids.insert(rule.parameter_id.clone()) {
            return Err(MutationGrammarErrorV1::DuplicateAllowedParameter(
                rule.parameter_id.to_string(),
            ));
        }
        if rule.minimum_delta > rule.maximum_delta {
            return Err(MutationGrammarErrorV1::InvertedRuleBounds(
                rule.parameter_id.to_string(),
            ));
        }
    }
    let mut protected_ids = BTreeSet::new();
    for entry in protected_parameters.iter() {
        if !protected_ids.insert(entry.parameter_id.clone()) {
            return Err(MutationGrammarErrorV1::DuplicateProtectedParameter(
                entry.parameter_id.to_string(),
            ));
        }
        if allowed_ids.contains(&entry.parameter_id) {
            return Err(MutationGrammarErrorV1::ProtectedParameterAllowed(
                entry.parameter_id.to_string(),
            ));
        }
    }
    Ok(())
}

fn digest_manifest(
    manifest: &MutationGrammarManifestV1,
) -> Result<Digest32, MutationGrammarErrorV1> {
    let mut bytes = b"hepta.plasticity.mutation-grammar.v1\0".to_vec();
    push_id(&mut bytes, &manifest.manifest_id)?;
    bytes.extend_from_slice(manifest.selected_artifact_digest.as_array());
    bytes.extend_from_slice(&manifest.revision.to_be_bytes());
    push_len(&mut bytes, manifest.allowed_parameters.len())?;
    for rule in &manifest.allowed_parameters {
        push_id(&mut bytes, &rule.layer_id)?;
        push_id(&mut bytes, &rule.parameter_id)?;
        bytes.extend_from_slice(&rule.minimum_delta.raw().to_be_bytes());
        bytes.extend_from_slice(&rule.maximum_delta.raw().to_be_bytes());
    }
    push_len(&mut bytes, manifest.protected_parameters.len())?;
    for protected in &manifest.protected_parameters {
        push_id(&mut bytes, &protected.parameter_id)?;
        bytes.push(protected.class.tag());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), MutationGrammarErrorV1> {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len())?;
    bytes.extend_from_slice(raw);
    Ok(())
}

fn push_len(bytes: &mut Vec<u8>, value: usize) -> Result<(), MutationGrammarErrorV1> {
    let length = u32::try_from(value).map_err(|_| MutationGrammarErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{LayerNormDenominatorV2, ParameterPlasticitySignalV3, ProposalWindowV2};

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("valid id")
    }
    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn manifest() -> MutationGrammarManifestV1 {
        build_mutation_grammar_manifest_v1(
            id("grammar:1"),
            digest("artifact"),
            1,
            vec![ParameterMutationRuleV1 {
                layer_id: id("layer:1"),
                parameter_id: id("parameter:allowed"),
                minimum_delta: FixedQ32::from_raw(-10),
                maximum_delta: FixedQ32::from_raw(10),
            }],
            vec![ProtectedParameterV1 {
                parameter_id: id("parameter:authority"),
                class: ProtectedParameterClassV1::Authority,
            }],
        )
        .expect("manifest")
    }

    fn profile(parameter_id: &str) -> ParameterGeneratorProfileV3 {
        ParameterGeneratorProfileV3 {
            selected_artifact_digest: digest("artifact"),
            window: ProposalWindowV2 {
                window_id: id("window:1"),
                window_digest: digest("window"),
            },
            norm_layers: vec![LayerNormDenominatorV2 {
                layer_id: id("layer:1"),
                baseline_squared_l2_raw_q64: 1,
            }],
            update_scales: vec![FixedQ32::ONE],
            signals: vec![ParameterPlasticitySignalV3 {
                layer_id: id("layer:1"),
                parameter_id: id(parameter_id),
                eligibility: FixedQ32::ONE,
                modulator: FixedQ32::ONE,
                learning_rate: FixedQ32::ONE,
                lower_bound: FixedQ32::from_raw(-5),
                upper_bound: FixedQ32::from_raw(5),
                evidence_digest: digest("evidence"),
            }],
        }
    }

    #[test]
    fn typed_grammar_allows_only_declared_bounded_parameter() {
        verify_generator_profile_against_mutation_grammar_v1(
            &profile("parameter:allowed"),
            &manifest(),
        )
        .expect("allowed");
    }

    #[test]
    fn typed_grammar_rejects_protected_or_unknown_parameter() {
        assert!(matches!(
            verify_generator_profile_against_mutation_grammar_v1(
                &profile("parameter:authority"),
                &manifest()
            ),
            Err(MutationGrammarErrorV1::ProtectedParameterAllowed(_))
        ));
        assert!(matches!(
            verify_generator_profile_against_mutation_grammar_v1(
                &profile("parameter:unknown"),
                &manifest()
            ),
            Err(MutationGrammarErrorV1::SignalNotAllowed(_))
        ));
    }

    #[test]
    fn typed_grammar_rejects_bound_widening() {
        let mut value = profile("parameter:allowed");
        value.signals[0].upper_bound = FixedQ32::from_raw(11);
        assert!(matches!(
            verify_generator_profile_against_mutation_grammar_v1(&value, &manifest()),
            Err(MutationGrammarErrorV1::SignalBoundsWidened(_))
        ));
    }
}
