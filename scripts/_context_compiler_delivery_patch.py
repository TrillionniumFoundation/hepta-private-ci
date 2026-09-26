#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:100]!r}")
    file_path.write_text(text.replace(old, new, 1))


# JSON escaping is part of the canonical bundle. Prove the compiler-owned bytes
# first, then record offsets of the escaped wire representation, never raw text.
replace_once(
    "codex-rs/hepta-intelligence/Cargo.toml",
    "codex-hepta-types = { path = \"../hepta-types\" }\n",
    "codex-hepta-types = { path = \"../hepta-types\" }\n"
    "serde_json = { workspace = true }\n",
)
replace_once(
    "codex-rs/hepta-intelligence/src/prompt_pipeline.rs",
    "use codex_hepta_context_compiler::record_canonical_context_bundle_v2;\n",
    "use codex_hepta_context_compiler::canonical_context_bundle_bytes_v2;\n"
    "use codex_hepta_context_compiler::record_canonical_context_bundle_v2;\n",
)
replace_once(
    "codex-rs/hepta-intelligence/src/prompt_pipeline.rs",
    "    let mut cursor = 0_usize;\n"
    "    let mut occurrences = Vec::with_capacity(materialization.payloads.len());\n"
    "    for item_id in compiled.receipt().selected_item_ids() {",
    "    let by_id = materialization\n"
    "        .payloads\n"
    "        .iter()\n"
    "        .map(|payload| (payload.binding.realization_id.clone(), payload))\n"
    "        .collect::<BTreeMap<_, _>>();\n"
    "    let ordered_realizations = compiled\n"
    "        .receipt()\n"
    "        .selected_item_ids()\n"
    "        .iter()\n"
    "        .map(|item_id| {\n"
    "            let payload = by_id.get(item_id).ok_or_else(|| {\n"
    "                PromptPipelineErrorV1::SelectedRealizationMissing(item_id.to_string())\n"
    "            })?;\n"
    "            Ok(ContextRealizedItemV2 {\n"
    "                item_id: item_id.clone(),\n"
    "                role: match payload.binding.role {\n"
    "                    PromptRoleV2::ToolSchemaFragment => ContextRoleV2::Schema,\n"
    "                    PromptRoleV2::SystemInstruction\n"
    "                    | PromptRoleV2::DeveloperInstruction\n"
    "                    | PromptRoleV2::UserTemplate => ContextRoleV2::TrustedInstruction,\n"
    "                },\n"
    "                content: payload.payload.clone(),\n"
    "            })\n"
    "        })\n"
    "        .collect::<Result<Vec<_>, PromptPipelineErrorV1>>()?;\n"
    "    let canonical = canonical_context_bundle_bytes_v2(&ordered_realizations)\n"
    "        .map_err(|error| PromptPipelineErrorV1::ContextCompiler(format!(\"{error:?}\")))?;\n"
    "    if canonical != serialized_payload {\n"
    "        return Err(PromptPipelineErrorV1::SerializationProofDrift);\n"
    "    }\n\n"
    "    let mut cursor = 0_usize;\n"
    "    let mut occurrences = Vec::with_capacity(materialization.payloads.len());\n"
    "    for item_id in compiled.receipt().selected_item_ids() {",
)
replace_once(
    "codex-rs/hepta-intelligence/src/prompt_pipeline.rs",
    "        let Some(relative_start) = find_subslice(&serialized_payload[cursor..], &payload.payload)\n"
    "        else {\n"
    "            return Err(PromptPipelineErrorV1::SerializedPayloadMissing(\n"
    "                item_id.to_string(),\n"
    "            ));\n"
    "        };\n"
    "        let start = cursor\n"
    "            .checked_add(relative_start)\n"
    "            .ok_or(PromptPipelineErrorV1::Arithmetic)?;\n"
    "        let end = start\n"
    "            .checked_add(payload.payload.len())\n"
    "            .ok_or(PromptPipelineErrorV1::Arithmetic)?;",
    "        let text = std::str::from_utf8(&payload.payload)\n"
    "            .map_err(|_| PromptPipelineErrorV1::SerializationProofDrift)?;\n"
    "        let encoded = serde_json::to_string(text)\n"
    "            .map_err(|_| PromptPipelineErrorV1::SerializationProofDrift)?;\n"
    "        let encoded = encoded\n"
    "            .as_bytes()\n"
    "            .get(1..encoded.len().saturating_sub(1))\n"
    "            .ok_or(PromptPipelineErrorV1::SerializationProofDrift)?;\n"
    "        let Some(relative_start) = find_subslice(&serialized_payload[cursor..], encoded) else {\n"
    "            return Err(PromptPipelineErrorV1::SerializedPayloadMissing(\n"
    "                item_id.to_string(),\n"
    "            ));\n"
    "        };\n"
    "        let start = cursor\n"
    "            .checked_add(relative_start)\n"
    "            .ok_or(PromptPipelineErrorV1::Arithmetic)?;\n"
    "        let end = start\n"
    "            .checked_add(encoded.len())\n"
    "            .ok_or(PromptPipelineErrorV1::Arithmetic)?;",
)

# Retain the exact model tuple used to read the original durable registry and
# expose a typed send preparation that re-reads the same durable owner.
replace_once(
    "codex-rs/hepta-intelligence/src/prompt_delivery.rs",
    "use codex_hepta_context_compiler::ContextAttachmentV2;\n",
    "use codex_hepta_context_compiler::ContextAdmissionRecordV2;\n"
    "use codex_hepta_context_compiler::ContextAdmissionSnapshotV2;\n"
    "use codex_hepta_context_compiler::ContextAdmissionVerifierV2;\n"
    "use codex_hepta_context_compiler::ContextAttachmentV2;\n",
)
replace_once(
    "codex-rs/hepta-intelligence/src/prompt_delivery.rs",
    "use codex_hepta_context_compiler::ContextModelProfileV2;\n",
    "use codex_hepta_context_compiler::ContextDeliveryPreparationV2;\n"
    "use codex_hepta_context_compiler::ContextModelProfileV2;\n",
)
replace_once(
    "codex-rs/hepta-intelligence/src/prompt_delivery.rs",
    "use codex_hepta_context_compiler::VerifiedAdmissionSnapshotV2;\n",
    "use codex_hepta_context_compiler::VerifiedAdmissionSnapshotSuccessorV2;\n"
    "use codex_hepta_context_compiler::VerifiedAdmissionSnapshotV2;\n",
)
replace_once(
    "codex-rs/hepta-intelligence/src/prompt_delivery.rs",
    "use codex_hepta_context_compiler::canonical_context_bundle_bytes_v2;\n",
    "use codex_hepta_context_compiler::canonical_context_bundle_bytes_v2;\n"
    "use codex_hepta_context_compiler::prepare_delivery_from_successor_v2;\n"
    "use codex_hepta_context_compiler::verify_admission_snapshot_successor_typed_v2;\n",
)
replace_once(
    "codex-rs/hepta-intelligence/src/prompt_delivery.rs",
    "    pub model_profile: ContextModelProfileV2,\n"
    "    pub admission_snapshot: VerifiedAdmissionSnapshotV2,",
    "    pub model_profile: ContextModelProfileV2,\n"
    "    pub registry_model_tuple: PromptModelTupleV2,\n"
    "    pub admission_snapshot: VerifiedAdmissionSnapshotV2,",
)
replace_once(
    "codex-rs/hepta-intelligence/src/prompt_delivery.rs",
    "            || self.admission_snapshot.snapshot_digest()\n"
    "                != self.attachment.admission_snapshot_digest()\n"
    "            || self.delivery_set_digest.is_zero()",
    "            || self.registry_model_tuple.digest() != self.compatible.model_tuple_digest\n"
    "            || self.registry_model_tuple.model_digest != self.model_profile.model_digest\n"
    "            || self.registry_model_tuple.tokenizer_digest != self.model_profile.tokenizer_digest\n"
    "            || self.registry_model_tuple.template_digest != self.model_profile.template_digest\n"
    "            || self.registry_model_tuple.tool_schema_digest\n"
    "                != self.model_profile.tool_schema_digest\n"
    "            || self.admission_snapshot.snapshot_digest()\n"
    "                != self.attachment.admission_snapshot_digest()\n"
    "            || self.delivery_set_digest.is_zero()",
)
replace_once(
    "codex-rs/hepta-intelligence/src/prompt_delivery.rs",
    "        admission_snapshot: prepared.admission_snapshot.clone(),\n"
    "        compiled: prepared.compiled,\n"
    "        model_profile,",
    "        admission_snapshot: prepared.admission_snapshot.clone(),\n"
    "        compiled: prepared.compiled,\n"
    "        model_profile,\n"
    "        registry_model_tuple: request.registry_model_tuple.clone(),",
)

fresh_preparation = r'''
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRegistryDeliveryPreparationV2 {
    pub registry_snapshot_digest: Digest32,
    pub final_use_materialization_digest: Digest32,
    pub successor: VerifiedAdmissionSnapshotSuccessorV2,
    pub preparation: ContextDeliveryPreparationV2,
    pub authority: AuthorityPosture,
}

impl PromptRegistryDeliveryPreparationV2 {
    pub fn validate_for(
        &self,
        compiled: &PromptRegistryCompiledContextV2,
    ) -> Result<(), PromptRegistryCompilationErrorV2> {
        if self.registry_snapshot_digest.is_zero()
            || self.final_use_materialization_digest.is_zero()
            || self.final_use_materialization_digest
                != prompt_payload_bundle_digest(&compiled.selected_deliveries)
            || self.successor.predecessor_snapshot_digest()
                != compiled.admission_snapshot.snapshot_digest()
            || self.preparation.admission_snapshot_digest()
                != self.successor.successor_snapshot_digest()
            || self.authority.grants_any()
        {
            return Err(PromptRegistryCompilationErrorV2::Integrity);
        }
        self.preparation
            .validate_for(
                &compiled.attachment,
                &compiled.serialized_context,
                &compiled.model_profile,
            )
            .map_err(PromptRegistryCompilationErrorV2::Context)
    }
}

#[derive(Clone, Debug)]
struct DeliverySnapshotVerifierV2 {
    verifier_digest: Digest32,
    scope_digest: Digest32,
    authority_domain_digest: Digest32,
}

impl ContextAdmissionVerifierV2 for DeliverySnapshotVerifierV2 {
    fn verifier_digest(&self) -> Digest32 {
        self.verifier_digest
    }

    fn verify_record(&self, record: &ContextAdmissionRecordV2) -> bool {
        record.scope_digest == self.scope_digest
            && record.authority_domain_digest == self.authority_domain_digest
            && !record.contains_secret
            && record.validate_shape().is_ok()
    }

    fn verify_snapshot(&self, snapshot: &ContextAdmissionSnapshotV2) -> bool {
        snapshot.scope_digest == self.scope_digest
            && snapshot.authority_domain_digest == self.authority_domain_digest
            && snapshot.revocation_set_complete
            && snapshot.validate_shape().is_ok()
    }
}

/// Re-read the exact durable registry immediately before a provider send. Every
/// selected realization must still dereference to the same binding and payload;
/// expiry, retirement, revocation, replacement, or byte drift fails closed.
pub fn prepare_prompt_registry_delivery_v2(
    registry: &DurablePromptRegistry,
    compiled: &PromptRegistryCompiledContextV2,
    now_unix_ms: u64,
    snapshot_id: StableId,
    preparation_id: StableId,
) -> Result<PromptRegistryDeliveryPreparationV2, PromptRegistryCompilationErrorV2> {
    compiled.validate()?;
    if now_unix_ms == 0 {
        return Err(PromptRegistryCompilationErrorV2::Integrity);
    }
    let generation_vector_digest = compiled.compiled.receipt().generation_vector_digest();
    let registry_snapshot = registry
        .snapshot_v2(generation_vector_digest, &compiled.registry_model_tuple)
        .map_err(PromptRegistryCompilationErrorV2::Registry)?;
    let mut fresh_deliveries = Vec::with_capacity(compiled.selected_deliveries.len());
    for expected in &compiled.selected_deliveries {
        let actual = registry
            .dereference_realization_v2(
                &expected.binding.realization_id,
                &registry_snapshot,
                generation_vector_digest,
                &compiled.registry_model_tuple,
                now_unix_ms,
            )
            .map_err(PromptRegistryCompilationErrorV2::Registry)?;
        if &actual != expected {
            return Err(PromptRegistryCompilationErrorV2::FinalUseDrift);
        }
        fresh_deliveries.push(actual);
    }
    let final_use_materialization_digest = prompt_payload_bundle_digest(&fresh_deliveries);
    if final_use_materialization_digest
        != prompt_payload_bundle_digest(&compiled.selected_deliveries)
    {
        return Err(PromptRegistryCompilationErrorV2::FinalUseDrift);
    }

    let verifier = DeliverySnapshotVerifierV2 {
        verifier_digest: compiled.admission_snapshot.verifier_digest(),
        scope_digest: compiled.admission_snapshot.scope_digest(),
        authority_domain_digest: compiled.admission_snapshot.authority_domain_digest(),
    };
    let observed_unix_ms = now_unix_ms.max(compiled.admission_snapshot.observed_unix_ms());
    let revocation_epoch = compiled
        .admission_snapshot
        .revocation_epoch()
        .checked_add(1)
        .ok_or(PromptRegistryCompilationErrorV2::Integrity)?;
    let raw_successor = ContextAdmissionSnapshotV2::new(
        snapshot_id,
        compiled.admission_snapshot.scope_digest(),
        compiled.admission_snapshot.authority_domain_digest(),
        observed_unix_ms,
        revocation_epoch,
        Vec::new(),
        true,
        Some(compiled.admission_snapshot.snapshot_digest()),
    )
    .map_err(PromptRegistryCompilationErrorV2::Context)?;
    let successor = verify_admission_snapshot_successor_typed_v2(
        raw_successor,
        &compiled.admission_snapshot,
        &verifier,
    )
    .map_err(|error| PromptRegistryCompilationErrorV2::Closure(error.to_string()))?;
    let preparation = prepare_delivery_from_successor_v2(
        &compiled.compiled,
        &compiled.serialized_context,
        &compiled.attachment,
        &compiled.model_profile,
        &successor,
        preparation_id,
    )
    .map_err(|error| PromptRegistryCompilationErrorV2::Closure(error.to_string()))?;
    let output = PromptRegistryDeliveryPreparationV2 {
        registry_snapshot_digest: registry_snapshot.snapshot_digest,
        final_use_materialization_digest,
        successor,
        preparation,
        authority: AuthorityPosture::DENY_ALL,
    };
    output.validate_for(compiled)?;
    Ok(output)
}

'''
replace_once(
    "codex-rs/hepta-intelligence/src/prompt_delivery.rs",
    "#[derive(Debug)]\npub enum PromptRegistryCompilationErrorV2 {",
    fresh_preparation + "#[derive(Debug)]\npub enum PromptRegistryCompilationErrorV2 {",
)
replace_once(
    "codex-rs/hepta-intelligence/src/prompt_delivery.rs",
    "    Context(ContextCompilerV2Error),\n"
    "    ProfileMismatch,\n"
    "    Integrity,",
    "    Context(ContextCompilerV2Error),\n"
    "    Closure(String),\n"
    "    ProfileMismatch,\n"
    "    FinalUseDrift,\n"
    "    Integrity,",
)
