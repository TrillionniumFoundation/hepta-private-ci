//! Inject malformed callee outputs into the actual production adapter.
//! This probe deliberately replaces HIA; the independent ABI gate uses real HIA.

pub use original::Decision;
pub use original::RuleMatch;
#[path = "../../codex-rs/execpolicy/src/hia_native_policy_summary.rs"]
mod hia_native_policy_summary;

use std::panic::AssertUnwindSafe;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

static STATUS: AtomicU64 = AtomicU64::new(0);
static WORDS: [AtomicU64; 3] = [const { AtomicU64::new(0) }; 3];
static CALLS: AtomicUsize = AtomicUsize::new(0);

#[unsafe(no_mangle)]
unsafe extern "C" fn codex_hia_policy_summary(
    _source: *const u8,
    source_length: u64,
    output: *mut u8,
    output_capacity: u64,
    _workspace: *mut u8,
    workspace_length: u64,
) -> u64 {
    assert!(source_length >= 8);
    assert_eq!(output_capacity, 24);
    assert_eq!(workspace_length, 0);
    for (index, word) in WORDS.iter().enumerate() {
        // SAFETY: the actual adapter lends its complete 24-byte output buffer.
        unsafe {
            output
                .cast::<u64>()
                .add(index)
                .write_unaligned(word.load(Ordering::Relaxed).to_le());
        }
    }
    CALLS.fetch_add(1, Ordering::Relaxed);
    STATUS.load(Ordering::Relaxed)
}

fn main() {
    let inputs = [
        vec![],
        vec![RuleMatch::HeuristicsRuleMatch {
            command: vec![],
            decision: Decision::Forbidden,
        }],
    ];
    let malformed = [
        ("invalid-frame-status", 0xFFFF_FFFF, [0, 0, 0]),
        ("short-output-status", 0xFFFF_FFFE, [0, 0, 0]),
        ("unknown-status", 0, [0, 0, 0]),
        ("invalid-presence", 24, [2, 0, 0]),
        ("invalid-decision", 24, [1, 3, 0]),
        ("invalid-explicit", 24, [1, 0, 2]),
        ("empty-with-decision", 24, [0, 1, 0]),
        ("empty-with-explicit", 24, [0, 0, 1]),
        ("unwritten-result", 24, [u64::MAX; 3]),
    ];
    let mut observed = Vec::new();
    for input in &inputs {
        for (label, status, words) in malformed {
            STATUS.store(status, Ordering::Relaxed);
            for (target, word) in WORDS.iter().zip(words) {
                target.store(word, Ordering::Relaxed);
            }
            let result = std::panic::catch_unwind(AssertUnwindSafe(|| {
                hia_native_policy_summary::summarize(input)
            }));
            assert!(
                result.is_err(),
                "malformed callee output became a successful result: {label}"
            );
            observed.push(serde_json::json!({"case": label, "input_count": input.len()}));
        }
    }
    assert_eq!(CALLS.load(Ordering::Relaxed), observed.len());
    println!(
        "policy_summary_failures={}",
        serde_json::json!({
            "passed": true, "cases": observed.len(), "observations": observed,
            "scope": "actual production adapter rejects injected callee errors; no native HIA qualification",
        })
    );
}
