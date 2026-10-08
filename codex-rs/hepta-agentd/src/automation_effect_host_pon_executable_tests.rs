//! Real Linux ELF/object tests; not Chain or independent-operator acceptance.
use super::*;
use sha2::Digest;
use sha2::Sha256;
use std::fs;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::process::Command;
use std::time::Duration;

type TestResult = Result<(), Box<dyn std::error::Error>>;

fn fixture() -> Result<(tempfile::TempDir, PathBuf, String), Box<dyn std::error::Error>> {
    let directory = tempfile::tempdir()?;
    let source = directory.path().canonicalize()?.join("node");
    let bytes = fs::read("/usr/bin/true")?;
    fs::write(&source, &bytes)?;
    fs::set_permissions(&source, fs::Permissions::from_mode(0o700))?;
    Ok((directory, source, format!("{:x}", Sha256::digest(&bytes))))
}

#[test]
fn pon_path_replacement_cannot_replace_sealed_executable() -> TestResult {
    let (_directory, source, expected) = fixture()?;
    let executable = PinnedExecutable::prepare(&source, &expected, Instant::now() + Duration::from_secs(5))?;
    let replacement = source.with_extension("replacement");
    fs::copy("/usr/bin/false", &replacement)?;
    fs::rename(&replacement, &source)?;
    assert!(!Command::new(&source).status()?.success());
    assert!(Command::new(executable.path()).status()?.success());
    assert!(PinnedExecutable::prepare(&source, &expected, Instant::now() + Duration::from_secs(5)).is_err());
    Ok(())
}

#[test]
fn pon_same_inode_rewrite_cannot_change_sealed_executable() -> TestResult {
    let (_directory, source, expected) = fixture()?;
    let executable = PinnedExecutable::prepare(&source, &expected, Instant::now() + Duration::from_secs(5))?;
    fs::write(&source, fs::read("/usr/bin/false")?)?;
    assert!(!Command::new(&source).status()?.success());
    assert!(Command::new(executable.path()).status()?.success());
    Ok(())
}

#[test]
fn pon_sealed_object_denies_write_resize_and_execute_mode_change() -> TestResult {
    let (_directory, source, expected) = fixture()?;
    let executable = PinnedExecutable::prepare(&source, &expected, Instant::now() + Duration::from_secs(5))?;
    let mut duplicate = executable._file.try_clone()?;
    assert!(duplicate.write_all(b"changed").is_err());
    assert!(duplicate.set_len(0).is_err());
    assert!(duplicate.set_len(duplicate.metadata()?.len() + 1).is_err());
    assert!(duplicate.set_permissions(fs::Permissions::from_mode(0o400)).is_err());
    assert!(Command::new(executable.path()).status()?.success());
    Ok(())
}

#[test]
fn pon_expired_digest_script_and_symlink_inputs_refuse_before_execution() -> TestResult {
    let (_directory, source, expected) = fixture()?;
    assert!(PinnedExecutable::prepare(&source, &expected, Instant::now()).is_err());
    assert!(PinnedExecutable::prepare(&source, &"00".repeat(32), Instant::now() + Duration::from_secs(5)).is_err());
    let alias = source.with_extension("link");
    std::os::unix::fs::symlink(&source, &alias)?;
    assert!(PinnedExecutable::prepare(&alias, &expected, Instant::now() + Duration::from_secs(5)).is_err());
    let script = b"#!/bin/sh\nexit 0\n";
    fs::write(&source, script)?;
    let expected = format!("{:x}", Sha256::digest(script));
    assert!(PinnedExecutable::prepare(&source, &expected, Instant::now() + Duration::from_secs(5)).is_err());
    Ok(())
}

#[test]
fn pon_writable_or_nonexecutable_source_is_not_an_executable_grant() -> TestResult {
    let (_directory, source, expected) = fixture()?;
    for mode in [0o722, 0o600] {
        fs::set_permissions(&source, fs::Permissions::from_mode(mode))?;
        assert!(PinnedExecutable::prepare(&source, &expected, Instant::now() + Duration::from_secs(5)).is_err());
    }
    Ok(())
}
