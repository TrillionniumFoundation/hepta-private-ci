#!/usr/bin/env python3
# Integrate registry-owned V3 compilation with the existing exact HTTP-body provider spine.

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}: {old[:120]!r}")
    write(path, text.replace(old, new))


def replace_all(path: str, old: str, new: str, minimum: int = 1) -> None:
    text = read(path)
    count = text.count(old)
    if count < minimum:
        raise SystemExit(f"{path}: expected at least {minimum} anchors, found {count}: {old!r}")
    write(path, text.replace(old, new))


def replace_between(path: str, start: str, end: str, replacement: str) -> None:
    text = read(path)
    start_index = text.find(start)
    if start_index < 0:
        raise SystemExit(f"{path}: missing start marker: {start!r}")
    end_index = text.find(end, start_index)
    if end_index < 0:
        raise SystemExit(f"{path}: missing end marker: {end!r}")
    if text.find(start, start_index + len(start)) >= 0:
        raise SystemExit(f"{path}: start marker is not unique: {start!r}")
    write(path, text[:start_index] + replacement + text[end_index:])


def remove(path: str) -> None:
    target = ROOT / path
    if target.exists():
        target.unlink()


# The exact encoded-body bridge remains the sole physical provider spine. Remove
# the alternative experimental Core/extension host to avoid two proof paths.
for obsolete in [
    "codex-rs/core/src/model_provider_policy/context_input.rs",
    "codex-rs/ext/extension-api/src/contributors/model_provider_context.rs",
    "codex-rs/ext/hepta-prompt/src/v3.rs",
    "codex-rs/hepta-agentd/src/prompt_product_v3.rs",
    "codex-rs/hepta-context-compiler/src/v2/preparation_archive.rs",
    "scripts/apply_context_compiler_v3_core.py",
]:
    remove(obsolete)

# Legacy prompt composition is source-compatible but default-off. Tests retain
# internal access to fixtures without exporting the compatibility API.
replace(
    "codex-rs/hepta-intelligence/Cargo.toml",
    'default = ["legacy-prompt-context-v1"]',
    "default = []",
)
replace_all(
    "codex-rs/hepta-intelligence/src/lib.rs",
    '#[cfg(feature = "legacy-prompt-context-v1")]\nmod prompt_pipeline;',
    '#[cfg(any(feature = "legacy-prompt-context-v1", test))]\nmod prompt_pipeline;',
)
replace_all(
    "codex-rs/hepta-intelligence/src/lib.rs",
    '#[cfg(feature = "legacy-prompt-context-v1")]\nmod prompt_delivery;',
    '#[cfg(any(feature = "legacy-prompt-context-v1", test))]\nmod prompt_delivery;',
)
replace(
    "codex-rs/hepta-intelligence/src/prompt_delivery.rs",
    "use crate::PromptContextCompileRequestV1;\n"
    "use crate::PromptDeliveryPrepareRequestV1;\n"
    "use crate::PromptPipelineErrorV1;\n"
    "use crate::compile_exercised_prompt_context_v1;\n"
    "use crate::prepare_prompt_delivery_v1;",
    "use crate::prompt_pipeline::PromptContextCompileRequestV1;\n"
    "use crate::prompt_pipeline::PromptDeliveryPrepareRequestV1;\n"
    "use crate::prompt_pipeline::PromptPipelineErrorV1;\n"
    "use crate::prompt_pipeline::compile_exercised_prompt_context_v1;\n"
    "use crate::prompt_pipeline::prepare_prompt_delivery_v1;",
)

replace(
    "codex-rs/hepta-agentd/Cargo.toml",
    'qualification-legacy-learning-write = ["codex-hepta-learning-ledger/qualification-legacy-write"]',
    'qualification-legacy-learning-write = ["codex-hepta-learning-ledger/qualification-legacy-write"]\n'
    'legacy-prompt-context-v1 = ["codex-hepta-intelligence/legacy-prompt-context-v1"]',
)

# Adapt the exact encoded-request observer from provisional V2 source composition
# to the registry-owned V3 compiler and typed authority successor.
exact_path = "codex-rs/hepta-agentd/src/exact_context_delivery.rs"
replace_all(exact_path, "PromptRegistryCompiledContextV2", "PromptRegistryCompiledContextV3")
replace_all(exact_path, "PromptRegistryDeliveryPreparationV2", "PreparedPromptDeliveryV3")
replace_all(exact_path, "prepare_prompt_registry_delivery_v2", "prepare_prompt_delivery_v3")

replace(
    exact_path,
    "use codex_hepta_intelligence::PreparedPromptDeliveryV3;\n"
    "use codex_hepta_intelligence::PromptRegistryCompiledContextV3;\n"
    "use codex_hepta_intelligence::prepare_prompt_delivery_v3;",
    "use codex_hepta_intelligence::PreparedPromptDeliveryV3;\n"
    "use codex_hepta_intelligence::PromptRegistryCompiledContextV3;\n"
    "use codex_hepta_intelligence::prepare_prompt_delivery_v3;",
)

replace_between(
    exact_path,
    '        let suffix = Digest32::of_bytes(request.attempt.attempt_id.as_bytes()).to_string();\n',
    '        let tokenizer = TokenizerRuntimeConfig::load(&request, &compiled)?;\n',
    '''        let suffix = Digest32::of_bytes(request.attempt.attempt_id.as_bytes()).to_string();
        let preparation_id = stable_id(format!("context-preparation:{suffix}"))?;
        let fresh = {
            let registry = self.registry.lock().unwrap_or_else(PoisonError::into_inner);
            prepare_prompt_delivery_v3(&registry, &compiled, now_unix_ms, preparation_id)
                .map_err(|error| ExactContextDeliveryError::Domain(error.to_string()))?
        };

''',
)

# Replace the tokenizer loader so the exact final request must use the same
# provider/model/binary/vocabulary/normalization/version identity admitted by V3.
replace_between(
    exact_path,
    "#[derive(Clone)]\nstruct TokenizerRuntimeConfig {\n",
    "struct BoundFinalRequestTokenizer {\n",
    r'''#[derive(Clone)]
struct TokenizerRuntimeConfig {
    binary: PathBuf,
    vocabulary: PathBuf,
    provider_id: String,
    model: String,
    version: String,
    normalization: String,
    timeout: Duration,
    identity: FinalRequestTokenizerIdentityV2,
}

impl TokenizerRuntimeConfig {
    fn load(
        request: &PromptRuntimeFinalRequestV2,
        compiled: &PromptRegistryCompiledContextV3,
    ) -> Result<Self, ExactContextDeliveryError> {
        let profile = &compiled.execution_profile;
        let binary = absolute_regular_file(HEPTA_CONTEXT_TOKENIZER_BIN_ENV, true)?;
        let vocabulary = absolute_regular_file(HEPTA_CONTEXT_TOKENIZER_VOCAB_ENV, false)?;
        let provider_id = bounded_env(HEPTA_CONTEXT_TOKENIZER_PROVIDER_ID_ENV, 512)?;
        let model = bounded_env(HEPTA_CONTEXT_TOKENIZER_MODEL_ENV, 512)?;
        let version = bounded_env(HEPTA_CONTEXT_TOKENIZER_VERSION_ENV, 256)?;
        let normalization = bounded_env(HEPTA_CONTEXT_TOKENIZER_NORMALIZATION_ENV, 256)?;
        if provider_id != request.attempt.provider_id
            || model != request.attempt.model
            || provider_id != profile.provider_id
            || model != profile.provider_model
            || version != profile.tokenizer.version
        {
            return Err(ExactContextDeliveryError::TokenizerIdentity);
        }
        let declared = Digest32::from_str(&bounded_env(
            HEPTA_CONTEXT_TOKENIZER_PROFILE_SHA256_ENV,
            64,
        )?)
        .map_err(|_| ExactContextDeliveryError::TokenizerIdentity)?;
        let binary_digest = hash_bounded_file(&binary)?;
        let vocabulary_digest = hash_bounded_file(&vocabulary)?;
        let normalization_digest = Digest32::of_bytes(normalization.as_bytes());
        if declared != profile.tokenizer.tokenizer_digest
            || binary_digest != profile.tokenizer.binary_digest
            || vocabulary_digest != profile.tokenizer.vocabulary_digest
            || normalization_digest != profile.tokenizer.normalization_policy_digest
            || declared != compiled.model_profile.tokenizer_digest
            || Digest32::of_bytes(provider_id.as_bytes())
                != compiled.model_profile.provider_id_digest
            || Digest32::of_bytes(model.as_bytes())
                != compiled.model_profile.provider_model_digest
        {
            return Err(ExactContextDeliveryError::TokenizerIdentity);
        }
        let timeout_ms = match env::var(HEPTA_CONTEXT_TOKENIZER_TIMEOUT_MS_ENV) {
            Ok(value) => value
                .parse::<u64>()
                .ok()
                .filter(|value| *value > 0 && *value <= TOKENIZER_TIMEOUT_MS_MAX)
                .ok_or(ExactContextDeliveryError::TokenizerConfiguration)?,
            Err(env::VarError::NotPresent) => TOKENIZER_TIMEOUT_MS_DEFAULT,
            Err(env::VarError::NotUnicode(_)) => {
                return Err(ExactContextDeliveryError::TokenizerConfiguration);
            }
        };
        let identity = FinalRequestTokenizerIdentityV2::new(
            Digest32::of_bytes(provider_id.as_bytes()),
            Digest32::of_bytes(model.as_bytes()),
            declared,
            binary_digest,
            Digest32::of_bytes(version.as_bytes()),
            vocabulary_digest,
            normalization_digest,
        )
        .map_err(|error| ExactContextDeliveryError::Domain(error.to_string()))?;
        Ok(Self {
            binary,
            vocabulary,
            provider_id,
            model,
            version,
            normalization,
            timeout: Duration::from_millis(timeout_ms),
            identity,
        })
    }

    async fn count(&self, request: &[u8]) -> Result<u64, ExactContextDeliveryError> {
        let mut child = Command::new(&self.binary)
            .arg("--provider")
            .arg(&self.provider_id)
            .arg("--model")
            .arg(&self.model)
            .arg("--version")
            .arg(&self.version)
            .arg("--vocabulary")
            .arg(&self.vocabulary)
            .arg("--normalization")
            .arg(&self.normalization)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .kill_on_drop(true)
            .spawn()
            .map_err(|_| ExactContextDeliveryError::TokenizerUnavailable)?;
        let mut stdin = child
            .stdin
            .take()
            .ok_or(ExactContextDeliveryError::TokenizerUnavailable)?;
        let mut stdout = child
            .stdout
            .take()
            .ok_or(ExactContextDeliveryError::TokenizerUnavailable)?;
        stdin
            .write_all(request)
            .await
            .map_err(|_| ExactContextDeliveryError::TokenizerUnavailable)?;
        drop(stdin);
        let execution = async {
            let mut output = Vec::new();
            stdout
                .take(MAX_TOKENIZER_STDOUT_BYTES + 1)
                .read_to_end(&mut output)
                .await
                .map_err(|_| ExactContextDeliveryError::TokenizerUnavailable)?;
            let status = child
                .wait()
                .await
                .map_err(|_| ExactContextDeliveryError::TokenizerUnavailable)?;
            Ok::<_, ExactContextDeliveryError>((status, output))
        };
        let (status, output) = timeout(self.timeout, execution)
            .await
            .map_err(|_| ExactContextDeliveryError::TokenizerTimeout)??;
        if !status.success()
            || u64::try_from(output.len()).unwrap_or(u64::MAX) > MAX_TOKENIZER_STDOUT_BYTES
        {
            return Err(ExactContextDeliveryError::TokenizerRejected);
        }
        parse_token_count(&output)
    }
}

''',
)

# V3 durable pre-send evidence records the registry-owned authority cut and typed
# preparation binding. Bump the schema so V2 provisional state fails closed.
replace(exact_path, "const EXACT_DELIVERY_SCHEMA: u32 = 1;", "const EXACT_DELIVERY_SCHEMA: u32 = 2;")
replace_all(exact_path, "registry_snapshot_digest", "authority_snapshot_digest")
replace_all(exact_path, "final_use_materialization_digest", "preparation_binding_digest")
replace(
    exact_path,
    "            authority_snapshot_digest: fresh.authority_snapshot_digest.into_array(),\n"
    "            preparation_binding_digest: fresh.preparation_binding_digest.into_array(),",
    "            authority_snapshot_digest: fresh.preparation.admission_snapshot_digest().into_array(),\n"
    "            preparation_binding_digest: fresh.preparation_binding_digest().into_array(),",
)

# Product runtime: default path compiles V3 with an explicit exact-tokenizer
# capability, stages that exact object into the encoded-body owner, then exposes
# the existing App Server host. V2 remains qualification-only and cannot stage
# authoritative exact-delivery evidence.
runtime_path = "codex-rs/hepta-agentd/src/prompt_runtime.rs"
replace(
    runtime_path,
    "use codex_hepta_intelligence::PromptRegistryCompilationRequestV2;\n"
    "use codex_hepta_intelligence::PromptRegistryCompiledContextV2;\n"
    "use codex_hepta_intelligence::compile_prompt_registry_v2;",
    '#[cfg(feature = "legacy-prompt-context-v1")]\n'
    "use codex_hepta_intelligence::PromptRegistryCompilationRequestV2;\n"
    '#[cfg(feature = "legacy-prompt-context-v1")]\n'
    "use codex_hepta_intelligence::PromptRegistryCompiledContextV2;\n"
    '#[cfg(feature = "legacy-prompt-context-v1")]\n'
    "use codex_hepta_intelligence::compile_prompt_registry_v2;\n"
    "use codex_hepta_intelligence::PromptExactTokenizerV3;\n"
    "use codex_hepta_intelligence::PromptRegistryCompilationRequestV3;\n"
    "use codex_hepta_intelligence::PromptRegistryCompiledContextV3;\n"
    "use codex_hepta_intelligence::compile_prompt_registry_v3;",
)

replace(
    runtime_path,
    "    /// Stage one exact optimizer-exercised/registry-dereferenced context for a\n"
    "    /// real Codex turn. Only DeveloperInstruction is activated in this profile.\n"
    "    pub fn stage_compiled_prompt_context(\n",
    "    /// Qualification-only compatibility staging. It does not stage the\n"
    "    /// authoritative exact-body V3 proof object and is default-off.\n"
    '#[cfg(feature = "legacy-prompt-context-v1")]\n'
    "    pub fn stage_compiled_prompt_context(\n",
)

stage_marker = "    /// Explicit cleanup for aborted turns is permitted only when no provider\n"
stage_v3 = r'''    /// Stage the registry-owned V3 context consumed by the exact encoded-body
    /// provider observer. Unsupported prompt roles have already failed closed in
    /// `compile_prompt_registry_v3`.
    pub fn stage_compiled_prompt_context_v3(
        &self,
        thread_id: &str,
        turn_id: &str,
        model: &str,
        requested_deadline_ms: u64,
        compiled: &PromptRegistryCompiledContextV3,
    ) -> Result<PromptRuntimeStageDisposition, AgentdPromptRuntimeError> {
        validate_thread_id(thread_id)?;
        validate_turn_id(turn_id)?;
        validate_model(model)?;
        if requested_deadline_ms == 0
            || model != compiled.execution_profile.provider_model
        {
            return Err(AgentdPromptRuntimeError::InvalidDeadline);
        }
        compiled
            .validate()
            .map_err(|_| AgentdPromptRuntimeError::SourceValidationFailed)?;
        if compiled.selected_deliveries.is_empty() || compiled.payload().is_empty() {
            return Err(AgentdPromptRuntimeError::EmptySelection);
        }
        let mut effective_deadline_ms =
            requested_deadline_ms.min(compiled.portfolio_valid_until_unix_ms());
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
        let canonical_bundle = std::str::from_utf8(compiled.payload())
            .map_err(|_| AgentdPromptRuntimeError::PayloadNotUtf8)?;
        let fragments = vec![
            PromptRuntimeDeveloperFragmentV1::new(canonical_bundle.to_owned())
                .map_err(|error| AgentdPromptRuntimeError::Adapter(error.to_string()))?,
        ];
        let attachment = PromptRuntimeAttachmentV1::new(
            compiled.compiled.receipt().compilation_id().clone(),
            compiled.attachment.attachment_digest(),
            compiled.attachment.payload_digest(),
            model.to_owned(),
            effective_deadline_ms,
            fragments,
        )
        .map_err(|error| AgentdPromptRuntimeError::Adapter(error.to_string()))?;

        let key = PromptRuntimeKey {
            thread_id: thread_id.to_owned(),
            turn_id: turn_id.to_owned(),
        };
        self.commit_state(|state| {
            if let Some(existing) = state.staged.get(&key) {
                return if existing == &attachment {
                    Ok(PromptRuntimeStageDisposition::Unchanged)
                } else {
                    Err(AgentdPromptRuntimeError::StageConflict)
                };
            }
            if state
                .dispatch_records
                .values()
                .any(|record| dispatch_key(record) == key)
            {
                return Err(AgentdPromptRuntimeError::StageConflict);
            }
            if state.staged.len() >= MAX_STAGED_TURNS {
                return Err(AgentdPromptRuntimeError::CapacityExceeded);
            }
            state.staged.insert(key, attachment);
            Ok(PromptRuntimeStageDisposition::Inserted)
        })
    }

'''
replace(runtime_path, stage_marker, stage_v3 + stage_marker)

replace(
    runtime_path,
    "    #[allow(clippy::too_many_arguments)]\n"
    "    pub fn compile_and_stage(\n",
    '#[cfg(feature = "legacy-prompt-context-v1")]\n'
    "    #[allow(clippy::too_many_arguments)]\n"
    "    pub fn compile_and_stage(\n",
)
replace(
    runtime_path,
    "        self.exact\n"
    "            .stage(thread_id, turn_id, compiled.clone())\n"
    "            .map_err(AgentdPromptPipelineError::ExactStage)?;\n"
    "        self.runtime\n"
    "            .stage_compiled_prompt_context(\n",
    "        self.runtime\n"
    "            .stage_compiled_prompt_context(\n",
)

legacy_end = '''            .map_err(AgentdPromptPipelineError::Stage)
    }
}

fn terminal_clears_stage'''
v3_method = r'''            .map_err(AgentdPromptPipelineError::Stage)
    }

    /// Canonical product composition. The tokenizer capability must execute the
    /// exact tokenizer identity declared by the V3 profile over every supplied
    /// byte sequence; digest lookup tables are rejected by the V3 contract.
    #[allow(clippy::too_many_arguments)]
    pub fn compile_and_stage_v3<T: PromptExactTokenizerV3>(
        &self,
        thread_id: &str,
        turn_id: &str,
        model: &str,
        requested_deadline_ms: u64,
        portfolio: &SelectedPromptPortfolioV1,
        exercise_request: &PromptExerciseRequestV1,
        compilation_request: PromptRegistryCompilationRequestV3,
        tokenizer: &T,
    ) -> Result<PromptRuntimeStageDisposition, AgentdPromptPipelineError> {
        let compiled = {
            let registry = self
                .registry
                .lock()
                .map_err(|_| AgentdPromptPipelineError::StatePoisoned)?;
            compile_prompt_registry_v3(
                &registry,
                portfolio,
                exercise_request,
                compilation_request,
                tokenizer,
            )
            .map_err(|error| AgentdPromptPipelineError::Compilation(error.to_string()))?
        };
        self.exact
            .stage(thread_id, turn_id, compiled.clone())
            .map_err(AgentdPromptPipelineError::ExactStage)?;
        self.runtime
            .stage_compiled_prompt_context_v3(
                thread_id,
                turn_id,
                model,
                requested_deadline_ms,
                &compiled,
            )
            .map_err(AgentdPromptPipelineError::Stage)
    }
}

fn terminal_clears_stage'''
replace(runtime_path, legacy_end, v3_method)

# Old source tests exercise only the compatibility pipeline.
replace(
    runtime_path,
    '#[cfg(test)]\n#[path = "prompt_runtime_tests.rs"]\nmod tests;',
    '#[cfg(all(test, feature = "legacy-prompt-context-v1"))]\n'
    '#[path = "prompt_runtime_tests.rs"]\nmod tests;',
)

# Remove now-unused imported parallel source migration before the workflow commits.
remove("scripts/apply_context_compiler_v3_core.py")