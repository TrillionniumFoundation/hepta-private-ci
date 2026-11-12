//! Root records the exact empty four-file baseline before Initial enrollment
//! ACK. The actual enrolled public trust fixes roles; no daemon payload does.

use super::*;

impl HostAuthorityService {
    pub(crate) fn register_original_initial_ledger(
        &self,
        slot: &RegisteredGenerationInitial,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        publisher: &OwnedFd,
        files: OriginalLedgerFiles,
        end: std::time::Instant,
    ) -> io::Result<RegisteredOriginalLedgerCaptureV1> {
        original_root()?;
        let target = &slot.profile.deployment.target;
        let owner = ledger_owner(target)?;
        let mut retained = None;
        let (refusal, ()) = RootDataRefusalV1::create_fresh(
            Arc::clone(&slot.root),
            RootDataKind::HistoricalLedger,
            target,
            || {
                if std::time::Instant::now() >= end {
                    return Err(io::Error::other(
                        "original Ledger enrollment deadline expired",
                    ));
                }
                self.with_initial_publication_context(config, registration, publisher, |proof| {
                    if slot.mode != RootGenerationInitialModeV1::Reserve
                        || files.deployment.initial != slot.profile.deployment
                        || slot.profile.writer != proof
                        || registration.registered_identity.identity()? != self.identity
                        || slot.profile.identity
                            != crate::neuron_generation_process_identity_digest_v1(&self.identity)
                                .map_err(io::Error::other)?
                                .to_string()
                    {
                        return Err(io::Error::other(
                            "original Initial Ledger enrollment required",
                        ));
                    }
                    slot.require_profile()?;
                    slot.require_genesis()?;
                    let now = self
                        .clock
                        .refresh_projection()
                        .map_err(io::Error::other)?
                        .observed_unix_ms;
                    slot.require_selection(now)?;
                    let trust = Arc::clone(&files.deployment.trust).bind_original(
                        &self.identity,
                        &slot.profile.deployment,
                        now,
                    )?;
                    if Some(&trust.pin) != slot.profile.learning_trust.as_ref() {
                        return Err(io::Error::other(
                            "Ledger metadata differs from original Root trust",
                        ));
                    }
                    let (_, generator, observer) = trust
                        .read_original_payload(now)?
                        .activate_pinned_genesis(now / 1_000)?;
                    let original = files
                        .deployment
                        .ledger
                        .configuration(generator, observer, now / 1_000)
                        .map_err(io::Error::other)?;
                    files.require_empty_baseline()?;
                    let baseline = LedgerRecord {
                        schema: 1,
                        purpose: LEDGER_PURPOSE.into(),
                        initial_profile: slot.profile.binding.clone(),
                        identity: slot.profile.identity.clone(),
                        registered_identity: serde_json::to_string(
                            &registration.registered_identity,
                        )
                        .map_err(io::Error::other)?,
                        writer: proof,
                        publisher_epoch: registration.publisher_epoch,
                        publisher: CognitiveCheckpointPeerLifetime {
                            uid: config.peer_uid,
                            pid: registration.peer_pid,
                            boot_id: registration.boot_id.clone(),
                            process_start_ticks: registration.process_start_ticks,
                        },
                        peer_gid: config.peer_gid,
                        target: target.clone(),
                        files: (*files.file_pins()).clone(),
                        metadata: files.deployment.metadata_digest().to_string(),
                        registered_at: now / 1_000,
                        trust: trust.pin.clone(),
                        phase: LedgerPhase::Enrolled,
                    };
                    let store = HostAuthorityFrontierStore::initialize(
                        Arc::clone(&slot.root),
                        owner.clone(),
                        baseline.clone(),
                    )
                    .map_err(io::Error::other)?;
                    if store.load(&owner).map_err(io::Error::other)? != baseline {
                        return Err(io::Error::other(
                            "original Ledger baseline acknowledgement differs",
                        ));
                    }
                    files.require_empty_baseline()?;
                    slot.require_genesis()?;
                    slot.require_profile()?;
                    slot.require_selection(
                        self.clock
                            .refresh_projection()
                            .map_err(io::Error::other)?
                            .observed_unix_ms,
                    )?;
                    retained = Some((store, baseline, original));
                    Ok(())
                })?;
                if std::time::Instant::now() >= end {
                    return Err(io::Error::other(
                        "original Ledger enrollment ended during registration",
                    ));
                }
                Ok(())
            },
        )?;
        let (store, baseline, original) = retained
            .ok_or_else(|| io::Error::other("original Ledger enrollment result missing"))?;
        Ok(RegisteredOriginalLedgerCaptureV1 {
            files,
            store,
            owner,
            baseline,
            config: original,
            refusal,
            end,
        })
    }
}
