//! One owner per executable; never link predecessor/native crate metadata together.

#[macro_use]
mod command_dispatch_fixtures;
use command_dispatch_fixtures::Case;
use command_dispatch_fixtures::scenarios;
use std::hint::black_box;
use std::time::Instant;

dispatch_owner!(measured_owner, owner);

fn main() {
    let label = std::env::args()
        .nth(1)
        .unwrap_or_else(|| panic!("baseline label is required"));
    let mut rows = Vec::new();
    let mut cases = scenarios();
    // Kind 7 becomes an exact hit after its first host callback. Kind 8
    // alternates None/Some, preserving the two callbacks throughout timing.
    let same_bucket = cases
        .iter_mut()
        .find(|(name, _)| *name == "exact-none-host-same-bucket")
        .unwrap_or_else(|| panic!("missing same-bucket workload"));
    same_bucket.1.buckets = vec![("tool".into(), vec![8])];
    cases.extend([
        (
            "many-exact-none",
            Case {
                buckets: vec![("tool".into(), vec![0; 1024])],
                fallback: None,
                ..Case::default()
            },
        ),
        (
            "many-exact-match",
            Case {
                buckets: vec![("tool".into(), vec![1; 1024])],
                fallback: None,
                ..Case::default()
            },
        ),
        (
            "many-host-paths-last-match",
            Case {
                command: vec!["/opt/tool".into()],
                resolve: true,
                buckets: vec![("tool".into(), vec![1])],
                host_paths: vec![(
                    "tool".into(),
                    (0..1024)
                        .map(|index| format!("/miss/{index}/tool").into())
                        .chain(["/opt/tool".into()])
                        .collect(),
                )],
                ..Case::default()
            },
        ),
        (
            "host-first-match-giant-unvisited",
            Case {
                command: vec!["/opt/tool".into()],
                resolve: true,
                buckets: vec![("tool".into(), vec![1])],
                host_paths: vec![(
                    "tool".into(),
                    vec![
                        "/opt/tool".into(),
                        format!("/{}", "x".repeat(1 << 20)).into(),
                    ],
                )],
                ..Case::default()
            },
        ),
    ]);
    for (name, case) in cases {
        let policy = measured_owner::policy(&case, None);
        let bytes = case.command.iter().map(String::len).sum::<usize>();
        let rule_count = case
            .buckets
            .iter()
            .map(|(_, values)| values.len())
            .sum::<usize>();
        let path_count = case
            .host_paths
            .iter()
            .map(|(_, values)| values.len())
            .sum::<usize>();
        let iterations = if bytes > 65536 || rule_count > 100 || path_count > 100 {
            30
        } else {
            10_000
        };
        for _ in 0..10 {
            black_box(measured_owner::matches(
                black_box(&policy),
                black_box(&case),
            ));
        }
        let start = Instant::now();
        let mut checksum = 0;
        for _ in 0..iterations {
            let result = black_box(measured_owner::matches(
                black_box(&policy),
                black_box(&case),
            ));
            checksum += result.len();
        }
        rows.push(serde_json::json!({"case": name, "iterations": iterations,
            "nanoseconds": start.elapsed().as_nanos(), "checksum": checksum,
            "command_bytes": bytes, "rules": rule_count, "paths": path_count}));
    }
    println!(
        "command_dispatch_performance={}",
        serde_json::json!({"passed": true, "label": label,
        "rows": rows, "skipped": 0, "performance_qualification": false,
        "scope": "one actual owner crate per process; diagnostic elapsed timings, fixture creation outside timing; no performance acceptance inferred"})
    );
}
