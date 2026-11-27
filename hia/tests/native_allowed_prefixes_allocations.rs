//! Count allocations and requested-live-byte peaks separately from timing measurements.

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

#[derive(Clone)]
enum Entry {
    Other,
    Prefix {
        first: String,
        alternatives: Option<Vec<String>>,
        tag: u8,
        metadata: Option<String>,
    },
}

macro_rules! owner {
    ($module:ident, $api:ident) => {
        mod $module {
            use super::*;
            use $api as api;
            #[derive(Debug)]
            struct Other;
            impl api::Rule for Other {
                fn program(&self) -> &str {
                    panic!("unexpected program callback");
                }
                fn matches(&self, _: &[String]) -> Option<api::RuleMatch> {
                    panic!("unexpected matches callback");
                }
                fn as_any(&self) -> &dyn std::any::Any {
                    self
                }
            }
            pub fn policy(
                records: &[Entry],
                hasher: std::collections::hash_map::RandomState,
            ) -> api::Policy {
                let mut rules = multimap::MultiMap::with_hasher(hasher);
                for entry in records {
                    let rule: api::RuleRef = match entry {
                        Entry::Other => std::sync::Arc::new(Other),
                        Entry::Prefix {
                            first,
                            alternatives,
                            tag,
                            metadata,
                        } => std::sync::Arc::new(api::PrefixRule {
                            pattern: api::PrefixPattern {
                                first: std::sync::Arc::from(first.as_str()),
                                rest: alternatives
                                    .as_ref()
                                    .map(|values| vec![api::PatternToken::Alts(values.clone())])
                                    .unwrap_or_default()
                                    .into(),
                            },
                            decision: match tag {
                                0 => api::Decision::Allow,
                                1 => api::Decision::Prompt,
                                2 => api::Decision::Forbidden,
                                _ => panic!("bad fixture tag"),
                            },
                            justification: metadata.clone(),
                        }),
                    };
                    rules.insert("one".to_string(), rule);
                }
                api::Policy::new(rules)
            }
        }
    };
}

owner!(old, original);
owner!(new, candidate);

fn prefix(first: &str, tag: u8) -> Entry {
    Entry::Prefix {
        first: first.into(),
        alternatives: None,
        tag,
        metadata: None,
    }
}

fn main() {
    let (probe, positive_probe) = measured(|| {
        let mut value = Vec::with_capacity(1);
        value.push(1_u8);
        value.reserve_exact(1024);
        black_box(value)
    });
    assert!(positive_probe[0] > 0 && positive_probe[1] > 0);
    drop(probe);
    let large = "x".repeat(2097153);
    let cases = [
        ("empty", vec![], true),
        ("one_other", vec![Entry::Other], true),
        ("many_other", vec![Entry::Other; 65], true),
        ("one_prompt", vec![prefix("p", 1)], true),
        ("one_forbidden", vec![prefix("p", 2)], true),
        ("many_prompt", vec![prefix("p", 1); 65], true),
        (
            "mixed_ignored",
            (0..128)
                .map(|index| prefix("p", 1 + (index % 2) as u8))
                .collect(),
            true,
        ),
        (
            "ignored_large_prompt",
            vec![Entry::Prefix {
                first: large.clone(),
                alternatives: Some(vec![large.clone(); 3]),
                tag: 1,
                metadata: None,
            }],
            true,
        ),
        (
            "ignored_large_forbidden",
            vec![Entry::Prefix {
                first: large.clone(),
                alternatives: Some(vec![large.clone(); 3]),
                tag: 2,
                metadata: None,
            }],
            true,
        ),
        (
            "ignored_large_metadata",
            vec![Entry::Prefix {
                first: "p".into(),
                alternatives: None,
                tag: 1,
                metadata: Some(large.clone()),
            }],
            true,
        ),
        ("empty_allowed_token", vec![prefix("", 0)], false),
        ("frame_511", vec![prefix(&"x".repeat(463), 0)], false),
        ("frame_512", vec![prefix(&"x".repeat(464), 0)], false),
        ("frame_513", vec![prefix(&"x".repeat(465), 0)], false),
        ("selected_12", vec![prefix("", 0); 12], false),
        ("selected_13", vec![prefix("", 0); 13], false),
        ("selected_15", vec![prefix("", 0); 15], false),
        ("selected_16", vec![prefix("", 0); 16], false),
        ("output_512", vec![prefix("", 0); 63], false),
        ("output_520", vec![prefix("", 0); 64], false),
        ("selected_65", vec![prefix("", 0); 65], false),
        (
            "ordinary_alternatives",
            vec![Entry::Prefix {
                first: "git".into(),
                alternatives: Some(vec!["diff".into(), "status".into()]),
                tag: 0,
                metadata: None,
            }],
            false,
        ),
        (
            "empty_alternatives",
            vec![Entry::Prefix {
                first: "p".into(),
                alternatives: Some(vec![]),
                tag: 0,
                metadata: None,
            }],
            false,
        ),
        (
            "allowed_large_metadata",
            vec![Entry::Prefix {
                first: "p".into(),
                alternatives: None,
                tag: 0,
                metadata: Some(large.clone()),
            }],
            false,
        ),
        ("single_large", vec![prefix(&large, 0)], false),
        ("repeated_large", vec![prefix(&large, 0); 4], false),
        (
            "large_alternatives",
            vec![Entry::Prefix {
                first: "p".into(),
                alternatives: Some(vec![large.clone(); 3]),
                tag: 0,
                metadata: None,
            }],
            false,
        ),
    ];
    let mut observations = Vec::new();
    let mut zero_cases = 0;
    for (name, records, expected_zero) in cases {
        let hasher = std::collections::hash_map::RandomState::new();
        let reference = old::policy(&records, hasher.clone());
        let native = new::policy(&records, hasher);
        let (old_result, old_counts) = measured(|| black_box(&reference).get_allowed_prefixes());
        let (new_result, new_counts) = measured(|| black_box(&native).get_allowed_prefixes());
        assert_eq!(new_result, old_result);
        if expected_zero {
            assert_eq!(new_counts, [0; 5]);
            assert_eq!(old_counts, [0; 5]);
            zero_cases += 1;
        } else {
            assert!(new_counts[0] > 0 && old_counts[0] > 0);
        }
        observations.push(
            json!({"case": name, "rules": records.len(), "result_vectors": new_result.len(),
                                 "native": new_counts, "reference": old_counts}),
        );
    }
    let mut reference = original::Policy::empty();
    let mut native = candidate::Policy::empty();
    let command = vec!["p".to_string()];
    for tag in [1, 2, 0, 0] {
        let old_decision = match tag {
            0 => original::Decision::Allow,
            1 => original::Decision::Prompt,
            2 => original::Decision::Forbidden,
            _ => unreachable!(),
        };
        let new_decision = match tag {
            0 => candidate::Decision::Allow,
            1 => candidate::Decision::Prompt,
            2 => candidate::Decision::Forbidden,
            _ => unreachable!(),
        };
        reference
            .add_prefix_rule(&command, old_decision)
            .unwrap_or_else(|error| panic!("fixture: {error}"));
        native
            .add_prefix_rule(&command, new_decision)
            .unwrap_or_else(|error| panic!("fixture: {error}"));
        let (old_result, old_counts) = measured(|| reference.get_allowed_prefixes());
        let (new_result, new_counts) = measured(|| native.get_allowed_prefixes());
        assert_eq!(new_result, old_result);
        if tag != 0 {
            assert_eq!(new_counts, [0; 5]);
            assert_eq!(old_counts, [0; 5]);
            zero_cases += 1;
        }
        observations
            .push(json!({"mutation_tag": tag, "native": new_counts, "reference": old_counts}));
    }
    println!(
        "allowed_prefixes_allocations={}",
        json!({"passed": true, "cases": observations.len(),
        "zero_allocation_cases": zero_cases, "positive_probe": positive_probe, "observations": observations,
        "metric_order": ["allocations", "reallocations", "requested_bytes", "peak_requested_live_bytes", "retained_requested_bytes"],
        "metric_semantics": "logical requested layouts during call; realloc subtracts old then adds new; excludes allocator transient dual buffers and process RSS",
        "scope": "actual public method; construction and assertions outside allocation measurement",
        "performance_qualification": false})
    );
}
