//! One explicit DELETE-only open and disposition; no pathname retry or new rights.

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
use windows_sys::Wdk::Foundation::NtClose;
use windows_sys::Wdk::Foundation::NtQueryObject;
use windows_sys::Wdk::Foundation::OBJECT_ATTRIBUTES;
use windows_sys::Wdk::Foundation::ObjectBasicInformation;
use windows_sys::Wdk::Storage::FileSystem::FILE_DISPOSITION_INFORMATION;
use windows_sys::Wdk::Storage::FileSystem::FILE_OPEN;
use windows_sys::Wdk::Storage::FileSystem::FILE_OPEN_FOR_BACKUP_INTENT;
use windows_sys::Wdk::Storage::FileSystem::FILE_OPEN_REPARSE_POINT;
use windows_sys::Wdk::Storage::FileSystem::NtCreateFile;
use windows_sys::Wdk::Storage::FileSystem::NtSetInformationFile;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Foundation::RtlNtStatusToDosError;
use windows_sys::Win32::Foundation::STATUS_ACCESS_DENIED;
use windows_sys::Win32::Foundation::STATUS_PENDING;
use windows_sys::Win32::Foundation::STATUS_SUCCESS;
use windows_sys::Win32::Foundation::UNICODE_STRING;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::System::IO::IO_STATUS_BLOCK;
use windows_sys::Win32::System::IO::IO_STATUS_BLOCK_0;
use windows_sys::Win32::System::Kernel::OBJ_CASE_INSENSITIVE;
use windows_sys::Win32::System::WindowsProgramming::FILE_INFORMATION_CLASS;
use windows_sys::Win32::System::WindowsProgramming::PUBLIC_OBJECT_BASIC_INFORMATION;

// Official NtSetInformationFile table: native class 13, not Win32 class 4.
const DISPOSITION_CLASS: FILE_INFORMATION_CLASS = 13;

pub(super) fn open_delete(path: &Path, scenario: &str) -> Result<Option<OwnedHandle>> {
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
            DELETE,
            &attributes,
            &mut io,
            std::ptr::null(),
            /*fileattributes*/ 0,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            FILE_OPEN,
            FILE_OPEN_FOR_BACKUP_INTENT | FILE_OPEN_REPARSE_POINT,
            std::ptr::null(),
            /*ealength*/ 0,
        )
    };
    if status == STATUS_PENDING {
        abort_pending(scenario, "open");
    }
    let handle = (status >= 0 && raw != 0 && raw != INVALID_HANDLE_VALUE)
        .then(|| unsafe { OwnedHandle::from_raw_handle(raw as _) });
    if status < 0 {
        eprintln!(
            "HEPTA_DISPOSITION_OPEN scenario={scenario} requested=0x{DELETE:08x} ntstatus=0x{:08x} mapped_win32={} io_status=0x{:08x} io_information={} root_handle=null options=0x00204000 opened=false query_ntstatus=not_opened query_bytes=0 granted=unknown",
            status as u32,
            unsafe { RtlNtStatusToDosError(status) },
            unsafe { io.Anonymous.Status } as u32,
            io.Information,
        );
        ensure!(
            status == STATUS_ACCESS_DENIED,
            "unexpected native open status 0x{:08x}",
            status as u32
        );
        return Ok(None);
    }
    let handle = handle.context("nonnegative native open returned an invalid handle")?;
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
    eprintln!(
        "HEPTA_DISPOSITION_OPEN scenario={scenario} requested=0x{DELETE:08x} ntstatus=0x{:08x} mapped_win32={} io_status=0x{:08x} io_information={} root_handle=null options=0x00204000 opened=true query_ntstatus=0x{:08x} query_bytes={returned} granted={granted:?}",
        status as u32,
        unsafe { RtlNtStatusToDosError(status) },
        unsafe { io.Anonymous.Status } as u32,
        io.Information,
        query_status as u32,
    );
    if status != STATUS_SUCCESS
        || unsafe { io.Anonymous.Status } != STATUS_SUCCESS
        || !queried
        || granted != Some(DELETE)
    {
        close(handle, scenario, "incomplete-open")?;
        anyhow::bail!("native open/query did not establish exact DELETE-only authority");
    }
    Ok(Some(handle))
}

pub(super) fn mark_and_close(handle: OwnedHandle, scenario: &str) -> Result<()> {
    let information = FILE_DISPOSITION_INFORMATION { DeleteFile: 1 };
    let mut io = IO_STATUS_BLOCK {
        Anonymous: IO_STATUS_BLOCK_0 {
            Status: STATUS_PENDING,
        },
        Information: 0,
    };
    let status = unsafe {
        NtSetInformationFile(
            handle.as_raw_handle() as _,
            &mut io,
            std::ptr::addr_of!(information).cast(),
            std::mem::size_of_val(&information) as u32,
            DISPOSITION_CLASS,
        )
    };
    if status == STATUS_PENDING {
        // Neither the IOSB nor information buffer may unwind while IO is pending.
        abort_pending(scenario, "mark");
    }
    // After marking, perform no operation on this handle except its single close.
    let closed = close(handle, scenario, "disposition");
    let io_status = unsafe { io.Anonymous.Status };
    eprintln!(
        "HEPTA_DISPOSITION_MARK scenario={scenario} class=13 delete_file=1 ntstatus=0x{:08x} mapped_win32={} io_status=0x{:08x} io_information={}",
        status as u32,
        unsafe { RtlNtStatusToDosError(status) },
        io_status as u32,
        io.Information,
    );
    ensure!(
        status == STATUS_SUCCESS && io_status == STATUS_SUCCESS,
        "native disposition incomplete: status=0x{:08x}, IOSB=0x{:08x}, close={closed:?}",
        status as u32,
        io_status as u32,
    );
    closed
}

pub(super) fn close(handle: OwnedHandle, scenario: &str, phase: &str) -> Result<()> {
    let status = unsafe { NtClose(handle.into_raw_handle() as _) };
    eprintln!(
        "HEPTA_DISPOSITION_CLOSE scenario={scenario} phase={phase} ntstatus=0x{:08x} mapped_win32={}",
        status as u32,
        unsafe { RtlNtStatusToDosError(status) }
    );
    ensure!(
        status == STATUS_SUCCESS,
        "native close incomplete: 0x{:08x}",
        status as u32
    );
    Ok(())
}

fn abort_pending(scenario: &str, phase: &str) -> ! {
    let _ = writeln!(
        std::io::stderr(),
        "HEPTA_DISPOSITION_INCOMPLETE scenario={scenario} phase={phase} ntstatus=0x00000103 completion=unknown cleanup=process_teardown"
    );
    std::process::abort();
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
