use super::ExecutorFileSystem;
use super::FileSystemSandboxContext;
use super::LocalFileSystem;
use codex_protocol::models::PermissionProfile;
use codex_protocol::permissions::FileSystemAccessMode;
use codex_protocol::permissions::FileSystemPath;
use codex_protocol::permissions::FileSystemSandboxEntry;
use codex_protocol::permissions::FileSystemSandboxPolicy;
use codex_protocol::permissions::NetworkSandboxPolicy;
use codex_utils_absolute_path::AbsolutePathBuf;
use codex_utils_path_uri::PathUri;
use std::io;
use std::path::Path;
use tokio::io::AsyncReadExt;

fn read_sandbox(root: &Path) -> io::Result<FileSystemSandboxContext> {
    let root = AbsolutePathBuf::from_absolute_path(root)?;
    let policy = FileSystemSandboxPolicy::restricted(vec![FileSystemSandboxEntry::new(
        FileSystemPath::Path {
            path: PathUri::from_abs_path(&root),
        },
        FileSystemAccessMode::Read,
    )]);
    let permissions =
        PermissionProfile::from_runtime_permissions(&policy, NetworkSandboxPolicy::Restricted);
    Ok(FileSystemSandboxContext::from_permission_profile_with_cwd(
        permissions,
        PathUri::from_abs_path(&root),
    ))
}

async fn authorized_read(
    file_system: &LocalFileSystem,
    path: &Path,
    sandbox: &FileSystemSandboxContext,
    max_bytes: usize,
) -> io::Result<Vec<u8>> {
    ExecutorFileSystem::read_file_bounded_authorized(
        file_system,
        &PathUri::from_host_native_path(path)?,
        sandbox,
        max_bytes,
    )
    .await
}

#[tokio::test]
async fn stable_handle_read_rejects_hardlink_provenance_ambiguity() -> io::Result<()> {
    if !super::stable_handle_authorized_read_available() {
        return Ok(());
    }

    let temp_dir = tempfile::tempdir()?;
    let allowed_dir = temp_dir.path().join("allowed");
    let denied_dir = temp_dir.path().join("denied");
    std::fs::create_dir_all(&allowed_dir)?;
    std::fs::create_dir_all(&denied_dir)?;
    let secret = denied_dir.join("secret.txt");
    let alias = allowed_dir.join("alias.txt");
    std::fs::write(&secret, b"secret")?;
    std::fs::hard_link(&secret, &alias)?;

    let error = authorized_read(
        &LocalFileSystem::unsandboxed(),
        &alias,
        &read_sandbox(&allowed_dir)?,
        128,
    )
    .await
    .expect_err("a hardlink into the authorized root must fail closed");
    assert_eq!(error.kind(), io::ErrorKind::PermissionDenied);
    assert_eq!(error.to_string(), "Permission denied");
    Ok(())
}

#[tokio::test]
async fn stable_handle_read_authorizes_resolved_symlink_target() -> io::Result<()> {
    use std::os::unix::fs::symlink;

    if !super::stable_handle_authorized_read_available() {
        return Ok(());
    }
    let temp_dir = tempfile::tempdir()?;
    let allowed_dir = temp_dir.path().join("allowed");
    let denied_dir = temp_dir.path().join("denied");
    std::fs::create_dir_all(&allowed_dir)?;
    std::fs::create_dir_all(&denied_dir)?;
    let allowed_file = allowed_dir.join("allowed.txt");
    let secret_file = denied_dir.join("secret.txt");
    std::fs::write(&allowed_file, b"allowed")?;
    std::fs::write(&secret_file, b"secret")?;
    let allowed_link = temp_dir.path().join("allowed-link");
    let denied_link = allowed_dir.join("denied-link");
    symlink(&allowed_file, &allowed_link)?;
    symlink(&secret_file, &denied_link)?;
    let file_system = LocalFileSystem::unsandboxed();
    let sandbox = read_sandbox(&allowed_dir)?;
    assert_eq!(
        authorized_read(&file_system, &allowed_link, &sandbox, 128).await?,
        b"allowed"
    );
    let error = authorized_read(&file_system, &denied_link, &sandbox, 128)
        .await
        .expect_err("symlink escaping the readable root must be denied");
    assert_eq!(error.kind(), io::ErrorKind::PermissionDenied);
    assert_eq!(error.to_string(), "Permission denied");
    Ok(())
}

#[tokio::test]
async fn stable_handle_read_applies_deny_glob_to_resolved_target() -> io::Result<()> {
    if !super::stable_handle_authorized_read_available() {
        return Ok(());
    }
    let temp_dir = tempfile::tempdir()?;
    let allowed_dir = temp_dir.path().join("allowed");
    std::fs::create_dir_all(&allowed_dir)?;
    let denied_file = allowed_dir.join("blocked.secret");
    std::fs::write(&denied_file, b"secret")?;
    let mut sandbox = read_sandbox(&allowed_dir)?;
    let native_permissions: PermissionProfile = sandbox.permissions.clone().try_into()?;
    let mut policy = native_permissions.file_system_sandbox_policy();
    policy.entries.push(FileSystemSandboxEntry::new(
        FileSystemPath::GlobPattern {
            pattern: format!("{}/*.secret", allowed_dir.display()),
        },
        FileSystemAccessMode::Deny,
    ));
    sandbox.permissions =
        PermissionProfile::from_runtime_permissions(&policy, NetworkSandboxPolicy::Restricted)
            .into();
    let error = authorized_read(&LocalFileSystem::unsandboxed(), &denied_file, &sandbox, 128)
        .await
        .expect_err("deny glob must override the readable root");
    assert_eq!(error.kind(), io::ErrorKind::PermissionDenied);
    assert_eq!(error.to_string(), "Permission denied");
    Ok(())
}

#[tokio::test]
async fn stable_handle_read_rejects_parent_symlink_replacement() -> io::Result<()> {
    use std::os::unix::fs::symlink;

    if !super::stable_handle_authorized_read_available() {
        return Ok(());
    }
    let temp_dir = tempfile::tempdir()?;
    let allowed = temp_dir.path().join("allowed");
    let outside = temp_dir.path().join("outside");
    let parent = allowed.join("parent");
    std::fs::create_dir_all(&parent)?;
    std::fs::create_dir_all(&outside)?;
    let path = parent.join("file.txt");
    std::fs::write(&path, b"allowed")?;

    let original = super::regular_file::open(&path).await?;
    let identity = super::unique_file_identity(&original).await?;
    let stable_path = super::stable_file_path(&original)?;
    std::fs::rename(&parent, outside.join("parent"))?;
    symlink(outside.join("parent"), &parent)?;

    let error = super::secure_reopen_matching_identity(stable_path.as_path(), identity)
        .await
        .expect_err("parent symlink replacement must fail closed");
    assert_eq!(error.kind(), io::ErrorKind::PermissionDenied);
    Ok(())
}

#[tokio::test]
async fn stable_handle_read_rejects_parent_directory_decoy() -> io::Result<()> {
    if !super::stable_handle_authorized_read_available() {
        return Ok(());
    }
    let temp_dir = tempfile::tempdir()?;
    let allowed_dir = temp_dir.path().join("allowed");
    let moved_dir = temp_dir.path().join("moved");
    let parent = allowed_dir.join("parent");
    std::fs::create_dir_all(&parent)?;
    let path = parent.join("file.txt");
    std::fs::write(&path, b"allowed")?;
    let original = super::regular_file::open(&path).await?;
    let identity = super::unique_file_identity(&original).await?;
    let stable_path = super::stable_file_path(&original)?;
    std::fs::create_dir_all(&moved_dir)?;
    std::fs::rename(&parent, moved_dir.join("parent"))?;
    std::fs::create_dir(&parent)?;
    std::fs::write(&path, b"secret")?;
    let error = super::secure_reopen_matching_identity(stable_path.as_path(), identity)
        .await
        .expect_err("same-name decoy must not replace the opened inode");
    assert_eq!(error.kind(), io::ErrorKind::PermissionDenied);
    Ok(())
}

#[tokio::test]
async fn stable_handle_read_rejects_file_path_identity_aba() -> io::Result<()> {
    // Qualification-only ABA check: once the authorized inode leaves the
    // pathname and a different inode takes its place, reopening by pathname
    // must fail closed. This is a path/identity binding check, not historical
    // provenance or production authority.
    if !super::stable_handle_authorized_read_available() {
        return Ok(());
    }
    let temp_dir = tempfile::tempdir()?;
    let path = temp_dir.path().join("skill.md");
    let moved = temp_dir.path().join("skill.moved.md");
    std::fs::write(&path, b"authorized")?;

    let original = super::regular_file::open(&path).await?;
    let identity = super::unique_file_identity(&original).await?;
    let stable_path = super::stable_file_path(&original)?;

    // A pathname ABA: remove the original name, then install a decoy at the
    // same name before the secure reopen. The stable inode identity must win.
    std::fs::rename(&path, &moved)?;
    std::fs::write(&path, b"decoy")?;
    let error = super::secure_reopen_matching_identity(stable_path.as_path(), identity)
        .await
        .expect_err("pathname ABA with a different inode must fail closed");
    assert_eq!(error.kind(), io::ErrorKind::PermissionDenied);
    assert_eq!(error.to_string(), "Permission denied");
    Ok(())
}

#[tokio::test]
async fn stable_handle_read_is_bound_to_opened_inode_after_path_replacement() -> io::Result<()> {
    if !super::stable_handle_authorized_read_available() {
        return Ok(());
    }
    let temp_dir = tempfile::tempdir()?;
    let path = temp_dir.path().join("file.txt");
    let moved = temp_dir.path().join("moved.txt");
    std::fs::write(&path, b"authorized")?;
    let original = super::regular_file::open(&path).await?;
    let identity = super::unique_file_identity(&original).await?;
    let stable_path = super::stable_file_path(&original)?;
    let mut reopened =
        super::secure_reopen_matching_identity(stable_path.as_path(), identity).await?;

    std::fs::rename(&path, &moved)?;
    std::fs::write(&path, b"replacement")?;
    let mut contents = Vec::new();
    reopened.read_to_end(&mut contents).await?;
    assert_eq!(contents, b"authorized");
    Ok(())
}

#[tokio::test]
async fn stable_handle_read_keeps_authorized_handle_after_later_hardlink() -> io::Result<()> {
    if !super::stable_handle_authorized_read_available() {
        return Ok(());
    }
    let temp_dir = tempfile::tempdir()?;
    let allowed_dir = temp_dir.path().join("allowed");
    let denied_dir = temp_dir.path().join("denied");
    std::fs::create_dir_all(&allowed_dir)?;
    std::fs::create_dir_all(&denied_dir)?;
    let path = allowed_dir.join("allowed.txt");
    let alias = denied_dir.join("alias.txt");
    std::fs::write(&path, b"allowed")?;
    let original = super::regular_file::open(&path).await?;
    let identity = super::unique_file_identity(&original).await?;
    let stable_path = super::stable_file_path(&original)?;
    super::authorize_stable_file_path(stable_path.as_path(), &read_sandbox(&allowed_dir)?)?;
    let mut authorized =
        super::secure_reopen_matching_identity(stable_path.as_path(), identity).await?;
    std::fs::hard_link(&path, &alias)?;
    let mut contents = Vec::new();
    authorized.read_to_end(&mut contents).await?;
    assert_eq!(contents, b"allowed");
    Ok(())
}

#[tokio::test]
async fn stable_handle_read_rejects_hardlink_added_before_reopen() -> io::Result<()> {
    if !super::stable_handle_authorized_read_available() {
        return Ok(());
    }
    let temp_dir = tempfile::tempdir()?;
    let path = temp_dir.path().join("allowed.txt");
    let alias = temp_dir.path().join("alias.txt");
    std::fs::write(&path, b"allowed")?;
    let original = super::regular_file::open(&path).await?;
    let identity = super::unique_file_identity(&original).await?;
    let stable_path = super::stable_file_path(&original)?;
    std::fs::hard_link(&path, &alias)?;
    let error = super::secure_reopen_matching_identity(stable_path.as_path(), identity)
        .await
        .expect_err("O_UNIQUE must reject a link added after initial authorization");
    assert_eq!(error.kind(), io::ErrorKind::PermissionDenied);
    Ok(())
}

#[tokio::test]
async fn stable_handle_read_redacts_missing_target_path() -> io::Result<()> {
    if !super::stable_handle_authorized_read_available() {
        return Ok(());
    }
    let temp_dir = tempfile::tempdir()?;
    let missing = temp_dir.path().join("SECRET-missing-target.txt");
    let error = authorized_read(
        &LocalFileSystem::unsandboxed(),
        &missing,
        &read_sandbox(temp_dir.path())?,
        128,
    )
    .await
    .expect_err("missing file must fail");
    assert_eq!(error.kind(), io::ErrorKind::NotFound);
    assert_eq!(error.to_string(), "No such file or directory");
    assert!(!error.to_string().contains("SECRET"));
    Ok(())
}

#[tokio::test]
async fn stable_handle_read_rejects_unlinked_initial_handle() -> io::Result<()> {
    if !super::stable_handle_authorized_read_available() {
        return Ok(());
    }
    let temp_dir = tempfile::tempdir()?;
    let path = temp_dir.path().join("unlinked.txt");
    std::fs::write(&path, b"allowed")?;
    let file = super::regular_file::open(&path).await?;
    std::fs::remove_file(&path)?;
    let error = super::unique_file_identity(&file)
        .await
        .expect_err("an unlinked handle must fail closed");
    assert_eq!(error.kind(), io::ErrorKind::PermissionDenied);
    Ok(())
}

#[tokio::test]
async fn stable_handle_bounded_read_never_returns_oversize_prefix() -> io::Result<()> {
    if !super::stable_handle_authorized_read_available() {
        return Ok(());
    }
    let temp_dir = tempfile::tempdir()?;
    let exact = temp_dir.path().join("exact.txt");
    let oversized = temp_dir.path().join("oversized.txt");
    std::fs::write(&exact, b"12345678")?;
    std::fs::write(&oversized, b"123456789")?;
    let sandbox = read_sandbox(temp_dir.path())?;
    let file_system = LocalFileSystem::unsandboxed();

    assert_eq!(
        authorized_read(&file_system, &exact, &sandbox, 8).await?,
        b"12345678"
    );
    let error = authorized_read(&file_system, &oversized, &sandbox, 8)
        .await
        .expect_err("oversized authorized read must fail without a prefix");
    assert_eq!(error.kind(), io::ErrorKind::InvalidData);
    assert_eq!(error.to_string(), "authorized file read exceeds bound");
    Ok(())
}
