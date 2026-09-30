#!/usr/bin/env python3
"""Close prompt.registry public capability bypasses on the delivery branch."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path.cwd()


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one replacement, found {count}: {old[:120]!r}")
    write(path, text.replace(old, new, 1))


# Raw durable mutations remain available only to in-crate unit tests.
replace_once(
    "codex-rs/hepta-prompt-registry/src/durable.rs",
    """    pub fn register_factor(
        &mut self,
        factor: PromptFactor,
    ) -> Result<RegistryReceipt, DurableRegistryError> {
""",
    """    #[cfg(test)]
    pub(crate) fn register_factor(
        &mut self,
        factor: PromptFactor,
    ) -> Result<RegistryReceipt, DurableRegistryError> {
""",
)
replace_once(
    "codex-rs/hepta-prompt-registry/src/durable.rs",
    """    pub fn register_factor_relation(
        &mut self,
        relation: PromptFactorRelation,
    ) -> Result<RegistryReceipt, DurableRegistryError> {
""",
    """    #[cfg(test)]
    pub(crate) fn register_factor_relation(
        &mut self,
        relation: PromptFactorRelation,
    ) -> Result<RegistryReceipt, DurableRegistryError> {
""",
)

# Convert the external V4 relation regression to signed final-use publication.
test_path = "codex-rs/hepta-prompt-registry/tests/durable_relations_v4.rs"
replace_once(
    test_path,
    "use codex_hepta_prompt_registry::final_use_admission_binding;\n",
    "use codex_hepta_prompt_registry::final_use_admission_binding;\nuse codex_hepta_prompt_registry::final_use_register_factor_binding;\nuse codex_hepta_prompt_registry::final_use_register_relation_binding;\n",
)
replace_once(
    test_path,
    """    registry
        .register_factor(factor.clone())
        .unwrap_or_else(|error| panic!("register factor: {error}"));
    let reviewer = id("reviewer:durable-v4-test");
""",
    """    let publisher = id("publisher:durable-v4-test");
    let publish_scope = digest(&format!("scope:publish:{factor_id}"));
    let publish_binding =
        final_use_register_factor_binding(&factor, &publisher, publish_scope)
            .unwrap_or_else(|error| panic!("factor publication binding: {error}"));
    let now = now_unix_ms();
    let publish_grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "security-owner:durable-v4-test".to_owned(),
        authority_epoch: 1,
        grant_id: format!("grant:publish:{factor_id}"),
        nonce: test_nonce(&format!("{nonce_label}:publish")),
        binding: publish_binding,
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 60_000,
    };
    let signed_publish = SignedFinalUseGrant {
        signature: key
            .sign(
                &publish_grant
                    .signing_bytes()
                    .unwrap_or_else(|error| panic!("publication signing bytes: {error}")),
            )
            .to_bytes()
            .to_vec(),
        grant: publish_grant,
    };
    registry
        .register_factor_final_use(
            authority,
            &signed_publish,
            &publisher,
            publish_scope,
            factor.clone(),
        )
        .unwrap_or_else(|error| panic!("register factor: {error}"));
    let reviewer = id("reviewer:durable-v4-test");
""",
)
replace_once(test_path, "    let now = now_unix_ms();\n    let grant = FinalUseGrant {\n", "    let grant = FinalUseGrant {\n")
replace_once(
    test_path,
    """    registry
        .register_factor_relation(PromptFactorRelation {
            relation_id: id("relation:left-right-conflict"),
            left_factor_id: id("factor:left"),
            right_factor_id: id("factor:right"),
            kind: PromptFactorRelationKind::Conflicts,
            evidence_digest: digest("relation evidence"),
        })
        .unwrap_or_else(|error| panic!("durable relation: {error}"));
""",
    """    let relation = PromptFactorRelation {
        relation_id: id("relation:left-right-conflict"),
        left_factor_id: id("factor:left"),
        right_factor_id: id("factor:right"),
        kind: PromptFactorRelationKind::Conflicts,
        evidence_digest: digest("relation evidence"),
    };
    let relation_actor = id("publisher:durable-v4-relation");
    let relation_scope = digest("scope:durable-v4-relation");
    let relation_binding =
        final_use_register_relation_binding(&relation, &relation_actor, relation_scope)
            .unwrap_or_else(|error| panic!("relation publication binding: {error}"));
    let now = now_unix_ms();
    let relation_grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "security-owner:durable-v4-test".to_owned(),
        authority_epoch: 1,
        grant_id: "grant:relation:left-right-conflict".to_owned(),
        nonce: test_nonce("relation-left-right-conflict"),
        binding: relation_binding,
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 60_000,
    };
    let signed_relation = SignedFinalUseGrant {
        signature: key
            .sign(
                &relation_grant
                    .signing_bytes()
                    .unwrap_or_else(|error| panic!("relation signing bytes: {error}")),
            )
            .to_bytes()
            .to_vec(),
        grant: relation_grant,
    };
    registry
        .register_factor_relation_final_use(
            &authority,
            &signed_relation,
            &relation_actor,
            relation_scope,
            relation,
        )
        .unwrap_or_else(|error| panic!("durable relation: {error}"));
""",
)

# Make the raw Agentd prompt runtime owner crate-private and remove its raw host.
runtime_path = "codex-rs/hepta-agentd/src/prompt_runtime.rs"
replace_once(runtime_path, "pub struct AgentdPromptRuntimeOwner {", "pub(crate) struct AgentdPromptRuntimeOwner {")
for old, new in [
    ("    pub fn new() -> Self {", "    pub(crate) fn new() -> Self {"),
    ("    pub fn open_state_dir(directory: &Path) -> Result<Self, AgentdPromptRuntimeError> {", "    pub(crate) fn open_state_dir(directory: &Path) -> Result<Self, AgentdPromptRuntimeError> {"),
    ("    pub fn requires_reopen(&self) -> bool {", "    pub(crate) fn requires_reopen(&self) -> bool {"),
    ("    pub fn stage_compiled_prompt_context(", "    pub(crate) fn stage_compiled_prompt_context("),
    ("    pub fn terminal_record(", "    pub(crate) fn terminal_record("),
    ("    pub fn dispatch_record(", "    pub(crate) fn dispatch_record("),
    ("    pub fn staged_count(&self) -> Result<usize, AgentdPromptRuntimeError> {", "    pub(crate) fn staged_count(&self) -> Result<usize, AgentdPromptRuntimeError> {"),
]:
    replace_once(runtime_path, old, new)
replace_once(
    runtime_path,
    """    /// Explicit cleanup for aborted turns is permitted only when no provider
    /// attempt is unresolved. Unknown possible dispatch must be reconciled.
    pub fn clear_turn(
""",
    """    /// Explicit cleanup for aborted turns is permitted only when no provider
    /// attempt is unresolved. Unknown possible dispatch must be reconciled.
    pub(crate) fn clear_turn(
""",
)
runtime_text = read(runtime_path)
start = runtime_text.find("    pub fn host(self: &Arc<Self>) -> Result<PromptRuntimeHost, AgentdPromptRuntimeError> {")
end_marker = "\n    fn ensure_available(&self) -> Result<(), AgentdPromptRuntimeError> {"
end = runtime_text.find(end_marker, start)
if start < 0 or end < 0:
    raise SystemExit("raw runtime host block not found")
write(runtime_path, runtime_text[:start] + runtime_text[end:])

# Product App Server receives only the governed wrapper.
replace_once(
    runtime_path,
    "/// Named Agentd composition owner for the canonical prompt-intervention path.\n",
    """/// Product-only host wrapper. The raw runtime owner is deliberately not exported.
pub(crate) struct PromptPipelineHost {
    inner: PromptRuntimeHost,
}

impl PromptPipelineHost {
    fn new(inner: PromptRuntimeHost) -> Self {
        Self { inner }
    }

    pub(crate) fn into_runtime_host(self) -> PromptRuntimeHost {
        self.inner
    }
}

/// Named Agentd composition owner for the canonical prompt-intervention path.
""",
)
replace_once(
    runtime_path,
    """    #[must_use]
    pub fn runtime_owner(&self) -> Arc<AgentdPromptRuntimeOwner> {
        Arc::clone(&self.runtime)
    }

    /// Product host that enforces the durable registry lease both when
    /// exposing staged bytes and immediately before provider dispatch.
    pub fn host(self: &Arc<Self>) -> Result<PromptRuntimeHost, AgentdPromptPipelineError> {
""",
    """    #[cfg(test)]
    #[must_use]
    pub(crate) fn runtime_owner(&self) -> Arc<AgentdPromptRuntimeOwner> {
        Arc::clone(&self.runtime)
    }

    /// Product host that enforces the durable registry lease both when
    /// exposing staged bytes and immediately before provider dispatch.
    pub(crate) fn host(self: &Arc<Self>) -> Result<PromptPipelineHost, AgentdPromptPipelineError> {
""",
)
replace_once(
    runtime_path,
    """        )
        .map_err(|error| {
            AgentdPromptPipelineError::Stage(AgentdPromptRuntimeError::Adapter(error.to_string()))
        })
    }

    /// Authenticated production writer for draft factor publication.
""",
    """        )
        .map(PromptPipelineHost::new)
        .map_err(|error| {
            AgentdPromptPipelineError::Stage(AgentdPromptRuntimeError::Adapter(error.to_string()))
        })
    }

    /// Authenticated production writer for draft factor publication.
""",
)
replace_once(
    "codex-rs/hepta-agentd/src/app_runtime.rs",
    """    let prompt_runtime_host = state
        .prompt_pipeline_owner()
        .host()
        .map_err(std::io::Error::other)?;
""",
    """    let prompt_runtime_host = state
        .prompt_pipeline_owner()
        .host()
        .map_err(std::io::Error::other)?
        .into_runtime_host();
""",
)
replace_once("codex-rs/hepta-agentd/src/lib.rs", "pub use prompt_runtime::AgentdPromptRuntimeOwner;\n", "")

# Product regression publishes through the governed Agentd facade.
agentd_test = "codex-rs/hepta-agentd/src/prompt_runtime_tests.rs"
replace_once(agentd_test, "use codex_hepta_prompt_registry::final_use_realization_binding;\n", "use codex_hepta_prompt_registry::final_use_realization_binding;\nuse codex_hepta_prompt_registry::final_use_register_factor_binding;\n")
replace_once(
    agentd_test,
    "    let reviewer = id(\"reviewer:agentd-prompt\");\n",
    """    let publisher = id("publisher:agentd-prompt");
    let factor_scope = digest("scope:agentd-prompt-factor-publication");
    let factor_binding =
        final_use_register_factor_binding(&factor, &publisher, factor_scope)
            .unwrap_or_else(|error| panic!("factor publication binding: {error}"));
    let factor_grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "review-authority:agentd-prompt".to_owned(),
        authority_epoch: 1,
        grant_id: "grant:agentd-prompt-factor".to_owned(),
        nonce: test_nonce("agentd-prompt-factor"),
        binding: factor_binding,
        not_before_unix_ms: wall_now.saturating_sub(1_000),
        expires_at_unix_ms: wall_now + 30_000,
    };
    let signed_factor = SignedFinalUseGrant {
        signature: signing_key
            .sign(
                &factor_grant
                    .signing_bytes()
                    .unwrap_or_else(|error| panic!("factor signing bytes: {error}")),
            )
            .to_bytes()
            .to_vec(),
        grant: factor_grant,
    };
    let reviewer = id("reviewer:agentd-prompt");
""",
)
replace_once(agentd_test, "    let publisher = id(\"publisher:agentd-prompt\");\n    let realization_scope = digest(\"scope:agentd-prompt-realization\");\n\n", "    let realization_scope = digest(\"scope:agentd-prompt-realization\");\n\n")
agentd_text = read(agentd_test)
block_start = agentd_text.find("""    {
        let mut registry = pipeline
            .registry
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        registry
            .register_factor(factor.clone())
""")
block_end_marker = "\n    }\n\n    let logical_now = wall_now;"
block_end = agentd_text.find(block_end_marker, block_start)
if block_start < 0 or block_end < 0:
    raise SystemExit("raw Agentd publication block not found")
replacement = """    pipeline
        .publish_factor(
            &authority,
            &signed_factor,
            &publisher,
            factor_scope,
            factor.clone(),
        )
        .unwrap_or_else(|error| panic!("publish factor: {error}"));
    pipeline
        .admit_factor(
            &authority,
            &signed_admission,
            &factor.factor_id,
            admission_scope,
            admission_evidence,
        )
        .unwrap_or_else(|error| panic!("admit factor: {error}"));
    let admitted_factor = {
        let registry = pipeline
            .registry
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        registry
            .registry()
            .unwrap_or_else(|error| panic!("registry read: {error}"))
            .factor(&factor.factor_id)
            .cloned()
            .unwrap_or_else(|| panic!("admitted factor missing"))
    };
    let realization_binding = final_use_realization_binding(
        &admitted_factor,
        &publisher,
        realization_scope,
        &realization,
        None,
    )
    .unwrap_or_else(|error| panic!("realization binding: {error}"));
    let realization_grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "review-authority:agentd-prompt".to_owned(),
        authority_epoch: 1,
        grant_id: "grant:agentd-prompt-realization".to_owned(),
        nonce: test_nonce("agentd-prompt-realization"),
        binding: realization_binding,
        not_before_unix_ms: wall_now.saturating_sub(1_000),
        expires_at_unix_ms: wall_now + 30_000,
    };
    let signed_realization = SignedFinalUseGrant {
        signature: signing_key
            .sign(
                &realization_grant
                    .signing_bytes()
                    .unwrap_or_else(|error| panic!("realization signing bytes: {error}")),
            )
            .to_bytes()
            .to_vec(),
        grant: realization_grant,
    };
    pipeline
        .publish_realization(
            &authority,
            &signed_realization,
            &publisher,
            realization_scope,
            realization.clone(),
            payload.to_vec(),
            None,
        )
        .unwrap_or_else(|error| panic!("register realization: {error}"));
"""
write(agentd_test, agentd_text[:block_start] + replacement + agentd_text[block_end + len("\n    }"):])

# Make the implementation map fail closed on any reintroduced public bypass.
map_path = "scripts/hepta-prompt-registry-map.py"
replace_once(map_path, "RUNTIME_TESTS = \"codex-rs/hepta-agentd/src/prompt_runtime_tests.rs\"\n", "RUNTIME_TESTS = \"codex-rs/hepta-agentd/src/prompt_runtime_tests.rs\"\nAGENTD_LIB = \"codex-rs/hepta-agentd/src/lib.rs\"\nAPP_RUNTIME = \"codex-rs/hepta-agentd/src/app_runtime.rs\"\n")
replace_once(map_path, "    \"codex-rs/hepta-agentd/src/prompt_runtime_tests.rs\",\n", "    \"codex-rs/hepta-agentd/src/prompt_runtime_tests.rs\",\n    AGENTD_LIB,\n    APP_RUNTIME,\n")
replace_once(
    map_path,
    "def source_blob(path: str) -> str:\n",
    """def verify_closed_public_capability_surface() -> list[dict[str, str]]:
    durable = (ROOT / DURABLE).read_text(encoding="utf-8")
    runtime = (ROOT / RUNTIME).read_text(encoding="utf-8")
    agentd_lib = (ROOT / AGENTD_LIB).read_text(encoding="utf-8")
    app_runtime = (ROOT / APP_RUNTIME).read_text(encoding="utf-8")
    checks = [
        (durable, r"\n    pub fn register_factor\(", "raw durable factor mutation"),
        (durable, r"\n    pub fn register_factor_relation\(", "raw durable relation mutation"),
        (agentd_lib, r"pub use prompt_runtime::AgentdPromptRuntimeOwner;", "exported raw runtime owner"),
        (runtime, r"pub struct AgentdPromptRuntimeOwner", "public raw runtime owner"),
        (runtime, r"\n    pub fn runtime_owner\(", "public raw owner accessor"),
    ]
    for text, pattern, label in checks:
        if re.search(pattern, text):
            raise ValueError(f"public capability bypass remains: {label}")
    if "pub(crate) struct PromptPipelineHost" not in runtime:
        raise ValueError("missing product-only PromptPipelineHost")
    if ".prompt_pipeline_owner()\n        .host()" not in app_runtime:
        raise ValueError("App Server is not bound to the governed pipeline host")
    if ".runtime_owner()" in app_runtime:
        raise ValueError("App Server bypasses the governed pipeline host")
    return [
        {"surface": "durable_mutation", "state": "governed_final_use_only"},
        {"surface": "agentd_runtime_owner", "state": "crate_private"},
        {"surface": "app_server_prompt_host", "state": "prompt_pipeline_host_only"},
    ]


def source_blob(path: str) -> str:
""",
)
replace_once(
    map_path,
    """    operations.extend([
        operation("current_use_gate",
""",
    """    for name in ["publish_factor", "admit_factor", "publish_realization",
                 "publish_relation", "retire_factor", "revoke_factor"]:
        operations.append(operation(
            "product_" + name,
            "AgentdPromptPipelineOwner::" + name,
            RUNTIME,
            RUNTIME_TESTS + "::named_agentd_pipeline_stages_exact_registry_bytes_for_app_server_host",
            "governed_agentd_writer_final_use_authority",
        ))
    operations.extend([
        operation("current_use_gate",
""",
)
replace_once(map_path, "    callers = []\n", "    public_capability_surface = verify_closed_public_capability_surface()\n    callers = []\n")
replace_once(map_path, "        \"closedWorldPublicFunctions\": False,\n        \"mappingCoverage\": \"curated_owner_and_boundary_operations_not_all_public_functions\",\n", "        \"closedWorldPublicFunctions\": True,\n        \"mappingCoverage\": \"closed_world_capability_sensitive_public_entrypoints_v1\",\n        \"publicCapabilitySurface\": public_capability_surface,\n")
replace_once(map_path, "\"claimBoundary\": {\"nativeSourceMappingComplete\": False, \"sourceRootPresent\": True,\n", "\"claimBoundary\": {\"nativeSourceMappingComplete\": True, \"sourceRootPresent\": True,\n")

# Align contracts without changing activation, acceptance, or release facts.
replace_once(
    "docs/modules/prompt.registry/API_CONTRACT.md",
    """No production ingress should substitute raw draft-registration helpers for the
signed product path. Grant consumption and registry persistence are distinct
owners: an indeterminate registry outcome requires reconciliation, not blind
resubmission of a spent grant.
""",
    """Raw durable factor and relation mutation helpers are crate-test-only. The
production crate surface exposes only operation-bound governed writer methods.
Agentd does not export its raw prompt runtime owner; App Server receives the
crate-private `PromptPipelineHost`, which always performs current-use validation
before attachment exposure and immediately before durable dispatch recording.
Grant consumption and registry persistence are distinct owners: an indeterminate
registry outcome requires reconciliation, not blind resubmission of a spent
grant.
""",
)
replace_once(
    "docs/modules/prompt.registry/ARCHITECTURE.md",
    """The committed candidate currently linearizes current-use validation through the
durable dispatch claim. Transport/output checkpointing is a separate capability
""",
    """The product composition exposes only the governed `PromptPipelineHost`; raw
durable mutation and raw runtime-owner host construction are not public
capabilities. The committed candidate currently linearizes current-use
validation through the durable dispatch claim. Transport/output checkpointing is a separate capability
""",
)
replace_once(
    "docs/modules/prompt.registry/QUALIFICATION_STATUS.md",
    """Current-use validation is shared by preparation and the locked durable dispatch
claim; cached ready contexts reconsult the owner and cannot silently replace the
already injected payload.
""",
    """Current-use validation is shared by preparation and the locked durable dispatch
claim; cached ready contexts reconsult the owner and cannot silently replace the
already injected payload. Raw durable mutations are crate-test-only, the raw
Agentd prompt runtime owner is not exported, and App Server consumes only the
governed `PromptPipelineHost`.
""",
)

print("prompt.registry public capability surface closed")
