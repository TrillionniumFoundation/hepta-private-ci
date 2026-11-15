//! Fixed-capacity private memory for the CRT-free diagnostic.
use core::ffi::c_void;

use super::number;
use super::ExitProcess;
use super::GetLastError;

#[link(name = "kernel32")]
unsafe extern "system" {
    fn VirtualAlloc(address: *mut c_void, size: usize, kind: u32, protection: u32) -> *mut c_void;
    fn VirtualFree(address: *mut c_void, size: usize, kind: u32) -> i32;
}

pub(super) struct BoundedMemory(*mut c_void);

impl BoundedMemory {
    pub(super) fn new(size: usize) -> Option<Self> {
        // All callers have fixed capacities. Reject an accidental expansion;
        // this does not replace a large stack frame with unbounded allocation.
        if !(1..=4096).contains(&size) {
            number(b"probe_allocation_invalid_size", /*value*/ 1);
            return None;
        }
        // VirtualAlloc provides zeroed, page-aligned, non-executable memory in
        // this process. No allocator DLL, extra handle, or security change.
        let pointer = unsafe {
            VirtualAlloc(
                core::ptr::null_mut(),
                size,
                /*RESERVE | COMMIT*/ 0x3000,
                /*READWRITE*/ 4,
            )
        };
        if pointer.is_null() {
            number(b"probe_allocation_win32_error", unsafe { GetLastError() });
            None
        } else {
            Some(Self(pointer))
        }
    }

    pub(super) fn as_ptr(&self) -> *mut c_void {
        self.0
    }
}

impl Drop for BoundedMemory {
    fn drop(&mut self) {
        // Exactly one non-Copy guard owns the original base. Every borrowed
        // slice is consumed before this releases its whole reserved region.
        if unsafe {
            VirtualFree(self.0, /*size*/ 0, /*MEM_RELEASE*/ 0x8000)
        } == 0
        {
            number(b"probe_release_win32_error", unsafe { GetLastError() });
            // A failed release is not reported as a completed observation.
            unsafe {
                ExitProcess(/*code*/ 93)
            }
        }
    }
}
