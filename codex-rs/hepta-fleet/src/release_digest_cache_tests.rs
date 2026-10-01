//! Native file-descriptor/inode checks. Root cases must be run explicitly;
//! ordinary temporary paths cannot qualify root-custody cache hits.

use std::io::Seek;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;

use pretty_assertions::assert_eq;

use super::*;

const MANIFEST: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

fn readonly_program(
    directory: &Path,
    name: &str,
    bytes: &[u8],
) -> Result<PathBuf, Box<dyn std::error::Error>> {
    let path = directory.join(name);
    std::fs::write(&path, bytes)?;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o555))?;
    Ok(path)
}

fn observe_reads(
    cache: &ReleaseDigestCache,
    path: &Path,
    manifest: &ManifestRead,
) -> Result<(String, u64), Box<dyn std::error::Error>> {
    let mut opened = File::open(path)?;
    // dup shares this actual kernel file offset. A cache hit must not consume
    // even one program byte; a miss must read the complete opened file.
    let digest = cache.opened_sha256(path, manifest, opened.try_clone()?)?;
    Ok((digest, opened.stream_position()?))
}

fn read_manifest(
    cache: &ReleaseDigestCache,
    directory: &Path,
    name: &str,
    bytes: &[u8],
) -> Result<ManifestRead, Box<dyn std::error::Error>> {
    let path = readonly_program(directory, name, bytes)?;
    Ok(cache.manifest(&path, /*maximum*/ 32 * 1024)?)
}

#[test]
fn ordinary_paths_always_read_program_bytes_without_root_cache_authority()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    let bytes = vec![b'o'; 70_001];
    let path = readonly_program(temp.path(), "program", &bytes)?;
    let cache = ReleaseDigestCache::default();
    let manifest = read_manifest(&cache, temp.path(), "manifest", MANIFEST.as_bytes())?;
    let expected = format!("{:x}", Sha256::digest(&bytes));
    for _ in 0..3 {
        assert_eq!(
            observe_reads(&cache, &path, &manifest)?,
            (expected.clone(), bytes.len() as u64)
        );
    }
    assert!(
        cache
            .entries
            .lock()
            .map_err(|_| "cache poisoned")?
            .is_empty()
    );
    Ok(())
}

fn root_fixture() -> Result<tempfile::TempDir, Box<dyn std::error::Error>> {
    let directory = tempfile::Builder::new()
        .prefix("hepta-release-digest-")
        .tempdir_in("/var/lib")?;
    assert_eq!(std::fs::metadata(directory.path())?.uid(), 0);
    Ok(directory)
}

#[test]
#[ignore = "requires root and protected native filesystem"]
fn root_custody_hit_keeps_opened_offset_while_manifest_change_reads_again()
-> Result<(), Box<dyn std::error::Error>> {
    let directory = root_fixture()?;
    let bytes = vec![b'r'; 70_001];
    let path = readonly_program(directory.path(), "program", &bytes)?;
    let cache = ReleaseDigestCache::default();
    let manifest = read_manifest(&cache, directory.path(), "manifest", MANIFEST.as_bytes())?;
    let expected = format!("{:x}", Sha256::digest(&bytes));
    assert_eq!(
        observe_reads(&cache, &path, &manifest)?,
        (expected.clone(), bytes.len() as u64)
    );
    assert_eq!(
        observe_reads(&cache, &path, &manifest)?,
        (expected.clone(), 0)
    );
    let manifest_path = directory.path().join("manifest");
    std::fs::set_permissions(&manifest_path, std::fs::Permissions::from_mode(0o755))?;
    std::fs::write(&manifest_path, b"changed actual manifest bytes")?;
    std::fs::set_permissions(&manifest_path, std::fs::Permissions::from_mode(0o555))?;
    assert!(cache.sha256(&path, &manifest).is_err());
    let changed_manifest = cache.manifest(&manifest_path, /*maximum*/ 32 * 1024)?;
    assert_eq!(
        observe_reads(&cache, &path, &changed_manifest)?,
        (expected.clone(), bytes.len() as u64)
    );
    assert_eq!(
        observe_reads(&cache, &path, &changed_manifest)?,
        (expected, 0)
    );
    Ok(())
}

#[test]
#[ignore = "requires root and protected native filesystem"]
fn same_length_same_mtime_mutation_and_inode_replacement_require_full_reads()
-> Result<(), Box<dyn std::error::Error>> {
    let directory = root_fixture()?;
    let original = vec![b'a'; 70_001];
    let changed_bytes = vec![b'b'; original.len()];
    let path = readonly_program(directory.path(), "program", &original)?;
    let cache = ReleaseDigestCache::default();
    let manifest = read_manifest(&cache, directory.path(), "manifest", MANIFEST.as_bytes())?;
    let original_digest = format!("{:x}", Sha256::digest(&original));
    assert_eq!(cache.sha256(&path, &manifest)?, original_digest);
    let original_metadata = std::fs::metadata(&path)?;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o755))?;
    std::fs::write(&path, &changed_bytes)?;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o555))?;
    // Preserve mtime deliberately: the accepted key must also cover ctime and
    // the real inode, rather than trusting size/mtime as a content proof.
    File::open(&path)?.set_times(
        std::fs::FileTimes::new()
            .set_accessed(original_metadata.accessed()?)
            .set_modified(original_metadata.modified()?),
    )?;
    let changed_metadata = std::fs::metadata(&path)?;
    assert_eq!(
        (
            changed_metadata.len(),
            changed_metadata.mtime(),
            changed_metadata.mtime_nsec()
        ),
        (
            original_metadata.len(),
            original_metadata.mtime(),
            original_metadata.mtime_nsec()
        )
    );
    let changed_digest = format!("{:x}", Sha256::digest(&changed_bytes));
    assert_eq!(
        observe_reads(&cache, &path, &manifest)?,
        (changed_digest.clone(), changed_bytes.len() as u64)
    );

    let stale = File::open(&path)?;
    let replacement = readonly_program(directory.path(), "replacement", &changed_bytes)?;
    std::fs::rename(&replacement, &path)?;
    assert!(cache.opened_sha256(&path, &manifest, stale).is_err());
    assert_eq!(
        observe_reads(&cache, &path, &manifest)?,
        (changed_digest, changed_bytes.len() as u64)
    );
    Ok(())
}

#[test]
#[ignore = "requires root and protected native filesystem"]
fn unsafe_parent_and_hardlink_metadata_cannot_reuse_root_custody_hit()
-> Result<(), Box<dyn std::error::Error>> {
    let directory = root_fixture()?;
    let bytes = vec![b'p'; 70_001];
    let path = readonly_program(directory.path(), "program", &bytes)?;
    let cache = ReleaseDigestCache::default();
    let manifest = read_manifest(&cache, directory.path(), "manifest", MANIFEST.as_bytes())?;
    let expected = format!("{:x}", Sha256::digest(&bytes));
    assert_eq!(cache.sha256(&path, &manifest)?, expected);
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o775))?;
    assert!(
        matches!(cache.sha256(&path, &manifest), Err(FleetRegistryError::Corrupt(message)) if message == "release manifest changed during program validation")
    );
    let manifest = cache.manifest(
        &directory.path().join("manifest"),
        /*maximum*/ 32 * 1024,
    )?;
    assert_eq!(
        observe_reads(&cache, &path, &manifest)?,
        (expected.clone(), bytes.len() as u64)
    );
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let manifest = cache.manifest(
        &directory.path().join("manifest"),
        /*maximum*/ 32 * 1024,
    )?;
    std::fs::hard_link(&path, directory.path().join("alias"))?;
    assert_eq!(
        observe_reads(&cache, &path, &manifest)?,
        (expected, bytes.len() as u64)
    );
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o755))?;
    assert!(cache.sha256(&path, &manifest).is_err());
    Ok(())
}

#[test]
#[ignore = "requires root and protected native filesystem"]
fn many_independent_actual_programs_keep_digest_memory_bounded()
-> Result<(), Box<dyn std::error::Error>> {
    let directory = root_fixture()?;
    let cache = ReleaseDigestCache::default();
    let manifest = read_manifest(&cache, directory.path(), "manifest", MANIFEST.as_bytes())?;
    for sequence in 0..MAX_CACHED_PROGRAMS + 7 {
        let bytes = sequence.to_be_bytes();
        let path = readonly_program(directory.path(), &format!("program-{sequence:04}"), &bytes)?;
        assert_eq!(
            cache.sha256(&path, &manifest)?,
            format!("{:x}", Sha256::digest(bytes))
        );
    }
    assert_eq!(
        cache.entries.lock().map_err(|_| "cache poisoned")?.len(),
        MAX_CACHED_PROGRAMS
    );
    Ok(())
}

#[test]
#[ignore = "requires root and protected native filesystem"]
fn deferred_cold_or_changed_identity_reads_no_program_bytes()
-> Result<(), Box<dyn std::error::Error>> {
    let directory = root_fixture()?;
    let path = readonly_program(directory.path(), "program", b"original bytes")?;
    let cache = ReleaseDigestCache::default();
    let manifest = read_manifest(&cache, directory.path(), "manifest", MANIFEST.as_bytes())?;
    let mut cold = File::open(&path)?;
    assert!(matches!(
        cache.opened_digest(
            &path,
            &manifest,
            cold.try_clone()?,
            /*defer_cold_read*/ true
        ),
        Err(FleetRegistryError::ReleasePrevalidationRequired)
    ));
    assert_eq!(cold.stream_position()?, 0);
    let expected = cache.sha256(&path, &manifest)?;
    assert_eq!(cache.sha256_prevalidated(&path, &manifest)?, expected);
    let replacement = readonly_program(directory.path(), "replacement", b"different data")?;
    std::fs::rename(replacement, &path)?;
    let mut changed = File::open(&path)?;
    assert!(matches!(
        cache.opened_digest(
            &path,
            &manifest,
            changed.try_clone()?,
            /*defer_cold_read*/ true
        ),
        Err(FleetRegistryError::ReleasePrevalidationRequired)
    ));
    assert_eq!(changed.stream_position()?, 0);
    Ok(())
}
