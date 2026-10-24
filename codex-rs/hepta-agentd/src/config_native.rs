use std::fs::File;
use std::path::PathBuf;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::FleetRegistry;

use crate::AgentdError;
pub use crate::process_identity::AgentdIdentity;
pub use crate::process_identity::HEPTA_AGENT_GENERATION_ENV;
pub use crate::process_identity::HEPTA_AGENT_HOME_ENV;
pub use crate::process_identity::HEPTA_AGENT_ID_ENV;
pub use crate::process_identity::HEPTA_AGENT_RUN_ROOT_ENV;

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
