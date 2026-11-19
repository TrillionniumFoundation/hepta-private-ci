//! Explicit reserve, open-only recovery, and one-shot owner custody transfer.

use std::fs::OpenOptions;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::OpenOptionsExt;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use codex_hepta_types::Generation;

use super::*;
use crate::authority_host_config::read_root_json;

#[path = "authority_host_q24_model_registration_v2.rs"]
mod v2;

/// Root administration only: reserve one exact operation under its original
/// live writer and daemon pidfd. Existing or partial state is never repaired.
pub fn register_host_q24_model_factory(
    config_file: &Path,
    registration_file: &Path,
    learning_profile_file: &Path,
    reservation_file: &Path,
    owner_pidfd: &OwnedFd,
) -> io::Result<HostAuthorityQ24ModelFactoryProfileV1> {
    let config = read_root_json(config_file)?;
    let registration = read_root_json(registration_file)?;
    let reservation = read_root_json(reservation_file)?;
    let service =
        crate::authority_host_runtime::open_registered_writer(&config, &registration, owner_pidfd)?;
    let learning = service.open_registered_learning_checkpoint(
        &config,
        &registration,
        owner_pidfd,
        learning_profile_file,
    )?;
    let end = Instant::now()
        .checked_add(Duration::from_millis(config.timeout_ms))
        .ok_or_else(|| io::Error::other("original factory registration deadline overflow"))?;
    service.reserve_q24_model_factory_for_profile(
        &config,
        &registration,
        owner_pidfd,
        &learning.profile,
        &reservation,
        end,
    )
}

impl HostAuthorityService {
    /// The original live service reserves this Root-derived scoped profile.
    /// Existing/partial state remains an error; the original end cannot renew.
    pub(crate) fn reserve_q24_model_factory_for_profile(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner_pidfd: &OwnedFd,
        learning: &HostAuthorityLearningProfileV1,
        reservation: &HostAuthorityQ24ModelFactoryReservationV1,
        end: Instant,
    ) -> io::Result<HostAuthorityQ24ModelFactoryProfileV1> {
        require_factory_end(end)?;
        let profile = self.with_learning_profile(
            config,
            registration,
            owner_pidfd,
            learning,
            |initial, proof| {
                require_factory_end(end)?;
                let scope = learning.require_cell_scope(&initial)?;
                let now = self
                    .clock
                    .refresh_projection()
                    .map_err(io::Error::other)?
                    .observed_unix_ms
                    / 1000;
                if now >= initial.request.envelope.expiry_unix_seconds {
                    return Err(io::Error::other(
                        "expired work cannot reserve a new Model factory",
                    ));
                }
                let domain = witness_domain(config, reservation)?;
                let directory = config.state_dir.join(DIRECTORY);
                require_factory_end(end)?;
                std::fs::DirBuilder::new().mode(0o700).create(&directory)?;
                File::open(&config.state_dir)?.sync_all()?;
                let journal = new_file(&directory.join("proposal.journal"))?;
                let witness = new_file(&witness_path(reservation))?;
                let profile = HostAuthorityQ24ModelFactoryProfileV1::new(
                    &self.identity,
                    &proof,
                    &initial,
                    &scope,
                    FilePin::capture(&journal)?,
                    FilePin::capture(&witness)?,
                    domain,
                    policy_digest(reservation)?,
                )?;
                let enrolled = FileAnchorWitnessStore::open(
                    witness,
                    JournalScope {
                        scope_digest: profile.binding().parse().map_err(io::Error::other)?,
                        objective_digest: initial.request.envelope.objective_digest,
                    },
                    Generation::new(self.identity.spawn_generation).map_err(io::Error::other)?,
                    WITNESS_RECORDS,
                )
                .map_err(io::Error::other)?;
                if enrolled.current().map_err(io::Error::other)?.is_some() {
                    return Err(io::Error::other("new factory witness already has history"));
                }
                drop(enrolled);
                HostAuthorityFrontierStore::initialize(
                    RootAuthorityDirectory::open(&directory).map_err(io::Error::other)?,
                    OWNER.into(),
                    FactoryRecord {
                        profile: ReservedFactoryProfile::LegacyV1(profile.clone()),
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
                    return Err(io::Error::other(
                        "factory reservation crossed its original work deadline",
                    ));
                }
                require_factory_end(end)?;
                Ok(profile)
            },
        )?;
        require_factory_end(end)?;
        Ok(profile)
    }

    pub(crate) fn open_q24_model_factory(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner_pidfd: &OwnedFd,
        learning: &HostAuthorityLearningProfileV1,
        reservation_file: &Path,
    ) -> io::Result<RegisteredQ24ModelFactory> {
        let reservation: HostAuthorityQ24ModelFactoryReservationV1 =
            read_root_json(reservation_file)?;
        self.with_learning_profile(
            config,
            registration,
            owner_pidfd,
            learning,
            |initial, proof| {
                let scope = learning.require_cell_scope(&initial)?;
                let domain = witness_domain(config, &reservation)?;
                let directory = config.state_dir.join(DIRECTORY);
                let store: HostAuthorityFrontierStore<FactoryRecord> =
                    HostAuthorityFrontierStore::open(
                        RootAuthorityDirectory::open(&directory).map_err(io::Error::other)?,
                        OWNER.into(),
                    )
                    .map_err(io::Error::other)?;
                let retained = store.load(OWNER).map_err(io::Error::other)?;
                retained.validate()?;
                let journal_path = directory.join("proposal.journal");
                let witness_path = witness_path(&reservation);
                let journal = open_file(&journal_path)?;
                let witness = open_file(&witness_path)?;
                let profile = HostAuthorityQ24ModelFactoryProfileV1::new(
                    &self.identity,
                    &proof,
                    &initial,
                    &scope,
                    FilePin::capture(&journal)?,
                    FilePin::capture(&witness)?,
                    domain,
                    policy_digest(&reservation)?,
                )?;
                if retained.profile != ReservedFactoryProfile::LegacyV1(profile.clone()) {
                    return Err(io::Error::other(
                        "original factory profile or reserved file changed",
                    ));
                }
                profile.require_files(&journal, &witness)?;
                let socket_path = config
                    .sockets
                    .observation
                    .parent()
                    .ok_or_else(|| io::Error::other("original Root lane parent required"))?
                    .join("q24-model-proposal-factory-v1.sock");
                let factory = RegisteredQ24ModelFactory {
                    original_b: None,
                    profile: LiveFactoryProfile::LegacyV1(profile),
                    learning: learning.clone(),
                    reservation,
                    store,
                    journal_observer: observe_file(&journal_path)?,
                    witness_observer: observe_file(&witness_path)?,
                    files: Some((journal, witness)),
                    socket_path,
                };
                factory.current(config)?;
                Ok(factory)
            },
        )
    }

    pub(crate) fn seal_q24_model_factory_offer(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner_pidfd: &OwnedFd,
        factory: &mut RegisteredQ24ModelFactory,
    ) -> io::Result<RootQ24ModelFactoryOfferV1> {
        // Consume rights before capture. Even a refused/uncertain offer cannot
        // mint a second writable alias through this retained session.
        let (journal, witness) = factory
            .files
            .take()
            .ok_or_else(|| io::Error::other("factory owner rights already consumed"))?;
        self.with_learning_profile(
            config,
            registration,
            owner_pidfd,
            &factory.learning,
            |initial, proof| {
                let before = factory.current(config)?;
                LiveFactoryProfile::require_context(
                    &factory.profile,
                    &self.identity,
                    &proof,
                    &initial,
                    &factory.learning.require_cell_scope(&initial)?,
                )?;
                factory.profile.require_files(&journal, &witness)?;
                let stat = std::fs::read_to_string("/proc/self/stat")?;
                let start = stat
                    .rsplit_once(") ")
                    .and_then(|(_, fields)| fields.split_whitespace().nth(19))
                    .and_then(|value| value.parse::<u64>().ok())
                    .filter(|value| *value != 0)
                    .ok_or_else(|| io::Error::other("original Root process start missing"))?;
                let bundle = Q24ModelFactoryBootstrap {
                    profile: factory.profile.clone(),
                    root: CognitiveCheckpointPeerLifetime {
                        uid: 0,
                        pid: std::process::id(),
                        boot_id: registration.boot_id.clone(),
                        process_start_ticks: start,
                    },
                    consumer: CognitiveCheckpointPeerLifetime {
                        uid: config.peer_uid,
                        pid: registration.peer_pid,
                        boot_id: registration.boot_id.clone(),
                        process_start_ticks: registration.process_start_ticks,
                    },
                    identity: registration.registered_identity.clone(),
                    socket_path: factory.socket_path.clone(),
                };
                let bytes = serde_json::to_vec(&bundle).map_err(io::Error::other)?;
                let bootstrap = crate::authority_host_bootstrap_seal::seal_bytes(&bytes)?;
                if factory.current(config)? != before {
                    return Err(io::Error::other(
                        "factory registration changed during capture",
                    ));
                }
                Ok(RootQ24ModelFactoryOfferV1 {
                    bootstrap,
                    journal,
                    witness,
                })
            },
        )
    }
}

impl FactoryRecord {
    pub(super) fn validate(&self) -> io::Result<()> {
        match (self.epoch, &self.material) {
            (1, None) => Ok(()),
            (2, Some(value))
                if value
                    .parse::<Digest32>()
                    .is_ok_and(|digest| !digest.is_zero() && digest.to_string() == *value) =>
            {
                Ok(())
            }
            _ => Err(io::Error::other(
                "invalid registered factory epoch/material",
            )),
        }
    }
}

impl RegisteredQ24ModelFactory {
    pub(super) fn current(&self, config: &HostAuthorityServiceConfig) -> io::Result<FactoryRecord> {
        config.required_bind.verify()?;
        RootAuthorityDirectory::open(&config.state_dir).map_err(io::Error::other)?;
        witness_domain(config, &self.reservation)?;
        self.profile
            .require_observers(&self.journal_observer, &self.witness_observer)?;
        // Reopen observed path identities as well: an unlinked/replaced owner
        // cannot remain valid merely because Root still holds its old inode.
        self.profile.require_observers(
            &observe_file(
                &config
                    .state_dir
                    .join(self.profile.directory())
                    .join("proposal.journal"),
            )?,
            &observe_file(
                &self
                    .reservation
                    .witness_directory
                    .join(self.profile.witness_filename()),
            )?,
        )?;
        let current = self
            .store
            .load(self.profile.store_owner())
            .map_err(io::Error::other)?;
        current.validate()?;
        if current.profile != self.profile.reserved() {
            return Err(io::Error::other(
                "original factory reservation was replaced",
            ));
        }
        Ok(current)
    }
}

fn require_factory_end(end: Instant) -> io::Result<()> {
    if Instant::now() >= end {
        return Err(io::Error::other(
            "original factory registration deadline expired",
        ));
    }
    Ok(())
}

fn witness_domain(
    config: &HostAuthorityServiceConfig,
    reservation: &HostAuthorityQ24ModelFactoryReservationV1,
) -> io::Result<Digest32> {
    policy_digest(reservation)?;
    if reservation.schema_version != 1
        || !reservation
            .witness_directory
            .starts_with(&reservation.witness_bind.mountpoint)
        || reservation.witness_directory.starts_with(&config.state_dir)
        || config.state_dir.starts_with(&reservation.witness_directory)
        || (
            reservation.witness_bind.device,
            reservation.witness_bind.inode,
        ) == (config.required_bind.device, config.required_bind.inode)
    {
        return Err(io::Error::other(
            "separate original protected witness domain required",
        ));
    }
    reservation.witness_bind.verify()?;
    RootAuthorityDirectory::open(&reservation.witness_directory).map_err(io::Error::other)?;
    let path = reservation
        .witness_directory
        .to_str()
        .ok_or_else(|| io::Error::other("UTF8 witness domain required"))?;
    Ok(Digest32::of_parts(&[
        b"hepta.root.q24-witness-domain.v1\0",
        path.as_bytes(),
        &reservation.witness_bind.device.to_be_bytes(),
        &reservation.witness_bind.inode.to_be_bytes(),
    ]))
}

fn policy_digest(reservation: &HostAuthorityQ24ModelFactoryReservationV1) -> io::Result<Digest32> {
    let value = reservation
        .local_policy_digest
        .parse::<Digest32>()
        .map_err(io::Error::other)?;
    if value.is_zero() || value.to_string() != reservation.local_policy_digest {
        return Err(io::Error::other(
            "canonical precommitted local policy required",
        ));
    }
    Ok(value)
}

fn witness_path(reservation: &HostAuthorityQ24ModelFactoryReservationV1) -> PathBuf {
    reservation
        .witness_directory
        .join("q24-model-proposal-factory-v1.witness")
}

fn new_file(path: &Path) -> io::Result<File> {
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
        .open(path)?;
    file.sync_all()?;
    File::open(
        path.parent()
            .ok_or_else(|| io::Error::other("owner parent required"))?,
    )?
    .sync_all()?;
    Ok(file)
}

fn open_file(path: &Path) -> io::Result<File> {
    OpenOptions::new()
        .read(true)
        .write(true)
        .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
        .open(path)
}

fn observe_file(path: &Path) -> io::Result<File> {
    OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
        .open(path)
}

#[cfg(test)]
#[path = "authority_host_q24_model_store_tests.rs"]
mod tests;
