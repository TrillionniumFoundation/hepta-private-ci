//! Owned Linux processes exercise the real normal Rust startup entry.
//!
//! Cargo must first build the declared test_arg0_preflight binary from this
//! exact source. Bazel supplies it through unit_test_extra_binaries. The shared
//! cargo-bin resolver handles the declared runfiles without a test-local fallback.

use std::fs;
use std::fs::File;
use std::os::unix::ffi::OsStringExt;
use std::path::PathBuf;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

use anyhow::Result;
use anyhow::ensure;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

const CHILD_MODE: &str = "ARG0_PREFLIGHT_TEST_CHILD_MODE";
const CHILD_ROOT: &str = "ARG0_PREFLIGHT_TEST_CHILD_ROOT";
const DOTENV_PROBE: &str = "ARG0_PREFLIGHT_TEST_DOTENV_PROBE";
const DOTENV_VALUE: &str = "loaded-after-preflight";
const CHILD_DEADLINE: Duration = Duration::from_secs(10);
const PATCH: &str =
    "*** Begin Patch\n*** Add File: helper-output.txt\n+actual helper wrote this\n*** End Patch\n";

#[derive(Clone, Copy)]
enum Mode {
    Refuse,
    Accept,
    Default,
    Helper,
}

struct OwnedChild(Option<Child>);

impl Drop for OwnedChild {
    fn drop(&mut self) {
        if let Some(child) = self.0.as_mut() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

struct ChildFixture {
    _temporary: TempDir,
    root: PathBuf,
}

impl ChildFixture {
    fn new() -> Result<Self> {
        let temporary = tempfile::tempdir()?;
        let root = temporary.path().canonicalize()?;
        fs::create_dir(root.join("home"))?;
        fs::create_dir(root.join("temporary"))?;
        fs::write(
            root.join("home/.env"),
            format!("{DOTENV_PROBE}={DOTENV_VALUE}\n"),
        )?;
        Ok(Self {
            _temporary: temporary,
            root,
        })
    }

    fn run(&self, mode: Mode) -> Result<()> {
        let mut command = Command::new(codex_utils_cargo_bin::cargo_bin("test_arg0_preflight")?);
        command
            .current_dir(&self.root)
            .env(CHILD_ROOT, &self.root)
            .env("CODEX_HOME", self.root.join("home"))
            // Keep the test's private home outside its separate temporary root,
            // including release builds that enforce the original alias guard.
            .env("TMPDIR", self.root.join("temporary"))
            .env_remove(DOTENV_PROBE)
            .stdout(Stdio::from(File::create(self.root.join("stdout"))?))
            .stderr(Stdio::from(File::create(self.root.join("stderr"))?));
        match mode {
            Mode::Refuse | Mode::Accept | Mode::Default => {
                let name = match mode {
                    Mode::Refuse => "refuse",
                    Mode::Accept => "accept",
                    Mode::Default => "default",
                    Mode::Helper => unreachable!("helper uses its actual arguments"),
                };
                command.env(CHILD_MODE, name);
            }
            Mode::Helper => {
                command
                    .env(CHILD_MODE, "helper")
                    .args([super::CODEX_CORE_APPLY_PATCH_ARG1, PATCH]);
            }
        }
        let mut child = OwnedChild(Some(command.spawn()?));
        let deadline = Instant::now() + CHILD_DEADLINE;
        loop {
            let process = child.0.as_mut().expect("owned child remains until reaped");
            if let Some(status) = process.try_wait()? {
                child.0.take();
                ensure!(
                    status.success(),
                    "owned child failed with {status}: {}",
                    fs::read_to_string(self.root.join("stderr"))?
                );
                return Ok(());
            }
            ensure!(Instant::now() < deadline, "owned startup child timed out");
            std::thread::sleep(Duration::from_millis(10));
        }
    }
}

#[test]
fn refused_preflight_has_no_alias_dotenv_or_runtime_side_effects() -> Result<()> {
    let fixture = ChildFixture::new()?;
    fixture.run(Mode::Refuse)?;
    assert_eq!(
        fs::read_to_string(fixture.root.join("child-entry"))?,
        "single-threaded Rust main\n"
    );
    assert_eq!(
        fs::read_to_string(fixture.root.join("events"))?,
        "preflight\nrefused\n"
    );
    assert!(!fixture.root.join("home/tmp/arg0").exists());
    assert!(!fixture.root.join("main-alias").exists());
    Ok(())
}

#[test]
fn preflight_precedes_aliases_and_runtime_and_default_entry_keeps_its_lifetime() -> Result<()> {
    for (mode, expected) in [
        (
            Mode::Accept,
            "preflight\nmain\nmain-after-yield\nreturned\n",
        ),
        (Mode::Default, "main\nmain-after-yield\nreturned\n"),
    ] {
        let fixture = ChildFixture::new()?;
        fixture.run(mode)?;
        assert_eq!(
            fs::read_to_string(fixture.root.join("child-entry"))?,
            "single-threaded Rust main\n"
        );
        assert_eq!(fs::read_to_string(fixture.root.join("events"))?, expected);
        let alias = PathBuf::from(std::ffi::OsString::from_vec(fs::read(
            fixture.root.join("main-alias"),
        )?));
        assert!(!alias.exists());
    }
    Ok(())
}

#[test]
fn actual_apply_patch_helper_precedes_preflight_without_normal_startup() -> Result<()> {
    let fixture = ChildFixture::new()?;
    fixture.run(Mode::Helper)?;
    assert_eq!(
        fs::read_to_string(fixture.root.join("child-entry"))?,
        "single-threaded Rust main\n"
    );
    assert_eq!(
        fs::read(fixture.root.join("helper-output.txt"))?,
        b"actual helper wrote this\n"
    );
    assert!(!fixture.root.join("events").exists());
    assert!(!fixture.root.join("home/tmp/arg0").exists());
    assert!(!fixture.root.join("main-alias").exists());
    Ok(())
}
