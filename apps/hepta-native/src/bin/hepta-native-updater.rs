use hepta_native::security::TrustedKeySet;
use hepta_native::update_handoff::UpdateHandoff;
use hepta_native::updater::PendingUpdateStatus;
use hepta_native::updater::UpdateManager;
use hepta_native::updater::activate_staged_update;
use std::io::Write as _;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

fn main() {
    if let Err(error) = run() {
        eprintln!("hepta-native-updater: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args().skip(1);
    let pending = absolute_arg(args.next(), "PENDING_JSON")?;
    let trusted_keys = absolute_arg(args.next(), "TRUSTED_KEYS_JSON")?;
    let target = absolute_arg(args.next(), "TARGET_BINARY")?;
    let protocol: u32 = args
        .next()
        .ok_or("missing BACKEND_PROTOCOL_VERSION")?
        .parse()?;
    if args.next().as_deref() != Some("--") {
        return Err("expected -- followed by ordinary product restart arguments".into());
    }
    let restart_args: Vec<String> = args.collect();
    // Validate before modifying any installed bytes. A static smoke/test profile
    // can never be the application's update readiness signal.
    UpdateHandoff::from_invocation("1".repeat(64), &restart_args)?;
    let key_set = TrustedKeySet::from_path(&trusted_keys)?;
    let root = pending
        .parent()
        .ok_or("pending record lacks a parent")?
        .to_path_buf();
    let manager = UpdateManager::new(key_set.clone(), root)?;
    if manager.pending_path() != pending {
        return Err("updater requires the canonical pending record".into());
    }
    let _runner = manager.lock_runner()?;
    if manager
        .load_pending()?
        .is_some_and(|p| p.status == PendingUpdateStatus::Confirmed)
    {
        // A lost helper acknowledgement cannot reapply an already confirmed update.
        return Ok(());
    }
    if manager.recover_interrupted_activation()? {
        return Err("interrupted update rolled back; restage before activation".into());
    }
    wait_for_executable_release(&target)?;
    activate_staged_update(&pending, &key_set, &target, protocol)?;
    restart_and_observe(&manager, &target, &restart_args)
}

fn restart_and_observe(
    manager: &UpdateManager,
    target: &Path,
    arguments: &[String],
) -> Result<(), Box<dyn std::error::Error>> {
    let handoff = match manager.prepare_restart(arguments) {
        Ok(handoff) => handoff,
        Err(error) => {
            manager.rollback_unconfirmed()?;
            return Err(error.into());
        }
    };
    let mut child = match Command::new(target)
        .args(arguments)
        .arg("--update-handoff")
        .arg(handoff.nonce())
        .stdin(Stdio::piped())
        .spawn()
    {
        Ok(child) => child,
        Err(error) => {
            manager.rollback_unconfirmed()?;
            return Err(error.into());
        }
    };
    let deadline = Instant::now() + Duration::from_secs(30);
    let outcome = (|| -> Result<(), Box<dyn std::error::Error>> {
        loop {
            if let Some(status) = child.try_wait()? {
                return Err(format!("candidate exited before product readiness: {status}").into());
            }
            match manager.load_pending() {
                Ok(Some(pending))
                    if pending.status == PendingUpdateStatus::Confirmed
                        && pending.handoff.as_ref() == Some(&handoff)
                        && pending
                            .readiness
                            .as_ref()
                            .is_some_and(|ready| ready.process_id == child.id()) =>
                {
                    // The candidate's stdin monitor exits on helper death before
                    // this ack, including the helper-death/reopen failure cut.
                    child
                        .stdin
                        .take()
                        .ok_or("candidate handoff pipe disappeared")?
                        .write_all(b"C")?;
                    return Ok(());
                }
                Ok(Some(pending))
                    if pending.status == PendingUpdateStatus::ActivatedUnconfirmed => {}
                Ok(_) => return Err("candidate update state changed before readiness".into()),
                Err(error) => return Err(format!("observe candidate readiness: {error}").into()),
            }
            if Instant::now() >= deadline {
                return Err(
                    "candidate failed to produce authenticated GUI readiness within 30 seconds"
                        .into(),
                );
            }
            std::thread::sleep(Duration::from_millis(25));
        }
    })();
    if outcome.is_ok() {
        return outcome;
    }
    // Drop the handoff pipe first; the product candidate treats its loss as a
    // failed startup. Do not restore bytes until process termination is observed.
    drop(child.stdin.take());
    if child.try_wait()?.is_none() {
        child.kill()?;
    }
    child.wait()?;
    manager.rollback_unconfirmed()?;
    outcome
}

#[cfg(windows)]
fn wait_for_executable_release(target: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        match std::fs::OpenOptions::new().write(true).open(target) {
            Ok(file) => {
                drop(file);
                return Ok(());
            }
            Err(error)
                if matches!(error.raw_os_error(), Some(5 | 32)) && Instant::now() < deadline =>
            {
                std::thread::sleep(Duration::from_millis(25));
            }
            Err(error) => return Err(error.into()),
        }
    }
}
#[cfg(not(windows))]
fn wait_for_executable_release(_target: &Path) -> Result<(), Box<dyn std::error::Error>> {
    Ok(())
}

fn absolute_arg(
    value: Option<String>,
    name: &'static str,
) -> Result<PathBuf, Box<dyn std::error::Error>> {
    let path = PathBuf::from(value.ok_or_else(|| format!("missing {name}"))?);
    if !path.is_absolute() {
        return Err(format!("{name} must be absolute").into());
    }
    Ok(path)
}
