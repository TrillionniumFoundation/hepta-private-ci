//! A Root composition reuses the original gateway enrollment without opening an owner.
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_contracts::AgentId;
use tokio::net::UnixStream;

use super::Policy;
use super::trust;
use crate::ProcessDriverError;
use crate::controller_peer::ControllerPeerGate;

pub struct RootGatewayPeerV1 {
    policy_path: PathBuf,
    policy_bytes: Vec<u8>,
    policy: Policy,
    gate: ControllerPeerGate,
}

impl RootGatewayPeerV1 {
    /// Read only the bounded protected configuration of the Root chat host.
    /// It neither opens Fleet state nor grants permission to a request.
    pub fn read_chat_configuration(path: &Path) -> Result<Vec<u8>, ProcessDriverError> {
        if unsafe { libc::geteuid() } != 0 {
            return Err(ProcessDriverError::new("chat configuration requires Root"));
        }
        trust::read_root_file(path, 64 * 1024)
    }

    pub fn open(policy_path: &Path) -> Result<Self, ProcessDriverError> {
        if unsafe { libc::geteuid() } != 0 {
            return Err(ProcessDriverError::new("gateway composition requires Root"));
        }
        let policy_bytes = trust::read_root_file(policy_path, 64 * 1024)?;
        let policy: Policy = serde_json::from_slice(&policy_bytes)?;
        if policy.version != 1 || policy.workload_uid == 0 || policy.workload_gid == 0 {
            return Err(ProcessDriverError::new(
                "invalid existing local-host policy",
            ));
        }
        crate::workload_principal::validate(
            policy.workload_uid,
            policy.workload_gid,
            policy.agent_workload_uids.as_ref(),
        )
        .map_err(super::host_error)?;
        policy.validate_controller_isolation()?;
        let principal = policy.controller_principal.clone().ok_or_else(|| {
            ProcessDriverError::new("the local-host owner has not enrolled a gateway")
        })?;
        let gate =
            ControllerPeerGate::open(principal, &policy.cgroup_root).map_err(super::host_error)?;
        Ok(Self {
            policy_path: policy_path.to_owned(),
            policy_bytes,
            policy,
            gate,
        })
    }

    /// No request UID, PID, executable, cgroup or path is accepted as identity.
    /// A policy replacement fences this instance rather than rebinding its peer.
    pub fn verify(&self, stream: &UnixStream) -> Result<(), ProcessDriverError> {
        if unsafe { libc::geteuid() } != 0
            || trust::read_root_file(&self.policy_path, 64 * 1024)? != self.policy_bytes
        {
            return Err(ProcessDriverError::new("gateway enrollment changed"));
        }
        self.gate.verify(stream).map_err(super::host_error)
    }

    pub fn socket_group(&self) -> u32 {
        self.gate.principal().gid
    }

    /// The same original mapping that creates workloads checks their UDS owner.
    pub fn agent_workload_uid(&self, agent_id: &AgentId) -> Result<u32, ProcessDriverError> {
        self.policy.workload_uid_for(agent_id)
    }
}

#[cfg(test)]
#[path = "local_fleet_gateway_peer_tests.rs"]
mod tests;
