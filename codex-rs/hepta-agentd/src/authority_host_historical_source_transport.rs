//! Terminal, zero-payload source capture over the original authenticated lane.
//! Root retains the fixed inputs and unique capability. A notification supplies
//! neither a source observation nor authority to read a historical experience.

use super::*;
use crate::RootHistoricalSourceCaptureCapabilityV1;
use crate::RootHistoricalSourceCaptureReceiptV1;
use crate::authority_host_service::generation_initial::historical_source_handoff::RootHistoricalSourceHandoffV1;
use crate::authority_host_service::generation_initial::historical_source_pin::RootHistoricalSourcePinV1;

pub(crate) const SOURCE_CAPTURE_PURPOSE: &str = "runtime.circuit.historical-source-capture.v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum SourceCapturePhase {
    Captured,
    Acknowledged,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct SourceCaptureResponse {
    pub(crate) schema: u8,
    pub(crate) purpose: String,
    pub(crate) request_id: u64,
    pub(crate) profile: InitialProfile,
    pub(crate) mode: RootGenerationInitialModeV1,
    pub(crate) pin: String,
    pub(crate) phase: SourceCapturePhase,
}

pub(super) struct OriginalSourceCaptureExchange<'a> {
    service: &'a HostAuthorityService,
    slot: &'a RegisteredGenerationInitial,
    config: &'a HostAuthorityServiceConfig,
    registration: &'a HostAuthorityRegistration,
    owner: &'a OwnedFd,
    capability: Option<&'a Mutex<Option<RootHistoricalSourceCaptureCapabilityV1>>>,
    receipt: Option<RootHistoricalSourceCaptureReceiptV1>,
    handoff: Option<RootHistoricalSourceHandoffV1>,
    begun: bool,
    acknowledged: bool,
}

impl<'a> OriginalSourceCaptureExchange<'a> {
    pub(super) fn new(
        service: &'a HostAuthorityService,
        slot: &'a RegisteredGenerationInitial,
        config: &'a HostAuthorityServiceConfig,
        registration: &'a HostAuthorityRegistration,
        owner: &'a OwnedFd,
        capability: Option<&'a Mutex<Option<RootHistoricalSourceCaptureCapabilityV1>>>,
    ) -> Self {
        Self {
            service,
            slot,
            config,
            registration,
            owner,
            capability,
            receipt: None,
            handoff: None,
            begun: false,
            acknowledged: false,
        }
    }

    pub(super) fn handles(&self, request: &Request) -> bool {
        self.begun
            || matches!(
                &request.command,
                Command::CaptureSource | Command::CaptureAck
            )
    }

    pub(super) fn exchange(
        &mut self,
        request: &Request,
        sequence: &mut u64,
    ) -> io::Result<Vec<u8>> {
        self.begun = true;
        if self.acknowledged
            || request.schema != 1
            || request.purpose != SOURCE_CAPTURE_PURPOSE
            || request.profile != self.slot.profile.binding
            || request.request_id != *sequence
        {
            return Err(io::Error::other("original source capture request differs"));
        }
        self.with_original_context(|| Ok(()))?;
        *sequence = sequence
            .checked_add(1)
            .ok_or_else(|| io::Error::other("original source capture sequence exhausted"))?;
        let phase = match &request.command {
            Command::CaptureSource if self.receipt.is_none() => {
                let capability: RootHistoricalSourceCaptureCapabilityV1 = self
                    .capability
                    .ok_or_else(|| io::Error::other("Root source capture was not enabled"))?
                    .try_lock()
                    .map_err(|_| io::Error::other("Root source capture capability busy"))?
                    .take()
                    .ok_or_else(|| io::Error::other("Root source capture capability consumed"))?;
                // The precheck's entire writer context and CURRENT guard have
                // ended. The independent worker can now enter that context.
                self.receipt = Some(capability.capture()?);
                SourceCapturePhase::Captured
            }
            Command::CaptureAck if self.receipt.is_some() => SourceCapturePhase::Acknowledged,
            _ => {
                return Err(io::Error::other(
                    "source capture requires its one terminal ACK",
                ));
            }
        };
        let receipt = self
            .receipt
            .as_ref()
            .ok_or_else(|| io::Error::other("original source capture receipt missing"))?;
        receipt.require_original_capture_session()?;
        let retained = RootHistoricalSourcePinV1::open_existing(
            Arc::clone(&self.slot.root),
            &self.slot.profile.deployment.target,
        )?;
        if retained.readback_digest()? != receipt.pin_digest() {
            return Err(io::Error::other("original Root source capture pin changed"));
        }
        let reply = serde_json::to_vec(&SourceCaptureResponse {
            schema: 1,
            purpose: SOURCE_CAPTURE_PURPOSE.into(),
            request_id: request.request_id,
            profile: self.slot.profile.clone(),
            mode: self.slot.mode,
            pin: receipt.pin_digest().to_string(),
            phase,
        })
        .map_err(io::Error::other)?;
        if reply.len() > 16 * 1024 {
            return Err(io::Error::other("source capture reply bound"));
        }
        match phase {
            SourceCapturePhase::Captured => {
                let mut pending = None;
                let result = self.with_original_context(|| {
                    pending = Some(RootHistoricalSourceHandoffV1::begin(
                        self.slot,
                        self.config,
                        self.registration,
                        receipt,
                    )?);
                    Ok(())
                });
                self.handoff = pending;
                result?;
            }
            SourceCapturePhase::Acknowledged => {
                let mut handoff = self
                    .handoff
                    .take()
                    .ok_or_else(|| io::Error::other("original pending handoff missing"))?;
                // ACK belongs to this exact original publisher and request
                // sequence. Its durable transition occurs inside that context.
                let result = self.with_original_context(|| {
                    RootHistoricalSourceHandoffV1::acknowledge(&mut handoff)
                });
                self.handoff = Some(handoff);
                result?;
                receipt.require_original_capture_session()?;
                RootHistoricalSourceHandoffV1::finalize_after_verified_context(
                    self.handoff
                        .as_mut()
                        .ok_or_else(|| io::Error::other("original acknowledged handoff missing"))?,
                )?;
                RootHistoricalSourceHandoffV1::open_finalized(
                    Arc::clone(&self.slot.root),
                    &self.slot.profile.deployment.target,
                )?;
                receipt.require_original_capture_session()?;
                self.acknowledged = true;
            }
        }
        Ok(reply)
    }

    fn with_original_context(&self, action: impl FnOnce() -> io::Result<()>) -> io::Result<()> {
        if let Some(receipt) = &self.receipt {
            receipt.require_original_capture_session()?;
        }
        self.service.with_initial_publication_context(
            self.config,
            self.registration,
            self.owner,
            |proof| {
                if self.slot.mode != RootGenerationInitialModeV1::Reserve
                    || self.slot.profile.writer != proof
                    || self.slot.profile.identity
                        != crate::neuron_generation_process_identity_digest_v1(
                            &self.service.identity,
                        )
                        .map_err(io::Error::other)?
                        .to_string()
                {
                    return Err(io::Error::other("original source capture context changed"));
                }
                self.slot.require_profile()?;
                self.slot.require_selection(
                    self.service
                        .clock
                        .refresh_projection()
                        .map_err(io::Error::other)?
                        .observed_unix_ms,
                )?;
                let current = self
                    .slot
                    .current
                    .try_lock()
                    .map_err(|_| io::Error::other("original Initial CURRENT busy"))?;
                let head = read_current(self.slot, current.as_ref())?
                    .ok_or_else(|| io::Error::other("original Initial publication missing"))?;
                crate::neuron_generation_current::initial_root::original_initial_record(
                    &self.slot.profile.prepared,
                    &head,
                )
                .map_err(io::Error::other)?
                .ok_or_else(|| io::Error::other("original Initial is not published"))?;
                require_observation(self.slot, Some(&head), &self.service.issuer.revocations()?)?;
                action()
            },
        )?;
        if let Some(receipt) = &self.receipt {
            receipt.require_original_capture_session()?;
        }
        Ok(())
    }

    pub(super) fn finish(&mut self, result: io::Result<()>) -> io::Result<()> {
        // Once the original peer's data handoff is durably finalized, a clean EOF
        // or its normal process exit cannot revoke that completed data handoff.
        // Transport errors still propagate; none become learning authority.
        if self.begun && !self.acknowledged {
            let refused = match result {
                Err(error) => error,
                Ok(()) => io::Error::other("original source capture peer ACK missing"),
            };
            // Make handoff unavailable before attempting the data pin fence.
            // Both attempts run even if one durable store is unavailable.
            let handoff_fence = self
                .handoff
                .as_mut()
                .map(RootHistoricalSourceHandoffV1::fence)
                .transpose();
            let pin_fence = RootHistoricalSourcePinV1::open_existing(
                Arc::clone(&self.slot.root),
                &self.slot.profile.deployment.target,
            )
            .and_then(|pin| pin.fence());
            if handoff_fence.is_err() || pin_fence.is_err() {
                return Err(io::Error::other(format!(
                    "source handoff refused: {refused}; handoff fence: {handoff_fence:?}; pin fence: {pin_fence:?}"
                )));
            }
            return Err(refused);
        }
        result
    }
}

#[cfg(test)]
#[path = "authority_host_historical_source_transport_tests.rs"]
mod tests;
