//! Compare the actual public method with the complete token-pinned Rust owner.

use serde_json::json;
use serde_json::Value;
use std::any::Any;
use std::hint::black_box;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::Instant;

#[derive(Clone, Debug)]
struct Record {
    host: String,
    protocol: u8,
    decision: u8,
    justification: Option<String>,
}

fn record(host: &str, decision: u8, protocol: u8) -> Record {
    Record {
        host: host.into(),
        protocol,
        decision,
        justification: Some("理由\0e\u{301}".into()),
    }
}

macro_rules! owner {
    ($module:ident, $api:ident) => {
        mod $module {
            use super::*;
            use $api as api;

            pub fn decision(tag: u8) -> api::Decision {
                match tag {
                    0 => api::Decision::Allow,
                    1 => api::Decision::Prompt,
                    2 => api::Decision::Forbidden,
                    _ => panic!("invalid fixture decision"),
                }
            }

            pub fn protocol(tag: u8) -> api::NetworkRuleProtocol {
                match tag {
                    0 => api::NetworkRuleProtocol::Http,
                    1 => api::NetworkRuleProtocol::Https,
                    2 => api::NetworkRuleProtocol::Socks5Tcp,
                    3 => api::NetworkRuleProtocol::Socks5Udp,
                    _ => panic!("invalid fixture protocol"),
                }
            }

            pub fn policy(records: &[Record]) -> api::Policy {
                api::Policy::from_parts(
                    Default::default(),
                    records.iter().map(|record| api::rule::NetworkRule {
                        host: record.host.clone(), protocol: protocol(record.protocol),
                        decision: decision(record.decision), justification: record.justification.clone(),
                    }).collect(),
                    Default::default(),
                )
            }

            fn snapshot(policy: &api::Policy) -> Value {
                json!(policy.network_rules().iter().map(|rule| {
                    json!([rule.host, rule.protocol.as_policy_string(), rule.decision, rule.justification])
                }).collect::<Vec<_>>())
            }

            pub fn entries() -> Vec<Value> {
                let mut rows = Vec::new();
                rows.push(json!(api::Policy::empty().compiled_network_domains()));
                rows.push(json!(api::Policy::new(Default::default()).compiled_network_domains()));
                let base = policy(&[record("A", 0, 0), record("b", 0, 1), record("A", 1, 2)]);
                let overlay = policy(&[record("A", 0, 3), record("b", 2, 0), record("A", 1, 0)]);
                let base_before = snapshot(&base);
                let overlay_before = snapshot(&overlay);
                for merged in [base.merge_overlay(&overlay), overlay.merge_overlay(&base),
                               base.merge_overlay(&base), base.merge_overlay(&api::Policy::empty())] {
                    rows.push(json!([snapshot(&merged), merged.compiled_network_domains()]));
                }
                assert_eq!(snapshot(&base), base_before);
                assert_eq!(snapshot(&overlay), overlay_before);
                let mut mutable = base.clone();
                for (host, tag, protocol_tag, justification) in [
                    ("A", 0, 0, None), ("b", 1, 1, None), ("b", 2, 2, Some("denied".into())),
                    (" Example.COM.:443 ", 0, 3, None), (" [2001:DB8::1]:443 ", 2, 1, None),
                    ("https://bad/path", 0, 0, None), ("good.example", 0, 0, Some(" ".into())),
                ] {
                    let outcome = mutable.add_network_rule(host, protocol(protocol_tag), decision(tag), justification)
                        .map_err(|error| error.to_string());
                    rows.push(json!([outcome, snapshot(&mutable), mutable.compiled_network_domains()]));
                }
                let mut parser = api::PolicyParser::new();
                for (name, text) in [
                    ("first.rules", r#"network_rule(host="A", protocol="http", decision="allow")
network_rule(host="b", protocol="https", decision="allow")"#),
                    ("second.rules", r#"network_rule(host="a", protocol="socks5_udp", decision="allow")
network_rule(host="b", protocol="http-connect", decision="deny")
network_rule(host="a", protocol="https_connect", decision="prompt")"#),
                    ("partial.rules", r#"network_rule(host="before.error", protocol="https", decision="allow")
network_rule(host="*", protocol="http", decision="allow")"#),
                ] {
                    rows.push(json!(parser.parse(name, text).map_err(|error| error.to_string())));
                }
                let parsed = parser.build();
                rows.push(json!([snapshot(&parsed), parsed.compiled_network_domains()]));
                let expected = mutable.compiled_network_domains();
                let mut returned = mutable.compiled_network_domains();
                if let Some(host) = returned.0.first_mut() { host.push_str("changed"); }
                returned.1.clear();
                assert_eq!(mutable.compiled_network_domains(), expected);
                rows.push(json!({"returned_objects_are_independent": true}));
                rows
            }

            struct Sentinel(Arc<AtomicUsize>);

            impl std::fmt::Debug for Sentinel {
                fn fmt(&self, _: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                    self.0.fetch_add(1, Ordering::Relaxed);
                    panic!("network reduction inspected command-rule Debug");
                }
            }

            impl api::Rule for Sentinel {
                fn program(&self) -> &str {
                    self.0.fetch_add(1, Ordering::Relaxed);
                    panic!("network reduction called program");
                }
                fn matches(&self, _: &[String]) -> Option<api::RuleMatch> {
                    self.0.fetch_add(1, Ordering::Relaxed);
                    panic!("network reduction called command matching");
                }
                fn as_any(&self) -> &dyn Any {
                    self.0.fetch_add(1, Ordering::Relaxed);
                    panic!("network reduction called as_any");
                }
            }

            pub fn effects() -> Value {
                let calls = Arc::new(AtomicUsize::new(0));
                let rule: api::RuleRef = Arc::new(Sentinel(calls.clone()));
                let baseline = policy(&[record("raw HOST:443 ", 0, 0), record("", 2, 1)]);
                let policy = api::Policy::from_parts(
                    [("tool".into(), rule.clone())].into_iter().collect(),
                    baseline.network_rules().to_vec(), Default::default());
                let before = snapshot(&policy);
                let reference_count = Arc::strong_count(&rule);
                for _ in 0..3 {
                    assert_eq!(policy.compiled_network_domains(),
                               (vec!["raw HOST:443 ".to_string()], vec![String::new()]));
                }
                assert_eq!(snapshot(&policy), before);
                assert_eq!(Arc::strong_count(&rule), reference_count);
                assert_eq!(calls.load(Ordering::Relaxed), 0);
                json!({"rule_callbacks": 0, "unchanged_network_rules": before,
                       "unchanged_rule_arc_count": reference_count, "repeated_calls": 3})
            }
        }
    };
}

owner!(old, original);
owner!(new, candidate);

fn compare(records: &[Record]) {
    assert_eq!(
        new::policy(records).compiled_network_domains(),
        old::policy(records).compiled_network_domains()
    );
}

fn main() {
    let mut comparisons = 0_u64;
    let hosts = ["", "a", "A"];
    for length in 0..=5_u32 {
        for mut number in 0..9_u64.pow(length) {
            let records: Vec<_> = (0..length)
                .map(|index| {
                    let tag = number % 9;
                    number /= 9;
                    record(
                        hosts[(tag / 3) as usize],
                        (tag % 3) as u8,
                        (index % 4) as u8,
                    )
                })
                .collect();
            compare(&records);
            comparisons += 1;
        }
    }
    let special = [
        "",
        "A",
        "a",
        " a ",
        "*",
        "a:443",
        "https://a/path",
        "é",
        "e\u{301}",
        "a\0b",
        "汉",
    ];
    let mut random = 0x4849_4144_4f4d_4149_u64;
    for _ in 0..1024 {
        random ^= random << 13;
        random ^= random >> 7;
        random ^= random << 17;
        let records: Vec<_> = (0..random as usize % 97)
            .map(|index| {
                random ^= random << 13;
                random ^= random >> 7;
                random ^= random << 17;
                record(
                    special[random as usize % special.len()],
                    (random % 3) as u8,
                    (index % 4) as u8,
                )
            })
            .collect();
        compare(&records);
        comparisons += 1;
    }
    for (tags, allowed, denied) in [
        (vec![("a", 0), ("b", 0), ("a", 0)], vec!["b", "a"], vec![]),
        (vec![("a", 2), ("b", 2), ("a", 2)], vec![], vec!["b", "a"]),
        (vec![("a", 0), ("b", 0), ("a", 1)], vec!["a", "b"], vec![]),
        (vec![("a", 0), ("a", 2), ("a", 1)], vec![], vec!["a"]),
        (
            vec![("a", 0), ("b", 2), ("a", 2), ("b", 0)],
            vec!["b"],
            vec!["a"],
        ),
        (vec![("a", 0), ("a", 2)], vec![], vec!["a"]),
    ] {
        let records: Vec<_> = tags
            .iter()
            .enumerate()
            .map(|(index, (host, tag))| record(host, *tag, (index % 4) as u8))
            .collect();
        let expected = (
            allowed.into_iter().map(str::to_string).collect::<Vec<_>>(),
            denied.into_iter().map(str::to_string).collect::<Vec<_>>(),
        );
        assert_eq!(old::policy(&records).compiled_network_domains(), expected);
        assert_eq!(new::policy(&records).compiled_network_domains(), expected);
        comparisons += 1;
    }
    let large = "é\0汉".repeat(349526);
    for records in [
        vec![record(&large, 1, 0)],
        vec![record(&large, 0, 0), record(&large, 2, 3)],
        vec![record(&large, 0, 0), record(&(large.clone() + "x"), 0, 1)],
        vec![Record {
            host: "x".into(),
            protocol: 0,
            decision: 0,
            justification: Some(large.clone()),
        }],
    ] {
        compare(&records);
        comparisons += 1;
    }
    let entry_observations = new::entries();
    assert_eq!(entry_observations, old::entries());
    let effects = new::effects();
    assert_eq!(effects, old::effects());
    let records: Vec<_> = special
        .iter()
        .enumerate()
        .map(|(i, host)| record(host, (i % 3) as u8, (i % 4) as u8))
        .collect();
    let reference = old::policy(&records);
    let native = new::policy(&records);
    std::thread::scope(|scope| {
        for _ in 0..8 {
            let reference = &reference;
            let native = &native;
            scope.spawn(move || {
                for _ in 0..64 {
                    assert_eq!(
                        native.compiled_network_domains(),
                        reference.compiled_network_domains()
                    );
                }
            });
        }
    });
    comparisons += 512;
    let giant = "x".repeat(2097153);
    let benchmarks = [
        ("empty", vec![], 10000),
        ("one_prompt", vec![record("a", 1, 0)], 10000),
        ("prompt_batch_boundary", vec![record("a", 1, 0); 65], 1000),
        ("large_prompt_hosts", vec![record(&giant, 1, 0); 4], 1000),
        (
            "three_unique",
            vec![record("a", 0, 0), record("b", 2, 1), record("c", 0, 2)],
            10000,
        ),
        (
            "same_decision_moves_last",
            vec![record("a", 0, 0), record("b", 0, 0), record("a", 0, 2)],
            10000,
        ),
        (
            "many_unique",
            (0..128)
                .map(|i| record(&format!("host{i}"), (i % 3) as u8, 0))
                .collect(),
            100,
        ),
        ("single_large_host", vec![record(&giant, 0, 0)], 3),
        ("repeated_large_host", vec![record(&giant, 0, 0); 4], 3),
        (
            "first_byte_difference",
            vec![
                record(&giant, 0, 0),
                record(&("y".to_string() + &"x".repeat(2097152)), 2, 0),
            ],
            3,
        ),
        (
            "last_byte_difference",
            vec![
                record(&giant, 0, 0),
                record(&("x".repeat(2097152) + "y"), 2, 0),
            ],
            3,
        ),
    ];
    let mut timing = Vec::new();
    for (name, records, calls) in benchmarks {
        let reference = old::policy(&records);
        let native = new::policy(&records);
        assert_eq!(
            native.compiled_network_domains(),
            reference.compiled_network_domains()
        );
        let started = Instant::now();
        for _ in 0..calls {
            black_box(black_box(&reference).compiled_network_domains());
        }
        let rust_ns = started.elapsed().as_nanos();
        let started = Instant::now();
        for _ in 0..calls {
            black_box(black_box(&native).compiled_network_domains());
        }
        let native_ns = started.elapsed().as_nanos();
        timing.push(
            json!({"case": name, "calls": calls, "rust_ns": rust_ns, "native_ns": native_ns}),
        );
    }
    println!(
        "network_domains_public={}",
        json!({
            "passed": true, "original_rust_comparisons": comparisons,
            "entry_observations": entry_observations, "effects": effects, "concurrent_comparisons": 512,
            "benchmarks": timing, "performance_qualification": false,
            "scope": "actual public Policy::compiled_network_domains; complete ordered tuples; original feature-off production crate"
        })
    );
}
