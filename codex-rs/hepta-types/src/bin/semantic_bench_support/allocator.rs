//! Single-thread diagnostic allocation traffic, not allocator footprint or RSS.
//! This module is linked only into the benchmark executable, never the library.
use std::alloc::GlobalAlloc;
use std::alloc::Layout;
use std::alloc::System;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

pub struct TrafficAllocator;
static ACTIVE: AtomicBool = AtomicBool::new(false);
static CALLS: AtomicUsize = AtomicUsize::new(0);
static REALLOCS: AtomicUsize = AtomicUsize::new(0);
static BYTES: AtomicUsize = AtomicUsize::new(0);

fn record(size: usize, reallocation: bool) {
    if ACTIVE.load(Ordering::Relaxed) {
        CALLS.fetch_add(1, Ordering::Relaxed);
        BYTES.fetch_add(size, Ordering::Relaxed);
        if reallocation {
            REALLOCS.fetch_add(1, Ordering::Relaxed);
        }
    }
}

// SAFETY: All pointers/layouts are forwarded unchanged to System. Observation
// uses only non-allocating atomics and does not change allocation ownership.
unsafe impl GlobalAlloc for TrafficAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        // SAFETY: The caller supplies the GlobalAlloc layout contract.
        let pointer = unsafe { System.alloc(layout) };
        if !pointer.is_null() {
            record(layout.size(), /*reallocation*/ false);
        }
        pointer
    }

    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        // SAFETY: The caller supplies the GlobalAlloc layout contract.
        let pointer = unsafe { System.alloc_zeroed(layout) };
        if !pointer.is_null() {
            record(layout.size(), /*reallocation*/ false);
        }
        pointer
    }

    unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
        // SAFETY: This allocator forwards the original pointer and layout.
        unsafe { System.dealloc(pointer, layout) };
    }

    unsafe fn realloc(&self, pointer: *mut u8, layout: Layout, size: usize) -> *mut u8 {
        // SAFETY: The caller guarantees that pointer/layout name a live block.
        let pointer = unsafe { System.realloc(pointer, layout, size) };
        if !pointer.is_null() {
            record(size, /*reallocation*/ true);
        }
        pointer
    }
}

pub struct Measurement;

impl Measurement {
    pub fn start() -> Self {
        CALLS.store(0, Ordering::Relaxed);
        REALLOCS.store(0, Ordering::Relaxed);
        BYTES.store(0, Ordering::Relaxed);
        ACTIVE.store(true, Ordering::Relaxed);
        Self
    }

    pub fn finish(self) -> (usize, usize, usize) {
        ACTIVE.store(false, Ordering::Relaxed);
        (
            CALLS.load(Ordering::Relaxed),
            REALLOCS.load(Ordering::Relaxed),
            BYTES.load(Ordering::Relaxed),
        )
    }
}

impl Drop for Measurement {
    fn drop(&mut self) {
        ACTIVE.store(false, Ordering::Relaxed);
    }
}
