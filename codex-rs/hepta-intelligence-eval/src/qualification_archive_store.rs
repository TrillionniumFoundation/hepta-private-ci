//! Create-only bounded archive storage on an owner-protected local filesystem.
//! Files are private on Unix. Encrypted storage and authenticated namespace
//! provisioning remain selected-host obligations, not properties of a digest.
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::codec::MAX_BYTES;
use crate::ProductEvaluationError;
use crate::ProductEvidenceSinkErrorV1;

static NEXT_TEMP: AtomicU64 = AtomicU64::new(0);

fn path_for(root: &Path, attempt: &StableId) -> PathBuf {
    let key = Digest32::of_parts(&[
        b"hepta.learning-eval.qualification-archive-key.v2",
        attempt.as_str().as_bytes(),
    ]);
    root.join(format!("{key}.qartifact2"))
}

fn check_root(root: &Path) -> Result<(), ProductEvaluationError> {
    if !fs::symlink_metadata(root)
        .map_err(read_error)?
        .file_type()
        .is_dir()
    {
        return Err(ProductEvaluationError::Binding(
            "qualification archive directory",
        ));
    }
    Ok(())
}

fn read_path(path: &Path) -> Result<Option<Vec<u8>>, ProductEvaluationError> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_file() => {}
        Ok(_) => {
            return Err(ProductEvaluationError::Integrity(
                "qualification archive file type",
            ));
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(read_error(error)),
    }
    let file = File::open(path).map_err(read_error)?;
    let metadata = file.metadata().map_err(read_error)?;
    if !metadata.file_type().is_file() || metadata.len() > MAX_BYTES as u64 {
        return Err(ProductEvaluationError::Integrity(
            "qualification archive size",
        ));
    }
    let mut bytes = Vec::new();
    file.take(MAX_BYTES as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(read_error)?;
    if bytes.is_empty() || bytes.len() > MAX_BYTES {
        return Err(ProductEvaluationError::Integrity(
            "qualification archive bounds",
        ));
    }
    Ok(Some(bytes))
}

pub(super) fn load(root: &Path, attempt: &StableId) -> Result<Vec<u8>, ProductEvaluationError> {
    // Recovery is a read: absence never creates a new root or rewrites an object.
    check_root(root)?;
    read_path(&path_for(root, attempt))?.ok_or(ProductEvaluationError::Binding(
        "qualification archive missing",
    ))
}

pub(super) fn persist(
    root: &Path,
    attempt: &StableId,
    bytes: &[u8],
) -> Result<(), ProductEvaluationError> {
    if bytes.is_empty() || bytes.len() > MAX_BYTES {
        return Err(ProductEvaluationError::Integrity(
            "qualification archive bounds",
        ));
    }
    match fs::create_dir(root) {
        Ok(()) => {
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                fs::set_permissions(root, fs::Permissions::from_mode(0o700))
                    .map_err(write_error)?;
            }
            // The parent is provisioned by the owner. Do not silently create
            // an unqualified chain of ancestor directories.
            let parent = root
                .parent()
                .filter(|path| !path.as_os_str().is_empty())
                .unwrap_or(Path::new("."));
            File::open(parent)
                .and_then(|file| file.sync_all())
                .map_err(write_error)?;
        }
        Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {}
        Err(error) => return Err(write_error(error)),
    }
    check_root(root)?;
    let final_path = path_for(root, attempt);
    if let Some(existing) = read_path(&final_path)? {
        if existing != bytes {
            return Err(ProductEvaluationError::Binding(
                "qualification archive conflict",
            ));
        }
        return sync_object(root, &final_path);
    }
    let ordinal = NEXT_TEMP.fetch_add(1, Ordering::Relaxed);
    let temporary = root.join(format!(".archive-{}-{ordinal}.tmp", std::process::id()));
    let result = (|| {
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut file = options.open(&temporary).map_err(write_error)?;
        file.write_all(bytes)
            .and_then(|()| file.sync_all())
            .map_err(write_error)?;
        match fs::hard_link(&temporary, &final_path) {
            Ok(()) => {}
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
                if read_path(&final_path)?.as_deref() != Some(bytes) {
                    return Err(ProductEvaluationError::Binding(
                        "qualification archive conflict",
                    ));
                }
            }
            Err(error) => return Err(write_error(error)),
        }
        // Also required on an idempotent/racing acknowledgement. A readable
        // directory entry alone is not proof it survived the earlier fsync.
        sync_object(root, &final_path)
    })();
    let _ = fs::remove_file(temporary);
    result
}

fn sync_object(root: &Path, path: &Path) -> Result<(), ProductEvaluationError> {
    File::open(path)
        .and_then(|file| file.sync_all())
        .map_err(write_error)?;
    File::open(root)
        .and_then(|file| file.sync_all())
        .map_err(write_error)
}

fn read_error(_error: io::Error) -> ProductEvaluationError {
    ProductEvaluationError::Sink(ProductEvidenceSinkErrorV1::Unavailable)
}

fn write_error(_error: io::Error) -> ProductEvaluationError {
    ProductEvaluationError::Sink(ProductEvidenceSinkErrorV1::Indeterminate)
}
