//! Executable ordinary first-task target before any initial CURRENT effect.
//! The real worker/decoder preflight confers no authority. Publication still
//! uses the original artifact owner and original FinalUse consumer.

use crate::AgentdError;
use crate::AgentdGenerationUpdateAuthoritiesV1;
use crate::AgentdSelectedGenerationV1;
use crate::CircuitTaskSourceInputV1;
use crate::LoadedCellQ24ModelV1;
use crate::OriginalRootGenerationInitialV1;
use crate::PreparedAgentdGenerationInitialV1;
use crate::PublishedCircuitFeatureTaskV1;
use crate::RootGenerationJournalInputsV1;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_neuron::CellDefinitionV1;
use codex_hepta_neuron::CellGenerationConfigV2;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_types::Digest32;
use std::sync::Arc;

/// Original host inputs. A model, bundle or scope description cannot replace
/// the retained files, live Root route, independently selected artifact or grant.
pub struct OriginalRootInitialFeatureTargetV1 {
    pub files: RootGenerationJournalInputsV1,
    pub model: Arc<LoadedCellQ24ModelV1>,
    pub bundle: CellCompatibilityBundleV1,
    pub definition: CellDefinitionV1,
    pub source: CircuitTaskSourceInputV1,
}

pub struct PreparedRootInitialFeatureV1 {
    original: PreparedAgentdGenerationInitialV1<FileAnchorWitnessStore>,
    config: CellGenerationConfigV2,
    model: Arc<LoadedCellQ24ModelV1>,
    bundle: CellCompatibilityBundleV1,
    definition: CellDefinitionV1,
    source: CircuitTaskSourceInputV1,
}

impl OriginalRootGenerationInitialV1 {
    /// Complete deterministic worker validation precedes Root's None→Prepared.
    /// Missing original deployment or malformed model/input is an error.
    pub fn prepare_feature(
        self,
        authorities: AgentdGenerationUpdateAuthoritiesV1,
        selected: AgentdSelectedGenerationV1,
        target: OriginalRootInitialFeatureTargetV1,
    ) -> Result<PreparedRootInitialFeatureV1, AgentdError> {
        require_feature(
            &target.files.config.generation,
            &target.bundle,
            &target.model,
            &target.definition,
            &target.source,
        )?;
        let config = target.files.config.generation.clone();
        let original = self.prepare_original_initial(authorities, selected, target.files)?;
        Ok(PreparedRootInitialFeatureV1 {
            original,
            config,
            model: target.model,
            bundle: target.bundle,
            definition: target.definition,
            source: target.source,
        })
    }

    /// Read only the same completed original initial operation. Pending or
    /// absent publication never dispatches a grant or repeats a task.
    pub fn recover_feature(
        self,
        authorities: AgentdGenerationUpdateAuthoritiesV1,
        selected: AgentdSelectedGenerationV1,
        target: OriginalRootInitialFeatureTargetV1,
    ) -> Result<PublishedCircuitFeatureTaskV1, AgentdError> {
        require_feature(
            &target.files.config.generation,
            &target.bundle,
            &target.model,
            &target.definition,
            &target.source,
        )?;
        let ready = self.recover_original_initial(authorities, selected, target.files)?;
        ready.into_circuit_feature_task(target.definition, target.source)
    }
}

impl PreparedRootInitialFeatureV1 {
    pub fn final_use_binding(&self) -> &FinalUseBinding {
        self.original.final_use_binding()
    }

    pub fn intent_digest(&self) -> Digest32 {
        self.original.intent_digest()
    }

    pub fn publish(
        self,
        signed: &SignedFinalUseGrant,
    ) -> Result<PublishedCircuitFeatureTaskV1, AgentdError> {
        require_feature(
            &self.config,
            &self.bundle,
            &self.model,
            &self.definition,
            &self.source,
        )?;
        let original: PreparedAgentdGenerationInitialV1<FileAnchorWitnessStore> = self.original;
        original
            .publish(signed)?
            .into_circuit_feature_task(self.definition, self.source)
    }
}

pub(crate) fn require_feature(
    config: &CellGenerationConfigV2,
    bundle: &CellCompatibilityBundleV1,
    model: &Arc<LoadedCellQ24ModelV1>,
    definition: &CellDefinitionV1,
    source: &CircuitTaskSourceInputV1,
) -> Result<(), AgentdError> {
    let manifest = &config.manifest;
    let scope = &config.initial.scope;
    if config.task_digest != crate::circuit_feature_task_digest_v1(definition, source)?.into_array()
        || config.source_frontier != source.source_frontier.into_array()
        || scope.agent_id != source.scope.agent_id.as_str()
        || scope.cell_id != source.scope.cell_id.as_str()
        || scope.run_id != source.scope.run_id.as_str()
        || scope.principal_digest != source.scope.principal_digest.into_array()
        || manifest.profile != crate::CellQ24GenerationWorkerV1::PROFILE
        || manifest.bundle_digest != definition.bundle_digest.into_array()
        || manifest.state_schema != definition.state_schema_digest.into_array()
        || manifest.encoder != Some(definition.runtime.encoder_digest.into_array())
        || manifest.head != Some(definition.runtime.head_digest.into_array())
    {
        return Err(AgentdError::GenerationFenced(
            "exact original initial Feature target required".into(),
        ));
    }
    crate::cell_q24_publication_driver::validation::require_executable_feature(
        bundle, manifest, model, definition, source,
    )
    .map_err(|error| AgentdError::GenerationFenced(error.to_string()))
}
