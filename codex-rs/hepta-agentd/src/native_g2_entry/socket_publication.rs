//! Publish a native role socket only after its original permissions are ready.
use std::ffi::CStr;
use std::ffi::CString;
use std::ffi::OsString;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::mem::MaybeUninit;
use std::ops::Deref;
use std::os::fd::AsRawFd;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixListener;
use std::path::Path;

/// The filesystem name belongs to this retained listener inode alone.
pub(super) struct PublishedListener {
    // Remove the matching name before closing the listener that retains it.
    _name: SocketName,
    listener: UnixListener,
}

impl Deref for PublishedListener {
    type Target = UnixListener;

    fn deref(&self) -> &Self::Target {
        &self.listener
    }
}

struct SocketName {
    directory: File,
    name: CString,
    device: libc::dev_t,
    inode: libc::ino_t,
}

impl SocketName {
    fn matches(&self, metadata: &libc::stat) -> bool {
        metadata.st_dev == self.device
            && metadata.st_ino == self.inode
            && metadata.st_uid == 0
            && metadata.st_mode & libc::S_IFMT == libc::S_IFSOCK
    }

    fn configured(&self, gid: u32) -> io::Result<()> {
        let metadata = metadata_at(&self.directory, &self.name)?;
        if !self.matches(&metadata) || metadata.st_gid != gid || metadata.st_mode & 0o7777 != 0o660
        {
            return Err(io::Error::other("native socket ownership changed"));
        }
        Ok(())
    }

    fn publish(mut self, final_name: CString, gid: u32) -> io::Result<Self> {
        self.configured(gid)?;
        // SAFETY: both names are live NUL-terminated basenames under the same
        // retained Root-controlled directory. NOREPLACE is mandatory; no
        // fallback may overwrite a pre-existing endpoint.
        if unsafe {
            libc::syscall(
                libc::SYS_renameat2,
                self.directory.as_raw_fd(),
                self.name.as_ptr(),
                self.directory.as_raw_fd(),
                final_name.as_ptr(),
                libc::RENAME_NOREPLACE,
            )
        } != 0
        {
            return Err(io::Error::last_os_error());
        }
        match metadata_at(&self.directory, &self.name) {
            Err(error) if error.raw_os_error() == Some(libc::ENOENT) => {}
            // Some kernels return success for a pre-existing same-inode alias.
            // Keep final untouched and clean only our pending name in that case.
            Ok(_) => return Err(io::Error::other("native socket name was not moved")),
            Err(error) => return Err(error),
        }
        self.name = final_name;
        self.configured(gid)?;
        Ok(self)
    }
}

impl Drop for SocketName {
    fn drop(&mut self) {
        if metadata_at(&self.directory, &self.name).is_ok_and(|metadata| self.matches(&metadata)) {
            // SAFETY: this is the same socket filesystem inode created by this
            // listener, in its held Root-only-writable directory. A collision
            // or a replacement inode never enters this unlink path.
            unsafe {
                libc::unlinkat(self.directory.as_raw_fd(), self.name.as_ptr(), 0);
            }
        }
    }
}

pub(super) fn listener(path: &Path, gid: u32) -> io::Result<PublishedListener> {
    let parent = path
        .parent()
        .ok_or_else(|| io::Error::other("native socket parent absent"))?;
    verify_root_ancestry(parent)?;
    let directory = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(parent)?;
    let directory_metadata = directory.metadata()?;
    if !directory_metadata.is_dir()
        || directory_metadata.uid() != 0
        || directory_metadata.mode() & 0o022 != 0
    {
        return Err(io::Error::other("native socket parent changed"));
    }
    let file_name = path
        .file_name()
        .ok_or_else(|| io::Error::other("native socket name absent"))?;
    let final_name = CString::new(file_name.as_encoded_bytes()).map_err(io::Error::other)?;
    let mut pending_name = OsString::from(".");
    pending_name.push(file_name);
    pending_name.push(".pending");
    let pending = parent.join(&pending_name);
    // The Linux ABI includes the terminating NUL in sun_path's 108 bytes.
    if pending.as_os_str().as_encoded_bytes().len() >= 108 {
        return Err(io::Error::other("native pending socket path is too long"));
    }
    let pending_name = CString::new(pending_name.as_encoded_bytes()).map_err(io::Error::other)?;
    // Never pre-unlink a colliding pending name, even after a failed prior run.
    let listener = UnixListener::bind(&pending)?;
    let metadata = metadata_at(&directory, &pending_name)?;
    if metadata.st_uid != 0 || metadata.st_mode & libc::S_IFMT != libc::S_IFSOCK {
        return Err(io::Error::other("new native socket identity unavailable"));
    }
    let name = SocketName {
        directory,
        name: pending_name,
        device: metadata.st_dev,
        inode: metadata.st_ino,
    };
    owner_socket(&pending, gid)?;
    listener.set_nonblocking(true)?;
    let name = name.publish(final_name, gid)?;
    Ok(PublishedListener {
        _name: name,
        listener,
    })
}

fn metadata_at(directory: &File, name: &CStr) -> io::Result<libc::stat> {
    let mut metadata = MaybeUninit::uninit();
    // SAFETY: fstatat writes the exact stat object only on success, without
    // following the retained basename if it was replaced by a symlink.
    if unsafe {
        libc::fstatat(
            directory.as_raw_fd(),
            name.as_ptr(),
            metadata.as_mut_ptr(),
            libc::AT_SYMLINK_NOFOLLOW,
        )
    } != 0
    {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: successful fstatat initialized the whole stat object above.
    Ok(unsafe { metadata.assume_init() })
}

pub(super) fn verify_root_ancestry(path: &Path) -> io::Result<()> {
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

fn owner_socket(path: &Path, gid: u32) -> io::Result<()> {
    let name = CString::new(path.as_os_str().as_encoded_bytes()).map_err(io::Error::other)?;
    // SAFETY: the newly bound socket name is a retained fixed native path.
    if unsafe { libc::chown(name.as_ptr(), 0, gid) } != 0 {
        return Err(io::Error::last_os_error());
    }
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o660))
}

#[cfg(test)]
#[path = "socket_publication_tests.rs"]
mod tests;
