//! Exact original owner bytes from engineering fixtures only.

use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_neuron::CellBackendManifestV2;
use codex_hepta_neuron::CellGenerationObservationV1;
use codex_hepta_neuron::CellGenerationReceiptV2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;

use super::AgentdGenerationLearningUseReadbackV1;
use crate::LearningIterationCheckpointErrorV1;

// Exercise the exact production codec without widening its production API.
#[allow(
    clippy::duplicate_mod,
    reason = "This test-only exporter reuses the private production codec without widening its API"
)]
#[path = "learning_iteration_checkpoint_codec.rs"]
mod checkpoint_codec;

pub(crate) fn verify_original_bytes(
    readback: &AgentdGenerationLearningUseReadbackV1,
    coordinator: &LearningIterationCoordinatorV1,
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
    let snapshot = coordinator.snapshot();
    assert_eq!(
        payload["learning_head"],
        serde_json::to_value(snapshot.head_digest.into_array())?
    );
    let checkpoint = checkpoint_codec::encode(snapshot)?;
    assert_eq!(checkpoint_codec::decode(&checkpoint)?, *snapshot);
    let initial =
        LearningIterationCoordinatorV1::new(snapshot.request.clone(), snapshot.owners.clone())?;
    let initial_checkpoint = checkpoint_codec::encode(initial.snapshot())?;
    assert_eq!(
        checkpoint_codec::decode(&initial_checkpoint)?,
        *initial.snapshot()
    );
    // The marker identifies original serialized fixture bytes, never a real
    // model/independent-evaluation claim. The collector must not rebuild JSON.
    if std::env::var_os("HEPTA_GENERATION_LEARNING_READBACK_STDOUT").is_some() {
        // Original native serialization of the fixture freeze. This exports
        // no Root registration, witness, scope custody or production authority.
        println!(
            "HEPTA_LEARNING_INITIAL_V1 {phase} {}",
            serde_json::json!({
                "schema": "hepta.learning.initial-checkpoint.fixture.v1",
                "initial_head": initial.snapshot().head_digest.to_string(),
                "checkpoint_sha256": Digest32::of_bytes(&initial_checkpoint).to_string(),
                "checkpoint_base64": STANDARD_NO_PAD.encode(&initial_checkpoint),
                "authority": "DENY_ALL",
                "current_permission": "NOT_EXPORTED",
                "production_qualification": "HOLD_NO_GO",
                "pins_are_fixture_derived": true,
            })
        );
        println!(
            "HEPTA_LEARNING_READBACK_V1 {phase} {}",
            serde_json::to_string(readback)?
        );
        // Paired native serialization of this test coordinator, not evidence
        // of independent production checkpoint custody or evaluation quality.
        println!(
            "HEPTA_LEARNING_CHECKPOINT_V2 {phase} {}",
            serde_json::json!({
                "schema": "hepta.learning.checkpoint.fixture.v2",
                "initial_head": initial.snapshot().head_digest.to_string(),
                "checkpoint_sha256": Digest32::of_bytes(&checkpoint).to_string(),
                "checkpoint_base64": STANDARD_NO_PAD.encode(&checkpoint),
                "learning_head": snapshot.head_digest.to_string(),
                "evaluation_profile": snapshot.request.evaluation_profile.to_string(),
                "authority": "DENY_ALL",
                "current_permission": "NOT_EXPORTED",
                "production_qualification": "HOLD_NO_GO",
                "pins_are_fixture_derived": true,
            })
        );
    }
    Ok(())
}

/// Export the terminal coordinator's exact production-codec bytes after the
/// original actor's acknowledged use and cold recovery. This remains a local
/// engineering fixture, independent of model training, STOP, or host authority.
pub(crate) fn verify_completed_bytes(
    readback: &AgentdGenerationLearningUseReadbackV1,
    coordinator: &LearningIterationCoordinatorV1,
    phase: &str,
) -> anyhow::Result<()> {
    assert_eq!(coordinator.next_stage(), None);
    assert_eq!(readback.authority(), AuthorityPosture::DENY_ALL);
    let snapshot = coordinator.snapshot();
    let mut selection = snapshot.clone();
    let next_use = selection
        .receipts
        .pop()
        .ok_or_else(|| anyhow::anyhow!("missing completed next-use receipt"))?;
    selection.head_digest = next_use.predecessor;
    assert_eq!(
        LearningIterationCoordinatorV1::from_snapshot(selection)?.next_stage(),
        Some(LearningIterationStageV1::NextUse)
    );
    let payload: serde_json::Value = serde_json::from_str(readback.payload_json())?;
    assert_eq!(
        payload["learning_head"],
        serde_json::to_value(next_use.predecessor.into_array())?
    );
    let observation: serde_json::Value = serde_json::from_str(
        payload["generation_observation_json"]
            .as_str()
            .ok_or_else(|| anyhow::anyhow!("missing original generation observation"))?,
    )?;
    assert_eq!(
        observation["pending_request_digest"],
        serde_json::Value::Null
    );
    assert_eq!(observation["pending_output"], serde_json::Value::Null);
    let checkpoint = checkpoint_codec::encode(snapshot)?;
    let decoded = checkpoint_codec::decode(&checkpoint)?;
    assert_eq!(decoded, *snapshot);
    assert_eq!(
        LearningIterationCoordinatorV1::from_snapshot(decoded)?.next_stage(),
        None
    );
    let initial =
        LearningIterationCoordinatorV1::new(snapshot.request.clone(), snapshot.owners.clone())?;
    if std::env::var_os("HEPTA_GENERATION_LEARNING_READBACK_STDOUT").is_some() {
        println!(
            "HEPTA_LEARNING_COMPLETION_V1 {phase} {}",
            serde_json::json!({
                "schema": "hepta.learning.completed-checkpoint.fixture.v1",
                "initial_head": initial.snapshot().head_digest.to_string(),
                "selection_head": next_use.predecessor.to_string(),
                "checkpoint_sha256": Digest32::of_bytes(&checkpoint).to_string(),
                "checkpoint_base64": STANDARD_NO_PAD.encode(&checkpoint),
                "learning_head": snapshot.head_digest.to_string(),
                "evaluation_profile": snapshot.request.evaluation_profile.to_string(),
                "readback_sha256": Digest32::of_bytes(&serde_json::to_vec(readback)?).to_string(),
                "authority": "DENY_ALL",
                "current_permission": "NOT_EXPORTED",
                "production_qualification": "HOLD_NO_GO",
                "pins_are_fixture_derived": true,
                "actual_model_execution_accepted": false,
            })
        );
    }
    Ok(())
}
