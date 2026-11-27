use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use anyhow::ensure;
use std::fs;
use std::io::ErrorKind;
use std::io::Write;
use std::sync::OnceLock;
use tempfile::NamedTempFile;

static HELPER_LAYOUT: OnceLock<Result<(), String>> = OnceLock::new();

/// Stages the real test helpers beside the current test executable, where the
/// production Windows resolver looks. This only prepares executable fixtures;
/// it does not run setup or modify sandbox users, policy, or ACLs.
pub fn stage_windows_sandbox_helpers() -> Result<()> {
    let result = HELPER_LAYOUT.get_or_init(|| {
        let stage = || -> Result<()> {
            let test_exe =
                std::env::current_exe().context("resolve current Windows test executable")?;
            let test_exe_dir = test_exe
                .parent()
                .context("Windows test executable should have a parent directory")?;
            let resources_dir = test_exe_dir.join("codex-resources");
            fs::create_dir_all(&resources_dir)
                .with_context(|| format!("create resources dir {}", resources_dir.display()))?;
            for helper_name in ["codex-windows-sandbox-setup", "codex-command-runner"] {
                let source = codex_utils_cargo_bin::cargo_bin(helper_name)?;
                let expected = fs::read(&source)
                    .with_context(|| format!("read actual helper {}", source.display()))?;
                let destination = resources_dir.join(format!("{helper_name}.exe"));
                match fs::read(&destination) {
                    Ok(actual) if actual == expected => continue,
                    Ok(_) => {}
                    Err(error) if error.kind() == ErrorKind::NotFound => {}
                    Err(error) => {
                        return Err(error)
                            .with_context(|| format!("inspect helper {}", destination.display()));
                    }
                }

                // Shards and retries can share the executable directory. Publish
                // complete bytes atomically and accept a competing writer only
                // when it installed this exact helper, including when a prior
                // child still has the destination executable open.
                let mut candidate = NamedTempFile::new_in(&resources_dir)?;
                candidate.write_all(&expected)?;
                match candidate.persist(&destination) {
                    Ok(file) => drop(file),
                    Err(error) => {
                        if !matches!(fs::read(&destination), Ok(actual) if actual == expected) {
                            return Err(error.error).with_context(|| {
                                format!("publish actual helper {}", destination.display())
                            });
                        }
                    }
                }
                ensure!(
                    fs::read(&destination)? == expected,
                    "staged helper differs from actual binary {}",
                    source.display()
                );
            }
            Ok(())
        };
        stage().map_err(|error| format!("{error:#}"))
    });
    match result {
        Ok(()) => Ok(()),
        Err(message) => bail!("{message}"),
    }
}
