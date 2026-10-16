//! A non-authorizing, research-only command-line acceptance test for one
//! independently reviewed frozen Granite97 export and bounded Cell Head set.
//!
//! This binary NEVER fetches/loads model weights, authenticates physical work,
//! grants model use or invokes tool/runtime effects. The four immutable local
//! inputs must come from an independent admission owner; data consistency
//! checks alone are not proof of reviewer identity.

use std::error::Error as StdError;
#[cfg(unix)]
use std::fs::OpenOptions;
#[cfg(unix)]
use std::io::Read;
#[cfg(unix)]
use std::os::unix::fs::MetadataExt;
#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;
#[cfg(unix)]
use std::path::Component;
#[cfg(unix)]
use std::path::Path;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_infer_worker_host::model_worker::read_shadow_granite_v3_v7;

const MAX_ADMISSION_BYTES: u64 = 1_000_000;
const MAX_SOURCE_BYTES: u64 = 65_536;
const MAX_EXPORT_BYTES: u64 = 2_500_000;
const MAX_REVIEW_BYTES: u64 = 65_536;

/// Read a single source-owned, create-only input through a stable open file
/// descriptor. Pre/post fstat and no-follow are additional local protections,
/// not a proof of an independent producer signature or an immutable filesystem.
#[cfg(unix)]
fn read_one(path: &str, maximum: u64) -> Result<Vec<u8>, Box<dyn StdError>> {
    let file_path = Path::new(path);
    if !file_path.is_absolute()
        || file_path
            .components()
            .any(|component| matches!(component, Component::ParentDir | Component::CurDir))
    {
        return Err("absolute, normalized, independently admitted path required".into());
    }

    // A direct symlink is refused by O_NOFOLLOW *at open*. Prechecking
    // ancestors rejects simple directory links; it does not pin mutable
    // ancestors against concurrent renames, so external owners still must
    // isolate/stage their source tree and attest source content.
    for parent in file_path.ancestors().skip(1) {
        let metadata = std::fs::symlink_metadata(parent)?;
        if metadata.file_type().is_symlink() || !metadata.is_dir() {
            return Err("symlinked/non-directory ancestor is not admitted".into());
        }
    }
    let pathname = std::fs::symlink_metadata(file_path)?;
    if pathname.file_type().is_symlink()
        || !pathname.is_file()
        || pathname.len() == 0
        || pathname.len() > maximum
        || pathname.nlink() != 1
    {
        return Err("input is not a single-link bounded regular file".into());
    }

    let mut file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC)
        .open(file_path)?;
    let opened = file.metadata()?;
    if !opened.is_file()
        || opened.nlink() != 1
        || opened.len() != pathname.len()
        || opened.dev() != pathname.dev()
        || opened.ino() != pathname.ino()
        || opened.mtime() != pathname.mtime()
        || opened.mtime_nsec() != pathname.mtime_nsec()
    {
        return Err("input identity changed between path check and open".into());
    }

    let mut data = Vec::new();
    {
        let mut limited = (&mut file).take(maximum + 1);
        limited.read_to_end(&mut data)?;
    }
    let after = file.metadata()?;
    if data.is_empty()
        || data.len() as u64 != opened.len()
        || data.len() as u64 > maximum
        || !after.is_file()
        || after.nlink() != 1
        || opened.dev() != after.dev()
        || opened.ino() != after.ino()
        || opened.len() != after.len()
        || opened.mtime() != after.mtime()
        || opened.mtime_nsec() != after.mtime_nsec()
    {
        return Err("input bytes or descriptor snapshot changed during read".into());
    }
    Ok(data)
}

// No weaker path-reading fallback is permitted on unsupported platforms.
#[cfg(not(unix))]
fn read_one(_path: &str, _maximum: u64) -> Result<Vec<u8>, Box<dyn StdError>> {
    Err("research CLI's descriptor-fenced local admission requires Unix".into())
}

fn main() -> Result<(), Box<dyn StdError>> {
    let mut admission = None;
    let mut source = None;
    let mut export = None;
    let mut review = None;
    let mut args = std::env::args().skip(1);
    while let Some(flag) = args.next() {
        if flag == "--help" {
            println!(
                "hepta-granite-v3-shadow --admission ABS_OWNER_JSON \
                 --original-source ABS_SOURCE_FILE --export ABS_EXPORT_JSON \
                 --review ABS_INDEPENDENT_REVIEW_JSON\n\
                 Research-only immutable data/CPU Reader validation. \
                 No model weights, unsigned grants, GPU or external effects."
            );
            return Ok(());
        }
        let value = args.next().ok_or("missing path for research input")?;
        match flag.as_str() {
            "--admission" if admission.is_none() => admission = Some(value),
            "--original-source" if source.is_none() => source = Some(value),
            "--export" if export.is_none() => export = Some(value),
            "--review" if review.is_none() => review = Some(value),
            _ => return Err(format!("duplicate or unexpected CLI flag: {flag}").into()),
        }
    }
    let admission_bytes = read_one(
        &admission.ok_or("--admission is required")?,
        MAX_ADMISSION_BYTES,
    )?;
    let original_bytes = read_one(
        &source.ok_or("--original-source is required")?,
        MAX_SOURCE_BYTES,
    )?;
    let export_bytes = read_one(&export.ok_or("--export is required")?, MAX_EXPORT_BYTES)?;
    let review_bytes = read_one(&review.ok_or("--review is required")?, MAX_REVIEW_BYTES)?;

    let now_ms = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    let report = read_shadow_granite_v3_v7(
        &admission_bytes,
        &original_bytes,
        &export_bytes,
        &review_bytes,
        now_ms,
    )?;
    if report.authority != "DENY_ALL" || report.production_authorized || report.model_selected {
        return Err("research data path unexpectedly requested a production grant".into());
    }
    println!("{}", serde_json::to_string(&report)?);
    Ok(())
}

#[cfg(all(test, unix))]
mod fd_intake_tests {
    use super::read_one;
    use std::fs;
    use std::os::unix::fs::symlink;
    use tempfile::tempdir;

    #[test]
    fn regular_exact_bytes_and_bounds() {
        let dir = tempdir().expect("temporary directory");
        let path = dir.path().join("owner.json");
        fs::write(&path, b"{\"a\":1}").expect("write bounded file");
        assert_eq!(
            read_one(path.to_str().expect("path"), 8).expect("safe descriptor intake"),
            b"{\"a\":1}".to_vec()
        );
        assert!(read_one(path.to_str().expect("path"), 6).is_err());
        fs::write(&path, b"").expect("empty test file");
        assert!(read_one(path.to_str().expect("path"), 8).is_err());
        assert!(read_one("relative.json", 8).is_err());
    }

    #[test]
    fn refuse_final_symlink_parent_symlink_and_hardlink() {
        let dir = tempdir().expect("temporary directory");
        let original_dir = dir.path().join("owner");
        fs::create_dir(&original_dir).expect("create owner directory");
        let original = original_dir.join("source.json");
        fs::write(&original, b"{}").expect("write");
        let linked_path = dir.path().join("source-link.json");
        symlink(&original, &linked_path).expect("symlink");
        assert!(read_one(linked_path.to_str().expect("path"), 3).is_err());
        let linked_dir = dir.path().join("owner-link");
        symlink(&original_dir, &linked_dir).expect("parent link");
        assert!(read_one(linked_dir.join("source.json").to_str().expect("path"), 3).is_err());
        let hardlink_path = dir.path().join("hardlink.json");
        fs::hard_link(&original, &hardlink_path).expect("hardlink");
        assert!(read_one(hardlink_path.to_str().expect("path"), 3).is_err());
        assert!(read_one(original.to_str().expect("path"), 3).is_err());
    }

    #[test]
    fn refuse_parent_components_even_when_canonical_target_exists() {
        let dir = tempdir().expect("temporary directory");
        fs::write(dir.path().join("input.json"), b"{}").expect("write");
        let noncanonical = dir.path().join("subdir").join("..").join("input.json");
        assert!(read_one(noncanonical.to_str().expect("path"), 3).is_err());
    }
}
