//! Trusted Root process custody. No ordinary wire selects an executable, UID,
//! environment, descriptor, lease, cut or authority owner through this API.
//! Root must remain the exclusive reaper and retain the returned child guard.

use super::root_role_child as process;
use super::root_role_executable::require_path;
use super::root_role_executable::require_root;
use super::root_role_fork::Deadlines;
use super::root_role_fork::Mapping;
use crate::RootNotesDeploymentV1;
use crate::RootNotesHostConfigV1;
use crate::RootRoleChild;
use crate::RootRoleExecutable;
use codex_hepta_contracts::HostAuthorityOwnerLifetime;
use std::ffi::CString;
use std::ffi::OsString;
use std::fs::File;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::os::fd::OwnedFd;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::FileTypeExt;
use std::os::unix::fs::MetadataExt;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;

/// Non-serialized, Root-installed display settings. No caller/wire environment
/// is copied. Omitted fields remain absent, including all LD_* and shell state.
pub struct RootSessionEnvironment {
    pub home: PathBuf,
    pub runtime_dir: PathBuf,
    pub display: Option<OsString>,
    pub wayland_display: Option<OsString>,
    pub xauthority: Option<PathBuf>,
    pub dbus_session_bus_address: Option<OsString>,
}

/// Transport only of the original control/boot descriptors. The original HOS2
/// adapter must still verify its sealed page, QueryAbi, boot and capability
/// space. This value neither creates nor transfers a native exec grant.
pub struct RootNativeHostDescriptors {
    pub control: OwnedFd,
    pub bootstrap: File,
}

/// Produce the one initial FD0 document, using the SAME original memfd custody
/// implementation. This config supplies installed paths, never authority.
pub fn seal_root_notes_host_config(config: &RootNotesHostConfigV1) -> io::Result<File> {
    require_root()?;
    config.validate_shape()?;
    if config.root != process::capture(std::process::id() as i32, 0)? {
        return Err(io::Error::other(
            "initial config must name actual Root producer",
        ));
    }
    let bytes = serde_json::to_vec(config).map_err(io::Error::other)?;
    if bytes.len() > crate::ROOT_NOTES_HOST_CONFIG_BOUND {
        return Err(io::Error::other(
            "initial config exceeds original 64KiB bound",
        ));
    }
    crate::authority_host_bootstrap_seal::seal_bytes(&bytes)
}

/// Fixed Host UID/GID60001. Stdout/stderr are explicit /dev/null sinks. The
/// original role guard must set dumpable=0 AFTER exec, before opening authority.
pub fn spawn_root_notes_host(
    executable: &RootRoleExecutable,
    arguments: &[OsString],
    config: File,
    root_pidfd: OwnedFd,
    end_boottime_ns: u64,
) -> io::Result<RootRoleChild> {
    let deadlines = Deadlines::new(end_boottime_ns)?;
    let config_value = initial_config(&config, &root_pidfd)?;
    if config_value.deployment != (RootNotesDeploymentV1::NotesOnly {}) {
        return Err(io::Error::other(
            "native profile needs original FD5 and FD6",
        ));
    }
    host(
        executable,
        arguments,
        config,
        root_pidfd,
        config_value,
        Vec::new(),
        deadlines,
    )
}

pub fn spawn_root_native_notes_host(
    executable: &RootRoleExecutable,
    arguments: &[OsString],
    config: File,
    root_pidfd: OwnedFd,
    native: RootNativeHostDescriptors,
    end_boottime_ns: u64,
) -> io::Result<RootRoleChild> {
    let deadlines = Deadlines::new(end_boottime_ns)?;
    let config_value = initial_config(&config, &root_pidfd)?;
    if config_value.deployment != (RootNotesDeploymentV1::NativeHos2 {}) {
        return Err(io::Error::other(
            "FD5 and FD6 require explicit native profile",
        ));
    }
    let extra = vec![
        Mapping::new(&native.control, 5)?,
        Mapping::new(&native.bootstrap, 6)?,
    ];
    host(
        executable,
        arguments,
        config,
        root_pidfd,
        config_value,
        extra,
        deadlines,
    )
}

fn host(
    executable: &RootRoleExecutable,
    arguments: &[OsString],
    config: File,
    root_pidfd: OwnedFd,
    value: RootNotesHostConfigV1,
    mut mappings: Vec<Mapping>,
    deadlines: Deadlines,
) -> io::Result<RootRoleChild> {
    let home = value.agent.home_root;
    require_private_directory(&home, 60001)?;
    let environment = vec![
        environment("HOME", home.as_os_str())?,
        environment("CODEX_HOME", home.as_os_str())?,
        environment("PATH", std::ffi::OsStr::new("/usr/bin:/bin"))?,
    ];
    mappings.extend([Mapping::new(&config, 0)?, Mapping::new(&root_pidfd, 3)?]);
    spawn(
        executable,
        arguments,
        &home,
        environment,
        mappings,
        60001,
        deadlines,
    )
}

/// Fixed Session UID/GID1000. Pass exactly the original Host-created pair from
/// RootNotesSessionChannels::into_descriptors(), in FD0/FD4 order. Each actual
/// socket's SO_PEERCRED must name this launcher's already-held Host child.
pub fn spawn_root_notes_session(
    executable: &RootRoleExecutable,
    arguments: &[OsString],
    host: &RootRoleChild,
    channels: [OwnedFd; 2],
    settings: RootSessionEnvironment,
    end_boottime_ns: u64,
) -> io::Result<RootRoleChild> {
    let deadlines = Deadlines::new(end_boottime_ns)?;
    require_root()?;
    host.check_alive()?;
    if host.peer().uid != 60001 {
        return Err(io::Error::other("actual owned Host required"));
    }
    for channel in &channels {
        crate::root_notes_launch_io::require_connected_unix_datagram(channel)?;
        require_host_socket(channel, host.peer().pid)?;
    }
    require_private_directory(&settings.home, 1000)?;
    require_private_directory(&settings.runtime_dir, 1000)?;
    let mut environment = vec![
        environment("HOME", settings.home.as_os_str())?,
        environment("XDG_RUNTIME_DIR", settings.runtime_dir.as_os_str())?,
        environment("PATH", std::ffi::OsStr::new("/usr/bin:/bin"))?,
    ];
    for (name, value) in [
        ("DISPLAY", settings.display),
        ("WAYLAND_DISPLAY", settings.wayland_display),
        (
            "XAUTHORITY",
            settings.xauthority.map(PathBuf::into_os_string),
        ),
        (
            "DBUS_SESSION_BUS_ADDRESS",
            settings.dbus_session_bus_address,
        ),
    ] {
        if let Some(value) = value {
            environment.push(self::environment(name, &value)?);
        }
    }
    let mappings = vec![
        Mapping::new(&channels[0], 0)?,
        Mapping::new(&host.try_clone_pidfd()?, 3)?,
        Mapping::new(&channels[1], 4)?,
    ];
    let result = spawn(
        executable,
        arguments,
        &settings.home,
        environment,
        mappings,
        1000,
        deadlines,
    )?;
    host.check_alive()?;
    result.check_alive()?;
    Ok(result)
}

fn spawn(
    executable: &RootRoleExecutable,
    arguments: &[OsString],
    home: &Path,
    environment: Vec<CString>,
    mut mappings: Vec<Mapping>,
    uid: u32,
    deadlines: Deadlines,
) -> io::Result<RootRoleChild> {
    require_root()?;
    process::remaining(deadlines.exec)?;
    if arguments.len() > 32 {
        return Err(io::Error::other("too many installed role arguments"));
    }
    let mut argv = vec![CString::new("hepta-installed-role").unwrap()];
    for value in arguments {
        if value.len() > 4096 {
            return Err(io::Error::other("installed role argument exceeds bound"));
        }
        argv.push(CString::new(value.as_bytes()).map_err(io::Error::other)?);
    }
    let sink = std::fs::OpenOptions::new()
        .write(true)
        .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
        .open("/dev/null")?;
    let metadata = sink.metadata()?;
    if !metadata.file_type().is_char_device() || metadata.rdev() != libc::makedev(1, 3) {
        return Err(io::Error::other("stdio sink must be actual /dev/null"));
    }
    mappings.extend([Mapping::new(&sink, 1)?, Mapping::new(&sink, 2)?]);
    let directory = CString::new(home.as_os_str().as_bytes()).map_err(io::Error::other)?;
    crate::root_role_fork::spawn(
        executable.for_exec()?,
        argv,
        environment,
        directory,
        mappings,
        uid,
        deadlines,
    )
}

use std::os::unix::fs::OpenOptionsExt;
fn initial_config(config: &File, root_pidfd: &OwnedFd) -> io::Result<RootNotesHostConfigV1> {
    require_root()?;
    let len = config.metadata()?.len();
    if len == 0 || len > crate::ROOT_NOTES_HOST_CONFIG_BOUND as u64 {
        return Err(io::Error::other("initial config exceeds original bound"));
    }
    crate::authority_host_bootstrap_seal::validate_sealed(config, len)?;
    let mut input = config.try_clone()?;
    input.rewind()?;
    let mut bytes = Vec::with_capacity(len as usize);
    Read::by_ref(&mut input)
        .take(crate::ROOT_NOTES_HOST_CONFIG_BOUND as u64 + 1)
        .read_to_end(&mut bytes)?;
    input.rewind()?;
    let value: RootNotesHostConfigV1 = serde_json::from_slice(&bytes).map_err(io::Error::other)?;
    value.validate_shape()?;
    let root = process::capture(std::process::id() as i32, 0)?;
    if value.root != root {
        return Err(io::Error::other("initial config must pin this actual Root"));
    }
    HostAuthorityOwnerLifetime::from_pidfd(
        root_pidfd.try_clone()?,
        root.pid,
        Duration::from_secs(300),
    )
    .map_err(io::Error::other)?
    .check_alive()
    .map_err(io::Error::other)?;
    Ok(value)
}
fn require_private_directory(path: &Path, uid: u32) -> io::Result<()> {
    require_path(path)?;
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.is_dir()
        || metadata.uid() != uid
        || metadata.gid() != uid
        || metadata.mode() & 0o7777 != 0o700
    {
        return Err(io::Error::other(
            "fixed role directory must be owned mode0700",
        ));
    }
    // The final directory is the target's own writable home. Its ancestors must
    // not be replaceable by another unprivileged identity.
    for ancestor in path
        .parent()
        .ok_or_else(|| io::Error::other("home ancestor"))?
        .ancestors()
    {
        let entry = std::fs::symlink_metadata(ancestor)?;
        if !entry.is_dir() || ![0, uid].contains(&entry.uid()) || entry.mode() & 0o022 != 0 {
            return Err(io::Error::other("unsafe installed role directory ancestor"));
        }
    }
    Ok(())
}
fn environment(name: &str, value: &std::ffi::OsStr) -> io::Result<CString> {
    if value.len() > 4096 {
        return Err(io::Error::other("installed environment exceeds bound"));
    }
    let mut bytes = name.as_bytes().to_vec();
    bytes.push(b'=');
    bytes.extend_from_slice(value.as_bytes());
    CString::new(bytes).map_err(io::Error::other)
}
fn require_host_socket(channel: &OwnedFd, pid: u32) -> io::Result<()> {
    use std::os::fd::AsRawFd;
    let mut peer: libc::ucred = unsafe { std::mem::zeroed() };
    let mut len = std::mem::size_of_val(&peer) as libc::socklen_t;
    if unsafe {
        libc::getsockopt(
            channel.as_raw_fd(),
            libc::SOL_SOCKET,
            libc::SO_PEERCRED,
            (&mut peer as *mut libc::ucred).cast(),
            &mut len,
        )
    } < 0
    {
        return Err(io::Error::last_os_error());
    }
    if len as usize != std::mem::size_of_val(&peer)
        || peer.uid != 60001
        || peer.gid != 60001
        || peer.pid as u32 != pid
    {
        return Err(io::Error::other(
            "Session channels must originate from captured actual Host",
        ));
    }
    Ok(())
}

#[cfg(test)]
#[path = "root_notes_native_launcher_tests.rs"]
mod tests;
