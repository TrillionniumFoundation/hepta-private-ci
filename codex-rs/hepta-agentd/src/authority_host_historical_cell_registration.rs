//! The Cell baseline is registered before the original Initial enrollment ACK.
//! Root custody and current writer authority bracket the complete observation;
//! a non-Root peer cannot create this record or choose the original files.

use super::*;

impl HostAuthorityService {
    pub(crate) fn register_original_initial_cell(
        &self,
        slot: &RegisteredGenerationInitial,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        publisher: &OwnedFd,
        files: OriginalCellFiles,
        end: std::time::Instant,
    ) -> io::Result<RegisteredOriginalCellCaptureV1> {
        original_root()?;
        let root = Arc::clone(&slot.root);
        let target = &slot.profile.deployment.target;
        let owner = cell_owner(target)?;
        let mut retained = None;
        let (refusal, ()) = RootDataRefusalV1::create_fresh(
            Arc::clone(&root),
            RootDataKind::CellSnapshot,
            target,
            || {
                if std::time::Instant::now() >= end {
                    return Err(io::Error::other(
                        "original Cell enrollment deadline expired",
                    ));
                }
                self.with_initial_publication_context(config, registration, publisher, |proof| {
                    if slot.mode != RootGenerationInitialModeV1::Reserve
                        || slot.profile.writer != proof
                        || slot.profile.identity
                            != crate::neuron_generation_process_identity_digest_v1(&self.identity)
                                .map_err(io::Error::other)?
                                .to_string()
                    {
                        return Err(io::Error::other(
                            "original Initial Cell enrollment required",
                        ));
                    }
                    slot.require_profile()?;
                    slot.require_genesis()?;
                    slot.require_selection(
                        self.clock
                            .refresh_projection()
                            .map_err(io::Error::other)?
                            .observed_unix_ms,
                    )?;
                    files.require_original_cell_baseline()?;
                    let baseline = CellRecord {
                        schema: 1,
                        purpose: CELL_PURPOSE.into(),
                        initial_profile: slot.profile.binding.clone(),
                        identity: slot.profile.identity.clone(),
                        writer: proof,
                        publisher_epoch: registration.publisher_epoch,
                        publisher: CognitiveCheckpointPeerLifetime {
                            uid: config.peer_uid,
                            pid: registration.peer_pid,
                            boot_id: registration.boot_id.clone(),
                            process_start_ticks: registration.process_start_ticks,
                        },
                        peer_gid: config.peer_gid,
                        registered_identity: serde_json::to_string(
                            &registration.registered_identity,
                        )
                        .map_err(io::Error::other)?,
                        target: target.clone(),
                        files: (*files.file_pins()).clone(),
                        context: files.context_digest().to_string(),
                        phase: CellPhase::Enrolled,
                    };
                    let store = HostAuthorityFrontierStore::initialize(
                        Arc::clone(&root),
                        owner.clone(),
                        baseline.clone(),
                    )
                    .map_err(io::Error::other)?;
                    if store.load(&owner).map_err(io::Error::other)? != baseline {
                        return Err(io::Error::other(
                            "original Cell baseline acknowledgement differs",
                        ));
                    }
                    files.require_original_cell_baseline()?;
                    slot.require_genesis()?;
                    slot.require_profile()?;
                    slot.require_selection(
                        self.clock
                            .refresh_projection()
                            .map_err(io::Error::other)?
                            .observed_unix_ms,
                    )?;
                    retained = Some((store, baseline));
                    Ok(())
                })?;
                if std::time::Instant::now() >= end {
                    return Err(io::Error::other(
                        "original Cell enrollment ended during registration",
                    ));
                }
                Ok(())
            },
        )?;
        let (store, baseline) =
            retained.ok_or_else(|| io::Error::other("original Cell enrollment result missing"))?;
        Ok(RegisteredOriginalCellCaptureV1 {
            files,
            root,
            store,
            owner,
            baseline,
            refusal,
        })
    }
}
