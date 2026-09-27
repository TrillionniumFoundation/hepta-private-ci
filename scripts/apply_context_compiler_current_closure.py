#!/usr/bin/env python3
"""Materialize context.compiler V3 on the current hardened provider spine.

This migration is intentionally narrow: it preserves the current typed-slot,
post-tokenization authorization, tokenizer pinning, durable observation and
recovery hardening. It only activates registry-owned V3 authority/composition,
makes V1 compatibility default-off, and joins V3 to the existing exact-body
Agentd owner. The script is one-shot and is removed by the materialization
workflow after native verification succeeds.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def path(name: str) -> Path:
    return ROOT / name


def read(name: str) -> str:
    return path(name).read_text(encoding="utf-8")


def write(name: str, text: str) -> None:
    path(name).write_text(text, encoding="utf-8")


def replace_once(name: str, old: str, new: str) -> None:
    text = read(name)
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{name}: expected one anchor, found {count}: {old[:120]!r}")
    write(name, text.replace(old, new, 1))


def replace_all(name: str, old: str, new: str, minimum: int = 1) -> None:
    text = read(name)
    count = text.count(old)
    if count < minimum:
        raise SystemExit(f"{name}: expected at least {minimum} anchors, found {count}: {old!r}")
    write(name, text.replace(old, new))


def replace_between(name: str, start: str, end: str, replacement: str) -> None:
    text = read(name)
    first = text.find(start)
    if first < 0:
        raise SystemExit(f"{name}: missing start marker: {start[:120]!r}")
    second = text.find(end, first + len(start))
    if second < 0:
        raise SystemExit(f"{name}: missing end marker: {end[:120]!r}")
    if text.find(start, first + len(start)) >= 0:
        raise SystemExit(f"{name}: non-unique start marker: {start[:120]!r}")
    write(name, text[:first] + replacement + text[second:])


# The source-stage script registers registry authority, V3 intelligence exports,
# dependencies and construction-closed source fixes. This script starts after
# that stage and turns compatibility off by default.
intel_cargo = "codex-rs/hepta-intelligence/Cargo.toml"
replace_once(
    intel_cargo,
    'default = ["legacy-prompt-context-v1"]',
    "default = []",
)

intel_lib = "codex-rs/hepta-intelligence/src/lib.rs"
replace_all(
    intel_lib,
    '#[cfg(feature = "legacy-prompt-context-v1")]\nmod prompt_pipeline;',
    '#[cfg(any(feature = "legacy-prompt-context-v1", test))]\nmod prompt_pipeline;',
)
replace_all(
    intel_lib,
    '#[cfg(feature = "legacy-prompt-context-v1")]\nmod prompt_delivery;',
    '#[cfg(any(feature = "legacy-prompt-context-v1", test))]\nmod prompt_delivery;',
)
replace_once(
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

agentd_cargo = "codex-rs/hepta-agentd/Cargo.toml"
replace_once(
    agentd_cargo,
    'qualification-legacy-learning-write = ["codex-hepta-learning-ledger/qualification-legacy-write"]',
    'qualification-legacy-learning-write = ["codex-hepta-learning-ledger/qualification-legacy-write"]\n'
    'legacy-prompt-context-v1 = ["codex-hepta-intelligence/legacy-prompt-context-v1"]',
)

# Join V3 to the existing exact-body owner. Keep the hardened ordering:
# expensive tokenizer execution first, then one current registry-authority cut,
# proof construction and durable pre-send with no await in between.
exact = "codex-rs/hepta-agentd/src/exact_context_delivery.rs"
replace_all(exact, "PromptRegistryCompiledContextV2", "PromptRegistryCompiledContextV3")
replace_all(exact, "PromptRegistryDeliveryPreparationV2", "PreparedPromptDeliveryV3")
replace_all(exact, "prepare_prompt_registry_delivery_v2", "prepare_prompt_delivery_v3")

old_fresh = '''        let suffix = Digest32::of_bytes(request.attempt.attempt_id.as_bytes()).to_string();
        let fresh = prepare_prompt_delivery_v3(
            &registry,
            &compiled,
            now_unix_ms,
            stable_id(format!("context-snapshot:{suffix}"))?,
            stable_id(format!("context-preparation:{suffix}"))?,
        )
        .map_err(|_| ExactContextDeliveryError::AdmissionChanged)?;
        fresh.validate_for(&compiled).map_err(|_| ExactContextDeliveryError::AdmissionChanged)?;
'''
new_fresh = '''        let suffix = Digest32::of_bytes(request.attempt.attempt_id.as_bytes()).to_string();
        let fresh = prepare_prompt_delivery_v3(
            &registry,
            &compiled,
            now_unix_ms,
            stable_id(format!("context-preparation:{suffix}"))?,
        )
        .map_err(|_| ExactContextDeliveryError::AdmissionChanged)?;
'''
replace_once(exact, old_fresh, new_fresh)

replace_once(
    exact,
    "    ) -> Result<Self, ExactContextDeliveryError> {\n"
    "        let binary = absolute_regular_file(HEPTA_CONTEXT_TOKENIZER_BIN_ENV, true)?;",
    "    ) -> Result<Self, ExactContextDeliveryError> {\n"
    "        let profile = &compiled.execution_profile;\n"
    "        let binary = absolute_regular_file(HEPTA_CONTEXT_TOKENIZER_BIN_ENV, true)?;",
)
replace_once(
    exact,
    "        if provider_id != request.attempt.provider_id || model != request.attempt.model {\n"
    "            return Err(ExactContextDeliveryError::TokenizerIdentity);\n"
    "        }",
    "        if provider_id != request.attempt.provider_id\n"
    "            || model != request.attempt.model\n"
    "            || provider_id != profile.provider_id\n"
    "            || model != profile.provider_model\n"
    "            || version != profile.tokenizer.version\n"
    "        {\n"
    "            return Err(ExactContextDeliveryError::TokenizerIdentity);\n"
    "        }",
)
replace_once(
    exact,
    "        if declared != compiled.model_profile.tokenizer_digest\n"
    "            || Digest32::of_bytes(provider_id.as_bytes())\n"
    "                != compiled.model_profile.provider_id_digest\n"
    "            || Digest32::of_bytes(model.as_bytes()) != compiled.model_profile.provider_model_digest\n"
    "        {\n"
    "            return Err(ExactContextDeliveryError::TokenizerIdentity);\n"
    "        }",
    "        if declared != profile.tokenizer.tokenizer_digest\n"
    "            || declared != compiled.model_profile.tokenizer_digest\n"
    "            || Digest32::of_bytes(provider_id.as_bytes())\n"
    "                != compiled.model_profile.provider_id_digest\n"
    "            || Digest32::of_bytes(model.as_bytes())\n"
    "                != compiled.model_profile.provider_model_digest\n"
    "            || Digest32::of_bytes(normalization.as_bytes())\n"
    "                != profile.tokenizer.normalization_policy_digest\n"
    "        {\n"
    "            return Err(ExactContextDeliveryError::TokenizerIdentity);\n"
    "        }",
)
replace_once(
    exact,
    "        if binary_pin.is_zero() || vocabulary_pin.is_zero()\n"
    "            || binary_pin != binary_digest || vocabulary_pin != vocabulary_digest\n"
    "        {",
    "        if binary_pin.is_zero()\n"
    "            || vocabulary_pin.is_zero()\n"
    "            || binary_pin != binary_digest\n"
    "            || vocabulary_pin != vocabulary_digest\n"
    "            || binary_digest != profile.tokenizer.binary_digest\n"
    "            || vocabulary_digest != profile.tokenizer.vocabulary_digest\n"
    "        {",
)

replace_all(exact, "registry_snapshot_digest", "authority_snapshot_digest")
replace_all(exact, "final_use_materialization_digest", "preparation_binding_digest")
replace_once(
    exact,
    "            authority_snapshot_digest: fresh.authority_snapshot_digest.into_array(),\n"
    "            preparation_binding_digest: fresh.preparation_binding_digest.into_array(),",
    "            authority_snapshot_digest: fresh\n"
    "                .preparation\n"
    "                .admission_snapshot_digest()\n"
    "                .into_array(),\n"
    "            preparation_binding_digest: fresh.preparation_binding_digest().into_array(),",
)

# Default product staging now composes V3 and hands the same typed object to the
# existing exact-body owner. V2 remains explicit compatibility-only source.
runtime = "codex-rs/hepta-agentd/src/prompt_runtime.rs"
replace_once(
    runtime,
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
replace_once(
    runtime,
    "    /// Stage one exact optimizer-exercised/registry-dereferenced context for a\n"
    "    /// real Codex turn. Only DeveloperInstruction is activated in this profile.\n"
    "    pub fn stage_compiled_prompt_context(\n",
    "    /// Compatibility-only V2 staging. It cannot arm the authoritative\n"
    "    /// registry-owned V3 exact-body proof path and is default-off.\n"
    '#[cfg(feature = "legacy-prompt-context-v1")]\n'
    "    pub fn stage_compiled_prompt_context(\n",
)

stage_marker = "    /// Explicit cleanup for aborted turns is permitted only when no provider\n"
stage_v3 = '''    /// Stage the registry-owned V3 context consumed by the exact encoded-body
    /// provider observer. The product profile currently accepts only the exact
    /// developer-policy slot; unsupported roles fail during V3 compilation.
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
        if requested_deadline_ms == 0 || model != compiled.execution_profile.provider_model {
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
        let attachment = PromptRuntimeAttachmentV1::new(
            compiled.compiled.receipt().compilation_id().clone(),
            compiled.attachment.attachment_digest(),
            compiled.attachment.payload_digest(),
            model.to_owned(),
            effective_deadline_ms,
            vec![PromptRuntimeDeveloperFragmentV1::new(canonical_bundle.to_owned())
                .map_err(|error| AgentdPromptRuntimeError::Adapter(error.to_string()))?],
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
replace_once(runtime, stage_marker, stage_v3 + stage_marker)
replace_once(
    runtime,
    "    #[allow(clippy::too_many_arguments)]\n    pub fn compile_and_stage(\n",
    '#[cfg(feature = "legacy-prompt-context-v1")]\n'
    "    #[allow(clippy::too_many_arguments)]\n    pub fn compile_and_stage(\n",
)
replace_once(
    runtime,
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
v3_end = '''            .map_err(AgentdPromptPipelineError::Stage)
    }

    /// Canonical source-composed product entrypoint. The supplied capability
    /// must execute the exact tokenizer identity declared by the V3 execution
    /// profile over the provided bytes; digest lookup tables do not satisfy the
    /// trait contract.
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
replace_once(runtime, legacy_end, v3_end)

# Compatibility tests remain available explicitly; default product tests target
# the registry-owned path.
text = read(runtime)
text = text.replace(
    '#[cfg(test)]\n#[path = "prompt_runtime_tests.rs"]\nmod tests;',
    '#[cfg(all(test, feature = "legacy-prompt-context-v1"))]\n'
    '#[path = "prompt_runtime_tests.rs"]\nmod tests;',
)
write(runtime, text)

# Keep status claims granular. Source composition is not exact-head execution,
# independent acceptance or activation.
manifest_path = path("docs/modules/context.compiler/MODULE_MANIFEST.json")
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
manifest["status"]["coreImplementation"] = "complete"
manifest["status"]["productComposition"] = "source_composed"
manifest["status"]["v2ProviderClosure"] = "source_composed"
manifest["status"]["currentHeadQualification"] = "absent"
manifest["statusRationale"]["productComposition"] = (
    "Registry-owned V3 authority and compiler composition are wired into the existing Agentd exact-body owner; legacy V1 composition is default-off. Exact-head execution and ordinary product ingress evidence remain separate."
)
manifest["statusRationale"]["v2ProviderClosure"] = (
    "Typed developer-slot framing, exact final-request tokenization, post-tokenization authority revalidation, durable pre-send and monotone terminal observation are source-composed. Post-crash proof reconstruction and independent provider evidence remain open."
)
manifest["maturity"].update(
    {
        "sourceExists": True,
        "compiledModuleReachability": "source_composed_pending_exact_head_execution",
        "productCallPath": "named_agentd_entrypoint_source_composed",
        "exactHeadExecution": "unverified",
        "independentAcceptance": False,
        "activation": False,
        "release": False,
    }
)
manifest["dormantSource"] = [
    entry
    for entry in manifest.get("dormantSource", [])
    if entry.get("path")
    not in {
        "codex-rs/hepta-prompt-registry/src/context_authority.rs",
        "codex-rs/hepta-intelligence/src/prompt_product_v3.rs",
    }
]
for source in [
    "codex-rs/hepta-prompt-registry/src/context_authority.rs",
    "codex-rs/hepta-intelligence/src/prompt_product_v3.rs",
    "codex-rs/hepta-agentd/src/prompt_runtime.rs",
]:
    if source not in manifest["sourceRoots"]:
        manifest["sourceRoots"].append(source)
manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

print("context.compiler current-head V3 closure materialized")
