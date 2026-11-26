//! Open-only calls for the fixed absolute-path comparison, not a product API.

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use std::io::Write;
use std::os::windows::ffi::OsStrExt;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::IntoRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::Path;
use windows_sys::Wdk::Foundation::NtQueryObject;
use windows_sys::Wdk::Foundation::OBJECT_ATTRIBUTES;
use windows_sys::Wdk::Foundation::ObjectBasicInformation;
use windows_sys::Wdk::Storage::FileSystem::FILE_OPEN;
use windows_sys::Wdk::Storage::FileSystem::FILE_OPEN_FOR_BACKUP_INTENT;
use windows_sys::Wdk::Storage::FileSystem::FILE_OPEN_REPARSE_POINT;
use windows_sys::Wdk::Storage::FileSystem::NtCreateFile;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::ERROR_ACCESS_DENIED;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Foundation::RtlNtStatusToDosError;
use windows_sys::Win32::Foundation::STATUS_ACCESS_DENIED;
use windows_sys::Win32::Foundation::STATUS_PENDING;
use windows_sys::Win32::Foundation::STATUS_SUCCESS;
use windows_sys::Win32::Foundation::UNICODE_STRING;
use windows_sys::Win32::Storage::FileSystem::CreateFileW;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OVERLAPPED;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::OPEN_EXISTING;
use windows_sys::Win32::Storage::FileSystem::SYNCHRONIZE;
use windows_sys::Win32::System::IO::IO_STATUS_BLOCK;
use windows_sys::Win32::System::IO::IO_STATUS_BLOCK_0;
use windows_sys::Win32::System::Kernel::OBJ_CASE_INSENSITIVE;
use windows_sys::Win32::System::WindowsProgramming::PUBLIC_OBJECT_BASIC_INFORMATION;

const SHARING: u32 = FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE;

pub(super) enum NativeRequest {
    DeleteOnly,
    ObservedWin32Grant,
    DeleteReadAttributes,
    DeleteSynchronize,
}

#[derive(Debug)]
pub(super) struct Observation {
    pub(super) opened: bool,
    pub(super) error: Option<u32>,
}

pub(super) fn win32(path: &Path, scenario: &str) -> Result<Observation> {
    local_drive_name(path)?;
    let name: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
    let raw = unsafe {
        CreateFileW(
            name.as_ptr(),
            DELETE,
            SHARING,
            std::ptr::null(),
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_OVERLAPPED,
            /*htemplatefile*/ 0,
        )
    };
    let error = (raw == INVALID_HANDLE_VALUE).then(|| unsafe { GetLastError() });
    if let Some(error) = error {
        eprintln!(
            "HEPTA_NATIVE_OPEN scenario={scenario} api=Win32 requested=0x{DELETE:08x} opened=false ntstatus=not_applicable win32_error={error} granted=unknown closed=not_opened"
        );
        ensure!(
            error == ERROR_ACCESS_DENIED,
            "unexpected Win32 open error {error}"
        );
        return Ok(Observation {
            opened: false,
            error: Some(error),
        });
    }
    ensure!(raw != 0, "successful Win32 open returned a null handle");
    let handle = unsafe { OwnedHandle::from_raw_handle(raw as _) };
    finish_open(handle, scenario, "Win32", DELETE, /*ntstatus*/ None)
}

pub(super) fn native(path: &Path, scenario: &str, request: NativeRequest) -> Result<Observation> {
    let (requested, api) = match request {
        NativeRequest::DeleteOnly => (DELETE, "NT"),
        NativeRequest::ObservedWin32Grant => (
            DELETE | SYNCHRONIZE | FILE_READ_ATTRIBUTES,
            "NTObservedGrant",
        ),
        NativeRequest::DeleteReadAttributes => (DELETE | FILE_READ_ATTRIBUTES, "NTReadAttributes"),
        NativeRequest::DeleteSynchronize => (DELETE | SYNCHRONIZE, "NTSynchronize"),
    };
    let dos = local_drive_name(path)?;
    let mut name: Vec<u16> = r"\??\".encode_utf16().chain(dos).collect();
    let unicode = UNICODE_STRING {
        Length: u16::try_from((name.len() - 1) * 2).context("NT name length")?,
        MaximumLength: u16::try_from(name.len() * 2).context("NT name capacity")?,
        Buffer: name.as_mut_ptr(),
    };
    let attributes = OBJECT_ATTRIBUTES {
        Length: std::mem::size_of::<OBJECT_ATTRIBUTES>() as u32,
        RootDirectory: 0,
        ObjectName: &unicode,
        Attributes: OBJ_CASE_INSENSITIVE as u32,
        SecurityDescriptor: std::ptr::null(),
        SecurityQualityOfService: std::ptr::null(),
    };
    let mut io = IO_STATUS_BLOCK {
        Anonymous: IO_STATUS_BLOCK_0 {
            Status: STATUS_PENDING,
        },
        Information: 0,
    };
    let mut raw = 0;
    let status = unsafe {
        NtCreateFile(
            &mut raw,
            requested,
            &attributes,
            &mut io,
            std::ptr::null(),
            /*fileattributes*/ 0,
            SHARING,
            FILE_OPEN,
            FILE_OPEN_FOR_BACKUP_INTENT | FILE_OPEN_REPARSE_POINT,
            std::ptr::null(),
            /*ealength*/ 0,
        )
    };
    if status == STATUS_PENDING {
        // This isolated observer cannot wait without adding synchronization
        // authority. Never unwind buffers that a pending operation might use.
        // Process termination releases its handles; no completion is inferred.
        let _ = writeln!(
            std::io::stderr(),
            "HEPTA_NATIVE_OPEN scenario={scenario} api={api} requested=0x{requested:08x} opened=unknown ntstatus=0x{:08x} win32_error={} granted=unknown closed=process_teardown protocol_error=pending",
            status as u32,
            unsafe { RtlNtStatusToDosError(status) }
        );
        std::process::abort();
    }
    // Acquire ownership before any fallible logging. A nonnegative terminal
    // informational status can still return a valid handle that must be closed.
    let handle = (status >= 0 && raw != 0 && raw != INVALID_HANDLE_VALUE)
        .then(|| unsafe { OwnedHandle::from_raw_handle(raw as _) });
    eprintln!(
        "HEPTA_NATIVE_STATUS scenario={scenario} ntstatus=0x{:08x} mapped_win32={} io_status=0x{:08x} io_information={} root_handle=null options=0x{:08x} api={api} requested=0x{requested:08x}",
        status as u32,
        unsafe { RtlNtStatusToDosError(status) },
        unsafe { io.Anonymous.Status } as u32,
        io.Information,
        FILE_OPEN_FOR_BACKUP_INTENT | FILE_OPEN_REPARSE_POINT,
    );
    if status < 0 {
        let error = unsafe { RtlNtStatusToDosError(status) };
        eprintln!(
            "HEPTA_NATIVE_OPEN scenario={scenario} api={api} requested=0x{requested:08x} opened=false ntstatus=0x{:08x} win32_error={error} granted=unknown closed=not_opened",
            status as u32
        );
        ensure!(
            status == STATUS_ACCESS_DENIED,
            "unexpected NT open status 0x{:08x}",
            status as u32
        );
        return Ok(Observation {
            opened: false,
            error: Some(error),
        });
    }
    let handle = handle.context("nonnegative NT open returned an invalid handle")?;
    let observation = finish_open(handle, scenario, api, requested, Some(status))?;
    ensure!(
        status == STATUS_SUCCESS,
        "nonzero informational NT status is incomplete: 0x{:08x}",
        status as u32,
    );
    Ok(observation)
}

fn finish_open(
    handle: OwnedHandle,
    scenario: &str,
    api: &str,
    requested: u32,
    ntstatus: Option<i32>,
) -> Result<Observation> {
    let mut info = PUBLIC_OBJECT_BASIC_INFORMATION {
        Attributes: 0,
        GrantedAccess: 0,
        HandleCount: 0,
        PointerCount: 0,
        Reserved: [0; 10],
    };
    let mut returned = 0;
    let query_status = unsafe {
        NtQueryObject(
            handle.as_raw_handle() as _,
            ObjectBasicInformation,
            std::ptr::addr_of_mut!(info).cast(),
            std::mem::size_of_val(&info) as u32,
            &mut returned,
        )
    };
    let queried =
        query_status == STATUS_SUCCESS && returned as usize == std::mem::size_of_val(&info);
    let granted = queried.then_some(info.GrantedAccess);
    // Explicit close happens even when the query fails. Never reopen with more access.
    let closed = unsafe { CloseHandle(handle.into_raw_handle() as _) } != 0;
    let close_error = (!closed).then(|| unsafe { GetLastError() });
    let completion = if ntstatus.is_none_or(|status| status == STATUS_SUCCESS) {
        "success"
    } else {
        "unknown"
    };
    let win32_error = if completion == "success" {
        "none"
    } else {
        "unknown"
    };
    eprintln!(
        "HEPTA_NATIVE_OPEN scenario={scenario} api={api} requested=0x{requested:08x} opened=true completion={completion} ntstatus={ntstatus:?} win32_error={win32_error} query_ntstatus=0x{:08x} query_mapped_win32={} query_bytes={returned} granted={granted:?} closed={closed} close_error={close_error:?}",
        query_status as u32,
        unsafe { RtlNtStatusToDosError(query_status) },
    );
    ensure!(closed, "close observed handle: {close_error:?}");
    ensure!(
        queried,
        "GrantedAccess is unknown: NtQueryObject status 0x{:08x}, bytes {returned}",
        query_status as u32
    );
    ensure!(
        info.GrantedAccess & requested == requested,
        "opened handle lacks the complete requested mask"
    );
    Ok(Observation {
        opened: true,
        error: None,
    })
}

fn local_drive_name(path: &Path) -> Result<Vec<u16>> {
    let original: Vec<u16> = path.as_os_str().encode_wide().collect();
    let prefix: Vec<u16> = r"\\?\".encode_utf16().collect();
    let name = original
        .strip_prefix(prefix.as_slice())
        .unwrap_or(&original);
    ensure!(
        name.len() >= 4 && name.len() <= 32_000,
        "fixture name length is out of bounds"
    );
    ensure!(
        name[0] <= 127
            && (name[0] as u8).is_ascii_alphabetic()
            && name[1] == u16::from(b':')
            && name[2] == u16::from(b'\\'),
        "only absolute local drive fixture paths are supported"
    );
    ensure!(
        !name.contains(&0)
            && !name.contains(&u16::from(b'/'))
            && name[3..]
                .split(|unit| *unit == u16::from(b'\\'))
                .all(|part| {
                    !part.is_empty()
                        && part != [u16::from(b'.')]
                        && part != [u16::from(b'.'), u16::from(b'.')]
                        && !part.contains(&u16::from(b':'))
                }),
        "fixture path contains a forbidden component"
    );
    Ok(name.iter().copied().chain(Some(0)).collect())
}
