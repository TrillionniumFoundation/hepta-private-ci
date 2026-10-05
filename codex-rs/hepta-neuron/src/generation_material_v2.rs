//! Whole immutable generation material owned by the original Neuron. A decoded
//! plan grants no store access, physical worker, current model use or admission.
use crate::*;
use codex_hepta_types::Digest32;
use std::path::PathBuf;

#[derive(Clone)]
pub struct NeuronGenerationMaterialV2 {
    pub model_manifest: PathBuf,
    pub model_manifest_digest: Digest32,
    pub generation_store: PathBuf,
    pub runtime_index: PathBuf,
    pub witness: PathBuf,
    pub native: SparseConfig,
    pub scope: JournalScope,
    pub runtime: NeuronRuntimeConfigV1,
    pub body: NeuronBodyBundleIdentityV1,
    pub store_context: NeuronGenerationStoreContextV2,
    pub index_context: NeuronRuntimeIndexContextV2,
    pub witness_context: NeuronWitnessContextV2,
}

#[derive(Debug)]
pub enum NeuronGenerationMaterialErrorV2 {
    Invalid(String),
    Json(serde_json::Error),
}
impl std::fmt::Display for NeuronGenerationMaterialErrorV2 {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Invalid(value) => f.write_str(value),
            Self::Json(error) => error.fmt(f),
        }
    }
}
impl std::error::Error for NeuronGenerationMaterialErrorV2 {}
impl From<serde_json::Error> for NeuronGenerationMaterialErrorV2 {
    fn from(error: serde_json::Error) -> Self {
        Self::Json(error)
    }
}
fn invalid(message: impl std::fmt::Display) -> NeuronGenerationMaterialErrorV2 {
    NeuronGenerationMaterialErrorV2::Invalid(message.to_string())
}

/// Validate the complete original runtime/native/body/context tuple without
/// opening any physical material or converting it into a capability.
pub fn validate_neuron_generation_material_v2(
    plan: &NeuronGenerationMaterialV2,
) -> Result<(), NeuronGenerationMaterialErrorV2> {
    plan.runtime
        .validate_native(&plan.native)
        .map_err(invalid)?;
    let config = &plan.runtime;
    let body = &plan.body;
    let config_digest = config.semantic_digest().map_err(invalid)?;
    let body_digest = body.semantic_digest().map_err(invalid)?;
    if config.native_config_digest != plan.native.digest().map_err(invalid)?
        || config.generation != plan.native.generation
        || config.calibration.generation != config.generation
        || config.model_manifest_digest != plan.model_manifest_digest
        || config.head_digest != plan.native.model_digest
        || config.normalization_digest != plan.native.normalization_digest
        || config.state_width != plan.native.width
        || body.body_generation != config.generation
        || body.effective_parameter_digest
            != config.execution_profile_digest_v1().map_err(invalid)?
        || plan.store_context.generation != config.generation
        || plan.store_context.scope != plan.scope
        || plan.store_context.runtime_config_digest != config_digest
        || plan.store_context.body_bundle_digest != body_digest
        || plan.index_context.generation != config.generation
        || plan.index_context.scope != plan.scope
        || plan.index_context.runtime_config_digest != config_digest
        || plan.index_context.body_bundle_digest != body_digest
        || plan.witness_context.generation != config.generation
        || plan.witness_context.scope != plan.scope
    {
        return Err(invalid(
            "CPU compiler changed body topology or generation-store context",
        ));
    }
    plan.store_context.validate().map_err(invalid)?;
    plan.index_context.validate().map_err(invalid)?;
    plan.witness_context.validate().map_err(invalid)?;
    for path in [
        &plan.model_manifest,
        &plan.generation_store,
        &plan.runtime_index,
        &plan.witness,
    ] {
        if !path.is_absolute() || path.file_name().is_none() {
            return Err(invalid("generation material paths must be absolute files"));
        }
    }
    if plan.generation_store == plan.runtime_index
        || plan.generation_store == plan.witness
        || plan.runtime_index == plan.witness
    {
        return Err(invalid("generation material stores must be distinct"));
    }
    Ok(())
}
