use std::fs;
use std::io;
use std::io::Read;
use std::io::Write;
use std::os::windows::ffi::OsStrExt;
use std::os::windows::io::AsHandle;
use std::os::windows::io::AsRawHandle;
use std::path::Path;
use std::ptr;

use pretty_assertions::assert_eq;
use windows_sys::Win32::System::IO::DeviceIoControl;
use windows_sys::Win32::System::Ioctl::FSCTL_SET_REPARSE_POINT;

use super::PrivateDirectory;
use super::snapshot_private_file;
use crate::windows_security::current_user_sid;
use crate::windows_security::owner_sid;

#[test]
fn private_state_publishes_reopens_and_retains_file_identity() -> io::Result<()> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().join("state");
    let directory = PrivateDirectory::open_or_create(&root)?;
    assert_eq!(
        owner_sid(directory.as_file().as_handle())?,
        current_user_sid()?
    );
    assert_eq!(
        directory
            .open_write_existing("state.json")
            .unwrap_err()
            .kind(),
        io::ErrorKind::NotFound
    );
    assert!(!directory.entry_exists("state.json")?);
    let mut file = directory.create_new("state.next")?;
    file.write_all(b"first durable state")?;
    file.sync_all()?;
    let before = snapshot_private_file(&file)?;
    directory.replace("state.next", "state.json")?;
    directory.sync_all()?;
    let after = snapshot_private_file(&directory.open_read("state.json")?)?;
    assert!(before.same_file(&after));
    assert!(!directory.entry_exists("state.next")?);
    assert_eq!(after.len(), 19);
    drop(file);
    drop(directory);

    let reopened = PrivateDirectory::open_existing(&root)?;
    let mut contents = String::new();
    reopened
        .open_read("state.json")?
        .read_to_string(&mut contents)?;
    assert_eq!(contents, "first durable state");
    let mut next = reopened.create_new("state.next")?;
    next.write_all(b"second durable state")?;
    next.sync_all()?;
    reopened.replace("state.next", "state.json")?;
    reopened.sync_all()?;
    assert_eq!(fs::read(root.join("state.json"))?, b"second durable state");
    Ok(())
}

#[test]
fn retained_parent_does_not_follow_a_replacement_path() -> io::Result<()> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().join("state");
    let moved = temp.path().join("retained");
    let directory = PrivateDirectory::open_or_create(&root)?;
    fs::rename(&root, &moved)?;
    let replacement = PrivateDirectory::open_or_create(&root)?;
    let mut file = directory.create_new("state.next")?;
    file.write_all(b"retained directory")?;
    file.sync_all()?;
    directory.replace("state.next", "state.json")?;
    directory.sync_all()?;
    assert_eq!(fs::read(moved.join("state.json"))?, b"retained directory");
    assert!(!replacement.entry_exists("state.json")?);
    Ok(())
}

#[test]
fn hardlinked_state_is_rejected_without_changing_contents() -> io::Result<()> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().join("state");
    let directory = PrivateDirectory::open_or_create(&root)?;
    let mut file = directory.create_new("state.json")?;
    file.write_all(b"unchanged")?;
    file.sync_all()?;
    fs::hard_link(root.join("state.json"), temp.path().join("second-link"))?;
    assert_eq!(
        directory.open_read("state.json").unwrap_err().kind(),
        io::ErrorKind::PermissionDenied
    );
    assert_eq!(
        directory.open_write("state.json").unwrap_err().kind(),
        io::ErrorKind::PermissionDenied
    );
    assert_eq!(fs::read(root.join("state.json"))?, b"unchanged");
    Ok(())
}

#[test]
fn entry_names_cannot_escape_the_retained_directory() -> io::Result<()> {
    let temp = tempfile::tempdir()?;
    let directory = PrivateDirectory::open_or_create(&temp.path().join("state"))?;
    for name in [
        "",
        ".",
        "..",
        "../other",
        "..\\other",
        "state:stream",
        "a\0b",
    ] {
        assert_eq!(
            directory.create_new(name).unwrap_err().kind(),
            io::ErrorKind::InvalidInput
        );
    }
    assert_eq!(fs::read_dir(temp.path().join("state"))?.count(), 0);
    Ok(())
}

#[test]
fn directory_reparse_points_are_rejected_in_every_resolved_component() -> io::Result<()> {
    let temp = tempfile::tempdir()?;
    let target = temp.path().join("target");
    fs::create_dir(&target)?;
    let junction = temp.path().join("junction");
    create_junction(&junction, &target)?;
    assert!(PrivateDirectory::open_existing(&junction).is_err());
    assert!(PrivateDirectory::open_or_create(&junction.join("state")).is_err());
    assert!(!target.join("state").exists());
    Ok(())
}

// Mount-point fixtures need no symlink privilege and never address another
// user's path. The payload is the documented REPARSE_DATA_BUFFER mount-point
// layout, set only on a newly created empty directory within this test TempDir.
fn create_junction(link: &Path, target: &Path) -> io::Result<()> {
    let directory = PrivateDirectory::open_or_create(link)?;
    let target = target.canonicalize()?;
    let target: Vec<u16> = target.as_os_str().encode_wide().collect();
    let verbatim: Vec<u16> = "\\\\?\\".encode_utf16().collect();
    let target = target.strip_prefix(verbatim.as_slice()).ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            "junction fixture requires a disk path",
        )
    })?;
    let substitute: Vec<u16> = "\\??\\"
        .encode_utf16()
        .chain(target.iter().copied())
        .collect();
    let substitute_length = u16::try_from(substitute.len() * 2)
        .map_err(|_| io::Error::other("fixture path is too long"))?;
    let print_length = u16::try_from(target.len() * 2)
        .map_err(|_| io::Error::other("fixture path is too long"))?;
    let payload_length = 8 + substitute_length + 2 + print_length + 2;
    let mut bytes = Vec::new();
    bytes.extend_from_slice(&0xA000_0003_u32.to_le_bytes());
    bytes.extend_from_slice(&payload_length.to_le_bytes());
    bytes.extend_from_slice(&0_u16.to_le_bytes());
    for value in [0, substitute_length, substitute_length + 2, print_length] {
        bytes.extend_from_slice(&value.to_le_bytes());
    }
    for unit in substitute
        .iter()
        .chain([0].iter())
        .chain(target)
        .chain([0].iter())
    {
        bytes.extend_from_slice(&unit.to_le_bytes());
    }
    let mut aligned = vec![0_u32; bytes.len().div_ceil(4)];
    let mut returned = 0;
    // SAFETY: the aligned allocation contains the complete initialized input;
    // the synchronous call uses the retained empty-directory handle and no
    // output payload. Both buffers and the output count outlive the call.
    unsafe {
        ptr::copy_nonoverlapping(bytes.as_ptr(), aligned.as_mut_ptr().cast(), bytes.len());
        if DeviceIoControl(
            directory.as_file().as_raw_handle(),
            FSCTL_SET_REPARSE_POINT,
            aligned.as_ptr().cast(),
            u32::try_from(bytes.len()).map_err(io::Error::other)?,
            ptr::null_mut(),
            /*noutbuffersize*/ 0,
            &mut returned,
            ptr::null_mut(),
        ) == 0
        {
            return Err(io::Error::last_os_error());
        }
    }
    Ok(())
}
