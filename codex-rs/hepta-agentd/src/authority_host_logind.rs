//! Independent physical-login verification for an explicit original Root
//! deployment. The provider supplies its already-held leader descriptor.
use crate::HostAuthorityNativeProfile;
use crate::HostAuthorityService;
use crate::deployment_issuer::TextHumanBinding;
use sha2::Digest;
use sha2::Sha256;
use std::collections::BTreeMap;
use std::io;
use std::io::Read;
use std::os::fd::AsRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::fs::FileTypeExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

pub(super) struct OriginalLogindSession {
    held: OwnedFd,
    binding: TextHumanBinding,
}

impl HostAuthorityNativeProfile {
    pub(crate) fn original_human_binding(&self) -> TextHumanBinding {
        TextHumanBinding {
            principal_id: self.principal_id.clone(),
            session_id: self.session_id.clone(),
            permission_revision: self.permission_revision,
            expires_at_ms: self.expires_at_ms,
            route: self.route.clone(),
        }
    }
}

impl HostAuthorityService {
    pub(crate) fn with_original_logind_session(
        mut self,
        profile: &HostAuthorityNativeProfile,
        uid: u32,
        held: OwnedFd,
    ) -> io::Result<Self> {
        if self.logind_session.is_some() {
            return Err(io::Error::other("original human login is already retained"));
        }
        verify_original_login(profile, uid, &held)?;
        self.logind_session = Some(OriginalLogindSession {
            held,
            binding: profile.original_human_binding(),
        });
        Ok(self)
    }

    pub(crate) fn check_logind_lifetime(&self) -> io::Result<()> {
        if let Some(login) = &self.logind_session {
            crate::authority_host_runtime::owner_alive(
                &login.held,
                Instant::now() + Duration::from_secs(1),
            )?;
        }
        Ok(())
    }

    pub(crate) fn check_logind_binding(&self, binding: &TextHumanBinding) -> io::Result<()> {
        if self
            .logind_session
            .as_ref()
            .is_some_and(|login| &login.binding != binding)
        {
            return Err(io::Error::other(
                "native human registration changed the original verified login",
            ));
        }
        self.check_logind_lifetime()
    }
}

fn verify_original_login(
    profile: &HostAuthorityNativeProfile,
    uid: u32,
    held: &OwnedFd,
) -> io::Result<()> {
    let invalid =
        || io::Error::other("original held physical login differs from protected native profile");
    let parts: Vec<_> = profile.session_id.split(':').collect();
    // SAFETY: these syscalls read only this process's actual credentials.
    if unsafe { libc::getuid() } != 0
        || unsafe { libc::geteuid() } != 0
        || uid == 0
        || parts.len() != 4
        || parts[0] != "logind"
        || parts[2].is_empty()
        || parts[2].len() > 64
        || !parts[2]
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_-".contains(&b))
    {
        return Err(invalid());
    }
    let start: u64 = parts[3].parse().map_err(|_| invalid())?;
    let machine = std::fs::read_to_string("/etc/machine-id")?;
    let principal = format!(
        "linux-user:{:x}:{uid}",
        Sha256::digest(machine.trim().as_bytes())
    );
    if start == 0
        || profile.principal_id != principal
        || parts[1] != std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?.trim()
    {
        return Err(invalid());
    }
    let fd = held.as_raw_fd();
    if std::fs::read_link(format!("/proc/self/fd/{fd}"))? != Path::new("anon_inode:[pidfd]") {
        return Err(invalid());
    }
    let info = std::fs::read_to_string(format!("/proc/self/fdinfo/{fd}"))?;
    let pid: u32 = info
        .lines()
        .find_map(|line| line.strip_prefix("Pid:"))
        .and_then(|value| value.trim().parse().ok())
        .filter(|pid| *pid > 1)
        .ok_or_else(invalid)?;
    crate::authority_host_runtime::owner_alive(held, Instant::now() + Duration::from_secs(1))?;
    let stat = std::fs::read_to_string(format!("/proc/{pid}/stat"))?;
    let actual_start = stat
        .rsplit_once(") ")
        .and_then(|(_, fields)| fields.split_whitespace().nth(19))
        .and_then(|value| value.parse::<u64>().ok());
    if actual_start != Some(start) {
        return Err(invalid());
    }
    let bus = std::fs::symlink_metadata("/run/dbus/system_bus_socket")?;
    if !bus.file_type().is_socket() || bus.uid() != 0 {
        return Err(invalid());
    }
    let path = Path::new("/usr/bin/loginctl");
    for ancestor in path.ancestors().skip(1) {
        let meta = std::fs::symlink_metadata(ancestor)?;
        if !meta.is_dir() || meta.uid() != 0 || meta.mode() & 0o022 != 0 {
            return Err(invalid());
        }
    }
    let program = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)?;
    let meta = program.metadata()?;
    if !meta.is_file() || meta.uid() != 0 || meta.mode() & 0o022 != 0 || meta.mode() & 0o111 == 0 {
        return Err(invalid());
    }
    let mut child = std::process::Command::new(format!("/proc/self/fd/{}", program.as_raw_fd()))
        .args([
            "show-session",
            parts[2],
            "--no-pager",
            "--property=Id,User,Active,State,Remote,Class,Type,Leader,Seat",
        ])
        .env_clear()
        .env("PATH", "/usr/bin:/bin")
        .env("LANG", "C")
        .env("LC_ALL", "C")
        .env(
            "DBUS_SYSTEM_BUS_ADDRESS",
            "unix:path=/run/dbus/system_bus_socket",
        )
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()?;
    let end = Instant::now() + Duration::from_secs(3);
    let status = loop {
        if let Some(status) = child.try_wait()? {
            break status;
        }
        if Instant::now() >= end {
            let _ = child.kill();
            let _ = child.wait();
            return Err(io::Error::new(
                io::ErrorKind::TimedOut,
                "original logind query deadline",
            ));
        }
        std::thread::sleep(Duration::from_millis(5));
    };
    let mut output = Vec::new();
    child
        .stdout
        .take()
        .ok_or_else(invalid)?
        .take(16 * 1024 + 1)
        .read_to_end(&mut output)?;
    if !status.success() || output.len() > 16 * 1024 {
        return Err(invalid());
    }
    let text = std::str::from_utf8(&output).map_err(|_| invalid())?;
    let mut properties = BTreeMap::new();
    for line in text.lines() {
        let (key, value) = line.split_once('=').ok_or_else(invalid)?;
        if properties.insert(key, value).is_some() {
            return Err(invalid());
        }
    }
    if properties.len() != 9
        || properties.get("Id") != Some(&parts[2])
        || properties.get("User").copied() != Some(uid.to_string().as_str())
        || properties.get("Leader").copied() != Some(pid.to_string().as_str())
        || properties.get("Active") != Some(&"yes")
        || properties.get("State") != Some(&"active")
        || properties.get("Remote") != Some(&"no")
        || properties.get("Class") != Some(&"user")
        || !matches!(properties.get("Type").copied(), Some("wayland" | "x11"))
        || properties.get("Seat").is_none_or(|seat| seat.is_empty())
    {
        return Err(invalid());
    }
    crate::authority_host_runtime::owner_alive(held, Instant::now() + Duration::from_secs(1))
}

#[cfg(test)]
#[path = "authority_host_logind_tests.rs"]
mod tests;
