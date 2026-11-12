//! Lossless raw compatibility-bundle data; only original owner validation can
//! bind it to an actual selected model, Training lineage or CURRENT.
use codex_hepta_learning_artifacts::{CellBundleComponentsV1, CellTrainingLineageV1, CellCompatibilityBundleV1};
use codex_hepta_types::{Digest32, Generation, StableId};
use serde::{Deserialize, Serialize};
use crate::AgentdError;
use super::deployment_error;
use super::learning_data::required_option;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalBundleComponentsData {
    pub base: [u8; 32],
    #[serde(deserialize_with = "required_option")]
    pub organ_adapter: Option<[u8; 32]>,
    #[serde(deserialize_with = "required_option")]
    pub cell_adapter: Option<[u8; 32]>,
    pub heads: [u8; 32],
    pub composition: [u8; 32],
    pub encoder: [u8; 32],
    pub tokenizer: [u8; 32],
    pub normalizer: [u8; 32],
    pub calibration: [u8; 32],
    pub numeric_profile: [u8; 32],
    pub output_schema: [u8; 32],
    pub state_schema: [u8; 32],
    pub state_semantics: [u8; 32],
}

impl OriginalBundleComponentsData {
    pub(super) fn original(&self) -> Result<CellBundleComponentsV1, AgentdError> {
        Ok(CellBundleComponentsV1 {
            base: Digest32::from_array(self.base),
            organ_adapter: self.organ_adapter.map(Digest32::from_array),
            cell_adapter: self.cell_adapter.map(Digest32::from_array),
            heads: Digest32::from_array(self.heads),
            composition: Digest32::from_array(self.composition),
            encoder: Digest32::from_array(self.encoder),
            tokenizer: Digest32::from_array(self.tokenizer),
            normalizer: Digest32::from_array(self.normalizer),
            calibration: Digest32::from_array(self.calibration),
            numeric_profile: Digest32::from_array(self.numeric_profile),
            output_schema: Digest32::from_array(self.output_schema),
            state_schema: Digest32::from_array(self.state_schema),
            state_semantics: Digest32::from_array(self.state_semantics),
        })
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalTrainingLineageData {
    pub source_bundle: [u8; 32],
    pub dataset: [u8; 32],
    pub update_rule: [u8; 32],
    pub evaluation_profile: [u8; 32],
}

impl OriginalTrainingLineageData {
    pub(super) fn original(&self) -> Result<CellTrainingLineageV1, AgentdError> {
        Ok(CellTrainingLineageV1 {
            source_bundle: Digest32::from_array(self.source_bundle),
            dataset: Digest32::from_array(self.dataset),
            update_rule: Digest32::from_array(self.update_rule),
            evaluation_profile: Digest32::from_array(self.evaluation_profile),
        })
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalBundleData {
    pub artifact_id: String,
    pub generation: u64,
    pub components: OriginalBundleComponentsData,
    #[serde(deserialize_with = "required_option")]
    pub training_lineage: Option<OriginalTrainingLineageData>,
    #[serde(deserialize_with = "required_option")]
    pub rollback_predecessor: Option<[u8; 32]>,
}

impl OriginalBundleData {
    pub(super) fn from_original(original: &CellCompatibilityBundleV1) -> Self {
        let parts = &original.components;
        Self {
            artifact_id: original.artifact_id.as_str().to_owned(),
            generation: original.generation.get(),
            components: OriginalBundleComponentsData {
                base: parts.base.into_array(),
                organ_adapter: parts.organ_adapter.map(Digest32::into_array),
                cell_adapter: parts.cell_adapter.map(Digest32::into_array),
                heads: parts.heads.into_array(), composition: parts.composition.into_array(),
                encoder: parts.encoder.into_array(), tokenizer: parts.tokenizer.into_array(),
                normalizer: parts.normalizer.into_array(), calibration: parts.calibration.into_array(),
                numeric_profile: parts.numeric_profile.into_array(),
                output_schema: parts.output_schema.into_array(), state_schema: parts.state_schema.into_array(),
                state_semantics: parts.state_semantics.into_array(),
            },
            training_lineage: original.training_lineage.as_ref().map(|lineage| OriginalTrainingLineageData {
                source_bundle: lineage.source_bundle.into_array(), dataset: lineage.dataset.into_array(),
                update_rule: lineage.update_rule.into_array(),
                evaluation_profile: lineage.evaluation_profile.into_array(),
            }),
            rollback_predecessor: original.rollback_predecessor.map(Digest32::into_array),
        }
    }

    pub(super) fn original(&self) -> Result<CellCompatibilityBundleV1, AgentdError> {
        Ok(CellCompatibilityBundleV1 {
            artifact_id: StableId::new(&self.artifact_id).map_err(deployment_error)?,
            generation: Generation::new(self.generation).map_err(deployment_error)?,
            components: self.components.original()?,
            training_lineage: self.training_lineage.as_ref().map(OriginalTrainingLineageData::original).transpose()?,
            rollback_predecessor: self.rollback_predecessor.map(Digest32::from_array),
        })
    }
}

