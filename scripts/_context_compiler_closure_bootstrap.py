#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:80]!r}")
    file_path.write_text(text.replace(old, new, 1))


replace_once(
    "codex-rs/hepta-context-compiler/src/lib.rs",
    "mod candidate_bound;\nmod requirements;",
    "mod candidate_bound;\nmod provider_closure;\nmod requirements;",
)
replace_once(
    "codex-rs/hepta-context-compiler/src/lib.rs",
    "pub use candidate_bound::compile_candidate_bound_with_requirements;\n",
    "pub use candidate_bound::compile_candidate_bound_with_requirements;\n"
    "pub use provider_closure::ExactFinalRequestTokenizerV2;\n"
    "pub use provider_closure::FinalProviderRequestProofV2;\n"
    "pub use provider_closure::FinalRequestSegmentKindV2;\n"
    "pub use provider_closure::FinalRequestSegmentV2;\n"
    "pub use provider_closure::FinalRequestTokenizationReceiptV2;\n"
    "pub use provider_closure::FinalRequestTokenizerIdentityV2;\n"
    "pub use provider_closure::MAX_FINAL_PROVIDER_REQUEST_BYTES_V2;\n"
    "pub use provider_closure::MAX_FINAL_PROVIDER_REQUEST_SEGMENTS_V2;\n"
    "pub use provider_closure::ProviderClosureErrorV2;\n"
    "pub use provider_closure::VerifiedAdmissionSnapshotSuccessorV2;\n"
    "pub use provider_closure::prepare_delivery_from_successor_v2;\n"
    "pub use provider_closure::prove_final_provider_request_v2;\n"
    "pub use provider_closure::verify_admission_snapshot_successor_typed_v2;\n",
)
replace_once(
    "codex-rs/hepta-context-compiler/src/provider_closure.rs",
    "    pub const fn successor_snapshot_digest(&self) -> Digest32 {",
    "    pub fn successor_snapshot_digest(&self) -> Digest32 {",
)
replace_once(
    "codex-rs/hepta-context-compiler/src/provider_closure.rs",
    "    let end = start\n        .checked_add(encoded_payload.len())",
    "    let start = *start;\n    let end = start\n        .checked_add(encoded_payload.len())",
)
replace_once(
    "codex-rs/hepta-context-compiler/src/provider_closure.rs",
    "    if *start > 0 {",
    "    if start > 0 {",
)
replace_once(
    "codex-rs/hepta-context-compiler/src/provider_closure.rs",
    "            *start,\n            &request[..*start],",
    "            start,\n            &request[..start],",
)
replace_once(
    "codex-rs/hepta-context-compiler/src/provider_closure.rs",
    "        *start,\n        end,\n        &request[*start..end],",
    "        start,\n        end,\n        &request[start..end],",
)
replace_once(
    "codex-rs/hepta-context-compiler/src/provider_closure.rs",
    "        request.extend(std::iter::repeat_n(b'z', 1024 * 1024));",
    "        request.extend(std::iter::repeat(b'z').take(1024 * 1024));",
)

# Resolve the exact turn-local observer from ExtensionData. Session-local test
# observers remain the explicit override, preserving existing behavior.
replace_once(
    "codex-rs/core/src/client.rs",
    "    pub fn clear_encoded_request_body_observer(&mut self) {\n"
    "        self.encoded_request_body_observer = None;\n"
    "    }\n\n"
    "    fn reset_websocket_session(&mut self) {",
    "    pub fn clear_encoded_request_body_observer(&mut self) {\n"
    "        self.encoded_request_body_observer = None;\n"
    "    }\n\n"
    "    fn encoded_request_body_observer_for_context(\n"
    "        &self,\n"
    "        provider_policy_context: Option<&ModelProviderPolicyContext<'_>>,\n"
    "    ) -> Option<Arc<dyn codex_api::EncodedRequestBodyObserver>> {\n"
    "        self.encoded_request_body_observer.clone().or_else(|| {\n"
    "            provider_policy_context\n"
    "                .and_then(|context| {\n"
    "                    context\n"
    "                        .turn_store\n"
    "                        .get::<codex_api::EncodedRequestBodyObserverAttachment>()\n"
    "                })\n"
    "                .map(|attachment| attachment.observer())\n"
    "        })\n"
    "    }\n\n"
    "    fn reset_websocket_session(&mut self) {",
)

# HTTP request construction receives the exact turn observer. This is recomputed
# inside the retry loop but remains the same Arc from the frozen turn store.
replace_once(
    "codex-rs/core/src/client.rs",
    "            let mut options = self\n"
    "                .build_responses_options(\n"
    "                    responses_metadata,\n"
    "                    compression,\n"
    "                    model_info.use_responses_lite,\n"
    "                )\n"
    "                .await;\n\n"
    "            let mut request = self.client.build_responses_request(",
    "            let mut options = self\n"
    "                .build_responses_options(\n"
    "                    responses_metadata,\n"
    "                    compression,\n"
    "                    model_info.use_responses_lite,\n"
    "                )\n"
    "                .await;\n"
    "            let encoded_request_body_observer =\n"
    "                self.encoded_request_body_observer_for_context(provider_policy_context);\n"
    "            options.encoded_body_observer = encoded_request_body_observer.clone();\n\n"
    "            let mut request = self.client.build_responses_request(",
)
replace_once(
    "codex-rs/core/src/client.rs",
    "            if self.encoded_request_body_observer.is_some() && admitted_provider_attempt.is_none() {",
    "            if encoded_request_body_observer.is_some() && admitted_provider_attempt.is_none() {",
)
replace_once(
    "codex-rs/core/src/client.rs",
    "                        self.encoded_request_body_observer.clone(),\n",
    "                        encoded_request_body_observer.clone(),\n",
)

# Both prewarm and real send must reject WebSocket when a turn-local exact-body
# observer is installed; WebSocket has a different encoding boundary.
replace_once(
    "codex-rs/core/src/client.rs",
    "        if self.encoded_request_body_observer.is_some() {\n"
    "            return Ok(());\n"
    "        }\n"
    "        // Turn-input contributors finish preparing their turn-local state before this",
    "        if self\n"
    "            .encoded_request_body_observer_for_context(provider_policy_context)\n"
    "            .is_some()\n"
    "        {\n"
    "            return Ok(());\n"
    "        }\n"
    "        // Turn-input contributors finish preparing their turn-local state before this",
)
replace_once(
    "codex-rs/core/src/client.rs",
    "        let ephemeral_model_input_requires_http =\n"
    "            provider_policy_context.is_some_and(has_active_ephemeral_model_input_contributor);\n"
    "        let wire_api = self.client.state.provider.info().wire_api;",
    "        let ephemeral_model_input_requires_http =\n"
    "            provider_policy_context.is_some_and(has_active_ephemeral_model_input_contributor);\n"
    "        let exact_encoded_body_observer =\n"
    "            self.encoded_request_body_observer_for_context(provider_policy_context);\n"
    "        let wire_api = self.client.state.provider.info().wire_api;",
)
replace_once(
    "codex-rs/core/src/client.rs",
    "                    && self.encoded_request_body_observer.is_none()\n",
    "                    && exact_encoded_body_observer.is_none()\n",
)
