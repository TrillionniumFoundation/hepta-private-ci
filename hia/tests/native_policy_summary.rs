//! Differential against the separately built, token-pinned original public crate.

use serde_json::json;
use serde_json::Value;
use std::any::Any;
use std::hint::black_box;
use std::panic::AssertUnwindSafe;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Instant;

pub use candidate::Decision;
pub use candidate::RuleMatch;
#[path = "../../codex-rs/execpolicy/src/hia_native_policy_summary.rs"]
mod hia_native_policy_summary;
include!(env!("CODEX_HIA_POLICY_SUMMARY_CLI"));

type Trace = Arc<Mutex<Vec<String>>>;

fn log(trace: &Trace, event: String) {
    trace
        .lock()
        .unwrap_or_else(|error| panic!("{error}"))
        .push(event);
}

fn value(input: &impl serde::Serialize) -> Value {
    serde_json::to_value(input).unwrap_or_else(|error| panic!("{error}"))
}

struct Commands {
    next: usize,
    commands: std::collections::VecDeque<Vec<String>>,
    trace: Trace,
    mode: &'static str,
}

struct Command {
    index: usize,
    command: Vec<String>,
    trace: Trace,
    panic_as_ref: bool,
}

impl Iterator for Commands {
    type Item = Command;
    fn next(&mut self) -> Option<Self::Item> {
        log(&self.trace, format!("next:{}", self.next));
        if self.mode == "iterator_panic" && self.next == 1 {
            panic!("iterator sentinel");
        }
        let index = self.next;
        self.next += 1;
        self.commands.pop_front().map(|command| Command {
            index,
            command,
            trace: self.trace.clone(),
            panic_as_ref: self.mode == "as_ref_panic" && index == 1,
        })
    }
}

impl Drop for Commands {
    fn drop(&mut self) {
        log(&self.trace, "iterator_drop".into());
    }
}

impl AsRef<[String]> for Command {
    fn as_ref(&self) -> &[String] {
        log(&self.trace, format!("as_ref:{}", self.index));
        assert!(!self.panic_as_ref, "as_ref sentinel");
        &self.command
    }
}

impl Drop for Command {
    fn drop(&mut self) {
        log(&self.trace, format!("command_drop:{}", self.index));
    }
}

macro_rules! owner {
    ($module:ident, $api:ident, $cli:ident) => {
        mod $module {
            use super::*;
            use $api as api;

            pub fn records(tags: &[u8], seed: usize, payload: &str) -> Vec<api::RuleMatch> {
                tags.iter().enumerate().map(|(index, tag)| {
                    let decision = match tag % 3 {
                        0 => api::Decision::Allow,
                        1 => api::Decision::Prompt,
                        _ => api::Decision::Forbidden,
                    };
                    let tokens = if index % 3 == 0 { vec![] } else {
                        vec!["tool".into(), payload.into(), format!("{seed}:{index}"), "".into()]
                    };
                    if tag / 3 == 0 {
                        api::RuleMatch::PrefixRuleMatch {
                            matched_prefix: tokens, decision,
                            resolved_program: (index % 2 == 1).then(|| {
                                "/opt/é/bin/tool".try_into().unwrap_or_else(|error| panic!("{error}"))
                            }),
                            justification: (index % 2 == 0).then(|| format!("理由\0{seed}:{index}")),
                        }
                    } else {
                        api::RuleMatch::HeuristicsRuleMatch { command: tokens, decision }
                    }
                }).collect()
            }

            #[derive(Debug)]
            struct RecordedRule {
                name: String,
                result: api::RuleMatch,
                trace: Option<Trace>,
                panic: bool,
            }

            impl api::Rule for RecordedRule {
                fn program(&self) -> &str { "tool" }
                fn matches(&self, command: &[String]) -> Option<api::RuleMatch> {
                    if let Some(trace) = &self.trace {
                        log(trace, format!("rule:{}:{command:?}", self.name));
                    }
                    assert!(!self.panic, "rule sentinel");
                    if command.get(1).is_some_and(|token| token == "miss") {
                        None
                    } else {
                        Some(self.result.clone())
                    }
                }
                fn as_any(&self) -> &dyn Any { self }
            }

            pub fn policy(matches: &[api::RuleMatch]) -> api::Policy {
                api::Policy::new(matches.iter().enumerate().map(|(index, matched)| {
                    ("tool".into(), Arc::new(RecordedRule {
                        name: index.to_string(), result: matched.clone(), trace: None, panic: false,
                    }) as api::RuleRef)
                }).collect())
            }

            pub fn snapshot(tags: &[u8], seed: usize, payload: &str) -> Value {
                let matches = records(tags, seed, payload);
                let evaluation = api::Evaluation { decision: api::Decision::Prompt, matched_rules: matches.clone() };
                let compact = $cli::format_matches_json(&matches, false).unwrap_or_else(|error| panic!("{error}"));
                let pretty = $cli::format_matches_json(&matches, true).unwrap_or_else(|error| panic!("{error}"));
                let (checked, multiple) = if matches.is_empty() { (Value::Null, Value::Null) } else {
                    let policy = policy(&matches);
                    let command = vec!["tool".into(), "ok".into()];
                    let fallback = |_: &[String]| panic!("matched command invoked fallback");
                    let checked = policy.check(&command, &fallback);
                    assert_eq!(value(&checked.matched_rules), value(&matches));
                    let multiple = policy.check_multiple([command.clone(), command], &fallback);
                    (value(&checked), value(&multiple))
                };
                json!({"is_match": evaluation.is_match(), "compact": compact, "pretty": pretty,
                       "evaluation": checked, "multiple": multiple})
            }

            pub fn mutations() -> Vec<Value> {
                let mut evaluation = api::Evaluation { decision: api::Decision::Forbidden, matched_rules: vec![] };
                let mut observations = Vec::new();
                for length in [0, 1, 31, 32, 33, 31, 0, 32, 1] {
                    evaluation.matched_rules = records(&vec![3; length], length, "é\0汉e\u{301}");
                    observations.push(json!([evaluation.is_match(), value(&evaluation)]));
                    if length > 0 {
                        evaluation.matched_rules[length - 1] = records(&[2], length, "").remove(0);
                        evaluation.decision = api::Decision::Allow;
                        observations.push(json!([evaluation.is_match(), value(&evaluation)]));
                        evaluation.matched_rules[length - 1] = records(&[5], length, "").remove(0);
                        observations.push(json!([evaluation.is_match(), value(&evaluation)]));
                    }
                }
                observations
            }

            pub fn effects(mode: &'static str) -> Value {
                let trace = Trace::default();
                let mut rules = Vec::new();
                for (index, result) in records(&[2, 3, 1], 0, "").into_iter().enumerate() {
                    rules.push(("tool".into(), Arc::new(RecordedRule {
                        name: format!("r{index}"), result, trace: Some(trace.clone()),
                        panic: mode == "rule_panic" && index == 1,
                    }) as api::RuleRef));
                }
                rules.push(("/trusted/tool".into(), Arc::new(RecordedRule {
                    name: "exact".into(), result: records(&[4], 0, "").remove(0),
                    trace: Some(trace.clone()), panic: false,
                }) as api::RuleRef));
                let mut policy = api::Policy::new(rules.into_iter().collect());
                policy.set_host_executable_paths("tool".into(), ["/trusted/tool", "/opt/tool"].into_iter()
                    .map(|path| path.try_into().unwrap_or_else(|error| panic!("{error}"))).collect());
                let fallback_calls = std::cell::Cell::new(0);
                let fallback = |command: &[String]| {
                    log(&trace, format!("fallback:{command:?}"));
                    assert!(mode != "fallback_panic", "fallback sentinel");
                    let count = fallback_calls.get();
                    fallback_calls.set(count + 1);
                    if count % 2 == 0 { api::Decision::Prompt } else { api::Decision::Allow }
                };
                let commands = if mode == "empty" { vec![] } else {
                    vec![vec!["tool", "ok"], vec!["unknown", ""], vec![], vec!["/trusted/tool", "ok"],
                         vec!["/opt/tool", "ok"], vec!["/blocked/tool", "ok"], vec!["tool", "miss"],
                         vec!["tool", "ok"], vec!["é\0汉", "e\u{301}"]]
                };
                let iterator = Commands {
                    next: 0, commands: commands.into_iter().map(|command| command.into_iter().map(str::to_string).collect()).collect(),
                    trace: trace.clone(), mode,
                };
                let outcome = std::panic::catch_unwind(AssertUnwindSafe(|| {
                    policy.check_multiple_with_options(iterator, &fallback,
                        &api::MatchOptions { resolve_host_executables: true })
                }));
                let outcome = match outcome {
                    Ok(evaluation) => json!({"evaluation": value(&evaluation), "is_match": evaluation.is_match()}),
                    Err(error) => {
                        let message = error.downcast_ref::<String>().cloned()
                            .or_else(|| error.downcast_ref::<&str>().map(|message| message.to_string()));
                        json!({"panic": message})
                    }
                };
                let events = trace.lock().unwrap_or_else(|error| panic!("{error}")).clone();
                json!({"outcome": outcome, "trace": events, "fallback_calls": fallback_calls.get()})
            }
        }
    };
}

owner!(old, original, reference_cli);
owner!(new, candidate, native_cli);

fn main() {
    let mut comparisons = 0_u64;
    for length in 0..=5_u32 {
        for number in 0..6_u64.pow(length) {
            let mut number = number;
            let tags: Vec<u8> = (0..length)
                .map(|_| {
                    let tag = (number % 6) as u8;
                    number /= 6;
                    tag
                })
                .collect();
            assert_eq!(
                new::snapshot(&tags, comparisons as usize, "é\0汉e\u{301}"),
                old::snapshot(&tags, comparisons as usize, "é\0汉e\u{301}")
            );
            comparisons += 1;
        }
    }
    let enumerated = comparisons;
    let mut state = 0x4849_4153_554d_4d_u64;
    for index in 0..512 {
        let mut next = || {
            state ^= state << 13;
            state ^= state >> 7;
            state ^= state << 17;
            state
        };
        let length = (next() % 97) as usize;
        let tags: Vec<u8> = (0..length).map(|_| (next() % 6) as u8).collect();
        assert_eq!(
            new::snapshot(&tags, index, ""),
            old::snapshot(&tags, index, "")
        );
        comparisons += 1;
    }
    let payload = "\0汉e\u{301}".repeat(262145);
    assert_eq!(
        new::snapshot(&[5, 0, 4], 0, &payload),
        old::snapshot(&[5, 0, 4], 0, &payload)
    );
    comparisons += 1;
    let empty = new::snapshot(&[], 0, "");
    assert_eq!(empty["compact"], "{\"matchedRules\":[]}");
    assert_eq!(empty["is_match"], false);
    let strict = new::snapshot(&[0, 4, 2], 0, "");
    assert_eq!(strict["evaluation"]["decision"], "forbidden");
    assert_eq!(
        strict["evaluation"]["matchedRules"]
            .as_array()
            .map(Vec::len),
        Some(3)
    );
    assert_eq!(
        strict["multiple"]["matchedRules"].as_array().map(Vec::len),
        Some(6)
    );
    let mutations = new::mutations();
    assert_eq!(mutations, old::mutations());
    let modes = [
        "normal",
        "empty",
        "rule_panic",
        "fallback_panic",
        "iterator_panic",
        "as_ref_panic",
    ];
    let mut effects = Vec::new();
    for mode in modes {
        let actual = new::effects(mode);
        assert_eq!(actual, old::effects(mode));
        if mode == "empty" {
            assert_eq!(
                actual["outcome"]["panic"],
                "invariant failed: matched_rules must be non-empty"
            );
        } else if mode == "normal" {
            assert_eq!(actual["fallback_calls"], 5);
            assert_eq!(actual["outcome"]["evaluation"]["decision"], "forbidden");
        }
        effects.push(json!({"mode": mode, "observation": actual}));
    }
    let barrier = Arc::new(std::sync::Barrier::new(8));
    let handles: Vec<_> = (0..8)
        .map(|worker| {
            let barrier = barrier.clone();
            std::thread::spawn(move || {
                barrier.wait();
                for index in 0..64 {
                    let tags = vec![((worker + index) % 6) as u8; index % 34];
                    assert_eq!(
                        new::snapshot(&tags, index, "并发"),
                        old::snapshot(&tags, index, "并发")
                    );
                }
                64_u64
            })
        })
        .collect();
    let concurrent: u64 = handles
        .into_iter()
        .map(|handle| {
            handle
                .join()
                .unwrap_or_else(|error| std::panic::resume_unwind(error))
        })
        .sum();
    let mut benchmarks = Vec::new();
    for (label, tags) in [
        ("is_match_empty", vec![]),
        ("is_match_mixed_3", vec![0, 4, 2]),
        ("is_match_all_heuristics_31", vec![3; 31]),
        (
            "is_match_first_prefix_31",
            std::iter::once(0)
                .chain(std::iter::repeat_n(3, 30))
                .collect(),
        ),
        (
            "is_match_last_prefix_32",
            std::iter::repeat_n(3, 31)
                .chain(std::iter::once(2))
                .collect(),
        ),
    ] {
        let reference = original::Evaluation {
            decision: original::Decision::Allow,
            matched_rules: old::records(&tags, 0, ""),
        };
        let native = candidate::Evaluation {
            decision: candidate::Decision::Allow,
            matched_rules: new::records(&tags, 0, ""),
        };
        assert_eq!(reference.is_match(), native.is_match());
        let iterations = 10000;
        let start = Instant::now();
        for _ in 0..iterations {
            black_box(black_box(&reference).is_match());
        }
        let rust_ns = start.elapsed().as_nanos();
        let start = Instant::now();
        for _ in 0..iterations {
            black_box(black_box(&native).is_match());
        }
        benchmarks.push(json!({"case": label, "iterations": iterations, "rust_ns": rust_ns, "hia_ns": start.elapsed().as_nanos()}));
    }
    println!(
        "policy_summary_public={}",
        json!({
            "passed": true, "enumerated_cases": enumerated, "full_result_comparisons": comparisons + concurrent,
            "concurrent_cases": concurrent, "mutable_states": mutations.len(), "effect_scenarios": effects,
            "benchmarks": benchmarks, "performance_qualification": false, "full_policy_migration": false,
        })
    );
}
