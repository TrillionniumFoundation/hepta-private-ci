// One actual owner per executable; instrumentation does not enter timing probes.
include!("network_host_fixtures.rs");

use std::alloc::GlobalAlloc;
use std::alloc::Layout;
use std::alloc::System;
use std::cell::Cell;
use std::hint::black_box;

network_host_owner!(measured_owner, owner);

#[derive(Clone, Copy, Debug, Default)]
struct Counts {
    allocations: usize,
    reallocations: usize,
    deallocations: usize,
    requested: usize,
    live: usize,
    peak: usize,
    untracked_releases: usize,
}

thread_local! {
    static COUNTS: Cell<Option<Counts>> = const { Cell::new(None) };
}

struct CountingAllocator;

fn allocated(old: usize, new: usize, reallocation: bool) {
    let _ = COUNTS.try_with(|cell| {
        if let Some(mut counts) = cell.get() {
            counts.allocations += usize::from(!reallocation);
            counts.reallocations += usize::from(reallocation);
            counts.requested += new;
            if old > counts.live {
                counts.untracked_releases += 1;
            }
            counts.live = counts.live.saturating_sub(old) + new;
            counts.peak = counts.peak.max(counts.live);
            cell.set(Some(counts));
        }
    });
}

unsafe impl GlobalAlloc for CountingAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        let pointer = unsafe { System.alloc(layout) };
        if !pointer.is_null() {
            allocated(0, layout.size(), false);
        }
        pointer
    }

    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        let pointer = unsafe { System.alloc_zeroed(layout) };
        if !pointer.is_null() {
            allocated(0, layout.size(), false);
        }
        pointer
    }

    unsafe fn realloc(&self, pointer: *mut u8, old: Layout, new: usize) -> *mut u8 {
        let result = unsafe { System.realloc(pointer, old, new) };
        if !result.is_null() {
            allocated(old.size(), new, true);
        }
        result
    }

    unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
        let _ = COUNTS.try_with(|cell| {
            if let Some(mut counts) = cell.get() {
                counts.deallocations += 1;
                if layout.size() > counts.live {
                    counts.untracked_releases += 1;
                }
                counts.live = counts.live.saturating_sub(layout.size());
                cell.set(Some(counts));
            }
        });
        unsafe { System.dealloc(pointer, layout) };
    }
}

#[global_allocator]
static ALLOCATOR: CountingAllocator = CountingAllocator;

fn measured<T>(call: impl FnOnce() -> T) -> (T, Counts) {
    COUNTS.with(|cell| {
        assert!(cell.get().is_none());
        cell.set(Some(Counts::default()));
    });
    let result = call();
    let counts = COUNTS
        .with(|cell| cell.take())
        .unwrap_or_else(|| panic!("allocation measurement was not initialized"));
    assert_eq!(
        counts.untracked_releases, 0,
        "fixture dropped an allocation made before measurement"
    );
    (result, counts)
}

fn main() {
    let label = std::env::args()
        .nth(1)
        .unwrap_or_else(|| panic!("baseline label is required"));
    let (probe, counts) = measured(|| {
        let mut bytes = Vec::with_capacity(7);
        bytes.extend_from_slice(&[1_u8; 7]);
        bytes.reserve_exact(17);
        black_box(bytes.as_ptr());
        bytes
    });
    assert!(counts.allocations > 0 && counts.reallocations > 0 && counts.peak >= 24);
    black_box(probe);
    let mut rows = Vec::new();
    for (name, raw) in host_samples() {
        let mut policy = measured_owner::prepared();
        let (result, counts) =
            measured(|| measured_owner::append(black_box(&mut policy), black_box(&raw), None));
        rows.push(serde_json::json!({"case": name, "raw_bytes": raw.len(),
            "result": result.map_err(measured_owner::error), "rules": measured_owner::snapshot(&policy),
            "allocations": counts.allocations, "reallocations": counts.reallocations,
            "deallocations": counts.deallocations, "requested_bytes": counts.requested,
            "requested_live_at_return_bytes": counts.live, "peak_requested_live_bytes": counts.peak,
            "untracked_releases": counts.untracked_releases}));
    }
    println!(
        "network_host_allocations={}",
        serde_json::json!({"passed": true, "label": label,
        "rows": rows, "positive_probe": {"allocations": counts.allocations,
            "reallocations": counts.reallocations, "peak_requested_live_bytes": counts.peak},
        "skipped": 0, "performance_qualification": false,
        "scope": "System allocator requested layouts during one actual public add_network_rule call; raw String and empty Policy with one reserved rule slot constructed outside measurement; returned allocations retained until after measurement. Realloc subtracts old before adding new, so this is neither RSS nor transient simultaneous allocator storage."})
    );
}
