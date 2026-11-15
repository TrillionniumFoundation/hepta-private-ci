//! Count allocations and requested-live-byte peaks separately from timing measurements.

#[macro_use]
mod command_dispatch_fixtures;
use command_dispatch_fixtures::Case;
use command_dispatch_fixtures::scenarios;
use serde_json::json;
use std::alloc::GlobalAlloc;
use std::alloc::Layout;
use std::alloc::System;
use std::hint::black_box;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

struct Counted;
#[global_allocator]
static ALLOCATOR: Counted = Counted;
static ACTIVE: AtomicBool = AtomicBool::new(false);
static ALLOCATIONS: AtomicUsize = AtomicUsize::new(0);
static REALLOCATIONS: AtomicUsize = AtomicUsize::new(0);
static REQUESTED: AtomicUsize = AtomicUsize::new(0);
static LIVE: AtomicUsize = AtomicUsize::new(0);
static PEAK: AtomicUsize = AtomicUsize::new(0);

fn allocated(size: usize) {
    if ACTIVE.load(Ordering::Relaxed) {
        ALLOCATIONS.fetch_add(1, Ordering::Relaxed);
        REQUESTED.fetch_add(size, Ordering::Relaxed);
        let live = LIVE.fetch_add(size, Ordering::Relaxed) + size;
        PEAK.fetch_max(live, Ordering::Relaxed);
    }
}

unsafe impl GlobalAlloc for Counted {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        allocated(layout.size());
        // SAFETY: preserve the allocator's requested layout.
        unsafe { System.alloc(layout) }
    }
    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        allocated(layout.size());
        // SAFETY: preserve the allocator's requested layout.
        unsafe { System.alloc_zeroed(layout) }
    }
    unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
        if ACTIVE.load(Ordering::Relaxed) {
            LIVE.fetch_sub(layout.size(), Ordering::Relaxed);
        }
        // SAFETY: preserve the allocation and its original layout.
        unsafe { System.dealloc(pointer, layout) }
    }
    unsafe fn realloc(&self, pointer: *mut u8, layout: Layout, size: usize) -> *mut u8 {
        if ACTIVE.load(Ordering::Relaxed) {
            REALLOCATIONS.fetch_add(1, Ordering::Relaxed);
            REQUESTED.fetch_add(size, Ordering::Relaxed);
            LIVE.fetch_sub(layout.size(), Ordering::Relaxed);
            let live = LIVE.fetch_add(size, Ordering::Relaxed) + size;
            PEAK.fetch_max(live, Ordering::Relaxed);
        }
        // SAFETY: forward the original allocation and requested new size.
        unsafe { System.realloc(pointer, layout, size) }
    }
}

fn measured<T>(call: impl FnOnce() -> T) -> (T, [usize; 5]) {
    assert!(!ACTIVE.load(Ordering::Relaxed));
    for counter in [&ALLOCATIONS, &REALLOCATIONS, &REQUESTED, &LIVE, &PEAK] {
        counter.store(0, Ordering::Relaxed);
    }
    ACTIVE.store(true, Ordering::Relaxed);
    let result = call();
    ACTIVE.store(false, Ordering::Relaxed);
    (
        result,
        [&ALLOCATIONS, &REALLOCATIONS, &REQUESTED, &PEAK, &LIVE]
            .map(|counter| counter.load(Ordering::Relaxed)),
    )
}

dispatch_owner!(old, original);
dispatch_owner!(new, candidate);

fn main() {
    let (probe, metrics) = measured(|| {
        let mut bytes = Vec::with_capacity(1);
        bytes.push(1_u8);
        black_box(&bytes);
        bytes.reserve_exact(1024);
        black_box(bytes)
    });
    assert_eq!(probe.len(), 1);
    assert!(metrics[0] > 0 && metrics[1] > 0);
    let mut cases = scenarios();
    cases.push((
        "empty-exact-bucket",
        Case {
            buckets: vec![("tool".into(), vec![])],
            fallback: None,
            ..Case::default()
        },
    ));
    cases.push((
        "first-path-match-giant-unvisited",
        Case {
            command: vec!["/opt/tool".into()],
            buckets: vec![("tool".into(), vec![1])],
            host_paths: vec![(
                "tool".into(),
                vec![
                    "/opt/tool".into(),
                    format!("/{}", "x".repeat(1 << 20)).into(),
                ],
            )],
            resolve: true,
            ..Case::default()
        },
    ));
    for length in [7, 8, 9, 90, 91, 127, 128, 129, 1024, 1 << 20] {
        let path = format!("/{}/tool", "x".repeat(length));
        cases.push((
            "path-transport-length",
            Case {
                command: vec![path.clone(), "".into()],
                buckets: vec![("tool".into(), vec![0])],
                host_paths: vec![("tool".into(), vec![path.into()])],
                resolve: true,
                fallback: None,
                ..Case::default()
            },
        ));
    }
    let mut results = Vec::new();
    let mut zero = 0;
    for (label, case) in cases {
        let old_policy = old::policy(&case, None);
        let new_policy = new::policy(&case, None);
        let (expected, reference) =
            measured(|| old::matches(black_box(&old_policy), black_box(&case)));
        let (actual, native) = measured(|| new::matches(black_box(&new_policy), black_box(&case)));
        assert_eq!(
            serde_json::to_value(&actual).unwrap(),
            serde_json::to_value(&expected).unwrap(),
            "{label}"
        );
        if reference[0] == 0 && reference[1] == 0 {
            assert_eq!(
                &native[..2],
                &[0, 0],
                "constant-size transport introduced heap allocation: {label}"
            );
            zero += 1;
        }
        results.push(json!({"case": label, "command_bytes": case.command.iter().map(String::len).sum::<usize>(),
            "reference": reference, "native": native, "matches": actual.len()}));
    }
    let command = vec!["unknown".to_owned(), "x".repeat(8192), "".into()];
    let minimum_clone_bytes = command.len() * std::mem::size_of::<String>()
        + command.iter().map(String::len).sum::<usize>();
    let mut clone_observations = Vec::new();
    macro_rules! clone_before {
        ($api:ident) => {{
            let policy = $api::Policy::empty();
            let observed = std::cell::Cell::new([0_usize; 3]);
            let callback = |_: &[String]| {
                observed.set([ALLOCATIONS.load(Ordering::Relaxed), LIVE.load(Ordering::Relaxed), PEAK.load(Ordering::Relaxed)]);
                $api::Decision::Prompt
            };
            let (result, metrics) = measured(|| policy.matches_for_command(&command, Some(&callback)));
            assert_eq!(result.len(), 1);
            assert!(observed.get()[1] >= minimum_clone_bytes, "callback ran before command clone");
            clone_observations.push(json!({"owner": stringify!($api), "at_callback": observed.get(), "final": metrics}));
        }};
    }
    clone_before!(original);
    clone_before!(candidate);
    println!(
        "command_dispatch_allocations={}",
        json!({"passed": true, "cases": results.len(), "zero_allocation_cases": zero,
        "positive_probe": metrics, "observations": results, "clone_before_callback": clone_observations, "skipped": 0,
        "metric_order": ["allocations", "reallocations", "requested_bytes", "peak_requested_live_bytes", "retained_requested_live_bytes"],
        "scope": "allocation calls and logical requested-live bytes during the call; excludes fixture construction; not RSS or allocator transient realloc overlap"})
    );
}
