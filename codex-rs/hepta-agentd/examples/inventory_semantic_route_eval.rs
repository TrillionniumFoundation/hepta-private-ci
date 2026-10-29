//! Live shared-encoder cost/quality plus native-head numerical parity.  This
//! read-only routing experiment does not impersonate the canonical fact owner.

use std::collections::BTreeMap;
use std::io::Write;
use std::sync::Arc;
use std::time::Instant;
use codex_hepta_agentd::{InventoryCellEncoderWorkerConfigV1, InventoryCellEncoderWorkerV1, InventoryCellSemanticHeadV1, InventoryCellSemanticRouterV1};
use codex_hepta_cognitive_types::{InventoryCellRouteV1, MemoryOperationV1};
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde_json::json;

#[derive(Deserialize)]
struct Case { id: String, text: String, reference_route: Option<InventoryCellRouteV1>, gold_route: Option<InventoryCellRouteV1>, features: Vec<f32>, truncated: bool }
#[derive(Deserialize)]
struct Reference { model_sha256: String, queries_sha256: String, cases: Vec<Case> }

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 6 { return Err("usage: inventory_semantic_route_eval ENCODER_CONFIG MODEL EXPECTED_SHA256 PYTHON_REFERENCE CREATE_NEW_OUTPUT".into()); }
    let configuration = std::fs::read(&args[1])?;
    let config = InventoryCellEncoderWorkerConfigV1::from_deployment_json(&configuration)?;
    let began = Instant::now();
    let encoder = Arc::new(InventoryCellEncoderWorkerV1::start(config).await?);
    let encoder_start_seconds = began.elapsed().as_secs_f64();
    let bytes = std::fs::read(&args[2])?;
    let expected: Digest32 = args[3].parse()?;
    let began = Instant::now();
    let head = InventoryCellSemanticHeadV1::from_bytes(&bytes, expected)?;
    let first = InventoryCellSemanticRouterV1::from_bytes(&bytes, expected, Arc::clone(&encoder))?;
    let second = InventoryCellSemanticRouterV1::from_bytes(&bytes, expected, Arc::clone(&encoder))?;
    let head_load_seconds = began.elapsed().as_secs_f64();
    let input = std::fs::read(&args[4])?;
    let reference: Reference = serde_json::from_slice(&input)?;
    if reference.model_sha256 != expected.to_string() || reference.cases.len() > 8192 {
        return Err("semantic reference model identity or count differs".into());
    }
    let mut groups: BTreeMap<&str, [u64; 4]> = BTreeMap::new();
    let mut cases = Vec::new();
    let mut head_parity = 0_u64;
    let mut live_parity = 0_u64;
    let started = Instant::now();
    for (index, case) in reference.cases.into_iter().enumerate() {
        let head_result = if case.truncated { None } else { head.route_features(&case.text, &case.features)? };
        let began = Instant::now();
        // Two independently constructed heads share exactly one prewarmed
        // worker; alternate requests to expose accidental per-head reloading.
        let result = if index % 2 == 0 { first.route_text(&case.text).await? } else { second.route_text(&case.text).await? };
        let nanos = began.elapsed().as_nanos();
        let same_head = head_result == case.reference_route;
        let same_live = result == case.reference_route;
        head_parity += u64::from(same_head); live_parity += u64::from(same_live);
        let correct = result == case.gold_route;
        let role = match case.gold_route.as_ref().map(|route| route.operation) {
            Some(MemoryOperationV1::Semantic) => "semantic", Some(MemoryOperationV1::Procedure) => "skill",
            Some(MemoryOperationV1::Apply) => "compose", None => "unknown", _ => return Err("unsupported semantic evaluation operation".into()),
        };
        let counts = groups.entry(role).or_default();
        counts[0] += 1; counts[1] += u64::from(correct); counts[2] += u64::from(result.is_none());
        counts[3] += u64::from(role == "unknown" && result.is_some());
        cases.push(json!({"id":case.id, "text":case.text, "route":result, "gold_route":case.gold_route,
            "native_head_python_parity":same_head, "live_worker_python_parity":same_live, "correct":correct, "inference_ns":nanos}));
    }
    let elapsed_seconds = started.elapsed().as_secs_f64();
    let metrics = encoder.metrics();
    let report = json!({"schema":"hepta.memory.inventory-semantic-evaluation.v1", "model_sha256":expected.to_string(),
        "configuration_sha256":Digest32::of_bytes(&configuration).to_string(), "query_file_sha256":reference.queries_sha256,
        "python_reference_sha256":Digest32::of_bytes(&input).to_string(), "rows":cases.len(), "head_parity_rows":head_parity,
        "live_parity_rows":live_parity, "group_fields":["total","correct","abstained","unknown_false_accept"], "groups":groups,
        "encoder_start_seconds":encoder_start_seconds, "head_load_seconds":head_load_seconds, "elapsed_seconds":elapsed_seconds,
        "shared_resolvers":2, "encoder_metrics":metrics, "head_serialized_bytes":bytes.len(), "cases":cases});
    let mut output = std::fs::OpenOptions::new().write(true).create_new(true).open(&args[5])?;
    output.write_all(&serde_json::to_vec(&report)?)?; output.sync_all()?;
    println!("{}", json!({"rows":report["rows"], "head_parity_rows":head_parity, "live_parity_rows":live_parity,
        "groups":report["groups"], "process_starts":metrics.process_starts, "elapsed_seconds":elapsed_seconds}));
    Ok(())
}
