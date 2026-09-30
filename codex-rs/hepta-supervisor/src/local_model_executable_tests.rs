use std::os::unix::fs::PermissionsExt;
use std::os::unix::process::CommandExt;
use std::process::Command;

use super::*;

fn fixture() -> anyhow::Result<(tempfile::TempDir, PathBuf, BTreeSet<String>)> {
    anyhow::ensure!(
        rustix::process::geteuid().as_raw() == 0,
        "root fixture required"
    );
    let directory = tempfile::Builder::new()
        .prefix("hepta-executable-native-")
        .tempdir_in("/var/lib/hepta-private-ci")?;
    let path = directory.path().join("program");
    let bytes = b"original-bytes";
    std::fs::write(&path, bytes)?;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o500))?;
    let digest = format!("{:x}", Sha256::digest(bytes));
    Ok((directory, path, BTreeSet::from([digest])))
}

fn enrolled(path: &Path, digests: &BTreeSet<String>) -> anyhow::Result<ExecutableCache> {
    ExecutableCache::prewarm(&BTreeSet::from([path.to_path_buf()]), digests)
}

#[test]
fn startup_enrollment_rejects_empty_or_unbounded_paths_before_opening_files() {
    let digests = BTreeSet::from(["a".repeat(64)]);
    assert!(ExecutableCache::prewarm(&BTreeSet::new(), &digests).is_err());
    let paths = (0..=MAX_ENROLLED_EXECUTABLES)
        .map(|index| PathBuf::from(format!("/does-not-exist/program-{index}")))
        .collect();
    assert!(ExecutableCache::prewarm(&paths, &digests).is_err());
}

#[test]
#[ignore = "requires root and the protected installation fixture parent"]
fn actual_proc_executable_matches_only_its_prewarmed_installation_inode() -> anyhow::Result<()> {
    let executable = Path::new("/usr/bin/sleep");
    let digest = format!("{:x}", Sha256::digest(std::fs::read(executable)?));
    let cache = enrolled(executable, &BTreeSet::from([digest.clone()]))?;
    let mut child = Command::new(executable)
        .arg("60")
        .uid(1000)
        .gid(1000)
        .spawn()?;
    let result = (|| -> anyhow::Result<()> {
        let process_executable = File::open(format!("/proc/{}/exe", child.id()))?;
        assert_eq!(cache.verify(&process_executable)?, digest);
        let (_directory, copy, _) = fixture()?;
        std::fs::copy(executable, &copy)?;
        std::fs::set_permissions(&copy, std::fs::Permissions::from_mode(0o500))?;
        assert!(cache.verify(&File::open(copy)?).is_err());
        Ok(())
    })();
    child.kill()?;
    child.wait()?;
    result
}

#[test]
#[ignore = "requires root and the protected installation fixture parent"]
fn same_inode_edits_and_replaced_installation_paths_revoke_the_cached_identity()
-> anyhow::Result<()> {
    {
        let (_directory, path, digests) = fixture()?;
        let cache = enrolled(&path, &digests)?;
        let executable = File::open(&path)?;
        assert!(cache.verify(&executable).is_ok());
        std::fs::write(&path, b"modified-bytes")?;
        assert!(cache.verify(&executable).is_err());
    }
    {
        let (directory, path, digests) = fixture()?;
        let cache = enrolled(&path, &digests)?;
        let old_executable = File::open(&path)?;
        std::fs::rename(&path, directory.path().join("old"))?;
        std::fs::write(&path, b"original-bytes")?;
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o500))?;
        assert!(cache.verify(&old_executable).is_err());
        assert!(cache.verify(&File::open(path)?).is_err());
    }
    Ok(())
}

#[test]
#[ignore = "requires root and the protected installation fixture parent"]
fn mutable_permissions_links_and_parents_cannot_reuse_or_create_enrollment() -> anyhow::Result<()> {
    let (directory, path, digests) = fixture()?;
    let cache = enrolled(&path, &digests)?;
    let executable = File::open(&path)?;
    assert!(enrolled(&path, &BTreeSet::from(["b".repeat(64)])).is_err());
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o520))?;
    assert!(cache.verify(&executable).is_err());
    assert!(enrolled(&path, &digests).is_err());
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o500))?;
    let cache = enrolled(&path, &digests)?;
    let link = directory.path().join("second-link");
    std::fs::hard_link(&path, &link)?;
    assert!(cache.verify(&executable).is_err());
    assert!(enrolled(&path, &digests).is_err());
    std::fs::remove_file(link)?;
    let cache = enrolled(&path, &digests)?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o777))?;
    assert!(cache.verify(&executable).is_err());
    assert!(enrolled(&path, &digests).is_err());
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    std::os::unix::fs::chown(&path, Some(1000), Some(1000))?;
    assert!(cache.verify(&executable).is_err());
    assert!(enrolled(&path, &digests).is_err());
    Ok(())
}
