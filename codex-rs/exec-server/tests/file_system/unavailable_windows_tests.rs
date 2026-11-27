use std::io::ErrorKind;

use anyhow::Result;
use codex_exec_server::ReadFileOptions;
use codex_exec_server::WriteFileOptions;
use codex_protocol::config_types::WindowsSandboxLevel;
use codex_utils_path_uri::PathUri;
use pretty_assertions::assert_eq;
use test_case::test_case;

use crate::support::FileSystemImplementation;
use crate::support::create_file_system_context;
use crate::support::workspace_write_sandbox;

#[test_case(FileSystemImplementation::Local, WindowsSandboxLevel::RestrictedToken, ErrorKind::Unsupported; "local_restricted")]
#[test_case(FileSystemImplementation::Remote, WindowsSandboxLevel::RestrictedToken, ErrorKind::Unsupported; "remote_restricted")]
#[test_case(FileSystemImplementation::Local, WindowsSandboxLevel::Elevated, ErrorKind::Unsupported; "local_elevated")]
#[test_case(FileSystemImplementation::Remote, WindowsSandboxLevel::Elevated, ErrorKind::Unsupported; "remote_elevated")]
#[test_case(FileSystemImplementation::Local, WindowsSandboxLevel::Disabled, ErrorKind::InvalidInput; "local_disabled")]
#[test_case(FileSystemImplementation::Remote, WindowsSandboxLevel::Disabled, ErrorKind::InvalidInput; "remote_disabled")]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn unenforceable_sandbox_preserves_type_and_never_changes_file(
    implementation: FileSystemImplementation,
    level: WindowsSandboxLevel,
    expected_kind: ErrorKind,
) -> Result<()> {
    let context = create_file_system_context(implementation).await?;
    let directory = tempfile::TempDir::new()?;
    let path = directory.path().join("unchanged.txt");
    std::fs::write(&path, "before")?;
    let uri = PathUri::from_host_native_path(&path)?;
    let mut sandbox = workspace_write_sandbox(directory.path().to_path_buf());
    sandbox.windows_sandbox_level = level;

    let read_error = context
        .file_system
        .read_file(&uri, ReadFileOptions::default(), Some(&sandbox))
        .await
        .expect_err("unenforceable sandbox must reject reads");
    let write_error = context
        .file_system
        .write_file(
            &uri,
            b"must not write".to_vec(),
            WriteFileOptions::default(),
            Some(&sandbox),
        )
        .await
        .expect_err("unenforceable sandbox must reject writes");
    assert_eq!(
        (
            read_error.kind(),
            write_error.kind(),
            std::fs::read_to_string(&path)?
        ),
        (expected_kind, expected_kind, "before".to_string()),
    );

    context
        .file_system
        .write_file(
            &uri,
            b"explicit unsandboxed".to_vec(),
            WriteFileOptions::default(),
            /*sandbox*/ None,
        )
        .await?;
    let bytes = context
        .file_system
        .read_file(&uri, ReadFileOptions::default(), /*sandbox*/ None)
        .await?;
    assert_eq!(bytes, b"explicit unsandboxed");
    Ok(())
}
