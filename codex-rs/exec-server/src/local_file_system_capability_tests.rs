use super::ExecutorFileSystem;
use super::FileSystemSandboxContext;
use super::LocalFileSystem;
use codex_protocol::protocol::SandboxPolicy;
use codex_utils_path_uri::PathUri;
use pretty_assertions::assert_eq;
use std::io;

#[tokio::test]
async fn unavailable_stable_handle_reads_never_fall_back_to_an_unrestricted_stream()
-> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let existing = temporary.path().join("private.txt");
    std::fs::write(&existing, b"private bytes")?;
    let sandbox = FileSystemSandboxContext::from_legacy_sandbox_policy(
        SandboxPolicy::DangerFullAccess,
        PathUri::from_host_native_path(temporary.path())?,
    )
    .expect("valid unrestricted fixture policy");
    let file_system = LocalFileSystem::unsandboxed();
    for path in [existing, temporary.path().join("missing.txt")] {
        let error = file_system
            .read_file_bounded_authorized(
                &PathUri::from_host_native_path(path)?,
                &sandbox,
                /*max_bytes*/ 128,
            )
            .await
            .expect_err("unavailable capability must reject before opening a stream");
        assert_eq!(error.kind(), io::ErrorKind::Unsupported);
        assert_eq!(
            error.to_string(),
            "bounded authorized file reads are unsupported"
        );
    }
    Ok(())
}
