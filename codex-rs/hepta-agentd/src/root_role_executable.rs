//! Custody of an installed executable, not native control-role admission.

use codex_hepta_types::Digest32;
use std::fs::File;
use std::fs::Metadata;
use std::fs::OpenOptions;
use std::io;
use std::io::Read;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Component;
use std::path::Path;

const FILE_BOUND: u64 = 8 * 1024 * 1024;
const LOAD_BOUND: u64 = 16 * 1024 * 1024;

/// One retained Root-owned, read-only, single-link x86-64 ELF. The recorded hash
/// can be pinned by the trusted installer. Dynamic ELF custody does not verify
/// its loader/libraries and never confers a native kernel control role.
/// No Clone, Serde or raw descriptor accessor is provided.
pub struct RootRoleExecutable {
    file: File,
    identity: Identity,
    sha256: Digest32,
}

#[derive(Eq, PartialEq)]
struct Identity {
    device: u64,
    inode: u64,
    mode: u32,
    uid: u32,
    gid: u32,
    links: u64,
    bytes: u64,
    modified: (i64, i64),
    changed: (i64, i64),
}

impl RootRoleExecutable {
    /// Must be called by the actual Root installer, with an absolute normalized
    /// path beneath Root-owned directories that have no group/other writes.
    /// Execution subsequently uses THIS held file, never reopens the pathname.
    pub fn open(path: &Path) -> io::Result<Self> {
        require_root()?;
        require_path(path)?;
        for ancestor in path.parent().ok_or_else(invalid)?.ancestors() {
            let metadata = std::fs::symlink_metadata(ancestor)?;
            if !metadata.is_dir() || metadata.uid() != 0 || metadata.mode() & 0o022 != 0 {
                return Err(invalid());
            }
        }
        let mut file = OpenOptions::new().read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC).open(path)?;
        let metadata = file.metadata()?;
        require_file(&metadata)?;
        let identity = Identity::from(&metadata);
        let mut bytes = Vec::with_capacity(metadata.len() as usize);
        Read::by_ref(&mut file).take(FILE_BOUND + 1).read_to_end(&mut bytes)?;
        require_elf(&bytes)?;
        if Identity::from(&file.metadata()?) != identity
            || Identity::from(&std::fs::symlink_metadata(path)?) != identity
        {
            return Err(invalid());
        }
        Ok(Self { file, identity, sha256: Digest32::of_bytes(&bytes) })
    }

    pub fn sha256(&self) -> Digest32 { self.sha256 }

    pub(super) fn for_exec(&self) -> io::Result<File> {
        require_root()?;
        let metadata = self.file.metadata()?;
        require_file(&metadata)?;
        if Identity::from(&metadata) != self.identity { return Err(invalid()); }
        // Allocate outside the fixed role FD range, before fork. No pathname
        // replacement after open can change the inode executed by the child.
        let raw = unsafe { libc::fcntl(self.file.as_raw_fd(), libc::F_DUPFD_CLOEXEC, 10) };
        if raw < 0 { return Err(io::Error::last_os_error()); }
        // SAFETY: F_DUPFD_CLOEXEC returned a fresh owned descriptor.
        Ok(unsafe { File::from_raw_fd(raw) })
    }
}

impl From<&Metadata> for Identity {
    fn from(m: &Metadata) -> Self {
        Self { device:m.dev(), inode:m.ino(), mode:m.mode(), uid:m.uid(), gid:m.gid(),
            links:m.nlink(), bytes:m.len(), modified:(m.mtime(),m.mtime_nsec()),
            changed:(m.ctime(),m.ctime_nsec()) }
    }
}

fn require_file(m: &Metadata) -> io::Result<()> {
    if !m.is_file() || m.uid() != 0 || m.nlink() != 1 || m.mode() & 0o7777 != 0o555
        || !(64..=FILE_BOUND).contains(&m.len())
    { return Err(invalid()); }
    Ok(())
}

pub(super) fn require_path(path: &Path) -> io::Result<()> {
    let text = path.to_str().ok_or_else(invalid)?;
    if !path.is_absolute() || text.len() > 4096 || text.contains('\0')
        || text.split('/').skip(1).any(|p| matches!(p, "" | "." | ".."))
        || path.components().any(|p| !matches!(p, Component::RootDir | Component::Normal(_)))
    { return Err(invalid()); }
    Ok(())
}

pub(super) fn require_root() -> io::Result<()> {
    // SAFETY: these calls read only the actual process credentials.
    if unsafe { libc::getuid() != 0 || libc::geteuid() != 0 } {
        return Err(io::Error::new(io::ErrorKind::PermissionDenied, "actual Root launcher required"));
    }
    Ok(())
}

fn invalid() -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, "installed role ELF custody or bounded layout differs")
}

// The ordinary process installer retains the existing 8MiB/16MiB shape bounds.
// ET_DYN/PT_INTERP may run as ordinary processes; this is NOT the separate G2
// static ET_EXEC/manifest/grant admission oracle.
fn require_elf(bytes: &[u8]) -> io::Result<()> {
    let u16_at = |offset| u16::from_le_bytes(bytes[offset..offset+2].try_into().unwrap());
    let u64_at = |offset| u64::from_le_bytes(bytes[offset..offset+8].try_into().unwrap());
    if !(64..=FILE_BOUND as usize).contains(&bytes.len())
        || &bytes[..7] != b"\x7fELF\x02\x01\x01"
        || !matches!(u16_at(16), 2 | 3) || u16_at(18) != 62 || u16_at(52) != 64
    { return Err(invalid()); }
    let entry = u64_at(24);
    let offset = u64_at(32);
    let count = u16_at(56) as u64;
    if u16_at(54) != 56 || !(1..=64).contains(&count)
        || offset.checked_add(count * 56).is_none_or(|end| end > bytes.len() as u64)
    { return Err(invalid()); }
    let mut loads = Vec::new();
    let mut executable_entry = false;
    for index in 0..count {
        let p = (offset + index * 56) as usize;
        let kind = u32::from_le_bytes(bytes[p..p+4].try_into().unwrap());
        let flags = u32::from_le_bytes(bytes[p+4..p+8].try_into().unwrap());
        if kind == 0x6474e551 && flags & 1 != 0 { return Err(invalid()); }
        if kind != 1 { continue; }
        let file = u64_at(p+8);
        let address = u64_at(p+16);
        let filesz = u64_at(p+32);
        let memsz = u64_at(p+40);
        let alignment = u64_at(p+48);
        let end = address.checked_add(memsz).ok_or_else(invalid)?;
        if filesz > memsz || memsz == 0 || end > (1 << 47)
            || file.checked_add(filesz).is_none_or(|end| end > bytes.len() as u64)
            || flags & 4 == 0 || flags & 3 == 3 || file % 4096 != address % 4096
            || alignment < 4096 || !alignment.is_power_of_two()
        { return Err(invalid()); }
        let pages = (address / 4096 * 4096, end.div_ceil(4096) * 4096);
        if loads.iter().any(|&(start, end)| pages.0 < end && start < pages.1) {
            return Err(invalid());
        }
        executable_entry |= flags & 1 != 0 && (address..end).contains(&entry);
        loads.push(pages);
    }
    if !(1..=16).contains(&loads.len()) || !executable_entry
        || loads.iter().map(|(a,b)| b-a).sum::<u64>() > LOAD_BOUND
    { return Err(invalid()); }
    Ok(())
}

#[cfg(test)]
#[path = "root_role_executable_tests.rs"]
mod tests;
