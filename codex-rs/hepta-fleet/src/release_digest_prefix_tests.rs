use super::*;
use pretty_assertions::assert_eq;
use std::io::Seek;
use std::os::unix::fs::PermissionsExt;

fn write_readonly(
    directory: &Path,
    name: &str,
    bytes: &[u8],
) -> Result<PathBuf, Box<dyn std::error::Error>> {
    let path = directory.join(name);
    std::fs::write(&path, bytes)?;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o555))?;
    Ok(path)
}

fn fixture() -> Result<tempfile::TempDir, Box<dyn std::error::Error>> {
    let directory = tempfile::Builder::new()
        .prefix("h7-prefix-")
        .tempdir_in("/var/lib")?;
    assert_eq!(directory.path().metadata()?.uid(), 0);
    Ok(directory)
}

#[test]
fn ordinary_prefix_reads_all_bytes_and_keeps_original_domains()
-> Result<(), Box<dyn std::error::Error>> {
    let directory = tempfile::tempdir()?;
    compare_prefixes(directory.path(), /*cacheable*/ false)
}

#[test]
#[ignore = "requires root and protected native filesystem"]
fn root_prefix_clones_exact_original_hash_without_program_reads()
-> Result<(), Box<dyn std::error::Error>> {
    let directory = fixture()?;
    compare_prefixes(directory.path(), /*cacheable*/ true)
}

fn compare_prefixes(directory: &Path, cacheable: bool) -> Result<(), Box<dyn std::error::Error>> {
    let bytes: Vec<u8> = (0..70_001).map(|index| (index % 251) as u8).collect();
    let program = write_readonly(directory, "program", &bytes)?;
    let manifest_path = write_readonly(directory, "manifest", b"physical manifest bytes")?;
    let cache = ReleaseDigestCache::default();
    let manifest = cache.manifest(&manifest_path, /*maximum*/ 32 * 1024)?;
    let expected_sha256 = cache.sha256(&program, &manifest)?;
    for domain in [LaunchDigestDomain::Agent, LaunchDigestDomain::Matrix] {
        let mut original = Sha256::new();
        if matches!(domain, LaunchDigestDomain::Matrix) {
            original.update(b"hepta.local-host.matrix.v1\0");
        }
        original.update(&bytes);
        let mut prefix =
            cache.launch_prefix(&program, manifest.clone(), &expected_sha256, domain)?;
        assert_eq!(
            prefix.file.stream_position()?,
            if cacheable { 0 } else { bytes.len() as u64 }
        );
        // Preserve concatenation, including unaligned partial blocks and real
        // binary lengths. Neither finalized SHA string nor bytes are substituted.
        for context in [
            b"manifest-context".as_slice(),
            &41_u64.to_be_bytes(),
            b"env\0value\0args",
        ] {
            original.update(context);
            prefix.update(context);
        }
        let expected: [u8; 32] = original.finalize().into();
        assert_eq!(prefix.finalize()?, expected);
    }
    Ok(())
}

#[test]
#[ignore = "requires root and protected native filesystem"]
fn prefix_finalization_rejects_changed_inode_manifest_and_custody()
-> Result<(), Box<dyn std::error::Error>> {
    for change in ["program", "manifest", "custody"] {
        let directory = fixture()?;
        let program = write_readonly(
            directory.path(),
            "program",
            b"verified actual program bytes",
        )?;
        let manifest_path =
            write_readonly(directory.path(), "manifest", b"physical manifest bytes")?;
        let cache = ReleaseDigestCache::default();
        let manifest = cache.manifest(&manifest_path, /*maximum*/ 32 * 1024)?;
        let digest = cache.sha256(&program, &manifest)?;
        let mut prefix =
            cache.launch_prefix(&program, manifest, &digest, LaunchDigestDomain::Agent)?;
        prefix.update(b"actual launch context");
        match change {
            "program" => {
                let next =
                    write_readonly(directory.path(), "next", b"verified actual program bytes")?;
                std::fs::rename(next, &program)?;
            }
            "manifest" => {
                let next = write_readonly(directory.path(), "next", b"physical manifest bytes")?;
                std::fs::rename(next, &manifest_path)?;
            }
            "custody" => {
                std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o777))?
            }
            _ => unreachable!(),
        }
        assert!(prefix.finalize().is_err(), "changed {change}");
    }
    Ok(())
}

#[test]
#[ignore = "requires root and protected native filesystem"]
fn committed_prefix_retains_actual_fd_and_rejects_change_before_spawn()
-> Result<(), Box<dyn std::error::Error>> {
    let directory = fixture()?;
    let program = write_readonly(directory.path(), "program", b"actual installed program")?;
    let manifest_path = write_readonly(directory.path(), "manifest", b"physical manifest bytes")?;
    let cache = ReleaseDigestCache::default();
    let manifest = cache.manifest(&manifest_path, /*maximum*/ 32 * 1024)?;
    let digest = cache.sha256(&program, &manifest)?;
    let mut prefix = cache.launch_prefix(&program, manifest, &digest, LaunchDigestDomain::Agent)?;
    prefix.update(b"context before durable prepare");
    let committed = prefix.commit()?;
    committed.verify_current()?;
    let next = write_readonly(directory.path(), "next", b"actual installed program")?;
    std::fs::rename(next, &program)?;
    assert!(committed.verify_current().is_err());
    assert_eq!(committed.file.metadata()?.nlink(), 0);
    Ok(())
}

#[test]
#[ignore = "requires root and protected native filesystem"]
fn pinned_prefix_survives_bounded_cache_pressure_and_full_reads_remain_valid()
-> Result<(), Box<dyn std::error::Error>> {
    let directory = fixture()?;
    let cache = ReleaseDigestCache::default();
    let manifest_path = write_readonly(directory.path(), "manifest", b"physical manifest bytes")?;
    let manifest = cache.manifest(&manifest_path, /*maximum*/ 32 * 1024)?;
    let mut paths = Vec::new();
    for index in 0..MAX_CACHED_PROGRAMS {
        let path = write_readonly(
            directory.path(),
            &format!("program-{index:04}"),
            b"actual small program",
        )?;
        cache.sha256(&path, &manifest)?;
        paths.push(path);
    }
    let pin = cache.pin_programs(&paths, &manifest)?;
    let next = write_readonly(directory.path(), "next", b"new actual program bytes")?;
    assert_eq!(
        cache.sha256(&next, &manifest)?,
        format!("{:x}", Sha256::digest(b"new actual program bytes"))
    );
    assert!(matches!(
        cache.sha256_prevalidated(&next, &manifest),
        Err(FleetRegistryError::ReleasePrevalidationRequired)
    ));
    assert_eq!(
        cache.entries.lock().map_err(|_| "cache poisoned")?.len(),
        MAX_CACHED_PROGRAMS
    );
    for path in &paths {
        let mut file = File::open(path)?;
        cache.opened_digest(
            path,
            &manifest,
            file.try_clone()?,
            /*defer_cold_read*/ true,
        )?;
        assert_eq!(file.stream_position()?, 0);
    }
    drop(pin);
    cache.sha256(&next, &manifest)?;
    assert!(cache.sha256_prevalidated(&next, &manifest).is_ok());
    assert_eq!(
        cache.entries.lock().map_err(|_| "cache poisoned")?.len(),
        MAX_CACHED_PROGRAMS
    );
    Ok(())
}

#[test]
#[ignore = "requires root and protected native filesystem"]
fn admitted_prefix_after_eviction_reads_original_bytes_instead_of_failing()
-> Result<(), Box<dyn std::error::Error>> {
    let directory = fixture()?;
    let cache = ReleaseDigestCache::default();
    let manifest_path = write_readonly(directory.path(), "manifest", b"physical manifest bytes")?;
    let manifest = cache.manifest(&manifest_path, /*maximum*/ 32 * 1024)?;
    let bytes = b"actual original program";
    let first = write_readonly(directory.path(), "000-first", bytes)?;
    let expected_sha = cache.sha256(&first, &manifest)?;
    for index in 0..MAX_CACHED_PROGRAMS {
        let path = write_readonly(
            directory.path(),
            &format!("100-program-{index:04}"),
            b"other actual program",
        )?;
        cache.sha256(&path, &manifest)?;
    }
    assert!(matches!(
        cache.sha256_prevalidated(&first, &manifest),
        Err(FleetRegistryError::ReleasePrevalidationRequired)
    ));
    let mut prefix =
        cache.launch_prefix(&first, manifest, &expected_sha, LaunchDigestDomain::Agent)?;
    assert_eq!(prefix.file.stream_position()?, bytes.len() as u64);
    prefix.update(b"context");
    let mut original = Sha256::new();
    original.update(bytes);
    original.update(b"context");
    let expected: [u8; 32] = original.finalize().into();
    assert_eq!(prefix.finalize()?, expected);
    Ok(())
}
