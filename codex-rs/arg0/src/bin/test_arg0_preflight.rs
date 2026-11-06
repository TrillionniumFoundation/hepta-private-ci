//! Normal-main fixture for the Linux arg0 preflight process controls.
//! Built explicitly for Cargo tests and declared as a Bazel test dependency.
//! It does not activate Agentd, convert credentials, or grant authority.

#[cfg(target_os = "linux")]
fn main() -> anyhow::Result<()> {
    linux::run()
}

#[cfg(not(target_os = "linux"))]
fn main() -> anyhow::Result<()> {
    anyhow::bail!("the arg0 preflight process fixture requires Linux")
}

#[cfg(target_os = "linux")]
mod linux {
    use std::fmt;
    use std::fs;
    use std::fs::File;
    use std::io::Write;
    use std::os::unix::ffi::OsStrExt;
    use std::os::unix::ffi::OsStringExt;
    use std::path::Path;
    use std::path::PathBuf;

    use anyhow::Result;
    use anyhow::bail;
    use anyhow::ensure;
    use codex_arg0::Arg0DispatchPaths;
    use codex_arg0::arg0_dispatch_or_else;
    use codex_arg0::arg0_dispatch_or_else_with_preflight;

    const CHILD_MODE: &str = "ARG0_PREFLIGHT_TEST_CHILD_MODE";
    const CHILD_ROOT: &str = "ARG0_PREFLIGHT_TEST_CHILD_ROOT";
    const DOTENV_PROBE: &str = "ARG0_PREFLIGHT_TEST_DOTENV_PROBE";
    const DOTENV_VALUE: &str = "loaded-after-preflight";

    #[derive(Clone, Copy)]
    enum Mode {
        Refuse,
        Accept,
        Default,
        Helper,
    }

    #[derive(Debug)]
    struct RefusedPreflight;

    impl fmt::Display for RefusedPreflight {
        fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
            formatter.write_str("owned preflight refusal")
        }
    }

    impl std::error::Error for RefusedPreflight {}

    pub(super) fn run() -> Result<()> {
        let mode = std::env::var_os(CHILD_MODE)
            .ok_or_else(|| anyhow::anyhow!("owned child mode absent"))?;
        let mode = match mode.to_str() {
            Some("refuse") => Mode::Refuse,
            Some("accept") => Mode::Accept,
            Some("default") => Mode::Default,
            Some("helper") => Mode::Helper,
            _ => bail!("unknown owned child mode"),
        };
        let root = PathBuf::from(
            std::env::var_os(CHILD_ROOT).ok_or_else(|| anyhow::anyhow!("child root absent"))?,
        );
        ensure!(root.is_absolute() && root.canonicalize()? == root);
        ensure!(std::env::current_dir()? == root);
        ensure!(
            std::env::args_os().next().is_some(),
            "normal main argv absent"
        );
        ensure_single_threaded()?;
        ensure!(tokio::runtime::Handle::try_current().is_err());
        ensure!(std::env::var_os(DOTENV_PROBE).is_none());
        let alias_root = root.join("home/tmp/arg0");
        ensure!(!alias_root.exists());
        fs::write(root.join("child-entry"), b"single-threaded Rust main\n")?;

        let path_before = std::env::var_os("PATH");
        let caller = std::thread::current().id();
        let main_root = root.clone();
        let main = move |paths| observe_main(paths, main_root, caller);
        let result = match mode {
            Mode::Default => arg0_dispatch_or_else(main),
            Mode::Refuse | Mode::Accept | Mode::Helper => {
                arg0_dispatch_or_else_with_preflight(|| {
                    ensure_single_threaded()?;
                    ensure!(std::thread::current().id() == caller);
                    ensure!(tokio::runtime::Handle::try_current().is_err());
                    ensure!(std::env::var_os(DOTENV_PROBE).is_none());
                    ensure!(!alias_root.exists());
                    record(&root, "preflight")?;
                    match mode {
                        Mode::Refuse | Mode::Helper => Err(RefusedPreflight.into()),
                        Mode::Accept => Ok(main),
                        Mode::Default => unreachable!("default entry does not use this callback"),
                    }
                })
            }
        };

        match mode {
            Mode::Refuse => {
                let Err(error) = result else {
                    bail!("refused preflight must return its original error");
                };
                ensure!(error.downcast_ref::<RefusedPreflight>().is_some());
                ensure!(error.to_string() == "owned preflight refusal");
                ensure!(std::env::var_os("PATH") == path_before);
                ensure!(std::env::var_os(DOTENV_PROBE).is_none());
                ensure!(!alias_root.exists());
                ensure!(!root.join("main-alias").exists());
                ensure!(tokio::runtime::Handle::try_current().is_err());
                ensure_single_threaded()?;
                record(&root, "refused")?;
            }
            Mode::Accept | Mode::Default => {
                result?;
                let alias = PathBuf::from(std::ffi::OsString::from_vec(fs::read(
                    root.join("main-alias"),
                )?));
                ensure!(!alias.exists(), "alias guard survived the returned main");
                record(&root, "returned")?;
            }
            Mode::Helper => bail!("the real apply-patch helper returned to normal startup"),
        }
        Ok(())
    }

    fn ensure_single_threaded() -> Result<()> {
        let tasks = fs::read_dir("/proc/self/task")?.collect::<std::io::Result<Vec<_>>>()?;
        ensure!(
            tasks.len() == 1,
            "startup child already had multiple threads"
        );
        Ok(())
    }

    fn record(root: &Path, event: &str) -> Result<()> {
        let mut file = File::options()
            .create(true)
            .append(true)
            .open(root.join("events"))?;
        writeln!(file, "{event}")?;
        Ok(())
    }

    async fn observe_main(
        paths: Arg0DispatchPaths,
        root: PathBuf,
        caller: std::thread::ThreadId,
    ) -> Result<()> {
        ensure!(std::thread::current().id() != caller);
        ensure!(std::thread::current().name() == Some("codex-main"));
        ensure!(tokio::runtime::Handle::try_current().is_ok());
        ensure!(std::env::var(DOTENV_PROBE)? == DOTENV_VALUE);
        let executable = std::env::current_exe()?;
        ensure!(paths.codex_self_exe.as_ref() == Some(&executable));
        let alias = paths
            .codex_linux_sandbox_exe
            .ok_or_else(|| anyhow::anyhow!("original Linux sandbox alias absent"))?;
        let directory = alias
            .parent()
            .ok_or_else(|| anyhow::anyhow!("alias parent absent"))?;
        ensure!(directory.parent() == Some(root.join("home/tmp/arg0").as_path()));
        ensure!(paths.main_execve_wrapper_exe == Some(directory.join("codex-execve-wrapper")));
        ensure!(
            std::env::split_paths(&std::env::var_os("PATH").unwrap_or_default()).next()
                == Some(directory.to_path_buf())
        );
        for name in [
            "apply_patch",
            "applypatch",
            "codex-linux-sandbox",
            "codex-execve-wrapper",
        ] {
            ensure!(fs::read_link(directory.join(name))? == executable);
        }
        ensure!(directory.join(".lock").is_file());
        fs::write(root.join("main-alias"), alias.as_os_str().as_bytes())?;
        record(&root, "main")?;
        tokio::task::yield_now().await;
        ensure!(
            alias.exists(),
            "alias guard disappeared while main was pending"
        );
        record(&root, "main-after-yield")?;
        Ok(())
    }
}
