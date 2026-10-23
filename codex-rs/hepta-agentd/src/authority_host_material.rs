//! Physical images for the original checkpoint; this archive never publishes Current.

use std::fs::File;
use std::io;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Mutex;

use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CognitiveRecoveryAnchor;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::RootCognitiveMaterialRegistration;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;

/// Fixed trusted-launch source and protected archive. The runtime peer cannot
/// choose paths, generations or owners. Retained images contain no new ledger.
pub(super) struct RegisteredMaterialArchive {
    source: RootCognitiveMaterialRegistration,
    layout: HeptaAgentLayout,
    root: PathBuf,
    directory: File,
    runtime: Mutex<tokio::runtime::Runtime>,
}

/// A checked durable image bound to one exact original request. Only the Root
/// archive constructs this value, before entering the registry dispatch fence.
pub(super) struct PreparedCheckpointMaterial {
    request_sha256: Sha256Digest,
    material: codex_hepta_memory::VerifiedCognitiveMaterial,
}

impl RegisteredMaterialArchive {
    pub(super) fn register(
        layout: &HeptaAgentLayout,
        uid: u32,
        root: &Path,
    ) -> io::Result<Self> {
        RootAuthorityDirectory::open(root).map_err(io::Error::other)?;
        let directory = std::fs::OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(root)?;
        let source = RootCognitiveMaterialRegistration::bind_registered_layout(layout, uid)
            .map_err(io::Error::other)?;
        // This synchronous Root service owns its executor. Calling from an
        // entered executor is an assembly error, never a nested-runtime panic.
        if tokio::runtime::Handle::try_current().is_ok() {
            return Err(io::Error::other("Root material registration requires its service thread"));
        }
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()?;
        Ok(Self {
            source,
            layout: layout.clone(),
            root: root.to_path_buf(),
            directory,
            runtime: Mutex::new(runtime),
        })
    }

    fn verify_root(&self) -> io::Result<()> {
        RootAuthorityDirectory::open(&self.root).map_err(io::Error::other)?;
        let actual = std::fs::symlink_metadata(&self.root)?;
        let retained = self.directory.metadata()?;
        if (actual.dev(), actual.ino()) != (retained.dev(), retained.ino()) {
            return Err(io::Error::other("registered material archive changed"));
        }
        Ok(())
    }

    fn destination(&self, cut: &CognitiveRecoveryAnchor) -> io::Result<HeptaAgentLayout> {
        self.verify_root()?;
        if cut.owner_agent_id != *self.layout.agent_id() {
            return Err(io::Error::other("material owner mismatch"));
        }
        let digest = Sha256Digest::for_bytes(&serde_json::to_vec(cut)?);
        Ok(HeptaFleetRoot::parse(self.root.join(digest.as_str()))
            .map_err(io::Error::other)?
            .layout()
            .agent(self.layout.agent_id()))
    }

    /// Prepare may copy a new exact cut. It never overwrites existing files,
    /// publishes a checkpoint or holds the original registry writer fence.
    pub(super) fn prepare(
        &self,
        request: &[u8],
        cut: &CognitiveRecoveryAnchor,
    ) -> io::Result<PreparedCheckpointMaterial> {
        if tokio::runtime::Handle::try_current().is_ok() {
            return Err(io::Error::other("material capture requires its Root service thread"));
        }
        let runtime = self.runtime.try_lock().map_err(|_| io::Error::other("material archive busy or fenced"))?;
        let destination = self.destination(cut)?;
        self.source.verify_registered().map_err(io::Error::other)?;
        let image = match std::fs::symlink_metadata(destination.cognitive_root()) {
            Ok(_) => runtime.block_on(CognitiveStore::verify_retained_root_material(&destination, cut)),
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                self.create_destination(destination.cognitive_root())?;
                self.source
                    .materialize_private_candidate(&destination)
                    .map_err(io::Error::other)?;
                runtime.block_on(CognitiveStore::verify_root_material_candidate(&destination, cut))
            }
            Err(error) => return Err(error),
        }.map_err(io::Error::other)?;
        self.retain_verified(request, image)
    }

    fn create_destination(&self, destination: &Path) -> io::Result<()> {
        self.verify_root()?;
        let mut parent = self.directory.try_clone()?;
        let mut path = self.root.clone();
        for component in destination.strip_prefix(&self.root).map_err(io::Error::other)?.components() {
            let std::path::Component::Normal(name) = component else {
                return Err(io::Error::other("invalid private material layout"));
            };
            path.push(name);
            match std::fs::DirBuilder::new().mode(0o700).create(&path) {
                Ok(()) => {}
                Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {}
                Err(error) => return Err(error),
            }
            RootAuthorityDirectory::open(&path).map_err(io::Error::other)?;
            let next = std::fs::OpenOptions::new().read(true)
                .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC).open(&path)?;
            next.sync_all()?;
            parent.sync_all()?;
            parent = next;
        }
        self.verify_root()
    }

    /// Commit/recovery only revalidate already retained material. Loss or a
    /// partial image cannot be repaired by copying the current live database.
    pub(super) fn retained(
        &self,
        request: &[u8],
        cut: &CognitiveRecoveryAnchor,
    ) -> io::Result<PreparedCheckpointMaterial> {
        let runtime = self.runtime.try_lock().map_err(|_| io::Error::other("material archive busy or fenced"))?;
        let destination = self.destination(cut)?;
        if tokio::runtime::Handle::try_current().is_ok() {
            return Err(io::Error::other("material capture requires its Root service thread"));
        }
        let image = runtime.block_on(CognitiveStore::verify_retained_root_material(&destination, cut))
            .map_err(io::Error::other)?;
        self.retain_verified(request, image)
    }

    fn retain_verified(
        &self,
        request: &[u8],
        image: codex_hepta_memory::VerifiedCognitiveMaterial,
    ) -> io::Result<PreparedCheckpointMaterial> {
        self.verify_root()?;
        // A previous uncertain attempt may have created an ancestor before
        // losing its acknowledgement. Sync each existing protected directory;
        // never recreate missing retained material or rely on a digest alone.
        let parent = image.path().parent().ok_or_else(|| io::Error::other("material parent missing"))?;
        let mut path = self.root.clone();
        self.directory.sync_all()?;
        for component in parent.strip_prefix(&self.root).map_err(io::Error::other)?.components() {
            let std::path::Component::Normal(name) = component else {
                return Err(io::Error::other("invalid retained material layout"));
            };
            path.push(name);
            RootAuthorityDirectory::open(&path).map_err(io::Error::other)?;
            std::fs::OpenOptions::new().read(true)
                .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC).open(&path)?.sync_all()?;
        }
        let prepared = PreparedCheckpointMaterial {
            request_sha256: Sha256Digest::for_bytes(request),
            material: image,
        };
        prepared.validate(request, prepared.material.anchor())?;
        Ok(prepared)
    }
}

impl PreparedCheckpointMaterial {
    /// Full schema/cut/integrity checks and fsync already completed outside
    /// the original fence. Recheck the held private inode immediately before
    /// CAS; no large copy, full hash or SQLite work occurs under that fence.
    pub(super) fn validate(&self, request: &[u8], cut: &CognitiveRecoveryAnchor) -> io::Result<()> {
        if self.request_sha256 != Sha256Digest::for_bytes(request) || self.material.anchor() != cut {
            return Err(io::Error::other("material is bound to another request or cut"));
        }
        self.material.verify_unchanged().map_err(io::Error::other)
    }
}
