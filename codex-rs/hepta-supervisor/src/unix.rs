//! Unix process effects with registered execution context and durable Fleet pins.
//!
//! Legacy library callers without the product scope retain their historical
//! behavior. The named daemon installs the scope before this driver is built.
#[path = "unix_core.rs"]
mod raw;

use std::future::Future;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use crate::AdoptSpec;
use crate::Adoption;
use crate::AgentCommand;
use crate::FleetStartAdmission;
use crate::ManagedProcess;
use crate::MatrixAdoptSpec;
use crate::MatrixSpawnSpec;
use crate::ProcessDriver;
use crate::ProcessDriverError;
use crate::ProcessObservation;
use crate::ProcessState;
use crate::SpawnSpec;
use crate::SpawnedProcess;
use crate::fleet_start_admission::execution::ProcessBinding;
use crate::fleet_start_admission::execution::ProcessEffect;
use crate::fleet_start_admission::execution::ProcessMonitor;
use crate::fleet_start_admission::execution::ProcessPermit;
use serde_json::Value;
use serde_json::json;

tokio::task_local! {
    static FLEET_START_ADMISSION: FleetStartAdmission;
}

pub(crate) async fn with_fleet_start_admission<F, T>(admission: FleetStartAdmission, future: F) -> T
where
    F: Future<Output = T>,
{
    FLEET_START_ADMISSION.scope(admission, future).await
}

enum PreparedProcess {
    Legacy,
    Fleet {
        permit: Box<ProcessPermit>,
        binding: Arc<ProcessBinding>,
        admission: Arc<FleetStartAdmission>,
    },
}

pub struct UnixProcessDriver {
    inner: raw::UnixProcessDriver,
    fleet: Option<(Arc<FleetStartAdmission>, Arc<ProcessBinding>)>,
}

/// Process exit is observable here, but cannot prove that descendants left the
/// selected-host resource scope. This wrapper never releases a physical pin.
pub struct UnixManagedProcess {
    inner: raw::UnixManagedProcess,
    monitor: Option<ProcessMonitor>,
    denied_since: Option<Instant>,
    last_kill: Option<Instant>,
}

impl UnixProcessDriver {
    pub fn new(log_channel_capacity: usize) -> Result<Self, ProcessDriverError> {
        let inner = raw::UnixProcessDriver::new(log_channel_capacity)?;
        let fleet = match FLEET_START_ADMISSION.try_with(Clone::clone) {
            Ok(admission) => {
                let binding = admission.capture_process_binding()?;
                Some((Arc::new(admission), Arc::new(binding)))
            }
            Err(_) => None,
        };
        Ok(Self { inner, fleet })
    }

    fn permit(&self, effect: ProcessEffect<'_>) -> Result<PreparedProcess, ProcessDriverError> {
        match &self.fleet {
            Some((admission, binding)) => Ok(PreparedProcess::Fleet {
                permit: Box::new(binding.prepare(admission, effect)?),
                binding: Arc::clone(binding),
                admission: Arc::clone(admission),
            }),
            None => Ok(PreparedProcess::Legacy),
        }
    }

    fn wrap(inner: raw::UnixManagedProcess, permit: PreparedProcess) -> UnixManagedProcess {
        let monitor = match permit {
            PreparedProcess::Legacy => None,
            PreparedProcess::Fleet {
                permit,
                binding,
                admission,
            } => Some((*permit).into_monitor(binding, admission)),
        };
        UnixManagedProcess {
            inner,
            monitor,
            denied_since: None,
            last_kill: None,
        }
    }
}

impl ManagedProcess for UnixManagedProcess {
    fn poll(&mut self, max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
        let mut observation = self.inner.poll(max_logs)?;
        if let ProcessState::Running { healthy, drained } = &mut observation.state
            && self
                .monitor
                .as_mut()
                .is_some_and(ProcessMonitor::authority_denied)
        {
            *healthy = false;
            *drained = false;
            let now = Instant::now();
            match self.denied_since {
                None => {
                    // A signal is a stop request, not a quiescence receipt.
                    self.inner.request_stop()?;
                    self.denied_since = Some(now);
                }
                Some(started)
                    if now.duration_since(started) >= Duration::from_secs(5)
                        && self.last_kill.is_none_or(|last| {
                            now.duration_since(last) >= Duration::from_secs(1)
                        }) =>
                {
                    self.inner.kill()?;
                    self.last_kill = Some(now);
                }
                Some(_) => {}
            }
        }
        Ok(observation)
    }

    fn request_drain(&mut self) -> Result<(), ProcessDriverError> {
        self.inner.request_drain()
    }

    fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
        self.inner.request_stop()
    }

    fn kill(&mut self) -> Result<(), ProcessDriverError> {
        self.inner.kill()
    }
}

impl ProcessDriver for UnixProcessDriver {
    type Process = UnixManagedProcess;

    fn spawn(
        &mut self,
        spec: &SpawnSpec,
    ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        let permit = self.permit(ProcessEffect {
            agent_id: &spec.agent_id,
            common: json!({
                "role": "agentd", "generation": spec.generation,
                "control_socket_os_bytes": spec.control_socket.as_os_str().as_encoded_bytes(),
            }),
            dispatch: Some(json!({
                "command": command_frame(&spec.command),
                "generation": spec.generation,
                "fleet_root_os_bytes": spec.fleet_root.as_os_str().as_encoded_bytes(),
                "workspace_os_bytes": spec.workspace.as_os_str().as_encoded_bytes(),
                "home_root_os_bytes": spec.home_root.as_os_str().as_encoded_bytes(),
                "run_root_os_bytes": spec.run_root.as_os_str().as_encoded_bytes(),
                "control_socket_os_bytes": spec.control_socket.as_os_str().as_encoded_bytes(),
                "logs_root_os_bytes": spec.logs_root.as_os_str().as_encoded_bytes(),
            })),
            workspace: Some(&spec.workspace),
            fleet_root: Some(&spec.fleet_root),
            home_root: Some(&spec.home_root),
            run_root: Some(&spec.run_root),
            matrix_root: None,
        })?;
        // Consume the same borrowed immutable spec that was serialized above.
        // The permit still owns the shared authority fence during this call.
        let spawned = self.inner.spawn(spec)?;
        Ok(SpawnedProcess {
            identity: spawned.identity,
            process: Self::wrap(spawned.process, permit),
        })
    }

    fn adopt(&mut self, spec: &AdoptSpec) -> Result<Adoption<Self::Process>, ProcessDriverError> {
        let permit = self.permit(ProcessEffect {
            agent_id: &spec.agent_id,
            common: json!({
                "role": "agentd", "generation": spec.spawn_generation,
                "control_socket_os_bytes": spec.control_socket.as_os_str().as_encoded_bytes(),
            }),
            dispatch: None,
            workspace: Some(&spec.workspace),
            fleet_root: None,
            home_root: Some(&spec.home_root),
            run_root: Some(&spec.run_root),
            matrix_root: None,
        })?;
        // The raw driver additionally proves the exact persisted PID/UDS
        // identity; a remembered intent alone never grants signal authority.
        Ok(match self.inner.adopt(spec)? {
            Adoption::Adopted(process) => Adoption::Adopted(Self::wrap(process, permit)),
            Adoption::Missing => Adoption::Missing,
            Adoption::Rejected => Adoption::Rejected,
        })
    }

    fn spawn_matrixd(
        &mut self,
        spec: &MatrixSpawnSpec,
    ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        let permit = self.permit(ProcessEffect {
            agent_id: &spec.agent_id,
            common: json!({
                "role": "matrixd", "generation": spec.agent_generation,
                "binding_revision": spec.binding_revision,
                "binding_digest": spec.binding_digest.as_str(),
                "release_id": spec.release_id.as_str(),
                "process_incarnation": spec.process_incarnation,
                "plane_epoch": spec.plane_epoch,
                "control_socket_os_bytes": spec.control_socket.as_os_str().as_encoded_bytes(),
            }),
            dispatch: Some(json!({
                "command": command_frame(&spec.command),
                "fleet_root_os_bytes": spec.fleet_root.as_os_str().as_encoded_bytes(),
                "workspace_os_bytes": spec.workspace.as_os_str().as_encoded_bytes(),
                "matrix_root_os_bytes": spec.matrix_root.as_os_str().as_encoded_bytes(),
                "agentd_control_socket_os_bytes": spec.agentd_control_socket.as_os_str().as_encoded_bytes(),
                "logs_root_os_bytes": spec.logs_root.as_os_str().as_encoded_bytes(),
            })),
            workspace: Some(&spec.workspace),
            fleet_root: Some(&spec.fleet_root),
            home_root: None,
            run_root: None,
            matrix_root: Some(&spec.matrix_root),
        })?;
        let spawned = self.inner.spawn_matrixd(spec)?;
        Ok(SpawnedProcess {
            identity: spawned.identity,
            process: Self::wrap(spawned.process, permit),
        })
    }

    fn adopt_matrixd(
        &mut self,
        spec: &MatrixAdoptSpec,
    ) -> Result<Adoption<Self::Process>, ProcessDriverError> {
        let permit = self.permit(ProcessEffect {
            agent_id: &spec.agent_id,
            common: json!({
                "role": "matrixd", "generation": spec.agent_generation,
                "binding_revision": spec.binding_revision,
                "binding_digest": spec.binding_digest.as_str(),
                "release_id": spec.release_id.as_str(),
                "process_incarnation": spec.process_incarnation,
                "plane_epoch": spec.plane_epoch,
                "control_socket_os_bytes": spec.control_socket.as_os_str().as_encoded_bytes(),
            }),
            dispatch: None,
            workspace: None,
            fleet_root: None,
            home_root: None,
            run_root: None,
            matrix_root: None,
        })?;
        Ok(match self.inner.adopt_matrixd(spec)? {
            Adoption::Adopted(process) => Adoption::Adopted(Self::wrap(process, permit)),
            Adoption::Missing => Adoption::Missing,
            Adoption::Rejected => Adoption::Rejected,
        })
    }
}

fn command_frame(command: &AgentCommand) -> Value {
    json!({
        "schema": "hepta.runtime.fleet.command.unix-bytes.v1",
        "program": command.program.as_os_str().as_encoded_bytes(),
        "args": command.args.iter().map(|argument| argument.as_encoded_bytes()).collect::<Vec<_>>(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::FLEET_START_TRUST_PROFILE_SCHEMA_VERSION;
    use crate::FleetStartNodeTrustV1;
    use crate::FleetStartTrustKeyV1;
    use crate::FleetStartTrustProfileV1;
    use std::ffi::OsString;
    use std::os::unix::ffi::OsStringExt;

    const DISTRIBUTOR_KEY: &str =
        "fa4834147f6e690c3693eff61336046403cd8ae2a14f31b3c407358569239565";
    const NODE_KEY: &str = "197f6b23e16c8532c6abc838facd5ea789be0c76b2920334039bfa8b3d368d61";

    fn trust_profile() -> FleetStartTrustProfileV1 {
        FleetStartTrustProfileV1 {
            schema_version: FLEET_START_TRUST_PROFILE_SCHEMA_VERSION,
            local_node_id: "node-a".into(),
            distributor_id: "revocation-distributor".into(),
            distributor_keys: vec![FleetStartTrustKeyV1 {
                key_id: "distributor-v1".into(),
                verifying_key_hex: DISTRIBUTOR_KEY.into(),
                not_before_authority_epoch: 1,
                not_after_authority_epoch: 99,
            }],
            nodes: vec![FleetStartNodeTrustV1 {
                node_id: "node-a".into(),
                keys: vec![FleetStartTrustKeyV1 {
                    key_id: "node-a-v1".into(),
                    verifying_key_hex: NODE_KEY.into(),
                    not_before_authority_epoch: 1,
                    not_after_authority_epoch: 99,
                }],
            }],
        }
    }

    #[tokio::test]
    async fn scoped_driver_rejects_before_process_effect_without_current_grant() {
        let directory = tempfile::tempdir().expect("tempdir");
        let state_root = directory.path().join("state");
        std::fs::create_dir(&state_root).expect("state root");
        let admission =
            FleetStartAdmission::new(&state_root, trust_profile()).expect("start admission");
        let result =
            with_fleet_start_admission(
                admission,
                async move { UnixProcessDriver::new(8).map(|_| ()) },
            )
            .await;
        assert!(
            result
                .expect_err("uninitialized host must deny physical effects")
                .to_string()
                .contains("runtime.fleet")
        );
    }

    #[test]
    fn command_frame_preserves_non_utf8_arguments_and_boundaries() {
        let command = |args| AgentCommand::new("/bin/echo", args).expect("command");
        let first = command(vec![OsString::from_vec(vec![b'a', 0xff]), "bc".into()]);
        let lossy = command(vec!["a\u{fffd}".into(), "bc".into()]);
        let regrouped = command(vec!["a".into(), OsString::from_vec(vec![0xff, b'b', b'c'])]);
        assert_ne!(command_frame(&first), command_frame(&lossy));
        assert_ne!(command_frame(&first), command_frame(&regrouped));
        assert_ne!(
            command_frame(&command(vec!["x".into(), "y".into()])),
            command_frame(&command(vec!["y".into(), "x".into()]))
        );
    }
}
