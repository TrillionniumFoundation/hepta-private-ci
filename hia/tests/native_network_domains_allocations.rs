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

macro_rules! policy {
    ($api:ident, $hosts:expr, $tags:expr, $metadata:expr) => {
        $api::Policy::from_parts(
            Default::default(),
            $hosts
                .iter()
                .zip($tags)
                .enumerate()
                .map(|(index, (host, tag))| $api::rule::NetworkRule {
                    host: host.clone(),
                    decision: match tag {
                        0 => $api::Decision::Allow,
                        1 => $api::Decision::Prompt,
                        2 => $api::Decision::Forbidden,
                        _ => panic!("invalid fixture decision"),
                    },
                    protocol: match index % 4 {
                        0 => $api::NetworkRuleProtocol::Http,
                        1 => $api::NetworkRuleProtocol::Https,
                        2 => $api::NetworkRuleProtocol::Socks5Tcp,
                        _ => $api::NetworkRuleProtocol::Socks5Udp,
                    },
                    justification: Some($metadata.to_string()),
                })
                .collect(),
            Default::default(),
        )
    };
}

fn main() {
    let (probe, probe_metrics) = measured(|| {
        let mut data = Vec::with_capacity(1);
        data.push(7_u8);
        black_box(&data);
        data.reserve_exact(1024);
        data.push(9);
        black_box(data)
    });
    assert_eq!(probe.len(), 2);
    assert!(probe_metrics[0] > 0 && probe_metrics[1] > 0 && probe_metrics[3] > 0);
    let mut cases = Vec::new();
    for length in [0, 1, 63, 64, 65, 4097] {
        cases.push((
            format!("all_prompt_{length}"),
            vec!["host".to_string(); length],
            vec![1_u8; length],
            String::new(),
            true,
        ));
    }
    let giant = "x".repeat(2097153);
    cases.push((
        "all_prompt_large_hosts".into(),
        vec![giant.clone(); 4],
        vec![1; 4],
        String::new(),
        true,
    ));
    cases.push((
        "all_prompt_large_metadata".into(),
        vec!["x".into(); 2],
        vec![1; 2],
        giant.clone(),
        true,
    ));
    for bytes in [463, 464, 465] {
        cases.push((
            format!("frame_{}", 48 + bytes),
            vec!["x".repeat(bytes)],
            vec![0],
            String::new(),
            false,
        ));
    }
    cases.push((
        "empty_host".into(),
        vec![String::new()],
        vec![0],
        String::new(),
        false,
    ));
    for length in [31, 32, 33, 62, 63, 512, 513] {
        cases.push((
            format!("selected_{length}"),
            vec![String::new(); length],
            vec![0; length],
            String::new(),
            false,
        ));
    }
    cases.push((
        "ordinary_success".into(),
        vec!["a".into(), "b".into(), "c".into()],
        vec![0, 2, 0],
        String::new(),
        false,
    ));
    cases.push((
        "repeated_large_host".into(),
        vec![giant; 4],
        vec![0; 4],
        String::new(),
        false,
    ));
    let mut observations = Vec::new();
    let mut zero_cases = 0;
    for (name, hosts, tags, metadata, zero) in cases {
        let original = policy!(original, hosts, &tags, metadata);
        let native = policy!(candidate, hosts, &tags, metadata);
        let reference = measured(|| black_box(&original).compiled_network_domains());
        let actual = measured(|| black_box(&native).compiled_network_domains());
        assert_eq!(actual.0, reference.0);
        if zero {
            assert_eq!(reference.1, [0; 5]);
            assert_eq!(actual.1, [0; 5]);
            zero_cases += 1;
        }
        match name.as_str() {
            "frame_511" | "frame_512" => assert_eq!(actual.1[0], 2),
            "frame_513" => assert_eq!(actual.1[0], 3),
            "empty_host" => assert_eq!(actual.1[0], 1),
            _ => {}
        }
        let selected: Vec<_> = hosts
            .iter()
            .zip(&tags)
            .filter(|(_, tag)| **tag != 1)
            .collect();
        let frame = if selected.is_empty() {
            0
        } else {
            24 + 24 * selected.len() + selected.iter().map(|(host, _)| host.len()).sum::<usize>()
        };
        observations.push(json!({
            "case": name, "rule_count": hosts.len(), "selected_count": selected.len(),
            "host_bytes": hosts.iter().map(String::len).sum::<usize>(),
            "metadata_bytes_per_rule": metadata.len(), "frame_bytes": frame,
            "native": actual.1, "reference": reference.1,
            "result_lengths": [actual.0.0.len(), actual.0.1.len()]
        }));
    }
    let mut mutable = candidate::Policy::empty();
    for decision in [
        candidate::Decision::Prompt,
        candidate::Decision::Prompt,
        candidate::Decision::Allow,
        candidate::Decision::Forbidden,
    ] {
        mutable
            .add_network_rule(
                "a",
                candidate::NetworkRuleProtocol::Https,
                decision,
                /*justification*/ None,
            )
            .unwrap_or_else(|error| panic!("{error}"));
        let actual = measured(|| black_box(&mutable).compiled_network_domains());
        if mutable.network_rules().len() <= 2 {
            assert_eq!(actual.1, [0; 5]);
            assert_eq!(actual.0, (vec![], vec![]));
            zero_cases += 1;
        } else {
            assert_eq!(actual.1[0], 2);
            let expected = if decision == candidate::Decision::Allow {
                (vec!["a".to_string()], vec![])
            } else {
                (vec![], vec!["a".to_string()])
            };
            assert_eq!(actual.0, expected);
        }
        observations.push(
            json!({"mutation_rule_count": mutable.network_rules().len(), "native": actual.1}),
        );
    }
    println!(
        "network_domains_allocations={}",
        json!({
            "passed": true, "cases": observations.len(), "zero_allocation_cases": zero_cases,
            "metric_order": ["allocations", "reallocations", "requested_bytes", "peak_requested_live_bytes", "retained_requested_bytes"],
            "metric_semantics": "logical requested layouts during the call; realloc subtracts old then adds new; excludes allocator transient dual buffers and process RSS",
            "positive_probe": probe_metrics, "observations": observations,
            "scope": "actual public method; construction/assertions outside measurement; single-thread allocator probe",
            "performance_qualification": false
        })
    );
}
