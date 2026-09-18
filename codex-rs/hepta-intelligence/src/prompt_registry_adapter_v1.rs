//! Adapter from the prompt-registry owner's V2 frozen view into the canonical
//! prompt-optimizer candidate source.
//!
//! This adapter authenticates by retaining one validated in-process owner view
//! and accepting only the exact derived source. Remote or cross-process callers
//! still need a host-authenticated transport for that owner view.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_prompt_optimizer::CanonicalPromptErrorV1;
use codex_hepta_prompt_optimizer::PromptAuthenticationErrorV1;
use codex_hepta_prompt_optimizer::PromptCandidateBindingV1;
use codex_hepta_prompt_optimizer::PromptCandidateRoleV1;
use codex_hepta_prompt_optimizer::PromptCandidateSourceAuthenticatorV1;
use codex_hepta_prompt_optimizer::PromptCandidateSourceV1;
use codex_hepta_prompt_optimizer::PromptModelProfileV1;
use codex_hepta_prompt_registry::CompatibleRealizationSetV2;
use codex_hepta_prompt_registry::PromptModelTupleV2;
use codex_hepta_prompt_registry::PromptRealizationBindingV2;
use codex_hepta_prompt_registry::PromptRegistrySnapshotV2;
use codex_hepta_prompt_registry::PromptRegistryV2Error;
use codex_hepta_prompt_registry::PromptRoleV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRegistryCandidateAdapterV1 {
    source: PromptCandidateSourceV1,
    owner_view_digest: Digest32,
}

impl PromptRegistryCandidateAdapterV1 {
    pub fn from_owner_view(
        snapshot: &PromptRegistrySnapshotV2,
        compatible: &CompatibleRealizationSetV2,
        model: &PromptModelTupleV2,
        now_unix_ms: u64,
    ) -> Result<Self, PromptRegistryAdapterErrorV1> {
        if now_unix_ms == 0 {
            return Err(PromptRegistryAdapterErrorV1::InvalidOwnerView);
        }
        snapshot
            .validate()
            .map_err(PromptRegistryAdapterErrorV1::Registry)?;
        compatible
            .validate()
            .map_err(PromptRegistryAdapterErrorV1::Registry)?;
        model
            .validate()
            .map_err(PromptRegistryAdapterErrorV1::Registry)?;
        let model_digest = model.digest();
        if snapshot.model_tuple_digest != model_digest
            || compatible.snapshot_digest != snapshot.snapshot_digest
            || compatible.model_tuple_digest != model_digest
            || snapshot.authority.grants_any()
            || compatible.authority.grants_any()
        {
            return Err(PromptRegistryAdapterErrorV1::InvalidOwnerView);
        }
        validate_required_factor_coverage(compatible)?;
        let mut candidates = compatible
            .bindings
            .iter()
            .map(|binding| adapt_binding(binding, model, compatible, now_unix_ms))
            .collect::<Result<Vec<_>, _>>()?;
        candidates.sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));

        let mut source = PromptCandidateSourceV1 {
            owner_id: StableId::new("prompt.registry")
                .map_err(|_| PromptRegistryAdapterErrorV1::InternalInvariant)?,
            registry_snapshot_digest: snapshot.snapshot_digest,
            registry_revision: snapshot.revision.get(),
            revocation_frontier: snapshot.revocation_frontier,
            generation_vector_digest: snapshot.generation_vector_digest,
            model_profile: PromptModelProfileV1 {
                model_digest: model.model_digest,
                tokenizer_digest: model.tokenizer_digest,
                template_digest: model.template_digest,
                tool_schema_digest: model.tool_schema_digest,
                locale_id: model.locale_id.clone(),
            },
            bindings: candidates,
            omitted_count: compatible.omitted_count,
            source_digest: Digest32::ZERO,
        };
        source.source_digest = source.compute_source_digest();
        source
            .validate_at(now_unix_ms)
            .map_err(PromptRegistryAdapterErrorV1::Canonical)?;
        let owner_view_digest = owner_view_digest(snapshot, compatible, model);
        Ok(Self {
            source,
            owner_view_digest,
        })
    }

    #[must_use]
    pub fn source(&self) -> &PromptCandidateSourceV1 {
        &self.source
    }

    #[must_use]
    pub const fn owner_view_digest(&self) -> Digest32 {
        self.owner_view_digest
    }
}

impl PromptCandidateSourceAuthenticatorV1 for PromptRegistryCandidateAdapterV1 {
    fn authenticate_candidate_source(
        &self,
        source: &PromptCandidateSourceV1,
        objective_digest: Digest32,
        now_unix_ms: u64,
    ) -> Result<(), PromptAuthenticationErrorV1> {
        if objective_digest.is_zero()
            || now_unix_ms == 0
            || source != &self.source
            || source.validate_at(now_unix_ms).is_err()
        {
            return Err(PromptAuthenticationErrorV1::Rejected);
        }
        Ok(())
    }
}

fn adapt_binding(
    binding: &PromptRealizationBindingV2,
    model: &PromptModelTupleV2,
    compatible: &CompatibleRealizationSetV2,
    now_unix_ms: u64,
) -> Result<PromptCandidateBindingV1, PromptRegistryAdapterErrorV1> {
    binding
        .validate()
        .map_err(PromptRegistryAdapterErrorV1::Registry)?;
    if binding.model_digest != model.model_digest
        || binding.tokenizer_digest != model.tokenizer_digest
        || binding.template_digest != model.template_digest
        || binding.tool_schema_digest != model.tool_schema_digest
        || binding.locale_id != model.locale_id
    {
        return Err(PromptRegistryAdapterErrorV1::ModelTupleMismatch(
            binding.realization_id.to_string(),
        ));
    }
    if binding
        .expires_unix_ms
        .is_some_and(|expires| now_unix_ms >= expires)
    {
        return Err(PromptRegistryAdapterErrorV1::ExpiredRealization(
            binding.realization_id.to_string(),
        ));
    }
    let mut candidate = PromptCandidateBindingV1 {
        candidate_id: binding.realization_id.clone(),
        factor_id: binding.factor_id.clone(),
        realization_id: binding.realization_id.clone(),
        role: adapt_role(binding.role),
        payload_digest: binding.payload_digest,
        admission_digest: binding.digest(),
        support_digest: compatible.set_digest,
        token_cost: u64::from(binding.token_cost),
        expires_unix_ms: binding.expires_unix_ms,
        binding_digest: Digest32::ZERO,
    };
    candidate.binding_digest = candidate.compute_binding_digest();
    Ok(candidate)
}

fn adapt_role(role: PromptRoleV2) -> PromptCandidateRoleV1 {
    match role {
        PromptRoleV2::SystemInstruction => PromptCandidateRoleV1::SystemInstruction,
        PromptRoleV2::DeveloperInstruction => PromptCandidateRoleV1::DeveloperInstruction,
        PromptRoleV2::UserTemplate => PromptCandidateRoleV1::UserTemplate,
        PromptRoleV2::ToolSchemaFragment => PromptCandidateRoleV1::ToolSchemaFragment,
    }
}

fn validate_required_factor_coverage(
    compatible: &CompatibleRealizationSetV2,
) -> Result<(), PromptRegistryAdapterErrorV1> {
    let mut required = BTreeSet::new();
    for factor_id in &compatible.required_factor_ids {
        if !required.insert(factor_id.clone()) {
            return Err(PromptRegistryAdapterErrorV1::DuplicateRequiredFactor(
                factor_id.to_string(),
            ));
        }
    }
    if required.is_empty() {
        return Ok(());
    }
    let returned = compatible
        .bindings
        .iter()
        .map(|binding| binding.factor_id.clone())
        .collect::<BTreeSet<_>>();
    if let Some(missing) = required
        .into_iter()
        .find(|factor_id| !returned.contains(factor_id))
    {
        return Err(PromptRegistryAdapterErrorV1::RequiredFactorUnavailable(
            missing.to_string(),
        ));
    }
    Ok(())
}

fn owner_view_digest(
    snapshot: &PromptRegistrySnapshotV2,
    compatible: &CompatibleRealizationSetV2,
    model: &PromptModelTupleV2,
) -> Digest32 {
    let mut bytes = b"hepta.intelligence.prompt-registry-owner-view.v1".to_vec();
    bytes.extend_from_slice(snapshot.snapshot_digest.as_array());
    bytes.extend_from_slice(compatible.set_digest.as_array());
    bytes.extend_from_slice(model.digest().as_array());
    Digest32::of_bytes(&bytes)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptRegistryAdapterErrorV1 {
    Registry(PromptRegistryV2Error),
    Canonical(CanonicalPromptErrorV1),
    InvalidOwnerView,
    DuplicateRequiredFactor(String),
    RequiredFactorUnavailable(String),
    ModelTupleMismatch(String),
    ExpiredRealization(String),
    InternalInvariant,
}

impl fmt::Display for PromptRegistryAdapterErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PromptRegistryAdapterErrorV1 {}

#[cfg(test)]
#[path = "prompt_registry_adapter_v1_tests.rs"]
mod tests;
