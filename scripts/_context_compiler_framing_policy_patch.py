#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:120]!r}")
    file_path.write_text(text.replace(old, new, 1))


# Make provider framing an explicit qualified capability rather than labelling
# every non-context prefix/suffix as trusted framing by construction.
replace_once(
    "codex-rs/hepta-context-compiler/src/provider_closure.rs",
    "    ContextPayloadAmbiguous,\n    SegmentCoverageInvalid,",
    "    ContextPayloadAmbiguous,\n"
    "    FramingVerifierRejected(String),\n"
    "    SegmentCoverageInvalid,",
)

framing_trait = r'''
/// Qualified verifier for provider-specific framing around the canonical
/// context bundle. The compiler proves complete byte coverage; this capability
/// proves that the non-context bytes belong to an allowed provider request
/// grammar for the exact provider/model pair.
pub trait FinalRequestFramingVerifierV2: Send + Sync {
    fn verifier_digest(&self) -> Digest32;

    fn verify_final_request(
        &self,
        canonical_request: &[u8],
        canonical_context_payload: &[u8],
    ) -> Result<(), String>;
}

'''
replace_once(
    "codex-rs/hepta-context-compiler/src/provider_closure.rs",
    "pub trait ExactFinalRequestTokenizerV2: Send + Sync {\n"
    "    fn identity(&self) -> &FinalRequestTokenizerIdentityV2;\n\n"
    "    /// Count the model-input tokens represented by this exact canonical\n"
    "    /// provider request. Implementations must parse provider semantics rather\n"
    "    /// than use byte/character estimates.\n"
    "    fn count_final_request_tokens(&self, canonical_request: &[u8]) -> Result<u64, String>;\n"
    "}\n\n",
    "pub trait ExactFinalRequestTokenizerV2: Send + Sync {\n"
    "    fn identity(&self) -> &FinalRequestTokenizerIdentityV2;\n\n"
    "    /// Count the model-input tokens represented by this exact canonical\n"
    "    /// provider request. Implementations must parse provider semantics rather\n"
    "    /// than use byte/character estimates.\n"
    "    fn count_final_request_tokens(&self, canonical_request: &[u8]) -> Result<u64, String>;\n"
    "}\n\n"
    + framing_trait,
)
replace_once(
    "codex-rs/hepta-context-compiler/src/provider_closure.rs",
    "    provider_wire_semantic_digest: Digest32,\n    request_bytes: u64,",
    "    provider_wire_semantic_digest: Digest32,\n"
    "    framing_verifier_digest: Digest32,\n"
    "    request_bytes: u64,",
)
replace_once(
    "codex-rs/hepta-context-compiler/src/provider_closure.rs",
    "    pub const fn provider_wire_semantic_digest(&self) -> Digest32 {\n"
    "        self.provider_wire_semantic_digest\n"
    "    }\n\n"
    "    #[must_use]\n"
    "    pub const fn request_bytes(&self) -> u64 {",
    "    pub const fn provider_wire_semantic_digest(&self) -> Digest32 {\n"
    "        self.provider_wire_semantic_digest\n"
    "    }\n\n"
    "    #[must_use]\n"
    "    pub const fn framing_verifier_digest(&self) -> Digest32 {\n"
    "        self.framing_verifier_digest\n"
    "    }\n\n"
    "    #[must_use]\n"
    "    pub const fn request_bytes(&self) -> u64 {",
)
replace_once(
    "codex-rs/hepta-context-compiler/src/provider_closure.rs",
    "            || self.provider_request_digest.is_zero()\n"
    "            || self.provider_wire_semantic_digest.is_zero()\n"
    "            || self.request_bytes == 0",
    "            || self.provider_request_digest.is_zero()\n"
    "            || self.provider_wire_semantic_digest.is_zero()\n"
    "            || self.framing_verifier_digest.is_zero()\n"
    "            || self.request_bytes == 0",
)
replace_once(
    "codex-rs/hepta-context-compiler/src/provider_closure.rs",
    "            self.provider_wire_semantic_digest,\n"
    "            self.segment_map_digest,",
    "            self.provider_wire_semantic_digest,\n"
    "            self.framing_verifier_digest,\n"
    "            self.segment_map_digest,",
)
replace_once(
    "codex-rs/hepta-context-compiler/src/provider_closure.rs",
    "    provider_wire_semantic_digest: Digest32,\n"
    "    canonical_request: &[u8],\n"
    "    tokenizer: &impl ExactFinalRequestTokenizerV2,",
    "    provider_wire_semantic_digest: Digest32,\n"
    "    canonical_request: &[u8],\n"
    "    framing_verifier: &impl FinalRequestFramingVerifierV2,\n"
    "    tokenizer: &impl ExactFinalRequestTokenizerV2,",
)
replace_once(
    "codex-rs/hepta-context-compiler/src/provider_closure.rs",
    "    tokenizer.identity().validate_for(profile)?;\n\n"
    "    let payload_text = std::str::from_utf8(serialization.payload())",
    "    tokenizer.identity().validate_for(profile)?;\n"
    "    let framing_verifier_digest = framing_verifier.verifier_digest();\n"
    "    if framing_verifier_digest.is_zero() {\n"
    "        return Err(ProviderClosureErrorV2::EmptyDigest(\n"
    "            \"provider_framing_verifier\",\n"
    "        ));\n"
    "    }\n\n"
    "    let payload_text = std::str::from_utf8(serialization.payload())",
)
replace_once(
    "codex-rs/hepta-context-compiler/src/provider_closure.rs",
    "    let segments = build_segment_map(\n"
    "        canonical_request,\n"
    "        encoded_payload,\n"
    "        preparation.payload_digest(),\n"
    "    )?;\n\n"
    "    let provider_request_digest = Digest32::of_bytes(canonical_request);",
    "    let segments = build_segment_map(\n"
    "        canonical_request,\n"
    "        encoded_payload,\n"
    "        preparation.payload_digest(),\n"
    "    )?;\n"
    "    framing_verifier\n"
    "        .verify_final_request(canonical_request, serialization.payload())\n"
    "        .map_err(ProviderClosureErrorV2::FramingVerifierRejected)?;\n\n"
    "    let provider_request_digest = Digest32::of_bytes(canonical_request);",
)
replace_once(
    "codex-rs/hepta-context-compiler/src/provider_closure.rs",
    "        provider_wire_semantic_digest,\n"
    "        request_bytes: u64::try_from(canonical_request.len())",
    "        provider_wire_semantic_digest,\n"
    "        framing_verifier_digest,\n"
    "        request_bytes: u64::try_from(canonical_request.len())",
)
replace_once(
    "codex-rs/hepta-context-compiler/src/lib.rs",
    "pub use provider_closure::FinalProviderRequestProofV2;\n",
    "pub use provider_closure::FinalProviderRequestProofV2;\n"
    "pub use provider_closure::FinalRequestFramingVerifierV2;\n",
)

# The product implementation validates the concrete Responses JSON grammar,
# exact model identity and one-and-only-one decoded context occurrence.
replace_once(
    "codex-rs/hepta-agentd/src/exact_context_delivery.rs",
    "use codex_hepta_context_compiler::FinalProviderRequestProofV2;\n",
    "use codex_hepta_context_compiler::FinalProviderRequestProofV2;\n"
    "use codex_hepta_context_compiler::FinalRequestFramingVerifierV2;\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/exact_context_delivery.rs",
    "        let final_request_proof = prove_final_provider_request_v2(\n"
    "            &fresh.preparation,",
    "        let framing_policy = ResponsesJsonFramingPolicy::new(\n"
    "            &request.attempt.provider_id,\n"
    "            &request.attempt.model,\n"
    "            request.attempt.provider_config_digest,\n"
    "            request.attempt.endpoint_digest,\n"
    "        )?;\n"
    "        let final_request_proof = prove_final_provider_request_v2(\n"
    "            &fresh.preparation,",
)
replace_once(
    "codex-rs/hepta-agentd/src/exact_context_delivery.rs",
    "            request.attempt.provider_wire_semantic_digest,\n"
    "            &request.canonical_request,\n"
    "            &bound_tokenizer,",
    "            request.attempt.provider_wire_semantic_digest,\n"
    "            &request.canonical_request,\n"
    "            &framing_policy,\n"
    "            &bound_tokenizer,",
)

policy_impl = r'''
#[derive(Clone, Debug)]
struct ResponsesJsonFramingPolicy {
    expected_model: String,
    verifier_digest: Digest32,
}

impl ResponsesJsonFramingPolicy {
    fn new(
        provider_id: &str,
        model: &str,
        provider_config_digest: Digest32,
        endpoint_digest: Digest32,
    ) -> Result<Self, ExactContextDeliveryError> {
        if provider_id.is_empty()
            || model.is_empty()
            || provider_config_digest.is_zero()
            || endpoint_digest.is_zero()
        {
            return Err(ExactContextDeliveryError::InvalidIdentity);
        }
        let mut bytes = b"hepta.responses-json-framing-verifier.v2".to_vec();
        push_framing_text(&mut bytes, provider_id);
        push_framing_text(&mut bytes, model);
        bytes.extend_from_slice(provider_config_digest.as_array());
        bytes.extend_from_slice(endpoint_digest.as_array());
        Ok(Self {
            expected_model: model.to_owned(),
            verifier_digest: Digest32::of_bytes(&bytes),
        })
    }
}

impl FinalRequestFramingVerifierV2 for ResponsesJsonFramingPolicy {
    fn verifier_digest(&self) -> Digest32 {
        self.verifier_digest
    }

    fn verify_final_request(
        &self,
        canonical_request: &[u8],
        canonical_context_payload: &[u8],
    ) -> Result<(), String> {
        let context = std::str::from_utf8(canonical_context_payload)
            .map_err(|_| "canonical context payload is not UTF-8".to_owned())?;
        if context.is_empty() {
            return Err("canonical context payload is empty".to_owned());
        }
        let value: serde_json::Value = serde_json::from_slice(canonical_request)
            .map_err(|error| format!("provider request is not valid JSON: {error}"))?;
        let object = value
            .as_object()
            .ok_or_else(|| "provider request root is not an object".to_owned())?;
        if object.get("model").and_then(serde_json::Value::as_str)
            != Some(self.expected_model.as_str())
        {
            return Err("provider request model does not match the bound model".to_owned());
        }
        if !object.contains_key("input") && !object.contains_key("instructions") {
            return Err("provider request has no typed model-input field".to_owned());
        }
        let occurrences = count_context_occurrences(&value, context)?;
        if occurrences != 1 {
            return Err(format!(
                "canonical context must occur in exactly one JSON string, observed {occurrences}"
            ));
        }
        Ok(())
    }
}

fn count_context_occurrences(
    value: &serde_json::Value,
    context: &str,
) -> Result<usize, String> {
    match value {
        serde_json::Value::String(text) => Ok(text.match_indices(context).count()),
        serde_json::Value::Array(values) => values.iter().try_fold(0_usize, |total, value| {
            total
                .checked_add(count_context_occurrences(value, context)?)
                .ok_or_else(|| "context occurrence count overflow".to_owned())
        }),
        serde_json::Value::Object(values) => values.values().try_fold(0_usize, |total, value| {
            total
                .checked_add(count_context_occurrences(value, context)?)
                .ok_or_else(|| "context occurrence count overflow".to_owned())
        }),
        _ => Ok(0),
    }
}

fn push_framing_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&u64::try_from(value.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

'''
replace_once(
    "codex-rs/hepta-agentd/src/exact_context_delivery.rs",
    "#[derive(Clone)]\nstruct TokenizerRuntimeConfig {",
    policy_impl + "#[derive(Clone)]\nstruct TokenizerRuntimeConfig {",
)

replace_once(
    "codex-rs/hepta-agentd/src/exact_context_delivery.rs",
    "mod tests {\n"
    "    use super::ExactContextDeliveryError;\n"
    "    use super::parse_token_count;",
    "mod tests {\n"
    "    use super::ExactContextDeliveryError;\n"
    "    use super::ResponsesJsonFramingPolicy;\n"
    "    use super::parse_token_count;\n"
    "    use codex_hepta_context_compiler::FinalRequestFramingVerifierV2;\n"
    "    use codex_hepta_types::Digest32;",
)
replace_once(
    "codex-rs/hepta-agentd/src/exact_context_delivery.rs",
    "    fn exact_tokenizer_output_is_strict_decimal() {\n"
    "        assert_eq!(parse_token_count(b\"42\\n\"), Ok(42));\n"
    "        assert_eq!(\n"
    "            parse_token_count(b\"estimate=42\"),\n"
    "            Err(ExactContextDeliveryError::TokenizerRejected)\n"
    "        );\n"
    "        assert_eq!(\n"
    "            parse_token_count(b\"0\"),\n"
    "            Err(ExactContextDeliveryError::TokenizerRejected)\n"
    "        );\n"
    "    }\n",
    "    fn exact_tokenizer_output_is_strict_decimal() {\n"
    "        assert_eq!(parse_token_count(b\"42\\n\"), Ok(42));\n"
    "        assert_eq!(\n"
    "            parse_token_count(b\"estimate=42\"),\n"
    "            Err(ExactContextDeliveryError::TokenizerRejected)\n"
    "        );\n"
    "        assert_eq!(\n"
    "            parse_token_count(b\"0\"),\n"
    "            Err(ExactContextDeliveryError::TokenizerRejected)\n"
    "        );\n"
    "    }\n\n"
    "    #[test]\n"
    "    fn framing_policy_accepts_one_bound_context_and_rejects_aliases() {\n"
    "        let policy = ResponsesJsonFramingPolicy::new(\n"
    "            \"provider\",\n"
    "            \"model\",\n"
    "            Digest32::of_bytes(b\"config\"),\n"
    "            Digest32::of_bytes(b\"endpoint\"),\n"
    "        )\n"
    "        .expect(\"policy\");\n"
    "        let context = br#\"{\\\"schema\\\":\\\"hepta.context-bundle.v2\\\"}\"#;\n"
    "        let request = serde_json::json!({\n"
    "            \"model\": \"model\",\n"
    "            \"instructions\": String::from_utf8(context.to_vec()).expect(\"utf8\"),\n"
    "            \"input\": []\n"
    "        });\n"
    "        let request = serde_json::to_vec(&request).expect(\"request\");\n"
    "        policy\n"
    "            .verify_final_request(&request, context)\n"
    "            .expect(\"single context\");\n\n"
    "        let duplicate = serde_json::json!({\n"
    "            \"model\": \"model\",\n"
    "            \"instructions\": String::from_utf8(context.to_vec()).expect(\"utf8\"),\n"
    "            \"input\": [String::from_utf8(context.to_vec()).expect(\"utf8\")]\n"
    "        });\n"
    "        let duplicate = serde_json::to_vec(&duplicate).expect(\"request\");\n"
    "        assert!(policy.verify_final_request(&duplicate, context).is_err());\n\n"
    "        let wrong_model = serde_json::json!({\n"
    "            \"model\": \"other\",\n"
    "            \"instructions\": String::from_utf8(context.to_vec()).expect(\"utf8\"),\n"
    "            \"input\": []\n"
    "        });\n"
    "        let wrong_model = serde_json::to_vec(&wrong_model).expect(\"request\");\n"
    "        assert!(policy.verify_final_request(&wrong_model, context).is_err());\n"
    "    }\n",
)
