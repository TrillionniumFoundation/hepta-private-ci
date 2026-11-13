//! The original single Material Source export may instead start before freeze.
//! It still serves only that same Task/Cell/Source, with one original 128-frame
//! budget and the same absolute session end. No second Source lane is opened.

use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_neuron::AnchorWitnessStore;
use crate::{AgentdError, AgentdRootAuthorityPeer, OriginalRootCircuitTaskCustodyV1};
use crate::circuit_task::original_material_source::wire;
use crate::circuit_task::original_prefreeze_source::{read_request, ready};
use crate::learning_owner_command_channel::original_owner_command_channel_v1;
use super::PreparedRootMaterialSourceHostV1;

#[path = "authority_host_prefreeze_source_registration.rs"]
mod registration;
pub use registration::OriginalRootPrefreezeSourceRegistrationV1;

impl<SW: AnchorWitnessStore, CW: AnchorWitnessStore> PreparedRootMaterialSourceHostV1<SW, CW> {
    /// Consume the SAME one-use host as post-freeze serve. Complete source
    /// observations are authorized by the supervisor's fixed task disclosure;
    /// Generator evidence independently authenticates the actual requester.
    /// No frame supplies a run/path/action or a replacement trust snapshot.
    pub fn serve_original_prefreeze(self, registration: OriginalRootPrefreezeSourceRegistrationV1)
        -> Result<u64, AgentdError>
    {
        self.require_current()?;
        let registration::OriginalRootPrefreezeSourceRegistrationV1 {
            request, trust, evidence, original_consumer_pidfd, stream, startup_end,
        } = registration;
        if request.consumer.pid == self.session.registration.peer_pid {
            return Err(protocol("the daemon is not the registered Generator/Material recipient"));
        }
        let require_evidence = || {
            // Learning evidence retains its original Unix-seconds clock.
            // require_current separately checks the real protected Root clock,
            // lease, issuer and same operation before and after each read.
            let at = SystemTime::now().duration_since(UNIX_EPOCH).map_err(protocol)?.as_secs();
            crate::OriginalCircuitPrefreezeSourceRequestV1::require_evidence(&request, trust.verifier(), trust.distribution_digest(),
                trust.generation(), &evidence, at).map_err(protocol)
        };
        let binding = require_evidence()?;
        let consumer = AgentdRootAuthorityPeer {
            boot_id: request.consumer.boot_id.clone(), pid: request.consumer.pid,
            process_start_ticks: request.consumer.process_start_ticks,
        };
        let timeout = Duration::from_millis(self.session.config.timeout_ms.min(500));
        let lifetime = self.end.checked_duration_since(Instant::now())
            .filter(|value| !value.is_zero() && *value <= Duration::from_secs(300))
            .ok_or_else(|| protocol("the original pre-freeze Source scope expired"))?;
        let mut channel = original_owner_command_channel_v1(stream, consumer, request.consumer_uid,
            original_consumer_pidfd, timeout, lifetime).map_err(protocol)?;
        let startup_end = startup_end.min(self.end);
        wire::before(startup_end).map_err(protocol)?;
        // One actual cold read handles already-completed recovered Source.
        // Only Missing/Pending waits for the original publication path; there
        // is no Source polling, retry, new Task or second request allowance.
        if OriginalRootCircuitTaskCustodyV1::original_prefreeze_is_pending(&self.custody, &request)? {
            self.source_ready.wait_original(startup_end)?;
        }
        channel.check_peer_lifetime().map_err(protocol)?;
        self.require_current()?;
        OriginalRootCircuitTaskCustodyV1::read_original_prefreeze_source(&self.custody, &request)?;
        self.require_current()?;
        if require_evidence()? != binding { return Err(protocol("pre-freeze enrollment changed")); }
        let hint = ready::frame(binding, request.nonce)?;
        wire::before(startup_end).map_err(protocol)?;
        if channel.request(&hint).map_err(protocol)? != hint {
            return Err(protocol("the fixed Source readiness acknowledgment differs"));
        }
        wire::before(startup_end).map_err(protocol)?;
        channel.check_peer_lifetime().map_err(protocol)?;
        self.require_current()?;
        if require_evidence()? != binding { return Err(protocol("pre-freeze enrollment changed")); }
        // The ready exchange consumes frame 1 of the SAME 128-frame allowance.
        // It contains no Source data, owner, receipt, or completion authority.
        for id in 2..=wire::LIMIT {
            let expected = read_request(binding, request.nonce, id).map_err(protocol)?;
            let mut failure = None;
            let mut deadline = None;
            let exchanged = channel.exchange(|bytes| {
                let result = (|| -> Result<Vec<u8>, AgentdError> {
                    let until = (Instant::now() + timeout).min(self.end);
                    deadline = Some(until);
                    wire::before(until).map_err(protocol)?;
                    if bytes != expected || require_evidence()? != binding {
                        return Err(protocol("the fixed pre-freeze request differs"));
                    }
                    self.require_current()?;
                    let payload = OriginalRootCircuitTaskCustodyV1::read_original_prefreeze_source(
                        &self.custody, &request,
                    )?;
                    self.require_current()?;
                    if require_evidence()? != binding {
                        return Err(protocol("pre-freeze enrollment changed during read"));
                    }
                    let response = wire::response(&expected, &payload).map_err(protocol)?;
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
                    if require_evidence()? != binding {
                        return Err(protocol("pre-freeze enrollment changed after response"));
                    }
                    wire::before(deadline.ok_or_else(|| protocol("source deadline missing"))?)
                        .map_err(protocol)?;
                }
                Err(error) => return Err(failure.unwrap_or_else(|| protocol(error))),
            }
        }
        Err(protocol("the original Source request bound is exhausted"))
    }
}

fn protocol(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Protocol(format!("original pre-freeze Source loan: {error}"))
}
