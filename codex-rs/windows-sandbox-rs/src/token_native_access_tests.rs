//! Native requests on the same owned directories and existing impersonation.

use super::to_wide;
use anyhow::Result;
use std::ffi::c_void;
use std::path::Path;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::FreeLibrary;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::HMODULE;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Foundation::STATUS_PENDING;
use windows_sys::Win32::Foundation::UNICODE_STRING;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::TOKEN_STATISTICS;
use windows_sys::Win32::Security::TokenStatistics;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::SYNCHRONIZE;
use windows_sys::Win32::System::IO::IO_STATUS_BLOCK;
use windows_sys::Win32::System::LibraryLoader::GetProcAddress;
use windows_sys::Win32::System::LibraryLoader::LOAD_LIBRARY_SEARCH_SYSTEM32;
use windows_sys::Win32::System::LibraryLoader::LoadLibraryExW;
use windows_sys::Win32::System::Threading::GetCurrentThread;
use windows_sys::Win32::System::Threading::OpenThreadToken;
use windows_sys::Win32::System::WindowsProgramming::PUBLIC_OBJECT_BASIC_INFORMATION;

const FILE_OPEN: u32 = 1;
const FILE_DIRECTORY_FILE: u32 = 1;
const FILE_OPEN_FOR_BACKUP_INTENT: u32 = 0x4000;
const FILE_SYNCHRONOUS_IO_NONALERT: u32 = 0x20;
const OBJ_CASE_INSENSITIVE: u32 = 0x40;

// Documented winternl/ntdef layouts. Existing dependency features supply the
// pointer-sized HANDLE, UNICODE_STRING and IO_STATUS_BLOCK definitions.
#[repr(C)]
struct ObjectAttributes {
    length: u32,
    root_directory: HANDLE,
    object_name: *mut UNICODE_STRING,
    attributes: u32,
    security_descriptor: *mut c_void,
    security_quality_of_service: *mut c_void,
}

type Create = unsafe extern "system" fn(
    *mut HANDLE,
    u32,
    *const ObjectAttributes,
    *mut IO_STATUS_BLOCK,
    *const i64,
    u32,
    u32,
    u32,
    u32,
    *const c_void,
    u32,
) -> i32;
type Query = unsafe extern "system" fn(HANDLE, i32, *mut c_void, u32, *mut u32) -> i32;
struct Api {
    create: Create,
    query: Query,
}

struct NativeCall {
    _buffer: Vec<u16>,
    name: UNICODE_STRING,
    attributes: ObjectAttributes,
    handle: HANDLE,
    completion: IO_STATUS_BLOCK,
}

enum RequestOutcome {
    Complete,
    Pending,
}

struct OwnedHandle(HANDLE);

impl OwnedHandle {
    fn close(&mut self) -> std::io::Result<()> {
        // SAFETY: this wrapper owns one successful file or query-token handle.
        if unsafe { CloseHandle(self.0) } == 0 {
            Err(std::io::Error::last_os_error())
        } else {
            self.0 = 0;
            Ok(())
        }
    }
}

impl Drop for OwnedHandle {
    fn drop(&mut self) {
        if self.0 != 0 {
            // SAFETY: a failed explicit close leaves ownership here. This
            // fallback is not reported as evidence of successful cleanup.
            unsafe { CloseHandle(self.0) };
        }
    }
}

struct Library(HMODULE);

impl Library {
    fn close(&mut self) -> std::io::Result<()> {
        // SAFETY: all calls and converted names have finished using this load.
        if unsafe { FreeLibrary(self.0) } == 0 {
            Err(std::io::Error::last_os_error())
        } else {
            self.0 = 0;
            Ok(())
        }
    }
}

impl Drop for Library {
    fn drop(&mut self) {
        if self.0 != 0 {
            // SAFETY: only our successful LoadLibraryEx reference is released.
            unsafe { FreeLibrary(self.0) };
        }
    }
}

#[derive(Clone, Copy)]
struct Stamp {
    token: (u32, i32),
    modified: (u32, i32),
}

fn stamp(case: u8, phase: u8) -> Result<Stamp> {
    let mut raw = 0;
    // SAFETY: query only the current thread; OpenAsSelf changes authorization
    // for this handle, not the installed token or its privileges.
    let opened = unsafe {
        OpenThreadToken(
            GetCurrentThread(),
            TOKEN_QUERY,
            /*openasself*/ 1,
            &mut raw,
        )
    } != 0;
    let open_os = (!opened).then(|| unsafe { GetLastError() });
    let owner = opened.then(|| OwnedHandle(raw));
    println!("FULL_NATIVE_TOKEN_OPEN case={case} phase={phase} success={opened} os={open_os:?}");
    let Some(mut owner) = owner else {
        anyhow::bail!("FULL_SETUP native_token_open");
    };
    let mut value: TOKEN_STATISTICS = unsafe { std::mem::zeroed() };
    let capacity = std::mem::size_of_val(&value) as u32;
    let mut returned = 0;
    // SAFETY: the fixed structure is initialized, aligned and exactly bounded.
    let queried = unsafe {
        GetTokenInformation(
            raw,
            TokenStatistics,
            (&mut value as *mut TOKEN_STATISTICS).cast(),
            capacity,
            &mut returned,
        )
    } != 0;
    let query_os = (!queried).then(|| unsafe { GetLastError() });
    let shape = queried && returned == capacity;
    let closed = owner.close();
    let close_os = closed.as_ref().err().and_then(std::io::Error::raw_os_error);
    println!(
        "FULL_NATIVE_TOKEN_QUERY case={case} phase={phase} api_ok={queried} shape_ok={shape} os={query_os:?} closed={} close_os={close_os:?}",
        closed.is_ok()
    );
    closed.map_err(|_| anyhow::anyhow!("FULL_SETUP native_token_close"))?;
    anyhow::ensure!(shape, "FULL_SETUP native_token_query");
    Ok(Stamp {
        token: (value.TokenId.LowPart, value.TokenId.HighPart),
        modified: (value.ModifiedId.LowPart, value.ModifiedId.HighPart),
    })
}

fn native_path(terminated: &[u16]) -> Option<(u8, Vec<u16>)> {
    let dos = terminated.strip_suffix(&[0])?;
    let (kind, drive) = if let Some(rest) = dos.strip_prefix(&[92, 92, 63, 92]) {
        (2, rest)
    } else {
        (1, dos)
    };
    if drive.len() < 4 || !matches!(drive[0], 65..=90 | 97..=122) || drive[1..3] != [58, 92] {
        return None;
    }
    for component in drive[3..].split(|unit| *unit == 92) {
        let text = String::from_utf16(component).ok()?;
        let stem = text.split('.').next()?.to_ascii_uppercase();
        let reserved = matches!(stem.as_str(), "CON" | "PRN" | "AUX" | "NUL")
            || ["COM", "LPT"].iter().any(|prefix| {
                stem.strip_prefix(prefix).is_some_and(|tail| {
                    matches!(
                        tail,
                        "1" | "2" | "3" | "4" | "5" | "6" | "7" | "8" | "9" | "¹" | "²" | "³"
                    )
                })
            });
        if component.is_empty()
            || text == "."
            || text == ".."
            || reserved
            || matches!(component.last(), Some(32 | 46))
            || component
                .iter()
                .any(|unit| *unit < 32 || matches!(*unit, 34 | 42 | 47 | 58 | 60 | 62 | 63 | 124))
        {
            return None;
        }
    }
    let mut buffer = vec![92, 63, 63, 92];
    buffer.extend_from_slice(drive);
    buffer.push(/*value*/ 0);
    u16::try_from(buffer.len().checked_mul(/*rhs*/ 2)?).ok()?;
    Some((kind, buffer))
}

fn request(
    api: &Api,
    library: &mut Library,
    case: u8,
    slot: u8,
    path: &Path,
    requested: u32,
    options: u32,
) -> Result<RequestOutcome> {
    let name = native_path(&to_wide(path));
    let kind = name.as_ref().map_or(/*default*/ 0, |value| value.0);
    println!(
        "FULL_NATIVE_PATH case={case} slot={slot} kind={kind} ready={}",
        name.is_some()
    );
    let Some((_, mut buffer)) = name else {
        anyhow::bail!("FULL_SETUP native_path_shape");
    };
    let name = UNICODE_STRING {
        Length: ((buffer.len() - 1) * 2) as u16,
        MaximumLength: (buffer.len() * 2) as u16,
        Buffer: buffer.as_mut_ptr(),
    };
    let mut call = Box::new(NativeCall {
        _buffer: buffer,
        name,
        attributes: ObjectAttributes {
            length: std::mem::size_of::<ObjectAttributes>() as u32,
            root_directory: 0,
            object_name: std::ptr::null_mut(),
            attributes: OBJ_CASE_INSENSITIVE,
            security_descriptor: std::ptr::null_mut(),
            security_quality_of_service: std::ptr::null_mut(),
        },
        handle: 0,
        completion: unsafe { std::mem::zeroed() },
    });
    call.attributes.object_name = &mut call.name;
    // SAFETY: exact documented ABI, live immutable name/attributes, stable output
    // allocations and no delete-on-close, create, write or relative-root option.
    let status = unsafe {
        (api.create)(
            &mut call.handle,
            requested,
            &call.attributes,
            &mut call.completion,
            std::ptr::null(),
            /*fileattributes*/ 0,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            FILE_OPEN,
            options,
            std::ptr::null(),
            /*ealength*/ 0,
        )
    };
    let pending = status == STATUS_PENDING;
    if pending {
        // Create is documented as synchronous. For this unexpected status,
        // retain every input/output allocation without reading outputs. The
        // module reference is also retained before any potentially panicking
        // output; no completion or cleanup is claimed.
        Box::leak(call);
        library.0 = 0;
        println!(
            "FULL_NATIVE_OPEN case={case} slot={slot} requested={requested} options={options} status={status} pending={pending}"
        );
        return Ok(RequestOutcome::Pending);
    }
    let output_nonzero = call.handle != 0;
    let owned = status == 0 && output_nonzero && call.handle != INVALID_HANDLE_VALUE;
    // Only completed success conveys ownership. Never close an unproven
    // output from a failed or otherwise unexpected status.
    let mut owner = owned.then(|| OwnedHandle(call.handle));
    println!(
        "FULL_NATIVE_OPEN case={case} slot={slot} requested={requested} options={options} status={status} pending={pending}"
    );
    let mut query_status = None;
    let mut granted = None;
    if status == 0
        && let Some(owner) = &owner
    {
        let mut info: PUBLIC_OBJECT_BASIC_INFORMATION = unsafe { std::mem::zeroed() };
        let capacity = std::mem::size_of_val(&info) as u32;
        let mut returned = 0;
        // SAFETY: query only fixed basic fields of the completed owned handle.
        let code = unsafe {
            (api.query)(
                owner.0,
                /*objectinformationclass*/ 0,
                (&mut info as *mut PUBLIC_OBJECT_BASIC_INFORMATION).cast(),
                capacity,
                &mut returned,
            )
        };
        query_status = Some(code);
        if code == 0 && returned == capacity {
            granted = Some(info.GrantedAccess);
        }
    }
    let closed = owner.as_mut().map(OwnedHandle::close);
    let close_ok = closed.as_ref().map(std::result::Result::is_ok);
    let close_os = closed
        .as_ref()
        .and_then(|v| v.as_ref().err())
        .and_then(std::io::Error::raw_os_error);
    println!(
        "FULL_NATIVE_HANDLE case={case} slot={slot} output_nonzero={output_nonzero} owned={owned} query_status={query_status:?} granted={granted:?} closed={close_ok:?} close_os={close_os:?}"
    );
    anyhow::ensure!(close_ok != Some(false), "FULL_SETUP native_handle_close");
    anyhow::ensure!(
        (status == 0 && owned && granted.is_some()) || (status < 0 && !output_nonzero),
        "FULL_SETUP native_result_shape"
    );
    Ok(RequestOutcome::Complete)
}

pub(super) fn observe(case: u8, parent: &Path, child: &Path) -> Result<()> {
    if !matches!(case, 0 | 3) {
        return Ok(());
    }
    let before = stamp(case, /*phase*/ 0)?;
    // SAFETY: a fixed system DLL is loaded using only the system-directory
    // search flag. Its reference outlives every function pointer and name.
    let module = unsafe {
        LoadLibraryExW(
            to_wide("ntdll.dll").as_ptr(),
            /*hfile*/ 0,
            LOAD_LIBRARY_SEARCH_SYSTEM32,
        )
    };
    let load_os = (module == 0).then(|| unsafe { GetLastError() });
    let library = (module != 0).then(|| Library(module));
    println!(
        "FULL_NATIVE_LIBRARY case={case} loaded={} os={load_os:?}",
        module != 0
    );
    let Some(mut library) = library else {
        anyhow::bail!("FULL_SETUP native_library_load");
    };
    let mut pending = false;
    let result = (|| -> Result<()> {
        // SAFETY: these fixed exports are resolved only inside the live module.
        let create = unsafe { GetProcAddress(module, c"NtCreateFile".as_ptr().cast()) };
        let query = unsafe { GetProcAddress(module, c"NtQueryObject".as_ptr().cast()) };
        println!(
            "FULL_NATIVE_API case={case} create={} query={}",
            create.is_some(),
            query.is_some()
        );
        let (Some(create), Some(query)) = (create, query) else {
            anyhow::bail!("FULL_SETUP native_export_unavailable");
        };
        // SAFETY: each fixed symbol is cast to its documented system-call ABI.
        let api = unsafe {
            Api {
                create: std::mem::transmute::<unsafe extern "system" fn() -> isize, Create>(create),
                query: std::mem::transmute::<unsafe extern "system" fn() -> isize, Query>(query),
            }
        };
        let asynchronous = FILE_DIRECTORY_FILE | FILE_OPEN_FOR_BACKUP_INTENT;
        for (slot, path, requested, options) in [
            (0_u8, parent, FILE_DELETE_CHILD, asynchronous),
            (1, child, DELETE, asynchronous),
            (2, child, DELETE | SYNCHRONIZE, asynchronous),
            (
                3,
                child,
                DELETE | SYNCHRONIZE,
                asynchronous | FILE_SYNCHRONOUS_IO_NONALERT,
            ),
        ] {
            match request(&api, &mut library, case, slot, path, requested, options)? {
                RequestOutcome::Complete => {}
                RequestOutcome::Pending => {
                    pending = true;
                    anyhow::bail!("FULL_SETUP native_pending_unknown");
                }
            }
        }
        Ok(())
    })();
    let closed = if pending {
        std::mem::forget(library);
        None
    } else {
        Some(library.close())
    };
    let close_ok = closed.as_ref().map(std::result::Result::is_ok);
    let close_os = closed
        .as_ref()
        .and_then(|value| value.as_ref().err())
        .and_then(std::io::Error::raw_os_error);
    println!(
        "FULL_NATIVE_LIBRARY_CLOSE case={case} success={close_ok:?} retained={pending} os={close_os:?}"
    );
    let after = stamp(case, /*phase*/ 1);
    let same_token = after.as_ref().ok().map(|value| value.token == before.token);
    let same_modified = after
        .as_ref()
        .ok()
        .map(|value| value.modified == before.modified);
    println!(
        "FULL_NATIVE_IDENTITY case={case} same_token={same_token:?} same_modified={same_modified:?}"
    );
    anyhow::ensure!(close_ok != Some(false), "FULL_SETUP native_library_close");
    after?;
    result
}
