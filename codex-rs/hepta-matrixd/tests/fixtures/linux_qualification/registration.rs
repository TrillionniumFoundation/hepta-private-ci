//! Two one-use setup sessions from the original pinned server registration.

use std::fs::File;
use std::fs::Metadata;
use std::fs::OpenOptions;
use std::io::Read;
use std::os::fd::AsRawFd;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Mutex;

use anyhow::Context;
use anyhow::Result;
use anyhow::anyhow;
use anyhow::ensure;
use reqwest::Client;
use serde::Deserialize;
use serde_json::Value;
use serde_json::json;
use url::Url;

use crate::AGENT_A_MXID;
use crate::AGENT_B_MXID;
use crate::MATRIX_SETUP_STEP_TIMEOUT;
use crate::endpoint;

const DIRECTORY: &str = "/tmp/hepta-registration-sessions";
const NAMES: [&str; 2] = ["agent-a-session.json", "agent-b-session.json"];
// Linux arm64 UAPI overrides the generic directory/no-follow values. The
// original qualification and take() both reject every non-aarch64 runtime.
const ARM64_DIRECTORY: i32 = 0o40000;
const ARM64_NOFOLLOW: i32 = 0o100000;
const ARM64_NONBLOCK: i32 = 0o4000;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Session {
    user_id: String,
    device_id: String,
    access_token: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Whoami {
    user_id: String,
    device_id: String,
    is_guest: bool,
}

pub(crate) struct RegistrationSessions {
    sessions: Mutex<[Option<Session>; 2]>,
}

fn same_file(left: &Metadata, right: &Metadata) -> bool {
    left.dev() == right.dev() && left.ino() == right.ino()
}

fn read_once(directory: &Path, name: &str, user: &str, uid: u32) -> Result<Session> {
    let path = directory.join(name);
    let mut file = OpenOptions::new()
        .read(true)
        .custom_flags(ARM64_NOFOLLOW | ARM64_NONBLOCK)
        .open(&path)
        .context("failed to open private registration capability")?;
    let metadata = file.metadata()?;
    ensure!(
        metadata.is_file()
            && metadata.mode() & 0o7777 == 0o600
            && metadata.uid() == uid
            && metadata.nlink() == 1
            && same_file(&metadata, &std::fs::symlink_metadata(&path)?),
        "registration capability identity or mode differs"
    );
    let mut raw = Vec::new();
    (&mut file).take(8193).read_to_end(&mut raw)?;
    let after = file.metadata()?;
    ensure!(
        same_file(&after, &std::fs::symlink_metadata(&path)?)
            && metadata.size() == after.size()
            && metadata.mode() == after.mode()
            && metadata.uid() == after.uid()
            && metadata.nlink() == after.nlink()
            && metadata.mtime() == after.mtime()
            && metadata.mtime_nsec() == after.mtime_nsec()
            && metadata.ctime() == after.ctime()
            && metadata.ctime_nsec() == after.ctime_nsec(),
        "registration capability changed during read"
    );
    std::fs::remove_file(&path)?;
    ensure!(
        raw.len() <= 8192,
        "registration capability exceeds its bound"
    );
    let session: Session = serde_json::from_slice(&raw)
        .map_err(|_| anyhow!("invalid private registration session JSON"))?;
    ensure!(session.user_id == user, "registration user differs");
    for (value, minimum, maximum) in [
        (&session.device_id, 1, 255),
        (&session.access_token, 32, 4096),
    ] {
        ensure!(
            (minimum..=maximum).contains(&value.len())
                && value.bytes().all(|byte| (33..=126).contains(&byte)),
            "registration session field shape differs"
        );
    }
    Ok(session)
}

fn cleanup(directory: &Path, root: &Path, opened: &Metadata) -> Result<()> {
    let mut failed = false;
    for name in NAMES {
        if let Err(error) = std::fs::remove_file(directory.join(name))
            && error.kind() != std::io::ErrorKind::NotFound
        {
            failed = true;
        }
    }
    let same_directory = std::fs::symlink_metadata(root)
        .is_ok_and(|actual| actual.is_dir() && same_file(opened, &actual));
    if !same_directory || std::fs::remove_dir(root).is_err() {
        failed = true;
    }
    ensure!(!failed, "registration capability cleanup failed");
    Ok(())
}

impl RegistrationSessions {
    pub(crate) fn take() -> Result<Self> {
        ensure!(
            std::env::consts::ARCH == "aarch64",
            "registration sessions require the original native ARM64 qualification"
        );
        let root = Path::new(DIRECTORY);
        ensure!(
            root.parent() == Some(Path::new("/tmp")),
            "invalid session root"
        );
        ensure!(
            Path::new("/tmp").canonicalize()? == Path::new("/tmp"),
            "registration temporary root is not physical"
        );
        let directory: File = OpenOptions::new()
            .read(true)
            .custom_flags(ARM64_DIRECTORY | ARM64_NOFOLLOW | ARM64_NONBLOCK)
            .open(root)?;
        let metadata = directory.metadata()?;
        let status = std::fs::read_to_string("/proc/self/status")?;
        let uid = status
            .lines()
            .find_map(|line| line.strip_prefix("Uid:\t"))
            .and_then(|value| value.split_whitespace().nth(1))
            .context("missing effective uid")?
            .parse::<u32>()?;
        ensure!(
            metadata.is_dir()
                && metadata.uid() == uid
                && same_file(&metadata, &std::fs::symlink_metadata(root)?),
            "registration directory authority differs"
        );
        let stable = PathBuf::from(format!("/proc/self/fd/{}", directory.as_raw_fd()));
        let result = (|| {
            ensure!(
                metadata.mode() & 0o7777 == 0o700,
                "registration directory mode differs"
            );
            let mut names = std::fs::read_dir(&stable)?
                .map(|entry| entry.map(|item| item.file_name()))
                .collect::<std::io::Result<Vec<_>>>()?;
            names.sort();
            ensure!(
                names == NAMES.map(std::ffi::OsString::from),
                "registration capability set differs"
            );
            let a = read_once(&stable, NAMES[0], AGENT_A_MXID, uid)?;
            let b = read_once(&stable, NAMES[1], AGENT_B_MXID, uid)?;
            ensure!(
                a.device_id != b.device_id && a.access_token != b.access_token,
                "registration sessions must have distinct devices and tokens"
            );
            Ok(Self {
                sessions: Mutex::new([Some(a), Some(b)]),
            })
        })();
        let cleaned = cleanup(&stable, root, &metadata);
        match (result, cleaned) {
            (Ok(value), Ok(())) => Ok(value),
            (Err(error), Ok(())) => Err(error),
            (_, Err(error)) => Err(error),
        }
    }

    pub(crate) async fn join(
        &self,
        homeserver: &str,
        mxid: &str,
        room_id: &str,
        forbidden_devices: &[&str],
    ) -> Result<()> {
        let index = [AGENT_A_MXID, AGENT_B_MXID]
            .iter()
            .position(|value| *value == mxid)
            .context("unknown setup session user")?;
        let session = self
            .sessions
            .lock()
            .map_err(|_| anyhow!("registration session ownership failed"))?[index]
            .take()
            .context("registration session already consumed")?;
        ensure!(
            !forbidden_devices.contains(&session.device_id.as_str()),
            "setup session reused a human or product device"
        );
        let homeserver = Url::parse(homeserver)?;
        let client = Client::builder()
            .timeout(MATRIX_SETUP_STEP_TIMEOUT)
            .build()?;
        eprintln!("R4_STAGE agent_join_whoami:start");
        let identity: Whoami = client
            .get(endpoint(
                &homeserver,
                &["_matrix", "client", "v3", "account", "whoami"],
            )?)
            .bearer_auth(&session.access_token)
            .send()
            .await
            .map_err(|_| anyhow!("setup session identity request failed"))?
            .error_for_status()
            .map_err(|_| anyhow!("setup session identity status failed"))?
            .json()
            .await
            .map_err(|_| anyhow!("setup session identity JSON failed"))?;
        ensure!(
            identity.user_id == mxid
                && identity.user_id == session.user_id
                && identity.device_id == session.device_id
                && !identity.is_guest,
            "setup session token does not bind the registered user and device"
        );
        eprintln!("R4_STAGE agent_join_whoami:done");
        eprintln!("R4_STAGE agent_join_request:start");
        let joined_response = client
            .post(endpoint(
                &homeserver,
                &["_matrix", "client", "v3", "join", room_id],
            )?)
            .bearer_auth(&session.access_token)
            .json(&json!({}))
            .send()
            .await;
        // Preserve logout before inspecting the join result, including errors.
        // An unbound whoami response above never authorizes mutation or logout.
        eprintln!("R4_STAGE agent_join_logout:start");
        client
            .post(endpoint(
                &homeserver,
                &["_matrix", "client", "v3", "logout"],
            )?)
            .bearer_auth(&session.access_token)
            .json(&json!({}))
            .send()
            .await
            .map_err(|_| anyhow!("setup session logout request failed"))?
            .error_for_status()
            .map_err(|_| anyhow!("setup session logout status failed"))?;
        eprintln!("R4_STAGE agent_join_logout:done");
        let joined: Value = joined_response
            .map_err(|_| anyhow!("setup session join request failed"))?
            .error_for_status()
            .map_err(|_| anyhow!("setup session join status failed"))?
            .json()
            .await
            .map_err(|_| anyhow!("setup session join JSON failed"))?;
        eprintln!("R4_STAGE agent_join_request:done");
        ensure!(
            joined["room_id"].as_str() == Some(room_id),
            "Agent fixture join did not bind the exact fresh encrypted room"
        );
        Ok(())
    }
}
