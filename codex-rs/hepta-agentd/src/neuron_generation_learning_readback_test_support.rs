//! Exact original owner bytes from engineering fixtures only.

use codex_hepta_neuron::CellBackendManifestV2;
use codex_hepta_neuron::CellGenerationObservationV1;
use codex_hepta_neuron::CellGenerationReceiptV2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;

use super::AgentdGenerationLearningUseReadbackV1;

pub(crate) fn verify_original_bytes(
    readback: &AgentdGenerationLearningUseReadbackV1,
    manifest: &CellBackendManifestV2,
    receipt: &CellGenerationReceiptV2,
    observation: &CellGenerationObservationV1,
    phase: &str,
) -> anyhow::Result<()> {
    assert_eq!(readback.authority(), AuthorityPosture::DENY_ALL);
    assert_eq!(
        readback.digest(),
        Digest32::of_parts(&[
            b"hepta.agentd.learning-use-readback.v1\0",
            readback.payload_json().as_bytes(),
        ])
        .into_array()
    );
    let payload: serde_json::Value = serde_json::from_str(readback.payload_json())?;
    assert_eq!(payload["manifest_json"], serde_json::to_string(manifest)?);
    assert_eq!(
        payload["step_receipt_json"],
        serde_json::to_string(receipt)?
    );
    assert_eq!(
        payload["generation_observation_json"],
        serde_json::to_string(observation)?
    );
    assert_eq!(payload["authority"], "DENY_ALL");
    assert_eq!(payload["current_permission"], "NOT_EXPORTED");
    // The marker identifies original serialized fixture bytes, never a real
    // model/independent-evaluation claim. The collector must not rebuild JSON.
    if std::env::var_os("HEPTA_GENERATION_LEARNING_READBACK_STDOUT").is_some() {
        println!(
            "HEPTA_LEARNING_READBACK_V1 {phase} {}",
            serde_json::to_string(readback)?
        );
    }
    Ok(())
}
