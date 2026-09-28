#!/usr/bin/env python3
"""Compose externally owned context security capabilities into direct V3 source.

Run only after the reviewed V3/recovery materializers.  This script never signs,
accepts, activates, releases, or edits qualification evidence.  It registers the
external verifier/lease/journal/tokenizer/terminal seams and makes the named V3
Agentd entry point fail closed until the full capability set is attached.
"""
from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one patch anchor, observed {count}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# Registry-owned snapshot construction remains construction-closed, but product
# use now additionally requires a separately verified external signature.
replace_once(
    "codex-rs/hepta-prompt-registry/src/lib.rs",
    "mod context_authority;\nmod delivery;\n",
    "mod context_authority;\nmod external_authority;\nmod delivery;\n",
)
replace_once(
    "codex-rs/hepta-prompt-registry/src/lib.rs",
    "pub use context_authority::prompt_context_authority_verifier_digest_v3;\n",
    "pub use context_authority::prompt_context_authority_verifier_digest_v3;\n"
    "pub use external_authority::ExternalPromptContextAuthorityErrorV3;\n"
    "pub use external_authority::ExternallyVerifiedPromptContextAuthoritySnapshotV3;\n"
    "pub use external_authority::PromptContextAuthoritySignatureV3;\n"
    "pub use external_authority::PromptContextAuthoritySignatureVerifierV3;\n"
    "pub use external_authority::VerifiedPromptContextAuthoritySignatureV3;\n"
    "pub use external_authority::verify_external_prompt_context_authority_snapshot_v3;\n"
    "pub use external_authority::verify_prompt_context_authority_signature_v3;\n",
)

# Expose only immutable clones/digests needed by the external verifier.  Callers
# still cannot construct snapshots, admissions, or verified compiler objects.
replace_once(
    "codex-rs/hepta-intelligence/src/prompt_product_v3.rs",
    "    pub fn authority_observed_unix_ms(&self) -> u64 {\n"
    "        self.verified_snapshot.observed_unix_ms()\n"
    "    }\n\n"
    "    #[must_use]\n"
    "    pub const fn authority(&self) -> AuthorityPosture {\n",
    "    pub fn authority_observed_unix_ms(&self) -> u64 {\n"
    "        self.verified_snapshot.observed_unix_ms()\n"
    "    }\n\n"
    "    #[must_use]\n"
    "    pub fn authority_snapshot_for_external_verification(\n"
    "        &self,\n"
    "    ) -> PromptContextAuthoritySnapshotV3 {\n"
    "        self.authority_snapshot.clone()\n"
    "    }\n\n"
    "    #[must_use]\n"
    "    pub const fn authority_snapshot_digest(&self) -> Digest32 {\n"
    "        self.authority_snapshot.snapshot_digest()\n"
    "    }\n\n"
    "    #[must_use]\n"
    "    pub const fn authority(&self) -> AuthorityPosture {\n",
)
replace_once(
    "codex-rs/hepta-intelligence/src/prompt_product_v3.rs",
    "    pub const fn preparation_binding_digest(&self) -> Digest32 {\n"
    "        self.preparation_binding_digest\n"
    "    }\n\n"
    "    #[must_use]\n"
    "    pub const fn authority(&self) -> AuthorityPosture {\n",
    "    pub const fn preparation_binding_digest(&self) -> Digest32 {\n"
    "        self.preparation_binding_digest\n"
    "    }\n\n"
    "    #[must_use]\n"
    "    pub fn current_authority_snapshot_for_external_verification(\n"
    "        &self,\n"
    "    ) -> PromptContextAuthoritySnapshotV3 {\n"
    "        self.authority_successor.current().clone()\n"
    "    }\n\n"
    "    #[must_use]\n"
    "    pub const fn predecessor_authority_snapshot_digest(&self) -> Digest32 {\n"
    "        self.authority_successor.predecessor_snapshot_digest()\n"
    "    }\n\n"
    "    #[must_use]\n"
    "    pub const fn authority(&self) -> AuthorityPosture {\n",
)

# Register every external security seam in the Agentd crate graph.
replace_once(
    "codex-rs/hepta-agentd/src/lib.rs",
    "mod control;\nmod error;\nmod event_buffer;\n",
    "mod control;\nmod context_attempt_journal;\nmod context_attempt_lease;\n"
    "mod context_security_runtime;\nmod context_terminal_attestation;\n"
    "mod context_tokenizer_custody;\nmod error;\nmod event_buffer;\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/lib.rs",
    "pub use config::HEPTA_COGNITIVE_RETRIEVAL_MODE_ENV;\n"
    "pub use error::AgentdError;\n",
    "pub use config::HEPTA_COGNITIVE_RETRIEVAL_MODE_ENV;\n"
    "pub use context_attempt_journal::ContextAttemptJournalErrorV3;\n"
    "pub use context_attempt_journal::ContextAttemptJournalEventV3;\n"
    "pub use context_attempt_journal::ContextAttemptJournalRecordV3;\n"
    "pub use context_attempt_journal::ContextAttemptJournalV3;\n"
    "pub use context_attempt_journal::ContextMonotonicGenerationAnchorV3;\n"
    "pub use context_attempt_journal::advance_context_generation_anchor_v3;\n"
    "pub use context_attempt_journal::append_context_attempt_journal_record_v3;\n"
    "pub use context_attempt_journal::validate_context_attempt_journal_v3;\n"
    "pub use context_attempt_lease::ContextAttemptLeaseAuthorityV3;\n"
    "pub use context_attempt_lease::ContextAttemptLeaseErrorV3;\n"
    "pub use context_attempt_lease::ContextAttemptLeaseGrantV3;\n"
    "pub use context_attempt_lease::ContextAttemptLeaseRequestV3;\n"
    "pub use context_attempt_lease::ContextAttemptLeaseSettlementV3;\n"
    "pub use context_attempt_lease::acquire_context_attempt_lease_v3;\n"
    "pub use context_security_runtime::ContextSecurityCapabilitiesV3;\n"
    "pub use context_security_runtime::ContextSecurityRuntimeV3;\n"
    "pub use context_security_runtime::ExternalContextAuthorityProviderV3;\n"
    "pub use context_security_runtime::ExternalContextSecurityErrorV3;\n"
    "pub use context_security_runtime::ProviderTerminalAttestationSourceV3;\n"
    "pub use context_terminal_attestation::IndependentProviderTerminalAttestationV3;\n"
    "pub use context_terminal_attestation::ProviderTerminalAttestationErrorV3;\n"
    "pub use context_terminal_attestation::ProviderTerminalAttestationVerifierV3;\n"
    "pub use context_terminal_attestation::VerifiedProviderTerminalAttestationV3;\n"
    "pub use context_terminal_attestation::verify_provider_terminal_attestation_v3;\n"
    "pub use context_tokenizer_custody::ImmutableTokenizerBundleIdentityV3;\n"
    "pub use context_tokenizer_custody::ImmutableTokenizerCustodyErrorV3;\n"
    "pub use context_tokenizer_custody::ImmutableTokenizerExecutionReceiptV3;\n"
    "pub use context_tokenizer_custody::ImmutableTokenizerExecutionRequestV3;\n"
    "pub use context_tokenizer_custody::ImmutableTokenizerExecutorV3;\n"
    "pub use context_tokenizer_custody::execute_immutable_tokenizer_v3;\n"
    "pub use error::AgentdError;\n",
)

# The exact physical-send owner requires the complete external capability set.
replace_once(
    "codex-rs/hepta-agentd/src/exact_context_delivery.rs",
    "use terminal_state::migrate_state;\n",
    "use terminal_state::migrate_state;\n\n"
    "use crate::context_security_runtime::ContextSecurityRuntimeV3;\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/exact_context_delivery.rs",
    "pub(crate) struct AgentdExactContextDeliveryOwner {\n"
    "    registry: Arc<Mutex<DurablePromptRegistry>>,\n",
    "pub(crate) struct AgentdExactContextDeliveryOwner {\n"
    "    registry: Arc<Mutex<DurablePromptRegistry>>,\n"
    "    security: Arc<ContextSecurityRuntimeV3>,\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/exact_context_delivery.rs",
    "    pub(crate) fn open(\n"
    "        directory: &Path,\n"
    "        registry: Arc<Mutex<DurablePromptRegistry>>,\n"
    "    ) -> Result<Self, ExactContextDeliveryError> {\n",
    "    pub(crate) fn open(\n"
    "        directory: &Path,\n"
    "        registry: Arc<Mutex<DurablePromptRegistry>>,\n"
    "        security: Arc<ContextSecurityRuntimeV3>,\n"
    "    ) -> Result<Self, ExactContextDeliveryError> {\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/exact_context_delivery.rs",
    "        Ok(Self {\n"
    "            registry,\n"
    "            state: Mutex::new(ExactRuntimeState {\n",
    "        Ok(Self {\n"
    "            registry,\n"
    "            security,\n"
    "            state: Mutex::new(ExactRuntimeState {\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/exact_context_delivery.rs",
    "    ) -> Result<(), ExactContextDeliveryError> {\n"
    "        self.store.ensure_available()?;\n"
    "        request\n"
    "            .attempt\n",
    "    ) -> Result<(), ExactContextDeliveryError> {\n"
    "        self.store.ensure_available()?;\n"
    "        self.security\n"
    "            .capabilities()\n"
    "            .map_err(|_| ExactContextDeliveryError::SecurityCapability)?;\n"
    "        request\n"
    "            .attempt\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/exact_context_delivery.rs",
    "    TokenizerRejected,\n"
    "    Domain(String),\n",
    "    TokenizerRejected,\n"
    "    SecurityCapability,\n"
    "    Domain(String),\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/exact_context_delivery.rs",
    "            Self::TokenizerRejected => \"context_delivery_v2_tokenizer_rejected\",\n"
    "            Self::Domain(_) => \"context_delivery_v2_domain_rejected\",\n",
    "            Self::TokenizerRejected => \"context_delivery_v2_tokenizer_rejected\",\n"
    "            Self::SecurityCapability => \"context_delivery_v3_security_capability_missing\",\n"
    "            Self::Domain(_) => \"context_delivery_v2_domain_rejected\",\n",
)

# Agentd product composition verifies the initial authority snapshot before any
# context is staged and exposes a one-time protected-environment attachment API.
replace_once(
    "codex-rs/hepta-agentd/src/prompt_runtime.rs",
    "use crate::exact_context_delivery::AgentdExactContextDeliveryOwner;\n",
    "use crate::context_security_runtime::ContextSecurityCapabilitiesV3;\n"
    "use crate::context_security_runtime::ContextSecurityRuntimeV3;\n"
    "use crate::context_security_runtime::ExternalContextSecurityErrorV3;\n"
    "use crate::exact_context_delivery::AgentdExactContextDeliveryOwner;\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/prompt_runtime.rs",
    "    ExactStage(ExactContextDeliveryError),\n",
    "    ExactStage(ExactContextDeliveryError),\n"
    "    Security(ExternalContextSecurityErrorV3),\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/prompt_runtime.rs",
    "pub struct AgentdPromptPipelineOwner {\n"
    "    registry: Arc<Mutex<DurablePromptRegistry>>,\n"
    "    runtime: Arc<AgentdPromptRuntimeOwner>,\n"
    "    exact: Arc<AgentdExactContextDeliveryOwner>,\n"
    "}\n",
    "pub struct AgentdPromptPipelineOwner {\n"
    "    registry: Arc<Mutex<DurablePromptRegistry>>,\n"
    "    runtime: Arc<AgentdPromptRuntimeOwner>,\n"
    "    exact: Arc<AgentdExactContextDeliveryOwner>,\n"
    "    security: Arc<ContextSecurityRuntimeV3>,\n"
    "}\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/prompt_runtime.rs",
    "        let exact_directory = runtime_directory.join(\"context-delivery-v2\");\n"
    "        let exact = AgentdExactContextDeliveryOwner::open(&exact_directory, Arc::clone(&registry))\n"
    "            .map_err(AgentdPromptPipelineError::ExactOpen)?;\n"
    "        Ok(Self {\n"
    "            registry,\n"
    "            runtime: Arc::new(runtime),\n"
    "            exact: Arc::new(exact),\n"
    "        })\n",
    "        let security = Arc::new(ContextSecurityRuntimeV3::new());\n"
    "        let exact_directory = runtime_directory.join(\"context-delivery-v2\");\n"
    "        let exact = AgentdExactContextDeliveryOwner::open(\n"
    "            &exact_directory,\n"
    "            Arc::clone(&registry),\n"
    "            Arc::clone(&security),\n"
    "        )\n"
    "        .map_err(AgentdPromptPipelineError::ExactOpen)?;\n"
    "        Ok(Self {\n"
    "            registry,\n"
    "            runtime: Arc::new(runtime),\n"
    "            exact: Arc::new(exact),\n"
    "            security,\n"
    "        })\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/prompt_runtime.rs",
    "    pub fn runtime_owner(&self) -> Arc<AgentdPromptRuntimeOwner> {\n"
    "        Arc::clone(&self.runtime)\n"
    "    }\n\n"
    "    pub fn host(&self) -> Result<PromptRuntimeHost, AgentdPromptPipelineError> {\n",
    "    pub fn runtime_owner(&self) -> Arc<AgentdPromptRuntimeOwner> {\n"
    "        Arc::clone(&self.runtime)\n"
    "    }\n\n"
    "    pub fn attach_context_security_capabilities_v3(\n"
    "        &self,\n"
    "        capabilities: Arc<ContextSecurityCapabilitiesV3>,\n"
    "    ) -> Result<(), AgentdPromptPipelineError> {\n"
    "        self.security\n"
    "            .attach(capabilities)\n"
    "            .map_err(AgentdPromptPipelineError::Security)\n"
    "    }\n\n"
    "    pub fn host(&self) -> Result<PromptRuntimeHost, AgentdPromptPipelineError> {\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/prompt_runtime.rs",
    "    pub fn compile_and_stage_v3<T: PromptExactTokenizerV3>(\n",
    "    pub async fn compile_and_stage_v3<T: PromptExactTokenizerV3>(\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/prompt_runtime.rs",
    "    ) -> Result<PromptRuntimeStageDisposition, AgentdPromptPipelineError> {\n"
    "        let compiled = {\n"
    "            let registry = self\n",
    "    ) -> Result<PromptRuntimeStageDisposition, AgentdPromptPipelineError> {\n"
    "        let observed_unix_ms = compilation_request.now_unix_ms;\n"
    "        let compiled = {\n"
    "            let registry = self\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/prompt_runtime.rs",
    "            .map_err(|error| AgentdPromptPipelineError::Compilation(error.to_string()))?\n"
    "        };\n"
    "        self.exact\n"
    "            .stage(thread_id, turn_id, compiled.clone())\n",
    "            .map_err(|error| AgentdPromptPipelineError::Compilation(error.to_string()))?\n"
    "        };\n"
    "        let capabilities = self\n"
    "            .security\n"
    "            .capabilities()\n"
    "            .map_err(AgentdPromptPipelineError::Security)?;\n"
    "        let external = capabilities\n"
    "            .authority_provider\n"
    "            .verify_snapshot(\n"
    "                compiled.authority_snapshot_for_external_verification(),\n"
    "                None,\n"
    "                observed_unix_ms,\n"
    "            )\n"
    "            .await\n"
    "            .map_err(AgentdPromptPipelineError::Security)?;\n"
    "        if external.snapshot().snapshot_digest() != compiled.authority_snapshot_digest()\n"
    "            || external.verification_digest().is_zero()\n"
    "        {\n"
    "            return Err(AgentdPromptPipelineError::Security(\n"
    "                ExternalContextSecurityErrorV3::AuthorityRejected,\n"
    "            ));\n"
    "        }\n"
    "        self.exact\n"
    "            .stage(thread_id, turn_id, compiled.clone())\n",
)

print("context.compiler external security composition materialized")
