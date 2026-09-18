//! Typed mutation grammar for governed parameter plasticity.
//!
//! The manifest is an explicit allowlist/protected-surface policy. A digest alone
//! is never treated as authorization: every generated signal must match one typed
//! rule bound to the exact selected artifact and proposal window.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::{Digest32, FixedQ32, StableId};

use crate::ProposalWindowV2;

const MAX_MUTATION_RULES_V1: usize = 4_096;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum ParameterMutationSurfaceV1 {
    LearnableParameter,
    Authority,
    Evaluator,
    Deletion,
    RuntimeTopology,
    Credential,
}

impl ParameterMutationSurfaceV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::LearnableParameter => 0,
            Self::Authority => 1,
            Self::Evaluator => 2,
            Self::Deletion => 3,
            Self::RuntimeTopology => 4,
            Self::Credential => 5,
        }
    }
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct ParameterMutationRuleV1 {
    pub parameter_id: StableId,
    pub layer_id: StableId,
    pub surface: ParameterMutationSurfaceV1,
    pub minimum_delta: FixedQ32,
    pub maximum_delta: FixedQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParameterMutationPolicyV1 {
    pub manifest_id: StableId,
    pub selected_artifact_digest: Digest32,
    pub window: ProposalWindowV2,
    pub rules: Vec<ParameterMutationRuleV1>,
    pub manifest_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ParameterMutationPolicyErrorV1 {
    EmptyArtifact,
    EmptyWindow,
    RuleLimit,
    DuplicateParameter(String),
    InvertedBounds(String),
    DigestMismatch,
    ArtifactMismatch,
    WindowMismatch,
    MissingRule(String),
    LayerMismatch(String),
    ProtectedSurface(String),
    BoundsEscape(String),
    Arithmetic,
}

impl fmt::Display for ParameterMutationPolicyErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for ParameterMutationPolicyErrorV1 {}

pub fn build_parameter_mutation_policy_v1(
    manifest_id: StableId,
    selected_artifact_digest: Digest32,
    window: ProposalWindowV2,
    mut rules: Vec<ParameterMutationRuleV1>,
) -> Result<ParameterMutationPolicyV1, ParameterMutationPolicyErrorV1> {
    validate_context(selected_artifact_digest, &window, &mut rules)?;
    let mut manifest = ParameterMutationPolicyV1 {
        manifest_id,
        selected_artifact_digest,
        window,
        rules,
        manifest_digest: Digest32::ZERO,
    };
    manifest.manifest_digest = digest_manifest(&manifest)?;
    Ok(manifest)
}

pub fn verify_parameter_mutation_policy_v1(
    manifest: &ParameterMutationPolicyV1,
) -> Result<(), ParameterMutationPolicyErrorV1> {
    let mut rules = manifest.rules.clone();
    validate_context(
        manifest.selected_artifact_digest,
        &manifest.window,
        &mut rules,
    )?;
    if rules != manifest.rules || manifest.manifest_digest.is_zero() {
        return Err(ParameterMutationPolicyErrorV1::DigestMismatch);
    }
    if digest_manifest(manifest)? != manifest.manifest_digest {
        return Err(ParameterMutationPolicyErrorV1::DigestMismatch);
    }
    Ok(())
}

pub fn authorize_parameter_mutation_v1(
    manifest: &ParameterMutationPolicyV1,
    selected_artifact_digest: Digest32,
    window: &ProposalWindowV2,
    layer_id: &StableId,
    parameter_id: &StableId,
    lower_bound: FixedQ32,
    upper_bound: FixedQ32,
) -> Result<(), ParameterMutationPolicyErrorV1> {
    verify_parameter_mutation_policy_v1(manifest)?;
    if manifest.selected_artifact_digest != selected_artifact_digest {
        return Err(ParameterMutationPolicyErrorV1::ArtifactMismatch);
    }
    if &manifest.window != window {
        return Err(ParameterMutationPolicyErrorV1::WindowMismatch);
    }
    let rule = manifest
        .rules
        .binary_search_by(|rule| rule.parameter_id.cmp(parameter_id))
        .ok()
        .and_then(|index| manifest.rules.get(index))
        .ok_or_else(|| ParameterMutationPolicyErrorV1::MissingRule(parameter_id.to_string()))?;
    if &rule.layer_id != layer_id {
        return Err(ParameterMutationPolicyErrorV1::LayerMismatch(
            parameter_id.to_string(),
        ));
    }
    if rule.surface != ParameterMutationSurfaceV1::LearnableParameter {
        return Err(ParameterMutationPolicyErrorV1::ProtectedSurface(
            parameter_id.to_string(),
        ));
    }
    if lower_bound < rule.minimum_delta || upper_bound > rule.maximum_delta {
        return Err(ParameterMutationPolicyErrorV1::BoundsEscape(
            parameter_id.to_string(),
        ));
    }
    Ok(())
}

fn validate_context(
    selected_artifact_digest: Digest32,
    window: &ProposalWindowV2,
    rules: &mut Vec<ParameterMutationRuleV1>,
) -> Result<(), ParameterMutationPolicyErrorV1> {
    if selected_artifact_digest.is_zero() {
        return Err(ParameterMutationPolicyErrorV1::EmptyArtifact);
    }
    if window.window_digest.is_zero() {
        return Err(ParameterMutationPolicyErrorV1::EmptyWindow);
    }
    if rules.len() > MAX_MUTATION_RULES_V1 {
        return Err(ParameterMutationPolicyErrorV1::RuleLimit);
    }
    rules.sort_by(|left, right| left.parameter_id.cmp(&right.parameter_id));
    let mut seen = BTreeSet::new();
    for rule in rules.iter() {
        if !seen.insert(rule.parameter_id.clone()) {
            return Err(ParameterMutationPolicyErrorV1::DuplicateParameter(
                rule.parameter_id.to_string(),
            ));
        }
        if rule.minimum_delta > rule.maximum_delta {
            return Err(ParameterMutationPolicyErrorV1::InvertedBounds(
                rule.parameter_id.to_string(),
            ));
        }
    }
    Ok(())
}

fn digest_manifest(
    manifest: &ParameterMutationPolicyV1,
) -> Result<Digest32, ParameterMutationPolicyErrorV1> {
    let mut bytes = b"hepta.plasticity.mutation-grammar.v1\0".to_vec();
    push_id(&mut bytes, &manifest.manifest_id)?;
    bytes.extend_from_slice(manifest.selected_artifact_digest.as_array());
    push_id(&mut bytes, &manifest.window.window_id)?;
    bytes.extend_from_slice(manifest.window.window_digest.as_array());
    push_len(&mut bytes, manifest.rules.len())?;
    for rule in &manifest.rules {
        push_id(&mut bytes, &rule.parameter_id)?;
        push_id(&mut bytes, &rule.layer_id)?;
        bytes.push(rule.surface.tag());
        bytes.extend_from_slice(&rule.minimum_delta.raw().to_be_bytes());
        bytes.extend_from_slice(&rule.maximum_delta.raw().to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), ParameterMutationPolicyErrorV1> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| ParameterMutationPolicyErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

fn push_len(bytes: &mut Vec<u8>, value: usize) -> Result<(), ParameterMutationPolicyErrorV1> {
    let value = u32::try_from(value).map_err(|_| ParameterMutationPolicyErrorV1::Arithmetic)?;
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
            window_id: id("window:grammar"),
            window_digest: digest(b"window"),
        }
    }
    fn rule(surface: ParameterMutationSurfaceV1) -> ParameterMutationRuleV1 {
        ParameterMutationRuleV1 {
            parameter_id: id("parameter:1"),
            layer_id: id("layer:1"),
            surface,
            minimum_delta: FixedQ32::from_raw(-100),
            maximum_delta: FixedQ32::from_raw(100),
        }
    }

    #[test]
    fn learnable_rule_authorizes_only_exact_context_and_bounds() {
        let artifact = digest(b"artifact");
        let manifest = build_parameter_mutation_policy_v1(
            id("grammar:1"),
            artifact,
            window(),
            vec![rule(ParameterMutationSurfaceV1::LearnableParameter)],
        )
        .expect("manifest");
        authorize_parameter_mutation_v1(
            &manifest,
            artifact,
            &window(),
            &id("layer:1"),
            &id("parameter:1"),
            FixedQ32::from_raw(-10),
            FixedQ32::from_raw(10),
        )
        .expect("authorized");
    }

    #[test]
    fn protected_surface_fails_closed() {
        let artifact = digest(b"artifact");
        let manifest = build_parameter_mutation_policy_v1(
            id("grammar:1"),
            artifact,
            window(),
            vec![rule(ParameterMutationSurfaceV1::Authority)],
        )
        .expect("manifest");
        assert!(matches!(
            authorize_parameter_mutation_v1(
                &manifest,
                artifact,
                &window(),
                &id("layer:1"),
                &id("parameter:1"),
                FixedQ32::ZERO,
                FixedQ32::ZERO,
            ),
            Err(ParameterMutationPolicyErrorV1::ProtectedSurface(_))
        ));
    }
}
