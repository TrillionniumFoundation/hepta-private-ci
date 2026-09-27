#!/usr/bin/env python3
"""Apply the capability and send-time final-use prompt runtime closure."""

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


def patch_optimizer_module() -> None:
    replace_once(
        "codex-rs/hepta-prompt-optimizer/src/lib.rs",
        "pub mod canonical;\nmod graph;",
        "pub mod canonical;\npub mod consumer;\nmod graph;",
    )


def patch_agentd_lib() -> None:
    path = "codex-rs/hepta-agentd/src/lib.rs"
    replace_once(
        path,
        "mod production_writer_host;\nmod prompt_runtime;",
        "mod production_writer_host;\nmod prompt_final_use;\nmod prompt_final_use_store;\nmod prompt_runtime;",
    )
    replace_once(
        path,
        "pub use production_writer_host::AgentdProductionWriterHost;\n"
        "pub use prompt_runtime::AgentdPromptPipelineError;",
        "pub use production_writer_host::AgentdProductionWriterHost;\n"
        "pub use prompt_final_use::PromptFinalUseLeaseError;\n"
        "pub use prompt_final_use::PromptFinalUseLeaseV1;\n"
        "pub use prompt_final_use::PromptFinalUseSelectionV1;\n"
        "pub use prompt_final_use_store::PromptFinalUseKeyV1;\n"
        "pub use prompt_final_use_store::PromptFinalUseStoreError;\n"
        "pub use prompt_runtime::AgentdPromptPipelineError;",
    )


def patch_app_runtime() -> None:
    path = "codex-rs/hepta-agentd/src/app_runtime.rs"
    replace_once(
        path,
        "    let prompt_runtime_host = state\n"
        "        .prompt_pipeline_owner()\n"
        "        .runtime_owner()\n"
        "        .host()\n",
        "    let prompt_runtime_host = state\n"
        "        .prompt_pipeline_owner()\n"
        "        .host()\n",
    )


def patch_prompt_runtime() -> None:
    path = "codex-rs/hepta-agentd/src/prompt_runtime.rs"
    replace_once(
        path,
        "use codex_hepta_prompt_optimizer::canonical::SelectedPromptPortfolioV1;\n"
        "use codex_hepta_prompt_optimizer::canonical::enumerate_factors_v1;\n",
        "use codex_hepta_prompt_optimizer::canonical::SelectedPromptPortfolioV1;\n"
        "use codex_hepta_prompt_optimizer::consumer::PromptConsumerCapabilitiesV1;\n"
        "use codex_hepta_prompt_optimizer::consumer::enumerate_factors_for_consumer_v1;\n",
    )
    replace_once(
        path,
        "use serde::Deserialize;\nuse serde::Serialize;\n",
        "use serde::Deserialize;\nuse serde::Serialize;\n\n"
        "use crate::prompt_final_use::PromptFinalUseLeaseError;\n"
        "use crate::prompt_final_use::PromptFinalUseLeaseV1;\n"
        "use crate::prompt_final_use_store::PromptFinalUseKeyV1;\n"
        "use crate::prompt_final_use_store::PromptFinalUseLeaseStore;\n"
        "use crate::prompt_final_use_store::PromptFinalUseStoreError;\n",
    )
    replace_once(
        path,
        "    Stage(AgentdPromptRuntimeError),\n}",
        "    Stage(AgentdPromptRuntimeError),\n"
        "    FinalUseLease(PromptFinalUseLeaseError),\n"
        "    FinalUseStore(PromptFinalUseStoreError),\n}"
    )
    replace_once(
        path,
        "pub struct AgentdPromptPipelineOwner {\n"
        "    registry: Mutex<DurablePromptRegistry>,\n"
        "    runtime: Arc<AgentdPromptRuntimeOwner>,\n"
        "}",
        "pub struct AgentdPromptPipelineOwner {\n"
        "    registry: Mutex<DurablePromptRegistry>,\n"
        "    runtime: Arc<AgentdPromptRuntimeOwner>,\n"
        "    final_use: Arc<PromptFinalUseLeaseStore>,\n"
        "}"
    )
    replace_once(
        path,
        "            .debug_struct(\"AgentdPromptPipelineOwner\")\n"
        "            .field(\"runtime\", &self.runtime)\n",
        "            .debug_struct(\"AgentdPromptPipelineOwner\")\n"
        "            .field(\"runtime\", &self.runtime)\n"
        "            .field(\"final_use\", &self.final_use)\n",
    )
    replace_once(
        path,
        "        let runtime = AgentdPromptRuntimeOwner::open_state_dir(runtime_directory)\n"
        "            .map_err(AgentdPromptPipelineError::RuntimeOpen)?;\n"
        "        Ok(Self {\n"
        "            registry: Mutex::new(registry),\n"
        "            runtime: Arc::new(runtime),\n"
        "        })",
        "        let runtime = AgentdPromptRuntimeOwner::open_state_dir(runtime_directory)\n"
        "            .map_err(AgentdPromptPipelineError::RuntimeOpen)?;\n"
        "        let final_use = PromptFinalUseLeaseStore::open(runtime_directory)\n"
        "            .map_err(AgentdPromptPipelineError::FinalUseStore)?;\n"
        "        Ok(Self {\n"
        "            registry: Mutex::new(registry),\n"
        "            runtime: Arc::new(runtime),\n"
        "            final_use: Arc::new(final_use),\n"
        "        })",
    )
    replace_once(
        path,
        "    #[must_use]\n"
        "    pub fn runtime_owner(&self) -> Arc<AgentdPromptRuntimeOwner> {\n"
        "        Arc::clone(&self.runtime)\n"
        "    }\n\n"
        "    /// Enumerate candidates from this owner's exact current durable registry.",
        "    #[must_use]\n"
        "    pub fn runtime_owner(&self) -> Arc<AgentdPromptRuntimeOwner> {\n"
        "        Arc::clone(&self.runtime)\n"
        "    }\n\n"
        "    /// Product host that enforces the durable registry lease both when\n"
        "    /// exposing staged bytes and immediately before provider dispatch.\n"
        "    pub fn host(self: &Arc<Self>) -> Result<PromptRuntimeHost, AgentdPromptPipelineError> {\n"
        "        let prepare_owner = Arc::clone(self);\n"
        "        let dispatch_owner = Arc::clone(self);\n"
        "        let record_owner = Arc::clone(self);\n"
        "        PromptRuntimeHost::new(\n"
        "            PROMPT_RUNTIME_CAPABILITY_ID,\n"
        "            move |request: PromptRuntimePrepareRequest| -> PromptRuntimePrepareFuture {\n"
        "                let owner = Arc::clone(&prepare_owner);\n"
        "                Box::pin(async move { owner.prepare_final_use(request) })\n"
        "            },\n"
        "            move |record: PromptRuntimeDispatchRecordV1| -> PromptRuntimeDispatchFuture {\n"
        "                let owner = Arc::clone(&dispatch_owner);\n"
        "                Box::pin(async move { owner.record_dispatch_final_use(record) })\n"
        "            },\n"
        "            move |record: PromptRuntimeTerminalRecordV1| -> PromptRuntimeRecordFuture {\n"
        "                let owner = Arc::clone(&record_owner);\n"
        "                Box::pin(async move { owner.record_terminal_final_use(record) })\n"
        "            },\n"
        "        )\n"
        "        .map_err(|error| {\n"
        "            AgentdPromptPipelineError::Stage(AgentdPromptRuntimeError::Adapter(\n"
        "                error.to_string(),\n"
        "            ))\n"
        "        })\n"
        "    }\n\n"
        "    /// Enumerate candidates from this owner's exact current durable registry.",
    )
    replace_once(
        path,
        "        enumerate_factors_v1(current, request)\n"
        "            .map_err(|error| AgentdPromptPipelineError::CandidateSource(error.to_string()))",
        "        enumerate_factors_for_consumer_v1(\n"
        "            current,\n"
        "            request,\n"
        "            &PromptConsumerCapabilitiesV1::developer_instruction_runtime(),\n"
        "        )\n"
        "        .map_err(|error| AgentdPromptPipelineError::CandidateSource(error.to_string()))",
    )
    replace_once(
        path,
        "    ) -> Result<PromptRuntimeStageDisposition, AgentdPromptPipelineError> {\n"
        "        let compiled = {\n"
        "            let registry = self\n"
        "                .registry\n"
        "                .lock()\n"
        "                .map_err(|_| AgentdPromptPipelineError::StatePoisoned)?;\n"
        "            compile_prompt_registry_v2(&registry, portfolio, exercise_request, compilation_request)\n"
        "                .map_err(|error| AgentdPromptPipelineError::Compilation(error.to_string()))?\n"
        "        };\n"
        "        self.runtime\n"
        "            .stage_compiled_prompt_context(\n"
        "                thread_id,\n"
        "                turn_id,\n"
        "                model,\n"
        "                requested_deadline_ms,\n"
        "                &compiled,\n"
        "            )\n"
        "            .map_err(AgentdPromptPipelineError::Stage)\n"
        "    }\n}",
        "    ) -> Result<PromptRuntimeStageDisposition, AgentdPromptPipelineError> {\n"
        "        let issued_unix_ms = compilation_request.now_unix_ms;\n"
        "        let compiled = {\n"
        "            let registry = self\n"
        "                .registry\n"
        "                .lock()\n"
        "                .map_err(|_| AgentdPromptPipelineError::StatePoisoned)?;\n"
        "            compile_prompt_registry_v2(&registry, portfolio, exercise_request, compilation_request)\n"
        "                .map_err(|error| AgentdPromptPipelineError::Compilation(error.to_string()))?\n"
        "        };\n"
        "        let lease = PromptFinalUseLeaseV1::from_compiled(\n"
        "            portfolio,\n"
        "            &compiled,\n"
        "            issued_unix_ms,\n"
        "            requested_deadline_ms,\n"
        "        )\n"
        "        .map_err(AgentdPromptPipelineError::FinalUseLease)?;\n"
        "        let disposition = self\n"
        "            .runtime\n"
        "            .stage_compiled_prompt_context(\n"
        "                thread_id,\n"
        "                turn_id,\n"
        "                model,\n"
        "                requested_deadline_ms,\n"
        "                &compiled,\n"
        "            )\n"
        "            .map_err(AgentdPromptPipelineError::Stage)?;\n"
        "        let key = PromptFinalUseKeyV1::new(thread_id, turn_id)\n"
        "            .map_err(AgentdPromptPipelineError::FinalUseStore)?;\n"
        "        if let Err(error) = self.final_use.put(key, lease) {\n"
        "            if disposition == PromptRuntimeStageDisposition::Inserted {\n"
        "                let _ = self.runtime.clear_turn(thread_id, turn_id);\n"
        "            }\n"
        "            return Err(AgentdPromptPipelineError::FinalUseStore(error));\n"
        "        }\n"
        "        Ok(disposition)\n"
        "    }\n\n"
        "    pub fn clear_turn(\n"
        "        &self,\n"
        "        thread_id: &str,\n"
        "        turn_id: &str,\n"
        "    ) -> Result<bool, AgentdPromptPipelineError> {\n"
        "        let cleared = self\n"
        "            .runtime\n"
        "            .clear_turn(thread_id, turn_id)\n"
        "            .map_err(AgentdPromptPipelineError::Stage)?;\n"
        "        let key = PromptFinalUseKeyV1::new(thread_id, turn_id)\n"
        "            .map_err(AgentdPromptPipelineError::FinalUseStore)?;\n"
        "        self.final_use\n"
        "            .remove(&key)\n"
        "            .map_err(AgentdPromptPipelineError::FinalUseStore)?;\n"
        "        Ok(cleared)\n"
        "    }\n\n"
        "    fn prepare_final_use(\n"
        "        &self,\n"
        "        request: PromptRuntimePrepareRequest,\n"
        "    ) -> Result<Option<PromptRuntimeAttachmentV1>, PromptRuntimeHostError> {\n"
        "        let key = PromptFinalUseKeyV1::new(&request.thread_id, &request.turn_id)\n"
        "            .map_err(final_use_store_host_error)?;\n"
        "        let attachment = self.runtime.prepare(request)?;\n"
        "        let Some(attachment) = attachment else {\n"
        "            let _ = self.final_use.remove(&key);\n"
        "            return Ok(None);\n"
        "        };\n"
        "        let lease = self\n"
        "            .final_use\n"
        "            .get(&key)\n"
        "            .map_err(final_use_store_host_error)?\n"
        "            .ok_or_else(|| {\n"
        "                PromptRuntimeHostError::new(\n"
        "                    \"agentd_prompt_final_use_missing\",\n"
        "                    \"staged prompt context has no durable final-use lease\",\n"
        "                )\n"
        "            })?;\n"
        "        lease.validate_shape().map_err(final_use_lease_host_error)?;\n"
        "        if lease.compilation_id != attachment.compilation_id\n"
        "            || lease.context_attachment_digest != attachment.context_attachment_digest\n"
        "            || lease.context_payload_digest != attachment.context_payload_digest\n"
        "        {\n"
        "            return Err(PromptRuntimeHostError::new(\n"
        "                \"agentd_prompt_final_use_binding_mismatch\",\n"
        "                \"staged prompt context does not match its durable final-use lease\",\n"
        "            ));\n"
        "        }\n"
        "        Ok(Some(attachment))\n"
        "    }\n\n"
        "    fn record_dispatch_final_use(\n"
        "        &self,\n"
        "        record: PromptRuntimeDispatchRecordV1,\n"
        "    ) -> Result<(), PromptRuntimeHostError> {\n"
        "        let key = PromptFinalUseKeyV1::new(&record.thread_id, &record.turn_id)\n"
        "            .map_err(final_use_store_host_error)?;\n"
        "        let lease = self\n"
        "            .final_use\n"
        "            .get(&key)\n"
        "            .map_err(final_use_store_host_error)?\n"
        "            .ok_or_else(|| {\n"
        "                PromptRuntimeHostError::new(\n"
        "                    \"agentd_prompt_final_use_missing\",\n"
        "                    \"provider dispatch has no durable prompt final-use lease\",\n"
        "                )\n"
        "            })?;\n"
        "        if lease.compilation_id != record.compilation_id\n"
        "            || lease.context_attachment_digest != record.context_attachment_digest\n"
        "            || lease.context_payload_digest != record.context_payload_digest\n"
        "        {\n"
        "            return Err(PromptRuntimeHostError::new(\n"
        "                \"agentd_prompt_final_use_binding_mismatch\",\n"
        "                \"provider dispatch does not match its prompt final-use lease\",\n"
        "            ));\n"
        "        }\n"
        "        let registry = self.registry.lock().map_err(|_| {\n"
        "            PromptRuntimeHostError::new(\n"
        "                \"agentd_prompt_registry_state_poisoned\",\n"
        "                \"prompt registry owner lock is poisoned\",\n"
        "            )\n"
        "        })?;\n"
        "        lease\n"
        "            .validate_current(&registry, record.dispatched_unix_ms)\n"
        "            .map_err(final_use_lease_host_error)?;\n"
        "        self.runtime.record_dispatch(record)\n"
        "    }\n\n"
        "    fn record_terminal_final_use(\n"
        "        &self,\n"
        "        record: PromptRuntimeTerminalRecordV1,\n"
        "    ) -> Result<(), PromptRuntimeHostError> {\n"
        "        let key = PromptFinalUseKeyV1::new(&record.thread_id, &record.turn_id)\n"
        "            .map_err(final_use_store_host_error)?;\n"
        "        let clear = terminal_clears_stage(&record);\n"
        "        self.runtime.record(record)?;\n"
        "        if clear {\n"
        "            self.final_use\n"
        "                .remove(&key)\n"
        "                .map_err(final_use_store_host_error)?;\n"
        "        }\n"
        "        Ok(())\n"
        "    }\n"
        "}\n\n"
        "fn final_use_store_host_error(error: PromptFinalUseStoreError) -> PromptRuntimeHostError {\n"
        "    PromptRuntimeHostError::new(\n"
        "        \"agentd_prompt_final_use_store_error\",\n"
        "        error.to_string(),\n"
        "    )\n"
        "}\n\n"
        "fn final_use_lease_host_error(error: PromptFinalUseLeaseError) -> PromptRuntimeHostError {\n"
        "    PromptRuntimeHostError::new(\n"
        "        \"agentd_prompt_final_use_lease_error\",\n"
        "        error.to_string(),\n"
        "    )\n"
        "}",
    )


def main() -> None:
    patch_optimizer_module()
    patch_agentd_lib()
    patch_app_runtime()
    patch_prompt_runtime()


if __name__ == "__main__":
    main()
