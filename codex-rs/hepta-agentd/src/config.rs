use std::ffi::OsString;
use std::fs::File;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::FleetRegistry;

use crate::AgentdError;

pub const HEPTA_AGENT_ID_ENV: &str = "HEPTA_AGENT_ID";
pub const HEPTA_AGENT_GENERATION_ENV: &str = "HEPTA_AGENT_GENERATION";
pub const HEPTA_AGENT_HOME_ENV: &str = "HEPTA_AGENT_HOME";
pub const HEPTA_AGENT_RUN_ROOT_ENV: &str = "HEPTA_AGENT_RUN_ROOT";
pub const HEPTA_COGNITIVE_RETRIEVAL_MODE_ENV: &str = "HEPTA_COGNITIVE_RETRIEVAL_MODE";

pub use codex_hepta_authority_types::AgentdIdentity;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CognitiveRetrievalMode {
    Compatibility,
    HnmfRequired,
}

impl CognitiveRetrievalMode {
    #[must_use]
    pub const fn requires_current_context(self) -> bool {
        matches!(self, Self::HnmfRequired)
    }
}

fn parse_cognitive_retrieval_mode(
    value: Option<OsString>,
) -> Result<CognitiveRetrievalMode, AgentdError> {
    let Some(value) = value.filter(|value| !value.is_empty()) else {
        return Ok(CognitiveRetrievalMode::Compatibility);
    };
    let value = value.into_string().map_err(|_| {
        AgentdError::Invalid(format!(
            "{HEPTA_COGNITIVE_RETRIEVAL_MODE_ENV} must be UTF-8"
        ))
    })?;
    match value.as_str() {
        "compatibility" => Ok(CognitiveRetrievalMode::Compatibility),
        "hnmf-required" => Ok(CognitiveRetrievalMode::HnmfRequired),
        _ => Err(AgentdError::Invalid(format!(
            "{HEPTA_COGNITIVE_RETRIEVAL_MODE_ENV} must be compatibility or hnmf-required"
        ))),
    }
}

fn cognitive_retrieval_mode_from_process_environment() -> Result<CognitiveRetrievalMode, AgentdError>
{
    parse_cognitive_retrieval_mode(std::env::var_os(HEPTA_COGNITIVE_RETRIEVAL_MODE_ENV))
}

pub struct AgentdConfig {
    identity: AgentdIdentity,
    registry: FleetRegistry,
    _writer_lock: File,
    authbus_trust_file: Option<PathBuf>,
    evidence_trust_file: Option<PathBuf>,
    automation_effect_host_file: Option<PathBuf>,
    evidence_recovery_frontier_file: Option<PathBuf>,
    evidence_recovery_frontier_trust_file: Option<PathBuf>,
    objective_profile_file: Option<PathBuf>,
    authbus_checkpoint_file: Option<PathBuf>,
    cognitive_ranker: Option<std::sync::Arc<crate::PinnedCognitiveRanker>>,
    production_operations: Option<crate::AgentdProductionOperationRuntimeConfig>,
    production_writer_host: Option<std::sync::Arc<crate::AgentdProductionWriterHost>>,
    notes_objective: Option<crate::AgentdNotesObjectiveConfig>,
    cognitive_retrieval_mode: CognitiveRetrievalMode,
    cognitive_retrieval_context: Option<std::sync::Arc<dyn crate::CurrentMemoryRetrievalContext>>,
    cognitive_retrieval_learning: Option<std::sync::Arc<crate::CognitiveRetrievalLearningSink>>,
    plasticity_bootstrap: Option<crate::PlasticityRuntimeBootstrapV1>,
    intuition_policy_host: Option<std::sync::Arc<crate::AgentdIntuitionPolicyHostV1>>,
    intelligence_product_runner: Option<std::sync::Arc<crate::AgentdIntelligenceProductRunnerV1>>,
    intelligence_invocation_provider:
        Option<std::sync::Arc<dyn crate::AgentdIntelligenceInvocationProviderV1>>,
}

impl AgentdConfig {
    pub fn from_process_environment() -> Result<Self, AgentdError> {
        let cognitive_retrieval_mode = cognitive_retrieval_mode_from_process_environment()?;
        let process = crate::process_config::ValidatedProcessConfig::from_process_environment()?;
        Ok(Self::from_validated_process(process)
            .with_cognitive_retrieval_mode(cognitive_retrieval_mode))
    }

    #[allow(clippy::too_many_arguments)]
    pub fn load(
        fleet_root: PathBuf,
        agent_id: AgentId,
        spawn_generation: u64,
        home_root: PathBuf,
        run_root: PathBuf,
        codex_home: PathBuf,
        current_dir: PathBuf,
    ) -> Result<Self, AgentdError> {
        let process = crate::process_config::ValidatedProcessConfig::load(
            fleet_root,
            agent_id,
            spawn_generation,
            home_root,
            run_root,
            codex_home,
            current_dir,
        )?;
        Ok(Self::from_validated_process(process))
    }

    fn from_validated_process(process: crate::process_config::ValidatedProcessConfig) -> Self {
        let (identity, registry, writer_lock) = process.into_parts();
        Self {
            identity,
            registry,
            _writer_lock: writer_lock,
            authbus_trust_file: None,
            evidence_trust_file: None,
            automation_effect_host_file: None,
            evidence_recovery_frontier_file: None,
            evidence_recovery_frontier_trust_file: None,
            objective_profile_file: None,
            authbus_checkpoint_file: None,
            cognitive_ranker: None,
            production_operations: None,
            production_writer_host: None,
            notes_objective: None,
            cognitive_retrieval_mode: CognitiveRetrievalMode::Compatibility,
            cognitive_retrieval_context: None,
            cognitive_retrieval_learning: None,
            plasticity_bootstrap: None,
            intuition_policy_host: None,
            intelligence_product_runner: None,
            intelligence_invocation_provider: None,
        }
    }

    /// Explicit owner-managed public-key/route registry. No file is generated
    /// or trusted implicitly; the runtime validates and reloads it before use.
    pub fn with_authbus_trust_file(mut self, path: PathBuf) -> Self {
        self.authbus_trust_file = Some(path);
        self
    }

    pub(crate) fn authbus_trust_file(&self) -> Option<&Path> {
        self.authbus_trust_file.as_deref()
    }

    /// Explicit multi-issuer role registry for kernel.evidence product ingress.
    /// The file is owner-controlled and revalidated at each append boundary.
    pub fn with_evidence_trust_file(mut self, path: PathBuf) -> Self {
        self.evidence_trust_file = Some(path);
        self
    }

    pub(crate) fn evidence_trust_file(&self) -> Option<&Path> {
        self.evidence_trust_file.as_deref()
    }

    /// Optional restore/startup gate backed by a signed frontier and a signer
    /// trust file from outside the Agent home rollback domain. Both files are
    /// required together.
    pub fn with_evidence_recovery_frontier_files(
        mut self,
        frontier_file: PathBuf,
        signer_trust_file: PathBuf,
    ) -> Self {
        self.evidence_recovery_frontier_file = Some(frontier_file);
        self.evidence_recovery_frontier_trust_file = Some(signer_trust_file);
        self
    }

    pub(crate) fn evidence_recovery_frontier_files(&self) -> Option<(&Path, &Path)> {
        match (
            self.evidence_recovery_frontier_file.as_deref(),
            self.evidence_recovery_frontier_trust_file.as_deref(),
        ) {
            (Some(frontier), Some(trust)) => Some((frontier, trust)),
            _ => None,
        }
    }

    /// Attach one protected provider/final-use configuration, fixed at startup.
    pub fn with_automation_effect_host_file(mut self, path: PathBuf) -> Self {
        self.automation_effect_host_file = Some(path);
        self
    }

    pub(crate) fn automation_effect_host_file(&self) -> Option<&Path> {
        self.automation_effect_host_file.as_deref()
    }

    /// Explicit owner-managed objective admission profile. A request cannot
    /// select or replace this file; changing it requires a new process generation.
    pub fn with_objective_profile_file(mut self, path: PathBuf) -> Self {
        self.objective_profile_file = Some(path);
        self
    }

    pub(crate) fn objective_profile_file(&self) -> Option<&Path> {
        self.objective_profile_file.as_deref()
    }

    /// Independently retained replay witness. Production signed ingress requires
    /// this alongside the trust file; it must live outside the Agent home.
    pub fn with_authbus_checkpoint_file(mut self, path: PathBuf) -> Self {
        self.authbus_checkpoint_file = Some(path);
        self
    }

    pub(crate) fn authbus_checkpoint_file(&self) -> Option<&Path> {
        self.authbus_checkpoint_file.as_deref()
    }

    /// Attach an explicitly selected, read-only learned consumer. The host must
    /// authenticate the selection and current revocation witness independently.
    /// No CLI/environment default manufactures an evaluator or selection.
    pub fn with_cognitive_ranker(
        mut self,
        ranker: std::sync::Arc<crate::PinnedCognitiveRanker>,
    ) -> Result<Self, AgentdError> {
        ranker
            .require_identity(&self.identity.agent_id, self.identity.spawn_generation)
            .map_err(AgentdError::Invalid)?;
        if self.cognitive_ranker.is_some() {
            return Err(AgentdError::Invalid(
                "cognitive ranker already configured".to_string(),
            ));
        }
        self.cognitive_ranker = Some(ranker);
        Ok(self)
    }

    pub(crate) fn cognitive_ranker(&self) -> Option<std::sync::Arc<crate::PinnedCognitiveRanker>> {
        self.cognitive_ranker.clone()
    }

    #[cfg(target_os = "linux")]
    pub(crate) fn require_unconfigured_production_hosts(&self) -> Result<(), AgentdError> {
        if self.production_writer_host.is_some() || self.production_operations.is_some() {
            return Err(AgentdError::Invalid(
                "production host is already configured".to_string(),
            ));
        }
        Ok(())
    }

    #[cfg(target_os = "linux")]
    pub(crate) fn install_production_hosts(
        &mut self,
        host: std::sync::Arc<crate::AgentdProductionWriterHost>,
        operations: crate::AgentdProductionOperationRuntimeConfig,
    ) -> Result<(), AgentdError> {
        self.require_unconfigured_production_hosts()?;
        operations.validate_for(self)?;
        let writer = host.writer();
        if writer.owner_agent_id() != &self.identity.agent_id
            || host.spawn_generation() != self.identity.spawn_generation
            || writer.authority() != &operations.authority
            || writer.lease_id() != operations.lease_id
            || writer.generation() != operations.lease_generation
        {
            return Err(AgentdError::GenerationFenced(
                "production recovered writer identity differs from Agentd".to_string(),
            ));
        }
        // After every metadata callback and recovery await, recheck the same
        // live verifier immediately before publishing either handle.
        operations
            .verifier
            .verify(&operations.authority, &self.identity.agent_id)
            .map_err(AgentdError::GenerationFenced)?;
        // No fallible operation follows either assignment. The caller has
        // revalidated this same original owner before this exclusive commit.
        self.production_writer_host = Some(host);
        self.production_operations = Some(operations);
        Ok(())
    }

    /// Attach an externally-authorized long-lived production operation host.
    /// Default process-environment startup never manufactures or loads this
    /// authority; an embedding must provide the complete verified runtime
    /// configuration explicitly.
    pub fn with_production_operations(
        mut self,
        operations: crate::AgentdProductionOperationRuntimeConfig,
    ) -> Result<Self, AgentdError> {
        operations.validate_for(&self)?;
        if self.production_operations.is_some() {
            return Err(AgentdError::Invalid(
                "production operation runtime already configured".to_string(),
            ));
        }
        self.production_operations = Some(operations);
        Ok(self)
    }

    pub(crate) fn take_production_operations(
        &mut self,
    ) -> Option<crate::AgentdProductionOperationRuntimeConfig> {
        self.production_operations.take()
    }

    /// Attach an externally verified production cognitive writer to normal
    /// Agentd composition. Agentd never manufactures this authority.
    pub fn with_production_writer_host(
        mut self,
        host: std::sync::Arc<crate::AgentdProductionWriterHost>,
    ) -> Result<Self, AgentdError> {
        if self.production_writer_host.is_some() {
            return Err(AgentdError::Invalid(
                "production cognitive writer host already configured".to_string(),
            ));
        }
        crate::process_config::validate_production_writer_host(&self.identity, &host)?;
        self.production_writer_host = Some(host);
        Ok(self)
    }

    pub(crate) fn production_writer_host(
        &self,
    ) -> Option<std::sync::Arc<crate::AgentdProductionWriterHost>> {
        self.production_writer_host.clone()
    }

    /// Select the retrieval product profile explicitly. Compatibility preserves
    /// the legacy owner-ranked path. HnmfRequired forbids startup without a
    /// current authenticated retrieval context and never silently falls back.
    pub fn with_cognitive_retrieval_mode(mut self, mode: CognitiveRetrievalMode) -> Self {
        self.cognitive_retrieval_mode = mode;
        self
    }

    pub(crate) fn cognitive_retrieval_mode(&self) -> CognitiveRetrievalMode {
        self.cognitive_retrieval_mode
    }

    /// Attach an authenticated external-generation/engram currentness source.
    /// The ordinary CLI never manufactures one. Once attached, any currentness
    /// failure closes HNMF retrieval instead of falling back to an older view.
    pub fn with_cognitive_retrieval_context(
        mut self,
        current: std::sync::Arc<dyn crate::CurrentMemoryRetrievalContext>,
    ) -> Result<Self, AgentdError> {
        if self.cognitive_retrieval_context.is_some() {
            return Err(AgentdError::Invalid(
                "cognitive retrieval context already configured".to_string(),
            ));
        }
        let context = current
            .current(&self.identity.agent_id, self.identity.spawn_generation)
            .map_err(AgentdError::Invalid)?;
        context
            .validate()
            .map_err(|error| AgentdError::Invalid(error.to_string()))?;
        self.cognitive_retrieval_context = Some(current);
        Ok(self)
    }

    pub(crate) fn cognitive_retrieval_context(
        &self,
    ) -> Option<std::sync::Arc<dyn crate::CurrentMemoryRetrievalContext>> {
        self.cognitive_retrieval_context.clone()
    }

    /// Attach the actual durable learning-ledger sink for HNMF assignment
    /// evidence. The retrieval currentness provider must already be configured;
    /// Agentd never records generator-relative assignments on the compatibility
    /// path that lacks a frozen HNMF generation.
    pub fn with_cognitive_retrieval_learning(
        mut self,
        sink: std::sync::Arc<crate::CognitiveRetrievalLearningSink>,
    ) -> Result<Self, AgentdError> {
        if self.cognitive_retrieval_context.is_none() {
            return Err(AgentdError::Invalid(
                "retrieval learning requires a configured current retrieval context".to_string(),
            ));
        }
        if self.cognitive_retrieval_learning.is_some() {
            return Err(AgentdError::Invalid(
                "cognitive retrieval learning sink already configured".to_string(),
            ));
        }
        self.cognitive_retrieval_learning = Some(sink);
        Ok(self)
    }

    pub(crate) fn cognitive_retrieval_learning(
        &self,
    ) -> Option<std::sync::Arc<crate::CognitiveRetrievalLearningSink>> {
        self.cognitive_retrieval_learning.clone()
    }

    /// Attach one explicitly constructed governed plasticity bootstrap envelope.
    /// Agentd itself consumes the envelope, creates the bounded channel, retains
    /// the sole mutable owner and stores the producer handle in daemon state.
    /// There is no ambient/default plasticity writer.
    pub fn with_plasticity_runtime_bootstrap(
        mut self,
        bootstrap: crate::PlasticityRuntimeBootstrapV1,
    ) -> Result<Self, AgentdError> {
        if self.plasticity_bootstrap.is_some() {
            return Err(AgentdError::Invalid(
                "plasticity runtime bootstrap already configured".to_string(),
            ));
        }
        self.plasticity_bootstrap = Some(bootstrap);
        Ok(self)
    }

    pub(crate) fn take_plasticity_runtime_bootstrap(
        &mut self,
    ) -> Option<crate::PlasticityRuntimeBootstrapV1> {
        self.plasticity_bootstrap.take()
    }

    /// Attach the authenticated current intuition-policy product caller.
    /// The caller is pinned to this exact Agentd identity/generation and owns
    /// no model, scorer, RNG or learning facts itself.
    pub fn with_intuition_policy_host(
        mut self,
        host: std::sync::Arc<crate::AgentdIntuitionPolicyHostV1>,
    ) -> Result<Self, AgentdError> {
        host.require_identity(&self.identity.agent_id, self.identity.spawn_generation)
            .map_err(|error| AgentdError::Invalid(error.to_string()))?;
        if self.intuition_policy_host.is_some() {
            return Err(AgentdError::Invalid(
                "intuition policy host already configured".to_string(),
            ));
        }
        self.intuition_policy_host = Some(host);
        Ok(self)
    }

    pub(crate) fn intuition_policy_host(
        &self,
    ) -> Option<std::sync::Arc<crate::AgentdIntuitionPolicyHostV1>> {
        self.intuition_policy_host.clone()
    }

    /// Compose the canonical intelligence product caller into this daemon.
    /// No authority file, signer identity, or verifying key is inferred.
    pub fn with_intelligence_product_runner(
        mut self,
        runner: std::sync::Arc<crate::AgentdIntelligenceProductRunnerV1>,
    ) -> Result<Self, AgentdError> {
        if self.intelligence_product_runner.is_some() {
            return Err(AgentdError::Invalid(
                "intelligence product runner already configured".to_string(),
            ));
        }
        self.intelligence_product_runner = Some(runner);
        Ok(self)
    }

    pub(crate) fn intelligence_product_runner(
        &self,
    ) -> Option<std::sync::Arc<crate::AgentdIntelligenceProductRunnerV1>> {
        self.intelligence_product_runner.clone()
    }

    /// Attach the host-owned provider that derives seven-owner inputs for the
    /// existing ObjectiveStart product ingress.  The provider is never
    /// constructed from request bytes.
    pub fn with_intelligence_invocation_provider(
        mut self,
        provider: std::sync::Arc<dyn crate::AgentdIntelligenceInvocationProviderV1>,
    ) -> Result<Self, AgentdError> {
        if self.intelligence_invocation_provider.is_some() {
            return Err(AgentdError::Invalid(
                "intelligence invocation provider already configured".to_string(),
            ));
        }
        self.intelligence_invocation_provider = Some(provider);
        Ok(self)
    }

    pub(crate) fn intelligence_invocation_provider(
        &self,
    ) -> Option<std::sync::Arc<dyn crate::AgentdIntelligenceInvocationProviderV1>> {
        self.intelligence_invocation_provider.clone()
    }

    /// Opt in to one frozen literal Notes profile; no general AI executor.
    pub fn with_notes_objective(
        mut self,
        config: crate::AgentdNotesObjectiveConfig,
    ) -> Result<Self, AgentdError> {
        config.validate()?;
        if self.notes_objective.is_some() {
            return Err(AgentdError::Invalid(
                "Notes Objective adapter already configured".into(),
            ));
        }
        self.notes_objective = Some(config);
        Ok(self)
    }

    #[cfg(target_os = "linux")]
    pub(crate) fn require_finite_notes_profile(&self) -> Result<(), AgentdError> {
        if self.production_writer_host.is_none()
            || self.notes_objective.is_none()
            || self.authbus_trust_file.is_none()
            || self.authbus_checkpoint_file.is_none()
            || self.objective_profile_file.is_none()
            || self.production_operations.is_some()
            || self.evidence_trust_file.is_some()
            || self.evidence_recovery_frontier_file.is_some()
            || self.evidence_recovery_frontier_trust_file.is_some()
            || self.automation_effect_host_file.is_some()
            || self.cognitive_ranker.is_some()
            || self.cognitive_retrieval_mode != CognitiveRetrievalMode::Compatibility
            || self.cognitive_retrieval_context.is_some()
            || self.cognitive_retrieval_learning.is_some()
            || self.plasticity_bootstrap.is_some()
            || self.intuition_policy_host.is_some()
            || self.intelligence_product_runner.is_some()
            || self.intelligence_invocation_provider.is_some()
        {
            return Err(AgentdError::Invalid(
                "finite Notes profile requires its original writer, Notes, AuthBus and admission owners without another execution plane".into(),
            ));
        }
        Ok(())
    }

    #[cfg(target_os = "linux")]
    pub(crate) fn require_finite_native_cpu_profile(&self) -> Result<(), AgentdError> {
        if self.production_writer_host.is_none()
            || self.notes_objective.is_some()
            || self.authbus_trust_file.is_some()
            || self.authbus_checkpoint_file.is_some()
            || self.objective_profile_file.is_some()
            || self.production_operations.is_some()
            || self.evidence_trust_file.is_some()
            || self.evidence_recovery_frontier_file.is_some()
            || self.evidence_recovery_frontier_trust_file.is_some()
            || self.automation_effect_host_file.is_some()
            || self.cognitive_ranker.is_some()
            || self.cognitive_retrieval_mode != CognitiveRetrievalMode::Compatibility
            || self.cognitive_retrieval_context.is_some()
            || self.cognitive_retrieval_learning.is_some()
            || self.plasticity_bootstrap.is_some()
            || self.intuition_policy_host.is_some()
            || self.intelligence_product_runner.is_some()
            || self.intelligence_invocation_provider.is_some()
        {
            return Err(AgentdError::Invalid("native CPU profile requires its one original recovered writer and fixed CPU execution path".into()));
        }
        Ok(())
    }

    pub(crate) fn notes_objective(&self) -> Option<crate::AgentdNotesObjectiveConfig> {
        self.notes_objective.clone()
    }

    pub fn identity(&self) -> &AgentdIdentity {
        &self.identity
    }

    pub(crate) fn into_parts(self) -> (AgentdIdentity, FleetRegistry, File) {
        (self.identity, self.registry, self._writer_lock)
    }
}

/// Internal native composition of the same validated process and recovered
/// writer. This type cannot carry an App Server, Prompt or other execution
/// owner, and is never constructed by converting a full Agentd configuration.
#[cfg(target_os = "linux")]
pub(crate) struct NativeCpuConfig {
    process: crate::process_config::ValidatedProcessConfig,
    production_writer_host: Option<std::sync::Arc<crate::AgentdProductionWriterHost>>,
}

#[cfg(target_os = "linux")]
impl NativeCpuConfig {
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn load(
        fleet_root: PathBuf,
        agent_id: AgentId,
        spawn_generation: u64,
        home_root: PathBuf,
        run_root: PathBuf,
        codex_home: PathBuf,
        current_dir: PathBuf,
    ) -> Result<Self, AgentdError> {
        Ok(Self {
            process: crate::process_config::ValidatedProcessConfig::load(
                fleet_root,
                agent_id,
                spawn_generation,
                home_root,
                run_root,
                codex_home,
                current_dir,
            )?,
            production_writer_host: None,
        })
    }

    pub(crate) fn identity(&self) -> &AgentdIdentity {
        self.process.identity()
    }

    pub(crate) fn with_production_writer_host(
        mut self,
        host: std::sync::Arc<crate::AgentdProductionWriterHost>,
    ) -> Result<Self, AgentdError> {
        if self.production_writer_host.is_some() {
            return Err(AgentdError::Invalid(
                "production cognitive writer host already configured".to_string(),
            ));
        }
        crate::process_config::validate_production_writer_host(self.identity(), &host)?;
        self.production_writer_host = Some(host);
        Ok(self)
    }

    pub(crate) fn production_writer_host(
        &self,
    ) -> Option<std::sync::Arc<crate::AgentdProductionWriterHost>> {
        self.production_writer_host.clone()
    }

    pub(crate) fn original_objective_sender<C: codex_hepta_memory::ObjectiveSenderCheckpoint>(
        &self,
        checkpoint: std::sync::Arc<C>,
        deadline: std::time::Duration,
    ) -> Result<codex_hepta_memory::ProductionObjectiveSender<C>, AgentdError> {
        crate::process_config::original_objective_sender(
            self.identity(),
            self.production_writer_host(),
            checkpoint,
            deadline,
        )
    }

    pub(crate) fn require_finite_native_cpu_profile(&self) -> Result<(), AgentdError> {
        // All other execution owners are absent from this type. A recovered
        // writer is still mandatory and uses the same attachment validation.
        if self.production_writer_host.is_none() {
            return Err(AgentdError::Invalid("native CPU profile requires its one original recovered writer and fixed CPU execution path".into()));
        }
        Ok(())
    }

    pub(crate) fn into_parts(self) -> (AgentdIdentity, FleetRegistry, File) {
        self.process.into_parts()
    }
}

#[cfg(test)]
#[path = "config_tests.rs"]
mod tests;

#[cfg(all(test, target_os = "linux"))]
#[path = "native_cpu_config_tests.rs"]
mod native_cpu_tests;
