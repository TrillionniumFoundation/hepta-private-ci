#!/usr/bin/env python3
"""Materialize the typed runtime.agentd shipping profile on the exact candidate."""

from pathlib import Path


def replace(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement, found {count}")
    file_path.write_text(text.replace(old, new))


Path("codex-rs/hepta-agentd/src/product_profile.rs").write_text(
    r'''//! Typed, all-or-none identity for the shipping Agentd product composition.
//!
//! The value owns every capability needed by the canonical execution path. It
//! cannot be deserialized from request bytes and is consumed exactly once when
//! the daemon starts. Compatibility embeddings may continue to call `run`, but
//! a `shipping-product` build refuses to start unless this profile was installed.

use codex_hepta_types::Digest32;

use crate::AgentdCanonicalRuntimeBootstrapV1;
use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdIdentity;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct AgentdProductCompositionIdentityV1 {
    pub(crate) profile_digest: Digest32,
    pub(crate) final_use_authority_digest: Digest32,
    pub(crate) neuron_owner_binding_digest: Digest32,
    pub(crate) production_writer_installed: bool,
}

/// Complete shipping composition selected by the trusted product host.
///
/// Construction binds the Agent/generation, final-use authority, durable Neuron
/// owner and writer posture into one immutable digest. Installation consumes the
/// bootstrap and records the same identity in `AgentdConfig` for readiness.
pub struct AgentdProductProfileV1 {
    config: AgentdConfig,
    bootstrap: AgentdCanonicalRuntimeBootstrapV1,
    composition: AgentdProductCompositionIdentityV1,
}

impl AgentdProductProfileV1 {
    #[must_use]
    pub fn new(config: AgentdConfig, bootstrap: AgentdCanonicalRuntimeBootstrapV1) -> Self {
        let final_use_authority_digest = bootstrap.final_use_authority_digest();
        let neuron_owner_binding_digest = bootstrap.neuron_owner_binding_digest();
        let production_writer_installed = config.production_writer_host().is_some();
        let generation = config.identity().spawn_generation.to_be_bytes();
        let writer = [u8::from(production_writer_installed)];
        let profile_digest = Digest32::of_parts(&[
            b"hepta.runtime-agentd.product-profile.v1\0",
            config.identity().agent_id.as_str().as_bytes(),
            &generation,
            final_use_authority_digest.as_array(),
            neuron_owner_binding_digest.as_array(),
            &writer,
        ]);
        Self {
            config,
            bootstrap,
            composition: AgentdProductCompositionIdentityV1 {
                profile_digest,
                final_use_authority_digest,
                neuron_owner_binding_digest,
                production_writer_installed,
            },
        }
    }

    #[must_use]
    pub fn identity(&self) -> &AgentdIdentity {
        self.config.identity()
    }

    #[must_use]
    pub const fn profile_digest(&self) -> Digest32 {
        self.composition.profile_digest
    }

    #[must_use]
    pub const fn final_use_authority_digest(&self) -> Digest32 {
        self.composition.final_use_authority_digest
    }

    #[must_use]
    pub const fn neuron_owner_binding_digest(&self) -> Digest32 {
        self.composition.neuron_owner_binding_digest
    }

    #[must_use]
    pub const fn production_writer_installed(&self) -> bool {
        self.composition.production_writer_installed
    }

    pub(crate) fn into_installed_config(self) -> Result<AgentdConfig, AgentdError> {
        self.bootstrap
            .install(self.config)?
            .with_product_composition_identity(self.composition)
    }
}
'''
)

Path("codex-rs/hepta-agentd/src/canonical_product_host.rs").write_text(
    r'''use codex_arg0::Arg0DispatchPaths;
use codex_hepta_types::Digest32;

use crate::AgentdCanonicalRuntimeBootstrapV1;
use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdProductProfileV1;

/// Sole product-level owner for one canonical Agentd process composition.
///
/// The host owns one complete typed profile. Starting the process consumes that
/// profile exactly once; no compatibility fallback or second runtime owner is
/// installed by this path.
pub struct AgentdCanonicalProductHostV1 {
    profile: AgentdProductProfileV1,
}

impl AgentdCanonicalProductHostV1 {
    #[must_use]
    pub fn new(config: AgentdConfig, bootstrap: AgentdCanonicalRuntimeBootstrapV1) -> Self {
        Self::from_profile(AgentdProductProfileV1::new(config, bootstrap))
    }

    #[must_use]
    pub const fn from_profile(profile: AgentdProductProfileV1) -> Self {
        Self { profile }
    }

    #[must_use]
    pub fn identity(&self) -> &AgentdIdentity {
        self.profile.identity()
    }

    #[must_use]
    pub const fn product_profile_digest(&self) -> Digest32 {
        self.profile.profile_digest()
    }

    pub async fn run(self, arg0_paths: Arg0DispatchPaths) -> Result<(), AgentdError> {
        let configured = self.profile.into_installed_config()?;
        crate::runtime::run(configured, arg0_paths).await
    }
}

pub async fn run_product_profile(
    profile: AgentdProductProfileV1,
    arg0_paths: Arg0DispatchPaths,
) -> Result<(), AgentdError> {
    AgentdCanonicalProductHostV1::from_profile(profile)
        .run(arg0_paths)
        .await
}

pub async fn run_canonical_product(
    config: AgentdConfig,
    bootstrap: AgentdCanonicalRuntimeBootstrapV1,
    arg0_paths: Arg0DispatchPaths,
) -> Result<(), AgentdError> {
    AgentdCanonicalProductHostV1::new(config, bootstrap)
        .run(arg0_paths)
        .await
}
'''
)

replace(
    "codex-rs/hepta-agentd/src/lib.rs",
    "mod production_writer_host;\nmod prompt_runtime;",
    "mod production_writer_host;\nmod product_profile;\nmod prompt_runtime;",
)
replace(
    "codex-rs/hepta-agentd/src/lib.rs",
    "pub use canonical_product_host::run_canonical_product;",
    "pub use canonical_product_host::run_canonical_product;\npub use canonical_product_host::run_product_profile;",
)
replace(
    "codex-rs/hepta-agentd/src/lib.rs",
    "pub use production_writer_host::AgentdProductionWriterHost;",
    "pub use production_writer_host::AgentdProductionWriterHost;\npub use product_profile::AgentdProductProfileV1;\npub(crate) use product_profile::AgentdProductCompositionIdentityV1;",
)
replace(
    "codex-rs/hepta-agentd/src/lib.rs",
    "pub use codex_hepta_agent_protocol::AgentdPayload;",
    "pub use codex_hepta_agent_protocol::AgentdPayload;\npub use codex_hepta_agent_protocol::AgentdProductCompositionSnapshotV1;",
)

replace(
    "codex-rs/hepta-agentd/src/config.rs",
    "    runtime_codex_supervisor: Option<crate::RuntimeCodexSupervisorHandleV1>,\n}",
    "    runtime_codex_supervisor: Option<crate::RuntimeCodexSupervisorHandleV1>,\n    product_composition_identity: Option<crate::AgentdProductCompositionIdentityV1>,\n}",
)
replace(
    "codex-rs/hepta-agentd/src/config.rs",
    "            runtime_codex_supervisor: None,\n        })",
    "            runtime_codex_supervisor: None,\n            product_composition_identity: None,\n        })",
)
replace(
    "codex-rs/hepta-agentd/src/config.rs",
    "    pub(crate) fn take_runtime_codex_supervisor(\n        &mut self,\n    ) -> Option<crate::RuntimeCodexSupervisorHandleV1> {\n        self.runtime_codex_supervisor.take()\n    }\n\n    /// Reject a partially requested canonical profile",
    "    pub(crate) fn take_runtime_codex_supervisor(\n        &mut self,\n    ) -> Option<crate::RuntimeCodexSupervisorHandleV1> {\n        self.runtime_codex_supervisor.take()\n    }\n\n    pub(crate) fn with_product_composition_identity(\n        mut self,\n        identity: crate::AgentdProductCompositionIdentityV1,\n    ) -> Result<Self, AgentdError> {\n        if self.product_composition_identity.is_some()\n            || identity.profile_digest.is_zero()\n            || identity.final_use_authority_digest.is_zero()\n            || identity.neuron_owner_binding_digest.is_zero()\n        {\n            return Err(AgentdError::Invalid(\n                \"invalid or duplicate Agentd product composition identity\".to_string(),\n            ));\n        }\n        self.product_composition_identity = Some(identity);\n        Ok(self)\n    }\n\n    pub(crate) fn product_composition_identity(\n        &self,\n    ) -> Option<crate::AgentdProductCompositionIdentityV1> {\n        self.product_composition_identity.clone()\n    }\n\n    /// Reject a partially requested canonical profile",
)

replace(
    "codex-rs/hepta-agent-protocol/src/lib.rs",
    "#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]\n#[serde(deny_unknown_fields)]\npub struct ReadinessSnapshot {\n    pub critical_stores_ready: bool,\n    pub revocation_ready: bool,\n    pub required_ports_ready: bool,\n    pub admission_open: bool,\n}",
    "#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]\n#[serde(deny_unknown_fields)]\npub struct AgentdProductCompositionSnapshotV1 {\n    pub schema_version: u32,\n    pub profile_digest: String,\n    pub final_use_authority_digest: String,\n    pub neuron_owner_binding_digest: String,\n    pub intelligence_runner_installed: bool,\n    pub invocation_provider_installed: bool,\n    pub production_writer_installed: bool,\n    pub runtime_codex_supervisor_installed: bool,\n}\n\n#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]\n#[serde(deny_unknown_fields)]\npub struct ReadinessSnapshot {\n    pub critical_stores_ready: bool,\n    pub revocation_ready: bool,\n    pub required_ports_ready: bool,\n    pub admission_open: bool,\n    #[serde(default, skip_serializing_if = \"Option::is_none\")]\n    pub product_composition: Option<AgentdProductCompositionSnapshotV1>,\n}",
)

replace(
    "codex-rs/hepta-agentd/src/state.rs",
    "    runtime_codex: std::sync::OnceLock<RuntimeCodexSupervisorHandleV1>,\n    plasticity_runtime:",
    "    runtime_codex: std::sync::OnceLock<RuntimeCodexSupervisorHandleV1>,\n    product_composition: Option<crate::AgentdProductCompositionIdentityV1>,\n    plasticity_runtime:",
)
replace(
    "codex-rs/hepta-agentd/src/state.rs",
    "        Self::new_with_prompt_registry_recovery(identity, registry, event_capacity, None)\n    }\n\n    pub(crate) fn new_with_prompt_registry_recovery(\n        identity: AgentdIdentity,\n        registry: FleetRegistry,\n        event_capacity: usize,\n        prompt_registry_recovery_checkpoint: Option<&Path>,\n    ) -> Result<Self, AgentdError> {",
    "        Self::new_with_product_composition(\n            identity,\n            registry,\n            event_capacity,\n            None,\n            None,\n        )\n    }\n\n    pub(crate) fn new_with_prompt_registry_recovery(\n        identity: AgentdIdentity,\n        registry: FleetRegistry,\n        event_capacity: usize,\n        prompt_registry_recovery_checkpoint: Option<&Path>,\n    ) -> Result<Self, AgentdError> {\n        Self::new_with_product_composition(\n            identity,\n            registry,\n            event_capacity,\n            prompt_registry_recovery_checkpoint,\n            None,\n        )\n    }\n\n    pub(crate) fn new_with_product_composition(\n        identity: AgentdIdentity,\n        registry: FleetRegistry,\n        event_capacity: usize,\n        prompt_registry_recovery_checkpoint: Option<&Path>,\n        product_composition: Option<crate::AgentdProductCompositionIdentityV1>,\n    ) -> Result<Self, AgentdError> {",
)
replace(
    "codex-rs/hepta-agentd/src/state.rs",
    "            runtime_codex: std::sync::OnceLock::new(),\n            cognitive_ranker:",
    "            runtime_codex: std::sync::OnceLock::new(),\n            product_composition,\n            cognitive_ranker:",
)

replace(
    "codex-rs/hepta-agentd/src/runtime.rs",
    "    config.require_intelligence_composition()?;\n    let production_operations",
    "    config.require_intelligence_composition()?;\n    let product_composition = config.product_composition_identity();\n    #[cfg(feature = \"shipping-product\")]\n    if product_composition.is_none() {\n        return Err(AgentdError::Invalid(\n            \"shipping-product Agentd requires AgentdProductProfileV1; compatibility fallback is disabled\".to_string(),\n        ));\n    }\n    let production_operations",
)
replace(
    "codex-rs/hepta-agentd/src/runtime.rs",
    "    let state = Arc::new(AgentdState::new_with_prompt_registry_recovery(\n        identity.clone(),\n        registry,\n        EVENT_CAPACITY,\n        prompt_registry_recovery_checkpoint.as_deref(),\n    )?);",
    "    let state = Arc::new(AgentdState::new_with_product_composition(\n        identity.clone(),\n        registry,\n        EVENT_CAPACITY,\n        prompt_registry_recovery_checkpoint.as_deref(),\n        product_composition,\n    )?);",
)

replace(
    "codex-rs/hepta-agentd/src/state_control.rs",
    "            crate::AgentdMethod::Readiness => AgentdPayload::Readiness(crate::ReadinessSnapshot {\n                critical_stores_ready,\n                revocation_ready,\n                required_ports_ready,\n                admission_open,\n            }),",
    "            crate::AgentdMethod::Readiness => AgentdPayload::Readiness(crate::ReadinessSnapshot {\n                critical_stores_ready,\n                revocation_ready,\n                required_ports_ready,\n                admission_open,\n                product_composition: self.product_composition.as_ref().map(|composition| {\n                    crate::AgentdProductCompositionSnapshotV1 {\n                        schema_version: 1,\n                        profile_digest: composition.profile_digest.to_string(),\n                        final_use_authority_digest: composition\n                            .final_use_authority_digest\n                            .to_string(),\n                        neuron_owner_binding_digest: composition\n                            .neuron_owner_binding_digest\n                            .to_string(),\n                        intelligence_runner_installed: self.intelligence_product.get().is_some(),\n                        invocation_provider_installed: self\n                            .intelligence_invocation\n                            .get()\n                            .is_some(),\n                        production_writer_installed: composition.production_writer_installed,\n                        runtime_codex_supervisor_installed: self.runtime_codex_snapshot()?.is_some(),\n                    }\n                }),\n            }),",
)

replace(
    "codex-rs/hepta-agentd/Cargo.toml",
    "production-cognitive-write = []\n# Adds the qualification-only",
    "production-cognitive-write = []\n# Shipping compositions must enter through AgentdProductProfileV1 and may not\n# fall back to the compatibility daemon path.\nshipping-product = [\"production-cognitive-write\"]\n# Adds the qualification-only",
)
