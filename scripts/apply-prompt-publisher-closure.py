#!/usr/bin/env python3
"""Apply authenticated prompt registry publisher bindings and Agentd ingress."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    file_path = ROOT / path
    text = file_path.read_text(encoding="utf-8")
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one exact anchor, found {count}: {old[:100]!r}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_admission() -> None:
    path = "codex-rs/hepta-prompt-registry/src/admission.rs"
    replace_once(
        path,
        "use crate::PromptFactor;\nuse crate::PromptRealizationBindingV2;",
        "use crate::PromptFactor;\nuse crate::PromptFactorRelation;\n"
        "use crate::PromptFactorRelationKind;\nuse crate::PromptRealizationBindingV2;",
    )
    replace_once(
        path,
        "const FINAL_USE_REALIZATION_DESTINATION: &str = \"prompt.registry:realization\";\n",
        "const FINAL_USE_REALIZATION_DESTINATION: &str = \"prompt.registry:realization\";\n"
        "const FINAL_USE_REGISTER_FACTOR_DESTINATION: &str = \"prompt.registry:register-factor\";\n"
        "const FINAL_USE_REGISTER_RELATION_DESTINATION: &str = \"prompt.registry:register-relation\";\n"
        "const FINAL_USE_REGISTER_FACTOR_REQUEST_DOMAIN: &[u8] =\n"
        "    b\"hepta.prompt-registry.final-use-register-factor.v1\\0\";\n"
        "const FINAL_USE_REGISTER_RELATION_REQUEST_DOMAIN: &[u8] =\n"
        "    b\"hepta.prompt-registry.final-use-register-relation.v1\\0\";\n",
    )
    replace_once(
        path,
        "pub fn final_use_admission_binding(\n",
        "pub fn final_use_register_factor_binding(\n"
        "    factor: &PromptFactor,\n"
        "    actor_id: &StableId,\n"
        "    scope_digest: Digest32,\n"
        ") -> Result<FinalUseBinding, AdmissionError> {\n"
        "    if factor.source != FactorSource::GovernedInternal\n"
        "        || factor.lifecycle != crate::Lifecycle::Draft\n"
        "        || factor.content_digest.is_zero()\n"
        "        || scope_digest.is_zero()\n"
        "    {\n"
        "        return Err(AdmissionError::ScopeMismatch);\n"
        "    }\n"
        "    let mut request = FINAL_USE_REGISTER_FACTOR_REQUEST_DOMAIN.to_vec();\n"
        "    push_id(&mut request, &factor.factor_id);\n"
        "    push_id(&mut request, &factor.proposer_id);\n"
        "    push_id(&mut request, &factor.semantic_version);\n"
        "    push_text(&mut request, &factor.semantic_purpose);\n"
        "    push_text(&mut request, &factor.authority_class);\n"
        "    request.extend_from_slice(\n"
        "        &u32::try_from(factor.eligible_objective_dimensions.len())\n"
        "            .unwrap_or(u32::MAX)\n"
        "            .to_be_bytes(),\n"
        "    );\n"
        "    for dimension in &factor.eligible_objective_dimensions {\n"
        "        push_id(&mut request, dimension);\n"
        "    }\n"
        "    request.extend_from_slice(factor.content_digest.as_array());\n"
        "    Ok(FinalUseBinding {\n"
        "        subject_id: actor_id.to_string(),\n"
        "        destination_id: FINAL_USE_REGISTER_FACTOR_DESTINATION.to_owned(),\n"
        "        request_sha256: Digest32::of_bytes(&request).into_array(),\n"
        "        scope_sha256: scope_digest.into_array(),\n"
        "        payload_sha256: factor.content_digest.into_array(),\n"
        "    })\n"
        "}\n\n"
        "pub fn final_use_register_relation_binding(\n"
        "    relation: &PromptFactorRelation,\n"
        "    actor_id: &StableId,\n"
        "    scope_digest: Digest32,\n"
        ") -> Result<FinalUseBinding, AdmissionError> {\n"
        "    if relation.evidence_digest.is_zero()\n"
        "        || relation.left_factor_id >= relation.right_factor_id\n"
        "        || scope_digest.is_zero()\n"
        "    {\n"
        "        return Err(AdmissionError::ScopeMismatch);\n"
        "    }\n"
        "    let mut request = FINAL_USE_REGISTER_RELATION_REQUEST_DOMAIN.to_vec();\n"
        "    push_id(&mut request, &relation.relation_id);\n"
        "    push_id(&mut request, &relation.left_factor_id);\n"
        "    push_id(&mut request, &relation.right_factor_id);\n"
        "    request.push(match relation.kind {\n"
        "        PromptFactorRelationKind::Complements => 0,\n"
        "        PromptFactorRelationKind::Substitutes => 1,\n"
        "        PromptFactorRelationKind::Conflicts => 2,\n"
        "    });\n"
        "    request.extend_from_slice(relation.evidence_digest.as_array());\n"
        "    Ok(FinalUseBinding {\n"
        "        subject_id: actor_id.to_string(),\n"
        "        destination_id: FINAL_USE_REGISTER_RELATION_DESTINATION.to_owned(),\n"
        "        request_sha256: Digest32::of_bytes(&request).into_array(),\n"
        "        scope_sha256: scope_digest.into_array(),\n"
        "        payload_sha256: relation.evidence_digest.into_array(),\n"
        "    })\n"
        "}\n\n"
        "pub fn final_use_admission_binding(\n",
    )


def patch_registry_exports() -> None:
    path = "codex-rs/hepta-prompt-registry/src/lib.rs"
    replace_once(
        path,
        "pub use admission::final_use_admission_binding;\n"
        "pub use admission::final_use_realization_binding;",
        "pub use admission::final_use_admission_binding;\n"
        "pub use admission::final_use_register_factor_binding;\n"
        "pub use admission::final_use_register_relation_binding;\n"
        "pub use admission::final_use_realization_binding;",
    )


def patch_durable() -> None:
    path = "codex-rs/hepta-prompt-registry/src/durable.rs"
    replace_once(
        path,
        "use crate::final_use_realization_binding;\n"
        "use crate::final_use_retire_binding;",
        "use crate::final_use_realization_binding;\n"
        "use crate::final_use_register_factor_binding;\n"
        "use crate::final_use_register_relation_binding;\n"
        "use crate::final_use_retire_binding;",
    )
    replace_once(
        path,
        "    pub fn register_factor(\n"
        "        &mut self,\n"
        "        factor: PromptFactor,\n"
        "    ) -> Result<RegistryReceipt, DurableRegistryError> {\n"
        "        self.commit(|registry| registry.register_factor(factor))\n"
        "    }\n\n",
        "    pub fn register_factor(\n"
        "        &mut self,\n"
        "        factor: PromptFactor,\n"
        "    ) -> Result<RegistryReceipt, DurableRegistryError> {\n"
        "        self.commit(|registry| registry.register_factor(factor))\n"
        "    }\n\n"
        "    pub fn register_factor_final_use(\n"
        "        &mut self,\n"
        "        authority: &FinalUseAuthority,\n"
        "        signed: &SignedFinalUseGrant,\n"
        "        actor_id: &StableId,\n"
        "        scope_digest: Digest32,\n"
        "        factor: PromptFactor,\n"
        "    ) -> Result<RegistryReceipt, DurableRegistryError> {\n"
        "        self.ensure_available()?;\n"
        "        let expected = final_use_register_factor_binding(&factor, actor_id, scope_digest)\n"
        "            .map_err(DurableRegistryError::Admission)?;\n"
        "        let token = authority\n"
        "            .claim(signed, &expected)\n"
        "            .map_err(map_final_use_error)\n"
        "            .map_err(DurableRegistryError::Admission)?;\n"
        "        authority\n"
        "            .with_verified_use(token, &expected, || {\n"
        "                self.commit(|registry| registry.register_factor(factor))\n"
        "            })\n"
        "            .map_err(map_final_use_error)\n"
        "            .map_err(DurableRegistryError::Admission)?\n"
        "    }\n\n",
    )
    replace_once(
        path,
        "    pub fn register_factor_relation(\n"
        "        &mut self,\n"
        "        relation: PromptFactorRelation,\n"
        "    ) -> Result<RegistryReceipt, DurableRegistryError> {\n"
        "        self.commit(|registry| registry.register_factor_relation(relation))\n"
        "    }\n\n",
        "    pub fn register_factor_relation(\n"
        "        &mut self,\n"
        "        relation: PromptFactorRelation,\n"
        "    ) -> Result<RegistryReceipt, DurableRegistryError> {\n"
        "        self.commit(|registry| registry.register_factor_relation(relation))\n"
        "    }\n\n"
        "    pub fn register_factor_relation_final_use(\n"
        "        &mut self,\n"
        "        authority: &FinalUseAuthority,\n"
        "        signed: &SignedFinalUseGrant,\n"
        "        actor_id: &StableId,\n"
        "        scope_digest: Digest32,\n"
        "        relation: PromptFactorRelation,\n"
        "    ) -> Result<RegistryReceipt, DurableRegistryError> {\n"
        "        self.ensure_available()?;\n"
        "        let expected = final_use_register_relation_binding(\n"
        "            &relation,\n"
        "            actor_id,\n"
        "            scope_digest,\n"
        "        )\n"
        "        .map_err(DurableRegistryError::Admission)?;\n"
        "        let token = authority\n"
        "            .claim(signed, &expected)\n"
        "            .map_err(map_final_use_error)\n"
        "            .map_err(DurableRegistryError::Admission)?;\n"
        "        authority\n"
        "            .with_verified_use(token, &expected, || {\n"
        "                self.commit(|registry| registry.register_factor_relation(relation))\n"
        "            })\n"
        "            .map_err(map_final_use_error)\n"
        "            .map_err(DurableRegistryError::Admission)?\n"
        "    }\n\n",
    )


def patch_agentd_publisher() -> None:
    path = "codex-rs/hepta-agentd/src/prompt_runtime.rs"
    replace_once(
        path,
        "use codex_hepta_intelligence::compile_prompt_registry_v2;\n",
        "use codex_hepta_intelligence::compile_prompt_registry_v2;\n"
        "use codex_hepta_contracts::FinalUseAuthority;\n"
        "use codex_hepta_contracts::SignedFinalUseGrant;\n",
    )
    replace_once(
        path,
        "use codex_hepta_prompt_registry::DurablePromptRegistry;\n"
        "use codex_hepta_prompt_registry::PromptRoleV2;",
        "use codex_hepta_prompt_registry::DurablePromptRegistry;\n"
        "use codex_hepta_prompt_registry::PromptFactor;\n"
        "use codex_hepta_prompt_registry::PromptFactorRelation;\n"
        "use codex_hepta_prompt_registry::PromptRealizationBindingV2;\n"
        "use codex_hepta_prompt_registry::PromptRoleV2;\n"
        "use codex_hepta_prompt_registry::RegistryReceipt;",
    )
    replace_once(
        path,
        "    FinalUseStore(PromptFinalUseStoreError),\n}",
        "    FinalUseStore(PromptFinalUseStoreError),\n"
        "    Publisher(String),\n}"
    )
    marker = "    /// Enumerate candidates from this owner's exact current durable registry.\n"
    methods = (
        "    /// Authenticated production writer for draft factor publication.\n"
        "    pub fn publish_factor(\n"
        "        &self,\n"
        "        authority: &FinalUseAuthority,\n"
        "        signed: &SignedFinalUseGrant,\n"
        "        actor_id: &StableId,\n"
        "        scope_digest: Digest32,\n"
        "        factor: PromptFactor,\n"
        "    ) -> Result<RegistryReceipt, AgentdPromptPipelineError> {\n"
        "        self.registry\n"
        "            .lock()\n"
        "            .map_err(|_| AgentdPromptPipelineError::StatePoisoned)?\n"
        "            .register_factor_final_use(authority, signed, actor_id, scope_digest, factor)\n"
        "            .map_err(|error| AgentdPromptPipelineError::Publisher(error.to_string()))\n"
        "    }\n\n"
        "    pub fn admit_factor(\n"
        "        &self,\n"
        "        authority: &FinalUseAuthority,\n"
        "        signed: &SignedFinalUseGrant,\n"
        "        factor_id: &StableId,\n"
        "        reviewed_scope_digest: Digest32,\n"
        "        evidence_digest: Digest32,\n"
        "    ) -> Result<RegistryReceipt, AgentdPromptPipelineError> {\n"
        "        self.registry\n"
        "            .lock()\n"
        "            .map_err(|_| AgentdPromptPipelineError::StatePoisoned)?\n"
        "            .admit_factor_final_use(\n"
        "                authority,\n"
        "                signed,\n"
        "                factor_id,\n"
        "                reviewed_scope_digest,\n"
        "                evidence_digest,\n"
        "            )\n"
        "            .map_err(|error| AgentdPromptPipelineError::Publisher(error.to_string()))\n"
        "    }\n\n"
        "    #[allow(clippy::too_many_arguments)]\n"
        "    pub fn publish_realization(\n"
        "        &self,\n"
        "        authority: &FinalUseAuthority,\n"
        "        signed: &SignedFinalUseGrant,\n"
        "        actor_id: &StableId,\n"
        "        scope_digest: Digest32,\n"
        "        binding: PromptRealizationBindingV2,\n"
        "        payload: Vec<u8>,\n"
        "        supersedes_realization_id: Option<StableId>,\n"
        "    ) -> Result<RegistryReceipt, AgentdPromptPipelineError> {\n"
        "        self.registry\n"
        "            .lock()\n"
        "            .map_err(|_| AgentdPromptPipelineError::StatePoisoned)?\n"
        "            .register_realization_payload_final_use_v2(\n"
        "                authority,\n"
        "                signed,\n"
        "                actor_id,\n"
        "                scope_digest,\n"
        "                binding,\n"
        "                payload,\n"
        "                supersedes_realization_id,\n"
        "            )\n"
        "            .map_err(|error| AgentdPromptPipelineError::Publisher(error.to_string()))\n"
        "    }\n\n"
        "    pub fn publish_relation(\n"
        "        &self,\n"
        "        authority: &FinalUseAuthority,\n"
        "        signed: &SignedFinalUseGrant,\n"
        "        actor_id: &StableId,\n"
        "        scope_digest: Digest32,\n"
        "        relation: PromptFactorRelation,\n"
        "    ) -> Result<RegistryReceipt, AgentdPromptPipelineError> {\n"
        "        self.registry\n"
        "            .lock()\n"
        "            .map_err(|_| AgentdPromptPipelineError::StatePoisoned)?\n"
        "            .register_factor_relation_final_use(\n"
        "                authority,\n"
        "                signed,\n"
        "                actor_id,\n"
        "                scope_digest,\n"
        "                relation,\n"
        "            )\n"
        "            .map_err(|error| AgentdPromptPipelineError::Publisher(error.to_string()))\n"
        "    }\n\n"
        + marker
    )
    replace_once(path, marker, methods)


def main() -> None:
    patch_admission()
    patch_registry_exports()
    patch_durable()
    patch_agentd_publisher()


if __name__ == "__main__":
    main()
