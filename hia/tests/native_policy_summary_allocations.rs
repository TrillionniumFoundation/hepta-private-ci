//! Allocation instrumentation is isolated from public differential timings.

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

unsafe impl GlobalAlloc for Counted {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        if ACTIVE.load(Ordering::Relaxed) {
            ALLOCATIONS.fetch_add(1, Ordering::Relaxed);
        }
        // SAFETY: forward the allocator's exact layout to System.
        unsafe { System.alloc(layout) }
    }
    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        if ACTIVE.load(Ordering::Relaxed) {
            ALLOCATIONS.fetch_add(1, Ordering::Relaxed);
        }
        // SAFETY: forward the allocator's exact layout to System.
        unsafe { System.alloc_zeroed(layout) }
    }
    unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
        // SAFETY: forward the allocation and its original layout to System.
        unsafe { System.dealloc(pointer, layout) }
    }
    unsafe fn realloc(&self, pointer: *mut u8, layout: Layout, size: usize) -> *mut u8 {
        if ACTIVE.load(Ordering::Relaxed) {
            REALLOCATIONS.fetch_add(1, Ordering::Relaxed);
        }
        // SAFETY: forward the valid allocation, layout and requested size.
        unsafe { System.realloc(pointer, layout, size) }
    }
}

fn measured(call: impl FnOnce() -> bool) -> (bool, usize, usize) {
    assert!(!ACTIVE.load(Ordering::Relaxed));
    ALLOCATIONS.store(0, Ordering::Relaxed);
    REALLOCATIONS.store(0, Ordering::Relaxed);
    ACTIVE.store(true, Ordering::Relaxed);
    let result = call();
    ACTIVE.store(false, Ordering::Relaxed);
    (
        result,
        ALLOCATIONS.load(Ordering::Relaxed),
        REALLOCATIONS.load(Ordering::Relaxed),
    )
}

macro_rules! evaluation {
    ($owner:ident, $tags:expr, $payload:expr) => {
        $owner::Evaluation {
            decision: $owner::Decision::Forbidden,
            matched_rules: $tags
                .iter()
                .map(|kind| {
                    if *kind == 0 {
                        $owner::RuleMatch::PrefixRuleMatch {
                            matched_prefix: vec![$payload.to_string(), "".into()],
                            decision: $owner::Decision::Allow,
                            resolved_program: None,
                            justification: Some($payload.to_string()),
                        }
                    } else {
                        $owner::RuleMatch::HeuristicsRuleMatch {
                            command: vec![$payload.to_string()],
                            decision: $owner::Decision::Prompt,
                        }
                    }
                })
                .collect(),
        }
    };
}

fn main() {
    let probe = measured(|| {
        let mut data = Vec::<u8>::with_capacity(1);
        data.push(7);
        black_box(&data);
        data.reserve_exact(1024);
        data.push(9);
        black_box(data).len() == 2
    });
    assert!(
        probe.0 && probe.1 > 0 && probe.2 > 0,
        "positive allocation/reallocation probe failed"
    );
    let mut rows = Vec::new();
    for length in [0, 1, 2, 31, 32, 33] {
        for placement in ["none", "first", "last"] {
            let mut tags = vec![1; length];
            if length > 0 && placement != "none" {
                tags[if placement == "first" { 0 } else { length - 1 }] = 0;
            }
            let original = evaluation!(original, tags, "é\0汉e\u{301}");
            let native = evaluation!(candidate, tags, "é\0汉e\u{301}");
            let reference = measured(|| black_box(&original).is_match());
            let actual = measured(|| black_box(&native).is_match());
            assert_eq!(reference, (original.is_match(), 0, 0));
            assert_eq!(actual, (reference.0, usize::from(length > 31), 0));
            rows.push(json!({"length": length, "frame_bytes": 8 + length * 16,
                             "placement": placement, "native": actual, "reference": reference}));
        }
    }
    let mut mutable = evaluation!(candidate, vec![1; 31], "");
    for length in [32, 31, 0, 1, 33, 31] {
        mutable.matched_rules = evaluation!(candidate, vec![1; length], "").matched_rules;
        mutable.decision = candidate::Decision::Allow;
        let actual = measured(|| black_box(&mutable).is_match());
        assert_eq!(actual, (false, usize::from(length > 31), 0));
        rows.push(json!({"mutation_length": length, "native": actual}));
        if length > 0 {
            mutable.matched_rules[0] = evaluation!(candidate, [0], "").matched_rules.remove(0);
            let actual = measured(|| black_box(&mutable).is_match());
            assert_eq!(actual, (true, usize::from(length > 31), 0));
            rows.push(json!({"mutation_prefix_length": length, "native": actual}));
        }
    }
    let payload = "é\0汉".repeat(524289);
    let native = evaluation!(candidate, [0], payload);
    let actual = measured(|| black_box(&native).is_match());
    assert_eq!(actual, (true, 0, 0));
    rows.push(json!({"large_metadata_bytes": payload.len(), "native": actual}));
    let zero = rows
        .iter()
        .filter(|row| row["native"][1] == 0 && row["native"][2] == 0)
        .count();
    println!(
        "policy_summary_allocations={}",
        json!({
            "passed": true, "cases": rows.len(), "zero_allocation_cases": zero,
            "positive_probe": probe, "observations": rows,
            "scope": "actual mutable public Evaluation::is_match; construction and assertions outside measurement",
        })
    );
}
