// This executable replaces only the new callee and exercises the actual adapter.
mod error {
    pub use original::Error;
    pub use original::Result;
}
#[path = "../../codex-rs/execpolicy/src/hia_native_network_host.rs"]
mod hia_native_network_host;

use std::panic::AssertUnwindSafe;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

static CASE: AtomicUsize = AtomicUsize::new(0);
static CALLS: AtomicUsize = AtomicUsize::new(0);
static RAW_POINTER: AtomicUsize = AtomicUsize::new(0);
static RAW_LENGTH: AtomicUsize = AtomicUsize::new(0);

#[unsafe(no_mangle)]
unsafe extern "C" fn codex_hia_network_host(
    source: *const u8,
    source_length: u64,
    output: *mut u8,
    output_capacity: u64,
    workspace: *mut u8,
    workspace_length: u64,
) -> u64 {
    assert_eq!(source as usize, RAW_POINTER.load(Ordering::Relaxed));
    assert_eq!(source_length as usize, RAW_LENGTH.load(Ordering::Relaxed));
    assert_eq!(workspace_length, 32);
    let control = unsafe { std::slice::from_raw_parts_mut(workspace, 32) };
    let mode = u64::from_le_bytes(control[8..16].try_into().expect("control mode width"));
    let bytes = unsafe { std::slice::from_raw_parts_mut(output, output_capacity as usize) };
    CALLS.fetch_add(1, Ordering::Relaxed);
    let case = CASE.load(Ordering::Relaxed);
    if mode == 0 {
        assert_eq!(bytes.len(), 16);
        let (tag, length) = match case {
            5 => (7_u64, 0_u64),
            6 => (1, 1),
            7 => (0, 0),
            8 => (0, u64::MAX),
            9 => (0, source_length + 1),
            20..=25 => (case as u64 - 19, 0),
            _ => (0, 3),
        };
        bytes[..8].copy_from_slice(&tag.to_le_bytes());
        bytes[8..].copy_from_slice(&length.to_le_bytes());
        if case == 10 {
            control[31] = 1;
        }
        match case {
            1 => 0xffff_ffff,
            2 => 0xffff_fffe,
            3 => 7,
            4 => 1_u64 << 32,
            _ => 0,
        }
    } else {
        assert_eq!(mode, 1);
        assert_eq!(bytes.len(), 3);
        bytes.copy_from_slice(if case == 14 { b"\xff\xff\xff" } else { b"abc" });
        if case == 15 {
            control[31] = 1;
        }
        match case {
            11 => 0xffff_ffff,
            12 => 0xffff_fffe,
            13 => 17,
            _ => 0,
        }
    }
}

fn configure(case: usize, raw: &str) {
    CASE.store(case, Ordering::Relaxed);
    CALLS.store(0, Ordering::Relaxed);
    RAW_POINTER.store(raw.as_ptr() as usize, Ordering::Relaxed);
    RAW_LENGTH.store(raw.len(), Ordering::Relaxed);
}

fn main() {
    let directory = std::path::PathBuf::from(
        std::env::args()
            .nth(1)
            .unwrap_or_else(|| panic!("a new owned artifact directory is required")),
    );
    let raw = "ABC";
    let mut observed = Vec::new();
    for case in 1..=15 {
        configure(case, raw);
        let result =
            std::panic::catch_unwind(AssertUnwindSafe(|| hia_native_network_host::normalize(raw)));
        assert!(result.is_err(), "callee corruption was accepted: {case}");
        assert_eq!(
            CALLS.load(Ordering::Relaxed),
            if case >= 11 { 2 } else { 1 }
        );
        let mut policy = candidate::Policy::empty();
        configure(case, raw);
        let result = std::panic::catch_unwind(AssertUnwindSafe(|| {
            policy.add_network_rule(
                raw,
                candidate::NetworkRuleProtocol::Https,
                candidate::Decision::Allow,
                None,
            )
        }));
        assert!(result.is_err());
        assert!(policy.network_rules().is_empty());
        let path = directory.join("must-not-exist").join("policy.rules");
        configure(case, raw);
        let result = std::panic::catch_unwind(AssertUnwindSafe(|| {
            candidate::blocking_append_network_rule(
                &path,
                raw,
                candidate::NetworkRuleProtocol::Https,
                candidate::Decision::Allow,
                None,
            )
        }));
        assert!(result.is_err());
        assert!(!path.parent().expect("owned fixture parent").exists());
        observed.push(case);
    }
    configure(0, raw);
    assert_eq!(
        hia_native_network_host::normalize(raw).expect("valid fake response"),
        "abc"
    );
    assert_eq!(CALLS.load(Ordering::Relaxed), 2);
    for tag in 1..=6 {
        let raw = " [a]oops ";
        configure(tag + 19, raw);
        let result = hia_native_network_host::normalize(raw).expect_err("semantic error expected");
        assert_eq!(CALLS.load(Ordering::Relaxed), 1);
        if tag == 4 {
            assert_eq!(
                result.to_string(),
                "invalid rule: network_rule host contains an unsupported suffix:  [a]oops "
            );
        }
    }
    let mut ignored = 0;
    for text in [
        "network_rule(host=\"http://bad\", protocol=\"bad\", decision=\"bad\", justification=\" \" )",
        "network_rule(host=\"http://bad\", protocol=\"https\", decision=\"bad\", justification=\" \" )",
        "network_rule(host=\"http://bad\", protocol=\"https\", decision=\"allow\", justification=\" \" )",
    ] {
        configure(1, "unused");
        let mut parser = candidate::PolicyParser::new();
        assert!(parser.parse("ignored.rules", text).is_err());
        assert_eq!(CALLS.load(Ordering::Relaxed), 0);
        assert!(parser.build().network_rules().is_empty());
        ignored += 1;
    }
    println!(
        "network_host_failures={}",
        serde_json::json!({"passed": true,
        "corruptions": observed, "checked_entrypoints_per_corruption": 3,
        "semantic_error_probes": 6, "valid_positive_probes": 1,
        "ignored_native_entry_probes": ignored, "native_hia_executed": false,
        "scope": "actual production transport and public callers with deliberately substituted callee; raw input pointer identity, no push/file creation after corruption, and original earlier parser validation retained"})
    );
}
