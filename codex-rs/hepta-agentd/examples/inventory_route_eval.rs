//! Evaluate the pinned native router against frozen Python-reference and gold
//! routes. This is a read-only language experiment, not a production owner.

use std::collections::BTreeMap;
use std::io::Write;
use std::time::Instant;
use codex_hepta_agentd::InventoryCellTextRouterV1;
use codex_hepta_cognitive_types::{InventoryCellRouteV1, MemoryOperationV1};
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde_json::json;

#[derive(Deserialize)]
struct Case { text: String, reference_route: Option<InventoryCellRouteV1>, gold_route: Option<InventoryCellRouteV1> }
#[derive(Deserialize)]
struct Reference { model_sha256: String, queries_sha256: String, cases: Vec<Case> }

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 5 { return Err("usage: inventory_route_eval MODEL EXPECTED_SHA256 REFERENCE_JSON CREATE_NEW_OUTPUT".into()); }
    let bytes = std::fs::read(&args[1])?;
    let expected: Digest32 = args[2].parse()?;
    let loading = Instant::now();
    let model = InventoryCellTextRouterV1::from_bytes(&bytes, expected)?;
    let load_seconds = loading.elapsed().as_secs_f64();
    let input = std::fs::read(&args[3])?;
    let reference: Reference = serde_json::from_slice(&input)?;
    if reference.model_sha256 != expected.to_string() { return Err("reference model hash differs".into()); }
    let mut groups: BTreeMap<&str, [u64; 4]> = BTreeMap::new();
    let mut cases = Vec::new();
    let started = Instant::now();
    let mut parity = 0_u64;
    for case in reference.cases {
        let began = Instant::now();
        let route = model.route_text(&case.text)?;
        let nanos = began.elapsed().as_nanos();
        let equivalent = route == case.reference_route;
        parity += u64::from(equivalent);
        let correct = route == case.gold_route;
        let role = match case.gold_route.as_ref().map(|route| route.operation) {
            Some(MemoryOperationV1::Semantic) => "semantic",
            Some(MemoryOperationV1::Procedure) => "skill",
            Some(MemoryOperationV1::Apply) => "compose",
            None => "unknown",
            _ => return Err("unexpected gold operation".into()),
        };
        let counts = groups.entry(role).or_default();
        counts[0] += 1; counts[1] += u64::from(correct); counts[2] += u64::from(route.is_none());
        counts[3] += u64::from(role == "unknown" && route.is_some());
        cases.push(json!({"text": case.text, "route": route, "gold_route": case.gold_route, "python_reference_equal": equivalent, "correct": correct, "inference_ns": nanos}));
    }
    let elapsed_seconds = started.elapsed().as_secs_f64();
    let report = json!({"schema":"hepta.memory.native-router-evaluation.v1", "model_sha256": expected.to_string(),
        "query_file_sha256": reference.queries_sha256, "reference_file_sha256": Digest32::of_bytes(&input).to_string(),
        "rows": cases.len(), "python_parity_rows": parity, "group_fields": ["total", "correct", "abstained", "unknown_false_accept"],
        "groups": groups, "load_seconds": load_seconds, "elapsed_seconds": elapsed_seconds, "cases": cases});
    let mut output = std::fs::OpenOptions::new().write(true).create_new(true).open(&args[4])?;
    output.write_all(&serde_json::to_vec(&report)?)?; output.sync_all()?;
    println!("{}", json!({"rows": report["rows"], "python_parity_rows": parity, "groups": report["groups"], "elapsed_seconds": elapsed_seconds}));
    Ok(())
}
