//! Stage the real Windows helpers beside the test-dispatched executable.
//!
//! The production resolver looks beside current_exe (or in codex-resources),
//! while Bazel exposes binaries through runfiles and Cargo uses target/debug.
//! Keep that production lookup and all sandbox enforcement unchanged.

use std::ffi::OsStr;
use std::path::Path;
use std::path::PathBuf;

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use tempfile::TempDir;

const HELPERS: [&str; 2] = ["codex-command-runner", "codex-windows-sandbox-setup"];

fn helper_source(current_exe: &Path, name: &str) -> Result<PathBuf> {
    let variable = format!("CARGO_BIN_EXE_{name}");
    if let Some(path) = std::env::var_os(&variable) {
        let path = PathBuf::from(path);
        if !path.is_file() {
            bail!("declared {variable} helper is missing: {}", path.display());
        }
        return Ok(path);
    }

    let directory = current_exe
        .parent()
        .context("test executable has no parent")?;
    let file_name = format!("{name}.exe");
    let sibling = directory.join(&file_name);
    if sibling.is_file() {
        return Ok(sibling);
    }
    if directory.file_name() == Some(OsStr::new("deps"))
        && let Some(target) = directory.parent()
    {
        let binary = target.join(&file_name);
        if binary.is_file() {
            return Ok(binary);
        }
    }
    bail!(
        "missing real Windows helper {file_name}; build the windows-sandbox-rs binaries or provide {variable}"
    )
}

pub(super) fn stage(current_exe: &Path) -> Result<(PathBuf, Option<TempDir>)> {
    // Resolve every required executable before creating a partial fixture.
    let sources = HELPERS
        .iter()
        .map(|name| helper_source(current_exe, name))
        .collect::<Result<Vec<_>>>()?;
    let directory = TempDir::new().context("create Windows helper fixture")?;
    let executable = directory.path().join(
        current_exe
            .file_name()
            .context("test executable has no filename")?,
    );
    // A link avoids copying the large test executable; cross-volume fixtures
    // retain a normal byte copy as the fallback.
    if std::fs::hard_link(current_exe, &executable).is_err() {
        std::fs::copy(current_exe, &executable).context("stage test executable")?;
    }
    for (name, source) in HELPERS.iter().zip(sources) {
        std::fs::copy(source, directory.path().join(format!("{name}.exe")))
            .with_context(|| format!("stage real Windows helper {name}"))?;
    }
    Ok((executable, Some(directory)))
}
