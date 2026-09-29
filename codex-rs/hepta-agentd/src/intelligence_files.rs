//! Bounded reads of authority and recovery files through no-follow handles.
//! No path metadata is used as authority for a later open of another object.

use std::fs::File;
use std::io;
use std::io::Read;
use std::path::Path;

pub(crate) fn read_bounded(path: &Path, maximum: usize) -> io::Result<Vec<u8>> {
    if maximum == 0 || !path.is_absolute() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "bounded absolute file required",
        ));
    }
    let file = open_no_follow(path)?;
    read_opened_bounded(file, maximum)
}

pub(crate) fn read_opened_bounded(file: File, maximum: usize) -> io::Result<Vec<u8>> {
    if maximum == 0 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "zero read bound",
        ));
    }
    let metadata = file.metadata()?;
    if !metadata.is_file() || metadata.len() == 0 || metadata.len() > maximum as u64 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "invalid bounded regular file",
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if metadata.mode() & 0o022 != 0 || metadata.nlink() != 1 {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "unsafe file permissions or links",
            ));
        }
    }
    let mut bytes = Vec::with_capacity(usize::try_from(metadata.len()).unwrap_or(maximum));
    file.take((maximum as u64).saturating_add(1))
        .read_to_end(&mut bytes)?;
    if bytes.is_empty() || bytes.len() > maximum {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "file exceeded read bound",
        ));
    }
    Ok(bytes)
}

#[cfg(unix)]
pub(crate) fn open_directory_no_follow(path: &Path) -> io::Result<File> {
    use rustix::fs::Mode;
    use rustix::fs::OFlags;
    use std::path::Component;
    let mut parts = path.components();
    if parts.next() != Some(Component::RootDir) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "absolute directory required",
        ));
    }
    let flags = OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC;
    let mut directory = rustix::fs::open("/", flags, Mode::empty())?;
    for part in parts {
        let Component::Normal(name) = part else {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "noncanonical directory",
            ));
        };
        directory = rustix::fs::openat(&directory, name, flags, Mode::empty())?;
    }
    Ok(File::from(directory))
}

#[cfg(unix)]
fn open_no_follow(path: &Path) -> io::Result<File> {
    use rustix::fs::Mode;
    use rustix::fs::OFlags;
    use std::path::Component;

    let mut parts = path.components().peekable();
    if parts.next() != Some(Component::RootDir) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "absolute path required",
        ));
    }
    let directory_flags = OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC;
    let mut directory = rustix::fs::open("/", directory_flags, Mode::empty())?;
    while let Some(part) = parts.next() {
        let Component::Normal(name) = part else {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "noncanonical file path",
            ));
        };
        if parts.peek().is_none() {
            // NONBLOCK prevents a raced FIFO/device from blocking before fstat.
            let flags = OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::NONBLOCK | OFlags::CLOEXEC;
            return rustix::fs::openat(&directory, name, flags, Mode::empty())
                .map(File::from)
                .map_err(Into::into);
        }
        directory = rustix::fs::openat(&directory, name, directory_flags, Mode::empty())?;
    }
    Err(io::Error::new(
        io::ErrorKind::InvalidInput,
        "file name required",
    ))
}

#[cfg(not(unix))]
fn open_no_follow(_path: &Path) -> io::Result<File> {
    // A platform-specific handle/reparse-point implementation must be qualified
    // before this security profile can be advertised on that platform.
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "no-follow authority file profile unavailable",
    ))
}

/// Publish a single-link immutable object without an overwrite or hard-link
/// crash window. Every operation uses the same already-opened parent directory.
#[cfg(any(target_os = "linux", target_os = "android", target_vendor = "apple"))]
pub(crate) fn publish_immutable(
    root: &Path,
    name: &str,
    bytes: &[u8],
    maximum: usize,
) -> io::Result<()> {
    use rustix::fs::{AtFlags, Mode, OFlags, RenameFlags};
    use std::io::Write;
    use std::os::unix::fs::MetadataExt;
    use std::sync::atomic::{AtomicU64, Ordering};
    static NEXT: AtomicU64 = AtomicU64::new(0);

    if name.is_empty()
        || name.contains('/')
        || name == "."
        || name == ".."
        || bytes.is_empty()
        || bytes.len() > maximum
    {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "immutable object bound",
        ));
    }
    let directory = open_directory_no_follow(root)?;
    if directory.metadata()?.mode() & 0o077 != 0 {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "private directory required",
        ));
    }
    let nonce = NEXT
        .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |n| n.checked_add(1))
        .map_err(|_| io::Error::other("temporary object identity exhausted"))?;
    let temporary = format!("{name}.tmp-{}-{nonce}", std::process::id());
    let flags = OFlags::WRONLY
        | OFlags::CREATE
        | OFlags::EXCL
        | OFlags::NOFOLLOW
        | OFlags::NONBLOCK
        | OFlags::CLOEXEC;
    let mut file = File::from(rustix::fs::openat(
        &directory,
        temporary.as_str(),
        flags,
        Mode::from_raw_mode(0o600),
    )?);
    let result = (|| -> io::Result<()> {
        file.write_all(bytes)?;
        file.sync_all()?;
        match rustix::fs::renameat_with(
            &directory,
            temporary.as_str(),
            &directory,
            name,
            RenameFlags::NOREPLACE,
        ) {
            Ok(()) => {}
            Err(rustix::io::Errno::EXIST) => {
                let existing = File::from(rustix::fs::openat(
                    &directory,
                    name,
                    OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::NONBLOCK | OFlags::CLOEXEC,
                    Mode::empty(),
                )?);
                if read_opened_bounded(existing.try_clone()?, maximum)? != bytes {
                    return Err(io::Error::new(
                        io::ErrorKind::AlreadyExists,
                        "immutable content conflict",
                    ));
                }
                existing.sync_all()?;
                rustix::fs::unlinkat(&directory, temporary.as_str(), AtFlags::empty())?;
            }
            Err(error) => return Err(error.into()),
        }
        directory.sync_all()
    })();
    if result.is_err() {
        // Remove only our unused temporary name. Never remove the published
        // object on an ambiguous directory sync: the durable intent owns retry.
        let _ = rustix::fs::unlinkat(&directory, temporary.as_str(), AtFlags::empty());
    }
    result
}

#[cfg(not(any(target_os = "linux", target_os = "android", target_vendor = "apple")))]
pub(crate) fn publish_immutable(
    _root: &Path,
    _name: &str,
    _bytes: &[u8],
    _maximum: usize,
) -> io::Result<()> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "atomic no-replace profile unavailable",
    ))
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;
    use std::os::unix::fs::symlink;

    #[test]
    fn authority_read_rejects_parent_leaf_links_and_oversize() {
        let temporary = tempfile::tempdir().expect("directory");
        let root = temporary.path().canonicalize().expect("canonical root");
        std::fs::create_dir(root.join("real")).expect("real directory");
        let path = root.join("real/manifest");
        std::fs::write(&path, b"signed manifest").expect("write");
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))
            .expect("permissions");
        assert_eq!(
            read_bounded(&path, 32).expect("bounded read"),
            b"signed manifest"
        );
        assert!(read_bounded(&path, 2).is_err());
        symlink(root.join("real"), root.join("alias")).expect("parent link");
        assert!(read_bounded(&root.join("alias/manifest"), 32).is_err());
        symlink(&path, root.join("leaf")).expect("leaf link");
        assert!(read_bounded(&root.join("leaf"), 32).is_err());
        std::fs::hard_link(&path, root.join("hard")).expect("hard link");
        assert!(read_bounded(&path, 32).is_err());
    }

    #[test]
    #[cfg(any(target_os = "linux", target_os = "android", target_vendor = "apple"))]
    fn immutable_publication_has_one_link_and_never_replaces_existing_bytes() {
        use std::os::unix::fs::MetadataExt;
        let temporary = tempfile::tempdir().expect("directory");
        let root = temporary.path().canonicalize().expect("canonical root");
        std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700))
            .expect("private root");
        publish_immutable(&root, "event.json", b"original", 64).expect("publish");
        assert_eq!(
            std::fs::metadata(root.join("event.json"))
                .expect("metadata")
                .nlink(),
            1
        );
        publish_immutable(&root, "event.json", b"original", 64).expect("idempotent");
        assert!(publish_immutable(&root, "event.json", b"replacement", 64).is_err());
        assert_eq!(
            read_bounded(&root.join("event.json"), 64).expect("original"),
            b"original"
        );
        assert_eq!(std::fs::read_dir(&root).expect("directory").count(), 1);
        assert!(publish_immutable(&root, "../escape", b"data", 64).is_err());
        assert!(publish_immutable(&root, "large", b"oversize", 1).is_err());
    }
}
