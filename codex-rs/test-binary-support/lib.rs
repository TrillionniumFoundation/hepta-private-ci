use std::path::Path;
use std::path::PathBuf;

use codex_arg0::Arg0DispatchPaths;
use codex_arg0::Arg0PathEntryGuard;
use tempfile::TempDir;

pub mod exec_server;

/// Return an executable whose normal entry point can run child helper modes.
///
/// musl does not initialize Rust's argument storage before test constructors.
pub fn test_binary_helper_exe() -> std::io::Result<PathBuf> {
    #[cfg(all(target_os = "linux", target_env = "musl"))]
    {
        match codex_utils_cargo_bin::cargo_bin("codex-test-helper") {
            Ok(path) => Ok(path),
            Err(codex_utils_cargo_bin::CargoBinError::NotFound { .. })
                if codex_utils_cargo_bin::runfiles_available() =>
            {
                // core_test_support declares this exact target as library data,
                // so its callers inherit the helper even without a test-level env.
                codex_utils_cargo_bin::resolve_bazel_runfile(
                    Some("codex-rs/test-binary-support"),
                    Path::new("codex-test-helper"),
                )
                .and_then(|path| path.canonicalize())
            }
            Err(error) => Err(std::io::Error::other(error)),
        }
    }
    #[cfg(not(all(target_os = "linux", target_env = "musl")))]
    {
        std::env::current_exe()
    }
}

/// Install test aliases before worker threads start.
pub fn arg0_dispatch_for_test_binary() -> Option<Arg0PathEntryGuard> {
    #[cfg(all(target_os = "linux", target_env = "musl"))]
    {
        let executable = match test_binary_helper_exe() {
            Ok(executable) => executable,
            Err(error) => panic!("failed to locate the standalone test helper: {error}"),
        };
        codex_arg0::arg0_dispatch_for_executable(&executable)
    }
    #[cfg(not(all(target_os = "linux", target_env = "musl")))]
    {
        codex_arg0::arg0_dispatch()
    }
}

pub struct TestBinaryDispatchGuard {
    _codex_home: TempDir,
    arg0: Arg0PathEntryGuard,
    _previous_codex_home: Option<std::ffi::OsString>,
}

impl TestBinaryDispatchGuard {
    pub fn paths(&self) -> &Arg0DispatchPaths {
        self.arg0.paths()
    }
}

pub enum TestBinaryDispatchMode {
    DispatchArg0Only,
    Skip,
    InstallAliases,
}

pub fn configure_test_binary_dispatch<F>(
    codex_home_prefix: &str,
    classify: F,
) -> Option<TestBinaryDispatchGuard>
where
    F: FnOnce(&str, Option<&str>) -> TestBinaryDispatchMode,
{
    configure_test_binary_dispatch_with(codex_home_prefix, classify, arg0_dispatch_for_test_binary)
}

fn configure_test_binary_dispatch_with<F, D>(
    codex_home_prefix: &str,
    classify: F,
    dispatch: D,
) -> Option<TestBinaryDispatchGuard>
where
    F: FnOnce(&str, Option<&str>) -> TestBinaryDispatchMode,
    D: FnOnce() -> Option<Arg0PathEntryGuard>,
{
    let mut args = std::env::args_os();
    let argv0 = args.next().unwrap_or_default();
    let exe_name = Path::new(&argv0)
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("");
    let argv1 = args.next();
    match classify(exe_name, argv1.as_deref().and_then(|arg| arg.to_str())) {
        TestBinaryDispatchMode::DispatchArg0Only => {
            let _ = dispatch();
            None
        }
        TestBinaryDispatchMode::Skip => None,
        TestBinaryDispatchMode::InstallAliases => {
            let codex_home = match tempfile::Builder::new().prefix(codex_home_prefix).tempdir() {
                Ok(codex_home) => codex_home,
                Err(error) => panic!("failed to create test CODEX_HOME: {error}"),
            };
            let previous_codex_home = std::env::var_os("CODEX_HOME");
            // Safety: this runs from a test ctor before test threads begin.
            unsafe {
                std::env::set_var("CODEX_HOME", codex_home.path());
            }

            let arg0 = match dispatch() {
                Some(arg0) => arg0,
                None => panic!("failed to configure arg0 dispatch aliases for test binary"),
            };
            match previous_codex_home.as_ref() {
                Some(value) => unsafe {
                    std::env::set_var("CODEX_HOME", value);
                },
                None => unsafe {
                    std::env::remove_var("CODEX_HOME");
                },
            }

            Some(TestBinaryDispatchGuard {
                _codex_home: codex_home,
                arg0,
                _previous_codex_home: previous_codex_home,
            })
        }
    }
}
