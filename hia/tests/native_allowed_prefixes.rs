//! Exercise the complete actual public API against the unchanged default crate.

use serde_json::json;
use serde_json::Value;
use std::any::Any;
use std::collections::hash_map::RandomState;
use std::hint::black_box;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Instant;

#[derive(Clone)]
enum Token {
    Single(String),
    Alts(Vec<String>),
}

#[derive(Clone)]
struct Record {
    key: String,
    first: String,
    rest: Vec<Token>,
    decision: u8,
    justification: Option<String>,
}

fn record(first: &str, rest: Vec<Token>, decision: u8) -> Record {
    Record {
        key: "group".into(),
        first: first.into(),
        rest,
        decision,
        justification: Some("理由\0e\u{301}".into()),
    }
}

#[derive(Clone, Copy)]
enum DynamicKind {
    Other,
    Prefix,
    Alternating,
}

macro_rules! owner {
    ($module:ident, $api:ident) => {
        mod $module {
            use super::*;
            use $api as api;

            fn decision(tag: u8) -> api::Decision {
                match tag {
                    0 => api::Decision::Allow,
                    1 => api::Decision::Prompt,
                    2 => api::Decision::Forbidden,
                    _ => panic!("invalid fixture decision"),
                }
            }

            fn rule(record: &Record) -> api::PrefixRule {
                api::PrefixRule {
                    pattern: api::PrefixPattern {
                        first: Arc::from(record.first.as_str()),
                        rest: record.rest.iter().map(|token| match token {
                            Token::Single(value) => api::PatternToken::Single(value.clone()),
                            Token::Alts(values) => api::PatternToken::Alts(values.clone()),
                        }).collect::<Vec<_>>().into(),
                    },
                    decision: decision(record.decision),
                    justification: record.justification.clone(),
                }
            }

            pub fn policy(records: &[Record], hasher: RandomState) -> api::Policy {
                let mut rules = multimap::MultiMap::with_hasher(hasher);
                for record in records {
                    let item: api::RuleRef = Arc::new(rule(record));
                    rules.insert(record.key.clone(), item);
                }
                api::Policy::new(rules)
            }

            pub fn entries(hasher: RandomState) -> Vec<Value> {
                let mut rows = vec![json!(api::Policy::empty().get_allowed_prefixes())];
                let base = policy(&[record("a", vec![], 0), record("b", vec![], 1)], hasher.clone());
                let overlay = policy(&[record("a", vec![], 0), record("b", vec![Token::Alts(vec![])], 0)], hasher);
                let before = (base.get_allowed_prefixes(), overlay.get_allowed_prefixes());
                for merged in [base.merge_overlay(&overlay), overlay.merge_overlay(&base),
                               base.merge_overlay(&base), base.merge_overlay(&api::Policy::empty())] {
                    rows.push(json!(merged.get_allowed_prefixes()));
                }
                assert_eq!((base.get_allowed_prefixes(), overlay.get_allowed_prefixes()), before);
                let mut mutable = base.clone();
                for (prefix, tag) in [(vec!["a", ""], 0), (vec!["b"], 2),
                                      (vec!["c"], 1), (vec!["d", "[]"], 0), (vec![], 0)] {
                    let input: Vec<_> = prefix.into_iter().map(str::to_string).collect();
                    let outcome = mutable.add_prefix_rule(&input, decision(tag)).map_err(|error| error.to_string());
                    rows.push(json!([outcome, mutable.get_allowed_prefixes()]));
                }
                let from_parts = api::Policy::from_parts(mutable.rules().clone(), vec![api::rule::NetworkRule {
                    host: "ignored network".into(), protocol: api::NetworkRuleProtocol::Http,
                    decision: api::Decision::Forbidden, justification: Some("ignored".into()),
                }], Default::default());
                assert_eq!(from_parts.get_allowed_prefixes(), mutable.get_allowed_prefixes());
                rows.push(json!([from_parts.get_allowed_prefixes(), from_parts.network_rules().len()]));
                let mut parser = api::PolicyParser::new();
                for (name, text) in [
                    ("first.rules", r#"prefix_rule(pattern=["git", ["diff", "status"]], decision="allow")
prefix_rule(pattern=["other"], decision="prompt")"#),
                    ("second.rules", r#"prefix_rule(pattern=["git", "[diff|status]"], decision="allow")
prefix_rule(pattern=["git", "ignored"], decision="forbidden")"#),
                    ("partial.rules", r#"prefix_rule(pattern=["before.error"], decision="allow")
prefix_rule(pattern=[], decision="allow")"#),
                ] {
                    rows.push(json!(parser.parse(name, text).map_err(|error| error.to_string())));
                }
                rows.push(json!(parser.build().get_allowed_prefixes()));
                let expected = mutable.get_allowed_prefixes();
                let mut returned = mutable.get_allowed_prefixes();
                returned[0][0].push_str("changed");
                returned.clear();
                assert_eq!(mutable.get_allowed_prefixes(), expected);
                rows.push(json!({"returned_objects_are_independent": true}));
                rows
            }

            struct Dynamic {
                id: usize,
                kind: DynamicKind,
                prefix: api::PrefixRule,
                calls: AtomicUsize,
                events: Arc<Mutex<Vec<(usize, usize)>>>,
                panic_at: Option<usize>,
            }

            impl std::fmt::Debug for Dynamic {
                fn fmt(&self, _: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                    panic!("unexpected Debug callback");
                }
            }

            impl api::Rule for Dynamic {
                fn program(&self) -> &str { panic!("unexpected program callback"); }
                fn matches(&self, _: &[String]) -> Option<api::RuleMatch> { panic!("unexpected matches callback"); }
                fn as_any(&self) -> &dyn Any {
                    let call = self.calls.fetch_add(1, Ordering::Relaxed);
                    self.events.lock().unwrap_or_else(|error| panic!("event lock: {error}")).push((self.id, call));
                    assert_ne!(self.panic_at, Some(call), "chosen as_any panic");
                    match self.kind {
                        DynamicKind::Other => self,
                        DynamicKind::Prefix => &self.prefix,
                        DynamicKind::Alternating if call % 2 == 0 => &self.prefix,
                        DynamicKind::Alternating => self,
                    }
                }
            }

            pub fn effects(hasher: RandomState, panic_id: Option<usize>, multiple_keys: bool) -> Value {
                let events = Arc::new(Mutex::new(Vec::new()));
                let mut rules = multimap::MultiMap::with_hasher(hasher);
                let mut retained = Vec::new();
                for (id, (kind, tag)) in [(DynamicKind::Other, 0), (DynamicKind::Prefix, 0),
                    (DynamicKind::Prefix, 1), (DynamicKind::Prefix, 2), (DynamicKind::Alternating, 0)].into_iter().enumerate() {
                    let item = Arc::new(Dynamic { id, kind, prefix: rule(&record(&format!("dyn{id}"), vec![], tag)),
                        calls: AtomicUsize::new(0), events: events.clone(), panic_at: panic_id.filter(|&value| value == id).map(|_| 0) });
                    retained.push(item.clone());
                    let item: api::RuleRef = item;
                    rules.insert(if multiple_keys { format!("key{}", id % 3) } else { "one".into() }, item);
                }
                let policy = api::Policy::new(rules);
                let keys: Vec<_> = policy.rules().iter_all().map(|(key, _)| key.clone()).collect();
                let before: Vec<_> = retained.iter().map(Arc::strong_count).collect();
                let mut outcomes = Vec::new();
                for _ in 0..if panic_id.is_some() { 1 } else { 2 } {
                    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| policy.get_allowed_prefixes()));
                    outcomes.push(match result {
                        Ok(prefixes) => json!({"ok": prefixes}),
                        Err(error) => json!({"panic": error.downcast_ref::<String>().map(String::as_str)
                            .or_else(|| error.downcast_ref::<&str>().copied()).unwrap_or("non-string panic")}),
                    });
                }
                let log = events.lock().unwrap_or_else(|error| panic!("event lock: {error}")).clone();
                if !multiple_keys {
                    let end = panic_id.map_or(5, |id| id + 1);
                    let expected: Vec<_> = (0..if panic_id.is_some() { 1 } else { 2 })
                        .flat_map(|call| (0..end).map(move |id| (id, call))).collect();
                    assert_eq!(log, expected);
                }
                assert_eq!(retained.iter().map(Arc::strong_count).collect::<Vec<_>>(), before);
                if panic_id.is_none() {
                    assert_eq!(outcomes, vec![json!({"ok": [["dyn1"], ["dyn4"]]}), json!({"ok": [["dyn1"]]})]);
                } else {
                    assert!(outcomes[0].get("panic").is_some());
                }
                json!({"keys": keys, "events": log, "outcomes": outcomes,
                       "calls": retained.iter().map(|rule| rule.calls.load(Ordering::Relaxed)).collect::<Vec<_>>(),
                       "arc_counts": before})
            }
        }
    };
}

owner!(old, original);
owner!(new, candidate);

fn compare(records: &[Record]) {
    let hasher = RandomState::new();
    let native = new::policy(records, hasher.clone());
    let original = old::policy(records, hasher);
    assert_eq!(
        native
            .rules()
            .iter_all()
            .map(|(key, _)| key)
            .collect::<Vec<_>>(),
        original
            .rules()
            .iter_all()
            .map(|(key, _)| key)
            .collect::<Vec<_>>()
    );
    assert_eq!(
        native.get_allowed_prefixes(),
        original.get_allowed_prefixes()
    );
}

fn next(seed: &mut u64) -> u64 {
    *seed ^= *seed << 13;
    *seed ^= *seed >> 7;
    *seed ^= *seed << 17;
    *seed
}

fn main() {
    let patterns = [
        ("", vec![]),
        ("a", vec![]),
        ("A", vec![]),
        ("a", vec![Token::Single(String::new())]),
        ("a", vec![Token::Alts(vec![])]),
        ("a", vec![Token::Alts(vec!["x".into(), "y".into()])]),
        ("a", vec![Token::Single("[x|y]".into())]),
    ];
    let mut comparisons = 0_u64;
    for length in 0..=3_u32 {
        for mut number in 0..21_u64.pow(length) {
            let records: Vec<_> = (0..length)
                .map(|index| {
                    let choice = number % 21;
                    number /= 21;
                    let (first, rest) = &patterns[(choice / 3) as usize];
                    let mut value = record(first, rest.clone(), (choice % 3) as u8);
                    value.key = format!("key{}", index % 3);
                    value
                })
                .collect();
            compare(&records);
            comparisons += 1;
        }
    }
    let words = [
        "", "a", "A", " a ", "[]", "[a|b]", "a|b", "|", "é", "e\u{301}", "a\0b", "汉",
    ];
    let mut seed = 0x4849_4141_4c4c_4f57_u64;
    for _ in 0..1024 {
        let records: Vec<_> = (0..next(&mut seed) as usize % 66)
            .map(|index| {
                let first = words[next(&mut seed) as usize % words.len()];
                let mut rest = Vec::new();
                for _ in 0..next(&mut seed) as usize % 5 {
                    rest.push(if next(&mut seed) % 2 == 0 {
                        Token::Single(words[next(&mut seed) as usize % words.len()].into())
                    } else {
                        Token::Alts(
                            (0..next(&mut seed) as usize % 5)
                                .map(|_| words[next(&mut seed) as usize % words.len()].into())
                                .collect(),
                        )
                    });
                }
                let mut value = record(first, rest, (next(&mut seed) % 3) as u8);
                value.key = format!("key{}", index % 7);
                value
            })
            .collect();
        compare(&records);
        comparisons += 1;
    }
    let collisions = vec![
        record("p", vec![Token::Single("[a|b]".into())], 0),
        record("p", vec![Token::Alts(vec!["a".into(), "b".into()])], 0),
        record("p", vec![Token::Alts(vec!["a|b".into()])], 0),
        record("p", vec![Token::Alts(vec![])], 0),
        record("p", vec![Token::Alts(vec![String::new()])], 0),
        record("p", vec![Token::Single("[]".into())], 0),
        record("p", vec![Token::Alts(vec!["b".into(), "a".into()])], 0),
    ];
    let exact = [
        (
            collisions.clone(),
            vec![vec!["p", "[]"], vec!["p", "[a|b]"], vec!["p", "[b|a]"]],
        ),
        (
            vec![
                record("a", vec![Token::Single(String::new())], 0),
                record("a", vec![], 0),
            ],
            vec![vec!["a"], vec!["a", ""]],
        ),
        (
            vec![
                record("azzzzzzz", vec![], 0),
                record("b\0\0\0\0\0\0\0", vec![], 0),
            ],
            vec![vec!["azzzzzzz"], vec!["b\0\0\0\0\0\0\0"]],
        ),
        (
            vec![
                record("é", vec![], 0),
                record("e\u{301}", vec![], 0),
                record("汉", vec![], 0),
                record("", vec![], 0),
            ],
            vec![vec![""], vec!["e\u{301}"], vec!["é"], vec!["汉"]],
        ),
        (
            vec![
                record("same", vec![], 0),
                record("same", vec![], 2),
                record("same", vec![], 1),
            ],
            vec![vec!["same"]],
        ),
        (
            vec![record("same", vec![], 1), record("same", vec![], 2)],
            vec![],
        ),
    ];
    for (records, wanted) in exact {
        let wanted: Vec<Vec<String>> = wanted
            .into_iter()
            .map(|tokens| tokens.into_iter().map(str::to_string).collect())
            .collect();
        let hasher = RandomState::new();
        assert_eq!(
            old::policy(&records, hasher.clone()).get_allowed_prefixes(),
            wanted
        );
        assert_eq!(new::policy(&records, hasher).get_allowed_prefixes(), wanted);
        comparisons += 1;
    }
    let large = "x".repeat(2097153);
    for records in [
        vec![record(&large, vec![Token::Alts(vec![large.clone(); 3])], 1)],
        vec![record(&large, vec![], 0), record(&large, vec![], 0)],
        vec![record(
            "p",
            vec![Token::Alts(vec![large.clone(), large.clone()])],
            0,
        )],
        vec![Record {
            justification: Some(large.clone()),
            ..record("p", vec![], 0)
        }],
    ] {
        compare(&records);
        comparisons += 1;
    }
    let hasher = RandomState::new();
    let entry_observations = new::entries(hasher.clone());
    assert_eq!(entry_observations, old::entries(hasher));
    let mut effects = Vec::new();
    for (panic_id, multiple_keys) in [
        (None, false),
        (Some(0), false),
        (Some(2), false),
        (Some(4), false),
        (None, true),
        (Some(2), true),
    ] {
        let hasher = RandomState::new();
        let actual = new::effects(hasher.clone(), panic_id, multiple_keys);
        assert_eq!(actual, old::effects(hasher, panic_id, multiple_keys));
        effects.push(actual);
    }
    let records: Vec<_> = words
        .iter()
        .enumerate()
        .map(|(index, word)| record(word, vec![], (index % 3) as u8))
        .collect();
    let hasher = RandomState::new();
    let reference = old::policy(&records, hasher.clone());
    let native = new::policy(&records, hasher);
    std::thread::scope(|scope| {
        for _ in 0..8 {
            let reference = &reference;
            let native = &native;
            scope.spawn(move || {
                for _ in 0..64 {
                    assert_eq!(
                        native.get_allowed_prefixes(),
                        reference.get_allowed_prefixes()
                    );
                }
            });
        }
    });
    comparisons += 512;
    let reverse: Vec<_> = (0..128)
        .rev()
        .map(|index| record(&format!("{index:04}"), vec![], 0))
        .collect();
    let sorted: Vec<_> = reverse.iter().rev().cloned().collect();
    let cases = [
        ("empty", vec![], 10000),
        ("one_prompt", vec![record("p", vec![], 1)], 10000),
        ("one_forbidden", vec![record("p", vec![], 2)], 10000),
        ("many_prompt", vec![record("p", vec![], 1); 65], 1000),
        (
            "ignored_large_pattern",
            vec![record(&large, vec![Token::Alts(vec![large.clone(); 3])], 1)],
            1000,
        ),
        (
            "ordinary_single",
            vec![record("git", vec![Token::Single("status".into())], 0)],
            10000,
        ),
        (
            "ordinary_alternatives",
            vec![record(
                "git",
                vec![Token::Alts(vec!["diff".into(), "status".into()])],
                0,
            )],
            10000,
        ),
        ("rendering_collisions", collisions, 1000),
        ("reverse_unique", reverse, 100),
        ("sorted_unique", sorted, 100),
        ("single_large", vec![record(&large, vec![], 0)], 3),
        ("repeated_large", vec![record(&large, vec![], 0); 4], 3),
        (
            "first_byte_difference",
            vec![
                record(&large, vec![], 0),
                record(&("y".to_string() + &large[1..]), vec![], 0),
            ],
            3,
        ),
        (
            "last_byte_difference",
            vec![
                record(&large, vec![], 0),
                record(&(large[..large.len() - 1].to_string() + "y"), vec![], 0),
            ],
            3,
        ),
    ];
    let mut benchmarks = Vec::new();
    for (name, records, calls) in cases {
        let hasher = RandomState::new();
        let reference = old::policy(&records, hasher.clone());
        let native = new::policy(&records, hasher);
        assert_eq!(
            native.get_allowed_prefixes(),
            reference.get_allowed_prefixes()
        );
        let started = Instant::now();
        for _ in 0..calls {
            black_box(black_box(&reference).get_allowed_prefixes());
        }
        let rust_ns = started.elapsed().as_nanos();
        let started = Instant::now();
        for _ in 0..calls {
            black_box(black_box(&native).get_allowed_prefixes());
        }
        benchmarks.push(json!({"case": name, "calls": calls, "rust_ns": rust_ns, "native_ns": started.elapsed().as_nanos()}));
    }
    println!(
        "allowed_prefixes_public={}",
        json!({"passed": true,
        "scope": "actual public Policy::get_allowed_prefixes; complete ordered Vec<Vec<String>>; original production default crate",
        "original_rust_comparisons": comparisons, "concurrent_comparisons_included": 512,
        "entry_observations": entry_observations, "effect_cases": effects,
        "hasher_binding": "same cloned RandomState and identical key insertion order; single-key panic cases also assert exact event prefixes",
        "benchmarks": benchmarks, "performance_qualification": false})
    );
}
