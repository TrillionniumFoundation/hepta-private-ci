//! Data checks around original capabilities. None of these helpers constructs
//! an owner or treats a historical snapshot as publication authorization.

use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_learning_artifacts::LearningEvaluationDispositionV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::ProvenanceModeV1;
use codex_hepta_neuron::CellCandidateKindV1;
use codex_hepta_neuron::CellEncodingRequestV1;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use codex_hepta_neuron::CellInputEncoderV1;

use crate::CellQ24FeatureWorkerV1;

use super::*;

pub(super) struct Decision {
    pub(super) snapshot: LearningIterationSnapshotV1,
    pub(super) bundle: CellCompatibilityBundleV1,
    pub(super) operation: StableId,
    pub(super) artifact_operation: StableId,
}

impl Decision {
    pub(super) fn new(snapshot: LearningIterationSnapshotV1) -> Result<Self, Error> {
        let coordinator = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())
            .map_err(|_| Error::Binding("original decision history"))?;
        if coordinator.next_stage() != Some(LearningIterationStageV1::Selection)
            || !matches!(
                snapshot.receipts.last().map(|r| &r.observation),
                Some(
                    LearningIterationObservationV1::LocalDecisionV2(_)
                        | LearningIterationObservationV1::TrainingNoUpdateV2(_)
                        | LearningIterationObservationV1::Evaluation {
                            disposition: LearningEvaluationDispositionV1::NoUpdate,
                            ..
                        }
                )
            )
        {
            return Err(Error::Binding(
                "actual local decision or original NoUpdate cut required",
            ));
        }
        let bundle = coordinator
            .next_task_bundle()
            .ok_or(Error::Binding("selected learning bundle"))?
            .clone();
        let operation = if bundle == snapshot.request.selected_bundle {
            crate::learning_retained_task_operation_id_v1(&coordinator)?
        } else {
            crate::learning_updated_task_operation_id_v1(&coordinator)?
        };
        let artifact_operation = StableId::new(format!(
            "q24-artifact:{}",
            Digest32::of_parts(&[
                b"hepta.agentd.q24-publication-artifact.v1\0",
                snapshot.head_digest.as_array(),
            ])
        ))
        .map_err(|_| Error::Binding("bounded original artifact operation"))?;
        Ok(Self {
            snapshot,
            bundle,
            operation,
            artifact_operation,
        })
    }

    pub(super) fn adopts(&self) -> bool {
        self.bundle != self.snapshot.request.selected_bundle
    }

    pub(super) fn require_new_work(&self) -> Result<(), Error> {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| Error::Binding("original work clock"))?
            .as_secs();
        if now >= self.snapshot.request.envelope.expiry_unix_seconds {
            return Err(Error::Binding("new publication after original deadline"));
        }
        Ok(())
    }
}

pub(super) fn artifact_request(
    decision: &Decision,
    original: &CellBackendManifestV2,
    request: &LearningArtifactPublishRequestV1,
) -> Result<(), Error> {
    artifact_material(
        decision,
        original,
        &request.admission.validated_manifest.manifest,
        &request.payload,
        &request.operation_id,
    )
}

pub(super) fn artifact_material(
    decision: &Decision,
    original: &CellBackendManifestV2,
    manifest: &codex_hepta_learning_artifacts::LearningArtifactManifestV2,
    payload: &[u8],
    operation: &StableId,
) -> Result<(), Error> {
    let bundle = &decision.bundle;
    let lineage = bundle
        .training_lineage
        .as_ref()
        .ok_or(Error::Binding("original trained lineage"))?;
    let bytes = serde_json::to_vec(original)
        .map_err(|_| Error::Binding("canonical original B manifest"))?;
    crate::cell_composed_q24::validate_manifest(bundle, original)
        .map_err(|_| Error::Binding("original qualified Q24 manifest"))?;
    if !decision.adopts()
        || operation != &decision.artifact_operation
        || bytes.is_empty()
        || bytes.len() > 64 * 1024
        || payload != bytes
        || manifest.kind != ArtifactKind::Model
        || manifest.artifact_id != bundle.artifact_id
        || manifest.generation != bundle.generation
        || manifest.provenance_mode != ProvenanceModeV1::DatasetDerived
        || manifest.source_dataset_digests != [lineage.dataset]
        || manifest.predecessor_ids
            != [decision
                .snapshot
                .request
                .selected_bundle
                .artifact_id
                .clone()]
        || manifest.rollback_predecessor.as_ref()
            != Some(&decision.snapshot.request.selected_bundle.artifact_id)
        || manifest.producer_id != decision.snapshot.owners.trainer
        || manifest.bytes_digest != Digest32::of_bytes(&bytes)
        || manifest.encoded_size_bytes != bytes.len() as u64
        || manifest.training_code_digest.as_array() != &original.source_digest
        || manifest.runtime_tuple_digest.as_array() != &original.runtime_digest
        || manifest.device_profile_digest.as_array() != &original.device_digest
        || manifest.objective_class_digest != decision.snapshot.request.envelope.objective_digest
        || manifest.compatibility_digest.as_array()
            != &original
                .digest()
                .map_err(|_| Error::Binding("original B manifest digest"))?
        || manifest.schema_profile_digest != bundle.components.state_schema
        || manifest.normalization_digest != bundle.components.normalizer
        || [
            lineage.source_bundle,
            lineage.dataset,
            lineage.update_rule,
            lineage.evaluation_profile,
        ]
        .iter()
        .any(|value| !manifest.lineage_digests.contains(value))
        || decision
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
            .any(|receipt| !manifest.lineage_digests.contains(&receipt.evidence_digest))
    {
        return Err(Error::Binding(
            "artifact request differs from original qualified material",
        ));
    }
    Ok(())
}

pub(super) fn signed_selection(
    decision: &Decision,
    signed: &SignedArtifactSelectionV1,
    publication: Option<&ArtifactPublicationReceiptV1>,
) -> Result<(), Error> {
    if signed.artifact_kind != ArtifactKind::Model
        || signed.artifact_id != decision.bundle.artifact_id
        || signed.artifact_generation != decision.bundle.generation
        || publication.is_some_and(|receipt| {
            receipt.operation_id != decision.artifact_operation
                || receipt.registry_head_digest != signed.registry_head_digest
        })
    {
        return Err(Error::Binding(
            "independent selection differs from actual publication",
        ));
    }
    Ok(())
}

pub(super) fn feature_target(
    decision: &Decision,
    target: &AgentdGenerationUpdateTargetV1<FileAnchorWitnessStore>,
    definition: &CellDefinitionV1,
    source: &CircuitTaskSourceInputV1,
    model: &Arc<LoadedCellQ24ModelV1>,
) -> Result<(), Error> {
    let request = &decision.snapshot.request;
    let manifest = &target.config.manifest;
    crate::cell_composed_q24::validate_manifest(&decision.bundle, manifest)
        .map_err(|_| Error::Binding("C complete selected manifest"))?;
    let scope = &target.config.initial.scope;
    if source.scope.run_id == request.source_run_id
        || source.scope.agent_id != request.agent_id
        || source.scope.cell_id != request.cell_id
        || source.scope.principal_digest.to_string() != request.principal_id.as_str()
        || scope.run_id != source.scope.run_id.as_str()
        || scope.agent_id != source.scope.agent_id.as_str()
        || scope.cell_id != source.scope.cell_id.as_str()
        || scope.principal_digest != source.scope.principal_digest.into_array()
        || target.config.source_frontier != source.source_frontier.into_array()
        || target.config.task_digest
            != crate::circuit_feature_task_digest_v1(definition, source)?.into_array()
        || definition.bundle_digest.into_array() != manifest.bundle_digest
        || definition.state_schema_digest.into_array() != manifest.state_schema
        || Some(definition.runtime.encoder_digest.into_array()) != manifest.encoder
        || Some(definition.runtime.head_digest.into_array()) != manifest.head
    {
        return Err(Error::Binding("exact independent ordinary C task"));
    }
    require_executable_feature(&decision.bundle, manifest, model, definition, source)
}

/// Invoke the ordinary worker constructor and exact input decoder without
/// inference, journal preparation, FinalUse claims or CURRENT writes. These
/// deterministic checks confer no authority and do not predict task success.
/// Live admission, clocks and resource observations remain the runtime owners.
pub(super) fn require_executable_feature(
    bundle: &CellCompatibilityBundleV1,
    manifest: &CellBackendManifestV2,
    model: &Arc<LoadedCellQ24ModelV1>,
    definition: &CellDefinitionV1,
    source: &CircuitTaskSourceInputV1,
) -> Result<(), Error> {
    crate::cell_composed_q24::validate_manifest(bundle, manifest)
        .map_err(|_| Error::Binding("C complete selected manifest"))?;
    if definition.runtime.runtime_digest.into_array() != manifest.runtime_digest
        || definition.runtime.device_digest.into_array() != manifest.device_digest
    {
        return Err(Error::Binding("C runtime differs from selected manifest"));
    }
    // A rehashed task digest is not a substitute for the exact candidate-mask
    // structure. Reject truncation, injection and reordered candidate IDs
    // before a successor is prepared or a FinalUse grant can be requested.
    if source.candidates.len() != definition.candidates.len()
        || source
            .candidates
            .iter()
            .zip(&definition.candidates)
            .any(|(mask, candidate)| mask.candidate_id != candidate.candidate_id)
    {
        return Err(Error::Binding("C candidate mask differs from definition"));
    }
    let worker = CellQ24FeatureWorkerV1::new(Arc::clone(model), bundle, definition)
        .map_err(|_| Error::Binding("C loaded model or worker definition"))?;
    if source.observation.len() > definition.max_input_bytes
        || source
            .candidates
            .iter()
            .zip(&definition.candidates)
            .any(|(mask, candidate)| {
                candidate.kind == CellCandidateKindV1::Abstain && !mask.allowed
            })
    {
        return Err(Error::Binding("C ordinary input capacity or abstention"));
    }
    worker
        .input_encoder()
        .encode(&CellEncodingRequestV1 {
            scope: &source.scope,
            source_frontier: source.source_frontier,
            encoder_digest: definition.runtime.encoder_digest,
            observation: &source.observation,
            checkpoint: None,
        })
        .map_err(|_| Error::Binding("C canonical Q24 input"))?;
    Ok(())
}

pub(super) fn predecessor(
    decision: &Decision,
    original: &AgentdGenerationUpdatePredecessorFilesV1<FileAnchorWitnessStore>,
    previous: &PublishedCircuitFeatureCompletionV1,
    source: &CircuitTaskSourceInputV1,
) -> Result<(), Error> {
    crate::cell_composed_q24::validate_manifest(
        &decision.snapshot.request.selected_bundle,
        &original.config.manifest,
    )
    .map_err(|_| Error::Binding("actual baseline manifest"))?;
    if original.config.initial.scope.run_id != decision.snapshot.request.source_run_id.as_str() {
        return Err(Error::Binding("original completed A run"));
    }
    let expected = CellGenerationOwnerBindingV1::new(&original.config, original.max_records)
        .map_err(|_| Error::Binding("original predecessor binding"))?;
    previous.require_publication_predecessor(&expected)?;
    if previous.source_publication().input().observation == source.observation {
        return Err(Error::Binding(
            "ordinary C must have a distinct original input",
        ));
    }
    Ok(())
}
