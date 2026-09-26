#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:110]!r}")
    file_path.write_text(text.replace(old, new, 1))


# Exact tokenizer execution uses a bounded Tokio child process and timeout.
replace_once(
    "codex-rs/hepta-agentd/Cargo.toml",
    '    "macros",\n    "rt-multi-thread",',
    '    "macros",\n    "process",\n    "rt-multi-thread",',
)
replace_once(
    "codex-rs/hepta-agentd/src/exact_context_delivery.rs",
    "use std::path::PathBuf;\n",
    "use std::path::PathBuf;\nuse std::process::Stdio;\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/exact_context_delivery.rs",
    "use tokio::process::Stdio;\n",
    "",
)

# Never turn an impossible canonical-intent serialization failure into a zero
# digest. Persisting pre-send evidence itself remains fallible and fail-closed.
replace_once(
    "codex-rs/hepta-agentd/src/exact_context_delivery.rs",
    "        let pre_send = StoredPreSend::new(&request, &fresh, &final_request_proof, &intent, now_unix_ms);",
    "        let pre_send = StoredPreSend::new(\n"
    "            &request,\n"
    "            &fresh,\n"
    "            &final_request_proof,\n"
    "            &intent,\n"
    "            now_unix_ms,\n"
    "        )?;",
)
replace_once(
    "codex-rs/hepta-agentd/src/exact_context_delivery.rs",
    "    ) -> Self {\n"
    "        Self {\n"
    "            thread_id: request.attempt.thread_id.clone(),",
    "    ) -> Result<Self, ExactContextDeliveryError> {\n"
    "        Ok(Self {\n"
    "            thread_id: request.attempt.thread_id.clone(),",
)
replace_once(
    "codex-rs/hepta-agentd/src/exact_context_delivery.rs",
    "            provider_intent_digest: Digest32::of_bytes(\n"
    "                &intent.canonical_wire_bytes().unwrap_or_default(),\n"
    "            )\n"
    "            .into_array(),",
    "            provider_intent_digest: Digest32::of_bytes(\n"
    "                &intent\n"
    "                    .canonical_wire_bytes()\n"
    "                    .map_err(ExactContextDeliveryError::Domain)?,\n"
    "            )\n"
    "            .into_array(),",
)
replace_once(
    "codex-rs/hepta-agentd/src/exact_context_delivery.rs",
    "            segment_map_digest: proof.segment_map_digest().into_array(),\n"
    "            recorded_unix_ms,\n"
    "        }\n"
    "    }\n"
    "}\n\n"
    "#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]",
    "            segment_map_digest: proof.segment_map_digest().into_array(),\n"
    "            recorded_unix_ms,\n"
    "        })\n"
    "    }\n"
    "}\n\n"
    "#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]",
)

# Export the fresh-registry preparation object to the Agentd product owner.
replace_once(
    "codex-rs/hepta-intelligence/src/lib.rs",
    "pub use prompt_delivery::PromptRegistryCompilationRequestV2;\n",
    "pub use prompt_delivery::PromptRegistryCompilationRequestV2;\n"
    "pub use prompt_delivery::PromptRegistryDeliveryPreparationV2;\n",
)
replace_once(
    "codex-rs/hepta-intelligence/src/lib.rs",
    "pub use prompt_delivery::compile_prompt_registry_v2;\n",
    "pub use prompt_delivery::compile_prompt_registry_v2;\n"
    "pub use prompt_delivery::prepare_prompt_registry_delivery_v2;\n",
)

# Register the Agentd-owned exact closure module.
replace_once(
    "codex-rs/hepta-agentd/src/lib.rs",
    "mod error;\n",
    "mod error;\nmod exact_context_delivery;\n",
)

# Compose the exact owner with the same durable registry instance as compilation.
replace_once(
    "codex-rs/hepta-agentd/src/prompt_runtime.rs",
    "use serde::Serialize;\n",
    "use serde::Serialize;\n\n"
    "use crate::exact_context_delivery::AgentdExactContextDeliveryOwner;\n"
    "use crate::exact_context_delivery::ExactContextDeliveryError;\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/prompt_runtime.rs",
    "    RuntimeOpen(AgentdPromptRuntimeError),\n"
    "    StatePoisoned,",
    "    RuntimeOpen(AgentdPromptRuntimeError),\n"
    "    ExactOpen(ExactContextDeliveryError),\n"
    "    StatePoisoned,",
)
replace_once(
    "codex-rs/hepta-agentd/src/prompt_runtime.rs",
    "    Stage(AgentdPromptRuntimeError),\n",
    "    Stage(AgentdPromptRuntimeError),\n"
    "    ExactStage(ExactContextDeliveryError),\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/prompt_runtime.rs",
    "pub struct AgentdPromptPipelineOwner {\n"
    "    registry: Mutex<DurablePromptRegistry>,\n"
    "    runtime: Arc<AgentdPromptRuntimeOwner>,\n"
    "}",
    "pub struct AgentdPromptPipelineOwner {\n"
    "    registry: Arc<Mutex<DurablePromptRegistry>>,\n"
    "    runtime: Arc<AgentdPromptRuntimeOwner>,\n"
    "    exact: Arc<AgentdExactContextDeliveryOwner>,\n"
    "}",
)
replace_once(
    "codex-rs/hepta-agentd/src/prompt_runtime.rs",
    "        let runtime = AgentdPromptRuntimeOwner::open_state_dir(runtime_directory)\n"
    "            .map_err(AgentdPromptPipelineError::RuntimeOpen)?;\n"
    "        Ok(Self {\n"
    "            registry: Mutex::new(registry),\n"
    "            runtime: Arc::new(runtime),\n"
    "        })",
    "        let registry = Arc::new(Mutex::new(registry));\n"
    "        let runtime = AgentdPromptRuntimeOwner::open_state_dir(runtime_directory)\n"
    "            .map_err(AgentdPromptPipelineError::RuntimeOpen)?;\n"
    "        let exact_directory = runtime_directory.join(\"context-delivery-v2\");\n"
    "        let exact = AgentdExactContextDeliveryOwner::open(\n"
    "            &exact_directory,\n"
    "            Arc::clone(&registry),\n"
    "        )\n"
    "        .map_err(AgentdPromptPipelineError::ExactOpen)?;\n"
    "        Ok(Self {\n"
    "            registry,\n"
    "            runtime: Arc::new(runtime),\n"
    "            exact: Arc::new(exact),\n"
    "        })",
)

# The App Server receives one host containing both the compatibility runtime and
# the exact V2 pre-send/terminal closure. Missing tokenizer configuration fails
# only context-bearing sends, not unrelated Agentd startup.
host_method = r'''
    pub fn host(&self) -> Result<PromptRuntimeHost, AgentdPromptPipelineError> {
        let request_owner = Arc::clone(&self.exact);
        let terminal_owner = Arc::clone(&self.exact);
        let host = self
            .runtime
            .host()
            .map_err(AgentdPromptPipelineError::Stage)?
            .with_final_request_observer(move |request| {
                let owner = Arc::clone(&request_owner);
                Box::pin(async move {
                    owner
                        .observe_final_request(request)
                        .await
                        .map_err(exact_host_error)
                })
            })
            .with_final_terminal_observer(move |terminal| {
                let owner = Arc::clone(&terminal_owner);
                Box::pin(async move {
                    owner
                        .observe_final_terminal(terminal)
                        .await
                        .map_err(exact_host_error)
                })
            });
        Ok(host)
    }

'''
replace_once(
    "codex-rs/hepta-agentd/src/prompt_runtime.rs",
    "    /// Enumerate candidates from this owner's exact current durable registry.\n",
    host_method + "    /// Enumerate candidates from this owner's exact current durable registry.\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/prompt_runtime.rs",
    "        self.runtime\n"
    "            .stage_compiled_prompt_context(\n",
    "        self.exact\n"
    "            .stage(thread_id, turn_id, compiled.clone())\n"
    "            .map_err(AgentdPromptPipelineError::ExactStage)?;\n"
    "        self.runtime\n"
    "            .stage_compiled_prompt_context(\n",
)

# Exact closure errors retain a stable reason code across the extension seam.
replace_once(
    "codex-rs/hepta-agentd/src/prompt_runtime.rs",
    "fn host_error(error: AgentdPromptRuntimeError) -> PromptRuntimeHostError {\n",
    "fn exact_host_error(error: ExactContextDeliveryError) -> PromptRuntimeHostError {\n"
    "    PromptRuntimeHostError::new(error.reason_code(), error.to_string())\n"
    "}\n\n"
    "fn host_error(error: AgentdPromptRuntimeError) -> PromptRuntimeHostError {\n",
)

# Route the embedded App Server through the composed product owner, not the raw
# compatibility runtime host.
replace_once(
    "codex-rs/hepta-agentd/src/app_runtime.rs",
    "    let prompt_runtime_host = state\n"
    "        .prompt_pipeline_owner()\n"
    "        .runtime_owner()\n"
    "        .host()\n",
    "    let prompt_runtime_host = state\n"
    "        .prompt_pipeline_owner()\n"
    "        .host()\n",
)
