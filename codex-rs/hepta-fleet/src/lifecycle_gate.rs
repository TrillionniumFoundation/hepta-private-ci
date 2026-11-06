//! Linux advisory exclusion on the existing per-agent run directory inode.
//! Every acquisition opens a new file description. No lock file is created,
//! repaired or shared through File::try_clone, and contention never waits.

use crate::FleetRegistryError;
use std::fs::File;
use std::fs::Metadata;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;

pub(super) enum LifecycleGateMode {
    Shared,
    Exclusive,
}

struct PinnedDirectory {
    path: PathBuf,
    held: File,
    identity: (u64, u64, u32, u32, u32),
}

impl PinnedDirectory {
    fn identity(metadata: &Metadata) -> (u64, u64, u32, u32, u32) {
        (metadata.dev(), metadata.ino(), metadata.uid(), metadata.gid(), metadata.mode())
    }

    fn verify(&self) -> Result<(), FleetRegistryError> {
        let actual = self.held.metadata()?;
        let named = self.path.symlink_metadata()?;
        if !actual.is_dir()
            || !named.is_dir()
            || Self::identity(&actual) != self.identity
            || Self::identity(&named) != self.identity
            || self.path.canonicalize()? != self.path
        {
            return Err(FleetRegistryError::Corrupt(
                "lifecycle gate directory identity or physical path changed".into(),
            ));
        }
        Ok(())
    }
}

pub(super) struct LifecycleGate {
    // The first descriptor is the run directory and owns the actual flock.
    // Ancestors use O_PATH, so search-only parents need not grant enumeration.
    directories: Vec<PinnedDirectory>,
}

impl LifecycleGate {
    pub(super) fn acquire(path: &Path, mode: LifecycleGateMode) -> Result<Self, FleetRegistryError> {
        if !path.is_absolute() || path.canonicalize()? != path {
            return Err(FleetRegistryError::Corrupt(
                "lifecycle gate requires the original absolute physical run directory".into(),
            ));
        }
        let mut directories = Vec::new();
        for (index, directory) in path.ancestors().enumerate() {
            let before = directory.symlink_metadata()?;
            if !before.is_dir() {
                return Err(FleetRegistryError::Corrupt(
                    "lifecycle gate ancestor is not a physical directory".into(),
                ));
            }
            let access = if index == 0 { 0 } else { libc::O_PATH };
            let held = OpenOptions::new().read(true)
                .custom_flags(access | libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK)
                .open(directory)?;
            let node = PinnedDirectory {
                path: directory.to_owned(), held, identity: PinnedDirectory::identity(&before),
            };
            node.verify()?;
            directories.push(node);
        }
        let gate = Self { directories };
        let result = match mode {
            LifecycleGateMode::Shared => gate.directories[0].held.try_lock_shared(),
            LifecycleGateMode::Exclusive => gate.directories[0].held.try_lock(),
        };
        match result {
            Ok(()) => {},
            Err(TryLockError::WouldBlock) => {
                return Err(io::Error::new(io::ErrorKind::WouldBlock,
                    "another lifecycle writer or retained reader owns this agent run directory").into());
            }
            Err(TryLockError::Error(error)) => return Err(error.into()),
        }
        gate.verify()?;
        Ok(gate)
    }

    pub(super) fn verify(&self) -> Result<(), FleetRegistryError> {
        for directory in &self.directories {
            directory.verify()?;
        }
        Ok(())
    }
}

impl crate::FleetRegistry {
    /// Run a synchronous read operation while Linux lifecycle publishers for
    /// this exact agent are excluded. This is not an effect grant or a signer.
    /// A conflict is WouldBlock before calling `operation`; it is never retried.
    /// The operation must not reenter a lifecycle writer or await a peer ACK.
    ///
    /// Cooperating writers use this same inode. Advisory locks cannot prevent
    /// privileged namespace replacement or writes by an older/noncooperating
    /// binary. Observed identity changes fail closed, including after I/O;
    /// such failure does not roll back or permit retrying that operation.
    pub fn try_with_current_spawn_lifecycle<T>(
        &self,
        agent_id: &codex_hepta_contracts::AgentId,
        spawn_generation: u64,
        lifecycle_generation: u64,
        operation: impl FnOnce() -> T,
    ) -> Result<T, FleetRegistryError> {
        let layout = self.layout().agent(agent_id);
        let gate = LifecycleGate::acquire(layout.run_root(), LifecycleGateMode::Shared)?;
        let record = self.load_agent_for_spawn(agent_id, spawn_generation)?;
        if record.lifecycle.generation != lifecycle_generation {
            return Err(FleetRegistryError::StaleGeneration {
                agent_id: agent_id.clone(), expected: lifecycle_generation,
                current: record.lifecycle.generation,
            });
        }
        if !matches!(record.lifecycle.lifecycle, crate::AgentLifecycle::Starting | crate::AgentLifecycle::Running) {
            return Err(FleetRegistryError::Invalid(
                "only the exact current Starting or Running lifecycle may enter this read boundary".into(),
            ));
        }
        gate.verify()?;
        let result = operation();
        gate.verify()?;
        if self.load_agent_for_spawn(agent_id, spawn_generation)?.lifecycle != record.lifecycle {
            return Err(FleetRegistryError::Corrupt(
                "original lifecycle changed while its shared gate was held".into(),
            ));
        }
        Ok(result)
    }
}
