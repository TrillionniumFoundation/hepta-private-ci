use std::fs;
use std::path::PathBuf;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::thread;
use std::time::Duration;
use std::time::Instant;

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use clap::Parser;
use codex_hepta_native_gateway::update_activation::NativeActivationStatus;
use codex_hepta_native_gateway::update_activation::NativeUpdateActivationConfig;
use codex_hepta_native_gateway::update_activation::activate_staged_update;
use codex_hepta_native_gateway::update_activation::rollback_unconfirmed_update;

const PARENT_EXIT_TIMEOUT: Duration = Duration::from_secs(60);
const CONFIRM_TIMEOUT: Duration = Duration::from_secs(30);
const POLL_INTERVAL: Duration = Duration::from_millis(100);

#[derive(Clone, Debug, Parser)]
#[command(
    name = "hepta-native-updater",
    about = "Post-exit activator for a verified Hepta native update"
)]
struct Args {
    #[arg(long)]
    parent_pid: u32,
    #[arg(long)]
    active_artifact: PathBuf,
    #[arg(long)]
    rollback_artifact: PathBuf,
    #[arg(long)]
    stage_artifact: PathBuf,
    #[arg(long)]
    update_journal: PathBuf,
    #[arg(long)]
    predecessor_digest: String,
    #[arg(long)]
    expected_package_digest: String,
    #[arg(long)]
    confirm_file: PathBuf,
    #[arg(long)]
    manifest_digest: String,
    #[arg(long)]
    grant_public_key: PathBuf,
    #[arg(long)]
    release_public_key: PathBuf,
    #[arg(long)]
    selection_public_key: PathBuf,
    #[arg(long)]
    effect_journal: PathBuf,
    #[arg(long)]
    windows_dpapi_session_path: PathBuf,
    #[arg(long)]
    allow_open_path: bool,
    #[arg(long)]
    allow_reveal_path: bool,
    #[arg(long)]
    allow_copy_text: bool,
    #[arg(long)]
    allow_notify: bool,
    #[arg(long)]
    no_session_persistence: bool,
}

fn main() -> Result<()> {
    let args = Args::parse();
    validate(&args)?;
    wait_for_parent_exit(args.parent_pid, PARENT_EXIT_TIMEOUT)?;

    if args.confirm_file.exists() {
        fs::remove_file(&args.confirm_file).context("remove stale native update confirmation")?;
    }
    let activation = activation_config(&args);
    match activate_staged_update(&activation)? {
        NativeActivationStatus::RestartRequired => {}
        status => bail!("staged native update activation returned unexpected status {status:?}"),
    }

    let mut child = spawn_application(&args, true)?;
    if wait_for_confirmation(&mut child, &args.confirm_file, &args.expected_package_digest)? {
        let _ = fs::remove_file(&args.confirm_file);
        return Ok(());
    }

    stop_child(&mut child);
    let rollback = rollback_unconfirmed_update(&activation, &args.predecessor_digest)
        .context("rollback unconfirmed native update")?;
    if rollback != NativeActivationStatus::RolledBack {
        bail!("native updater expected rollback, observed {rollback:?}");
    }
    let _ = fs::remove_file(&args.confirm_file);
    let _predecessor = spawn_application(&args, false)
        .context("restart predecessor after native update rollback")?;
    bail!("new native application did not confirm startup; predecessor restored")
}

fn activation_config(args: &Args) -> NativeUpdateActivationConfig {
    NativeUpdateActivationConfig {
        active_artifact: args.active_artifact.clone(),
        rollback_artifact: args.rollback_artifact.clone(),
        stage_artifact: args.stage_artifact.clone(),
        update_journal: args.update_journal.clone(),
    }
}

fn spawn_application(args: &Args, confirm_update: bool) -> Result<Child> {
    let mut command = Command::new(&args.active_artifact);
    command
        .arg("--manifest-digest")
        .arg(&args.manifest_digest)
        .arg("--grant-public-key")
        .arg(&args.grant_public_key)
        .arg("--release-public-key")
        .arg(&args.release_public_key)
        .arg("--selection-public-key")
        .arg(&args.selection_public_key)
        .arg("--effect-journal")
        .arg(&args.effect_journal)
        .arg("--update-journal")
        .arg(&args.update_journal)
        .arg("--rollback-artifact")
        .arg(&args.rollback_artifact)
        .arg("--stage-artifact")
        .arg(&args.stage_artifact)
        .arg("--windows-dpapi-session-path")
        .arg(&args.windows_dpapi_session_path)
        .stdin(Stdio::null());
    if args.allow_open_path {
        command.arg("--allow-open-path");
    }
    if args.allow_reveal_path {
        command.arg("--allow-reveal-path");
    }
    if args.allow_copy_text {
        command.arg("--allow-copy-text");
    }
    if args.allow_notify {
        command.arg("--allow-notify");
    }
    if args.no_session_persistence {
        command.arg("--no-session-persistence");
    }
    if confirm_update {
        command
            .arg("--update-confirm-file")
            .arg(&args.confirm_file)
            .arg("--update-expected-digest")
            .arg(&args.expected_package_digest);
    }
    command.spawn().context("launch Hepta native application")
}

fn wait_for_confirmation(child: &mut Child, path: &PathBuf, expected: &str) -> Result<bool> {
    let deadline = Instant::now() + CONFIRM_TIMEOUT;
    while Instant::now() < deadline {
        if path.exists() {
            let observed = fs::read_to_string(path).context("read native update confirmation")?;
            return Ok(observed.trim() == expected);
        }
        if child.try_wait()?.is_some() {
            return Ok(false);
        }
        thread::sleep(POLL_INTERVAL);
    }
    Ok(false)
}

fn stop_child(child: &mut Child) {
    if child.try_wait().ok().flatten().is_none() {
        let _ = child.kill();
        let _ = child.wait();
    }
}

fn wait_for_parent_exit(pid: u32, timeout: Duration) -> Result<()> {
    #[cfg(windows)]
    {
        const SCRIPT: &str = r#"
$ErrorActionPreference='Stop'
try { Wait-Process -Id ([int]$args[0]) -Timeout 60 -ErrorAction Stop } catch {
  if (Get-Process -Id ([int]$args[0]) -ErrorAction SilentlyContinue) { exit 3 }
}
"#;
        let status = Command::new("powershell.exe")
            .args([
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                SCRIPT,
                "--",
                &pid.to_string(),
            ])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .context("wait for native parent process on Windows")?;
        if !status.success() {
            bail!("native parent process did not exit before activation timeout");
        }
        return Ok(());
    }

    #[cfg(not(windows))]
    {
        let deadline = Instant::now() + timeout;
        while Instant::now() < deadline {
            let status = Command::new("kill")
                .args(["-0", &pid.to_string()])
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .status();
            match status {
                Ok(status) if status.success() => thread::sleep(POLL_INTERVAL),
                Ok(_) => return Ok(()),
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                    bail!("kill utility is required to fence native updater activation")
                }
                Err(error) => return Err(error).context("inspect native parent process"),
            }
        }
        bail!("native parent process did not exit before activation timeout")
    }
}

fn validate(args: &Args) -> Result<()> {
    for (name, path) in [
        ("active artifact", &args.active_artifact),
        ("rollback artifact", &args.rollback_artifact),
        ("stage artifact", &args.stage_artifact),
        ("update journal", &args.update_journal),
        ("confirmation file", &args.confirm_file),
        ("grant public key", &args.grant_public_key),
        ("release public key", &args.release_public_key),
        ("selection public key", &args.selection_public_key),
        ("effect journal", &args.effect_journal),
        ("Windows DPAPI path", &args.windows_dpapi_session_path),
    ] {
        if !path.is_absolute() {
            bail!("native updater {name} must be absolute");
        }
    }
    validate_digest(&args.predecessor_digest, "predecessor digest")?;
    validate_digest(&args.expected_package_digest, "expected package digest")?;
    validate_digest(&args.manifest_digest, "manifest digest")?;
    Ok(())
}

fn validate_digest(value: &str, name: &str) -> Result<()> {
    if value.len() != 64
        || value.bytes().all(|byte| byte == b'0')
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'))
    {
        bail!("native updater {name} must be a non-zero lowercase SHA-256 digest");
    }
    Ok(())
}
