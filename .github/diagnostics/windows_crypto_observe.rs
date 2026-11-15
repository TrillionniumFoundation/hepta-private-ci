//! Bounded metadata from this probe only; no memory, names, or other processes.
use core::ffi::c_void;

use super::number;
use super::write;
use super::GetProcAddress;

#[link(name = "kernel32")]
unsafe extern "system" {
    fn GetCurrentProcess() -> isize;
    fn CloseHandle(handle: isize) -> i32;
    fn PssCaptureSnapshot(process: isize, flags: u32, context: u32, out: *mut isize) -> u32;
    fn PssFreeSnapshot(process: isize, snapshot: isize) -> u32;
    fn PssWalkMarkerCreate(allocator: *const c_void, out: *mut isize) -> u32;
    fn PssWalkMarkerFree(marker: isize) -> u32;
    fn PssWalkSnapshot(
        snapshot: isize,
        kind: u32,
        marker: isize,
        out: *mut c_void,
        len: u32,
    ) -> u32;
}

// PSS_HANDLE_ENTRY from processsnapshot.h. The omitted union members are all
// smaller than Thread on AMD64, the only target accepted by the probe builder.
#[repr(C)]
struct HandleEntry {
    handle: isize,
    flags: u32,
    object_type: u32,
    capture_time: [u32; 2],
    attributes: u32,
    granted_access: u32,
    handle_count: u32,
    pointer_count: u32,
    paged_pool_charge: u32,
    non_paged_pool_charge: u32,
    creation_time: [u32; 2],
    type_name_length: u16,
    type_name: *const u16,
    object_name_length: u16,
    object_name: *const u16,
    type_information: ThreadInformation,
}

#[repr(C)]
struct ThreadInformation {
    exit_status: u32,
    teb: *mut c_void,
    process_id: u32,
    thread_id: u32,
    affinity: usize,
    priority: i32,
    base_priority: i32,
    start_address: *mut c_void,
}

// Keep the raw FFI layout explicit; the builder accepts AMD64 PE files only.
const _: () = {
    assert!(core::mem::size_of::<HandleEntry>() == 136);
    assert!(core::mem::offset_of!(HandleEntry, granted_access) == 28);
    assert!(core::mem::offset_of!(HandleEntry, type_name) == 64);
    assert!(core::mem::offset_of!(HandleEntry, type_information) == 88);
};

type Query = unsafe extern "system" fn(isize, u32, *mut c_void, u32, *mut u32) -> i32;
type OpenToken = unsafe extern "system" fn(isize, u32, *mut isize) -> i32;

pub(super) fn token_metadata(ntdll: isize) {
    let open = unsafe { GetProcAddress(ntdll, c"NtOpenProcessToken".as_ptr().cast()) };
    let query = unsafe { GetProcAddress(ntdll, c"NtQueryInformationToken".as_ptr().cast()) };
    if open.is_null() || query.is_null() {
        number(b"self_token_exports_missing", /*value*/ 1);
        return;
    }
    // SAFETY: these named ntdll exports have the documented NT token ABIs.
    let open = unsafe { core::mem::transmute::<*mut c_void, OpenToken>(open) };
    let query = unsafe { core::mem::transmute::<*mut c_void, Query>(query) };
    let mut token = 0;
    let status = unsafe {
        open(
            GetCurrentProcess(),
            /*desired_access: TOKEN_QUERY*/ 8,
            &mut token,
        )
    };
    number(b"self_token_open_ntstatus", status as u32);
    if status < 0 {
        return;
    }
    let mut label = [0_usize; 32];
    let mut returned = 0;
    let status = unsafe {
        query(
            token,
            /*kind: TokenIntegrityLevel*/ 25,
            label.as_mut_ptr().cast(),
            core::mem::size_of_val(&label) as u32,
            &mut returned,
        )
    };
    number(b"self_integrity_query_ntstatus", status as u32);
    if status >= 0 && returned as usize <= core::mem::size_of_val(&label) {
        // The SID_AND_ATTRIBUTES prefix points into this same returned buffer.
        let offset = label[0].checked_sub(label.as_ptr() as usize);
        let valid = offset
            .filter(|offset| *offset >= 2 * core::mem::size_of::<usize>())
            .filter(|offset| {
                offset
                    .checked_add(12)
                    .is_some_and(|end| end <= returned as usize)
            });
        if let Some(offset) = valid {
            let bytes =
                unsafe { core::slice::from_raw_parts(label.as_ptr().cast::<u8>().add(offset), 12) };
            if bytes[..8] == [1, 1, 0, 0, 0, 0, 0, 16] {
                number(
                    b"self_integrity_rid",
                    u32::from_le_bytes([bytes[8], bytes[9], bytes[10], bytes[11]]),
                );
            } else {
                number(b"self_integrity_label_invalid", /*value*/ 1);
            }
        } else {
            number(b"self_integrity_label_invalid", /*value*/ 1);
        }
    }
    let mut policy = 0_u32;
    let status = unsafe {
        query(
            token,
            /*kind: TokenMandatoryPolicy*/ 27,
            (&mut policy as *mut u32).cast(),
            4,
            &mut returned,
        )
    };
    number(b"self_mandatory_query_ntstatus", status as u32);
    if status >= 0 && returned == 4 {
        number(b"self_mandatory_policy", policy);
    }
    number(
        b"self_token_close_ok",
        (unsafe { CloseHandle(token) } != 0) as u32,
    );
}

#[derive(Clone, Copy, PartialEq, Eq)]
struct HandleKey {
    handle: isize,
    object_type: u32,
    access: u32,
    attributes: u32,
    basic_available: bool,
}

const EMPTY: HandleKey = HandleKey {
    handle: 0,
    object_type: 0,
    access: 0,
    attributes: 0,
    basic_available: false,
};
const HANDLE_LIMIT: usize = 64;
const REPORT_LIMIT: usize = 24;
const QUERY_REPORT_LIMIT: usize = 8;

pub(super) struct Handles {
    entries: [HandleKey; HANDLE_LIMIT],
    len: usize,
    complete: bool,
    missing_basic: usize,
}

impl Handles {
    pub(super) fn capture(before: Option<&Self>, ntdll: isize) -> Self {
        let mut result = Self {
            entries: [EMPTY; HANDLE_LIMIT],
            len: 0,
            complete: false,
            missing_basic: 0,
        };
        let mut snapshot = 0;
        // PSS_CAPTURE_HANDLES | PSS_CAPTURE_HANDLE_BASIC_INFORMATION only:
        // no names, threads, virtual-memory clone, contexts, traces, or remote PID.
        let status = unsafe { PssCaptureSnapshot(GetCurrentProcess(), 0x14, 0, &mut snapshot) };
        number(b"self_handles_capture_error", status);
        if status != 0 {
            return result;
        }
        let mut marker = 0;
        let status = unsafe { PssWalkMarkerCreate(core::ptr::null(), &mut marker) };
        number(b"self_handles_marker_error", status);
        if status == 0 {
            let query = unsafe { GetProcAddress(ntdll, c"NtQueryObject".as_ptr().cast()) };
            let mut differences = 0;
            let mut fallback_count = 0;
            loop {
                // All fields, including unused union storage, start initialized.
                let mut entry: HandleEntry = unsafe { core::mem::zeroed() };
                let status = unsafe {
                    PssWalkSnapshot(
                        snapshot,
                        /*kind: PSS_WALK_HANDLES*/ 2,
                        marker,
                        (&mut entry as *mut HandleEntry).cast(),
                        core::mem::size_of::<HandleEntry>() as u32,
                    )
                };
                if status == 259 {
                    result.complete = true;
                    break;
                }
                if status != 0 {
                    number(b"self_handles_walk_error", status);
                    break;
                }
                if result.len == HANDLE_LIMIT {
                    number(b"self_handles_capacity_exceeded", /*value*/ 1);
                    break;
                }
                // A successful walk can return a handle without basic metadata.
                // Keep walking, and query only that self-captured handle. A failed
                // query remains unknown; it must not become a zero-rights result.
                if entry.flags & 4 == 0 {
                    fallback_count += 1;
                    if !query.is_null() && entry.handle > 0 {
                        // PUBLIC_OBJECT_BASIC_INFORMATION: four public ULONGs
                        // followed by ten reserved ULONGs. No object content/name.
                        let mut basic = [0_u32; 14];
                        let mut returned = 0;
                        let query = unsafe { core::mem::transmute::<*mut c_void, Query>(query) };
                        let status = unsafe {
                            query(
                                entry.handle,
                                /*kind: ObjectBasicInformation*/ 0,
                                basic.as_mut_ptr().cast(),
                                core::mem::size_of_val(&basic) as u32,
                                &mut returned,
                            )
                        };
                        if fallback_count <= QUERY_REPORT_LIMIT {
                            number(b"self_handles_basic_query_ntstatus", status as u32);
                            number(b"self_handles_basic_query_returned", returned);
                        }
                        if status >= 0 && returned as usize == core::mem::size_of_val(&basic) {
                            entry.attributes = basic[0];
                            entry.granted_access = basic[1];
                            entry.flags |= 4;
                        }
                    } else if fallback_count <= QUERY_REPORT_LIMIT {
                        number(b"self_handles_basic_query_unavailable", /*value*/ 1);
                    }
                }
                let basic_available = entry.flags & 4 != 0;
                result.missing_basic += usize::from(!basic_available);
                let object_type_id = if entry.flags & 1 != 0 {
                    entry.object_type
                } else {
                    u32::MAX
                };
                let key = HandleKey {
                    handle: entry.handle,
                    object_type: object_type_id,
                    access: if basic_available {
                        entry.granted_access
                    } else {
                        0
                    },
                    attributes: if basic_available { entry.attributes } else { 0 },
                    basic_available,
                };
                result.entries[result.len] = key;
                result.len += 1;
                if before.is_some_and(|before| {
                    before.complete && !before.entries[..before.len].contains(&key)
                }) {
                    differences += 1;
                    if differences <= REPORT_LIMIT {
                        number(b"handle_delta_index", differences as u32);
                        number(b"handle_delta_object_type", object_type_id);
                        number(b"handle_delta_basic_available", basic_available as u32);
                        if basic_available {
                            number(b"handle_delta_granted_access", entry.granted_access);
                            number(b"handle_delta_attributes", entry.attributes);
                        }
                        if !query.is_null() && entry.handle > 0 {
                            // SAFETY: named export; query only this currently owned handle's type.
                            let query =
                                unsafe { core::mem::transmute::<*mut c_void, Query>(query) };
                            object_type(query, entry.handle);
                        }
                    }
                }
            }
            number(b"self_handles_metadata_differences", differences as u32);
            number(b"self_handles_basic_fallback_count", fallback_count as u32);
            number(
                b"self_handles_query_report_capacity_exceeded",
                (fallback_count > QUERY_REPORT_LIMIT) as u32,
            );
            number(
                b"self_handles_report_capacity_exceeded",
                (differences > REPORT_LIMIT) as u32,
            );
            number(b"self_handles_marker_free_error", unsafe {
                PssWalkMarkerFree(marker)
            });
        }
        number(b"self_handles_snapshot_free_error", unsafe {
            PssFreeSnapshot(GetCurrentProcess(), snapshot)
        });
        number(b"self_handles_count", result.len as u32);
        number(b"self_handles_complete", result.complete as u32);
        number(b"self_handles_missing_basic", result.missing_basic as u32);
        number(
            b"self_handles_comparison_available",
            (result.complete && before.is_some_and(|before| before.complete)) as u32,
        );
        number(
            b"self_handles_comparison_metadata_complete",
            (result.complete
                && result.missing_basic == 0
                && before.is_some_and(|before| before.complete && before.missing_basic == 0))
                as u32,
        );
        // This compares handle metadata, not kernel object identity. Reused handle
        // values with the same metadata and transient objects may be unobserved.
        result
    }
}

fn object_type(query: Query, handle: isize) {
    let mut data = [0_usize; 64];
    let mut returned = 0;
    let status = unsafe {
        query(
            handle,
            /*kind: ObjectTypeInformation*/ 2,
            data.as_mut_ptr().cast(),
            core::mem::size_of_val(&data) as u32,
            &mut returned,
        )
    };
    number(b"handle_delta_type_ntstatus", status as u32);
    if status < 0 || returned as usize > core::mem::size_of_val(&data) {
        return;
    }
    // PUBLIC_OBJECT_TYPE_INFORMATION begins with a UNICODE_STRING; all pointer
    // reads stay inside this query's initialized, aligned, bounded output.
    let len = data[0] & 0xffff;
    let offset = data[1].checked_sub(data.as_ptr() as usize);
    let valid = offset
        .filter(|offset| *offset >= 2 * core::mem::size_of::<usize>() && *offset % 2 == 0)
        .filter(|offset| {
            offset
                .checked_add(len)
                .is_some_and(|end| end <= returned as usize)
        });
    if len == 0 || len > 128 || len % 2 != 0 || valid.is_none() {
        number(b"handle_delta_type_bounds_invalid", /*value*/ 1);
        return;
    }
    let units = unsafe { core::slice::from_raw_parts(data[1] as *const u16, len / 2) };
    if units.iter().any(|value| !(32..=126).contains(value)) {
        number(b"handle_delta_type_non_ascii", /*value*/ 1);
        return;
    }
    write(b"handle_delta_type_name=");
    for unit in units {
        write(&[*unit as u8]);
    }
    write(b"\n");
}
