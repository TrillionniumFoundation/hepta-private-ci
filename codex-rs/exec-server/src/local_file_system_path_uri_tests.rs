use codex_utils_path_uri::PathUri;
use pretty_assertions::assert_eq;
use tokio::io;

use super::*;

#[tokio::test]
async fn direct_file_system_rejects_non_native_uri_as_invalid_input() {
    let error = DirectFileSystem
        .read_file(&non_native_uri(), Default::default(), /*sandbox*/ None)
        .await
        .expect_err("non-native URI should be rejected");

    assert_eq!(error.kind(), io::ErrorKind::InvalidInput);
}

fn non_native_uri() -> PathUri {
    #[cfg(unix)]
    let uri = "file://server/share/file.txt";
    #[cfg(windows)]
    let uri = "file:///usr/local/file.txt";

    match PathUri::parse(uri) {
        Ok(uri) => uri,
        Err(err) => panic!("valid non-native URI should parse: {err}"),
    }
}

#[cfg(not(target_os = "macos"))]
#[tokio::test]
async fn unavailable_authorized_read_never_falls_back_to_a_generic_stream() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let readable = temporary.path().join("readable.txt");
    std::fs::write(&readable, b"private")?;
    let sandbox = FileSystemSandboxContext::from_legacy_sandbox_policy(
        codex_protocol::protocol::SandboxPolicy::DangerFullAccess,
        PathUri::from_host_native_path(temporary.path())?,
    )
    .expect("valid test context");
    let file_system = LocalFileSystem::unsandboxed();
    for path in [readable, temporary.path().join("missing.txt")] {
        let error = ExecutorFileSystem::read_file_bounded_authorized(
            &file_system,
            &PathUri::from_host_native_path(path)?,
            &sandbox,
            /*max_bytes*/ 64,
        )
        .await
        .expect_err("an unavailable capability must reject before reading any path");
        assert_eq!(
            (error.kind(), error.to_string()),
            (
                io::ErrorKind::Unsupported,
                "bounded authorized file reads are unsupported".to_string(),
            ),
        );
    }
    Ok(())
}
