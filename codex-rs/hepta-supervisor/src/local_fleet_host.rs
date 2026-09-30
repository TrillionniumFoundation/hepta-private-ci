//! Explicit root-owned local resource authority and native containment.
//! This owner issues only resource leases, never model or acceptance grants.

use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;
use codex_hepta_fleet::AllocationGrant;
use codex_hepta_fleet::DurableFleetStore;
use codex_hepta_fleet::DurableLeaseDispositionV1;
use codex_hepta_fleet::FleetAuthorityPort;
use codex_hepta_fleet::FleetExecutionContextV1;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::LocalCapacityObserver;
use codex_hepta_fleet::LocalCapacityObserverConfig;
use codex_hepta_fleet::ResourceVectorV1;
use serde::Deserialize;
use sha2::Digest;
use sha2::Sha256;
use tokio::runtime::Handle;
use tokio_util::sync::CancellationToken;

use crate::ProcessDriverError;
use crate::SpawnSpec;

#[path = "local_fleet_containment.rs"]
mod containment;
#[path = "local_fleet_environment.rs"]
mod environment;
#[path = "local_fleet_maintenance.rs"]
mod maintenance;
#[path = "local_fleet_trust.rs"]
mod trust;
pub(crate) use containment::PreparedExecution;

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Policy {
    pub version: u32,
    pub workload_uid: u32,
    pub workload_gid: u32,
    pub cgroup_root: String,
    pub resource_authority_frontier: PathBuf,
    pub process_thread_reserve: u64,
    pub matrix_resources: ResourceVectorV1,
    #[serde(default)]
    pub self_iteration_config_directory: Option<PathBuf>,
}

pub struct LocalFleetHost {
    store: DurableFleetStore,
    registry: FleetRegistry,
    authority: AuthorityLeaseRegistry,
    observer: LocalCapacityObserver,
    runtime: Handle,
    clock: Arc<trust::HostClock>,
    launch_gate: Arc<tokio::sync::Mutex<()>>,
    launch_environment: environment::LaunchEnvironment,
    pub(crate) policy: Policy,
}

impl LocalFleetHost {
    /// Open a root-protected, explicit policy before any workload can spawn.
    pub async fn open(
        policy_path: &Path,
        registry: FleetRegistry,
    ) -> Result<Arc<Self>, ProcessDriverError> {
        let bytes = trust::read_root_file(policy_path, 64 * 1024)?;
        let policy: Policy = serde_json::from_slice(&bytes)?;
        if unsafe { libc::geteuid() } != 0
            || policy.version != 1
            || policy.workload_uid == 0
            || policy.workload_gid == 0
            || !(32..=1024).contains(&policy.process_thread_reserve)
        {
            return Err(ProcessDriverError::new(
                "local host requires root and a bounded non-root workload policy",
            ));
        }
        if let Some(directory) = &policy.self_iteration_config_directory {
            trust::validate_root_directory(directory)?;
        }
        containment::prepare_base(&policy)?;
        containment::protect_registry(&registry, &policy)?;
        let clock = Arc::new(trust::HostClock::new()?);
        let store = DurableFleetStore::open_with_clock(
            registry
                .layout()
                .state_root()
                .join("fleet-resources.sqlite3")
                .as_path(),
            clock.clone(),
        )
        .await
        .map_err(host_error)?;
        let mut config = LocalCapacityObserverConfig::for_local_supervisor(
            registry.layout().fleet_root().as_path(),
            1,
        )
        .map_err(host_error)?;
        config.generation = store
            .register_local_boot(&config.host_id)
            .await
            .map_err(host_error)?;
        let observer = LocalCapacityObserver::new(config).map_err(host_error)?;
        let frontier = Arc::new(trust::RootResourceFrontier::open(
            &policy.resource_authority_frontier,
        )?);
        let authority = AuthorityLeaseRegistry::open_state_dir_with_trust(
            &registry.layout().state_root().join("resource-authority"),
            "local-supervisor-resources".into(),
            clock.clone(),
            frontier,
        )
        .map_err(host_error)?;
        let host = Arc::new(Self {
            store,
            registry,
            authority,
            observer,
            runtime: Handle::current(),
            clock,
            launch_gate: Arc::new(tokio::sync::Mutex::new(())),
            launch_environment: environment::LaunchEnvironment::capture(),
            policy,
        });
        host.maintain().await?;
        Ok(host)
    }

    pub(crate) fn prepare_registration(
        &self,
        record: &codex_hepta_fleet::AgentRecord,
    ) -> Result<(), ProcessDriverError> {
        self.launch_environment
            .resolve(&self.policy, &record.manifest.agent_id)?;
        containment::prepare_workload(&record.layout, &self.policy)
    }

    pub(crate) fn prepare_agent(
        &self,
        spec: &SpawnSpec,
    ) -> Result<containment::PreparedExecution, ProcessDriverError> {
        self.runtime.block_on(async {
            let launch = Arc::clone(&self.launch_gate).lock_owned().await;
            let record = self
                .registry
                .load_agent(&spec.agent_id)
                .map_err(host_error)?;
            containment::prepare_workload(&record.layout, &self.policy)?;
            let environment = self
                .launch_environment
                .resolve(&self.policy, &spec.agent_id)?;
            let budget = &record.manifest.resources;
            let resources = ResourceVectorV1 {
                cpu_millis: u64::from(budget.max_concurrent_turns) * 1000,
                memory_bytes: u64::from(budget.memory_limit_mib) * 1024 * 1024,
                accelerator_millis: 0,
                concurrent_turns: u64::from(budget.max_concurrent_turns),
                tool_processes: u64::from(budget.max_tool_processes),
                turn_queue_slots: u64::from(budget.turn_queue_capacity),
            };
            // Actual installed program bytes and the complete immutable launch
            // configuration determine the digest; no request digest is trusted.
            let mut digest = Sha256::new();
            digest.update(std::fs::read(&spec.command.program)?);
            digest.update(serde_json::to_vec(&record.manifest)?);
            digest.update(spec.generation.to_be_bytes());
            for (name, value) in &environment {
                for bytes in [name.as_encoded_bytes(), value.as_encoded_bytes()] {
                    digest.update((bytes.len() as u64).to_be_bytes());
                    digest.update(bytes);
                }
            }
            for arg in &spec.command.args {
                let bytes = arg.as_encoded_bytes();
                digest.update((bytes.len() as u64).to_be_bytes());
                digest.update(bytes);
            }
            let mut prepared = self
                .prepare(
                    &spec.agent_id,
                    "main",
                    resources,
                    hex_digest(digest.finalize()),
                )
                .await?;
            prepared.launch = Some(launch);
            prepared.environment = environment;
            Ok(prepared)
        })
    }

    pub(crate) fn prepare_matrix(
        &self,
        spec: &crate::MatrixSpawnSpec,
    ) -> Result<containment::PreparedExecution, ProcessDriverError> {
        self.runtime.block_on(async {
            let launch = Arc::clone(&self.launch_gate).lock_owned().await;
            let record = self
                .registry
                .load_agent(&spec.agent_id)
                .map_err(host_error)?;
            containment::prepare_workload(&record.layout, &self.policy)?;
            let mut digest = Sha256::new();
            digest.update(b"hepta.local-host.matrix.v1\0");
            digest.update(std::fs::read(&spec.command.program)?);
            digest.update(serde_json::to_vec(&record.manifest)?);
            digest.update(spec.binding_digest.as_str());
            digest.update(spec.agent_generation.to_be_bytes());
            digest.update(spec.plane_epoch.to_be_bytes());
            digest.update(spec.process_incarnation.as_bytes());
            for arg in &spec.command.args {
                let bytes = arg.as_encoded_bytes();
                digest.update((bytes.len() as u64).to_be_bytes());
                digest.update(bytes);
            }
            let mut prepared = self
                .prepare(
                    &spec.agent_id,
                    "matrix",
                    self.policy.matrix_resources,
                    hex_digest(digest.finalize()),
                )
                .await?;
            prepared.launch = Some(launch);
            Ok(prepared)
        })
    }

    async fn prepare(
        &self,
        agent: &AgentId,
        kind: &str,
        resources: ResourceVectorV1,
        manifest_digest: String,
    ) -> Result<containment::PreparedExecution, ProcessDriverError> {
        self.roll_resource_epoch_if_needed()?;
        let principal = if kind == "main" {
            agent.to_string()
        } else {
            format!("matrix:{agent}")
        };
        if self
            .store
            .active_execution_for_principal(&principal)
            .await
            .map_err(host_error)?
            .is_some()
        {
            return Err(ProcessDriverError::new(
                "principal still owns a durable execution hold",
            ));
        }
        let (observation, _) = self
            .store
            .refresh_local_capacity(&self.observer)
            .await
            .map_err(host_error)?;
        let execution_id = uuid::Uuid::new_v4().to_string();
        let prepared =
            containment::create_execution(&self.policy, agent, kind, &execution_id, resources)?;
        let grant = AllocationGrant {
            allocation_id: execution_id.clone(),
            request_id: format!("spawn:{execution_id}"),
            principal_id: principal.clone(),
            host_id: observation.host.host_id.clone(),
            failure_domain_id: observation.host.failure_domain_id,
            host_generation: observation.host.generation,
            authority_epoch: self
                .authority
                .frontier()
                .map_err(host_error)?
                .authority_epoch,
            lease_generation: 1,
            expires_at_ms: observation.host.valid_until_ms,
            resources,
            semantic_digest: manifest_digest.clone(),
            revoked: false,
        };
        self.authorize(
            &grant.allocation_id,
            FleetAuthorityPort::binding_for_issue(&grant).map_err(host_error)?,
            grant.expires_at_ms,
        )?;
        let port = FleetAuthorityPort::new(self.authority.verifier());
        self.store
            .issue_authorized(&port, &grant.allocation_id, 1, grant.clone())
            .await
            .map_err(host_error)?;
        let context = FleetExecutionContextV1 {
            execution_id: execution_id.clone(),
            allocation_id: grant.allocation_id,
            principal_id: principal,
            host_id: grant.host_id,
            host_generation: grant.host_generation,
            lease_generation: 1,
            manifest_digest,
            resources,
            containment: prepared.relative.clone(),
        };
        self.store
            .prepare_local_execution(&context)
            .await
            .map_err(host_error)?;
        Ok(prepared)
    }

    fn authorize(
        &self,
        id: &str,
        binding: codex_hepta_contracts::authority_lease::AuthorityLeaseBinding,
        expires_at_ms: u64,
    ) -> Result<u64, ProcessDriverError> {
        use codex_hepta_contracts::AuthorityClock;
        let current = self.authority.read_lease(id).map_err(host_error)?;
        let previous = current.as_ref().map_or(0, |lease| lease.lease.revision);
        let epoch = self
            .authority
            .frontier()
            .map_err(host_error)?
            .authority_epoch;
        let lease = AuthorityLease {
            schema_version: 1,
            lease_id: id.into(),
            authority_epoch: epoch,
            revision: previous + 1,
            binding,
            issued_at_unix_ms: self.clock.now_unix_ms().map_err(host_error)?,
            expires_at_unix_ms: expires_at_ms,
        };
        self.authority
            .put_lease(lease, previous)
            .map_err(host_error)?;
        Ok(previous + 1)
    }

    pub(crate) fn bind(
        &self,
        execution: &containment::PreparedExecution,
        pid: u32,
    ) -> Result<(), ProcessDriverError> {
        self.runtime
            .block_on(self.store.bind_local_process(&execution.id, pid))
            .map_err(host_error)
    }

    pub(crate) fn constrain(
        &self,
        command: &mut std::process::Command,
        prepared: &PreparedExecution,
    ) {
        // Keep the owner's explicit per-agent launch fields, then discard all
        // inherited variables. Loader and language runtime injection variables
        // cannot cross the root-to-workload boundary through the environment.
        let explicit: Vec<_> = command
            .get_envs()
            .filter_map(|(name, value)| value.map(|value| (name.to_owned(), value.to_owned())))
            .collect();
        command
            .env_clear()
            .env("PATH", "/usr/bin:/bin")
            .env("LANG", "C.UTF-8")
            .envs(
                prepared
                    .environment
                    .iter()
                    .map(|(name, value)| (name, value)),
            )
            .envs(explicit);
        containment::constrain(command, prepared, &self.policy);
    }

    pub(crate) fn recover_execution(
        &self,
        principal: &str,
        pid: u32,
    ) -> Result<String, ProcessDriverError> {
        self.runtime.block_on(async {
            let hold = self
                .store
                .active_execution_for_principal(principal)
                .await
                .map_err(host_error)?
                .ok_or_else(|| {
                    ProcessDriverError::new("live process has no durable resource hold")
                })?;
            self.store
                .verify_local_process(&hold.context.execution_id, pid)
                .await
                .map_err(host_error)?;
            Ok(hold.context.execution_id)
        })
    }

    pub(crate) fn request_stop(&self, id: &str) -> Result<(), ProcessDriverError> {
        self.runtime
            .block_on(self.store.request_local_stop(id))
            .map(|_| ())
            .map_err(host_error)
    }

    pub(crate) fn kill(&self, id: &str) -> Result<(), ProcessDriverError> {
        self.runtime
            .block_on(self.store.kill_local_containment(id))
            .map_err(host_error)
    }

    pub(crate) fn finish_exit(&self, id: &str) -> Result<bool, ProcessDriverError> {
        self.runtime.block_on(async {
            match self.store.confirm_local_exit(id).await {
                Ok(()) => {
                    if let Some(hold) = self.store.execution_hold(id).await.map_err(host_error)? {
                        match containment::remove_empty_execution(&hold.context.containment) {
                            Ok(()) => {}
                            Err(error) => {
                                eprintln!("could not remove retired execution cgroup: {error}")
                            }
                        }
                    }
                    Ok(true)
                }
                Err(codex_hepta_fleet::DurableFleetError::Conflict(_)) => {
                    self.store
                        .kill_local_containment(id)
                        .await
                        .map_err(host_error)?;
                    Ok(false)
                }
                Err(error) => Err(host_error(error)),
            }
        })
    }

    pub(crate) fn validate_retirement(&self, agent: &AgentId) -> Result<(), ProcessDriverError> {
        self.runtime.block_on(async {
            for principal in [agent.to_string(), format!("matrix:{agent}")] {
                if self
                    .store
                    .active_execution_for_principal(&principal)
                    .await
                    .map_err(host_error)?
                    .is_some()
                {
                    return Err(ProcessDriverError::new(
                        "agent still owns a durable resource hold",
                    ));
                }
            }
            Ok(())
        })
    }
}

fn host_error(error: impl std::fmt::Display) -> ProcessDriverError {
    ProcessDriverError::new(error.to_string())
}
fn hex_digest(bytes: impl AsRef<[u8]>) -> String {
    bytes
        .as_ref()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}
