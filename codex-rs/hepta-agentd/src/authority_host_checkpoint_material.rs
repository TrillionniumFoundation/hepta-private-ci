//! Root-owned immutable physical material for the original checkpoint owner.
//!
//! Records describe a candidate produced by the ORIGINAL Root transition. They
//! confer no Current status: admission additionally requires the actual protected
//! head to equal that complete candidate. Image and record are durable BEFORE
//! the original Current CAS, so a crash never requires hashing the live DB.

use super::*;
use codex_hepta_memory::CognitiveCheckpointReceipt;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_paths::HeptaAgentLayout;
use serde::Deserialize;
use serde::Serialize;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::PathBuf;
use std::time::Duration;

#[path = "authority_host_checkpoint_material_worker.rs"]
mod worker;

/// Root-only constructor input, never a peer-deserializable deployment profile.
#[derive(Clone)]
pub(crate) struct RootMaterialProfile {
    pub(crate) layout: HeptaAgentLayout,
    pub(crate) root: PathBuf,
    pub(crate) deadline: Duration,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct MaterialRecord {
    schema_version: u32,
    candidate: CognitiveCheckpointReceipt,
    registered_cognitive_root: PathBuf,
    image_sha256: Sha256Digest,
    image_bytes: u64,
}

struct MaterialArea {
    path: PathBuf,
    directory: File,
    _custody: Arc<RootAuthorityDirectory>,
    layout: HeptaAgentLayout,
}

impl MaterialArea {
    fn open(profile: &RootMaterialProfile) -> Result<Self, AuthorityTrustError> {
        let custody = RootAuthorityDirectory::open(&profile.root)?;
        if profile.root.starts_with(profile.layout.cognitive_root()) {
            return Err(AuthorityTrustError::Invalid);
        }
        let directory = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(&profile.root)
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        Ok(Self {
            path: profile.root.clone(),
            directory,
            _custody: custody,
            layout: profile.layout.clone(),
        })
    }

    fn validate_candidate(
        &self,
        candidate: &CognitiveCheckpointReceipt,
    ) -> Result<(), AuthorityTrustError> {
        if candidate.head.phase != CognitiveCheckpointPhase::Current
            || candidate.head.proposal.is_some()
            || candidate.head.owner_agent_id != *self.layout.agent_id()
            || candidate.token != token_for(&candidate.head)?
        {
            return Err(AuthorityTrustError::Invalid);
        }
        Ok(())
    }

    fn record_path(&self, candidate: &CognitiveCheckpointReceipt) -> PathBuf {
        self.path.join(format!(
            "current-{}.json",
            candidate.token.head_sha256.as_str()
        ))
    }

    fn image_path(&self, digest: &Sha256Digest) -> PathBuf {
        self.path.join(format!("image-{}.sqlite3", digest.as_str()))
    }

    async fn prepare(
        &self,
        candidate: &CognitiveCheckpointReceipt,
        source_uid: u32,
    ) -> Result<MaterialRecord, AuthorityTrustError> {
        self.check_custody()?;
        self.validate_candidate(candidate)?;
        match std::fs::symlink_metadata(self.record_path(candidate)) {
            Ok(_) => return self.verify(candidate).await,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(_) => return Err(AuthorityTrustError::Unavailable),
        }
        // The first native profile is finite. Exhaustion refuses publication;
        // it never deletes an older independent image to make the request fit.
        self.ensure_capacity(/*additional*/ 2)?;
        let temporary = self.path.join(format!(
            "capture-{}.sqlite3",
            candidate.token.head_sha256.as_str()
        ));
        let image = CognitiveStore::capture_live_checkpoint_image(
            &self.layout,
            source_uid,
            &candidate.head.last_current,
            &temporary,
        )
        .await
        .map_err(|_| AuthorityTrustError::Unavailable)?;
        let retained = self.image_path(image.sha256());
        match std::fs::hard_link(&temporary, &retained) {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                CognitiveStore::verify_retained_checkpoint_image(
                    &retained,
                    image.cut(),
                    image.sha256(),
                )
                .await
                .map_err(|_| AuthorityTrustError::Unavailable)?;
            }
            Err(_) => return Err(AuthorityTrustError::Unavailable),
        }
        std::fs::remove_file(&temporary).map_err(|_| AuthorityTrustError::Unavailable)?;
        self.directory
            .sync_all()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        let record = MaterialRecord {
            schema_version: 1,
            candidate: candidate.clone(),
            registered_cognitive_root: self.layout.cognitive_root().to_path_buf(),
            image_sha256: image.sha256().clone(),
            image_bytes: image.bytes(),
        };
        self.retain_record(&record)?;
        self.verify(candidate).await
    }

    fn ensure_capacity(&self, additional: usize) -> Result<(), AuthorityTrustError> {
        let count = std::fs::read_dir(&self.path)
            .map_err(|_| AuthorityTrustError::Unavailable)?
            .take(129)
            .try_fold(0_usize, |count, entry| {
                entry
                    .map(|_| count + 1)
                    .map_err(|_| AuthorityTrustError::Unavailable)
            })?;
        if count
            .checked_add(additional)
            .is_none_or(|count| count > 128)
        {
            return Err(AuthorityTrustError::Unavailable);
        }
        Ok(())
    }

    fn retain_record(&self, record: &MaterialRecord) -> Result<(), AuthorityTrustError> {
        self.ensure_capacity(/*additional*/ 1)?;
        let bytes = serde_json::to_vec(&record).map_err(|_| AuthorityTrustError::Unavailable)?;
        if bytes.len() > 32_768 {
            return Err(AuthorityTrustError::Invalid);
        }
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(self.record_path(&record.candidate))
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        file.write_all(&bytes)
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        file.sync_all()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        self.directory
            .sync_all()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        Ok(())
    }

    async fn rebind(
        &self,
        previous: &CognitiveCheckpointReceipt,
        candidate: &CognitiveCheckpointReceipt,
    ) -> Result<MaterialRecord, AuthorityTrustError> {
        self.validate_candidate(candidate)?;
        let mut retained = self.verify(previous).await?;
        if candidate.head.last_current != previous.head.last_current {
            return Err(AuthorityTrustError::Invalid);
        }
        match std::fs::symlink_metadata(self.record_path(candidate)) {
            Ok(_) => {
                let existing = self.verify(candidate).await?;
                if existing.image_sha256 != retained.image_sha256
                    || existing.image_bytes != retained.image_bytes
                {
                    return Err(AuthorityTrustError::Invalid);
                }
                return Ok(existing);
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(_) => return Err(AuthorityTrustError::Unavailable),
        }
        retained.candidate = candidate.clone();
        self.retain_record(&retained)?;
        self.verify(candidate).await
    }

    async fn install(
        &self,
        candidate: &CognitiveCheckpointReceipt,
    ) -> Result<codex_hepta_memory::InstalledRootCheckpointImage, AuthorityTrustError> {
        let retained = self.verify(candidate).await?;
        let image = CognitiveStore::verify_retained_checkpoint_image(
            &self.image_path(&retained.image_sha256),
            &candidate.head.last_current,
            &retained.image_sha256,
        )
        .await
        .map_err(|_| AuthorityTrustError::Unavailable)?;
        CognitiveStore::install_root_checkpoint_image(&self.layout, image)
            .await
            .map_err(|_| AuthorityTrustError::Unavailable)
    }

    async fn reopen_installation(
        &self,
        candidate: &CognitiveCheckpointReceipt,
    ) -> Result<codex_hepta_memory::InstalledRootCheckpointImage, AuthorityTrustError> {
        let retained = self.verify(candidate).await?;
        let image = CognitiveStore::verify_retained_checkpoint_image(
            &self.image_path(&retained.image_sha256),
            &candidate.head.last_current,
            &retained.image_sha256,
        )
        .await
        .map_err(|_| AuthorityTrustError::Unavailable)?;
        CognitiveStore::reopen_root_checkpoint_installation(
            &self.layout,
            image,
            candidate.head.peer_lifetime.uid,
        )
        .await
        .map_err(|_| AuthorityTrustError::Unavailable)
    }

    async fn verify(
        &self,
        candidate: &CognitiveCheckpointReceipt,
    ) -> Result<MaterialRecord, AuthorityTrustError> {
        self.check_custody()?;
        self.validate_candidate(candidate)?;
        let path = self.record_path(candidate);
        let file = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(&path)
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        let metadata = file
            .metadata()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        if !metadata.is_file()
            || metadata.uid() != 0
            || metadata.nlink() != 1
            || metadata.mode() & 0o7777 != 0o600
            || metadata.len() > 32_768
        {
            return Err(AuthorityTrustError::Invalid);
        }
        let mut bytes = Vec::new();
        file.take(32_769)
            .read_to_end(&mut bytes)
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        if bytes.len() > 32_768 {
            return Err(AuthorityTrustError::Invalid);
        }
        let record: MaterialRecord =
            serde_json::from_slice(&bytes).map_err(|_| AuthorityTrustError::Invalid)?;
        if record.schema_version != 1
            || record.candidate != *candidate
            || record.registered_cognitive_root != self.layout.cognitive_root()
        {
            return Err(AuthorityTrustError::Invalid);
        }
        let checked = CognitiveStore::verify_retained_checkpoint_image(
            &self.image_path(&record.image_sha256),
            &candidate.head.last_current,
            &record.image_sha256,
        )
        .await
        .map_err(|_| AuthorityTrustError::Unavailable)?;
        if checked.bytes() != record.image_bytes {
            return Err(AuthorityTrustError::Invalid);
        }
        self.check_custody()?;
        Ok(record)
    }

    fn check_custody(&self) -> Result<(), AuthorityTrustError> {
        let path = self
            .path
            .symlink_metadata()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        let held = self
            .directory
            .metadata()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        if !path.is_dir()
            || path.uid() != 0
            || path.mode() & 0o7777 != 0o700
            || (path.dev(), path.ino()) != (held.dev(), held.ino())
        {
            return Err(AuthorityTrustError::Invalid);
        }
        Ok(())
    }
}

pub(super) use worker::RootCheckpointMaterial;
pub(super) use worker::SourceCustody;
