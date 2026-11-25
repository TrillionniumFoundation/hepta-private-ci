//! One trusted launch-ready confirmation; no runtime registration protocol.
use super::*;
use std::fs::File;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::Ordering;

pub(super) struct RequiredMaterialStartup {
    root: PathBuf,
    directory: File,
    state: AtomicU8,
}

#[repr(u8)]
enum StartupState {
    Pending,
    Installing,
    Registering,
    Confirmed,
    Failed,
}

impl RequiredMaterialStartup {
    pub(super) fn is_pending(&self) -> bool {
        self.state.load(Ordering::Acquire) == StartupState::Pending as u8
    }

    fn open(root: &Path) -> io::Result<Self> {
        codex_hepta_contracts::RootAuthorityDirectory::open(root).map_err(io::Error::other)?;
        let directory = std::fs::OpenOptions::new().read(true)
            .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC).open(root)?;
        let state = Self { root: root.to_path_buf(), directory, state: AtomicU8::new(StartupState::Pending as u8) };
        state.verify_directory()?;
        Ok(state)
    }

    pub(super) fn begin_install(&self) -> io::Result<()> {
        self.state.compare_exchange(StartupState::Pending as u8, StartupState::Installing as u8,
            Ordering::AcqRel, Ordering::Acquire)
            .map(|_| ()).map_err(|_| io::Error::other("material install requires pending startup"))
    }

    pub(super) fn installed(&self) {
        self.state.store(StartupState::Pending as u8, Ordering::Release);
    }

    pub(super) fn fail(&self) {
        self.state.store(StartupState::Failed as u8, Ordering::Release);
    }

    pub(super) fn verify_directory(&self) -> io::Result<()> {
        codex_hepta_contracts::RootAuthorityDirectory::open(&self.root).map_err(io::Error::other)?;
        let actual = std::fs::symlink_metadata(&self.root)?;
        let retained = self.directory.metadata()?;
        if (actual.dev(), actual.ino()) != (retained.dev(), retained.ino()) {
            return Err(io::Error::other("fixed startup material archive changed"));
        }
        Ok(())
    }
}

impl HostAuthorityService {
    /// Require the original recovered-owner-ready handshake for this launch.
    /// Call before bootstrap capture/serving. The archive path is supplied once
    /// by trusted Root configuration and held by identity; no peer selects it.
    /// Until confirmation, only proof/feed and original checkpoint/frontier
    /// reads are available. No issuer signature or checkpoint mutation is made.
    pub fn with_required_material_startup(mut self, archive_root: &Path) -> io::Result<Self> {
        let checkpoint = self.checkpoint.as_ref().ok_or_else(|| io::Error::other("registered checkpoint required"))?;
        if self.bootstrap.is_some() || self.material_startup.is_some()
            || checkpoint.material_attempted.load(Ordering::Acquire)
        {
            return Err(io::Error::other("required material startup must be fixed before bootstrap"));
        }
        self.material_startup = Some(RequiredMaterialStartup::open(archive_root)?);
        Ok(self)
    }

    /// Trusted Root launch control only, after this fixed Host's sole original
    /// recovery factory reports ready and before protected bind/writer release.
    /// This zero-argument method operates on this same served object. It starts
    /// no detached work and confirms no arbitrary path, cut, generation or grant.
    /// A failed first registration permanently closes the checkpoint; neither
    /// disconnection nor a second call may repair/retry it in this launch.
    pub fn confirm_recovered_owner_ready(&self) -> io::Result<()> {
        let startup = self.material_startup.as_ref().ok_or_else(|| io::Error::other("required material startup missing"))?;
        startup.state.compare_exchange(StartupState::Pending as u8, StartupState::Registering as u8,
            Ordering::AcqRel, Ordering::Acquire)
            .map_err(|_| io::Error::other("recovered owner readiness was already attempted"))?;
        let result = (|| {
            if self.checkpoint.as_ref().and_then(|checkpoint| checkpoint.recovered.as_ref())
                .is_some_and(|recovered| !recovered.installed.load(Ordering::Acquire))
            {
                return Err(io::Error::other("original recovered owner material was not installed"));
            }
            startup.verify_directory()?;
            self.register_material_archive_for_root(&startup.root)?;
            startup.verify_directory()?;
            // Original whole Current, proof, actual processes, both frontiers
            // and the final protected clock are checked after blocking I/O.
            // Capture makes no sequence, ticket or permission and retains no
            // second issuer. The existing public bootstrap does not change.
            self.capture_public_bootstrap_before_return(|| {
                startup.state.compare_exchange(StartupState::Registering as u8, StartupState::Confirmed as u8,
                    Ordering::AcqRel, Ordering::Acquire)
                    .map(|_| ()).map_err(|_| io::Error::other("material readiness was permanently fenced"))
            })?;
            Ok(())
        })();
        if result.is_err() {
            self.fail_material_startup();
        }
        result
    }

    pub(super) fn require_material_startup_complete(&self) -> io::Result<()> {
        if self.material_startup.as_ref().is_some_and(|startup| startup.state.load(Ordering::Acquire) != StartupState::Confirmed as u8) {
            return Err(io::Error::new(io::ErrorKind::PermissionDenied, "recovered material startup is not confirmed"));
        }
        Ok(())
    }

    pub(super) fn require_startup_read(&self, lane: HostAuthorityLane, bytes: &[u8]) -> io::Result<()> {
        if self.require_material_startup_complete().is_ok() {
            return Ok(());
        }
        let read = match lane {
            HostAuthorityLane::Observation => true,
            HostAuthorityLane::Issuer => false,
            HostAuthorityLane::Checkpoint => serde_json::from_slice::<codex_hepta_memory::CognitiveCheckpointRequest>(bytes)
                .is_ok_and(|request| request.command == codex_hepta_memory::CognitiveCheckpointCommand::ReadHead),
            HostAuthorityLane::DeviceConsumerFrontier | HostAuthorityLane::NotesConsumerFrontier =>
                crate::authority_host_consumer_frontier::is_startup_read(bytes),
        };
        if !read {
            return Err(io::Error::new(io::ErrorKind::PermissionDenied, "only original startup reads are available before recovered owner ready"));
        }
        Ok(())
    }
}
