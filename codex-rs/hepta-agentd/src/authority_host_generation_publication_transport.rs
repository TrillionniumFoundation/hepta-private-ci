//! The actual original Root dispatch. Only derived preparation and the
//! original one-operation publication may mutate CURRENT. Readback never does.

use std::os::unix::net::UnixStream;

use crate::neuron_generation_current::types::Published;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;

use super::*;

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
    pub(crate) profile: PublicationProfile,
    pub(crate) head: CurrentHead,
}

impl HostAuthorityService {
    pub(crate) fn serve_generation_publication(
        &self,
        slot: &RegisteredGenerationPublication,
        learning: &RegisteredHostLearningCheckpointV1,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        stream: UnixStream,
        policy: HostAuthorityPeerPolicy,
        owner: OwnedFd,
    ) -> io::Result<()> {
        let sequence = 1;
        let pin = owner.try_clone()?;
        let channel = HostAuthorityPeerChannel::from_stream(stream, policy, owner)
            .map_err(io::Error::other)?;
        self.serve_original_publication_channel(
            slot,
            learning,
            config,
            registration,
            pin,
            channel,
            sequence,
            None,
        )
    }

    pub(crate) fn serve_generation_publication_until(
        &self,
        slot: &RegisteredGenerationPublication,
        learning: &RegisteredHostLearningCheckpointV1,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        stream: UnixStream,
        policy: HostAuthorityPeerPolicy,
        owner: OwnedFd,
        phase: &crate::authority_host_same_actor_q24_phase_publication::OriginalPhasePublicationContext<'_>,
    ) -> io::Result<()> {
        let _closing = crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop::new(phase.gate);
        phase.require_original(slot)?;
        let _stream_stop = phase.gate.retain_original_stream(&stream)?;
        let pin = owner.try_clone()?;
        let channel = HostAuthorityPeerChannel::from_stream_until(
            stream,
            policy,
            owner,
            phase.gate.deadline().instant(),
        )
        .map_err(io::Error::other)?;
        self.serve_original_publication_channel(
            slot,
            learning,
            config,
            registration,
            pin,
            channel,
            1,
            Some(phase),
        )?;
        Err(io::Error::other(
            "required original phase publication lane ended",
        ))
    }

    fn serve_original_publication_channel(
        &self,
        slot: &RegisteredGenerationPublication,
        learning: &RegisteredHostLearningCheckpointV1,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        pin: OwnedFd,
        mut channel: HostAuthorityPeerChannel,
        mut sequence: u64,
        phase: Option<&crate::authority_host_same_actor_q24_phase_publication::OriginalPhasePublicationContext<'_>>,
    ) -> io::Result<()> {
        while channel
            .exchange(|bytes| {
                let _admission = phase
                    .map(|context| context.gate.enter_original_lane())
                    .transpose()
                    .map_err(|_| codex_hepta_contracts::HostIssuerTransportError::Unavailable)?;
                if let Some(context) = phase {
                    context.require_original(slot).map_err(|_| {
                        codex_hepta_contracts::HostIssuerTransportError::Unavailable
                    })?;
                }
                let response = self.with_learning_profile(
                    config,
                    registration,
                    &pin,
                    &learning.profile,
                    |initial, proof| {
                        let scope = learning.profile.require_cell_scope(&initial)?;
                        if slot.profile.initial != initial.head_digest.to_string()
                            || slot.profile.scope != scope.binding().to_string()
                            || slot.profile.writer != proof
                            || slot.profile.identity
                                != crate::neuron_generation_process_identity_digest_v1(
                                    &self.identity,
                                )
                                .map_err(io::Error::other)?
                                .to_string()
                        {
                            return Err(io::Error::other("original Root learning context changed"));
                        }
                        let request: Request =
                            serde_json::from_slice(bytes).map_err(io::Error::other)?;
                        if request.schema != 1
                            || request.purpose != PURPOSE
                            || request.request_id != sequence
                            || (request.profile != slot.profile.binding
                                && !(sequence == 1
                                    && request.profile.is_empty()
                                    && matches!(&request.command, Command::Observe)))
                        {
                            return Err(io::Error::other(
                                "publication purpose/scope/sequence differs",
                            ));
                        }
                        sequence = sequence
                            .checked_add(1)
                            .ok_or_else(|| io::Error::other("publication sequence exhausted"))?;
                        slot.require_profile()?;
                        slot.require_history(learning, &scope)?;
                        slot.require_previous()?;
                        let now = self
                            .clock
                            .refresh_projection()
                            .map_err(io::Error::other)?
                            .observed_unix_ms;
                        slot.require_selection(now)?;
                        let before = slot
                            .current
                            .original_broker_head()
                            .map_err(io::Error::other)?;
                        let original_revocations = self.issuer.revocations()?;
                        let intent = &slot.profile.intent;
                        let original_digest =
                            intent.digest().map_err(io::Error::other)?.to_string();
                        let mut after = before.clone();
                        let mut fresh_grant = None;
                        match &request.command {
                            Command::Observe => {
                                if before.current == intent.target {
                                    let record = before
                                        .published
                                        .as_ref()
                                        .filter(|record| record.intent == *intent)
                                        .ok_or_else(|| {
                                            io::Error::other("original published record missing")
                                        })?;
                                    if slot.verify_retained(&record.signed, &record.witness)?
                                        != original_revocations
                                    {
                                        return Err(io::Error::other(
                                            "original published revocations differ",
                                        ));
                                    }
                                    slot.target.observe().map_err(io::Error::other)?;
                                } else if before.current == intent.previous {
                                    slot.target
                                        .require_original_unwritten_or_genesis()
                                        .map_err(io::Error::other)?;
                                } else {
                                    return Err(io::Error::other("another CURRENT generation"));
                                }
                            }
                            Command::Prepare {
                                expected,
                                intent: requested,
                            } => {
                                if *expected != head_digest(&before)?
                                    || *requested != original_digest
                                    || before.current != intent.previous
                                    || before
                                        .prepared
                                        .as_ref()
                                        .is_some_and(|value| value != intent)
                                    || now / 1000 >= initial.request.envelope.expiry_unix_seconds
                                {
                                    return Err(io::Error::other(
                                        "original preparation cut or deadline differs",
                                    ));
                                }
                                slot.target
                                    .require_original_unwritten_or_genesis()
                                    .map_err(io::Error::other)?;
                                after.prepared = Some(intent.clone());
                            }
                            Command::Publish {
                                expected,
                                intent: requested,
                                signed,
                                witness,
                            } => {
                                if *expected != head_digest(&before)?
                                    || *requested != original_digest
                                    || before.current != intent.previous
                                    || before.prepared.as_ref() != Some(intent)
                                {
                                    return Err(io::Error::other(
                                        "original prepared CURRENT required for fresh publication",
                                    ));
                                }
                                require_fresh_window(
                                    now,
                                    initial.request.envelope.expiry_unix_seconds,
                                    signed,
                                    witness,
                                )?;
                                if slot.verify_retained(signed, witness)? != original_revocations {
                                    return Err(io::Error::other(
                                        "original entered consumer and live issuer differ",
                                    ));
                                }
                                slot.require_genesis()?;
                                after.current = intent.target.clone();
                                after.prepared = None;
                                after.initial = None;
                                after.published = Some(Published {
                                    intent: intent.clone(),
                                    signed: signed.clone(),
                                    witness: witness.clone(),
                                    signed_grant_digest:
                                        crate::neuron_generation_current::signed_grant_digest(
                                            signed,
                                        )
                                        .map_err(io::Error::other)?
                                        .into_array(),
                                });
                                fresh_grant = Some((signed, witness));
                            }
                        }
                        let response = Response {
                            schema: 1,
                            purpose: PURPOSE.into(),
                            request_id: request.request_id,
                            profile: slot.profile.clone(),
                            head: after.clone(),
                        };
                        // Check the exact success frame before crossing any CURRENT effect.
                        let raw = serde_json::to_vec(&response).map_err(io::Error::other)?;
                        if raw.len() > 16 * 1024 {
                            return Err(io::Error::other("publication reply bound"));
                        }
                        if let Some(context) = phase {
                            context.require_original(slot)?;
                        }
                        match &request.command {
                            Command::Observe => {}
                            Command::Prepare { .. } => {
                                slot.current
                                    .original_broker_prepare(intent)
                                    .map_err(io::Error::other)?;
                            }
                            Command::Publish {
                                signed, witness, ..
                            } => {
                                slot.current
                                    .original_broker_publish(intent, signed, witness)
                                    .map_err(io::Error::other)?;
                            }
                        }
                        // There is no cross-owner transaction: any post-effect loss is
                        // unavailable/uncertain and permanently closes the original lane.
                        slot.require_profile()?;
                        slot.require_history(learning, &scope)?;
                        slot.require_previous()?;
                        let after_time = self
                            .clock
                            .refresh_projection()
                            .map_err(io::Error::other)?
                            .observed_unix_ms;
                        slot.require_selection(after_time)?;
                        if let Some((signed, witness)) = fresh_grant {
                            slot.require_genesis()?;
                            require_fresh_window(
                                after_time,
                                initial.request.envelope.expiry_unix_seconds,
                                signed,
                                witness,
                            )?;
                            if slot.verify_retained(signed, witness)? != original_revocations {
                                return Err(io::Error::other(
                                    "consumer changed after original publication",
                                ));
                            }
                        }
                        if matches!(&request.command, Command::Observe)
                            && after.current == intent.target
                        {
                            let record = after.published.as_ref().ok_or_else(|| {
                                io::Error::other("original published record missing after read")
                            })?;
                            if slot.verify_retained(&record.signed, &record.witness)?
                                != original_revocations
                            {
                                return Err(io::Error::other(
                                    "original consumer changed during retained read",
                                ));
                            }
                            slot.target.observe().map_err(io::Error::other)?;
                        }
                        if self.issuer.revocations()? != original_revocations
                            || slot
                                .current
                                .original_broker_head()
                                .map_err(io::Error::other)?
                                != after
                        {
                            return Err(io::Error::other(
                                "original publication completion uncertain",
                            ));
                        }
                        Ok(raw)
                    },
                )
                .map_err(|_| codex_hepta_contracts::HostIssuerTransportError::Unavailable)?;
                if let Some(context) = phase {
                    context.require_original(slot).map_err(|_| {
                        codex_hepta_contracts::HostIssuerTransportError::Unavailable
                    })?;
                }
                Ok(response)
            })
            .map_err(io::Error::other)?
        {
            if let Some(context) = phase {
                context.require_original(slot)?;
            }
        }
        Ok(())
    }
}

fn require_fresh_window(
    now: u64,
    work_expiry: u64,
    signed: &SignedFinalUseGrant,
    witness: &VerifiedUseTokenWitnessV1,
) -> io::Result<()> {
    if now < signed.grant.not_before_unix_ms
        || now >= signed.grant.expires_at_unix_ms
        || now / 1000 >= work_expiry
        || witness.verified_at_unix_ms > now
    {
        return Err(io::Error::other(
            "original live publication grant window differs",
        ));
    }
    Ok(())
}
