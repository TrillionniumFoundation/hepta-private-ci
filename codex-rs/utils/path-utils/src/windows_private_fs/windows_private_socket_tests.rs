use std::fs;
use std::io;

use pretty_assertions::assert_eq;

use super::PrivateSocketDirectory;
use crate::windows_private_fs::PrivateDirectory;

#[test]
fn socket_directory_pins_its_parent_and_every_physical_ancestor() -> io::Result<()> {
    let temp = tempfile::tempdir()?;
    let ancestor = temp.path().join("ancestor");
    fs::create_dir(&ancestor)?;
    let parent = ancestor.join("sockets");
    let directory = PrivateSocketDirectory::open_or_create(&parent)?;
    assert!(directory.open_socket("absent.ctl")?.is_none());
    assert!(fs::rename(&parent, ancestor.join("moved-sockets")).is_err());
    assert!(fs::rename(&ancestor, temp.path().join("moved-ancestor")).is_err());
    PrivateDirectory::open_existing(&parent)?;
    drop(directory);
    fs::rename(&ancestor, temp.path().join("moved-ancestor"))?;
    Ok(())
}

#[test]
fn non_socket_entries_are_refused_and_preserved() -> io::Result<()> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().join("sockets");
    let directory = PrivateSocketDirectory::open_or_create(&root)?;
    fs::write(root.join("regular.ctl"), b"retain ordinary file")?;
    fs::create_dir(root.join("directory.ctl"))?;
    assert!(directory.open_socket("regular.ctl").is_err());
    assert!(directory.open_socket("directory.ctl").is_err());
    assert_eq!(fs::read(root.join("regular.ctl"))?, b"retain ordinary file");
    assert!(fs::symlink_metadata(root.join("directory.ctl"))?.is_dir());
    assert_eq!(fs::read_dir(root.join("directory.ctl"))?.count(), 0);
    for name in ["../escape", "other\\entry", "socket:stream", "", ".", ".."] {
        assert_eq!(
            directory.open_socket(name).unwrap_err().kind(),
            io::ErrorKind::InvalidInput
        );
    }
    Ok(())
}

#[test]
fn foreign_reparse_entries_and_ancestors_are_refused_without_following_them() -> io::Result<()> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().join("sockets");
    let target = temp.path().join("target");
    fs::create_dir(&target)?;
    let directory = PrivateSocketDirectory::open_or_create(&root)?;
    let junction = root.join("junction.ctl");
    crate::windows_private_fs::tests::create_junction(&junction, &target)?;
    assert!(directory.open_socket("junction.ctl").is_err());
    assert!(PrivateSocketDirectory::open_or_create(&junction).is_err());
    assert!(PrivateSocketDirectory::open_or_create(&junction.join("sockets")).is_err());
    assert!(fs::symlink_metadata(&junction).is_ok());
    assert_eq!(fs::read_dir(&target)?.count(), 0);
    Ok(())
}
