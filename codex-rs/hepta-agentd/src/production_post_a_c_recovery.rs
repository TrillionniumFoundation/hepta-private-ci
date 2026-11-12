//! Existing C is observed through its original Root registration. The daemon
//! opens only the existing generation target and never reopens Source/Cell
//! writers, submits ingress, requests a grant, or publishes a new CURRENT.

use super::*;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellDefinitionV1;
use codex_hepta_types::Digest32;

pub(in crate::production_launcher::post_a_q24) struct OriginalExistingCTask {
    pub(in crate::production_launcher::post_a_q24) target_data: CellGenerationObserverConfigV1,
    target: crate::AgentdGenerationUpdateTargetV1<FileAnchorWitnessStore>,
    definition: CellDefinitionV1,
    source: crate::CircuitTaskSourceInputV1,
    model: Arc<LoadedCellQ24ModelV1>,
    previous_manifest: CellBackendManifestV2,
    custody: OriginalCTaskCustody,
    mode: OriginalSuccessorRecoveryModeV1,
}

impl OriginalCTaskPlan {
    pub(in crate::production_launcher::post_a_q24) async fn open_original_existing_task(
        self,
        route: &OriginalPreparedPublicationRoute,
        identity: &AgentdIdentity,
        decision: &Decision,
        selected: &CellBackendManifestV2,
        baseline: Arc<LoadedCellQ24ModelV1>,
        owners: &OriginalCellQ24LearningStageOwnersV1,
        files: &mut OriginalFiles,
        cancelled: &CancellationToken,
    ) -> Result<OriginalExistingCTask, AgentdError> {
        if !OriginalCTaskPlan::require_original_mode(&self, route)? {
            return Err(refused("existing C requires the original Recover route"));
        }
        let mode = self
            .recovery
            .ok_or_else(|| refused("explicit original C capture/read phase absent"))?;
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
        let source = self.source.wait_original_value(cancelled).await?;
        let original = OriginalLateValue::with_original_bytes(&source, |bytes| {
            Ok(
                OriginalSingleQ24SourceConfigurationV1::from_original_deployment_bytes(
                    bytes, identity,
                )?,
            )
        })?;
        let target = self.target.wait_original_value(cancelled).await?;
        let target_data = OriginalLateValue::with_original_bytes(&target, |bytes| {
            let data: ObserverData = serde_json::from_slice(bytes)?;
            Ok(data.original_observer_config()?)
        })?;
        if &target_data.generation.manifest != selected {
            return Err(refused(
                "original recovered C target differs from selection",
            ));
        }
        crate::cell_composed_q24::validate_manifest(&decision.bundle, selected).map_err(refused)?;
        let ingress = self.ingress.wait_original_value(cancelled).await?;
        let model = actual_model(owners, decision, baseline).await?;
        let (target_owner, previous_manifest) = route.with_original_data(|fixed| {
            files::require_original_paths(fixed, &original, &self.execution)?;
            let target = open_existing_target(fixed, &target_data, files)?;
            Ok((target, fixed.inputs.previous.generation.manifest.clone()))
        })?;
        let custody = OriginalCTaskCustody {
            source,
            target,
            ingress,
            end: self.end,
        };
        custody.require_original()?;
        OriginalPreparedPublicationRoute::require_current(route)?;
        Ok(OriginalExistingCTask {
            target_data,
            target: target_owner,
            definition: original.definition,
            source: original.source,
            model,
            previous_manifest,
            custody,
            mode,
        })
    }
}

impl OriginalExistingCTask {
    pub(in crate::production_launcher::post_a_q24) fn require_original_custody(
        &self,
    ) -> Result<(), AgentdError> {
        self.custody.require_original()
    }

    pub(in crate::production_launcher::post_a_q24) fn into_original_recovery(
        self,
        intent_digest: Digest32,
        original_a: Arc<OriginalHistoricalTaskReadReceiptV1>,
    ) -> Result<
        (
            crate::cell_q24_publication_driver::OriginalCellQ24HistoricalFeatureRecoveryV1,
            OriginalCTaskCustody,
            OriginalSuccessorRecoveryModeV1,
        ),
        AgentdError,
    > {
        self.custody.require_original()?;
        if intent_digest.is_zero() {
            return Err(refused("the original published intent is absent"));
        }
        Ok((
            crate::cell_q24_publication_driver::OriginalCellQ24HistoricalFeatureRecoveryV1 {
                target: self.target,
                definition: self.definition,
                source: self.source,
                model: self.model,
                previous_manifest: self.previous_manifest,
                original_a,
                intent_digest,
            },
            self.custody,
            self.mode,
        ))
    }
}

fn open_existing_target(
    fixed: &crate::authority_host_runtime::PreparedPublicationData,
    target: &CellGenerationObserverConfigV1,
    files: &mut OriginalFiles,
) -> Result<crate::AgentdGenerationUpdateTargetV1<FileAnchorWitnessStore>, AgentdError> {
    if !matches!(
        fixed.inputs.mode,
        crate::authority_host_runtime::publication_data::Mode::Recover
    ) {
        return Err(refused("original target recovery mode differs"));
    }
    let journal = files.write(&fixed.inputs.target_journal)?;
    let witness = files.write(&fixed.inputs.target_witness)?;
    journal.try_lock().map_err(refused)?;
    witness.try_lock().map_err(refused)?;
    if journal.metadata()?.len() == 0 || witness.metadata()?.len() == 0 {
        return Err(refused("original published target history is missing"));
    }
    let witness = FileAnchorWitnessStore::open(
        witness,
        target.witness_scope,
        target.witness_generation,
        target.witness_records,
    )
    .map_err(refused)?;
    if witness.current().map_err(refused)?.is_none() {
        return Err(refused(
            "original target witness has no acknowledged history",
        ));
    }
    Ok(crate::AgentdGenerationUpdateTargetV1 {
        file: journal,
        witness,
        config: target.generation.clone(),
        max_records: target.journal_records,
    })
}
