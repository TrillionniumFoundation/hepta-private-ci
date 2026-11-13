//! Explicit V2 reservation and existing-only recovery through the same live
//! Root service. The V1 witness deployment DTO remains strict Root metadata;
//! these methods alone choose the separate V2 owner namespace and purpose.

use codex_hepta_neuron::observe_original_file_anchor_v1;

use super::super::profile::v2::DIRECTORY_V2;
use super::super::profile::v2::DurableQ24ModelFactoryProfileV2;
use super::super::profile::v2::LiveQ24ModelFactoryProfileV2;
use super::super::profile::v2::OWNER_V2;
use super::super::profile::v2::SOCKET_FILENAME_V2;
use super::super::profile::v2::WITNESS_FILENAME_V2;
use super::*;

impl HostAuthorityService {
    pub(crate) fn reserve_q24_model_factory_v2_for_profile(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner_pidfd: &OwnedFd,
        learning: &HostAuthorityLearningProfileV1,
        reservation: &HostAuthorityQ24ModelFactoryReservationV1,
        end: Instant,
    ) -> io::Result<()> {
        require_factory_end(end)?;
        self.with_learning_profile(
            config,
            registration,
            owner_pidfd,
            learning,
            |initial, _proof| {
                require_factory_end(end)?;
                let scope = learning.require_cell_scope(&initial)?;
                if self
                    .clock
                    .refresh_projection()
                    .map_err(io::Error::other)?
                    .observed_unix_ms
                    / 1000
                    >= initial.request.envelope.expiry_unix_seconds
                {
                    return Err(io::Error::other("expired work cannot reserve a V2 factory"));
                }
                let domain = witness_domain(config, reservation)?;
                let generation =
                    Generation::new(self.identity.spawn_generation).map_err(io::Error::other)?;
                let directory = config.state_dir.join(DIRECTORY_V2);
                require_factory_end(end)?;
                std::fs::DirBuilder::new().mode(0o700).create(&directory)?;
                File::open(&config.state_dir)?.sync_all()?;
                let journal = new_file(&directory.join("proposal.journal"))?;
                let witness = new_file(&reservation.witness_directory.join(WITNESS_FILENAME_V2))?;
                let profile = DurableQ24ModelFactoryProfileV2::reserve_description(
                    &initial,
                    &scope,
                    FilePin::capture(&journal)?,
                    FilePin::capture(&witness)?,
                    domain,
                    policy_digest(reservation)?,
                    generation,
                )?;
                let enrolled = FileAnchorWitnessStore::open(
                    witness,
                    JournalScope {
                        scope_digest: profile
                            .durable_binding()
                            .parse()
                            .map_err(io::Error::other)?,
                        objective_digest: initial.request.envelope.objective_digest,
                    },
                    generation,
                    WITNESS_RECORDS,
                )
                .map_err(io::Error::other)?;
                if enrolled.current().map_err(io::Error::other)?.is_some() {
                    return Err(io::Error::other("new V2 witness already has history"));
                }
                drop(enrolled);
                HostAuthorityFrontierStore::initialize(
                    RootAuthorityDirectory::open(&directory).map_err(io::Error::other)?,
                    OWNER_V2.into(),
                    FactoryRecord {
                        profile: ReservedFactoryProfile::DurableV2(profile),
                        epoch: 1,
                        material: None,
                    },
                )
                .map_err(io::Error::other)?;
                config.required_bind.verify()?;
                witness_domain(config, reservation)?;
                if self
                    .clock
                    .refresh_projection()
                    .map_err(io::Error::other)?
                    .observed_unix_ms
                    / 1000
                    >= initial.request.envelope.expiry_unix_seconds
                {
                    return Err(io::Error::other("V2 reservation crossed its work deadline"));
                }
                require_factory_end(end)
            },
        )?;
        require_factory_end(end)
    }

    pub(crate) fn open_q24_model_factory_v2(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner_pidfd: &OwnedFd,
        learning: &HostAuthorityLearningProfileV1,
        reservation_file: &Path,
        end: Instant,
    ) -> io::Result<RegisteredQ24ModelFactory> {
        require_factory_end(end)?;
        let reservation: HostAuthorityQ24ModelFactoryReservationV1 =
            read_root_json(reservation_file)?;
        let (factory, witness_scope, generation, original_anchor, retained) = self
            .with_learning_profile(
                config,
                registration,
                owner_pidfd,
                learning,
                |initial, proof| {
                    require_factory_end(end)?;
                    let scope = learning.require_cell_scope(&initial)?;
                    let domain = witness_domain(config, &reservation)?;
                    let directory = config.state_dir.join(DIRECTORY_V2);
                    let store: HostAuthorityFrontierStore<FactoryRecord> =
                        HostAuthorityFrontierStore::open(
                            RootAuthorityDirectory::open(&directory).map_err(io::Error::other)?,
                            OWNER_V2.into(),
                        )
                        .map_err(io::Error::other)?;
                    let retained = store.load(OWNER_V2).map_err(io::Error::other)?;
                    retained.validate()?;
                    let ReservedFactoryProfile::DurableV2(original) = &retained.profile else {
                        return Err(io::Error::other(
                            "V2 reopen cannot upgrade a legacy reservation",
                        ));
                    };
                    let journal_path = directory.join("proposal.journal");
                    let witness_path = reservation.witness_directory.join(WITNESS_FILENAME_V2);
                    let journal = open_file(&journal_path)?;
                    let witness = open_file(&witness_path)?;
                    DurableQ24ModelFactoryProfileV2::require_reserved_context(
                        original,
                        &initial,
                        &scope,
                        FilePin::capture(&journal)?,
                        FilePin::capture(&witness)?,
                        domain,
                        policy_digest(&reservation)?,
                    )?;
                    original.require_files(&journal, &witness)?;
                    let generation = original.original_generation()?;
                    let witness_scope = JournalScope {
                        scope_digest: original
                            .durable_binding()
                            .parse()
                            .map_err(io::Error::other)?,
                        objective_digest: initial.request.envelope.objective_digest,
                    };
                    // A decoder-only O_RDONLY observer cannot initialize or repair
                    // the original witness, even when recovery fails halfway.
                    let witness_observer = observe_file(&witness_path)?;
                    let original_anchor = observe_original_file_anchor_v1(
                        &witness_observer,
                        witness_scope,
                        generation,
                        WITNESS_RECORDS,
                    )
                    .map_err(io::Error::other)?;
                    let profile = LiveFactoryProfile::SessionV2(
                        LiveQ24ModelFactoryProfileV2::admit_current_session(
                            &self.identity,
                            &proof,
                            &initial,
                            &scope,
                            original.clone(),
                        )?,
                    );
                    let socket_path = config
                        .sockets
                        .observation
                        .parent()
                        .ok_or_else(|| io::Error::other("original Root lane parent required"))?
                        .join(SOCKET_FILENAME_V2);
                    let factory = RegisteredQ24ModelFactory {
                        original_b: None,
                        profile,
                        learning: learning.clone(),
                        reservation,
                        store,
                        journal_observer: observe_file(&journal_path)?,
                        witness_observer,
                        files: Some((journal, witness)),
                        socket_path,
                    };
                    if factory.current(config)? != retained {
                        return Err(io::Error::other("V2 reservation changed during recovery"));
                    }
                    require_factory_end(end)?;
                    Ok((
                        factory,
                        witness_scope,
                        generation,
                        original_anchor,
                        retained,
                    ))
                },
            )?;
        // The original writer context has completed all its postchecks before
        // this last physical witness read. No failed open initializes anything.
        require_factory_end(end)?;
        if factory.current(config)? != retained {
            return Err(io::Error::other(
                "V2 registry changed across original Root admission",
            ));
        }
        if observe_original_file_anchor_v1(
            &factory.witness_observer,
            witness_scope,
            generation,
            WITNESS_RECORDS,
        )
        .map_err(io::Error::other)?
            != original_anchor
        {
            return Err(io::Error::other(
                "V2 witness changed across original Root admission",
            ));
        }
        require_factory_end(end)?;
        Ok(factory)
    }
}
