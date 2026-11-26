use std::io::Write;
use std::path::Path;
use std::sync::OnceLock;

use anyhow::Context;

pub(super) fn stage(test_exe: &Path) -> anyhow::Result<()> {
    static STAGED: OnceLock<Result<(), String>> = OnceLock::new();
    STAGED
        .get_or_init(|| stage_helpers(test_exe).map_err(|error| format!("{error:#}")))
        .as_ref()
        .map_err(|error| anyhow::anyhow!(error.clone()))?;
    Ok(())
}

fn stage_helpers(test_exe: &Path) -> anyhow::Result<()> {
    let resources = test_exe
        .parent()
        .context("Windows test executable has no parent directory")?;
    std::fs::create_dir_all(resources)
        .with_context(|| format!("create helper directory {}", resources.display()))?;
    for name in ["codex-windows-sandbox-setup", "codex-command-runner"] {
        let source = codex_utils_cargo_bin::cargo_bin(name)?;
        let destination = resources.join(Path::new(name).with_extension("exe"));
        let expected = std::fs::read(&source)
            .with_context(|| format!("read built helper {}", source.display()))?;
        // Parallel integration binaries and Bazel retries can share this
        // directory. Reuse only the exact current build, including when an
        // existing helper is still running and Windows disallows replacement.
        if std::fs::read(&destination).ok().as_deref() == Some(expected.as_slice()) {
            continue;
        }
        let mut staged = tempfile::NamedTempFile::new_in(resources)?;
        staged.write_all(&expected)?;
        staged.flush()?;
        anyhow::ensure!(
            std::fs::read(staged.path())? == expected,
            "helper staging changed bytes"
        );
        // Publish without replacing a path another test process may already
        // have validated or launched. The temporary file is complete first.
        if let Err(error) = staged.persist_noclobber(&destination)
            && std::fs::read(&destination).ok().as_deref() != Some(expected.as_slice())
        {
            return Err(error.error).with_context(|| {
                format!(
                    "publish helper {} at {}",
                    source.display(),
                    destination.display()
                )
            });
        }
        anyhow::ensure!(
            std::fs::read(&destination)? == expected,
            "staged helper differs from the current build: {}",
            destination.display()
        );
    }
    Ok(())
}
