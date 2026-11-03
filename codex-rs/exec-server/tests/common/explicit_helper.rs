use std::env;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use std::sync::OnceLock;

use anyhow::Context as _;
use anyhow::ensure;
use codex_sandboxing::landlock::CODEX_LINUX_SANDBOX_ARG0;
use tempfile::TempDir;

const HELPER_NAME: &str = "codex-exec-server-test-helper";
const HELPER_ENV_KEYS: [&str; 4] = [
    "CARGO_BIN_EXE_codex-exec-server-test-helper",
    "CARGO_BIN_EXE_codex_exec_server_test_helper",
    "NEXTEST_BIN_EXE_codex-exec-server-test-helper",
    "NEXTEST_BIN_EXE_codex_exec_server_test_helper",
];

struct HelperPaths {
    executable: PathBuf,
    sandbox_alias: PathBuf,
    _alias_dir: TempDir,
}

// The direct filesystem and relay fixtures also need the sandbox alias to
// remain live after this function returns. No process environment is modified.
static HELPER_PATHS: OnceLock<Result<HelperPaths, String>> = OnceLock::new();

pub(super) fn paths() -> anyhow::Result<(PathBuf, Option<PathBuf>)> {
    match HELPER_PATHS.get_or_init(|| create_paths().map_err(|error| format!("{error:#}"))) {
        Ok(paths) => Ok((paths.executable.clone(), Some(paths.sandbox_alias.clone()))),
        Err(error) => {
            anyhow::bail!("failed to configure explicit exec-server test helper: {error}")
        }
    }
}

fn create_paths() -> anyhow::Result<HelperPaths> {
    let executable = resolve_executable()?.canonicalize()?;
    let metadata = executable.metadata()?;
    ensure!(
        metadata.is_file() && metadata.permissions().mode() & 0o111 != 0,
        "exec-server test helper is not an executable regular file: {}",
        executable.display()
    );
    let alias_dir = tempfile::Builder::new()
        .prefix("codex-exec-server-test-helper")
        .tempdir()?;
    let sandbox_alias = alias_dir.path().join(CODEX_LINUX_SANDBOX_ARG0);
    std::os::unix::fs::symlink(&executable, &sandbox_alias)?;
    Ok(HelperPaths {
        executable,
        sandbox_alias,
        _alias_dir: alias_dir,
    })
}

fn resolve_executable() -> anyhow::Result<PathBuf> {
    if option_env!("BAZEL_PACKAGE").is_some() {
        ensure!(
            env::var_os(HELPER_ENV_KEYS[0]).is_some(),
            "Bazel did not declare the exec-server test helper runfile"
        );
        return Ok(codex_utils_cargo_bin::cargo_bin(HELPER_NAME)?);
    }

    // Respect explicit Cargo/nextest paths with cargo_bin's existing precedence
    // and fail-closed resolution; an invalid explicit path must not fall back.
    if HELPER_ENV_KEYS.iter().any(|key| env::var_os(key).is_some()) {
        return Ok(codex_utils_cargo_bin::cargo_bin(HELPER_NAME)?);
    }

    // Cargo examples use dev-dependencies without adding an installable product
    // bin. An exact --test selection needs the explicit example built first.
    let current_exe = env::current_exe()?;
    let deps_dir = current_exe
        .parent()
        .context("test executable has no parent")?;
    ensure!(
        deps_dir.file_name() == Some(std::ffi::OsStr::new("deps")),
        "test executable is outside Cargo's deps directory; provide an explicit helper path"
    );
    let profile_dir = deps_dir
        .parent()
        .context("Cargo deps directory has no parent")?;
    let executable = profile_dir.join("examples").join(HELPER_NAME);
    ensure!(
        executable.is_file(),
        "missing exec-server test helper at {}; first build cargo build -p codex-exec-server --example codex-exec-server-test-helper with the same target and profile",
        executable.display()
    );
    Ok(executable)
}
