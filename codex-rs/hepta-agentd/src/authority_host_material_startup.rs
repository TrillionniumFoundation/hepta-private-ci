//! One trusted launch-ready confirmation; no runtime registration protocol.
use super::*;
use std::fs::File;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

pub(super) struct RequiredMaterialStartup {
    root: PathBuf,
    directory: File,
    confirmed: AtomicBool,
}

impl RequiredMaterialStartup {
    fn open(root: &Path) -> io::Result<Self> {
        codex_hepta_contracts::RootAuthorityDirectory::open(root).map_err(io::Error::other)?;
        let directory = std::fs::OpenOptions::new().read(true)
            .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC).open(root)?;
        let state = Self { root: root.to_path_buf(), directory, confirmed: AtomicBool::new(false) };
        state.verify_directory()?;
        Ok(state)
    }

    fn verify_directory(&self) -> io::Result<()> {
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
        let result = (|| {
            startup.verify_directory()?;
            self.register_material_archive_for_root(&startup.root)?;
            startup.verify_directory()?;
            // Original whole Current, proof, actual processes, both frontiers
            // and the final protected clock are checked after blocking I/O.
            // Capture makes no sequence, ticket or permission and retains no
            // second issuer. The existing public bootstrap does not change.
            self.capture_public_bootstrap()?;
            startup.confirmed.store(true, Ordering::Release);
            Ok(())
        })();
        if result.is_err() {
            startup.confirmed.store(false, Ordering::Release);
            if let Some(checkpoint) = &self.checkpoint {
                checkpoint.backend.close();
            }
        }
        result
    }

    pub(super) fn require_material_startup_complete(&self) -> io::Result<()> {
        if self.material_startup.as_ref().is_some_and(|startup| !startup.confirmed.load(Ordering::Acquire)) {
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
