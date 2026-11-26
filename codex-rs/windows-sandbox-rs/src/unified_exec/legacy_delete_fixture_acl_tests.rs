//! Establish the ordinary-user access premise only on the new, empty test tree.

use super::Descriptor;
use super::Identities;
use super::MAX_BYTES;
use super::checked_sid;
use super::snapshot_handle;
use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use anyhow::ensure;
use serde_json::Value;
use serde_json::json;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::windows::fs::MetadataExt;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::ptr;
use tempfile::TempDir;
use windows_sys::Win32::Foundation::ERROR_NO_TOKEN;
use windows_sys::Win32::Security::ACL;
use windows_sys::Win32::Security::Authorization::EXPLICIT_ACCESS_W;
use windows_sys::Win32::Security::Authorization::GRANT_ACCESS;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::Authorization::SetEntriesInAclW;
use windows_sys::Win32::Security::Authorization::SetSecurityInfo;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_SID;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_USER;
use windows_sys::Win32::Security::Authorization::TRUSTEE_W;
use windows_sys::Win32::Security::CONTAINER_INHERIT_ACE;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::IsValidAcl;
use windows_sys::Win32::Security::OBJECT_INHERIT_ACE;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_DIRECTORY;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;
use windows_sys::Win32::Storage::FileSystem::WRITE_DAC;
use windows_sys::Win32::System::Threading::GetCurrentThread;
use windows_sys::Win32::System::Threading::OpenThreadToken;

const LOG_BYTES: usize = 16 * 1024;
const PREFIX: &str = "HEPTA_LEGACY_FIXTURE_ACL ";

fn aligned_words(bytes: &[u8]) -> Vec<usize> {
    let mut words = vec![0usize; bytes.len().div_ceil(size_of::<usize>())];
    // SAFETY: independent word storage is pointer-aligned, initialized and
    // large enough for every input byte. The allocations cannot overlap.
    unsafe { ptr::copy_nonoverlapping(bytes.as_ptr(), words.as_mut_ptr().cast(), bytes.len()) };
    words
}

fn sd_offset(bytes: &[u8], field: usize) -> Result<usize> {
    let value: [u8; 4] = bytes
        .get(field..field + 4)
        .context("short self-relative security descriptor")?
        .try_into()?;
    let offset = u32::from_le_bytes(value) as usize;
    ensure!(offset >= 20 && offset < bytes.len(), "invalid SD offset");
    Ok(offset)
}

fn owner_and_group(bytes: &[u8]) -> Result<[Vec<u8>; 2]> {
    let [owner, group] = [4, 8].map(|field| {
        let offset = sd_offset(bytes, field)?;
        // SAFETY: the checked offset is within the owned SD; checked_sid
        // verifies the full SID extent before calling IsValidSid.
        checked_sid(bytes, unsafe {
            bytes.as_ptr().add(offset).cast_mut().cast()
        })
    });
    Ok([owner?, group?])
}

fn dacl_bytes(bytes: &[u8]) -> Result<&[u8]> {
    let offset = sd_offset(bytes, /*field*/ 16)?;
    let header = bytes.get(offset..offset + 8).context("short DACL")?;
    let length = usize::from(u16::from_le_bytes([header[2], header[3]]));
    ensure!(length >= size_of::<ACL>(), "short ACL header");
    bytes
        .get(offset..offset + length)
        .context("DACL outside SD")
}

fn emit(value: &Value, remaining: &mut usize) -> Result<()> {
    let line = serde_json::to_string(value)?;
    let length = PREFIX.len() + line.len() + 1;
    ensure!(length <= *remaining, "fixture ACL log exceeds fixed budget");
    *remaining -= length;
    writeln!(std::io::stderr().lock(), "{PREFIX}{line}").context("write fixture ACL record")
}

pub(in super::super) fn prepare(root: &TempDir) -> Result<()> {
    let mut thread_token = 0;
    // SAFETY: query the current thread only; successful handles are owned below.
    if unsafe {
        OpenThreadToken(
            GetCurrentThread(),
            TOKEN_QUERY,
            /*openasself*/ 1,
            &mut thread_token,
        )
    } != 0
    {
        // SAFETY: the successful query returned this new handle, closed here.
        drop(unsafe { OwnedHandle::from_raw_handle(thread_token as _) });
        bail!("fixture ACL setup requires the original, non-impersonating caller");
    }
    ensure!(
        std::io::Error::last_os_error().raw_os_error() == Some(ERROR_NO_TOKEN as i32),
        "cannot establish original fixture caller"
    );
    let file = OpenOptions::new()
        .access_mode(READ_CONTROL | WRITE_DAC | FILE_READ_ATTRIBUTES)
        .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
        .open(root.path())?;
    let attributes = file.metadata()?.file_attributes();
    ensure!(
        attributes & FILE_ATTRIBUTE_DIRECTORY != 0
            && attributes & FILE_ATTRIBUTE_REPARSE_POINT == 0,
        "fixture root must be a real directory"
    );
    ensure!(
        std::fs::read_dir(root.path())?
            .next()
            .transpose()?
            .is_none(),
        "ordinary identity setup is restricted to the fresh, empty fixture"
    );
    let identities = Identities::capture()?;
    let (before, before_bytes) = snapshot_handle(&file, Some(&identities))?;
    let mut remaining = LOG_BYTES;
    emit(
        &json!({"phase":"before_owned_fixture_grant","snapshot":before}),
        &mut remaining,
    )?;
    let old_entries = before["aces"].as_array().context("missing original ACEs")?;
    ensure!(
        !before["dacl_null_pointer"]
            .as_bool()
            .context("missing DACL state")?
            && old_entries.iter().all(|entry| entry["type"] == 0),
        "fixture has a null DACL or deny/unknown ACE; no automatic ACL repair"
    );
    let original_owner_group = owner_and_group(&before_bytes)?;
    let old_dacl = dacl_bytes(&before_bytes)?;
    let old_dacl_words = aligned_words(old_dacl);
    let mut user_words = aligned_words(&identities.user);

    let entry = EXPLICIT_ACCESS_W {
        grfAccessPermissions: FILE_ALL_ACCESS,
        grfAccessMode: GRANT_ACCESS,
        grfInheritance: OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE,
        Trustee: TRUSTEE_W {
            pMultipleTrustee: ptr::null_mut(),
            MultipleTrusteeOperation: 0,
            TrusteeForm: TRUSTEE_IS_SID,
            TrusteeType: TRUSTEE_IS_USER,
            ptstrName: user_words.as_mut_ptr().cast(),
        },
    };
    let mut new_dacl = ptr::null_mut();
    // SAFETY: the verified SID and original DACL remain allocated; this adds
    // only the caller-user ACE and does not replace any production capability.
    let status = unsafe {
        SetEntriesInAclW(
            /*ccountofexplicitentries*/ 1,
            &entry,
            old_dacl_words.as_ptr().cast(),
            &mut new_dacl,
        )
    };
    ensure!(status == 0, "prepare owned fixture DACL: {status}");
    let allocation = Descriptor(new_dacl.cast());
    ensure!(
        !new_dacl.is_null() && unsafe { IsValidAcl(new_dacl) } != 0,
        "invalid fixture DACL allocation"
    );
    // SAFETY: SetEntriesInAclW returned a validated ACL allocation.
    let length = unsafe { (*new_dacl).AclSize } as usize;
    ensure!(
        (size_of::<ACL>()..=MAX_BYTES).contains(&length),
        "fixture ACL exceeds bound"
    );
    let expected = unsafe { std::slice::from_raw_parts(new_dacl.cast::<u8>(), length) }.to_vec();
    // SAFETY: this retained no-follow handle is the new empty TempDir; owner,
    // group and SACL are not written. Windows copies the valid ACL before return.
    let status = unsafe {
        SetSecurityInfo(
            file.as_raw_handle() as _,
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION,
            ptr::null_mut(),
            ptr::null_mut(),
            new_dacl,
            ptr::null(),
        )
    };
    ensure!(status == 0, "install owned fixture DACL: {status}");
    drop(allocation);
    let (after, after_bytes) = snapshot_handle(&file, Some(&identities))?;
    ensure!(
        dacl_bytes(&after_bytes)? == expected,
        "fixture DACL did not read back exactly"
    );
    ensure!(
        owner_and_group(&after_bytes)? == original_owner_group,
        "fixture owner/group changed"
    );
    ensure!(
        file.metadata()?.file_attributes() == attributes,
        "fixture attributes changed"
    );
    ensure!(
        after["aces"]
            .as_array()
            .context("missing new ACEs")?
            .iter()
            .any(|ace| ace["type"] == 0
                && ace["sid_class"] == "parent_process_user"
                && ace["mask"] == FILE_ALL_ACCESS
                && ace["flags"] == (OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE)),
        "explicit inheritable ordinary-user full-access premise missing"
    );
    emit(
        &json!({"phase":"after_owned_fixture_grant","snapshot":after,
        "same_owner_group":true,"exact_dacl_readback":true,"changed":before_bytes!=after_bytes,
        "grant_subject":"parent_process_token_user","grant_mask":FILE_ALL_ACCESS,
        "grant_inheritance":OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE,
        "scope":"fresh_owned_empty_fixture_only"}),
        &mut remaining,
    )?;
    Ok(())
}
