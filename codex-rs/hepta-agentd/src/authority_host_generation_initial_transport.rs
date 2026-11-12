//! Fixed initial-purpose requests. Peer data cannot choose a target, profile,
//! directory, issuer or consumer. CURRENT is written only after original
//! selection, physical target and FinalUse read-side checks.

use super::*;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use std::os::unix::net::UnixStream;

#[path = "authority_host_historical_source_transport.rs"]
mod source_capture;

use source_capture::OriginalSourceCaptureExchange;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Request {
    pub(crate) schema: u8,
    pub(crate) purpose: String,
    pub(crate) request_id: u64,
    pub(crate) profile: String,
    pub(crate) command: Command,
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum Command {
    CaptureSource,
    CaptureAck,
    Observe,
    Prepare {
        expected: String,
        intent: String,
    },
    Publish {
        expected: String,
        intent: String,
        signed: SignedFinalUseGrant,
        witness: VerifiedUseTokenWitnessV1,
    },
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Response {
    pub(crate) schema: u8,
    pub(crate) purpose: String,
    pub(crate) request_id: u64,
    pub(crate) profile: InitialProfile,
    pub(crate) mode: RootGenerationInitialModeV1,
    pub(crate) head: Option<CurrentHead>,
}

impl HostAuthorityService {
    pub(crate) fn serve_generation_initial(
        &self,
        slot: &RegisteredGenerationInitial,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        stream: UnixStream,
        policy: HostAuthorityPeerPolicy,
        owner: OwnedFd,
        source_capability: Option<&Mutex<Option<crate::RootHistoricalSourceCaptureCapabilityV1>>>,
    ) -> io::Result<()> {
        let mut sequence = 1_u64;
        let pin = owner.try_clone()?;
        let mut channel = HostAuthorityPeerChannel::from_stream(stream, policy, owner)
            .map_err(io::Error::other)?;
        let mut source_capture = OriginalSourceCaptureExchange::new(
            self,
            slot,
            config,
            registration,
            &pin,
            source_capability,
        );
        let result = (|| {
            while channel
                .exchange(|bytes| {
                    let request: Request = serde_json::from_slice(bytes)
                        .map_err(|_| codex_hepta_contracts::HostIssuerTransportError::Unavailable)?;
                    if source_capture.handles(&request) {
                        return source_capture
                            .exchange(&request, &mut sequence)
                            .map_err(|_| codex_hepta_contracts::HostIssuerTransportError::Unavailable);
                    }
                    let mut encoded_response = None;
                    self.with_initial_publication_context(config, registration, &pin, |proof| {
                        if slot.profile.writer != proof
                            || slot.profile.identity
                                != crate::neuron_generation_process_identity_digest_v1(&self.identity)
                                    .map_err(io::Error::other)?
                                    .to_string()
                        {
                            return Err(io::Error::other("original initial Root context changed"));
                        }
                        if request.schema != 1
                            || request.purpose != PURPOSE
                            || request.request_id != sequence
                            || (request.profile != slot.profile.binding
                                && !(sequence == 1
                                    && request.profile.is_empty()
                                    && matches!(&request.command, Command::Observe)))
                        {
                            return Err(io::Error::other("initial purpose/profile/sequence differs"));
                        }
                        sequence = sequence
                            .checked_add(1)
                            .ok_or_else(|| io::Error::other("initial sequence exhausted"))?;
                        slot.require_profile()?;
                        let now = self
                            .clock
                            .refresh_projection()
                            .map_err(io::Error::other)?
                            .observed_unix_ms;
                        slot.require_selection(now)?;
                        let revocations = self.issuer.revocations()?;
                        let mut current: std::sync::MutexGuard<
                            '_,
                            Option<NeuronGenerationCurrentOwnerV1>,
                        > = slot
                            .current
                            .try_lock()
                            .map_err(|_| io::Error::other("initial CURRENT busy"))?;
                        let before = read_current(slot, current.as_ref())?;
                        let mut after = before.clone();
                        match &request.command {
                            Command::CaptureSource | Command::CaptureAck => {
                                return Err(io::Error::other(
                                    "source capture requires its dedicated terminal purpose",
                                ));
                            }
                            Command::Observe => {
                                require_observation(slot, before.as_ref(), &revocations)?;
                            }
                            Command::Prepare { expected, intent } => {
                                if slot.mode != RootGenerationInitialModeV1::Reserve
                                    || before.is_some()
                                    || *expected != head_digest(&before)?
                                    || *intent != slot.profile.intent
                                {
                                    return Err(io::Error::other("initial CURRENT is not vacant"));
                                }
                                slot.require_target(/*fresh*/ true)?;
                                after = Some(slot.profile.prepared.clone());
                            }
                            Command::Publish {
                                expected,
                                intent,
                                signed,
                                witness,
                            } => {
                                if slot.mode != RootGenerationInitialModeV1::Reserve
                                    || before.as_ref() != Some(&slot.profile.prepared)
                                    || *expected != head_digest(&before)?
                                    || *intent != slot.profile.intent
                                    || signed.grant.binding != slot.profile.final_use
                                {
                                    return Err(io::Error::other("exact initial preparation required"));
                                }
                                require_fresh_window(now, signed, witness)?;
                                if slot.verify_retained(signed, witness)? != revocations {
                                    return Err(io::Error::other(
                                        "original entered initial consumer differs",
                                    ));
                                }
                                slot.require_genesis()?;
                                after = Some(
                                    crate::neuron_generation_current::initial_root::original_initial_next(
                                        &slot.profile.prepared,
                                        signed,
                                        witness,
                                    )
                                    .map_err(io::Error::other)?,
                                );
                            }
                        }
                        let response = Response {
                            schema: 1,
                            purpose: PURPOSE.into(),
                            request_id: request.request_id,
                            profile: slot.profile.clone(),
                            mode: slot.mode,
                            head: after.clone(),
                        };
                        let raw = serde_json::to_vec(&response).map_err(io::Error::other)?;
                        if raw.len() > 16 * 1024 {
                            return Err(io::Error::other("initial response bound"));
                        }
                        // No write occurs before the full reply and all preconditions
                        // are known. The original initializer itself rejects any
                        // existing CURRENT; absence is never inferred from an error.
                        match &request.command {
                            Command::CaptureSource | Command::CaptureAck => {
                                return Err(io::Error::other(
                                    "source capture requires its dedicated terminal purpose",
                                ));
                            }
                            Command::Observe => {}
                            Command::Prepare { .. } => {
                                let mut selected: std::sync::MutexGuard<
                                    '_,
                                    AgentdSelectedGenerationV1,
                                > = slot
                                    .selected
                                    .try_lock()
                                    .map_err(|_| io::Error::other("initial selection busy"))?;
                                if let Err(error) = selected.revalidate_original_artifacts(
                                    &slot.artifacts,
                                    self.clock
                                        .refresh_projection()
                                        .map_err(io::Error::other)?
                                        .observed_unix_ms,
                                ) {
                                    slot.fence()?;
                                    return Err(io::Error::other(error));
                                }
                                if selected.observation().digest().to_string()
                                    != slot.profile.selection
                                {
                                    slot.fence()?;
                                    return Err(io::Error::other(
                                        "initial selection changed before prepare",
                                    ));
                                }
                                slot.require_target(/*fresh*/ true)?;
                                let (owner, prepared) =
                                    NeuronGenerationCurrentOwnerV1::prepare_initial(
                                        slot.root.clone(),
                                        slot.profile.deployment.operation.clone(),
                                        slot.profile.deployment.target.clone(),
                                        &selected,
                                    )
                                    .map_err(io::Error::other)?;
                                if prepared.intent_digest().to_string() != slot.profile.intent
                                    || read_current(slot, Some(&owner))?.as_ref()
                                        != Some(&slot.profile.prepared)
                                {
                                    slot.fence()?;
                                    return Err(io::Error::other(
                                        "initial preparation acknowledgement uncertain",
                                    ));
                                }
                                *current = Some(owner);
                            }
                            Command::Publish {
                                signed, witness, ..
                            } => {
                                current
                                    .as_ref()
                                    .ok_or_else(|| {
                                        io::Error::other("original initial CURRENT missing")
                                    })?
                                    .original_broker_initial_publish(
                                        &slot.profile.prepared,
                                        signed,
                                        witness,
                                    )
                                    .map_err(io::Error::other)?;
                            }
                        }
                        slot.require_profile()?;
                        let after_time = self
                            .clock
                            .refresh_projection()
                            .map_err(io::Error::other)?
                            .observed_unix_ms;
                        slot.require_selection(after_time)?;
                        match &request.command {
                            Command::CaptureSource | Command::CaptureAck => {
                                return Err(io::Error::other(
                                    "source capture requires its dedicated terminal purpose",
                                ));
                            }
                            Command::Observe => {
                                require_observation(slot, after.as_ref(), &revocations)?
                            }
                            Command::Prepare { .. } => {
                                slot.require_target(/*fresh*/ true)?;
                            }
                            Command::Publish {
                                signed, witness, ..
                            } => {
                                slot.require_genesis()?;
                                require_fresh_window(after_time, signed, witness)?;
                                if slot.verify_recorded_use(signed, witness)? != revocations {
                                    slot.fence()?;
                                    return Err(io::Error::other(
                                        "initial consumer changed after publication",
                                    ));
                                }
                            }
                        }
                        if self.issuer.revocations()? != revocations
                            || read_current(slot, current.as_ref())? != after
                        {
                            slot.fence()?;
                            return Err(io::Error::other("original initial completion uncertain"));
                        }
                        #[cfg(test)]
                        if matches!(&request.command, Command::Publish { .. })
                            && DROP_NEXT_PUBLICATION_ACK
                                .swap(false, std::sync::atomic::Ordering::AcqRel)
                        {
                            return Err(io::Error::new(
                                io::ErrorKind::BrokenPipe,
                                "controlled original post-CAS acknowledgement loss",
                            ));
                        }
                        encoded_response = Some(raw);
                        Ok(())
                    })
                    .map_err(|_| codex_hepta_contracts::HostIssuerTransportError::Unavailable)?;
                    encoded_response.ok_or(codex_hepta_contracts::HostIssuerTransportError::Unavailable)
                })
                .map_err(io::Error::other)?
            {}
            Ok(())
        })();
        source_capture.finish(result)
    }
}

fn read_current(
    slot: &RegisteredGenerationInitial,
    current: Option<&NeuronGenerationCurrentOwnerV1>,
) -> io::Result<Option<CurrentHead>> {
    match current
        .map(|current: &NeuronGenerationCurrentOwnerV1| current.original_broker_head())
        .transpose()
    {
        Ok(head) => Ok(head),
        Err(error) => {
            slot.fence()?;
            Err(io::Error::other(error))
        }
    }
}

fn require_observation(
    slot: &RegisteredGenerationInitial,
    head: Option<&CurrentHead>,
    revocations: &codex_hepta_contracts::FinalUseRevocations,
) -> io::Result<()> {
    let Some(head) = head else {
        if slot.mode != RootGenerationInitialModeV1::Reserve {
            return Err(io::Error::other(
                "recovery cannot initialize missing CURRENT",
            ));
        }
        return slot.require_target(/*fresh*/ true);
    };
    let record = match crate::neuron_generation_current::initial_root::original_initial_record(
        &slot.profile.prepared,
        head,
    ) {
        Ok(record) => record,
        Err(error) => {
            slot.fence()?;
            return Err(io::Error::other(error));
        }
    };
    if let Some((signed, witness)) = record {
        if &slot.verify_recorded_use(&signed, &witness)? != revocations {
            slot.fence()?;
            return Err(io::Error::other("retained initial consumer changed"));
        }
        slot.observe_published_target()?;
    } else {
        slot.require_target(/*fresh*/ false)?;
    }
    Ok(())
}

fn require_fresh_window(
    now: u64,
    signed: &SignedFinalUseGrant,
    witness: &VerifiedUseTokenWitnessV1,
) -> io::Result<()> {
    if now < signed.grant.not_before_unix_ms
        || now >= signed.grant.expires_at_unix_ms
        || witness.verified_at_unix_ms > now
    {
        return Err(io::Error::other(
            "original live initial grant window differs",
        ));
    }
    Ok(())
}

// Test-only fault after the real CURRENT CAS and original postconditions. No
// peer request or production configuration can select this fault.
#[cfg(test)]
static DROP_NEXT_PUBLICATION_ACK: std::sync::atomic::AtomicBool =
    std::sync::atomic::AtomicBool::new(false);

#[cfg(test)]
pub(crate) fn drop_next_test_publication_ack() {
    DROP_NEXT_PUBLICATION_ACK.store(true, std::sync::atomic::Ordering::Release);
}
