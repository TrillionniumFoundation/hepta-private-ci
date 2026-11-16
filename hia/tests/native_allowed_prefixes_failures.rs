//! Probe the production transport with deliberately malformed callee results.

use original::Decision;
use original::PatternToken;
use original::PrefixPattern;
use original::PrefixRule;
use original::Rule;
use original::RuleMatch;
use original::RuleRef;
use serde_json::json;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::sync::Arc;

#[path = "../../codex-rs/execpolicy/src/hia_native_allowed_prefixes.rs"]
mod production;

static FAILURE: AtomicUsize = AtomicUsize::new(0);
static ADMISSIONS: AtomicUsize = AtomicUsize::new(0);
static PLANS: AtomicUsize = AtomicUsize::new(0);
static RUNS: AtomicUsize = AtomicUsize::new(0);

fn word(bytes: &[u8], at: usize) -> u64 {
    u64::from_le_bytes(
        bytes[at..at + 8]
            .try_into()
            .unwrap_or_else(|_| panic!("fixture word")),
    )
}

fn store(bytes: &mut [u8], at: usize, value: u64) {
    bytes[at..at + 8].copy_from_slice(&value.to_le_bytes());
}

fn expected_source(mode: u64, count: u64) -> Vec<u8> {
    let mut result = Vec::new();
    for value in [mode, count] {
        result.extend_from_slice(&value.to_le_bytes());
    }
    if count == 0 {
        return result;
    }
    assert_eq!(count, 3);
    for tokens in [
        vec![(0_u64, vec!["b"])],
        vec![(0, vec!["a"]), (1, vec![])],
        vec![(0, vec!["a"]), (0, vec!["[]"])],
    ] {
        result.extend_from_slice(&(tokens.len() as u64).to_le_bytes());
        for (kind, values) in tokens {
            result.extend_from_slice(&kind.to_le_bytes());
            result.extend_from_slice(&(values.len() as u64).to_le_bytes());
            for value in values {
                result.extend_from_slice(&(value.len() as u64).to_le_bytes());
                result.extend_from_slice(value.as_bytes());
            }
        }
    }
    result
}

fn correct_workspace() -> Vec<u8> {
    let mut bytes = Vec::new();
    for value in [80_u64, 97, 124, 151, 1, 2, 0, 1, 0, 2] {
        bytes.extend_from_slice(&value.to_le_bytes());
    }
    for tokens in [vec!["b"], vec!["a", "[]"], vec!["a", "[]"]] {
        bytes.extend_from_slice(&(tokens.len() as u64).to_le_bytes());
        for token in tokens {
            bytes.extend_from_slice(&(token.len() as u64).to_le_bytes());
            bytes.extend_from_slice(token.as_bytes());
        }
    }
    assert_eq!(bytes.len(), 151);
    bytes
}

#[unsafe(no_mangle)]
unsafe extern "C" fn codex_hia_allowed_prefixes(
    source: *const u8,
    source_length: u64,
    output: *mut u8,
    output_capacity: u64,
    workspace: *mut u8,
    workspace_length: u64,
) -> u64 {
    // SAFETY: this shim receives the actual adapter's disjoint live slices and
    // uses only their supplied extents. No pointer is kept after the call.
    let source = unsafe { std::slice::from_raw_parts(source, source_length as usize) };
    let output = unsafe { std::slice::from_raw_parts_mut(output, output_capacity as usize) };
    let workspace = unsafe { std::slice::from_raw_parts_mut(workspace, workspace_length as usize) };
    let failure = FAILURE.load(Ordering::Relaxed);
    let mode = word(source, 0);
    if mode == 0 {
        ADMISSIONS.fetch_add(1, Ordering::Relaxed);
        assert_eq!(source.len(), 16);
        assert!(workspace.is_empty());
        let decision = word(source, 8);
        assert!(decision <= 2);
        match failure {
            1 => return 0xffff_ffff,
            2 => return 0xffff_fffe,
            3 => return 0xffff_fffc,
            4 => return 99,
            5 => store(output, 0, 2),
            6 => return 0,
            _ => store(output, 0, u64::from(decision == 0)),
        }
        return 0;
    }
    assert!(mode == 1 || mode == 2);
    let count = word(source, 8);
    assert_eq!(source, expected_source(mode, count));
    if mode == 1 {
        PLANS.fetch_add(1, Ordering::Relaxed);
        assert!(workspace.is_empty());
        match failure {
            7 => return 0xffff_ffff,
            8 => return 0xffff_fffe,
            9 => return 0xffff_fffc,
            10 => return 99,
            15 => return 0,
            _ => {}
        }
        let (rendered, scratch, capacity) = if count == 0 { (0, 8, 8) } else { (71, 151, 32) };
        store(output, 0, rendered);
        store(output, 8, scratch);
        store(output, 16, capacity);
        match failure {
            11 => store(output, 0, 0),
            12 => store(output, 0, source.len() as u64),
            13 => store(output, 8, scratch + 1),
            14 => store(output, 16, capacity + 1),
            _ => {}
        }
        return 0;
    }
    RUNS.fetch_add(1, Ordering::Relaxed);
    match failure {
        16 => return 0xffff_ffff,
        17 => return 0xffff_fffe,
        18 => return 0xffff_fffd,
        19 => return 0xffff_fffc,
        20 => return 99,
        26 => return 0,
        _ => {}
    }
    if count == 0 {
        assert_eq!(output.len(), 8);
        assert_eq!(workspace.len(), 8);
        store(output, 0, 0);
        store(workspace, 0, 8);
        return 0;
    }
    assert_eq!(output.len(), 32);
    assert_eq!(workspace.len(), 151);
    workspace.copy_from_slice(&correct_workspace());
    for (index, value) in [2, 1, 0].into_iter().enumerate() {
        store(output, index * 8, value);
    }
    match failure {
        21 => store(output, 0, 0),
        22 => store(output, 0, 4),
        23 => store(output, 0, u64::MAX),
        24 => store(output, 8, 3),
        25 => store(output, 16, 1),
        27 => store(workspace, 0, 79),
        28 => store(workspace, 16, u64::MAX),
        29 => store(workspace, 8, 79),
        30 => store(workspace, 24, 150),
        31 => store(workspace, 97, 0),
        32 => store(workspace, 97, u64::MAX),
        33 => store(workspace, 105, u64::MAX),
        34 => store(workspace, 97, 1),
        35 => workspace[113] = 0xff,
        _ => {}
    }
    0
}

fn prefix(first: &str, rest: Vec<PatternToken>, decision: Decision) -> RuleRef {
    Arc::new(PrefixRule {
        pattern: PrefixPattern {
            first: Arc::from(first),
            rest: rest.into(),
        },
        decision,
        justification: Some("metadata must stay outside frame".into()),
    })
}

#[derive(Debug)]
struct Other;
impl Rule for Other {
    fn program(&self) -> &str {
        panic!("unexpected program");
    }
    fn matches(&self, _: &[String]) -> Option<RuleMatch> {
        panic!("unexpected matching");
    }
    fn as_any(&self) -> &dyn std::any::Any {
        self
    }
}

fn main() {
    let large = "excluded pattern".repeat(150000);
    let mut rules = multimap::MultiMap::new();
    for item in [
        prefix("b", vec![], Decision::Allow),
        prefix(
            &large,
            vec![PatternToken::Alts(vec![large.clone()])],
            Decision::Prompt,
        ),
        prefix("a", vec![PatternToken::Alts(vec![])], Decision::Allow),
        prefix(
            &large,
            vec![PatternToken::Single(large.clone())],
            Decision::Forbidden,
        ),
        prefix(
            "a",
            vec![PatternToken::Single("[]".into())],
            Decision::Allow,
        ),
    ] {
        rules.insert("same".to_string(), item);
    }
    let expected = vec![
        vec!["a".to_string(), "[]".to_string()],
        vec!["b".to_string()],
    ];
    assert_eq!(production::collect(&rules), expected);
    let mut observations = Vec::new();
    for (index, name) in [
        "admit-invalid",
        "admit-short",
        "admit-overflow",
        "admit-unknown",
        "admit-value",
        "admit-unwritten",
        "plan-invalid",
        "plan-short",
        "plan-overflow",
        "plan-unknown",
        "plan-rendered-small",
        "plan-rendered-large",
        "plan-workspace",
        "plan-output",
        "plan-unwritten",
        "run-invalid",
        "run-short-output",
        "run-short-workspace",
        "run-overflow",
        "run-unknown",
        "run-empty",
        "run-count",
        "run-count-max",
        "run-index",
        "run-duplicate",
        "run-unwritten",
        "offset-first",
        "offset-large",
        "offset-descending",
        "offset-last",
        "token-count-zero",
        "token-count-max",
        "token-length-max",
        "token-trailing",
        "token-utf8",
    ]
    .into_iter()
    .enumerate()
    {
        FAILURE.store(index + 1, Ordering::Relaxed);
        let result =
            std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| production::collect(&rules)));
        let Err(error) = result else {
            panic!("malformed callee result was accepted: {name}");
        };
        let message = error
            .downcast_ref::<String>()
            .map(String::as_str)
            .or_else(|| error.downcast_ref::<&str>().copied())
            .unwrap_or("non-string panic");
        observations.push(json!({"case": name, "panic": message}));
    }
    FAILURE.store(0, Ordering::Relaxed);
    let mut ignored_cases = 0;
    for count in [0, 1, 64, 65, 129] {
        let mut ignored = multimap::MultiMap::new();
        for index in 0..count {
            let rule: RuleRef = if index % 3 == 0 {
                Arc::new(Other)
            } else {
                prefix(
                    "ignored",
                    vec![PatternToken::Alts(vec!["ignored".into()])],
                    if index % 3 == 1 {
                        Decision::Prompt
                    } else {
                        Decision::Forbidden
                    },
                )
            };
            ignored.insert("same".to_string(), rule);
        }
        assert!(production::collect(&ignored).is_empty());
        ignored_cases += 1;
    }
    println!(
        "allowed_prefixes_failures={}",
        json!({"passed": true, "cases": observations.len(),
        "observations": observations, "ignored_transport_cases": ignored_cases,
        "admission_calls": ADMISSIONS.load(Ordering::Relaxed), "plan_calls": PLANS.load(Ordering::Relaxed),
        "run_calls": RUNS.load(Ordering::Relaxed),
        "scope": "production transport with injected callee results; no actual HIA qualification"})
    );
}
