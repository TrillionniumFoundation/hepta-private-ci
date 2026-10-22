use super::*;

use pretty_assertions::assert_eq;
use std::os::windows::fs::symlink_file;

#[test]
fn ordinary_entries_cannot_be_classified_as_socket_rendezvous() -> io::Result<()> {
    let directory = tempfile::tempdir()?;
    let file = directory.path().join("ordinary");
    std::fs::write(&file, b"preserve these bytes")?;
    assert_eq!(
        [
            is_socket_entry(&file)?,
            is_socket_entry(directory.path())?,
            is_socket_entry(&directory.path().join("absent"))?,
        ],
        [false, false, false]
    );
    assert_eq!(std::fs::read(file)?, b"preserve these bytes");
    Ok(())
}

#[test]
fn live_and_closed_af_unix_entries_retain_their_socket_tag() -> io::Result<()> {
    let directory = tempfile::tempdir()?;
    let socket = directory.path().join("socket");
    let listener = uds_windows::UnixListener::bind(&socket)?;
    assert!(is_socket_entry(&socket)?);
    drop(listener);
    assert!(is_socket_entry(&socket)?);
    Ok(())
}

#[test]
fn symlinks_to_socket_regular_and_missing_targets_are_not_sockets() -> io::Result<()> {
    let directory = tempfile::tempdir()?;
    let socket = directory.path().join("socket");
    let _listener = uds_windows::UnixListener::bind(&socket)?;
    let regular = directory.path().join("ordinary");
    std::fs::write(&regular, b"not a socket")?;
    for (index, target) in [socket, regular, directory.path().join("absent")]
        .into_iter()
        .enumerate()
    {
        let link = directory.path().join(format!("link-{index}"));
        symlink_file(target, &link)?;
        assert!(!is_socket_entry(&link)?);
        assert!(std::fs::symlink_metadata(link)?.file_type().is_symlink());
    }
    Ok(())
}
