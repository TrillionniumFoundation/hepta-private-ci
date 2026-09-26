#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:100]!r}")
    file_path.write_text(text.replace(old, new, 1))


# The product serializer is compiler-owned. Its UTF-8 JSON envelope is the one
# context fragment injected into the provider request; callers cannot supply
# arbitrary bytes and ask the compiler to bless them.
replace_once(
    "codex-rs/hepta-context-compiler/src/provider_closure.rs",
    "use std::fmt;\n",
    "use std::fmt;\n\nuse serde::Serialize;\n",
)
replace_once(
    "codex-rs/hepta-context-compiler/src/provider_closure.rs",
    "use crate::ContextDeliveryPreparationV2;\n"
    "use crate::ContextModelProfileV2;\n"
    "use crate::SerializedContextV2;",
    "use crate::ContextDeliveryPreparationV2;\n"
    "use crate::ContextModelProfileV2;\n"
    "use crate::ContextRealizedItemV2;\n"
    "use crate::ContextRoleV2;\n"
    "use crate::ContextSerializerV2;\n"
    "use crate::ExactTokenizerV2;\n"
    "use crate::SerializedContextV2;",
)
replace_once(
    "codex-rs/hepta-context-compiler/src/provider_closure.rs",
    "use crate::prepare_delivery_v2;\n",
    "use crate::prepare_delivery_v2;\nuse crate::record_serialization;\n",
)
replace_once(
    "codex-rs/hepta-context-compiler/src/provider_closure.rs",
    "const FINAL_REQUEST_PROOF_DOMAIN: &[u8] = b\"hepta.context-final-provider-request-proof.v2\";\n",
    "const FINAL_REQUEST_PROOF_DOMAIN: &[u8] = b\"hepta.context-final-provider-request-proof.v2\";\n"
    "const CANONICAL_CONTEXT_BUNDLE_SCHEMA_V2: &str = \"hepta.context-bundle.v2\";\n",
)

canonical_bundle = r'''
#[derive(Serialize)]
struct CanonicalContextBundleEnvelopeV2<'a> {
    schema: &'static str,
    items: Vec<CanonicalContextBundleItemV2<'a>>,
}

#[derive(Serialize)]
struct CanonicalContextBundleItemV2<'a> {
    item_id: &'a str,
    role: &'static str,
    content_sha256: String,
    content: &'a str,
}

#[derive(Clone, Debug)]
struct CanonicalContextBundleSerializerV2 {
    serializer_digest: Digest32,
    template_digest: Digest32,
    tool_schema_digest: Digest32,
}

impl CanonicalContextBundleSerializerV2 {
    fn for_profile(profile: &ContextModelProfileV2) -> Self {
        Self {
            serializer_digest: profile.serializer_digest,
            template_digest: profile.template_digest,
            tool_schema_digest: profile.tool_schema_digest,
        }
    }
}

impl ContextSerializerV2 for CanonicalContextBundleSerializerV2 {
    fn serializer_digest(&self) -> Digest32 {
        self.serializer_digest
    }

    fn template_digest(&self) -> Digest32 {
        self.template_digest
    }

    fn tool_schema_digest(&self) -> Digest32 {
        self.tool_schema_digest
    }

    fn serialize(
        &self,
        items: &[ContextRealizedItemV2],
    ) -> Result<Vec<u8>, ContextCompilerV2Error> {
        canonical_context_bundle_bytes_core(items)
    }
}

/// Render the only product-authorized context bundle. Serde struct field order,
/// compiler-selected item order, explicit role labels, content digests, and
/// UTF-8 rejection make this byte sequence deterministic and reviewable.
pub fn canonical_context_bundle_bytes_v2(
    items: &[ContextRealizedItemV2],
) -> Result<Vec<u8>, ProviderClosureErrorV2> {
    Ok(canonical_context_bundle_bytes_core(items)?)
}

/// Record a serialization receipt using the compiler-owned canonical serializer.
/// Product callsites use this instead of supplying a `ContextSerializerV2`.
pub fn record_canonical_context_bundle_v2(
    compiled: &crate::CompiledContextV2,
    profile: &ContextModelProfileV2,
    serialization_id: StableId,
    realizations: Vec<ContextRealizedItemV2>,
    tokenizer: &impl ExactTokenizerV2,
) -> Result<SerializedContextV2, ProviderClosureErrorV2> {
    let serializer = CanonicalContextBundleSerializerV2::for_profile(profile);
    Ok(record_serialization(
        compiled,
        profile,
        serialization_id,
        realizations,
        &serializer,
        tokenizer,
    )?)
}

fn canonical_context_bundle_bytes_core(
    items: &[ContextRealizedItemV2],
) -> Result<Vec<u8>, ContextCompilerV2Error> {
    let mut encoded_items = Vec::with_capacity(items.len());
    for item in items {
        let content = std::str::from_utf8(&item.content)
            .map_err(|_| ContextCompilerV2Error::SerializationMismatch)?;
        let role = match item.role {
            ContextRoleV2::TrustedInstruction => "trusted_instruction",
            ContextRoleV2::Schema => "schema",
            ContextRoleV2::UntrustedEvidence => "untrusted_evidence",
        };
        encoded_items.push(CanonicalContextBundleItemV2 {
            item_id: item.item_id.as_str(),
            role,
            content_sha256: Digest32::of_bytes(&item.content).to_string(),
            content,
        });
    }
    serde_json::to_vec(&CanonicalContextBundleEnvelopeV2 {
        schema: CANONICAL_CONTEXT_BUNDLE_SCHEMA_V2,
        items: encoded_items,
    })
    .map_err(|_| ContextCompilerV2Error::SerializationMismatch)
}

'''
replace_once(
    "codex-rs/hepta-context-compiler/src/provider_closure.rs",
    "/// Identity of the exact tokenizer executable and vocabulary used on the\n",
    canonical_bundle + "/// Identity of the exact tokenizer executable and vocabulary used on the\n",
)

# Export the construction-closed serializer entrypoints.
replace_once(
    "codex-rs/hepta-context-compiler/src/lib.rs",
    "pub use provider_closure::prepare_delivery_from_successor_v2;\n",
    "pub use provider_closure::canonical_context_bundle_bytes_v2;\n"
    "pub use provider_closure::prepare_delivery_from_successor_v2;\n"
    "pub use provider_closure::record_canonical_context_bundle_v2;\n",
)

# Remove the caller-controlled product serializer and force preparation through
# the compiler-owned canonical bundle.
replace_once(
    "codex-rs/hepta-intelligence/src/prompt_pipeline.rs",
    "use codex_hepta_context_compiler::ContextSerializationReceiptV2;\n"
    "use codex_hepta_context_compiler::ContextSerializerV2;\n"
    "use codex_hepta_context_compiler::ExactTokenizerV2;",
    "use codex_hepta_context_compiler::ContextSerializationReceiptV2;\n"
    "use codex_hepta_context_compiler::ExactTokenizerV2;",
)
replace_once(
    "codex-rs/hepta-intelligence/src/prompt_pipeline.rs",
    "use codex_hepta_context_compiler::record_serialization;\n",
    "use codex_hepta_context_compiler::record_canonical_context_bundle_v2;\n",
)
exact_prepared_serializer = r'''#[derive(Clone, Debug)]
struct ExactPreparedSerializer {
    serializer_digest: Digest32,
    template_digest: Digest32,
    tool_schema_digest: Digest32,
    payload: Vec<u8>,
}

impl ContextSerializerV2 for ExactPreparedSerializer {
    fn serializer_digest(&self) -> Digest32 {
        self.serializer_digest
    }
    fn template_digest(&self) -> Digest32 {
        self.template_digest
    }
    fn tool_schema_digest(&self) -> Digest32 {
        self.tool_schema_digest
    }
    fn serialize(
        &self,
        _items: &[ContextRealizedItemV2],
    ) -> Result<Vec<u8>, ContextCompilerV2Error> {
        Ok(self.payload.clone())
    }
}

'''
replace_once(
    "codex-rs/hepta-intelligence/src/prompt_pipeline.rs",
    exact_prepared_serializer,
    "",
)
old_serialization = r'''    let serializer = ExactPreparedSerializer {
        serializer_digest: prepared.model_profile.serializer_digest,
        template_digest: prepared.model_profile.template_digest,
        tool_schema_digest: prepared.model_profile.tool_schema_digest,
        payload: serialized_payload.clone(),
    };
    let serialized_context = record_serialization(
        &prepared.compiled,
        &prepared.model_profile,
        serialization_id,
        realizations,
        &serializer,
        &tokenizer,
    )
    .map_err(|error| PromptPipelineErrorV1::ContextCompiler(format!("{error:?}")))?;
'''
new_serialization = r'''    let serialized_context = record_canonical_context_bundle_v2(
        &prepared.compiled,
        &prepared.model_profile,
        serialization_id,
        realizations,
        &tokenizer,
    )
    .map_err(|error| PromptPipelineErrorV1::ContextCompiler(format!("{error:?}")))?;
    if serialized_context.payload() != serialized_payload.as_slice() {
        return Err(PromptPipelineErrorV1::SerializationProofDrift);
    }
'''
replace_once(
    "codex-rs/hepta-intelligence/src/prompt_pipeline.rs",
    old_serialization,
    new_serialization,
)

# Generate the serialized payload through the same compiler-owned function and
# retain the verified admission predecessor needed by typed send revalidation.
replace_once(
    "codex-rs/hepta-intelligence/src/prompt_delivery.rs",
    "use codex_hepta_context_compiler::ContextModelProfileV2;\n"
    "use codex_hepta_context_compiler::ContextSerializationReceiptV2;",
    "use codex_hepta_context_compiler::ContextModelProfileV2;\n"
    "use codex_hepta_context_compiler::ContextRealizedItemV2;\n"
    "use codex_hepta_context_compiler::ContextRoleV2;\n"
    "use codex_hepta_context_compiler::ContextSerializationReceiptV2;",
)
replace_once(
    "codex-rs/hepta-intelligence/src/prompt_delivery.rs",
    "use codex_hepta_context_compiler::SerializedContextV2;\n",
    "use codex_hepta_context_compiler::SerializedContextV2;\n"
    "use codex_hepta_context_compiler::VerifiedAdmissionSnapshotV2;\n"
    "use codex_hepta_context_compiler::canonical_context_bundle_bytes_v2;\n",
)
replace_once(
    "codex-rs/hepta-intelligence/src/prompt_delivery.rs",
    "const SERIALIZED_PAYLOAD_DOMAIN: &[u8] = b\"hepta.prompt-registry.serialized-context.v3\";\n",
    "",
)
replace_once(
    "codex-rs/hepta-intelligence/src/prompt_delivery.rs",
    "    pub compiled: CompiledContextV2,\n"
    "    pub model_profile: ContextModelProfileV2,",
    "    pub compiled: CompiledContextV2,\n"
    "    pub model_profile: ContextModelProfileV2,\n"
    "    pub admission_snapshot: VerifiedAdmissionSnapshotV2,",
)
replace_once(
    "codex-rs/hepta-intelligence/src/prompt_delivery.rs",
    "        if self.authority.grants_any()\n"
    "            || self.delivery_set_digest.is_zero()",
    "        if self.authority.grants_any()\n"
    "            || self.admission_snapshot.snapshot_digest()\n"
    "                != self.attachment.admission_snapshot_digest()\n"
    "            || self.delivery_set_digest.is_zero()",
)
replace_once(
    "codex-rs/hepta-intelligence/src/prompt_delivery.rs",
    "    let serialized_payload = serialize_selected_deliveries(&selected_deliveries);\n",
    "    let serialized_payload = serialize_selected_deliveries(&selected_deliveries)?;\n",
)
replace_once(
    "codex-rs/hepta-intelligence/src/prompt_delivery.rs",
    "        compiled: prepared.compiled,\n"
    "        model_profile,",
    "        admission_snapshot: prepared.admission_snapshot.clone(),\n"
    "        compiled: prepared.compiled,\n"
    "        model_profile,",
)
old_delivery_serializer = r'''fn serialize_selected_deliveries(deliveries: &[RealizationDeliveryV2]) -> Vec<u8> {
    let mut bytes = SERIALIZED_PAYLOAD_DOMAIN.to_vec();
    bytes.extend_from_slice(
        &u64::try_from(deliveries.len())
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    );
    for delivery in deliveries {
        let realization_id = delivery.binding.realization_id.as_str().as_bytes();
        bytes.extend_from_slice(
            &u64::try_from(realization_id.len())
                .unwrap_or(u64::MAX)
                .to_be_bytes(),
        );
        bytes.extend_from_slice(realization_id);
        bytes.push(prompt_role_code(delivery.binding.role));
        bytes.extend_from_slice(delivery.binding.digest().as_array());
        bytes.extend_from_slice(
            &u64::try_from(delivery.payload.len())
                .unwrap_or(u64::MAX)
                .to_be_bytes(),
        );
        bytes.extend_from_slice(&delivery.payload);
    }
    bytes
}

const fn prompt_role_code(role: PromptRoleV2) -> u8 {
    match role {
        PromptRoleV2::SystemInstruction => 0,
        PromptRoleV2::DeveloperInstruction => 1,
        PromptRoleV2::UserTemplate => 2,
        PromptRoleV2::ToolSchemaFragment => 3,
    }
}
'''
new_delivery_serializer = r'''fn serialize_selected_deliveries(
    deliveries: &[RealizationDeliveryV2],
) -> Result<Vec<u8>, PromptRegistryCompilationErrorV2> {
    let realizations = deliveries
        .iter()
        .map(|delivery| ContextRealizedItemV2 {
            item_id: delivery.binding.realization_id.clone(),
            role: match delivery.binding.role {
                PromptRoleV2::ToolSchemaFragment => ContextRoleV2::Schema,
                PromptRoleV2::SystemInstruction
                | PromptRoleV2::DeveloperInstruction
                | PromptRoleV2::UserTemplate => ContextRoleV2::TrustedInstruction,
            },
            content: delivery.payload.clone(),
        })
        .collect::<Vec<_>>();
    canonical_context_bundle_bytes_v2(&realizations)
        .map_err(|_| PromptRegistryCompilationErrorV2::Integrity)
}
'''
replace_once(
    "codex-rs/hepta-intelligence/src/prompt_delivery.rs",
    old_delivery_serializer,
    new_delivery_serializer,
)

# Agentd injects the exact compiler-owned bundle as one fragment. It still walks
# selected deliveries for role and expiry validation, but never rebuilds prompt
# bytes from them.
old_agentd_fragments = r'''        let mut effective_deadline_ms = requested_deadline_ms;
        let mut fragments = Vec::with_capacity(compiled.selected_deliveries.len());
        for delivery in &compiled.selected_deliveries {
            if delivery.binding.role != PromptRoleV2::DeveloperInstruction {
                return Err(AgentdPromptRuntimeError::UnsupportedPromptRole);
            }
            if let Some(expires_unix_ms) = delivery.binding.expires_unix_ms {
                if expires_unix_ms == 0 {
                    return Err(AgentdPromptRuntimeError::InvalidDeadline);
                }
                effective_deadline_ms = effective_deadline_ms.min(expires_unix_ms);
            }
            let text = std::str::from_utf8(&delivery.payload)
                .map_err(|_| AgentdPromptRuntimeError::PayloadNotUtf8)?;
            fragments.push(
                PromptRuntimeDeveloperFragmentV1::new(text.to_owned())
                    .map_err(|error| AgentdPromptRuntimeError::Adapter(error.to_string()))?,
            );
        }
'''
new_agentd_fragments = r'''        let mut effective_deadline_ms = requested_deadline_ms;
        for delivery in &compiled.selected_deliveries {
            if delivery.binding.role != PromptRoleV2::DeveloperInstruction {
                return Err(AgentdPromptRuntimeError::UnsupportedPromptRole);
            }
            if let Some(expires_unix_ms) = delivery.binding.expires_unix_ms {
                if expires_unix_ms == 0 {
                    return Err(AgentdPromptRuntimeError::InvalidDeadline);
                }
                effective_deadline_ms = effective_deadline_ms.min(expires_unix_ms);
            }
        }
        let canonical_bundle = std::str::from_utf8(&compiled.serialized_payload)
            .map_err(|_| AgentdPromptRuntimeError::PayloadNotUtf8)?;
        let fragments = vec![
            PromptRuntimeDeveloperFragmentV1::new(canonical_bundle.to_owned())
                .map_err(|error| AgentdPromptRuntimeError::Adapter(error.to_string()))?,
        ];
'''
replace_once(
    "codex-rs/hepta-agentd/src/prompt_runtime.rs",
    old_agentd_fragments,
    new_agentd_fragments,
)

# One canonical bundle may legitimately approach the compiler's 16 MiB bound.
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "const MAX_DEVELOPER_FRAGMENT_BYTES: usize = 64 * 1024;\n"
    "const MAX_DEVELOPER_TOTAL_BYTES: usize = 1024 * 1024;",
    "const MAX_DEVELOPER_FRAGMENT_BYTES: usize = 16 * 1024 * 1024;\n"
    "const MAX_DEVELOPER_TOTAL_BYTES: usize = 16 * 1024 * 1024;",
)
