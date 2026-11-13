//! One read-only Material loan shares the Root task's actual owners. It may be
//! retained before A completes and bound to the later actual Material contract,
//! but every request requires original completed Source/Cell/current readback.

use std::sync::Arc;
use std::time::{Duration, Instant};
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_neuron::AnchorWitnessStore;
use super::{PreparedRootHostCircuitTaskV1, OriginalHostInitialOperation,
    OriginalRootCircuitTaskCustodyV1, PreparedHostAuthoritySession, require_original_session};
use crate::AgentdError;
use crate::circuit_task::original_material_source::wire;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;
use crate::neuron_generation_current::NeuronGenerationInitialReadbackV1;

#[path = "authority_host_material_source_registration.rs"]
mod registration;
pub use registration::OriginalRootMaterialSourceRegistrationV1;

#[path = "authority_host_prefreeze_source.rs"]
mod prefreeze;
pub use prefreeze::OriginalRootPrefreezeSourceRegistrationV1;

/// Non-Clone, single-use, Material-only reader. The Arcs retain the same
/// concrete original owners; they neither duplicate a writer nor expose one.
/// The session's original absolute end remains fixed across task/loan use.
pub struct PreparedRootMaterialSourceHostV1<SW: AnchorWitnessStore, CW: AnchorWitnessStore> {
    session: Arc<PreparedHostAuthoritySession>,
    operation: Arc<OriginalHostInitialOperation>,
    custody: Arc<OriginalRootCircuitTaskCustodyV1<SW, CW>>,
    source_ready: Arc<super::original_source_ready::Hint>,
    end: Instant,
}

impl<SW, CW> PreparedRootHostCircuitTaskV1<SW, CW>
where SW: AnchorWitnessStore + Send + 'static, CW: AnchorWitnessStore + Send + 'static,
{
    /// Export this one bounded read service before moving the actual task pump
    /// into its service thread. This cannot build a Material contract, publish
    /// Source or cause A to run. Export failure after the once bit is consumed
    /// never restores it or substitutes another source.
    pub fn prepare_original_material_source_host(&mut self)
        -> Result<PreparedRootMaterialSourceHostV1<SW, CW>, AgentdError>
    {
        PreparedRootHostCircuitTaskV1::read_original_root_task_generation(self)?;
        if self.material_source_taken {
            return Err(AgentdError::Invalid("original Material Source service already exported".into()));
        }
        self.material_source_taken = true;
        let host = PreparedRootMaterialSourceHostV1 {
            session: Arc::clone(&self.session), operation: Arc::clone(&self.operation),
            custody: Arc::clone(&self.custody),
            source_ready: Arc::clone(&self.source_ready), end: self.end,
        };
        host.require_current()?;
        Ok(host)
    }
}

impl<SW: AnchorWitnessStore, CW: AnchorWitnessStore> PreparedRootMaterialSourceHostV1<SW, CW> {
    fn require_current(&self) -> Result<(), AgentdError> {
        require_original_session(&self.session, self.end)?;
        let observed = OriginalRootCircuitTaskCustodyV1::read_original_operation(&self.custody)?;
        OriginalHostInitialOperation::require_observed(&self.operation, &observed)?;
        if !matches!(observed, NeuronGenerationInitialReadbackV1::Published(_)) {
            return Err(AgentdError::Invalid("original Material Source generation is not published".into()));
        }
        require_original_session(&self.session, self.end)
    }

    /// Consume the one opaque supervisor registration. No action/run/path or
    /// actor is accepted from requests. The original command peer checker still
    /// rejects same-UID/same-PID connections; the Material process is separate.
    /// Missing, expired, changed or unavailable original evidence ends this
    /// loan. This serves no cached publication and supplies no reconnect retry.
    pub fn serve(self, registration: OriginalRootMaterialSourceRegistrationV1)
        -> Result<u64, AgentdError>
    {
        self.require_current()?;
        let registration::OriginalRootMaterialSourceRegistrationV1 {
            material, consumer, consumer_uid, original_consumer_pidfd, stream, nonce,
        } = registration;
        if consumer.pid == self.session.registration.peer_pid {
            return Err(protocol("the registered daemon is not the original Material process"));
        }
        let binding = wire::context(&material).map_err(protocol)?;
        let timeout = Duration::from_millis(self.session.config.timeout_ms.min(500));
        let lifetime = self.end.checked_duration_since(Instant::now())
            .filter(|value| !value.is_zero() && *value <= Duration::from_secs(300))
            .ok_or_else(|| protocol("original Material Source scope expired"))?;
        let mut channel = original_owner_command_channel_v1(stream, consumer, consumer_uid,
            original_consumer_pidfd, timeout, lifetime).map_err(protocol)?;
        self.require_current()?;
        wire::before(self.end).map_err(protocol)?;
        for id in 1..=wire::LIMIT {
            let request = wire::request(binding, nonce, id).map_err(protocol)?;
            let mut failure = None;
            let mut deadline = None;
            let exchanged = channel.exchange(|bytes| {
                let result = (|| -> Result<Vec<u8>, AgentdError> {
                    let until = (Instant::now() + timeout).min(self.end);
                    deadline = Some(until);
                    wire::before(until).map_err(protocol)?;
                    if bytes != request || wire::context(&material).map_err(protocol)? != binding {
                        return Err(protocol("original Material Source request differs"));
                    }
                    self.require_current()?;
                    let payload = OriginalRootCircuitTaskCustodyV1::read_original_material_source(
                        &self.custody, &material.initial.request,
                    )?;
                    self.require_current()?;
                    if wire::context(&material).map_err(protocol)? != binding {
                        return Err(protocol("original Material Source context changed"));
                    }
                    let response = wire::response(&request, &payload).map_err(protocol)?;
                    wire::before(until).map_err(protocol)?;
                    Ok(response)
                })();
                result.map_err(|error| { failure = Some(error); HostIssuerTransportError::Unavailable })
            });
            match exchanged {
                Ok(false) => { self.require_current()?; return Ok(id - 1); }
                Ok(true) => {
                    channel.check_peer_lifetime().map_err(protocol)?;
                    self.require_current()?;
                    if wire::context(&material).map_err(protocol)? != binding {
                        return Err(protocol("original Material Source context changed after response"));
                    }
                    let until = deadline.ok_or_else(|| protocol("original Source deadline missing"))?;
                    wire::before(until).map_err(protocol)?;
                }
                Err(error) => return Err(failure.unwrap_or_else(|| protocol(error))),
            }
        }
        Err(protocol("original Material Source request bound exhausted"))
    }
}

fn protocol(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Protocol(format!("original Material Source loan: {error}"))
}
