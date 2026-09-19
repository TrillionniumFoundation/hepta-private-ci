//! Conservative storage hygiene for immutable artifact files.
//!
//! These helpers do not discover authoritative paths or grant repair authority.
//! The host must authenticate the target root and hold its exclusive writer
//! fence before invoking cleanup. Only a regular zero-length file beneath the
//! trusted root can be removed.

use std::fs;
#[cfg(unix)]
use std::fs::File;
use std::io;
use std::path::Path;

use crate::ArtifactStorageError;
use crate::storage::resolve_beneath_trusted_root;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OrphanCleanupDispositionV1 {
    Removed,
    Absent,
    NotZeroLengthRegularFile,
}

/// Remove one proven create-only orphan beneath a trusted root.
///
/// The caller must hold the host writer fence for the target namespace. This
/// function rejects lexical escape and symlink ancestors through the same path
/// resolver used by contained writers. The final component must be a regular
/// zero-length file; symlinks, directories, special files and non-empty files
/// are never removed.
///
/// A concurrent hostile replacement of trusted path components is outside this
/// safe-Rust boundary and must be prevented by the host.
pub fn cleanup_zero_length_orphan_beneath(
    root: impl AsRef<Path>,
    relative: impl AsRef<Path>,
) -> Result<OrphanCleanupDispositionV1, ArtifactStorageError> {
    let path = resolve_beneath_trusted_root(root, relative)?;
    let metadata = match fs::symlink_metadata(&path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            return Ok(OrphanCleanupDispositionV1::Absent);
        }
        Err(error) => return Err(error.into()),
    };

    if metadata.file_type().is_symlink() || !metadata.is_file() || metadata.len() != 0 {
        return Ok(OrphanCleanupDispositionV1::NotZeroLengthRegularFile);
    }

    fs::remove_file(&path)?;

    // On Unix, make the directory-entry deletion durable before reporting a
    // successful cleanup. Other targets require target-host qualification for
    // their directory durability primitive.
    #[cfg(unix)]
    {
        let parent = path.parent().ok_or(ArtifactStorageError::InvalidPath)?;
        File::open(parent)
            .and_then(|directory| directory.sync_all())
            .map_err(|_| ArtifactStorageError::Indeterminate)?;
    }

    Ok(OrphanCleanupDispositionV1::Removed)
}

#[cfg(test)]
mod tests {
    use super::*;

    use std::io::Write;
    use std::path::PathBuf;
    use std::sync::atomic::AtomicU64;
    use std::sync::atomic::Ordering;

    use crate::CreateOnlyArtifactFile;

    static NEXT_ROOT: AtomicU64 = AtomicU64::new(1);

    fn root(label: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "hepta-learning-artifact-hygiene-{label}-{}-{}",
            std::process::id(),
            NEXT_ROOT.fetch_add(1, Ordering::Relaxed)
        ))
    }

    #[test]
    fn orphan_cleanup_removes_only_zero_length_regular_file() {
        let root = root("cleanup");
        fs::create_dir_all(root.join("generation")).expect("create fixture root");

        let orphan = root.join("generation/orphan.bin");
        drop(CreateOnlyArtifactFile::create(&orphan).expect("reserve orphan"));
        assert_eq!(
            cleanup_zero_length_orphan_beneath(&root, "generation/orphan.bin"),
            Ok(OrphanCleanupDispositionV1::Removed)
        );
        assert_eq!(
            cleanup_zero_length_orphan_beneath(&root, "generation/orphan.bin"),
            Ok(OrphanCleanupDispositionV1::Absent)
        );

        let nonempty = root.join("generation/nonempty.bin");
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&nonempty)
            .expect("create nonempty fixture");
        file.write_all(b"durable").expect("write fixture");
        file.sync_all().expect("sync fixture");
        drop(file);
        assert_eq!(
            cleanup_zero_length_orphan_beneath(&root, "generation/nonempty.bin"),
            Ok(OrphanCleanupDispositionV1::NotZeroLengthRegularFile)
        );
        assert!(nonempty.exists());

        fs::remove_dir_all(root).expect("cleanup fixture root");
    }

    #[test]
    fn orphan_cleanup_rejects_path_escape() {
        let root = root("escape");
        fs::create_dir_all(&root).expect("create fixture root");
        assert_eq!(
            cleanup_zero_length_orphan_beneath(&root, "../escape"),
            Err(ArtifactStorageError::InvalidPath)
        );
        fs::remove_dir_all(root).expect("cleanup fixture root");
    }

    #[cfg(unix)]
    #[test]
    fn orphan_cleanup_never_follows_final_symlink() {
        use std::os::unix::fs::symlink;

        let root = root("symlink");
        fs::create_dir_all(root.join("generation")).expect("create fixture root");
        let outside = root.with_extension("outside");
        fs::write(&outside, b"outside").expect("write outside fixture");
        symlink(&outside, root.join("generation/link")).expect("create symlink");

        assert_eq!(
            cleanup_zero_length_orphan_beneath(&root, "generation/link"),
            Ok(OrphanCleanupDispositionV1::NotZeroLengthRegularFile)
        );
        assert_eq!(fs::read(&outside).expect("read outside fixture"), b"outside");

        fs::remove_dir_all(root).expect("cleanup fixture root");
        fs::remove_file(outside).expect("cleanup outside fixture");
    }
}
