//! DACL metadata on new File/Key handles already owned by this probe.
//! No reopen, object name, object contents, SID bytes, SACL, or ACL mutation.
use core::ffi::c_void;

use super::number;
use super::windows_probe_memory::BoundedMemory;
use super::write;
use super::GetProcAddress;

const DESCRIPTOR_BYTES: usize = 4096;

#[derive(Clone, Copy)]
pub(super) enum SelfHandleKind {
    File,
    Key,
    Other,
}

type QuerySecurity = unsafe extern "system" fn(isize, u32, *mut c_void, u32, *mut u32) -> i32;
type ValidRelative = unsafe extern "system" fn(*mut c_void, u32, u32) -> u8;
type GetDacl = unsafe extern "system" fn(*mut c_void, *mut u8, *mut *mut c_void, *mut u8) -> i32;
type GetAce = unsafe extern "system" fn(*mut c_void, u32, *mut *mut c_void) -> i32;

pub(super) fn observe(ntdll: isize, handle: isize) {
    let query = unsafe { GetProcAddress(ntdll, c"NtQuerySecurityObject".as_ptr().cast()) };
    let valid =
        unsafe { GetProcAddress(ntdll, c"RtlValidRelativeSecurityDescriptor".as_ptr().cast()) };
    let get_dacl =
        unsafe { GetProcAddress(ntdll, c"RtlGetDaclSecurityDescriptor".as_ptr().cast()) };
    let get_ace = unsafe { GetProcAddress(ntdll, c"RtlGetAce".as_ptr().cast()) };
    if query.is_null() || valid.is_null() || get_dacl.is_null() || get_ace.is_null() {
        number(b"handle_delta_dacl_exports_missing", /*value*/ 1);
        return;
    }
    // SAFETY: exact named ntdll exports, using ULONG/u8 BOOLEAN and pointer ABIs.
    let query = unsafe { core::mem::transmute::<*mut c_void, QuerySecurity>(query) };
    let valid = unsafe { core::mem::transmute::<*mut c_void, ValidRelative>(valid) };
    let get_dacl = unsafe { core::mem::transmute::<*mut c_void, GetDacl>(get_dacl) };
    let get_ace = unsafe { core::mem::transmute::<*mut c_void, GetAce>(get_ace) };
    let Some(data) = BoundedMemory::new(DESCRIPTOR_BYTES) else {
        number(b"handle_delta_dacl_complete", /*value*/ 0);
        return;
    };
    let mut returned = 0;
    let status = unsafe {
        query(
            handle,
            /*security_information: DACL_SECURITY_INFORMATION*/ 4,
            data.as_ptr(),
            DESCRIPTOR_BYTES as u32,
            &mut returned,
        )
    };
    number(b"handle_delta_dacl_query_ntstatus", status as u32);
    number(b"handle_delta_dacl_query_required_bytes", returned);
    if status < 0 || !(20..=DESCRIPTOR_BYTES).contains(&(returned as usize)) {
        number(b"handle_delta_dacl_complete", /*value*/ 0);
        return;
    }
    // Validation consumes only the initialized returned range, not guessed offsets.
    let descriptor = data.as_ptr();
    if unsafe {
        valid(descriptor, returned, /*required_information*/ 4)
    } == 0
    {
        number(b"handle_delta_dacl_descriptor_invalid", /*value*/ 1);
        number(b"handle_delta_dacl_complete", /*value*/ 0);
        return;
    }
    let mut present = 0_u8;
    let mut defaulted = 0_u8;
    let mut acl = core::ptr::null_mut();
    let status = unsafe { get_dacl(descriptor, &mut present, &mut acl, &mut defaulted) };
    number(b"handle_delta_dacl_get_ntstatus", status as u32);
    if status < 0 {
        number(b"handle_delta_dacl_complete", /*value*/ 0);
        return;
    }
    number(b"handle_delta_dacl_present", present as u32);
    if present == 0 {
        number(b"handle_delta_dacl_complete", /*value*/ 1);
        return;
    }
    number(b"handle_delta_dacl_null", acl.is_null() as u32);
    if acl.is_null() {
        number(b"handle_delta_dacl_complete", /*value*/ 1);
        return;
    }
    number(b"handle_delta_dacl_defaulted", defaulted as u32);
    let bytes =
        unsafe { core::slice::from_raw_parts(data.as_ptr().cast::<u8>(), returned as usize) };
    let Some(offset) = (acl as usize)
        .checked_sub(bytes.as_ptr() as usize)
        .filter(|n| {
            *n >= 20 && *n % 4 == 0 && n.checked_add(8).is_some_and(|end| end <= bytes.len())
        })
    else {
        number(b"handle_delta_dacl_bounds_invalid", /*value*/ 1);
        number(b"handle_delta_dacl_complete", /*value*/ 0);
        return;
    };
    // Read the fixed, validated ACL header only; RtlGetAce performs ACE traversal.
    let size = u16::from_le_bytes([bytes[offset + 2], bytes[offset + 3]]) as usize;
    let count = u16::from_le_bytes([bytes[offset + 4], bytes[offset + 5]]) as usize;
    let Some(end) = offset
        .checked_add(size)
        .filter(|end| size >= 8 && *end <= bytes.len())
    else {
        number(b"handle_delta_dacl_bounds_invalid", /*value*/ 1);
        number(b"handle_delta_dacl_complete", /*value*/ 0);
        return;
    };
    number(b"handle_delta_dacl_ace_count", count as u32);
    const ACE_REPORT_LIMIT: usize = 8;
    let mut complete = count <= ACE_REPORT_LIMIT;
    for index in 0..count.min(ACE_REPORT_LIMIT) {
        let mut ace = core::ptr::null_mut();
        let status = unsafe { get_ace(acl, index as u32, &mut ace) };
        number(b"handle_delta_dacl_ace_index", index as u32);
        if status < 0 {
            number(b"handle_delta_dacl_ace_ntstatus", status as u32);
            complete = false;
            break;
        }
        let Some(start) = (ace as usize)
            .checked_sub(bytes.as_ptr() as usize)
            .filter(|n| {
                *n >= offset + 8 && *n % 4 == 0 && n.checked_add(4).is_some_and(|v| v <= end)
            })
        else {
            number(b"handle_delta_dacl_ace_bounds_invalid", /*value*/ 1);
            complete = false;
            break;
        };
        let ace_size = u16::from_le_bytes([bytes[start + 2], bytes[start + 3]]) as usize;
        let Some(ace_end) = start
            .checked_add(ace_size)
            .filter(|v| ace_size >= 4 && *v <= end)
        else {
            number(b"handle_delta_dacl_ace_bounds_invalid", /*value*/ 1);
            complete = false;
            break;
        };
        let entry = &bytes[start..ace_end];
        number(b"handle_delta_dacl_ace_type", entry[0] as u32);
        number(b"handle_delta_dacl_ace_flags", entry[1] as u32);
        // Only standard allow/deny ACEs have the following mask/SID layout.
        if !matches!(entry[0], 0 | 1) || entry.len() < 16 {
            number(b"handle_delta_dacl_ace_uninterpreted", /*value*/ 1);
            complete = false;
            continue;
        }
        number(
            b"handle_delta_dacl_ace_mask",
            u32::from_le_bytes([entry[4], entry[5], entry[6], entry[7]]),
        );
        let sid = &entry[8..];
        let count = sid[1] as usize;
        if sid[0] != 1 || count > 15 || 8 + count * 4 > sid.len() {
            number(b"handle_delta_dacl_sid_bounds_invalid", /*value*/ 1);
            complete = false;
            continue;
        }
        // Classify only public fixed SIDs. All account/logon/capability identifiers
        // remain "other"; neither raw SID bytes nor hashes are emitted.
        let authority = &sid[2..8];
        let rid = if count > 0 {
            u32::from_le_bytes([sid[8], sid[9], sid[10], sid[11]])
        } else {
            0
        };
        let second = if count > 1 {
            u32::from_le_bytes([sid[12], sid[13], sid[14], sid[15]])
        } else {
            0
        };
        let role: &[u8] = match (authority, count, rid, second) {
            ([0, 0, 0, 0, 0, 1], 1, 0, _) => b"world",
            ([0, 0, 0, 0, 0, 3], 1, 0, _) => b"creator_owner",
            ([0, 0, 0, 0, 0, 5], 1, 11, _) => b"authenticated_users",
            ([0, 0, 0, 0, 0, 5], 1, 12, _) => b"restricted_code",
            ([0, 0, 0, 0, 0, 5], 1, 18, _) => b"local_system",
            ([0, 0, 0, 0, 0, 5], 1, 33, _) => b"write_restricted_code",
            ([0, 0, 0, 0, 0, 5], 2, 32, 544) => b"administrators",
            ([0, 0, 0, 0, 0, 5], 2, 32, 545) => b"builtin_users",
            _ => b"other",
        };
        write(b"handle_delta_dacl_ace_sid_class=");
        write(role);
        write(b"\n");
    }
    number(
        b"handle_delta_dacl_ace_report_capacity_exceeded",
        (count > ACE_REPORT_LIMIT) as u32,
    );
    number(b"handle_delta_dacl_complete", complete as u32);
}
