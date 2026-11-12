//! Original C data and files enter the existing supervised successor worker.
//! The actual Trainer material supplies the model, and the completed historical
//! A receipt supplies the predecessor fact; neither is inferred from a manifest.

use std::path::PathBuf;
use std::sync::Arc;
use std::time::Instant;

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_neuron::CellBackendManifestV2;
use codex_hepta_neuron::CellGenerationObserverConfigV1;
use codex_hepta_neuron::FileAnchorWitnessStore;
use serde::Deserialize;
use tokio_util::sync::CancellationToken;

use super::OriginalFiles;
use super::late_input::OriginalLateInput;
use super::late_input::OriginalLateValue;
use super::owners::OpenMode;
use super::post_a_remaining;
use super::refused;
use crate::AgentdError;
use crate::AgentdGenerationUpdatePredecessorFilesV1;
use crate::AgentdIdentity;
use crate::AuthBusObjectiveIngress;
use crate::LoadedCellQ24ModelV1;
use crate::OriginalCellQ24FeatureTargetV1;
use crate::OriginalCellQ24LearningStageOwnersV1;
use crate::OriginalQ24SuccessorExecutionInputsV1;
use crate::OriginalSingleQ24SourceConfigurationV1;
use crate::PublishedCircuitFeatureCompletionV1;
use crate::authority_host_runtime::publication_data::ObserverData;
use crate::cell_q24_publication_driver::validation::Decision;
use crate::root_generation_publication_inputs::OriginalPreparedPublicationRoute;
use crate::root_historical_task_read_client::OriginalHistoricalTaskReadReceiptV1;

#[path = "production_post_a_c_files.rs"]
mod files;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct CTaskData {
    source: PathBuf,
    target: PathBuf,
    signed_ingress: PathBuf,
    mode: OpenMode,
    clock_domain: String,
    files: files::ExecutionFilesData,
}

pub(super) struct OriginalCTaskPlan {
    source: OriginalLateInput,
    target: OriginalLateInput,
    ingress: OriginalLateInput,
    mode: OpenMode,
    execution: files::ExecutionFilesData,
    end: Instant,
}

pub(super) struct OriginalCTaskCustody {
    source: OriginalLateValue,
    target: OriginalLateValue,
    ingress: OriginalLateValue,
    end: Instant,
}

impl OriginalCTaskCustody {
    pub(super) fn require_original(&self) -> Result<(), AgentdError> {
        post_a_remaining(self.end)?;
        self.source.require_unchanged()?;
        self.target.require_unchanged()?;
        self.ingress.require_unchanged()?;
        post_a_remaining(self.end)?;
        Ok(())
    }
}

pub(super) struct OriginalNewCTask {
    pub(super) predecessor: AgentdGenerationUpdatePredecessorFilesV1<FileAnchorWitnessStore>,
    pub(super) target: OriginalCellQ24FeatureTargetV1,
    pub(super) target_data: CellGenerationObserverConfigV1,
    pub(super) execution: OriginalQ24SuccessorExecutionInputsV1,
    pub(super) ingress: AuthBusObjectiveIngress,
    pub(super) custody: OriginalCTaskCustody,
}

impl CTaskData {
    pub(super) fn open_original(
        self,
        files: &mut OriginalFiles,
        end: Instant,
    ) -> Result<OriginalCTaskPlan, AgentdError> {
        if self.clock_domain != super::super::initial_q24::clock::DOMAIN {
            return Err(refused(
                "C must retain the actual original monotonic clock domain",
            ));
        }
        self.files.require_bounds()?;
        Ok(OriginalCTaskPlan {
            source: OriginalLateInput::open_original(self.source, files, end)?,
            target: OriginalLateInput::open_original(self.target, files, end)?,
            ingress: OriginalLateInput::open_original(self.signed_ingress, files, end)?,
            mode: self.mode,
            execution: self.files,
            end,
        })
    }
}

impl OriginalCTaskPlan {
    pub(super) async fn open_original_new_task(
        self,
        route: &OriginalPreparedPublicationRoute,
        identity: &AgentdIdentity,
        decision: &Decision,
        selected: &CellBackendManifestV2,
        baseline: Arc<LoadedCellQ24ModelV1>,
        owners: &OriginalCellQ24LearningStageOwnersV1,
        receipt: &OriginalHistoricalTaskReadReceiptV1,
        files: &mut OriginalFiles,
        cancelled: &CancellationToken,
    ) -> Result<OriginalNewCTask, AgentdError> {
        if !matches!(self.mode, OpenMode::Create) {
            return Err(refused(
                "an existing C requires explicit original cold recovery",
            ));
        }
        route.with_original_data(|fixed| {
            for (input, expected) in [
                (&self.source, &fixed.successor.source_configuration),
                (&self.target, &fixed.successor.target_configuration),
                (&self.ingress, &fixed.successor.signed_ingress),
            ] {
                OriginalLateInput::require_original_pin(
                    input,
                    &expected.path,
                    (
                        expected.device,
                        expected.inode,
                        expected.uid,
                        expected.gid,
                        expected.mode,
                    ),
                )?;
            }
            Ok(())
        })?;
        route.require_current()?;
        let source = self.source.wait_original_value(cancelled).await?;
        let original = OriginalLateValue::with_original_bytes(&source, |bytes| {
            Ok(
                OriginalSingleQ24SourceConfigurationV1::from_original_deployment_bytes(
                    bytes, identity,
                )?,
            )
        })?;
        super::super::initial_q24::clock::require_source_deadline(&original.source)?;
        let target = self.target.wait_original_value(cancelled).await?;
        let target_data = OriginalLateValue::with_original_bytes(&target, |bytes| {
            let data: ObserverData = serde_json::from_slice(bytes)?;
            Ok(data.original_observer_config()?)
        })?;
        if &target_data.generation.manifest != selected {
            return Err(refused(
                "original C target differs from the selected full manifest",
            ));
        }
        crate::cell_composed_q24::validate_manifest(&decision.bundle, selected).map_err(refused)?;
        let ingress = self.ingress.wait_original_value(cancelled).await?;
        let request = OriginalLateValue::with_original_bytes(&ingress, |bytes| {
            Ok(serde_json::from_slice(bytes)?)
        })?;
        let model = actual_model(owners, decision, baseline).await?;
        let (predecessor, new_target, execution) = route.with_original_data(|fixed| {
            files::open_original_new_files(fixed, &target_data, &original, &self.execution, files)
        })?;
        let previous = route.with_original_data(|fixed| {
            PublishedCircuitFeatureCompletionV1::read_original_historical_completion(
                receipt,
                fixed.inputs.previous.generation.manifest.clone(),
            )
        })?;
        let custody = OriginalCTaskCustody {
            source,
            target,
            ingress,
            end: self.end,
        };
        custody.require_original()?;
        route.require_current()?;
        super::super::initial_q24::clock::require_source_deadline(&original.source)?;
        Ok(OriginalNewCTask {
            predecessor,
            target: OriginalCellQ24FeatureTargetV1 {
                target: new_target,
                definition: original.definition,
                source: original.source,
                model,
                previous,
            },
            target_data,
            execution,
            ingress: request,
            custody,
        })
    }
}

async fn actual_model(
    owners: &OriginalCellQ24LearningStageOwnersV1,
    decision: &Decision,
    baseline: Arc<LoadedCellQ24ModelV1>,
) -> Result<Arc<LoadedCellQ24ModelV1>, AgentdError> {
    if !decision.adopts() {
        if baseline.components() != &decision.bundle.components {
            return Err(refused("actual retained baseline components differ"));
        }
        return Ok(baseline);
    }
    let mut training =
        LearningIterationCoordinatorV1::from_snapshot(owners.prepared().initial().clone())
            .map_err(refused)?;
    for receipt in &decision.snapshot.receipts {
        training
            .record(receipt.clone(), receipt.observed_unix_seconds)
            .map_err(refused)?;
        if receipt.observation.stage() == LearningIterationStageV1::Training {
            let material = owners
                .read_original_training_material(training.snapshot())
                .await
                .map_err(refused)?;
            return match material.into_completion().outcome {
                crate::CellQ24TrainingOutcomeV1::Candidate(candidate)
                    if candidate.bundle == decision.bundle =>
                {
                    Ok(Arc::new(candidate.model))
                }
                _ => Err(refused(
                    "original Trainer material differs from adopted C bundle",
                )),
            };
        }
    }
    Err(refused("original adopted decision has no Trainer cut"))
}
