//! Read-only observations after a failed macOS unit-test rename, before cleanup.

use std::io;
use std::io::Write;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::MetadataExt;
use std::path::Path;
use std::path::PathBuf;

use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

const MAX_RECORD_BYTES: usize = 8192;

#[derive(Serialize)]
struct ErrorObservation {
    kind: String,
    raw_os_error: Option<i32>,
}

#[derive(Serialize)]
#[serde(tag = "status", content = "value", rename_all = "snake_case")]
enum MetadataObservation {
    Present {
        file_type: &'static str,
        mode: u32,
        uid: u32,
        gid: u32,
        device: u64,
        inode: u64,
        links: u64,
    },
    Error(ErrorObservation),
}

#[derive(Serialize)]
#[serde(tag = "status", content = "value", rename_all = "snake_case")]
enum CanonicalObservation {
    Resolved {
        path_sha256: String,
        spelling_unchanged: bool,
    },
    Error(ErrorObservation),
}

#[derive(Serialize)]
struct PathObservation {
    role: &'static str,
    path_sha256: String,
    metadata: MetadataObservation,
    canonical: CanonicalObservation,
}

#[derive(Serialize)]
struct RenameObservation {
    schema_version: u32,
    phase: &'static str,
    atomic_snapshot: bool,
    original_error: ErrorObservation,
    lexical_parents_equal: bool,
    staging_parent_matches_canonical_parent: Option<bool>,
    final_parent_matches_canonical_parent: Option<bool>,
    staging: PathObservation,
    final_path: PathObservation,
    parent: Option<PathObservation>,
}

pub(crate) fn observe_failed_rename(staging: &Path, final_path: &Path, error: &io::Error) -> bool {
    // These are sequential observations of the three fixed paths. Do not
    // enumerate directories, read file contents, change permissions, or retry.
    let (staging_observation, canonical_staging) = observe_path("staging", staging);
    let (final_observation, canonical_final) = observe_path("final", final_path);
    let parent = staging.parent().map(|path| observe_path("parent", path));
    let canonical_parent = parent
        .as_ref()
        .and_then(|(_, canonical)| canonical.as_ref().ok());
    let snapshot = RenameObservation {
        schema_version: 1,
        phase: "after_rename_error_before_cleanup",
        atomic_snapshot: false,
        original_error: error_observation(error),
        lexical_parents_equal: staging.parent() == final_path.parent(),
        staging_parent_matches_canonical_parent: canonical_staging
            .as_ref()
            .ok()
            .zip(canonical_parent)
            .map(|(staging, parent)| staging.parent() == Some(parent.as_path())),
        final_parent_matches_canonical_parent: canonical_final
            .as_ref()
            .ok()
            .zip(canonical_parent)
            .map(|(final_path, parent)| final_path.parent() == Some(parent.as_path())),
        staging: staging_observation,
        final_path: final_observation,
        parent: parent.map(|(observation, _)| observation),
    };

    let mut record = b"fleet_release_rename_snapshot ".to_vec();
    match serde_json::to_vec(&snapshot) {
        Ok(bytes) if record.len() + bytes.len() < MAX_RECORD_BYTES => {
            record.extend_from_slice(&bytes);
        }
        Ok(_) => record.extend_from_slice(b"record_exceeds_bound"),
        Err(_) => record.extend_from_slice(b"record_encoding_failed"),
    }
    record.push(b'\n');
    // One bounded best-effort write. A short/failed write does not replace the
    // original rename error, and is not evidence that the observation succeeded.
    match io::stderr().lock().write(&record) {
        Ok(written) => written == record.len(),
        Err(_) => false,
    }
}

fn observe_path(role: &'static str, path: &Path) -> (PathObservation, io::Result<PathBuf>) {
    let metadata = match std::fs::symlink_metadata(path) {
        Ok(metadata) => MetadataObservation::Present {
            file_type: if metadata.file_type().is_symlink() {
                "symlink"
            } else if metadata.is_dir() {
                "directory"
            } else if metadata.is_file() {
                "file"
            } else {
                "other"
            },
            mode: metadata.mode(),
            uid: metadata.uid(),
            gid: metadata.gid(),
            device: metadata.dev(),
            inode: metadata.ino(),
            links: metadata.nlink(),
        },
        Err(error) => MetadataObservation::Error(error_observation(&error)),
    };
    let canonical_path = path.canonicalize();
    let canonical = match &canonical_path {
        Ok(canonical) => CanonicalObservation::Resolved {
            path_sha256: path_sha256(canonical),
            spelling_unchanged: path == canonical.as_path(),
        },
        Err(error) => CanonicalObservation::Error(error_observation(error)),
    };
    (
        PathObservation {
            role,
            path_sha256: path_sha256(path),
            metadata,
            canonical,
        },
        canonical_path,
    )
}

fn error_observation(error: &io::Error) -> ErrorObservation {
    ErrorObservation {
        kind: format!("{:?}", error.kind()),
        raw_os_error: error.raw_os_error(),
    }
}

fn path_sha256(path: &Path) -> String {
    format!("{:x}", Sha256::digest(path.as_os_str().as_bytes()))
}
