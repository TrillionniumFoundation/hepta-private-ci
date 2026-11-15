// Each process links one actual owner and has no allocator instrumentation.
include!("network_host_fixtures.rs");

use std::hint::black_box;
use std::time::Instant;

network_host_owner!(measured_owner, owner);

fn main() {
    let label = std::env::args()
        .nth(1)
        .unwrap_or_else(|| panic!("baseline label is required"));
    let mut rows = Vec::new();
    for (name, raw) in host_samples() {
        let iterations = if raw.len() > 65_536 { 3 } else { 2048 };
        let mut sample = measured_owner::prepared();
        let expected_result =
            measured_owner::append(&mut sample, &raw, None).map_err(measured_owner::error);
        let expected_rules = measured_owner::snapshot(&sample);
        let mut policies = (0..iterations)
            .map(|_| measured_owner::prepared())
            .collect::<Vec<_>>();
        let mut results = Vec::with_capacity(iterations);
        let started = Instant::now();
        for policy in &mut policies {
            results.push(black_box(measured_owner::append(
                black_box(policy),
                black_box(&raw),
                None,
            )));
        }
        let elapsed = started.elapsed().as_nanos();
        for (policy, result) in policies.iter().zip(results) {
            assert_eq!(result.map_err(measured_owner::error), expected_result);
            assert_eq!(measured_owner::snapshot(policy), expected_rules);
        }
        rows.push(serde_json::json!({"case": name, "iterations": iterations,
            "raw_bytes": raw.len(), "nanoseconds": elapsed,
            "result": expected_result, "rules": expected_rules}));
    }
    println!(
        "network_host_performance={}",
        serde_json::json!({"passed": true, "label": label,
        "rows": rows, "skipped": 0, "performance_qualification": false,
        "scope": "Actual public add_network_rule; raw input, empty Policies with one reserved slot and result-vector capacity constructed before timing; complete results checked outside timing. Each large case has three calls; one diagnostic observation, no statistical or performance acceptance."})
    );
}
