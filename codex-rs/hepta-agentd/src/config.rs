use std::ffi::OsString;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;

use crate::AgentdError;

pub const HEPTA_AGENT_ID_ENV: &str = "HEPTA_AGENT_ID";
pub const HEPTA_AGENT_GENERATION_ENV: &str = "HEPTA_AGENT_GENERATION";
pub const HEPTA_AGENT_HOME_ENV: &str = "HEPTA_AGENT_HOME";
pub const HEPTA_AGENT_RUN_ROOT_ENV: &str = "HEPTA_AGENT_RUN_ROOT";
pub const HEPTA_COGNITIVE_RETRIEVAL_MODE_ENV: &str = "HEPTA_COGNITIVE_RETRIEVAL_MODE";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIdentity {
    pub agent_id: AgentId,
    pub layout: HeptaAgentLayout,
    pub spawn_generation: u64,
    pub fleet_root: PathBuf,
    pub workspace: PathBuf,
    pub resources: ResourceBudget,
    pub home_root: PathBuf,
    pub run_root: PathBuf,
    pub control_socket: PathBuf,
    pub app_server_socket: PathBuf,
}

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
    objective_checkpoint_file: Option<PathBuf>,
    authbus_checkpoint_file: Option<PathBuf>,
    cognitive_ranker: Option<std::sync::Arc<crate::PinnedCognitiveRanker>>,
    production_operations: Option<crate::AgentdProductionOperationRuntimeConfig>,
    production_writer_host: Option<std::sync::Arc<crate::AgentdProductionWriterHost>>,
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
        let fleet_root = required_path(codex_hepta_paths::HEPTA_FLEET_ROOT_ENV)?;
        let agent_id = required_utf8(HEPTA_AGENT_ID_ENV)?;
        let spawn_generation = required_utf8(HEPTA_AGENT_GENERATION_ENV)?
            .parse::<u64>()
            .map_err(|_| {
                AgentdError::Invalid(format!(
                    "{HEPTA_AGENT_GENERATION_ENV} must be an unsigned integer"
                ))
            })?;
        let home_root = required_path(HEPTA_AGENT_HOME_ENV)?;
        let run_root = required_path(HEPTA_AGENT_RUN_ROOT_ENV)?;
        let codex_home = required_path("CODEX_HOME")?;
        let current_dir = std::env::current_dir()?;
        Self::load(
            fleet_root,
            AgentId::parse(agent_id).map_err(|error| AgentdError::Invalid(error.to_string()))?,
            spawn_generation,
            home_root,
            run_root,
            codex_home,
            current_dir,
        )
        .map(|config| config.with_cognitive_retrieval_mode(cognitive_retrieval_mode))
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
        if spawn_generation == 0 {
            return Err(AgentdError::Invalid(
                "spawn generation must be non-zero".to_string(),
            ));
        }
        let typed_fleet_root = HeptaFleetRoot::parse(fleet_root.clone())
            .map_err(|error| AgentdError::Invalid(error.to_string()))?;
        require_canonical(&fleet_root, "fleet root")?;
        let registry = FleetRegistry::open_existing(typed_fleet_root)?;
        let record = registry
            .load()?
            .agent(&agent_id)
            .cloned()
            .ok_or_else(|| AgentdError::Invalid(format!("unknown fleet agent {agent_id}")))?;

        if record.lifecycle.lifecycle != AgentLifecycle::Starting
            || record.lifecycle.generation != spawn_generation
        {
            return Err(AgentdError::GenerationFenced(format!(
                "agent {agent_id} expected Starting generation {spawn_generation}, found {:?} generation {}",
                record.lifecycle.lifecycle, record.lifecycle.generation
            )));
        }
        require_exact_path(&home_root, record.layout.home_root(), "agent home")?;
        require_exact_path(&run_root, record.layout.run_root(), "agent run root")?;
        require_exact_path(&codex_home, record.layout.home_root(), "Codex home")?;
        let workspace = current_dir.canonicalize()?;
        if workspace != record.manifest.workspace.as_path() {
            return Err(AgentdError::Invalid(format!(
                "process workspace {} does not match manifest {}",
                workspace.display(),
                record.manifest.workspace.as_path().display()
            )));
        }

        let writer_lock = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(record.layout.writer_lock())?;
        writer_lock.try_lock().map_err(|error| {
            AgentdError::Invalid(format!(
                "agent {agent_id} already has a live writer lock: {error}"
            ))
        })?;
        let layout = record.layout;
        let control_socket = layout.agentd_control_socket().to_path_buf();
        let app_server_socket = layout.app_server_socket().to_path_buf();

        Ok(Self {
            identity: AgentdIdentity {
                agent_id,
                layout,
                spawn_generation,
                fleet_root,
                workspace,
                resources: record.manifest.resources,
                home_root,
                run_root,
                control_socket,
                app_server_socket,
            },
            registry,
            _writer_lock: writer_lock,
            authbus_trust_file: None,
            evidence_trust_file: None,
            automation_effect_host_file: None,
            evidence_recovery_frontier_file: None,
            evidence_recovery_frontier_trust_file: None,
            objective_profile_file: None,
            objective_checkpoint_file: None,
            authbus_checkpoint_file: None,
            cognitive_ranker: None,
            production_operations: None,
            production_writer_host: None,
            cognitive_retrieval_mode: CognitiveRetrievalMode::Compatibility,
            cognitive_retrieval_context: None,
            cognitive_retrieval_learning: None,
            plasticity_bootstrap: None,
            intuition_policy_host: None,
            intelligence_product_runner: None,
            intelligence_invocation_provider: None,
        })
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

    /// Independent monotonic witness for the segmented objective RunStart
    /// history. It must live outside the Agent home rollback domain.
    pub fn with_objective_checkpoint_file(mut self, path: PathBuf) -> Self {
        self.objective_checkpoint_file = Some(path);
        self
    }

    pub(crate) fn objective_checkpoint_file(&self) -> Option<&Path> {
        self.objective_checkpoint_file.as_deref()
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
        let writer = host.writer();
        if writer.owner_agent_id() != &self.identity.agent_id {
            return Err(AgentdError::GenerationFenced(
                "production cognitive writer owner does not match Agentd identity".to_string(),
            ));
        }
        if writer.generation() != self.identity.spawn_generation {
            return Err(AgentdError::GenerationFenced(format!(
                "production cognitive writer generation {} does not match Agentd spawn generation {}",
                writer.generation(),
                self.identity.spawn_generation
            )));
        }
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

    pub fn identity(&self) -> &AgentdIdentity {
        &self.identity
    }

    pub(crate) fn into_parts(self) -> (AgentdIdentity, FleetRegistry, File) {
        (self.identity, self.registry, self._writer_lock)
    }
}

fn required_utf8(name: &str) -> Result<String, AgentdError> {
    let value = std::env::var_os(name)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| AgentdError::Invalid(format!("{name} is required")))?;
    value
        .into_string()
        .map_err(|_| AgentdError::Invalid(format!("{name} must be UTF-8")))
}

fn required_path(name: &str) -> Result<PathBuf, AgentdError> {
    let value: OsString = std::env::var_os(name)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| AgentdError::Invalid(format!("{name} is required")))?;
    Ok(PathBuf::from(value))
}

fn require_canonical(path: &Path, label: &str) -> Result<(), AgentdError> {
    let canonical = path.canonicalize()?;
    if canonical != path {
        return Err(AgentdError::Invalid(format!(
            "{label} must be canonical and symlink-free: {}",
            path.display()
        )));
    }
    Ok(())
}

fn require_exact_path(actual: &Path, expected: &Path, label: &str) -> Result<(), AgentdError> {
    require_canonical(actual, label)?;
    if actual != expected {
        return Err(AgentdError::Invalid(format!(
            "{label} {} does not match registered path {}",
            actual.display(),
            expected.display()
        )));
    }
    Ok(())
}

#[cfg(test)]
#[path = "config_tests.rs"]
mod tests;
