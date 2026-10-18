//! Ordinary publication and withdrawal use the existing signed writer and its
//! durable operation IDs. An ACK is descriptive; installation remains separate.

use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use anyhow::Result;
use anyhow::ensure;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_learning_artifacts as artifacts;
use serde::Deserialize;
use serde_json::Value;
use serde_json::json;

use crate::cognitive_artifact_owner_materials::CognitiveArtifactOwnerMaterialsV1;
use crate::cognitive_process_current::CurrentHeadDescriptorV1;
use crate::cognitive_process_materials::LearningArtifactManifestV2Raw;
use crate::cognitive_process_wire::Digest;
use crate::cognitive_process_wire::Id;
use crate::cognitive_materials_io::read_material;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CognitiveArtifactPublicationInputV1 {
    owner: CognitiveArtifactOwnerMaterialsV1,
    operation_id: Id,
    source_manifest: LearningArtifactManifestV2Raw,
    payload_path: PathBuf,
    admitted_at: u64,
    expected_registry_predecessor_head: Digest,
    signed_current_head: CurrentHeadDescriptorV1,
}

pub fn publish_cognitive_artifact_v1(fleet: &FleetRegistry, input: CognitiveArtifactPublicationInputV1) -> Result<Value> {
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    ensure!(input.admitted_at <= now, "publication admission time is in the future");
    let mut owner = input.owner.open(fleet, now)?;
    let manifest: artifacts::LearningArtifactManifestV2 = input.source_manifest.into();
    let artifact = manifest.artifact_id.to_string();
    let generation = manifest.generation.get();
    let payload_sha256 = manifest.bytes_digest.to_string();
    let payload = read_material(&input.payload_path, 64 * 1024 * 1024)?;
    let admission = artifacts::admit_manifest_at_withdrawal_head_v3(
        owner.withdrawal_registry(), owner.withdrawal_registry().head_digest(), manifest, input.admitted_at,
    )?;
    let receipt = owner.publish(artifacts::LearningArtifactPublishRequestV1 {
        operation_id: input.operation_id.into(), admission, payload,
        signed_current_head: input.signed_current_head.native()?,
        expected_registry_predecessor_head: input.expected_registry_predecessor_head.into(), now,
    })?;
    let current = owner.current_registry_view(now)?;
    Ok(json!({
        "state":"published", "operation_id":receipt.operation_id.as_str(),
        "artifact_id":artifact, "artifact_generation":generation, "payload_sha256":payload_sha256,
        "admission_sha256":receipt.admission_digest.to_string(),
        "publication_head_sha256":receipt.registry_head_digest.to_string(),
        "current_head_sha256":current.receipt().head_digest.to_string(),
        "current_witness_sha256":current.witness_digest().to_string(),
        "owner_state_sha256":receipt.state_digest.to_string(), "acknowledged_at":receipt.acknowledged_at,
        "authority_granted":receipt.authority.grants_any(),
    }))
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CognitiveArtifactRevocationInputV1 {
    owner: CognitiveArtifactOwnerMaterialsV1,
    operation_id: Id,
    event_id: Id,
    artifact_id: Id,
    evaluator_id: Id,
    reason_digest: Digest,
    expected_registry_predecessor_head: Digest,
    signed_current_head: CurrentHeadDescriptorV1,
}

pub fn revoke_cognitive_artifact_v1(fleet: &FleetRegistry, input: CognitiveArtifactRevocationInputV1) -> Result<Value> {
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    let mut owner = input.owner.open(fleet, now)?;
    let receipt = owner.revoke(artifacts::LearningArtifactRevokeRequestV1 {
        operation_id: input.operation_id.into(),
        change: artifacts::StateChange {
            event_id: input.event_id.into(), artifact_id: input.artifact_id.into(),
            evaluator_id: input.evaluator_id.into(), reason_digest: input.reason_digest.into(),
        },
        signed_current_head: input.signed_current_head.native()?,
        expected_registry_predecessor_head: input.expected_registry_predecessor_head.into(), now,
    })?;
    let current = owner.current_registry_view(now)?;
    Ok(json!({
        "state":"revoked", "operation_id":receipt.operation_id.as_str(),
        "artifact_id":receipt.change.artifact_id.as_str(), "event_id":receipt.change.event_id.as_str(),
        "reason_sha256":receipt.change.reason_digest.to_string(),
        "revocation_head_sha256":receipt.registry_head_digest.to_string(),
        "current_head_sha256":current.receipt().head_digest.to_string(),
        "owner_state_sha256":receipt.state_digest.to_string(), "acknowledged_at":receipt.acknowledged_at,
        "authority_granted":receipt.authority.grants_any(),
    }))
}
