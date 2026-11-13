//! Ordinary Root handoff and service for the same retained task factory. The
//! non-Clone lane is taken before handoff side effects. Failure never puts the
//! writer back or emits a new operation; only original custody readback remains.

use std::os::fd::{AsRawFd, OwnedFd};
use std::os::unix::net::UnixDatagram;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use codex_hepta_contracts::{HostAuthorityPeerChannel, HostAuthorityPeerPolicy, HostIssuerPeer};
use codex_hepta_neuron::AnchorWitnessStore;

use super::PreparedRootHostCircuitTaskV1;
use crate::AgentdError;
use crate::circuit_task::remote::OriginalRootTaskStreams;
use crate::root_original_task_descriptor::{protocol, require_before};

#[path = "authority_host_task_listeners.rs"]
mod listeners;

impl<SW, CW> PreparedRootHostCircuitTaskV1<SW, CW>
where SW: AnchorWitnessStore + Send + 'static, CW: AnchorWitnessStore + Send + 'static,
{
    /// Send one sealed task offer on a distinct inherited Root-created pair,
    /// then accept only the same registered daemon after its credential drop.
    /// The original writer/issuer/checkpoint lanes use this SAME retained
    /// session and its original sealed bootstrap on a separate original pair.
    /// Both paths must use the existing Root:peer-gid mode02710 runtime parent.
    /// No Config, SQL store, grant or caller-selected Cell is constructed here.
    ///
    /// The factory's one lane is consumed before bind/seal/send. Partial handoff,
    /// timeout and lost ACK retain only same-operation readback/drain custody;
    /// this method supplies no automatic rebind or second execution lane.
    pub fn handoff_and_serve_original_root_circuit_task(
        &mut self, production_handoff: UnixDatagram, task_handoff: UnixDatagram,
        original_root_pidfd: OwnedFd, consumer_state_root: &Path,
        task_path: PathBuf, loan_path: PathBuf, session_nonce: [u8; 16],
    ) -> Result<u64, AgentdError> {
        let startup_end = (Instant::now() + Duration::from_secs(30)).min(self.end);
        PreparedRootHostCircuitTaskV1::handoff_and_serve_original_root_circuit_task_before(
            self, production_handoff, task_handoff, original_root_pidfd, consumer_state_root,
            task_path, loan_path, session_nonce, startup_end,
        )
    }

    /// The one ordinary assembly supplies its already-running startup window.
    /// Reuse the original handoff body and same runtime; neither a delayed
    /// service thread nor this call may create another thirty-second window.
    pub(crate) fn handoff_and_serve_original_root_circuit_task_before(
        &mut self, production_handoff: UnixDatagram, task_handoff: UnixDatagram,
        original_root_pidfd: OwnedFd, consumer_state_root: &Path,
        task_path: PathBuf, loan_path: PathBuf, session_nonce: [u8; 16], startup_end: Instant,
    ) -> Result<u64, AgentdError> {
        let startup_end = startup_end.min(Instant::now() + Duration::from_secs(30)).min(self.end);
        require_before(startup_end)?;
        PreparedRootHostCircuitTaskV1::read_original_root_task_generation(self)?;
        let identity = self.session.registration.registered_identity.identity()?;
        if rustix::process::getuid().as_raw() != 0 || rustix::process::geteuid().as_raw() != 0
            || self.session.config.peer_uid == 0
            || self.session.registration.peer_pid == std::process::id()
            || session_nonce == [0; 16]
        { return Err(AgentdError::Invalid("original Root task registration differs".into())); }
        let (binding, registry, source, capacity) = crate::CircuitQ24TaskRuntimeV1::original_root_handoff_data(&self.runtime)?;
        let lane = crate::CircuitQ24TaskRuntimeV1::take_original_root_lane(&mut self.runtime)?;
        let bound = listeners::TaskListeners::bind(&task_path, &loan_path, self.session.config.peer_gid)?;
        let original_host: super::super::super::super::original_task_host::OriginalTaskHostLanes<'_> =
            crate::PreparedHostAuthoritySession::bind_original_task_host_lanes(&self.session)?;
        let original_bootstrap = crate::PreparedHostAuthoritySession::seal_bootstrap(&self.session, consumer_state_root)?;
        let descriptor = crate::root_original_task_descriptor::seal(
            std::process::id(), self.session.registration.peer_pid,
            self.session.config.peer_uid, self.session.config.peer_gid,
            &task_path, &loan_path, session_nonce, self.end, capacity, binding, &registry, &source,
        )?;
        PreparedRootHostCircuitTaskV1::read_original_root_task_generation(self)?;
        let remaining = startup_end.checked_duration_since(Instant::now())
            .filter(|value| !value.is_zero()).ok_or_else(|| AgentdError::Invalid("Root task startup expired".into()))?;
        crate::send_root_production_handoff(production_handoff, &original_bootstrap,
            &original_root_pidfd, remaining)?;
        let remaining = startup_end.checked_duration_since(Instant::now())
            .filter(|value| !value.is_zero()).ok_or_else(|| AgentdError::Invalid("Root task startup expired".into()))?;
        crate::root_production_handoff::send_original_task_handoff(
            task_handoff, &descriptor, &original_root_pidfd, remaining,
        )?;
        let root: &PreparedRootHostCircuitTaskV1<SW, CW> = self;
        std::thread::scope(|scope| {
            // This is a real, already-Root host process. The ordinary daemon
            // performs its own process credential drop before either connect.
            let host = scope.spawn(move || original_host.serve());
            let task_result = (|| {
                let (task, loan) = bound.accept(&root.session.owner_pidfd, startup_end)?;
                root.read_original_root_task_generation()?;
                require_before(startup_end)?;
                let lifetime = root.end.checked_duration_since(Instant::now())
                    .filter(|value| !value.is_zero() && *value <= Duration::from_secs(300))
                    .ok_or_else(|| AgentdError::Invalid("original Root task scope expired".into()))?;
                let policy = HostAuthorityPeerPolicy {
                    peer: HostIssuerPeer { uid: root.session.config.peer_uid, pid: root.session.registration.peer_pid },
                    timeout: Duration::from_millis(root.session.config.timeout_ms.min(500)), lifetime,
                    request_bound: 65_536, response_bound: 65_536,
                };
                let task_fd = task.as_raw_fd();
                let task = HostAuthorityPeerChannel::from_stream(task, policy, root.session.owner_pidfd.try_clone()?)
                    .map_err(protocol)?;
                let loan = HostAuthorityPeerChannel::from_stream(loan, policy, root.session.owner_pidfd.try_clone()?)
                    .map_err(protocol)?;
                listeners::wait_first_frame(task_fd, &root.session.owner_pidfd, startup_end)?;
                root.read_original_root_task_generation()?;
                let end = root.end;
                crate::circuit_task::remote::serve(root, &identity, lane,
                    OriginalRootTaskStreams::new(task, loan, session_nonce, end)).map_err(protocol)
            })();
            let host_result = host.join()
                .map_err(|_| AgentdError::Protocol("original Root service panicked".into()))?
                .map_err(AgentdError::from);
            match (task_result, host_result) {
                (Ok(count), Ok(())) => Ok(count),
                (Err(task), Ok(())) => Err(task),
                (Ok(_), Err(host)) => Err(host),
                (Err(task), Err(host)) => Err(AgentdError::Protocol(format!(
                    "original task result Unknown: {task}; original host termination: {host}"))),
            }
        })
    }
}
