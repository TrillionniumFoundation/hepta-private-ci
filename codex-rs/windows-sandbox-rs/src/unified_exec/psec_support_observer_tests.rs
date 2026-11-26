//! Query-only PSEC availability facts in one existing Windows test.
//!
//! The official Microsoft MXC bindings at commit
//! 383933e9dd4a6b068670767f5926adbdba2de6c9 define QuerySupport's output as u64
//! and the version outputs as BOOLEAN/u32. No environment or child is created.

use serde::Serialize;
use std::io::Write;
use windows_sys::Win32::Foundation::FreeLibrary;
use windows_sys::Win32::Foundation::HMODULE;
use windows_sys::Win32::System::LibraryLoader::GetProcAddress;
use windows_sys::Win32::System::LibraryLoader::LOAD_LIBRARY_SEARCH_SYSTEM32;
use windows_sys::Win32::System::LibraryLoader::LoadLibraryExW;

const PREFIX: &str = "HEPTA_PSEC_SUPPORT ";
const LOG_BYTES: usize = 4096;
type Export = unsafe extern "system" fn() -> isize;
type QuerySupport = unsafe extern "system" fn(*mut u64) -> i32;
type QueryVersion = unsafe extern "system" fn(u32, *mut u8, *mut u32) -> i32;

#[derive(Serialize)]
struct QueryResult {
    hresult: i32,
    flags_raw: u64,
    outputs_valid: bool,
}

#[derive(Serialize)]
struct VersionResult {
    hresult: i32,
    major_requested: u32,
    available_raw: u8,
    minor_raw: u32,
    outputs_valid: bool,
}

#[derive(Serialize)]
struct Exports {
    query_support: bool,
    query_version: bool,
    create_presence_only: bool,
    close_presence_only: bool,
}

#[derive(Serialize)]
struct ReleaseResult {
    success: bool,
    win32_error: Option<i32>,
}

struct SystemModule(HMODULE);

impl SystemModule {
    fn close(mut self) -> ReleaseResult {
        let handle = std::mem::take(&mut self.0);
        // SAFETY: this handle is the one successful LoadLibraryExW reference.
        // Disarming before the call prevents a second FreeLibrary on failure.
        let success = unsafe { FreeLibrary(handle) } != 0;
        ReleaseResult {
            success,
            win32_error: if success {
                None
            } else {
                std::io::Error::last_os_error().raw_os_error()
            },
        }
    }
}

impl Drop for SystemModule {
    fn drop(&mut self) {
        if self.0 != 0 {
            // SAFETY: a still-owned module reference is released on early unwind.
            // The normal path explicitly closes once and records its result.
            unsafe { FreeLibrary(self.0) };
        }
    }
}

#[derive(Serialize)]
struct Observation {
    schema: u32,
    actor: &'static str,
    module_loaded: bool,
    module_load_win32_error: Option<i32>,
    exports: Option<Exports>,
    query_support: Option<QueryResult>,
    query_version: Option<VersionResult>,
    module_release: Option<ReleaseResult>,
    environment_create_calls: u32,
    environment_close_calls: u32,
    child_launch_calls: u32,
}

pub(super) fn record() {
    let mut observation = Observation {
        schema: 1,
        actor: "parent_test_process",
        module_loaded: false,
        module_load_win32_error: None,
        exports: None,
        query_support: None,
        query_version: None,
        module_release: None,
        environment_create_calls: 0,
        environment_close_calls: 0,
        child_launch_calls: 0,
    };
    let name: Vec<u16> = "processmodel.dll\0".encode_utf16().collect();
    // SAFETY: the fixed NUL-terminated name remains live; loading is restricted
    // to the system directory. No current-directory or PATH lookup is used.
    let raw = unsafe {
        LoadLibraryExW(
            name.as_ptr(),
            /*hfile*/ 0,
            LOAD_LIBRARY_SEARCH_SYSTEM32,
        )
    };
    if raw == 0 {
        observation.module_load_win32_error = std::io::Error::last_os_error().raw_os_error();
    } else {
        let module = SystemModule(raw);
        observation.module_loaded = true;
        // SAFETY: all four names are static NUL-terminated ASCII and the module
        // stays loaded until both optional queries have returned. Create/Close
        // pointers are inspected for presence and are never called.
        let (support, version, create, close) = unsafe {
            (
                GetProcAddress(
                    raw,
                    c"QueryProcessSecurityEnvironmentSupport".as_ptr().cast(),
                ),
                GetProcAddress(
                    raw,
                    c"IsProcessSecurityEnvironmentVersionSupported"
                        .as_ptr()
                        .cast(),
                ),
                GetProcAddress(raw, c"CreateProcessSecurityEnvironment".as_ptr().cast()),
                GetProcAddress(raw, c"CloseProcessSecurityEnvironment".as_ptr().cast()),
            )
        };
        observation.exports = Some(Exports {
            query_support: support.is_some(),
            query_version: version.is_some(),
            create_presence_only: create.is_some(),
            close_presence_only: close.is_some(),
        });
        if let Some(function) = support {
            // SAFETY: exact official MXC QuerySupport ABI for the named export;
            // the aligned u64 output remains live through this synchronous call.
            let query = unsafe { std::mem::transmute::<Export, QuerySupport>(function) };
            let mut flags_raw = 0u64;
            let hresult = unsafe { query(&mut flags_raw) };
            observation.query_support = Some(QueryResult {
                hresult,
                flags_raw,
                outputs_valid: hresult == 0,
            });
        }
        if let Some(function) = version {
            // SAFETY: exact official BOOLEAN/u32 output ABI; both owned outputs
            // remain live through this synchronous call. No support is inferred
            // from a failure or a BOOLEAN outside its documented 0/1 values.
            let query = unsafe { std::mem::transmute::<Export, QueryVersion>(function) };
            let (mut available_raw, mut minor_raw) = (0u8, 0u32);
            let hresult = unsafe {
                query(/*major*/ 1, &mut available_raw, &mut minor_raw)
            };
            observation.query_version = Some(VersionResult {
                hresult,
                major_requested: 1,
                available_raw,
                minor_raw,
                outputs_valid: hresult == 0 && available_raw <= 1,
            });
        }
        observation.module_release = Some(module.close());
    }
    let bytes = serde_json::to_vec(&observation)
        .unwrap_or_else(|_| br#"{"schema":1,"observation_error":"serialization_failed"}"#.to_vec());
    let mut stderr = std::io::stderr().lock();
    if PREFIX.len() + bytes.len() < LOG_BYTES {
        // One locked record, at most 4096 bytes including newline. Logging
        // failure must not replace any original native assertion or exit.
        let _ = stderr.write_all(PREFIX.as_bytes());
        let _ = stderr.write_all(&bytes);
        let _ = stderr.write_all(b"\n");
    } else {
        let _ = stderr.write_all(
            b"HEPTA_PSEC_SUPPORT {\"schema\":1,\"observation_error\":\"record_exceeds_bound\"}\n",
        );
    }
}
