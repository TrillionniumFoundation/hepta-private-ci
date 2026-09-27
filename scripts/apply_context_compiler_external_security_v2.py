#!/usr/bin/env python3
"""Run the external-security materializer with recovery-stable V3 anchors."""
from __future__ import annotations

from pathlib import Path
import runpy

path = Path("scripts/apply_context_compiler_external_security.py")
text = path.read_text(encoding="utf-8")

compile_old = '''replace_once(
    "codex-rs/hepta-agentd/src/prompt_runtime.rs",
    "    ) -> Result<PromptRuntimeStageDisposition, AgentdPromptPipelineError> {\\n"
    "        let compiled = {\\n"
    "            let registry = self\\n",
    "    ) -> Result<PromptRuntimeStageDisposition, AgentdPromptPipelineError> {\\n"
    "        let observed_unix_ms = compilation_request.now_unix_ms;\\n"
    "        let compiled = {\\n"
    "            let registry = self\\n",
)
'''
compile_new = '''replace_once(
    "codex-rs/hepta-agentd/src/prompt_runtime.rs",
    "    pub async fn compile_and_stage_v3<T: PromptExactTokenizerV3>(\\n"
    "        &self,\\n"
    "        thread_id: &str,\\n"
    "        turn_id: &str,\\n"
    "        model: &str,\\n"
    "        requested_deadline_ms: u64,\\n"
    "        portfolio: &SelectedPromptPortfolioV1,\\n"
    "        exercise_request: &PromptExerciseRequestV1,\\n"
    "        compilation_request: PromptRegistryCompilationRequestV3,\\n"
    "        tokenizer: &T,\\n"
    "    ) -> Result<PromptRuntimeStageDisposition, AgentdPromptPipelineError> {\\n"
    "        let compiled = {\\n"
    "            let registry = self\\n",
    "    pub async fn compile_and_stage_v3<T: PromptExactTokenizerV3>(\\n"
    "        &self,\\n"
    "        thread_id: &str,\\n"
    "        turn_id: &str,\\n"
    "        model: &str,\\n"
    "        requested_deadline_ms: u64,\\n"
    "        portfolio: &SelectedPromptPortfolioV1,\\n"
    "        exercise_request: &PromptExerciseRequestV1,\\n"
    "        compilation_request: PromptRegistryCompilationRequestV3,\\n"
    "        tokenizer: &T,\\n"
    "    ) -> Result<PromptRuntimeStageDisposition, AgentdPromptPipelineError> {\\n"
    "        let observed_unix_ms = compilation_request.now_unix_ms;\\n"
    "        let compiled = {\\n"
    "            let registry = self\\n",
)
'''

request_old = '''replace_once(
    "codex-rs/hepta-agentd/src/exact_context_delivery.rs",
    "    ) -> Result<(), ExactContextDeliveryError> {\\n"
    "        self.store.ensure_available()?;\\n"
    "        request\\n"
    "            .attempt\\n",
    "    ) -> Result<(), ExactContextDeliveryError> {\\n"
    "        self.store.ensure_available()?;\\n"
    "        self.security\\n"
    "            .capabilities()\\n"
    "            .map_err(|_| ExactContextDeliveryError::SecurityCapability)?;\\n"
    "        request\\n"
    "            .attempt\\n",
)
'''
request_new = '''replace_once(
    "codex-rs/hepta-agentd/src/exact_context_delivery.rs",
    "    pub(crate) async fn observe_final_request(\\n"
    "        self: Arc<Self>,\\n"
    "        request: PromptRuntimeFinalRequestV2,\\n"
    "    ) -> Result<(), ExactContextDeliveryError> {\\n",
    "    pub(crate) async fn observe_final_request(\\n"
    "        self: Arc<Self>,\\n"
    "        request: PromptRuntimeFinalRequestV2,\\n"
    "    ) -> Result<(), ExactContextDeliveryError> {\\n"
    "        self.security\\n"
    "            .capabilities()\\n"
    "            .map_err(|_| ExactContextDeliveryError::SecurityCapability)?;\\n",
)
'''

for label, old, new in (
    ("compile-and-stage-v3", compile_old, compile_new),
    ("observe-final-request", request_old, request_new),
):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label} external-security anchor drifted: observed {count}")
    text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
runpy.run_path(str(path), run_name="__main__")
