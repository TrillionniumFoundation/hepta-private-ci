use codex_protocol::models::PermissionProfile;
use codex_protocol::permissions::FileSystemSandboxPolicy;
use codex_protocol::permissions::NetworkSandboxPolicy;
use codex_utils_path_uri::PathUri;
use pretty_assertions::assert_eq;
use std::io;

use super::ExecutorFileSystem;
use super::FileSystemSandboxContext;
use super::LocalFileSystem;

#[tokio::test]
async fn unsupported_authorized_reads_reject_present_and_missing_paths() -> io::Result<()> {
    assert!(!super::stable_handle_authorized_read_available());
    let temp = tempfile::tempdir()?;
    let present = temp.path().join("present.txt");
    std::fs::write(&present, b"file content")?;
    let missing = temp.path().join("missing.txt");
    let sandbox = FileSystemSandboxContext::from_permission_profile(
        PermissionProfile::from_runtime_permissions(
            &FileSystemSandboxPolicy::restricted(Vec::new()),
            NetworkSandboxPolicy::Restricted,
        ),
    );
    let file_system = LocalFileSystem::unsandboxed();

    for path in [present, missing] {
        let path = PathUri::from_host_native_path(&path)?;
        let error = ExecutorFileSystem::read_file_bounded_authorized(
            &file_system,
            &path,
            &sandbox,
            /*max_bytes*/ 16,
        )
        .await
        .expect_err("an unavailable stable-handle read must reject every path");
        assert_eq!(error.kind(), io::ErrorKind::Unsupported);
        assert_eq!(
            error.to_string(),
            "bounded authorized file reads are unsupported"
        );
    }
    Ok(())
}
