use std::fmt;
use std::sync::Arc;

#[cfg(windows)]
use anyhow::Context;
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

pub(crate) struct FileSystemContext {
    pub(crate) file_system: Arc<dyn ExecutorFileSystem>,
    _helper_paths: Option<TestCodexHelperPaths>,
    _server: Option<ExecServerHarness>,
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
    #[cfg(windows)]
    {
        static HELPERS: std::sync::OnceLock<std::result::Result<(), String>> =
            std::sync::OnceLock::new();
        let staged = HELPERS.get_or_init(|| {
            (|| -> Result<()> {
                let test_exe = std::env::current_exe()
                    .context("resolve Windows filesystem test executable")?;
                let helper_dir = test_exe
                    .parent()
                    .context("Windows filesystem test executable has no parent")?;
                for helper_name in ["codex-windows-sandbox-setup", "codex-command-runner"] {
                    let source = codex_utils_cargo_bin::cargo_bin(helper_name)?;
                    // The production lookup checks direct siblings before package resources.
                    // Stage the real declared runfile at that first lookup location.
                    let destination = helper_dir.join(format!("{helper_name}.exe"));
                    if !destination.try_exists()? {
                        let mut input = std::fs::File::open(&source)?;
                        let mut temporary = tempfile::NamedTempFile::new_in(helper_dir)?;
                        std::io::copy(&mut input, temporary.as_file_mut())?;
                        match temporary.persist_noclobber(&destination) {
                            Ok(_) => {}
                            Err(error)
                                if error.error.kind() == std::io::ErrorKind::AlreadyExists => {}
                            Err(error) => {
                                return Err(error.error).with_context(|| {
                                    format!(
                                        "stage Windows sandbox helper {}",
                                        destination.display()
                                    )
                                });
                            }
                        }
                    }
                    // Another process may already have staged or opened this executable.
                    // Reuse only the exact declared helper; never overwrite a live image or
                    // accept an arbitrary existing file as evidence of correct packaging.
                    anyhow::ensure!(
                        std::fs::symlink_metadata(&destination)?
                            .file_type()
                            .is_file(),
                        "staged Windows sandbox helper is not a regular file: {}",
                        destination.display()
                    );
                    anyhow::ensure!(
                        std::fs::read(&destination)? == std::fs::read(&source)?,
                        "staged Windows sandbox helper differs from declared runfile: {}",
                        destination.display()
                    );
                }
                Ok(())
            })()
            .map_err(|error| format!("{error:#}"))
        });
        if let Err(message) = staged {
            anyhow::bail!("{message}");
        }
    }

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

#[cfg(windows)]
pub(crate) fn is_unsupported_restricted_token_host<T>(result: &std::io::Result<T>) -> bool {
    result.as_ref().err().is_some_and(|err| {
        err.to_string()
            .contains("windows sandbox failed: CreateRestrictedToken failed: 87")
    })
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
    // Keep the runtime policy aligned with the legacy workspace-write projection used by the
    // unelevated restricted-token preflight.
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
    sandbox.windows_sandbox_level = WindowsSandboxLevel::RestrictedToken;
    sandbox
}

fn sandbox_context(mut entries: Vec<FileSystemSandboxEntry>) -> FileSystemSandboxContext {
    if cfg!(windows) {
        // Restricted-token sandboxing cannot enforce read restrictions, so leave the root
        // readable while exercising the requested write restrictions.
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
        sandbox.windows_sandbox_level = WindowsSandboxLevel::RestrictedToken;
    }
    sandbox
}
