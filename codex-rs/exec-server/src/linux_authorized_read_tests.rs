use super::*;
use codex_protocol::models::PermissionProfile;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn kernel_probe_and_advertised_capability_support_the_real_bounded_read() -> io::Result<()> {
    assert!(
        available(),
        "Linux qualification requires the actual kernel probe to succeed"
    );
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("file.txt");
    std::fs::write(&path, b"authorized")?;
    let sandbox = FileSystemSandboxContext::from_permission_profile_with_cwd(
        PermissionProfile::read_only(),
        PathUri::from_host_native_path(directory.path())?,
    );
    let bytes =
        read_bounded_authorized(&PathUri::from_host_native_path(&path)?, &sandbox, 10).await?;
    assert_eq!(
        (
            crate::local_environment_info()
                .capabilities
                .stable_handle_authorized_read,
            bytes
        ),
        (true, b"authorized".to_vec())
    );
    Ok(())
}

#[test]
fn secure_reopen_rejects_namespace_and_mount_identity_mismatches() -> io::Result<()> {
    assert!(
        available(),
        "Linux qualification requires the actual kernel probe to succeed"
    );
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("file.txt");
    std::fs::write(&path, b"authorized")?;
    let original = File::open(&path)?;
    let identity = file_identity(&original, Arc::new(MountNamespace::capture()?))?;
    let physical = stable_file_path(&original)?;
    let mut wrong_mount = identity.clone();
    wrong_mount.mount = wrong_mount.mount.wrapping_add(1);
    let mount_error = secure_reopen(physical.as_path(), &wrong_mount)
        .expect_err("a different mount cannot supply the authorized descriptor");

    let mut namespace = MountNamespace::capture()?;
    namespace.inode = namespace.inode.wrapping_add(1);
    let wrong_namespace = UniqueFileIdentity {
        namespace: Arc::new(namespace),
        ..identity
    };
    let namespace_error = secure_reopen(physical.as_path(), &wrong_namespace)
        .expect_err("a different namespace cannot supply the authorized descriptor");
    assert_eq!(
        (mount_error.kind(), namespace_error.kind()),
        (
            io::ErrorKind::PermissionDenied,
            io::ErrorKind::PermissionDenied
        )
    );
    Ok(())
}
