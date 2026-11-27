//! Inject invalid replies into the actual transport; real HIA runs separately.

pub use original::Decision;
pub use original::MatchOptions;
pub use original::Policy;
pub use original::RuleMatch;
pub use original::RuleRef;
#[path = "../../codex-rs/execpolicy/src/executable_name.rs"]
mod executable_name;
#[path = "../../codex-rs/execpolicy/src/hia_native_command_dispatch.rs"]
mod hia_native_command_dispatch;

use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
static CASE: AtomicUsize = AtomicUsize::new(0);
static CALLS: AtomicUsize = AtomicUsize::new(0);
static CALLBACKS: AtomicUsize = AtomicUsize::new(0);

fn word(bytes: &[u8], at: usize) -> u64 {
    u64::from_le_bytes(
        bytes[at..at + 8]
            .try_into()
            .unwrap_or_else(|_| panic!("fixture word")),
    )
}

fn put(bytes: &mut [u8], at: usize, value: u64) {
    bytes[at..at + 8].copy_from_slice(&value.to_le_bytes());
}

#[unsafe(no_mangle)]
unsafe extern "C" fn codex_hia_command_dispatch(
    source: *const u8,
    source_length: u64,
    output: *mut u8,
    output_capacity: u64,
    _workspace: *mut u8,
    workspace_length: u64,
) -> u64 {
    // SAFETY: the production transport supplies initialized disjoint buffers.
    let source = unsafe { std::slice::from_raw_parts(source, source_length as usize) };
    // SAFETY: the fake writes within precisely the borrowed output extent.
    let output = unsafe { std::slice::from_raw_parts_mut(output, output_capacity as usize) };
    assert_eq!(output.len(), 200);
    assert_eq!(workspace_length, 0);
    assert_eq!(word(source, 0), 1);
    let ordinal = CALLS.fetch_add(1, Ordering::Relaxed);
    let case = CASE.load(Ordering::Relaxed);
    if ordinal == 0 && (1..=4).contains(&case) {
        return [0, 0xFFFF_FFFF, 0xFFFF_FFFE, 91, 0][case];
    }
    output.fill(0);
    output[..160].copy_from_slice(&source[16..176]);
    put(output, 0, 0x4849_4144);
    put(output, 80, word(source, 96) + 1);
    let event = word(source, 8);
    let fallback_fixture =
        event == 0 && word(source, 176) == 0 || word(source, 40) == 0 && event != 0;
    let action;
    if fallback_fixture {
        if event == 0 {
            assert_eq!(source.len(), 200);
            put(output, 16, 2);
            action = 9;
        } else {
            assert_eq!(event, 8);
            action = 0;
            put(output, 160, 1);
        }
    } else {
        // Fixed successful script, not a replacement policy implementation.
        // It reaches both path comparisons, construction, metadata and cleanup.
        let expected_events = [0, 1, 2, 3, 4, 5, 6, 6, 7, 2];
        assert_eq!(event, expected_events[ordinal]);
        action = [1, 2, 3, 4, 5, 6, 6, 7, 8, 0][ordinal];
        match ordinal {
            0 => {
                assert_eq!(&source[16..176], &[0; 160]);
                put(output, 16, 3);
                put(output, 24, 2);
            }
            1 => {
                put(output, 32, 1);
            }
            2 => {
                put(output, 40, 1);
            }
            3 => {
                assert_eq!(word(source, 176), 1);
                put(output, 72, 6);
            }
            4 => {
                put(output, 32, 1);
                put(output, 40, 0);
            }
            5 => {
                put(output, 56, 2);
            }
            6 | 7 => {
                assert_eq!(word(source, 176), (ordinal - 6) as u64);
                assert_eq!(word(source, 184), 3);
                assert_eq!(word(source, 192), 3);
                let mut expected = Vec::new();
                for component in [
                    b"".as_slice(),
                    b"opt",
                    b"tool",
                    b"",
                    if ordinal == 6 { b"bad" } else { b"opt" },
                    b"tool",
                ] {
                    expected.extend_from_slice(
                        &(if component.is_empty() { 1_u64 } else { 4 }).to_le_bytes(),
                    );
                    expected.extend_from_slice(&(component.len() as u64).to_le_bytes());
                    expected.extend_from_slice(component);
                }
                assert_eq!(&source[200..], expected);
                put(output, 64, (ordinal - 5) as u64);
                if ordinal == 6 {
                    put(output, 184, 1);
                }
            }
            8 => {
                assert_eq!(word(source, 176), 2);
                put(output, 72, 5);
            }
            9 => {
                assert_eq!(word(source, 184), 1);
                put(output, 40, 1);
                put(output, 48, 1);
                put(output, 72, 0);
                put(output, 160, 2);
                put(output, 168, 5);
            }
            _ => panic!("unexpected script step"),
        }
    }
    put(output, 8, if action == 0 { 10 } else { action });
    put(output, 176, action);
    if ordinal == 0 {
        match case {
            5 => put(output, 0, 0),
            6 => put(output, 8, 5),
            7 => put(output, 16, 0),
            8 => put(output, 24, 99),
            9 => put(output, 80, 0),
            10 => put(output, 88, 1),
            11 => put(output, 192, 1),
            12 => put(output, 176, 99),
            13 => put(output, 160, 3),
            14 => put(output, 168, 1),
            15 => put(output, 184, 1),
            16 => put(output, 48, 1),
            17 => put(output, 64, 1),
            18 => put(output, 72, 6),
            19 => put(output, 168, 5),
            20 => put(output, 160, 1),
            _ => {}
        }
    }
    if ordinal == 1 {
        match case {
            21 => put(output, 184, 9),
            22 => {
                put(output, 40, 1);
                put(output, 184, 1);
            }
            23 => put(output, 160, 2),
            _ => {}
        }
    }
    if ordinal == 5 && case == 24 {
        put(output, 184, 2);
    }
    if ordinal == 2 && case == 28 {
        put(output, 48, 1);
        put(output, 8, 9);
        put(output, 176, 9);
    }
    if ordinal == 0 && case == 29 {
        put(output, 8, 10);
        put(output, 176, 0);
    }
    if ordinal == 4 && case == 30 {
        put(output, 40, 1);
    }
    if (ordinal == 3 && case == 31) || (ordinal == 8 && case == 32) {
        put(output, 8, 9);
        put(output, 72, 0);
        put(output, 176, 9);
    }
    if ordinal == 9 {
        match case {
            25 => put(output, 160, 0),
            26 => put(output, 168, 6),
            27 => put(output, 168, 0),
            33 => {
                put(output, 8, 9);
                put(output, 48, 0);
                put(output, 176, 9);
            }
            _ => {}
        }
    }
    0
}

#[derive(Debug)]
struct Rule(bool);
impl original::Rule for Rule {
    fn program(&self) -> &str {
        panic!("unexpected program")
    }
    fn as_any(&self) -> &dyn std::any::Any {
        panic!("unexpected as_any")
    }
    fn matches(&self, command: &[String]) -> Option<RuleMatch> {
        CALLBACKS.fetch_add(1, Ordering::Relaxed);
        self.0.then(|| RuleMatch::PrefixRuleMatch {
            matched_prefix: command.to_vec(),
            decision: Decision::Allow,
            resolved_program: None,
            justification: Some("metadata".into()),
        })
    }
}

fn main() {
    let rules = [
        (
            "/opt/tool".into(),
            std::sync::Arc::new(Rule(false)) as RuleRef,
        ),
        ("tool".into(), std::sync::Arc::new(Rule(true)) as RuleRef),
    ]
    .into_iter()
    .collect();
    let mut policy = Policy::new(rules);
    policy.set_host_executable_paths(
        "tool".into(),
        ["/bad/tool", "/opt/tool"]
            .into_iter()
            .map(|path| path.try_into().unwrap_or_else(|error| panic!("{error}")))
            .collect(),
    );
    let command = vec!["/opt/tool".into(), "".into()];
    let fallback_calls = std::cell::Cell::new(0);
    let fallback = |_: &[String]| {
        fallback_calls.set(fallback_calls.get() + 1);
        Decision::Prompt
    };
    let options = MatchOptions {
        resolve_host_executables: true,
    };
    let valid = hia_native_command_dispatch::matches_for_command(
        &policy,
        &command,
        Some(&fallback),
        &options,
    );
    assert_eq!(valid.len(), 1);
    assert_eq!(CALLS.load(Ordering::Relaxed), 10);
    assert_eq!(fallback_calls.get(), 0);
    let mut results = Vec::new();
    for case in 1..=33 {
        CASE.store(case, Ordering::Relaxed);
        CALLS.store(0, Ordering::Relaxed);
        let before = fallback_calls.get();
        let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            hia_native_command_dispatch::matches_for_command(
                &policy,
                &command,
                Some(&fallback),
                &options,
            )
        }));
        let Err(error) = outcome else {
            panic!("invalid callee reply returned successful matches");
        };
        let message = error
            .downcast_ref::<String>()
            .cloned()
            .or_else(|| error.downcast_ref::<&str>().map(|value| value.to_string()))
            .unwrap_or_else(|| panic!("non-textual panic"));
        assert!(
            message.contains("HIA"),
            "unrelated failure {case}: {message}"
        );
        assert_eq!(
            fallback_calls.get(),
            before,
            "transport failure reached fallback"
        );
        let case_name = match case {
            31 => "omitted-path-cleanup-before-fallback",
            32 => "omitted-command-cleanup-before-fallback",
            33 => "fallback-after-retaining-match",
            _ => "structural-reply-error",
        };
        results.push(
            serde_json::json!({"case": case, "case_name": case_name, "panic": message,
            "native_calls": CALLS.load(Ordering::Relaxed)}),
        );
    }
    CASE.store(0, Ordering::Relaxed);
    CALLS.store(0, Ordering::Relaxed);
    let fallback_only = hia_native_command_dispatch::matches_for_command(
        &Policy::empty(),
        &[],
        Some(&fallback),
        &MatchOptions {
            resolve_host_executables: false,
        },
    );
    assert_eq!(fallback_only.len(), 1);
    assert_eq!(CALLS.load(Ordering::Relaxed), 2);
    println!(
        "command_dispatch_failures={}",
        serde_json::json!({"passed": true, "cases": results.len(),
        "results": results, "transport_script_cases": 2, "skipped": 0,
        "scope": "actual adapter structural replies, status/error propagation and scheduled effects; structurally valid semantic lies require the real HIA/public differential gates"})
    );
}
