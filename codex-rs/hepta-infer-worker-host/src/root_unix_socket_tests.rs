use super::*;
use pretty_assertions::assert_eq;

fn root_directory() -> Result<(tempfile::TempDir, u32)> {
    assert_eq!(rustix::process::geteuid().as_raw(), 0);
    let group = rustix::process::getegid()
        .as_raw()
        .checked_add(1)
        .ok_or_else(|| anyhow::anyhow!("fixture group has no nondefault successor"))?;
    let directory = tempfile::Builder::new()
        .prefix("hepta-original-root-socket-")
        .tempdir_in("/run")?;
    std::os::unix::fs::chown(directory.path(), Some(0), Some(group))?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o750))?;
    Ok((directory, group))
}

#[test]
fn socket_guard_removes_only_its_original_socket() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("endpoint.sock");
    let listener = std::os::unix::net::UnixListener::bind(&path)?;
    let metadata = std::fs::symlink_metadata(&path)?;
    let guard = SocketGuard {
        path: path.clone(),
        dev: metadata.dev(),
        ino: metadata.ino(),
    };
    drop(guard);
    assert!(!path.exists());
    drop(listener);
    let listener = std::os::unix::net::UnixListener::bind(&path)?;
    let metadata = std::fs::symlink_metadata(&path)?;
    let guard = SocketGuard {
        path: path.clone(),
        dev: metadata.dev(),
        ino: metadata.ino(),
    };
    std::fs::remove_file(&path)?;
    std::fs::write(&path, b"replacement owner file")?;
    drop(guard);
    assert_eq!(std::fs::read(&path)?, b"replacement owner file");
    drop(listener);
    Ok(())
}

#[tokio::test]
#[ignore = "requires an actual Root process and isolated protected /run directory"]
async fn actual_root_socket_binds_nondefault_enrolled_group_and_refuses_live_listener() -> Result<()>
{
    let (directory, group) = root_directory()?;
    let path = directory.path().join("endpoint.sock");
    let (listener, guard) = bind_socket(&path, group).await?;
    let before = std::fs::symlink_metadata(&path)?;
    assert_eq!(
        (before.uid(), before.gid(), before.mode() & 0o7777),
        (0, group, 0o660)
    );
    assert!(bind_socket(&path, group).await.is_err());
    let after = std::fs::symlink_metadata(&path)?;
    assert_eq!((after.dev(), after.ino()), (before.dev(), before.ino()));
    let client = UnixStream::connect(&path).await?;
    drop(client);
    drop(listener);
    drop(guard);
    assert!(!path.exists());
    Ok(())
}

#[tokio::test]
#[ignore = "requires an actual Root process and isolated protected /run directory"]
async fn actual_root_socket_retires_only_stale_inode_and_preserves_replacement_owner() -> Result<()>
{
    let (directory, group) = root_directory()?;
    let path = directory.path().join("endpoint.sock");
    let (listener, old_guard) = bind_socket(&path, group).await?;
    let old = std::fs::symlink_metadata(&path)?;
    drop(listener);
    let (listener, guard) = bind_socket(&path, group).await?;
    let current = std::fs::symlink_metadata(&path)?;
    assert_ne!((current.dev(), current.ino()), (old.dev(), old.ino()));
    drop(old_guard);
    assert!(path.exists());
    std::fs::remove_file(&path)?;
    std::fs::write(&path, b"replacement owner file")?;
    drop(guard);
    assert_eq!(std::fs::read(&path)?, b"replacement owner file");
    assert!(bind_socket(&path, group).await.is_err());
    assert_eq!(std::fs::read(&path)?, b"replacement owner file");
    drop(listener);
    Ok(())
}

#[tokio::test]
#[ignore = "requires an actual Root process and isolated protected /run directory"]
async fn actual_root_socket_denies_wrong_namespace_without_creating_endpoint() -> Result<()> {
    let (directory, group) = root_directory()?;
    let path = directory.path().join("endpoint.sock");
    assert!(bind_socket(&path, group + 1).await.is_err());
    assert!(!path.exists());
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o770))?;
    assert!(bind_socket(&path, group).await.is_err());
    assert!(!path.exists());
    Ok(())
}
