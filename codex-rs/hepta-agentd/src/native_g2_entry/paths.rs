//! Fixed native product storage, separate Root material and actual bind views.

use std::ffi::CString;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::FileTypeExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;

pub(super) const STATE: &str = "/state";
pub(super) const FLEET: &str = "/hepta-fleet";
pub(super) const WORKSPACE: &str = "/hepta-workspace";
pub(super) const RUNTIME: &str = "/run/hepta-g2";
pub(super) const LANES: &str = "/run/hepta-g2/authority";

pub(super) fn mount_fresh() -> io::Result<()> {
    let device = std::fs::symlink_metadata("/dev/vda")?;
    if !device.file_type().is_block_device() || device.uid() != 0 {
        return Err(io::Error::other(
            "actual Root-owned native state block device required",
        ));
    }
    empty_root_directory(Path::new(STATE))?;
    mount("/dev/vda", STATE, MountKind::Ext2)?;
    std::fs::set_permissions(STATE, std::fs::Permissions::from_mode(0o700))?;
    if std::fs::read_dir(STATE)?.any(|entry| match entry {
        Ok(entry) => entry.file_name() != "lost+found",
        Err(_) => true,
    }) {
        return Err(io::Error::other(
            "fresh native activation refuses existing or partial state",
        ));
    }
    empty_root_directory(Path::new("/hepta-cgroup"))?;
    mount("none", "/hepta-cgroup", MountKind::Cgroup2)?;
    for name in ["fleet", "workspace"] {
        std::fs::DirBuilder::new()
            .mode(0o700)
            .create(Path::new(STATE).join(name))?;
    }
    File::open(STATE)?.sync_all()?;
    // Root authority remains under /state's private ancestry. Agent data has
    // separate actual views so its original dedicated UID need not traverse
    // Root's material directory. No Root directory becomes peer-writable.
    for (source, target) in [("/state/fleet", FLEET), ("/state/workspace", WORKSPACE)] {
        empty_root_directory(Path::new(target))?;
        mount(source, target, MountKind::Bind)?;
    }
    Ok(())
}

pub(super) fn prepare_runtime() -> io::Result<()> {
    verify_root_ancestry(Path::new("/run"))?;
    std::fs::DirBuilder::new().mode(0o755).create(RUNTIME)?;
    let path = CString::new(RUNTIME).map_err(io::Error::other)?;
    // SAFETY: path is a fixed NUL-terminated live string; only group ownership
    // of this newly created Root-owned directory changes, with no write grant.
    if unsafe { libc::chown(path.as_ptr(), 0, 60001) } != 0 {
        return Err(io::Error::last_os_error());
    }
    std::fs::DirBuilder::new().mode(0o2710).create(LANES)?;
    let lanes = CString::new(LANES).map_err(io::Error::other)?;
    // SAFETY: only this newly created private Root runtime directory changes.
    if unsafe { libc::chown(lanes.as_ptr(), 0, 60001) } != 0 {
        return Err(io::Error::last_os_error());
    }
    std::fs::set_permissions(LANES, std::fs::Permissions::from_mode(0o2710))?;
    verify_root_ancestry(Path::new(LANES))?;
    Ok(())
}

fn verify_root_ancestry(path: &Path) -> io::Result<()> {
    if path.canonicalize()? != path {
        return Err(io::Error::other(
            "physical native Root runtime ancestry required",
        ));
    }
    for ancestor in path.ancestors() {
        let metadata = std::fs::symlink_metadata(ancestor)?;
        if !metadata.is_dir() || metadata.uid() != 0 || metadata.mode() & 0o022 != 0 {
            return Err(io::Error::other(
                "native runtime ancestor is not exclusively Root controlled",
            ));
        }
    }
    Ok(())
}

pub(super) fn owner_socket(path: &Path, gid: u32) -> io::Result<()> {
    let name = CString::new(path.as_os_str().as_encoded_bytes()).map_err(io::Error::other)?;
    // SAFETY: the newly bound socket name is a retained fixed native path.
    if unsafe { libc::chown(name.as_ptr(), 0, gid) } != 0 {
        return Err(io::Error::last_os_error());
    }
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o660))
}

pub(super) fn root_json(path: &Path, value: &impl serde::Serialize) -> io::Result<()> {
    use std::io::Write;
    let bytes = serde_json::to_vec(value).map_err(io::Error::other)?;
    if bytes.is_empty() || bytes.len() > 65_536 {
        return Err(io::Error::other("bounded native Root record required"));
    }
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    File::open(
        path.parent()
            .ok_or_else(|| io::Error::other("missing Root record parent"))?,
    )?
    .sync_all()
}

fn empty_root_directory(path: &Path) -> io::Result<()> {
    match std::fs::DirBuilder::new().mode(0o700).create(path) {
        Ok(()) => {}
        Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {}
        Err(error) => return Err(error),
    }
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.is_dir()
        || metadata.uid() != 0
        || metadata.mode() & 0o7777 != 0o700
        || path.canonicalize()? != path
        || std::fs::read_dir(path)?.next().is_some()
    {
        return Err(io::Error::other(
            "empty physical Root0700 mountpoint required",
        ));
    }
    Ok(())
}

enum MountKind {
    Ext2,
    Cgroup2,
    Bind,
}

fn mount(source: &str, target: &str, kind: MountKind) -> io::Result<()> {
    let source = CString::new(source).map_err(io::Error::other)?;
    let target = CString::new(target).map_err(io::Error::other)?;
    let (kind, flags) = match kind {
        MountKind::Ext2 => (Some(CString::new("ext2").map_err(io::Error::other)?), 0),
        MountKind::Cgroup2 => (Some(CString::new("cgroup2").map_err(io::Error::other)?), 0),
        MountKind::Bind => (None, libc::MS_BIND),
    };
    // SAFETY: every string and optional filesystem name remains NUL-terminated
    // and live for this synchronous original Linux-ABI mount call; data is null.
    if unsafe {
        libc::mount(
            source.as_ptr(),
            target.as_ptr(),
            kind.as_ref().map_or(std::ptr::null(), |kind| kind.as_ptr()),
            flags,
            std::ptr::null(),
        )
    } != 0
    {
        return Err(io::Error::last_os_error());
    }
    Ok(())
}
