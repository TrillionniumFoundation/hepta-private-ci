//! Optional Fleet configuration is separate from the legacy public options.

use std::path::PathBuf;

use anyhow::Context;
use anyhow::Result;

use crate::NativeGatewayOptions;

#[derive(Debug)]
pub(super) struct ObserverOptions {
    pub socket: PathBuf,
    pub owner_uid: u32,
}

#[derive(Debug)]
pub(super) struct ControllerOptions {
    pub socket: PathBuf,
    pub owner_uid: u32,
    pub auth_keyring_account: String,
    pub capability_file: Option<PathBuf>,
}

pub(super) struct LaunchConfiguration {
    pub options: NativeGatewayOptions,
    pub observer: Option<ObserverOptions>,
    pub controller: Option<ControllerOptions>,
    pub read_capability_file: Option<PathBuf>,
}

pub(super) fn parse(raw: &[String]) -> Result<Option<LaunchConfiguration>> {
    if raw.first().map(String::as_str) != Some("--serve-ui") {
        return Ok(None);
    }
    let mut legacy = vec![raw[0].clone()];
    let mut socket = None;
    let mut owner_uid = None;
    let mut controller_socket = None;
    let mut controller_owner_uid = None;
    let mut controller_account = None;
    let mut controller_capability_file = None;
    let mut read_capability_file = None;
    let mut index = 1;
    while index < raw.len() {
        match raw[index].as_str() {
            "--controller-socket" | "--lifecycle-capability-file" | "--auth-capability-file" => {
                let name = raw[index].as_str();
                index += 1;
                let path = PathBuf::from(
                    raw.get(index)
                        .context("capability option requires an absolute path")?,
                );
                let selected = match name {
                    "--controller-socket" => &mut controller_socket,
                    "--lifecycle-capability-file" => &mut controller_capability_file,
                    _ => &mut read_capability_file,
                };
                if !path.is_absolute() || selected.replace(path).is_some() {
                    anyhow::bail!("capability path must be absolute and specified once");
                }
            }
            "--controller-owner-uid" => {
                index += 1;
                let uid = raw
                    .get(index)
                    .context("controller owner UID is required")?
                    .parse::<u32>()?;
                if controller_owner_uid.replace(uid).is_some() {
                    anyhow::bail!("duplicate controller owner UID");
                }
            }
            "--lifecycle-auth-keyring-account" => {
                index += 1;
                let account = raw
                    .get(index)
                    .context("lifecycle account is required")?
                    .clone();
                crate::validate_auth_account(&account)?;
                if controller_account.replace(account).is_some() {
                    anyhow::bail!("duplicate lifecycle account");
                }
            }
            "--observer-socket" => {
                index += 1;
                let value = raw.get(index).context("--observer-socket requires PATH")?;
                let path = PathBuf::from(value);
                if !path.is_absolute() || socket.replace(path).is_some() {
                    anyhow::bail!("observer socket must be one absolute path");
                }
            }
            "--observer-owner-uid" => {
                index += 1;
                let value = raw
                    .get(index)
                    .context("--observer-owner-uid requires UID")?;
                let uid = value
                    .parse::<u32>()
                    .context("observer owner UID is invalid")?;
                if owner_uid.replace(uid).is_some() {
                    anyhow::bail!("observer owner UID may be specified only once");
                }
            }
            _ => legacy.push(raw[index].clone()),
        }
        index += 1;
    }
    let observer = match (socket, owner_uid) {
        (Some(socket), Some(owner_uid)) => Some(ObserverOptions { socket, owner_uid }),
        (None, None) => None,
        _ => anyhow::bail!("Fleet observation requires both socket and pinned owner UID"),
    };
    let options = crate::parse_serve_ui_args(&legacy)?.context("gateway mode is missing")?;
    let controller = match (controller_socket, controller_owner_uid, controller_account) {
        (Some(socket), Some(owner_uid), Some(auth_keyring_account)) if observer.is_some() => {
            Some(ControllerOptions {
                socket,
                owner_uid,
                auth_keyring_account,
                capability_file: controller_capability_file,
            })
        }
        (None, None, None) if controller_capability_file.is_none() => None,
        _ => anyhow::bail!(
            "lifecycle control requires Fleet observer, controller socket, pinned owner UID and separate account"
        ),
    };
    Ok(Some(LaunchConfiguration {
        options,
        observer,
        controller,
        read_capability_file,
    }))
}

#[cfg(test)]
#[path = "source_launch_tests.rs"]
mod tests;
