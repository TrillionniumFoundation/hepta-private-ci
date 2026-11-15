//! An observation-only child with no CRT, Rust std, CLR, or CNG import.
//! Build separately with panic=abort and an explicit kernel32-only entry point.
#![no_std]
#![no_main]

use core::ffi::c_void;

#[link(name = "kernel32")]
unsafe extern "system" {
    fn GetStdHandle(kind: u32) -> isize;
    fn WriteFile(
        file: isize,
        data: *const u8,
        len: u32,
        written: *mut u32,
        overlapped: *mut c_void,
    ) -> i32;
    fn GetLastError() -> u32;
    fn SetLastError(error: u32);
    fn GetModuleHandleW(name: *const u16) -> isize;
    fn LoadLibraryExW(name: *const u16, file: isize, flags: u32) -> isize;
    fn FreeLibrary(module: isize) -> i32;
    fn GetProcAddress(module: isize, name: *const u8) -> *mut c_void;
    fn GetModuleFileNameW(module: isize, path: *mut u16, capacity: u32) -> u32;
    fn WideCharToMultiByte(
        page: u32,
        flags: u32,
        input: *const u16,
        len: i32,
        output: *mut u8,
        capacity: i32,
        default: *const u8,
        replaced: *mut i32,
    ) -> i32;
    fn ExitProcess(code: u32) -> !;
}

const BCRYPT: &[u16] = &[98, 99, 114, 121, 112, 116, 46, 100, 108, 108, 0];
const PRIMITIVES: &[u16] = &[
    98, 99, 114, 121, 112, 116, 112, 114, 105, 109, 105, 116, 105, 118, 101, 115, 46, 100, 108,
    108, 0,
];
const NTDLL: &[u16] = &[110, 116, 100, 108, 108, 46, 100, 108, 108, 0];
const SYSTEM32_ONLY: u32 = 0x0000_0800;

type LastNtStatus = unsafe extern "system" fn() -> i32;
type GenRandom = unsafe extern "system" fn(*mut c_void, *mut u8, u32, u32) -> i32;

fn write(bytes: &[u8]) {
    let mut offset = 0;
    while offset < bytes.len() {
        let mut count = 0;
        let result = unsafe {
            WriteFile(
                GetStdHandle((-11_i32) as u32),
                bytes.as_ptr().add(offset),
                (bytes.len() - offset) as u32,
                &mut count,
                core::ptr::null_mut(),
            )
        };
        if result == 0 || count == 0 {
            unsafe {
                ExitProcess(/*code*/ 91)
            }
        }
        offset += count as usize;
    }
}

fn number(name: &[u8], value: u32) {
    let mut digits = *b"0x00000000\n";
    for index in 0..8 {
        let value = ((value >> ((7 - index) * 4)) & 15) as u8;
        digits[index + 2] = if value < 10 {
            b'0' + value
        } else {
            b'a' + value - 10
        };
    }
    write(name);
    write(b"=");
    write(&digits);
}

fn module_path(label: &[u8], module: isize) {
    let mut path = [0_u16; 512];
    let length = unsafe { GetModuleFileNameW(module, path.as_mut_ptr(), path.len() as u32) };
    if length == 0 || length as usize >= path.len() {
        number(b"module_path_error", unsafe { GetLastError() });
        return;
    }
    let mut utf8 = [0_u8; 1536];
    let count = unsafe {
        WideCharToMultiByte(
            /*page*/ 65001,
            /*flags*/ 0,
            path.as_ptr(),
            length as i32,
            utf8.as_mut_ptr(),
            utf8.len() as i32,
            core::ptr::null(),
            core::ptr::null_mut(),
        )
    };
    if count <= 0 {
        number(b"module_path_utf8_error", unsafe { GetLastError() });
        return;
    }
    write(label);
    write(b"=");
    write(&utf8[..count as usize]);
    write(b"\n");
}

#[unsafe(no_mangle)]
pub extern "system" fn mainCRTStartup() -> ! {
    write(b"probe_entry=1\n");
    module_path(b"probe_path", /*module*/ 0);
    let ntdll = unsafe { GetModuleHandleW(NTDLL.as_ptr()) };
    let nt_status = unsafe { GetProcAddress(ntdll, c"RtlGetLastNtStatus".as_ptr().cast()) };
    let nt_status = if nt_status.is_null() {
        None
    } else {
        // SAFETY: the named ntdll export has this NTSTATUS-returning ABI.
        Some(unsafe { core::mem::transmute::<*mut c_void, LastNtStatus>(nt_status) })
    };
    number(
        b"bcrypt_preloaded",
        (unsafe { GetModuleHandleW(BCRYPT.as_ptr()) } != 0) as u32,
    );
    number(
        b"primitives_preloaded",
        (unsafe { GetModuleHandleW(PRIMITIVES.as_ptr()) } != 0) as u32,
    );
    unsafe {
        SetLastError(/*error*/ 0)
    };
    let bcrypt = unsafe {
        LoadLibraryExW(BCRYPT.as_ptr(), /*file*/ 0, SYSTEM32_ONLY)
    };
    let error = unsafe { GetLastError() };
    let status = nt_status.map(|get| unsafe { get() });
    number(b"bcrypt_loaded", (bcrypt != 0) as u32);
    number(b"bcrypt_load_win32_error", error);
    if let Some(status) = status {
        number(b"bcrypt_load_last_ntstatus", status as u32);
    }
    if bcrypt != 0 {
        module_path(b"bcrypt_path", bcrypt);
        let random = unsafe { GetProcAddress(bcrypt, c"BCryptGenRandom".as_ptr().cast()) };
        if random.is_null() {
            number(b"rng_symbol_error", unsafe { GetLastError() });
        } else {
            // SAFETY: resolved the named system32 bcrypt export with its exact ABI.
            let random = unsafe { core::mem::transmute::<*mut c_void, GenRandom>(random) };
            let mut bytes = [0_u8; 16];
            let result = unsafe {
                random(
                    core::ptr::null_mut(),
                    bytes.as_mut_ptr(),
                    bytes.len() as u32,
                    /*flags*/ 2,
                )
            };
            // Random bytes are never logged or retained in the diagnostic output.
            for byte in &mut bytes {
                unsafe {
                    core::ptr::write_volatile(byte, /*src*/ 0)
                };
            }
            number(b"system_rng_ntstatus", result as u32);
        }
        unsafe { FreeLibrary(bcrypt) };
    }
    unsafe {
        SetLastError(/*error*/ 0)
    };
    let primitives = unsafe {
        LoadLibraryExW(PRIMITIVES.as_ptr(), /*file*/ 0, SYSTEM32_ONLY)
    };
    let error = unsafe { GetLastError() };
    let status = nt_status.map(|get| unsafe { get() });
    number(b"primitives_loaded", (primitives != 0) as u32);
    number(b"primitives_load_win32_error", error);
    if let Some(status) = status {
        number(b"primitives_load_last_ntstatus", status as u32);
    }
    if primitives != 0 {
        module_path(b"primitives_path", primitives);
        unsafe { FreeLibrary(primitives) };
    }
    write(b"probe_complete=1\n");
    // Completion means observations were emitted, not that CNG authorization passed.
    unsafe {
        ExitProcess(/*code*/ 0)
    }
}

#[panic_handler]
fn panic(_: &core::panic::PanicInfo<'_>) -> ! {
    unsafe {
        ExitProcess(/*code*/ 92)
    }
}

// LLVM may lower zeroing/copies to these symbols. Keep the probe independent of
// the CRT, and use volatile byte accesses so these definitions do not recurse.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn memset(dst: *mut u8, value: i32, size: usize) -> *mut u8 {
    for index in 0..size {
        unsafe { dst.add(index).write_volatile(value as u8) };
    }
    dst
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn memcpy(dst: *mut u8, src: *const u8, size: usize) -> *mut u8 {
    for index in 0..size {
        unsafe {
            dst.add(index)
                .write_volatile(src.add(index).read_volatile())
        };
    }
    dst
}
