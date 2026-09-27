#!/usr/bin/env python3
"""Run the external-security materializer with a V3-unique method anchor."""
from __future__ import annotations

from pathlib import Path
import runpy

path = Path("scripts/apply_context_compiler_external_security.py")
text = path.read_text(encoding="utf-8")
old = '''replace_once(
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
new = '''replace_once(
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
count = text.count(old)
if count != 1:
    raise SystemExit(f"external security patch anchor drifted: observed {count}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
runpy.run_path(str(path), run_name="__main__")
