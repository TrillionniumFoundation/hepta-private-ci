//! Export the actual native operator outputs for direct original-Torch comparison.

use std::io::Write;
use codex_hepta_neuron::{MemoryResidualCellV1, MEMORY_RESIDUAL_NUMERIC_PROFILE_V1};
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde_json::json;

#[derive(Deserialize)]
struct Case { features: Vec<f32> }
#[derive(Deserialize)]
struct Fixture { artifact_json: String, artifact_sha256: String, parameter_sha256: String, cases: Vec<Case> }

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 3 { return Err("usage: memory_residual_export_logits FIXTURE_DIRECTORY CREATE_NEW_OUTPUT".into()); }
    let mut models = Vec::new();
    let mut total_cases = 0;
    for seed in [731, 732, 733] {
        for kind in ["semantic", "skill"] {
            let raw = std::fs::read(std::path::Path::new(&args[1]).join(format!("seed-{seed}-{kind}.json")))?;
            let fixture: Fixture = serde_json::from_slice(&raw)?;
            let expected: Digest32 = fixture.artifact_sha256.parse()?;
            let model = MemoryResidualCellV1::from_bytes(fixture.artifact_json.as_bytes(), expected).map_err(|error| error.to_string())?;
            if model.parameters_digest().to_string() != fixture.parameter_sha256 { return Err("native parameter identity differs".into()); }
            let mut cases = Vec::new();
            for (index, case) in fixture.cases.iter().enumerate() {
                let prediction = model.predict(&case.features, model.encoder_digest()).map_err(|error| error.to_string())?;
                let feature_bytes: Vec<_> = case.features.iter().flat_map(|value| value.to_le_bytes()).collect();
                cases.push(json!({"index":index, "features_f32le_sha256":Digest32::of_bytes(&feature_bytes).to_string(),
                    "logits":prediction.logits, "value":prediction.value}));
            }
            total_cases += cases.len();
            models.push(json!({"seed":seed, "kind":kind, "fixture_sha256":Digest32::of_bytes(&raw).to_string(),
                "artifact_sha256":model.artifact_digest().to_string(), "parameter_sha256":model.parameters_digest().to_string(), "cases":cases}));
        }
    }
    let report = json!({"schema":"hepta.memory.actual-native-residual-logits.v1", "numeric_profile":MEMORY_RESIDUAL_NUMERIC_PROFILE_V1,
        "debug_assertions":cfg!(debug_assertions), "cases":total_cases, "models":models});
    let mut output = std::fs::OpenOptions::new().write(true).create_new(true).open(&args[2])?;
    output.write_all(&serde_json::to_vec(&report)?)?; output.sync_all()?;
    println!("{}", json!({"models":6, "cases":total_cases, "output":args[2]}));
    Ok(())
}
