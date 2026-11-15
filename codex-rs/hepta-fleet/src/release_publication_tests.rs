use super::restore_unsealed_staging;
use pretty_assertions::assert_eq;
use std::fs;
use std::os::unix::fs::PermissionsExt;

#[test]
fn failed_seal_restores_only_the_original_unsealed_directory() -> std::io::Result<()> {
    let temp = tempfile::tempdir()?;
    let staging = temp.path().join("staging");
    let published = temp.path().join("published");
    fs::create_dir(&staging)?;
    fs::set_permissions(&staging, fs::Permissions::from_mode(0o700))?;
    fs::write(staging.join("payload"), b"original")?;
    let identity = fs::symlink_metadata(&staging)?;
    fs::rename(&staging, &published)?;

    assert!(restore_unsealed_staging(&published, &staging, &identity));
    assert!(!published.exists());
    assert_eq!(fs::read(staging.join("payload"))?, b"original");
    // The restored name is usable by a normal fresh installation attempt.
    fs::remove_dir_all(&staging)?;
    fs::create_dir(&staging)?;
    fs::write(staging.join("payload"), b"retry")?;
    fs::rename(&staging, &published)?;
    assert_eq!(fs::read(published.join("payload"))?, b"retry");
    Ok(())
}

#[test]
fn failed_seal_preserves_a_replacement_directory_and_existing_staging() -> std::io::Result<()> {
    let temp = tempfile::tempdir()?;
    let staging = temp.path().join("staging");
    let published = temp.path().join("published");
    let retained = temp.path().join("retained");
    fs::create_dir(&staging)?;
    fs::write(staging.join("payload"), b"original")?;
    let identity = fs::symlink_metadata(&staging)?;
    fs::rename(&staging, &retained)?;
    fs::create_dir(&published)?;
    fs::write(published.join("payload"), b"replacement")?;

    assert!(!restore_unsealed_staging(&published, &staging, &identity));
    assert_eq!(fs::read(published.join("payload"))?, b"replacement");
    assert_eq!(fs::read(retained.join("payload"))?, b"original");
    fs::remove_dir_all(&published)?;
    fs::rename(&retained, &published)?;
    fs::create_dir(&staging)?;
    fs::write(staging.join("payload"), b"occupied")?;
    assert!(!restore_unsealed_staging(&published, &staging, &identity));
    assert_eq!(fs::read(staging.join("payload"))?, b"occupied");
    assert_eq!(fs::read(published.join("payload"))?, b"original");
    Ok(())
}

#[test]
fn sealed_publication_is_never_made_writable_for_cleanup() -> std::io::Result<()> {
    let temp = tempfile::tempdir()?;
    let staging = temp.path().join("staging");
    let published = temp.path().join("published");
    fs::create_dir(&staging)?;
    fs::write(staging.join("payload"), b"admitted")?;
    let identity = fs::symlink_metadata(&staging)?;
    fs::rename(&staging, &published)?;
    fs::set_permissions(&published, fs::Permissions::from_mode(0o555))?;

    assert!(!restore_unsealed_staging(&published, &staging, &identity));
    assert!(!staging.exists());
    assert_eq!(fs::read(published.join("payload"))?, b"admitted");
    assert_eq!(
        fs::metadata(&published)?.permissions().mode() & 0o777,
        0o555
    );
    fs::set_permissions(&published, fs::Permissions::from_mode(0o700))?;
    Ok(())
}
