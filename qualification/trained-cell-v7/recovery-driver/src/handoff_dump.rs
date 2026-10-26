//! Exact checkpoint transport after native decoding. The caller retains the
//! owner/admission boundary; this serialization does not confer authority.

use crate::Result;
use crate::owner;
use codex_hepta_neuron::TrainingHandoffBundleV7;
use serde_json::Value;
use serde_json::json;

pub fn dump(bundle: &TrainingHandoffBundleV7) -> Result<Value> {
    let mut checkpoints = Vec::new();
    for checkpoint in bundle.checkpoints() {
        let vector: Vec<u8> = checkpoint
            .state_vector()
            .iter()
            .flat_map(|v| v.to_bits().to_le_bytes())
            .collect();
        let actions: Vec<u8> = checkpoint
            .planned_actions()
            .iter()
            .flatten()
            .flat_map(|v| v.to_bits().to_le_bytes())
            .collect();
        checkpoints.push(json!({"cell_id":checkpoint.cell_id().as_str(),
            "state_metadata_json":std::str::from_utf8(checkpoint.state_metadata_json())?,
            "controller_metadata_json":std::str::from_utf8(checkpoint.controller_metadata_json())?,
            "state_vector_le_hex":owner::hex(&vector),"resolved_actions_le_hex":owner::hex(&actions),
            "pending_actions":checkpoint.pending_actions().len()}));
    }
    Ok(json!({"schema":"hepta.native-full-checkpoint-dump.v7",
        "artifact_id":bundle.artifact_id().as_str(),"generation":bundle.generation().get(),
        "handoff_sha256":bundle.content_digest().to_string(),"serving_sha256":bundle.serving().content_digest().to_string(),
        "protocol_sha256":bundle.protocol_digest().to_string(),
        "predecessor_sha256":bundle.predecessor_digest().map(|v| v.to_string()),"checkpoints":checkpoints,
        "authority":"DENY_ALL","optimizer_executed":false,"production_activation":false}))
}
