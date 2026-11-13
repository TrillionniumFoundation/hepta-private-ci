//! A real Root process serves only the already registered daemon's fixed Cell
//! and Source lanes. Config, AgentdState, SQL writer and private receipts stay
//! in that daemon. No thread is used as a replacement for process credentials.

use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_neuron::AnchorWitnessStore;

use super::PreparedRootHostCircuitTaskV1;
use crate::{AgentdError, CircuitTaskSourceReadbackV1, OriginalRootCircuitTaskCustodyV1};
use crate::circuit_task::remote::OriginalRootTaskStreams;

impl<SW, CW> PreparedRootHostCircuitTaskV1<SW, CW>
where SW: AnchorWitnessStore + Send + 'static, CW: AnchorWitnessStore + Send + 'static,
{
    /// Consume this runtime's one actual factory lane. Both streams must have
    /// been connected by the registered non-Root process; their two pidfds are
    /// duplicates of this session's same pre-held process handle. The nonce
    /// separates the fixed lanes and grants no task, model or effect authority.
    ///
    /// This synchronous scope owns the actual work until it returns. A caller
    /// cancelling its await cannot release these owners. Any error is Unknown;
    /// this value retains only its original readback/drain custody, never a new
    /// lane, a new operation or an automatic Create/Execute retry.
    pub fn serve_original_root_circuit_task(&mut self, task: UnixStream, loan: UnixStream,
        session_nonce: [u8; 16]) -> Result<u64, AgentdError>
    {
        PreparedRootHostCircuitTaskV1::read_original_root_task_generation(self)?;
        let identity = self.session.registration.registered_identity.identity()?;
        if self.session.config.peer_uid == 0 || self.session.registration.peer_pid == std::process::id()
            || session_nonce == [0; 16]
        { return Err(AgentdError::Invalid("original Root task peer or session differs".into())); }
        let lifetime = self.end.checked_duration_since(Instant::now())
            .filter(|value| !value.is_zero() && *value <= Duration::from_secs(300))
            .ok_or_else(|| AgentdError::Invalid("original Root task scope expired".into()))?;
        let policy = HostAuthorityPeerPolicy {
            peer: HostIssuerPeer { uid: self.session.config.peer_uid, pid: self.session.registration.peer_pid },
            timeout: Duration::from_millis(self.session.config.timeout_ms.min(500)), lifetime,
            request_bound: 65_536, response_bound: 65_536,
        };
        let task = HostAuthorityPeerChannel::from_stream(task, policy, self.session.owner_pidfd.try_clone()?)
            .map_err(|error| AgentdError::Protocol(error.to_string()))?;
        let loan = HostAuthorityPeerChannel::from_stream(loan, policy, self.session.owner_pidfd.try_clone()?)
            .map_err(|error| AgentdError::Protocol(error.to_string()))?;
        let lane = crate::CircuitQ24TaskRuntimeV1::take_original_root_lane(&mut self.runtime)?;
        crate::circuit_task::remote::serve(self, &identity, lane,
            OriginalRootTaskStreams::new(task, loan, session_nonce, self.end))
            .map_err(|error| AgentdError::Protocol(format!("original Root task service: {error}")))
    }

    pub(crate) fn require_original_root_task_source(&self,
        source: &Arc<CircuitTaskSourceReadbackV1<SW>>) -> Result<(), AgentdError>
    {
        PreparedRootHostCircuitTaskV1::read_original_root_task_generation(self)?;
        OriginalRootCircuitTaskCustodyV1::require_original_source(&self.custody, source)
    }
}
