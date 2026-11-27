//! Live-only physical image construction for the original Root publisher.
//!
//! This is an integrity operation, never a Current or writer-authority factory.
//! The Root caller retains the real publication barrier and authenticates the
//! expected cut independently. Recovery must verify a previously retained Root
//! image; it must never invoke this live capture on a crash-time suspect store.

use std::fs::File;
use std::fs::OpenOptions;
use std::os::unix::fs::FileExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_paths::HeptaAgentLayout;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use sha2::Digest;
use sha2::Sha256;

use crate::CognitiveRecoveryAnchor;
use crate::CognitiveRecoveryError;
use crate::CognitiveRecoveryRequirement;
use crate::CognitiveStore;
use crate::cognitive_store::capture_recovery_anchor;
use crate::cognitive_store::resolve_active_database_path;

const MAX_IMAGE_BYTES: u64 = 128 * 1024 * 1024;

/// A self-contained image whose actual SQLite content matched an independently
/// supplied original cut. Only this module constructs it. It is not a Current
/// receipt, grant, Root custody proof, recovery permit or mutable store handle.
pub struct CognitiveCheckpointImage {
    path: PathBuf,
    cut: CognitiveRecoveryAnchor,
    sha256: Sha256Digest,
    bytes: u64,
    file: File,
}

impl CognitiveCheckpointImage {
    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn cut(&self) -> &CognitiveRecoveryAnchor {
        &self.cut
    }

    pub fn sha256(&self) -> &Sha256Digest {
        &self.sha256
    }

    pub fn bytes(&self) -> u64 {
        self.bytes
    }
}

impl CognitiveStore {
    /// Verify only an independently retained image and the Root's previously
    /// recorded physical digest/cut. This path never opens the live database,
    /// creates an image, derives a replacement witness or installs a writer.
    pub async fn verify_retained_checkpoint_image(
        path: &Path,
        expected: &CognitiveRecoveryAnchor,
        expected_sha256: &Sha256Digest,
    ) -> Result<CognitiveCheckpointImage, CognitiveRecoveryError> {
        let owner = rustix::process::geteuid().as_raw();
        let _directory = private_directory(
            path.parent()
                .ok_or_else(|| invalid("missing material parent"))?,
            owner,
        )?;
        let identity = private_file(path, owner)?;
        let file = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(path)
            .map_err(unavailable)?;
        let metadata = file.metadata().map_err(unavailable)?;
        if (metadata.dev(), metadata.ino()) != (identity.0, identity.1) {
            return Err(invalid("retained material descriptor identity differs"));
        }
        let (digest, bytes) = digest_image(&file)?;
        if digest != *expected_sha256 {
            return Err(invalid(
                "retained material differs from Root's pre-crash digest",
            ));
        }
        validate_image(path, expected).await?;
        if private_file(path, owner)? != identity || digest_image(&file)?.0 != digest {
            return Err(invalid("retained material changed during verification"));
        }
        Ok(CognitiveCheckpointImage {
            path: path.to_path_buf(),
            cut: expected.clone(),
            sha256: digest,
            bytes,
            file,
        })
    }

    /// Root's live publication path only. Read the active database selected by
    /// the original registered layout with SQLite's READONLY flag; VACUUM INTO
    /// produces a separate consistent physical snapshot. The original owner
    /// must retain its existing BEGIN IMMEDIATE publication barrier throughout.
    ///
    /// `source_uid` comes from Root's actual publisher registration (or Root's
    /// fresh, unreleased original store), never an ordinary request. The target
    /// parent must be private and owned by the actual caller; production Root
    /// additionally proves that it is its registered Root-only material area.
    /// No source file is replaced, checkpointed or opened as a writable owner.
    /// Every logical fact and required schema is recomputed from the IMAGE.
    pub async fn capture_live_checkpoint_image(
        layout: &HeptaAgentLayout,
        source_uid: u32,
        expected: &CognitiveRecoveryAnchor,
        destination: &Path,
    ) -> Result<CognitiveCheckpointImage, CognitiveRecoveryError> {
        super::validate_requirement(
            layout,
            CognitiveRecoveryRequirement::ExactCurrentCut(expected),
        )?;
        let root = layout.cognitive_root();
        if root.canonicalize().map_err(unavailable)? != root
            || destination.starts_with(root)
            || destination.parent().is_none()
        {
            return Err(invalid(
                "registered source and independent destination required",
            ));
        }
        let source = resolve_active_database_path(root).map_err(unavailable)?;
        let original = private_file(&source, source_uid)?;
        let parent = destination
            .parent()
            .ok_or_else(|| invalid("missing image parent"))?;
        let owner = rustix::process::geteuid().as_raw();
        let directory = private_directory(parent, owner)?;
        let image = OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(destination)
            .map_err(unavailable)?;
        let image_identity = image.metadata().map_err(unavailable)?;
        let config = SqliteConfig::from_sqlite_home(
            AbsolutePathBuf::try_from(root.to_path_buf()).map_err(unavailable)?,
        );
        let pool = config
            .open_read_only_pool(&source)
            .await
            .map_err(unavailable)?;
        let copied = sqlx::query("VACUUM INTO ?")
            .bind(
                destination
                    .to_str()
                    .ok_or_else(|| invalid("non-UTF8 image path"))?,
            )
            .execute(&pool)
            .await;
        pool.close().await;
        copied.map_err(unavailable)?;
        if private_file(&source, source_uid)? != original {
            return Err(invalid(
                "live source identity changed during publication copy",
            ));
        }
        let current_image = private_file(destination, owner)?;
        if current_image.0 != image_identity.dev() || current_image.1 != image_identity.ino() {
            return Err(invalid(
                "new image path no longer names its retained descriptor",
            ));
        }
        validate_image(destination, expected).await?;
        let path = destination.to_path_buf();
        let cut = expected.clone();
        tokio::task::spawn_blocking(move || {
            image.sync_all().map_err(unavailable)?;
            directory.sync_all().map_err(unavailable)?;
            let (sha256, bytes) = digest_image(&image)?;
            if private_file(&path, owner)? != current_image {
                return Err(invalid(
                    "image changed after independent semantic verification",
                ));
            }
            Ok(CognitiveCheckpointImage {
                path,
                cut,
                sha256,
                bytes,
                file: image,
            })
        })
        .await
        .map_err(unavailable)?
    }
}

#[path = "cognitive_checkpoint_install.rs"]
mod install;
pub use install::InstalledRootCheckpointImage;

async fn validate_image(
    path: &Path,
    expected: &CognitiveRecoveryAnchor,
) -> Result<(), CognitiveRecoveryError> {
    for suffix in ["-wal", "-shm", "-journal"] {
        match PathBuf::from(format!("{}{suffix}", path.display())).symlink_metadata() {
            Ok(_) => return Err(invalid("physical checkpoint image must be self-contained")),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(unavailable(error)),
        }
    }
    let config = SqliteConfig::from_sqlite_home(
        AbsolutePathBuf::try_from(
            path.parent()
                .ok_or_else(|| invalid("missing image parent"))?
                .to_path_buf(),
        )
        .map_err(unavailable)?,
    );
    let pool = config
        .open_read_only_pool(path)
        .await
        .map_err(unavailable)?;
    let checked = async {
        let mut transaction = pool.begin().await.map_err(unavailable)?;
        let observed = capture_recovery_anchor(&mut transaction, &expected.owner_agent_id)
            .await
            .map_err(unavailable)?;
        if observed != *expected {
            return Err(invalid(
                "independent image differs from the original protected cut",
            ));
        }
        let integrity: Vec<String> = sqlx::query_scalar("PRAGMA integrity_check(1)")
            .fetch_all(&mut *transaction)
            .await
            .map_err(unavailable)?;
        if integrity != ["ok"] {
            return Err(invalid(
                "independent image failed SQLite integrity checking",
            ));
        }
        transaction.rollback().await.map_err(unavailable)
    }
    .await;
    pool.close().await;
    checked
}

fn private_directory(path: &Path, owner: u32) -> Result<File, CognitiveRecoveryError> {
    if path.canonicalize().map_err(unavailable)? != path {
        return Err(invalid("redirected image directory"));
    }
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)
        .map_err(unavailable)?;
    let metadata = file.metadata().map_err(unavailable)?;
    if !metadata.is_dir() || metadata.uid() != owner || metadata.mode() & 0o7777 != 0o700 {
        return Err(invalid("private image directory custody differs"));
    }
    Ok(file)
}

fn private_file(
    path: &Path,
    owner: u32,
) -> Result<(u64, u64, u64, i64, i64), CognitiveRecoveryError> {
    let metadata = path.symlink_metadata().map_err(unavailable)?;
    if !metadata.is_file()
        || metadata.uid() != owner
        || metadata.nlink() != 1
        || metadata.mode() & 0o7777 != 0o600
        || metadata.len() > MAX_IMAGE_BYTES
    {
        return Err(invalid("private SQLite file custody or bound differs"));
    }
    Ok((
        metadata.dev(),
        metadata.ino(),
        metadata.len(),
        metadata.mtime(),
        metadata.mtime_nsec(),
    ))
}

fn digest_image(file: &File) -> Result<(Sha256Digest, u64), CognitiveRecoveryError> {
    let mut digest = Sha256::new();
    let mut buffer = [0_u8; 65536];
    let mut bytes = 0_u64;
    loop {
        let count = file.read_at(&mut buffer, bytes).map_err(unavailable)?;
        if count == 0 {
            break;
        }
        bytes = bytes
            .checked_add(count as u64)
            .filter(|value| *value <= MAX_IMAGE_BYTES)
            .ok_or_else(|| invalid("physical image exceeds its retained bound"))?;
        digest.update(&buffer[..count]);
    }
    if bytes == 0 {
        return Err(invalid("empty physical image"));
    }
    Ok((Sha256Digest::from_sha256_output(digest.finalize()), bytes))
}

fn unavailable(error: impl std::fmt::Display) -> CognitiveRecoveryError {
    CognitiveRecoveryError::Unavailable(error.to_string())
}

fn invalid(message: &str) -> CognitiveRecoveryError {
    CognitiveRecoveryError::Indeterminate(message.to_string())
}

#[cfg(test)]
#[path = "cognitive_checkpoint_image_tests.rs"]
mod tests;
