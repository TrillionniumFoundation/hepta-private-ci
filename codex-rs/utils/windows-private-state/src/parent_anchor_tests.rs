use super::ParentAnchor;
use crate::security::CurrentUser;
use std::error::Error;
use std::fs;
use std::fs::OpenOptions;
use std::io;
use std::os::windows::ffi::OsStrExt;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::path::Path;
use std::path::PathBuf;
use std::ptr;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::Authorization::ConvertStringSecurityDescriptorToSecurityDescriptorW;
use windows_sys::Win32::Security::Authorization::SDDL_REVISION_1;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::Authorization::SetSecurityInfo;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::GetSecurityDescriptorDacl;
use windows_sys::Win32::Security::PROTECTED_DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::CreateDirectoryW;

type Result<T = ()> = std::result::Result<T, Box<dyn Error>>;
static NEXT: AtomicU64 = AtomicU64::new(0);
struct Fixture(PathBuf);
impl Fixture {
    fn new() -> Result<Self> {
        let sequence = NEXT.fetch_add(1, Ordering::Relaxed);
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)?
            .as_nanos();
        // A real admin fixture under the actual drive root avoids assuming that
        // a shared CI TEMP parent is protected. Production still checks every ancestor.
        let mut root = PathBuf::from(std::env::var_os("SystemDrive").ok_or("missing SystemDrive")?);
        root.push(r"\");
        let path = root.join(format!(
            "hepta-anchor-{}-{nanos}-{sequence}",
            std::process::id()
        ));
        with_descriptor("", |raw| {
            let path: Vec<u16> = path.as_os_str().encode_wide().chain([0]).collect();
            let attrs = SECURITY_ATTRIBUTES {
                nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
                lpSecurityDescriptor: raw,
                bInheritHandle: 0,
            };
            // SAFETY: the private descriptor applies atomically to a fresh directory.
            if unsafe { CreateDirectoryW(path.as_ptr(), &attrs) } == 0 {
                return Err(io::Error::last_os_error().into());
            }
            Ok(())
        })?;
        Ok(Self(path))
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_file(self.0.join("state"));
        let _ = fs::remove_dir(&self.0); // only this newly created exact directory
    }
}

fn with_descriptor(
    extra_ace: &str,
    action: impl FnOnce(*mut std::ffi::c_void) -> Result,
) -> Result {
    let user = CurrentUser::capture_effective()?;
    let bytes = user.sid_bytes();
    let authority = bytes[2..8]
        .iter()
        .fold(0_u64, |value, byte| (value << 8) | u64::from(*byte));
    let mut sid = format!("S-1-{authority}");
    for sub in bytes[8..].chunks_exact(4) {
        sid.push_str(&format!("-{}", u32::from_le_bytes(sub.try_into()?)));
    }
    let text: Vec<u16> = format!("O:{sid}D:P(A;;FA;;;{sid}){extra_ace}")
        .encode_utf16()
        .chain([0])
        .collect();
    let mut raw = ptr::null_mut();
    // SAFETY: this fixture converts only its bounded descriptor text.
    if unsafe {
        ConvertStringSecurityDescriptorToSecurityDescriptorW(
            text.as_ptr(),
            SDDL_REVISION_1,
            &mut raw,
            ptr::null_mut(),
        )
    } == 0
    {
        return Err(io::Error::last_os_error().into());
    }
    let result = action(raw);
    // SAFETY: conversion transferred this LocalAlloc allocation, freed once.
    unsafe {
        LocalFree(raw);
    }
    result
}

fn set_fixture_dacl(path: &Path, extra_ace: &str) -> Result {
    with_descriptor(extra_ace, |raw| {
        let mut present = 0;
        let mut defaulted = 0;
        let mut acl = ptr::null_mut();
        // SAFETY: raw is the still-live descriptor returned by conversion.
        if unsafe { GetSecurityDescriptorDacl(raw, &mut present, &mut acl, &mut defaulted) } == 0
            || present != 1
            || acl.is_null()
        {
            return Err("fixture DACL missing".into());
        }
        let file = OpenOptions::new()
            .read(true)
            .access_mode(0x0006_0080)
            .share_mode(3)
            .custom_flags(0x0220_0000)
            .open(path)?; // query + WRITE_DAC, no DELETE
        // SAFETY: only this exact fixture directory's DACL is changed.
        let error = unsafe {
            SetSecurityInfo(
                file.as_raw_handle() as HANDLE,
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
                ptr::null_mut(),
                ptr::null_mut(),
                acl,
                ptr::null_mut(),
            )
        };
        if error != 0 {
            return Err(io::Error::from_raw_os_error(error as i32).into());
        }
        Ok(())
    })
}

#[test]
fn actual_ancestor_chain_revalidates_and_reopens_without_touching_state() -> Result {
    let fixture = Fixture::new()?;
    fs::write(fixture.0.join("state"), b"existing-marker-bytes")?;
    let mut anchor = ParentAnchor::for_create_only(&fixture.0)?;
    assert!((2..=32).contains(&anchor.ancestors.len()));
    anchor.revalidate()?;
    let replacement = fixture.0.with_extension("moved");
    assert!(fs::rename(&fixture.0, &replacement).is_err());
    assert!(!replacement.exists());
    drop(anchor);
    ParentAnchor::for_create_only(&fixture.0)?.revalidate()?;
    assert_eq!(fs::read(fixture.0.join("state"))?, b"existing-marker-bytes");
    Ok(()) // parent observation only, not owner-journal cold recovery
}

#[test]
fn actual_parent_delete_child_rights_reject_live_and_cold_anchor() -> Result {
    let fixture = Fixture::new()?;
    let mut anchor = ParentAnchor::for_create_only(&fixture.0)?;
    set_fixture_dacl(&fixture.0, "(A;;DC;;;WD)")?;
    assert!(anchor.revalidate().is_err());
    assert!(ParentAnchor::for_create_only(&fixture.0).is_err());
    set_fixture_dacl(&fixture.0, "")?;
    assert!(
        anchor.revalidate().is_err(),
        "repair cannot revive refused capability"
    );
    Ok(())
}
