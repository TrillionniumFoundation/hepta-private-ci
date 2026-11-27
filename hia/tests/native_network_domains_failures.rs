//! Inject malformed callee results into the production adapter.
//! The separate raw ABI gate executes real HIA; this executable substitutes it.

pub use original::Decision;
pub mod rule {
    pub use original::rule::NetworkRule;
}
#[path = "../../codex-rs/execpolicy/src/hia_native_network_domains.rs"]
mod hia_native_network_domains;

use std::panic::AssertUnwindSafe;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

static CASE: AtomicUsize = AtomicUsize::new(0);
static SELECT_CALLS: AtomicUsize = AtomicUsize::new(0);
static REDUCE_CALLS: AtomicUsize = AtomicUsize::new(0);

fn word(bytes: &[u8], at: usize) -> u64 {
    u64::from_le_bytes(
        bytes[at..at + 8]
            .try_into()
            .unwrap_or_else(|_| panic!("fixture word is incomplete")),
    )
}

fn put(bytes: &mut [u8], at: usize, value: u64) {
    bytes[at..at + 8].copy_from_slice(&value.to_le_bytes());
}

#[unsafe(no_mangle)]
unsafe extern "C" fn codex_hia_network_domains(
    source: *const u8,
    source_length: u64,
    output: *mut u8,
    output_capacity: u64,
    _workspace: *mut u8,
    workspace_length: u64,
) -> u64 {
    assert!(source_length >= 16);
    // SAFETY: the actual adapter lends complete initialized source/output arrays.
    let source = unsafe { std::slice::from_raw_parts(source, source_length as usize) };
    // SAFETY: this mock writes only within the actual adapter's output extent.
    let output = unsafe { std::slice::from_raw_parts_mut(output, output_capacity as usize) };
    let case = CASE.load(Ordering::Relaxed);
    if word(source, 0) == 0 {
        SELECT_CALLS.fetch_add(1, Ordering::Relaxed);
        let count = word(source, 8) as usize;
        assert!(count <= 64);
        assert_eq!(source.len(), 16 + count);
        assert_eq!(output.len(), 72);
        assert_eq!(workspace_length, 0);
        assert!(source[16..].iter().all(|tag| *tag <= 2));
        if (1..=3).contains(&case) {
            return [0, 0xFFFF_FFFF, 0xFFFF_FFFE, 99][case];
        }
        if case == 9 {
            return 0;
        }
        let mut selected: Vec<u8> = source[16..]
            .iter()
            .enumerate()
            .filter_map(|(index, tag)| (*tag != 1).then_some(index as u8))
            .collect();
        match case {
            4 => {
                put(output, 0, 65);
                return 0;
            }
            5 => selected = vec![255],
            6 => selected = vec![1],
            7 => selected = vec![0, 0],
            8 => selected = vec![2, 0],
            _ => {}
        }
        put(output, 0, selected.len() as u64);
        output[8..8 + selected.len()].copy_from_slice(&selected);
        return 0;
    }
    REDUCE_CALLS.fetch_add(1, Ordering::Relaxed);
    assert_eq!(word(source, 0), 1);
    assert_eq!(word(source, 8), 4);
    assert_eq!(word(source, 16), 3);
    assert_eq!(workspace_length, 3);
    assert_eq!(output.len(), 40);
    let mut expected = [1_u64, 4, 3]
        .into_iter()
        .flat_map(u64::to_le_bytes)
        .collect::<Vec<_>>();
    for (index, tag, host) in [(0_u64, 0_u64, b'A'), (2, 2, b'B'), (3, 0, b'C')] {
        for value in [index, tag, 1] {
            expected.extend_from_slice(&value.to_le_bytes());
        }
        expected.push(host);
    }
    assert_eq!(
        source, expected,
        "Prompt host or metadata entered REDUCE transport"
    );
    match case {
        20 => return 0xFFFF_FFFF,
        21 => return 0xFFFF_FFFE,
        22 => return 0xFFFF_FFFD,
        23 => return 99,
        32 => return 0,
        _ => {}
    }
    let (mut allowed, mut denied, mut indices) = (2, 1, [0, 3, 2]);
    match case {
        24 => {
            allowed = u64::MAX;
            denied = 1;
        }
        25 => allowed = 4,
        26 => {
            allowed = 0;
            denied = 0;
        }
        27 => indices[0] = 99,
        28 => indices[0] = 1,
        29 => indices[1] = 0,
        30 => indices.swap(0, 1),
        31 => indices[0] = 2,
        33 => indices[1] = 2,
        _ => {}
    }
    put(output, 0, allowed);
    put(output, 8, denied);
    for (position, index) in indices.into_iter().enumerate() {
        put(output, 16 + position * 8, index);
    }
    0
}

fn main() {
    let inputs = [
        ("A".to_string(), Decision::Allow),
        (
            "PROMPT-HOST-DO-NOT-TRANSPORT".repeat(8192),
            Decision::Prompt,
        ),
        ("B".to_string(), Decision::Forbidden),
        ("C".to_string(), Decision::Allow),
    ]
    .into_iter()
    .map(|(host, decision)| rule::NetworkRule {
        host,
        decision,
        protocol: original::NetworkRuleProtocol::Https,
        justification: Some("METADATA-DO-NOT-TRANSPORT".repeat(1024)),
    })
    .collect::<Vec<_>>();
    let expected = (
        vec!["A".to_string(), "C".to_string()],
        vec!["B".to_string()],
    );
    assert_eq!(hia_native_network_domains::compile(&inputs), expected);
    let mut observations = Vec::new();
    for (case, label) in [
        (1, "select-invalid-status"),
        (2, "select-short-status"),
        (3, "select-unknown-status"),
        (4, "select-count"),
        (5, "select-out-of-range"),
        (6, "select-prompt"),
        (7, "select-duplicate"),
        (8, "select-descending"),
        (9, "select-unwritten"),
        (20, "reduce-invalid-status"),
        (21, "reduce-short-output"),
        (22, "reduce-short-workspace"),
        (23, "reduce-unknown-status"),
        (24, "reduce-count-overflow"),
        (25, "reduce-count-too-large"),
        (26, "reduce-empty"),
        (27, "reduce-out-of-range"),
        (28, "reduce-unselected"),
        (29, "reduce-duplicate"),
        (30, "reduce-descending"),
        (31, "reduce-wrong-decision"),
        (32, "reduce-unwritten"),
        (33, "reduce-overlap"),
    ] {
        CASE.store(case, Ordering::Relaxed);
        let result = std::panic::catch_unwind(AssertUnwindSafe(|| {
            hia_native_network_domains::compile(&inputs)
        }));
        let Err(error) = result else {
            panic!("malformed callee result became a successful domain list");
        };
        let message = error
            .downcast_ref::<String>()
            .cloned()
            .or_else(|| error.downcast_ref::<&str>().map(|value| value.to_string()))
            .unwrap_or_else(|| panic!("non-textual contract panic"));
        assert!(
            message.contains("HIA network"),
            "{label}: unrelated panic: {message}"
        );
        observations.push(serde_json::json!({"case": label, "panic": message}));
    }
    CASE.store(0, Ordering::Relaxed);
    let select_before = SELECT_CALLS.load(Ordering::Relaxed);
    let reduce_before = REDUCE_CALLS.load(Ordering::Relaxed);
    for count in [0, 1, 64, 65, 129] {
        let prompts = (0..count)
            .map(|_| rule::NetworkRule {
                host: "DO-NOT-TRANSPORT".into(),
                decision: Decision::Prompt,
                protocol: original::NetworkRuleProtocol::Socks5Udp,
                justification: Some("IGNORE".into()),
            })
            .collect::<Vec<_>>();
        assert_eq!(
            hia_native_network_domains::compile(&prompts),
            (vec![], vec![])
        );
    }
    assert_eq!(REDUCE_CALLS.load(Ordering::Relaxed), reduce_before);
    assert_eq!(SELECT_CALLS.load(Ordering::Relaxed) - select_before, 8);
    println!(
        "network_domains_failures={}",
        serde_json::json!({
            "passed": true, "cases": observations.len(), "observations": observations,
            "select_calls": SELECT_CALLS.load(Ordering::Relaxed),
            "reduce_calls": REDUCE_CALLS.load(Ordering::Relaxed),
            "prompt_transport_cases": 5,
            "scope": "production adapter with injected callee results; transport payload and errors; no real HIA qualification"
        })
    );
}
