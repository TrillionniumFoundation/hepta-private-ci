//! Linux kernel identity for the one explicitly enrolled gateway service.
//! No identity field in a lifecycle request participates in this check.

use std::fs::File;
use std::io::Read;
use std::os::unix::fs::MetadataExt;
use std::path::Path;
use std::path::PathBuf;

use serde::Deserialize;
use tokio::net::UnixStream;

use crate::SupervisorError;

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ControllerPrincipal {
    pub(crate) uid: u32,
    pub(crate) gid: u32,
    pub(crate) desktop_uid: u32,
    pub(crate) gateway_executable: PathBuf,
    pub(crate) gateway_cgroup: String,
}

pub(crate) struct ControllerPeerGate {
    principal: ControllerPrincipal,
    executable: File,
    fleet_cgroup: String,
}

fn denied() -> SupervisorError {
    SupervisorError::Invalid("controller peer is not the enrolled gateway service".into())
}

fn protected_directory(path: &Path) -> Result<(), SupervisorError> {
    if !path.is_absolute() || path.canonicalize()? != path {
        return Err(denied());
    }
    for ancestor in path.ancestors() {
        let metadata = std::fs::symlink_metadata(ancestor)?;
        if !metadata.is_dir() || metadata.uid() != 0 || metadata.mode() & 0o022 != 0 {
            return Err(denied());
        }
    }
    Ok(())
}

impl ControllerPeerGate {
    pub(crate) fn open(
        principal: ControllerPrincipal,
        fleet_cgroup: &str,
    ) -> Result<Self, SupervisorError> {
        let path = &principal.gateway_executable;
        if principal.uid == 0
            || principal.gid == 0
            || principal.desktop_uid == 0
            || path.canonicalize()? != *path
            || !principal.gateway_cgroup.starts_with('/')
            || principal.gateway_cgroup == "/"
            || principal.gateway_cgroup.len() > 4096
            || principal.gateway_cgroup.split('/').skip(1).any(|part| {
                part.is_empty() || part == "." || part == ".." || part.bytes().any(|b| b < 0x20)
            })
        {
            return Err(denied());
        }
        protected_directory(path.parent().ok_or_else(denied)?)?;
        let executable = File::open(path)?;
        let metadata = executable.metadata()?;
        if !metadata.is_file()
            || metadata.uid() != 0
            || metadata.nlink() != 1
            || metadata.mode() & 0o022 != 0
            || metadata.mode() & 0o111 == 0
        {
            return Err(denied());
        }
        let fleet_cgroup = format!("/{}", fleet_cgroup.trim_matches('/'));
        if within(&principal.gateway_cgroup, &fleet_cgroup) {
            return Err(denied());
        }
        let cgroup = Path::new("/sys/fs/cgroup").join(&principal.gateway_cgroup[1..]);
        protected_directory(&cgroup)?;
        let membership = std::fs::symlink_metadata(cgroup.join("cgroup.procs"))?;
        if !membership.is_file() || membership.uid() != 0 || membership.mode() & 0o022 != 0 {
            return Err(denied());
        }
        Ok(Self {
            principal,
            executable,
            fleet_cgroup,
        })
    }

    pub(crate) fn principal(&self) -> &ControllerPrincipal {
        &self.principal
    }

    pub(crate) fn verify(&self, stream: &UnixStream) -> Result<(), SupervisorError> {
        let credentials = stream.peer_cred()?;
        if credentials.uid() != self.principal.uid || credentials.gid() != self.principal.gid {
            return Err(denied());
        }
        let pid = credentials
            .pid()
            .filter(|pid| *pid > 0)
            .ok_or_else(denied)?;
        let process = PathBuf::from(format!("/proc/{pid}"));
        let before = start_ticks(&process)?;
        let executable = File::open(process.join("exe"))?;
        let expected = self.executable.metadata()?;
        let actual = executable.metadata()?;
        if actual.dev() != expected.dev() || actual.ino() != expected.ino() {
            return Err(denied());
        }
        let cgroup = bounded_text(&process.join("cgroup"), 4096)?;
        if cgroup.trim_end() != format!("0::{}", self.principal.gateway_cgroup)
            || within(&self.principal.gateway_cgroup, &self.fleet_cgroup)
            || before != start_ticks(&process)?
        {
            return Err(denied());
        }
        // Recheck the executable and membership at admission. An inherited socket
        // or a PID that changed executable cannot borrow the enrolled identity.
        let after = File::open(process.join("exe"))?.metadata()?;
        if after.dev() != expected.dev()
            || after.ino() != expected.ino()
            || bounded_text(&process.join("cgroup"), 4096)? != cgroup
            || start_ticks(&process)? != before
        {
            return Err(denied());
        }
        Ok(())
    }
}

fn within(path: &str, base: &str) -> bool {
    path == base
        || path
            .strip_prefix(base)
            .is_some_and(|suffix| suffix.starts_with('/'))
}

fn bounded_text(path: &Path, maximum: u64) -> Result<String, SupervisorError> {
    let mut bytes = Vec::new();
    File::open(path)?
        .take(maximum + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > maximum {
        return Err(denied());
    }
    String::from_utf8(bytes).map_err(|_| denied())
}

fn start_ticks(process: &Path) -> Result<u64, SupervisorError> {
    let stat = bounded_text(&process.join("stat"), 16 * 1024)?;
    stat.rsplit_once(") ")
        .and_then(|(_, fields)| fields.split_ascii_whitespace().nth(19))
        .and_then(|value| value.parse().ok())
        .filter(|value| *value > 0)
        .ok_or_else(denied)
}

#[cfg(test)]
#[path = "controller_peer_tests.rs"]
pub(crate) mod tests;
