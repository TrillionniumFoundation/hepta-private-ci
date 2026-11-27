use std::fmt;
use std::sync::Arc;

use anyhow::Result;
use codex_exec_server::Environment;
use codex_exec_server::ExecServerRuntimePaths;
use codex_exec_server::ExecutorFileSystem;
use codex_exec_server::FileSystemSandboxContext;
use codex_exec_server::LocalFileSystem;
use codex_protocol::config_types::WindowsSandboxLevel;
use codex_protocol::models::PermissionProfile;
use codex_protocol::permissions::FileSystemAccessMode;
use codex_protocol::permissions::FileSystemPath;
use codex_protocol::permissions::FileSystemSandboxEntry;
use codex_protocol::permissions::FileSystemSandboxPolicy;
use codex_protocol::permissions::FileSystemSpecialPath;
use codex_protocol::permissions::NetworkSandboxPolicy;
use codex_utils_absolute_path::AbsolutePathBuf;
#[cfg(windows)]
use codex_utils_path_uri::PathUri;

use crate::common::exec_server::ExecServerHarness;
use crate::common::exec_server::TestCodexHelperPaths;
use crate::common::exec_server::exec_server;
use crate::common::exec_server::test_codex_helper_paths;
#[cfg(windows)]
use crate::windows_elevated_fixture::AuthorizedReadOnlySandboxFixture;

pub(crate) struct FileSystemContext {
    pub(crate) file_system: Arc<dyn ExecutorFileSystem>,
    _helper_paths: Option<TestCodexHelperPaths>,
    _server: Option<ExecServerHarness>,
}

impl FileSystemContext {
    pub(crate) async fn close(mut self) -> Result<()> {
        drop(self.file_system);
        if let Some(server) = self._server.as_mut() {
            server.shutdown().await?;
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug)]
pub(crate) enum FileSystemImplementation {
    Local,
    Remote,
}

impl fmt::Display for FileSystemImplementation {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Local => formatter.write_str("local"),
            Self::Remote => formatter.write_str("remote"),
        }
    }
}

pub(crate) async fn create_file_system_context(
    implementation: FileSystemImplementation,
) -> Result<FileSystemContext> {
    match implementation {
        FileSystemImplementation::Local => {
            let helper_paths = test_codex_helper_paths()?;
            let runtime_paths = ExecServerRuntimePaths::new(
                helper_paths.codex_exe.clone(),
                helper_paths.codex_linux_sandbox_exe.clone(),
            )?;
            Ok(FileSystemContext {
                file_system: Arc::new(LocalFileSystem::with_runtime_paths(runtime_paths)),
                _helper_paths: Some(helper_paths),
                _server: None,
            })
        }
        FileSystemImplementation::Remote => {
            let server = exec_server().await?;
            let environment =
                Environment::create_for_tests(Some(server.websocket_url().to_string()))?;
            Ok(FileSystemContext {
                file_system: environment.get_filesystem(),
                _helper_paths: None,
                _server: Some(server),
            })
        }
    }
}

pub(crate) enum SandboxFixture {
    Ordinary(tempfile::TempDir),
    #[cfg(windows)]
    Elevated(AuthorizedReadOnlySandboxFixture),
}

impl SandboxFixture {
    pub(crate) fn ordinary() -> Result<Self> {
        Ok(Self::Ordinary(tempfile::TempDir::new()?))
    }

    pub(crate) fn sandboxed() -> Result<Self> {
        #[cfg(windows)]
        {
            Ok(Self::Elevated(AuthorizedReadOnlySandboxFixture::new(
                *uuid::Uuid::new_v4().as_bytes(),
            )?))
        }
        #[cfg(not(windows))]
        {
            Self::ordinary()
        }
    }

    pub(crate) fn path(&self) -> &std::path::Path {
        match self {
            Self::Ordinary(fixture) => fixture.path(),
            #[cfg(windows)]
            Self::Elevated(fixture) => fixture.path(),
        }
    }

    pub(crate) fn close(self) -> Result<()> {
        match self {
            Self::Ordinary(fixture) => fixture.close()?,
            #[cfg(windows)]
            Self::Elevated(fixture) => fixture.close()?,
        }
        Ok(())
    }
}

pub(crate) fn absolute_path(path: std::path::PathBuf) -> AbsolutePathBuf {
    assert!(
        path.is_absolute(),
        "path must be absolute: {}",
        path.display()
    );
    AbsolutePathBuf::try_from(path).expect("path should be absolute")
}

pub(crate) fn read_only_sandbox(readable_root: std::path::PathBuf) -> FileSystemSandboxContext {
    let readable_root = absolute_path(readable_root);
    sandbox_context(vec![FileSystemSandboxEntry {
        path: FileSystemPath::Path {
            path: readable_root.into(),
        },
        access: FileSystemAccessMode::Read,
        missing_path_behavior: None,
    }])
}

#[cfg(not(windows))]
pub(crate) fn workspace_write_sandbox(
    writable_root: std::path::PathBuf,
) -> FileSystemSandboxContext {
    let writable_root = absolute_path(writable_root);
    sandbox_context(vec![FileSystemSandboxEntry {
        path: FileSystemPath::Path {
            path: writable_root.into(),
        },
        access: FileSystemAccessMode::Write,
        missing_path_behavior: None,
    }])
}

#[cfg(windows)]
pub(crate) fn workspace_write_sandbox(
    writable_root: std::path::PathBuf,
) -> FileSystemSandboxContext {
    let writable_root = absolute_path(writable_root);
    // Preserve the existing root-read and workspace-write permission scope.
    let policy = FileSystemSandboxPolicy::restricted(vec![
        FileSystemSandboxEntry::new(
            FileSystemPath::Special {
                value: FileSystemSpecialPath::Root,
            },
            FileSystemAccessMode::Read,
        ),
        FileSystemSandboxEntry::new(
            FileSystemPath::Special {
                value: FileSystemSpecialPath::project_roots(/*subpath*/ None),
            },
            FileSystemAccessMode::Write,
        ),
    ]);
    let mut sandbox = FileSystemSandboxContext::from_permission_profile_with_cwd(
        PermissionProfile::from_runtime_permissions(&policy, NetworkSandboxPolicy::Restricted),
        PathUri::from_abs_path(&writable_root),
    );
    sandbox.windows_sandbox_level = WindowsSandboxLevel::Elevated;
    sandbox
}

fn sandbox_context(mut entries: Vec<FileSystemSandboxEntry>) -> FileSystemSandboxContext {
    if cfg!(windows) {
        // Preserve this fixture's existing root-read permission scope.
        entries.push(FileSystemSandboxEntry::new(
            FileSystemPath::Special {
                value: FileSystemSpecialPath::Root,
            },
            FileSystemAccessMode::Read,
        ));
    }
    let mut sandbox = FileSystemSandboxContext::from_permission_profile(
        PermissionProfile::from_runtime_permissions(
            &FileSystemSandboxPolicy::restricted(entries),
            NetworkSandboxPolicy::Restricted,
        ),
    );
    if cfg!(windows) {
        sandbox.windows_sandbox_level = WindowsSandboxLevel::Elevated;
    }
    sandbox
}
