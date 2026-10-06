//! Diagnostic-only Windows handle identity experiment, never a recovery backend.
//! Run with rustc --edition=2024 --test; no product API or security setting changes.
#![cfg(windows)]
#![deny(warnings)]

use std::ffi::c_void;
use std::io;
use std::mem::size_of;
use std::os::windows::ffi::OsStrExt;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::{AsRawHandle, FromRawHandle, OwnedHandle};
use std::path::{Component, Path, PathBuf, Prefix};

const READ_ATTRIBUTES: u32 = 0x80;
const SHARE_ALL: u32 = 7;
const OPEN_EXISTING: u32 = 3;
const BACKUP_SEMANTICS: u32 = 0x0200_0000;
const OPEN_REPARSE_POINT: u32 = 0x0020_0000;
const REPARSE_POINT: u32 = 0x400;
const DIRECTORY: u32 = 0x10;

#[link(name = "kernel32")]
unsafe extern "system" {
    fn CreateFileW(
        name: *const u16,
        access: u32,
        share: u32,
        security: *const c_void,
        disposition: u32,
        flags: u32,
        template: *mut c_void,
    ) -> *mut c_void;
    fn GetFileInformationByHandleEx(
        handle: *mut c_void,
        class: i32,
        information: *mut c_void,
        size: u32,
    ) -> i32;
    fn GetFileType(handle: *mut c_void) -> u32;
    fn GetDriveTypeW(root: *const u16) -> u32;
    fn GetCurrentProcess() -> *mut c_void;
    fn GetProcessHandleCount(process: *mut c_void, count: *mut u32) -> i32;
}

#[repr(C)]
#[derive(Default)]
struct FileIdInfo {
    volume: u64,
    id: [u8; 16],
}
#[repr(C)]
#[derive(Default)]
struct AttributeTagInfo {
    attributes: u32,
    tag: u32,
}
#[repr(C)]
#[derive(Default)]
struct StandardInfo {
    allocation: i64,
    end: i64,
    links: u32,
    delete_pending: u8,
    directory: u8,
}
#[repr(C)]
#[derive(Default)]
struct BasicInfo {
    created: i64,
    accessed: i64,
    written: i64,
    changed: i64,
    attributes: u32,
}

fn invalid(message: &'static str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message)
}

fn wide(path: &Path) -> io::Result<Vec<u16>> {
    let mut value: Vec<u16> = path.as_os_str().encode_wide().collect();
    if value.is_empty() || value.len() >= 32767 || value.contains(&0) {
        return Err(invalid("invalid or oversized Windows path"));
    }
    value.push(0);
    Ok(value)
}

/// Only lexical absolute drive paths; no UNC, verbatim/device path, ADS or dot components.
fn ancestors(path: &Path) -> io::Result<Vec<PathBuf>> {
    let raw: Vec<u16> = path.as_os_str().encode_wide().collect();
    if raw.len() < 4
        || raw[1] != u16::from(b':')
        || raw[2] != u16::from(b'\\')
        || !matches!(raw[0], 65..=90 | 97..=122)
        || raw[2..].contains(&u16::from(b':'))
        || raw.contains(&u16::from(b'/'))
        || raw.contains(&0)
    {
        return Err(invalid(
            "only absolute local drive paths without streams are accepted",
        ));
    }
    // Components normalizes '.', so reject it before parsing.
    for part in raw[3..].split(|unit| *unit == u16::from(b'\\')) {
        if part.is_empty()
            || part == [46]
            || part == [46, 46]
            || matches!(part.last(), Some(32 | 46))
        {
            return Err(invalid("ambiguous Windows path component"));
        }
    }
    let mut components = path.components();
    if !matches!(components.next(), Some(Component::Prefix(p)) if matches!(p.kind(), Prefix::Disk(_)))
        || !matches!(components.next(), Some(Component::RootDir))
        || !components.all(|part| matches!(part, Component::Normal(_)))
    {
        return Err(invalid("unsupported Windows path namespace"));
    }
    let mut chain: Vec<PathBuf> = path.ancestors().map(Path::to_path_buf).collect();
    chain.reverse();
    if chain.len() < 2 || chain.len() > 64 {
        return Err(invalid("ancestor count outside diagnostic bound"));
    }
    let root = wide(&chain[0])?;
    // SAFETY: NUL-terminated root lives across this call; no ownership transfer.
    if unsafe { GetDriveTypeW(root.as_ptr()) } != 3 {
        return Err(invalid("only local fixed drives are admitted"));
    }
    Ok(chain)
}

fn open_attributes(path: &Path) -> io::Result<OwnedHandle> {
    let name = wide(path)?;
    // SAFETY: stable terminated UTF-16; null security/template; no create/write flags.
    let raw = unsafe {
        CreateFileW(
            name.as_ptr(),
            READ_ATTRIBUTES,
            SHARE_ALL,
            std::ptr::null(),
            OPEN_EXISTING,
            BACKUP_SEMANTICS | OPEN_REPARSE_POINT,
            std::ptr::null_mut(),
        )
    };
    if raw == (-1_isize) as *mut c_void || raw.is_null() {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: successful CreateFile returns one uniquely owned handle.
    Ok(unsafe { OwnedHandle::from_raw_handle(raw) })
}

/// The caller chooses a concrete documented information class/struct pair.
unsafe fn information<T: Default>(handle: &OwnedHandle, class: i32) -> io::Result<T> {
    let mut result = T::default();
    // SAFETY: caller pairs class with T; writable initialized storage of exact size.
    if unsafe {
        GetFileInformationByHandleEx(
            handle.as_raw_handle(),
            class,
            (&mut result as *mut T).cast(),
            size_of::<T>() as u32,
        )
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    Ok(result)
}

#[derive(Debug, PartialEq, Eq)]
struct Snapshot {
    volume: u64,
    id: [u8; 16],
    attributes: u32,
    links: u32,
    length: i64,
    created: i64,
    written: i64,
    changed: i64,
}

fn snapshot(handle: &OwnedHandle, directory: bool) -> io::Result<Snapshot> {
    // SAFETY: borrowed live handle; each class below matches its repr(C) structure.
    if unsafe { GetFileType(handle.as_raw_handle()) } != 1 {
        return Err(invalid("not a disk file handle"));
    }
    let id: FileIdInfo = unsafe { information(handle, 18)? };
    let tag: AttributeTagInfo = unsafe { information(handle, 9)? };
    let standard: StandardInfo = unsafe { information(handle, 1)? };
    let basic: BasicInfo = unsafe { information(handle, 0)? };
    if id.id == [0; 16]
        || tag.attributes & REPARSE_POINT != 0
        || tag.tag != 0
        || (tag.attributes & DIRECTORY != 0) != directory
        || (standard.directory != 0) != directory
        || standard.delete_pending != 0
        || (!directory && standard.links != 1)
        || standard.end < 0
        || basic.attributes != tag.attributes
    {
        return Err(invalid("unsupported, linked, reparse or wrong-kind object"));
    }
    Ok(Snapshot {
        volume: id.volume,
        id: id.id,
        attributes: tag.attributes,
        links: standard.links,
        length: standard.end,
        created: basic.created,
        written: basic.written,
        changed: basic.changed,
    })
}

impl Snapshot {
    fn matches(&self, other: &Self, directory: bool) -> bool {
        if directory {
            // Ancestors provide identity, not a directory-content or privacy witness.
            self.volume == other.volume
                && self.id == other.id
                && self.attributes & (DIRECTORY | REPARSE_POINT)
                    == other.attributes & (DIRECTORY | REPARSE_POINT)
        } else {
            self == other
        }
    }
}

struct Object {
    path: PathBuf,
    handle: OwnedHandle,
    initial: Snapshot,
    directory: bool,
}
struct Inspection {
    chain: Vec<Object>,
}

impl Inspection {
    fn bind(path: &Path) -> io::Result<Self> {
        let paths = ancestors(path)?;
        let count = paths.len();
        let mut chain = Vec::with_capacity(count);
        for (index, path) in paths.into_iter().enumerate() {
            let directory = index + 1 != count;
            let handle = open_attributes(&path)?;
            let initial = snapshot(&handle, directory)?;
            chain.push(Object {
                path,
                handle,
                initial,
                directory,
            });
        }
        let result = Self { chain };
        result.verify()?;
        Ok(result)
    }

    fn verify(&self) -> io::Result<()> {
        for object in &self.chain {
            let current_path = open_attributes(&object.path)?;
            if !object.initial.matches(
                &snapshot(&object.handle, object.directory)?,
                object.directory,
            ) || !object.initial.matches(
                &snapshot(&current_path, object.directory)?,
                object.directory,
            ) {
                return Err(invalid("retained object or path identity drift"));
            }
        }
        Ok(())
    }
}

// This checks persistent ancestor replacement. It is NOT an atomic parent-relative
// traversal: replacement and restoration entirely between checks may escape it.
// No ACL privacy proof, coherent byte image, public recovery guard or writer follows.

struct Fixture {
    root: PathBuf,
    file: PathBuf,
}
impl Fixture {
    fn new() -> io::Result<Self> {
        use std::sync::atomic::{AtomicU64, Ordering};
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(io::Error::other)?
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "hepta-inspection-{}-{stamp}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir(&root)?;
        let file = root.join("database.sqlite3");
        std::fs::write(&file, b"fixture-only-bytes")?;
        Ok(Self { root, file })
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

#[test]
fn stable_identity_and_unchanged_bytes() -> io::Result<()> {
    let f = Fixture::new()?;
    let before = std::fs::read(&f.file)?;
    let guard = Inspection::bind(&f.file)?;
    guard.verify()?;
    assert_eq!(std::fs::read(&f.file)?, before);
    Ok(())
}

#[test]
fn equal_length_path_replacement_is_rejected() -> io::Result<()> {
    let f = Fixture::new()?;
    let guard = Inspection::bind(&f.file)?;
    std::fs::rename(&f.file, f.root.join("original"))?;
    std::fs::write(&f.file, b"fixture-only-bytes")?;
    assert!(guard.verify().is_err());
    Ok(())
}

#[test]
fn length_drift_and_hardlink_inputs_are_rejected() -> io::Result<()> {
    let f = Fixture::new()?;
    let guard = Inspection::bind(&f.file)?;
    std::fs::write(&f.file, b"longer fixture mutation for negative control")?;
    assert!(guard.verify().is_err());
    drop(guard);
    std::fs::hard_link(&f.file, f.root.join("alias"))?;
    assert!(Inspection::bind(&f.file).is_err());
    Ok(())
}

#[test]
fn persistent_parent_replacement_is_rejected() -> io::Result<()> {
    let f = Fixture::new()?;
    let parent = f.root.join("parent");
    std::fs::create_dir(&parent)?;
    let file = parent.join("db");
    std::fs::write(&file, b"same")?;
    let guard = Inspection::bind(&file)?;
    std::fs::rename(&parent, f.root.join("old-parent"))?;
    std::fs::create_dir(&parent)?;
    std::fs::write(&file, b"same")?;
    assert!(guard.verify().is_err());
    Ok(())
}

#[test]
fn reparse_input_is_rejected_or_probe_explicitly_fails() -> io::Result<()> {
    let f = Fixture::new()?;
    let link = f.root.join("link");
    // No privilege enabling. Failure is a real failed probe, never a skipped pass.
    std::os::windows::fs::symlink_file(&f.file, &link)?;
    assert!(Inspection::bind(&link).is_err());
    Ok(())
}

#[test]
fn namespaces_directories_are_rejected_without_claiming_writer_exclusion() -> io::Result<()> {
    for path in [
        r"\\server\share\db",
        r"\\?\C:\db",
        r"C:\db:stream",
        r"C:\a\..\db",
        r"C:\a.\db",
    ] {
        assert!(ancestors(Path::new(path)).is_err());
    }
    let f = Fixture::new()?;
    assert!(Inspection::bind(&f.root).is_err());
    let held = std::fs::OpenOptions::new()
        .read(true)
        .share_mode(0)
        .open(&f.file)?;
    // READ_ATTRIBUTES is exempt from share-mode exclusion; this is no writer fence.
    Inspection::bind(&f.file)?.verify()?;
    drop(held);
    Inspection::bind(&f.file)?.verify()?;
    Ok(())
}

fn handle_count() -> io::Result<u32> {
    let mut count = 0;
    // SAFETY: pseudo-handle needs no close; pointer targets initialized writable u32.
    if unsafe { GetProcessHandleCount(GetCurrentProcess(), &mut count) } == 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(count)
}

#[test]
fn success_and_partial_failure_release_handles() -> io::Result<()> {
    let f = Fixture::new()?;
    drop(Inspection::bind(&f.file)?); // warm up before observing the count
    let before = handle_count()?;
    for _ in 0..32 {
        drop(Inspection::bind(&f.file)?);
        assert!(Inspection::bind(&f.root.join("missing")).is_err());
    }
    assert_eq!(handle_count()?, before);
    Ok(())
}

#[test]
fn unsupported_information_class_returns_error_without_fallback() -> io::Result<()> {
    let f = Fixture::new()?;
    let handle = open_attributes(&f.file)?;
    // SAFETY: an invalid class must fail; storage is valid and sufficiently sized.
    let result: io::Result<FileIdInfo> = unsafe { information(&handle, -1) };
    assert!(result.is_err());
    Ok(())
}

#[test]
fn unrelated_sibling_changes_do_not_change_ancestor_identity() -> io::Result<()> {
    let f = Fixture::new()?;
    let guard = Inspection::bind(&f.file)?;
    let sibling = f.root.join("unrelated");
    std::fs::write(&sibling, b"unrelated sibling content")?;
    guard.verify()?;
    std::fs::rename(&sibling, f.root.join("unrelated-renamed"))?;
    guard.verify()?;
    assert_eq!(std::fs::read(&f.file)?, b"fixture-only-bytes");
    Ok(())
}
