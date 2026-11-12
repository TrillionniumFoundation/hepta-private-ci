//! Guarded primary operations. Every possible primary read belongs to the
//! independent refusal arm; CAS and final real postchecks finish before Ready.

use super::*;

impl RunStartRecordStore {
    pub(super) fn initialize_unchecked(
        root: Arc<RootAuthorityDirectory>,
        original: OriginalRunStartRegistration,
    ) -> io::Result<Self> {
        let owner = owner(&original.target)?;
        let expected = RetainedRunStartRecord {
            original,
            phase: RetentionPhase::AwaitingLiveAppend,
            observed: None,
        };
        let store = HostAuthorityFrontierStore::initialize(root, owner.clone(), expected.clone())
            .map_err(io::Error::other)?;
        let state = Self {
            store,
            owner,
            expected,
        };
        state.require_exact_unchecked()?;
        Ok(state)
    }

    pub(super) fn require_exact_unchecked(&self) -> io::Result<()> {
        if self.store.load(&self.owner).map_err(io::Error::other)? != self.expected {
            return Err(io::Error::other("original Root RunStart primary changed"));
        }
        Ok(())
    }

    pub(super) fn finalize_unchecked(
        &self,
        observed: RunStartObservation,
    ) -> io::Result<RetainedRunStartRecord> {
        self.require_exact_unchecked()?;
        if self.expected.phase != RetentionPhase::AwaitingLiveAppend
            || self.expected.observed.is_some()
        {
            return Err(io::Error::other(
                "RunStart first live retain was already consumed",
            ));
        }
        let mut next = self.expected.clone();
        next.phase = RetentionPhase::Finalized;
        next.observed = Some(observed);
        self.store
            .compare_and_set(&self.owner, &self.expected, &next)
            .map_err(io::Error::other)?;
        if self.store.load(&self.owner).map_err(io::Error::other)? != next {
            return Err(io::Error::other("RunStart finalization readback differs"));
        }
        Ok(next)
    }
}

impl HostAuthorityService {
    /// Actual Reserve enrollment calls this before accepting the Initial lane.
    /// The fresh arm precedes the first profile/trust/journal physical read and
    /// spans the original writer context's final pidfd/lease postchecks.
    pub(crate) fn register_initial_run_start_retention(
        &self,
        slot: &RegisteredGenerationInitial,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        publisher_pidfd: &OwnedFd,
        files: Arc<RootInitialRunStartFilesV1>,
        session_end: Instant,
    ) -> io::Result<RegisteredInitialRunStartRetentionV1> {
        original_root()?;
        require_end(session_end)?;
        if slot.mode != RootGenerationInitialModeV1::Reserve {
            return Err(io::Error::other(
                "Recover cannot register a new RunStart ACK",
            ));
        }
        let (refusal, state) = RootDataRefusalV1::create_fresh(
            Arc::clone(&slot.root),
            RootDataKind::RunStart,
            &slot.profile.deployment.target,
            || {
                let mut captured = None;
                self.with_initial_publication_context(
                    config,
                    registration,
                    publisher_pidfd,
                    |proof| {
                        self.require_run_start_registration(slot, config, registration, &proof)?;
                        let held = slot
                            .current
                            .try_lock()
                            .map_err(|_| io::Error::other("initial CURRENT busy"))?;
                        if held.is_some() {
                            return Err(io::Error::other(
                                "RunStart baseline must precede initial CURRENT",
                            ));
                        }
                        slot.require_target(/*fresh*/ true)?;
                        let inputs = OriginalInputPin::capture(
                            &files,
                            &self.identity,
                            config.peer_uid,
                            config.peer_gid,
                        )?;
                        let original = OriginalRunStartRegistration {
                            schema: 1,
                            purpose: RECORD_PURPOSE.into(),
                            initial_profile: slot.profile.binding.clone(),
                            identity: slot.profile.identity.clone(),
                            spawn_generation: self.identity.spawn_generation,
                            writer: proof,
                            publisher_epoch: registration.publisher_epoch,
                            publisher: CognitiveCheckpointPeerLifetime {
                                uid: config.peer_uid,
                                pid: registration.peer_pid,
                                boot_id: registration.boot_id.clone(),
                                process_start_ticks: registration.process_start_ticks,
                            },
                            publisher_gid: config.peer_gid,
                            target: slot.profile.deployment.target.clone(),
                            target_files: slot.profile.target_files.clone(),
                            inputs,
                        };
                        let state = RunStartRecordStore::initialize_unchecked(
                            Arc::clone(&slot.root),
                            original,
                        )?;
                        if OriginalInputPin::capture(
                            &files,
                            &self.identity,
                            config.peer_uid,
                            config.peer_gid,
                        )? != state.expected.original.inputs
                        {
                            return Err(io::Error::other(
                                "RunStart baseline changed before original registration",
                            ));
                        }
                        slot.require_target(/*fresh*/ true)?;
                        self.require_run_start_registration(
                            slot,
                            config,
                            registration,
                            &state.expected.original.writer,
                        )?;
                        state.require_exact_unchecked()?;
                        captured = Some(state);
                        Ok(())
                    },
                )?;
                // This is after the real context's complete postcheck, inside
                // the same durable arm. No external bool substitutes for it.
                require_end(session_end)?;
                captured.ok_or_else(|| io::Error::other("original RunStart registration missing"))
            },
        )?;
        Ok(RegisteredInitialRunStartRetentionV1 {
            files,
            state: Mutex::new(state),
            refusal,
            consumed: AtomicBool::new(false),
        })
    }
}

impl RootRetainedRunStartDataV1 {
    /// No original Initial runtime or first-retain capability is reconstructed.
    pub(crate) fn open_finalized(
        root: Arc<RootAuthorityDirectory>,
        target: &CellGenerationOwnerBindingV1,
    ) -> io::Result<Self> {
        original_root()?;
        let refusal =
            RootDataRefusalV1::open_existing(Arc::clone(&root), RootDataKind::RunStart, target)?;
        let state = RootDataRefusalV1::inspect(&refusal, || {
            let owner = owner(target)?;
            let store =
                HostAuthorityFrontierStore::open(root, owner.clone()).map_err(io::Error::other)?;
            let expected: RetainedRunStartRecord = store.load(&owner).map_err(io::Error::other)?;
            if expected.original.schema != 1
                || expected.original.purpose != RECORD_PURPOSE
                || &expected.original.target != target
                || expected.phase != RetentionPhase::Finalized
                || expected.observed.is_none()
            {
                return Err(io::Error::other("original finalized RunStart data missing"));
            }
            Ok(RunStartRecordStore {
                store,
                owner,
                expected,
            })
        })?;
        Ok(Self { state, refusal })
    }

    pub(crate) fn readback_digest(&self) -> io::Result<Digest32> {
        RootDataRefusalV1::inspect(&self.refusal, || {
            self.state.require_exact_unchecked()?;
            record_digest(&self.state.expected)
        })
    }

    /// Re-read original data only. Authentication is checked at the Root's
    /// durably retained observation time, not treated as today's permission.
    /// The caller must independently join actual retirement, current AuthBus
    /// and the new recipient's Root learning scope before using this history.
    pub(crate) fn read_original_publication(
        &self,
        files: &RootInitialRunStartFilesV1,
        original_identity: &crate::AgentdIdentity,
    ) -> io::Result<RunStartReadOnlyFrameV1> {
        RootDataRefusalV1::inspect(&self.refusal, || {
            self.state.require_exact_unchecked()?;
            let original = &self.state.expected.original;
            if original.identity
                != crate::neuron_generation_process_identity_digest_v1(original_identity)
                    .map_err(io::Error::other)?
                    .to_string()
                || original.spawn_generation != original_identity.spawn_generation
                || original.target.scope().agent_id != original_identity.agent_id.as_str()
            {
                return Err(io::Error::other(
                    "retained RunStart original identity differs",
                ));
            }
            let observed = self.state.expected.observed.as_ref().ok_or_else(|| {
                io::Error::other("original finalized RunStart observation missing")
            })?;
            let frame = OriginalInputPin::observe(
                &original.inputs,
                files,
                original_identity,
                &original.target,
                &observed.publication,
                original.publisher.uid,
                original.publisher_gid,
                observed.observed_unix_ms,
            )?;
            if frame.frame_start != observed.frame_start
                || frame.frame_end != observed.frame_end
                || frame.observed_length < observed.observed_length
            {
                return Err(io::Error::other("retained RunStart physical cut differs"));
            }
            self.state.require_exact_unchecked()?;
            Ok(frame)
        })
    }
}

pub(super) fn record_digest(record: &RetainedRunStartRecord) -> io::Result<Digest32> {
    Ok(Digest32::of_parts(&[
        b"hepta.root.original-run-start-retained.v1\0",
        &serde_json::to_vec(record).map_err(io::Error::other)?,
    ]))
}
