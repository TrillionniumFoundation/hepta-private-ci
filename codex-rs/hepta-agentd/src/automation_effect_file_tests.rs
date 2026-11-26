use super::*;
use std::io::Write;

const TEST_LIMIT: u64 = 4096;
const LABEL: &str = "effect operator file";

type TestResult = Result<(), Box<dyn std::error::Error>>;

fn write_file(path: &Path, bytes: &[u8]) -> std::io::Result<()> {
    fs::write(path, bytes)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;

        fs::set_permissions(path, fs::Permissions::from_mode(0o600))?;
    }
    Ok(())
}

#[test]
fn valid_private_operator_file_at_exact_limit_is_read() -> TestResult {
    let temp = tempfile::tempdir()?;
    let path = temp.path().canonicalize()?.join("effect.json");
    let expected = vec![b' '; TEST_LIMIT as usize];
    write_file(&path, &expected)?;
    assert_eq!(read_protected_file(&path, TEST_LIMIT, LABEL)?, expected);
    Ok(())
}

#[test]
fn growth_after_open_is_bounded_and_rejected() -> TestResult {
    let temp = tempfile::tempdir()?;
    let path = temp.path().canonicalize()?.join("effect.json");
    write_file(&path, b"trusted")?;
    let reader = ProtectedEffectFile::open(&path, TEST_LIMIT, LABEL)?;
    fs::OpenOptions::new()
        .append(true)
        .open(&path)?
        .write_all(&vec![b' '; TEST_LIMIT as usize])?;
    assert!(reader.read(TEST_LIMIT, LABEL).is_err());
    Ok(())
}

#[cfg(unix)]
#[test]
fn writable_parent_is_rejected_even_for_a_private_regular_file() -> TestResult {
    use std::os::unix::fs::PermissionsExt;

    let temp = tempfile::tempdir()?;
    let path = temp.path().canonicalize()?.join("effect.json");
    write_file(&path, b"trusted")?;
    for mode in [0o720, 0o702, 0o1777] {
        fs::set_permissions(temp.path(), fs::Permissions::from_mode(mode))?;
        assert!(read_protected_file(&path, TEST_LIMIT, LABEL).is_err());
    }
    Ok(())
}

#[cfg(unix)]
#[test]
fn writable_ancestor_is_rejected_above_a_private_parent() -> TestResult {
    use std::os::unix::fs::PermissionsExt;

    let temp = tempfile::tempdir()?;
    let root = temp.path().canonicalize()?;
    let private = root.join("private");
    fs::create_dir(&private)?;
    fs::set_permissions(&private, fs::Permissions::from_mode(0o700))?;
    let path = private.join("effect.json");
    write_file(&path, b"trusted")?;
    fs::set_permissions(&root, fs::Permissions::from_mode(0o777))?;
    assert!(read_protected_file(&path, TEST_LIMIT, LABEL).is_err());
    Ok(())
}

#[cfg(unix)]
#[test]
fn trusted_sticky_ancestor_accepts_a_private_parent() -> TestResult {
    use std::os::unix::fs::PermissionsExt;

    let temp = tempfile::tempdir()?;
    let root = temp.path().canonicalize()?;
    let private = root.join("private");
    fs::create_dir(&private)?;
    fs::set_permissions(&private, fs::Permissions::from_mode(0o700))?;
    let path = private.join("effect.json");
    write_file(&path, b"trusted")?;
    fs::set_permissions(&root, fs::Permissions::from_mode(0o1777))?;
    assert_eq!(read_protected_file(&path, TEST_LIMIT, LABEL)?, b"trusted");
    Ok(())
}

#[cfg(unix)]
#[test]
fn namespace_permission_drift_is_rejected_after_open() -> TestResult {
    use std::os::unix::fs::PermissionsExt;

    let temp = tempfile::tempdir()?;
    let root = temp.path().canonicalize()?;
    let path = root.join("effect.json");
    write_file(&path, b"trusted")?;
    fs::set_permissions(&root, fs::Permissions::from_mode(0o700))?;
    let reader = ProtectedEffectFile::open(&path, TEST_LIMIT, LABEL)?;
    fs::set_permissions(&root, fs::Permissions::from_mode(0o755))?;
    assert!(reader.read(TEST_LIMIT, LABEL).is_err());
    Ok(())
}

#[cfg(unix)]
#[test]
fn same_file_in_replaced_parent_is_rejected_after_open() -> TestResult {
    let temp = tempfile::tempdir()?;
    let root = temp.path().canonicalize()?;
    let parent = root.join("parent");
    let alternate = root.join("alternate");
    fs::create_dir(&parent)?;
    fs::create_dir(&alternate)?;
    let path = parent.join("effect.json");
    write_file(&path, b"trusted")?;
    fs::hard_link(&path, alternate.join("effect.json"))?;
    let reader = ProtectedEffectFile::open(&path, TEST_LIMIT, LABEL)?;
    fs::rename(&parent, root.join("old"))?;
    fs::rename(&alternate, &parent)?;
    assert!(same_file_version(&reader.metadata, &fs::metadata(&path)?));
    assert!(reader.read(TEST_LIMIT, LABEL).is_err());
    Ok(())
}

#[cfg(unix)]
#[test]
fn final_component_symlink_is_rejected_before_and_after_open() -> TestResult {
    let temp = tempfile::tempdir()?;
    let root = temp.path().canonicalize()?;
    let path = root.join("effect.json");
    let retained = root.join("retained.json");
    write_file(&path, b"trusted")?;
    let reader = ProtectedEffectFile::open(&path, TEST_LIMIT, LABEL)?;
    fs::rename(&path, &retained)?;
    std::os::unix::fs::symlink(&retained, &path)?;
    assert!(reader.read(TEST_LIMIT, LABEL).is_err());
    assert!(read_protected_file(&path, TEST_LIMIT, LABEL).is_err());
    Ok(())
}
