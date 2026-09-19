use std::path::PathBuf;
use std::process::Command;

use hepta_native::security::TrustedKeySet;
use hepta_native::updater::UpdateManager;
use hepta_native::updater::activate_staged_update;

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
    if args.next().is_some() {
        return Err("unexpected updater arguments".into());
    }
    let key_set = TrustedKeySet::from_path(&trusted_keys)?;
    let update_root = pending
        .parent()
        .ok_or("pending update record must have a parent directory")?
        .to_path_buf();
    let manager = UpdateManager::new(key_set.clone(), update_root)?;
    activate_staged_update(&pending, &key_set, &target, protocol)?;

    let smoke = Command::new(&target).arg("--self-test").status();
    match smoke {
        Ok(status) if status.success() => {
            if !manager.confirm_current_digest(&target)? {
                manager.rollback_unconfirmed()?;
                return Err(
                    "activated binary passed smoke test but update confirmation was absent".into(),
                );
            }
        }
        Ok(status) => {
            manager.rollback_unconfirmed()?;
            return Err(format!("activated binary self-test failed with {status}").into());
        }
        Err(error) => {
            manager.rollback_unconfirmed()?;
            return Err(format!("activated binary could not start: {error}").into());
        }
    }
    Ok(())
}

fn absolute_arg(
    value: Option<String>,
    name: &'static str,
) -> Result<PathBuf, Box<dyn std::error::Error>> {
    let path = PathBuf::from(value.ok_or_else(|| format!("missing {name}"))?);
    if !path.is_absolute() {
        return Err(format!("{name} must be an absolute path").into());
    }
    Ok(path)
}
