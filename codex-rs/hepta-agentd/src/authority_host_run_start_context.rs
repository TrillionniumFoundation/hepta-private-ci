//! Live first-retain path in the same actual Initial registration. The mutex
//! guards CURRENT throughout physical observation, then the original writer
//! context must return successfully before durable Finalized is written.

use super::*;

impl HostAuthorityService {
    pub(super) fn require_run_start_registration(
        &self,
        slot: &RegisteredGenerationInitial,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        proof: &str,
    ) -> io::Result<()> {
        original_root()?;
        if slot.mode != RootGenerationInitialModeV1::Reserve
            || slot.profile.writer != proof
            || slot.profile.identity
                != crate::neuron_generation_process_identity_digest_v1(&self.identity)
                    .map_err(io::Error::other)?
                    .to_string()
            || slot.profile.deployment.target.scope().agent_id != self.identity.agent_id.as_str()
            || registration.checkpoint_owner_agent_id != self.identity.agent_id
            || registration.publisher_epoch == 0
        {
            return Err(io::Error::other(
                "original RunStart publisher registration differs",
            ));
        }
        self.checkpoint
            .as_ref()
            .ok_or_else(|| io::Error::other("original checkpoint publisher missing"))?
            .validate_peer(codex_hepta_contracts::HostIssuerPeer {
                uid: config.peer_uid,
                pid: registration.peer_pid,
            })?;
        slot.require_profile()?;
        slot.require_selection(
            self.clock
                .refresh_projection()
                .map_err(io::Error::other)?
                .observed_unix_ms,
        )
    }

    pub(crate) fn retain_initial_run_start(
        &self,
        retained: &RegisteredInitialRunStartRetentionV1,
        slot: &RegisteredGenerationInitial,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        publisher_pidfd: &OwnedFd,
        publication: &OriginalRunStartPublicationDataV1,
        request_id: u64,
        session_end: Instant,
    ) -> io::Result<Vec<u8>> {
        original_root()?;
        if retained.consumed.swap(true, Ordering::AcqRel) {
            return Err(io::Error::other(
                "original RunStart first-retain attempt consumed",
            ));
        }
        let request_end =
            session_end.min(Instant::now() + Duration::from_millis(config.timeout_ms));
        let mut state = retained
            .state
            .try_lock()
            .map_err(|_| io::Error::other("original RunStart retention busy"))?;
        let (next, reply) = RootDataRefusalV1::inspect(&retained.refusal, || {
            require_end(request_end)?;
            state.require_exact_unchecked()?;
            require_original(
                &state.expected.original,
                slot,
                config,
                registration,
                &self.identity,
            )?;
            publication.validate()?;
            if state.expected.phase != RetentionPhase::AwaitingLiveAppend
                || state.expected.observed.is_some()
            {
                return Err(io::Error::other(
                    "cold data cannot make a first RunStart ACK",
                ));
            }
            let mut observation = None;
            self.with_initial_publication_context(
                config,
                registration,
                publisher_pidfd,
                |proof| {
                    self.require_run_start_registration(slot, config, registration, &proof)?;
                    let current = slot
                        .current
                        .try_lock()
                        .map_err(|_| io::Error::other("initial CURRENT busy"))?;
                    let current = current
                        .as_ref()
                        .ok_or_else(|| io::Error::other("original Initial CURRENT missing"))?;
                    let before = NeuronGenerationCurrentOwnerV1::original_broker_head(current)
                        .map_err(io::Error::other)?;
                    let (signed, witness) =
                        crate::neuron_generation_current::initial_root::original_initial_record(
                            &slot.profile.prepared,
                            &before,
                        )
                        .map_err(io::Error::other)?
                        .ok_or_else(|| {
                            io::Error::other(
                                "original Initial publication required before RunStart retain",
                            )
                        })?;
                    let revocations = self.issuer.revocations()?;
                    if slot.verify_recorded_use(&signed, &witness)? != revocations {
                        return Err(io::Error::other("original Initial FinalUse differs"));
                    }
                    slot.require_genesis()?;
                    let now = self
                        .clock
                        .refresh_projection()
                        .map_err(io::Error::other)?
                        .observed_unix_ms;
                    let observed = OriginalInputPin::observe(
                        &state.expected.original.inputs,
                        &retained.files,
                        &self.identity,
                        &slot.profile.deployment.target,
                        publication,
                        config.peer_uid,
                        config.peer_gid,
                        now,
                    )?;
                    let confirmed_at = self
                        .clock
                        .refresh_projection()
                        .map_err(io::Error::other)?
                        .observed_unix_ms;
                    let confirmed = OriginalInputPin::observe(
                        &state.expected.original.inputs,
                        &retained.files,
                        &self.identity,
                        &slot.profile.deployment.target,
                        publication,
                        config.peer_uid,
                        config.peer_gid,
                        confirmed_at,
                    )?;
                    if confirmed != observed
                        || NeuronGenerationCurrentOwnerV1::original_broker_head(current)
                            .map_err(io::Error::other)?
                            != before
                        || slot.verify_recorded_use(&signed, &witness)? != revocations
                    {
                        return Err(io::Error::other(
                            "original RunStart/CURRENT/FinalUse changed",
                        ));
                    }
                    slot.require_genesis()?;
                    self.require_run_start_registration(slot, config, registration, &proof)?;
                    require_end(request_end)?;
                    observation = Some(RunStartObservation {
                        publication: publication.clone(),
                        frame_start: observed.frame_start,
                        frame_end: observed.frame_end,
                        observed_length: observed.observed_length,
                        observed_unix_ms: confirmed_at,
                        current: before,
                    });
                    Ok(())
                },
            )?;
            // This return is after the actual original pidfd/lease/revocation
            // context postchecks. A crash before it leaves the refusal Armed.
            require_end(request_end)?;
            let next =
                state.finalize_unchecked(observation.ok_or_else(|| {
                    io::Error::other("original live RunStart observation missing")
                })?)?;
            let reply = serde_json::to_vec(&OriginalRunStartRetentionResponseV1 {
                schema: 1,
                purpose: RUN_START_RETENTION_PURPOSE.into(),
                request_id,
                profile: slot.profile.binding.clone(),
                mode: slot.mode,
                publication: publication.clone(),
                retained: store::record_digest(&next)?.to_string(),
            })
            .map_err(io::Error::other)?;
            if reply.len() > 16 * 1024 {
                return Err(io::Error::other("original RunStart receipt exceeds bound"));
            }
            RootInitialRunStartFilesV1::with_original_files(&retained.files, |_, _, _| Ok(()))?;
            // The actual absolute end is checked after primary CAS/readback
            // and receipt construction, before this exact arm can become Ready.
            require_end(request_end)?;
            Ok((next, reply))
        })?;
        state.expected = next;
        Ok(reply)
    }
}

fn require_original(
    original: &OriginalRunStartRegistration,
    slot: &RegisteredGenerationInitial,
    config: &HostAuthorityServiceConfig,
    registration: &HostAuthorityRegistration,
    identity: &crate::AgentdIdentity,
) -> io::Result<()> {
    if original.initial_profile != slot.profile.binding
        || original.identity != slot.profile.identity
        || original.spawn_generation != identity.spawn_generation
        || original.writer != slot.profile.writer
        || original.target != slot.profile.deployment.target
        || original.target_files != slot.profile.target_files
        || original.publisher_epoch != registration.publisher_epoch
        || original.publisher_gid != config.peer_gid
        || original.publisher
            != (CognitiveCheckpointPeerLifetime {
                uid: config.peer_uid,
                pid: registration.peer_pid,
                boot_id: registration.boot_id.clone(),
                process_start_ticks: registration.process_start_ticks,
            })
    {
        return Err(io::Error::other(
            "RunStart registration belongs to a different original session",
        ));
    }
    Ok(())
}
