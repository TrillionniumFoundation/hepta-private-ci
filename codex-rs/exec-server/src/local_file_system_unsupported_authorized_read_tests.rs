use super::ExecutorFileSystem;
use super::FileSystemSandboxContext;
use super::LocalFileSystem;
use codex_protocol::models::PermissionProfile;
use codex_protocol::permissions::FileSystemAccessMode;
use codex_protocol::permissions::FileSystemPath;
use codex_protocol::permissions::FileSystemSandboxEntry;
use codex_protocol::permissions::FileSystemSandboxPolicy;
use codex_protocol::permissions::NetworkSandboxPolicy;
use codex_utils_path_uri::PathUri;
use std::io;

#[tokio::test]
async fn unavailable_stable_handle_read_rejects_without_stream_fallback() -> anyhow::Result<()> {
    let temp = tempfile::tempdir()?;
    let allowed = temp.path().join("allowed");
    std::fs::create_dir(&allowed)?;
    let present = allowed.join("present.txt");
    std::fs::write(&present, b"must not be returned")?;
    let root = PathUri::from_host_native_path(&allowed)?;
    let policy = FileSystemSandboxPolicy::restricted(vec![FileSystemSandboxEntry::new(
        FileSystemPath::Path { path: root.clone() },
        FileSystemAccessMode::Read,
    )]);
    let permissions =
        PermissionProfile::from_runtime_permissions(&policy, NetworkSandboxPolicy::Restricted);
    let sandbox = FileSystemSandboxContext::from_permission_profile_with_cwd(permissions, root);
    let file_system = LocalFileSystem::unsandboxed();
    for path in [
        present,
        allowed.join("missing.txt"),
        temp.path().join("outside.txt"),
    ] {
        let uri = PathUri::from_host_native_path(&path)?;
        let error = file_system
            .read_file_bounded_authorized(&uri, &sandbox, /*max_bytes*/ 64)
            .await
            .expect_err("unavailable stable-handle capability must reject every read");
        assert_eq!(error.kind(), io::ErrorKind::Unsupported);
        assert_eq!(
            error.to_string(),
            "bounded authorized file reads are unsupported"
        );
    }
    Ok(())
}
