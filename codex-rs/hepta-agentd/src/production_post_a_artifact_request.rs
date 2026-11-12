//! Canonical material from the actual authenticated Decision and original B.
//! The original Artifact owner still checks the independent head signature.

use codex_hepta_learning_artifacts::*;
use codex_hepta_neuron::CellBackendManifestV2;
use codex_hepta_types::Digest32;

use super::super::refused;
use crate::AgentdError;
use crate::cell_q24_publication_driver::validation::Decision;

pub(super) fn original_request(
    decision: &Decision,
    manifest: &CellBackendManifestV2,
    signed_current_head: SignedCurrentArtifactHeadV1,
    owner: &LearningArtifactOwnerService,
    now: u64,
) -> Result<LearningArtifactPublishRequestV1, AgentdError> {
    decision.require_root_publication().map_err(refused)?;
    if !decision.adopts() {
        return Err(refused("retention has no new Artifact transaction"));
    }
    let bundle = &decision.bundle;
    crate::cell_composed_q24::validate_manifest(bundle, manifest).map_err(refused)?;
    let lineage = bundle
        .training_lineage
        .as_ref()
        .ok_or_else(|| refused("original training lineage absent"))?;
    let payload = serde_json::to_vec(manifest)?;
    let mut lineage_digests = vec![
        lineage.source_bundle,
        lineage.dataset,
        lineage.update_rule,
        lineage.evaluation_profile,
    ];
    lineage_digests.extend(
        decision
            .snapshot
            .receipts
            .iter()
            .filter(|receipt| {
                matches!(
                    receipt.observation,
                    LearningIterationObservationV1::Training { .. }
                        | LearningIterationObservationV1::Evaluation { .. }
                        | LearningIterationObservationV1::Proposal { .. }
                        | LearningIterationObservationV1::LocalDecisionV2(_)
                )
            })
            .map(|receipt| receipt.evidence_digest),
    );
    lineage_digests.sort_unstable();
    lineage_digests.dedup();
    let original = LearningArtifactManifestV2 {
        artifact_id: bundle.artifact_id.clone(),
        kind: ArtifactKind::Model,
        generation: bundle.generation,
        provenance_mode: ProvenanceModeV1::DatasetDerived,
        source_dataset_digests: vec![lineage.dataset],
        lineage_digests,
        predecessor_ids: vec![
            decision
                .snapshot
                .request
                .selected_bundle
                .artifact_id
                .clone(),
        ],
        rollback_predecessor: Some(
            decision
                .snapshot
                .request
                .selected_bundle
                .artifact_id
                .clone(),
        ),
        bytes_digest: Digest32::of_bytes(&payload),
        encoded_size_bytes: payload.len() as u64,
        training_code_digest: Digest32::from_array(manifest.source_digest),
        runtime_tuple_digest: Digest32::from_array(manifest.runtime_digest),
        device_profile_digest: Digest32::from_array(manifest.device_digest),
        objective_class_digest: decision.snapshot.request.envelope.objective_digest,
        compatibility_digest: Digest32::from_array(manifest.digest().map_err(refused)?),
        schema_profile_digest: bundle.components.state_schema,
        normalization_digest: bundle.components.normalizer,
        producer_id: decision.snapshot.owners.trainer.clone(),
        // Preserve the existing head issuer's signed window. No new timestamp
        // or local signature can extend its validity.
        created_at: signed_current_head.witness.issued_at,
        expires_at: signed_current_head.witness.expires_at,
    };
    let admission = admit_manifest_at_withdrawal_head_v3(
        owner.withdrawal_registry(),
        owner.withdrawal_registry().head_digest(),
        original,
        now,
    )
    .map_err(refused)?;
    Ok(LearningArtifactPublishRequestV1 {
        operation_id: decision.artifact_operation.clone(),
        admission,
        payload,
        signed_current_head,
        expected_registry_predecessor_head: owner.registry().snapshot().head_digest,
        now,
    })
}
