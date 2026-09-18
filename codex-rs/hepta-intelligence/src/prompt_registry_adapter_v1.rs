//! Authenticated in-process adapter from the durable prompt-registry owner
//! into the canonical prompt-optimizer candidate source.
//!
//! The adapter builds its source directly from DurablePromptRegistry, retaining
//! the exact frozen snapshot and compatible set it authenticated. It never
//! accepts caller-constructed admission or realization-binding digests.

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
use codex_hepta_prompt_registry::DurablePromptRegistry;
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
    snapshot: PromptRegistrySnapshotV2,
    compatible: CompatibleRealizationSetV2,
    owner_view_digest: Digest32,
}

impl PromptRegistryCandidateAdapterV1 {
    pub fn from_registry(
        registry: &DurablePromptRegistry,
        generation_vector_digest: Digest32,
        model: &PromptModelTupleV2,
        now_unix_ms: u64,
        required_factor_ids: Vec<StableId>,
        maximum_results: u32,
    ) -> Result<Self, PromptRegistryAdapterErrorV1> {
        if now_unix_ms == 0 {
            return Err(PromptRegistryAdapterErrorV1::InvalidOwnerView);
        }
        model
            .validate()
            .map_err(PromptRegistryAdapterErrorV1::Registry)?;
        let snapshot = registry
            .snapshot_v2(generation_vector_digest, model)
            .map_err(|_| PromptRegistryAdapterErrorV1::OwnerRejected)?;
        let compatible = registry
            .read_compatible_v2(
                &snapshot,
                generation_vector_digest,
                model,
                now_unix_ms,
                required_factor_ids,
                maximum_results,
            )
            .map_err(|_| PromptRegistryAdapterErrorV1::OwnerRejected)?;
        snapshot
            .validate()
            .map_err(PromptRegistryAdapterErrorV1::Registry)?;
        compatible
            .validate()
            .map_err(PromptRegistryAdapterErrorV1::Registry)?;
        validate_required_factor_coverage(&compatible)?;

        let mut candidates = compatible
            .bindings
            .iter()
            .map(|binding| adapt_binding(registry, binding, model, &compatible, now_unix_ms))
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
                model_id: model.model_id.clone(),
                model_version: model.model_version.clone(),
                model_digest: model.model_digest,
                tokenizer_digest: model.tokenizer_digest,
                template_digest: model.template_digest,
                tool_schema_digest: model.tool_schema_digest,
                context_profile_digest: model.context_profile_digest,
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
        let owner_view_digest = owner_view_digest(&snapshot, &compatible, model);
        Ok(Self {
            source,
            snapshot,
            compatible,
            owner_view_digest,
        })
    }

    #[must_use]
    pub fn source(&self) -> &PromptCandidateSourceV1 {
        &self.source
    }

    #[must_use]
    pub fn snapshot(&self) -> &PromptRegistrySnapshotV2 {
        &self.snapshot
    }

    #[must_use]
    pub fn compatible(&self) -> &CompatibleRealizationSetV2 {
        &self.compatible
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
    registry: &DurablePromptRegistry,
    binding: &PromptRealizationBindingV2,
    model: &PromptModelTupleV2,
    compatible: &CompatibleRealizationSetV2,
    now_unix_ms: u64,
) -> Result<PromptCandidateBindingV1, PromptRegistryAdapterErrorV1> {
    binding
        .validate()
        .map_err(PromptRegistryAdapterErrorV1::Registry)?;
    if binding.model_id != model.model_id
        || binding.model_version != model.model_version
        || binding.model_digest != model.model_digest
        || binding.tokenizer_digest != model.tokenizer_digest
        || binding.template_digest != model.template_digest
        || binding.tool_schema_digest != model.tool_schema_digest
        || binding.context_profile_digest != model.context_profile_digest
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
    let admission_digest = registry
        .registry()
        .admission_event_digest(&binding.factor_id)
        .ok_or_else(|| {
            PromptRegistryAdapterErrorV1::MissingAdmissionLineage(binding.factor_id.to_string())
        })?;
    let mut candidate = PromptCandidateBindingV1 {
        candidate_id: binding.realization_id.clone(),
        factor_id: binding.factor_id.clone(),
        realization_id: binding.realization_id.clone(),
        role: adapt_role(binding.role),
        payload_digest: binding.payload_digest,
        registry_binding_digest: binding.digest(),
        admission_digest,
        support_digest: compatible.set_digest,
        token_cost: u64::from(binding.token_cost),
        expires_unix_ms: binding.expires_unix_ms,
        binding_digest: Digest32::ZERO,
    };
    candidate.binding_digest = candidate.compute_binding_digest();
    Ok(candidate)
}

const fn adapt_role(role: PromptRoleV2) -> PromptCandidateRoleV1 {
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
    OwnerRejected,
    InvalidOwnerView,
    DuplicateRequiredFactor(String),
    RequiredFactorUnavailable(String),
    MissingAdmissionLineage(String),
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
