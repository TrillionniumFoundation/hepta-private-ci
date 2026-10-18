use super::*;

#[test]
fn regular_configuration_is_read_and_its_original_byte_bound_remains_required()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    let path = temp.path().join("host.json");
    std::fs::write(&path, b"config")?;
    assert_eq!(bounded_file(path.clone(), 6)?, b"config");
    assert!(bounded_file(path, 5).is_err());
    Ok(())
}

#[cfg(unix)]
#[test]
fn a_configured_alias_still_resolves_to_its_original_regular_file()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    let path = temp.path().join("host.json");
    let alias = temp.path().join("alias.json");
    std::fs::write(&path, b"config")?;
    std::os::unix::fs::symlink(&path, &alias)?;
    assert_eq!(bounded_file(alias, 6)?, b"config");
    Ok(())
}

#[cfg(unix)]
#[test]
fn inspected_configuration_replaced_with_a_fifo_is_rejected_without_a_writer()
-> Result<(), Box<dyn std::error::Error>> {
    use std::os::unix::ffi::OsStrExt;
    let temp = tempfile::tempdir()?;
    let path = temp.path().join("host.json");
    std::fs::write(&path, b"config")?;
    let inspected = ConfigFilePreflight::capture(path.clone())?;
    std::fs::remove_file(&path)?;
    let name = std::ffi::CString::new(path.as_os_str().as_bytes())?;
    if unsafe { libc::mkfifo(name.as_ptr(), 0o600) } != 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    assert!(inspected.read(6).is_err());
    Ok(())
}

#[cfg(unix)]
#[test]
fn inspected_leaf_cannot_be_replaced_by_a_symlink_or_directory()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    let path = temp.path().join("host.json");
    std::fs::write(&path, b"config")?;
    let inspected = ConfigFilePreflight::capture(path.clone())?;
    let retained = temp.path().join("retained.json");
    std::fs::rename(&path, &retained)?;
    std::os::unix::fs::symlink(&retained, &path)?;
    assert!(inspected.read(6).is_err());
    std::fs::remove_file(&path)?;
    std::fs::write(&path, b"config")?;
    let inspected = ConfigFilePreflight::capture(path.clone())?;
    std::fs::remove_file(&path)?;
    std::fs::create_dir(&path)?;
    assert!(inspected.read(6).is_err());
    Ok(())
}
