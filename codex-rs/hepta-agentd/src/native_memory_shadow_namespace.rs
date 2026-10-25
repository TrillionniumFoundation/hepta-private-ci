//! Durable source/profile namespace on the independent witness header.

use crate::native_memory_types::ENCODER;
use crate::native_memory_types::HEAD;
use crate::native_memory_types::NativeMemoryError;
use crate::native_memory_types::NativeMemoryModelConfigV1;
use crate::native_memory_types::parse_digest;
use codex_hepta_memory::MemoryCellSourceBindingV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::NeuronResourceEnvelopeV1;
use codex_hepta_neuron::NeuronRuntime;
use codex_hepta_neuron::NeuronShadowConfigV1;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use std::fs::File;

#[derive(Clone, Copy)]
pub(crate) struct NativeMemoryJournalContext<'a> {
    pub subject: &'a StableId,
    pub objective: Digest32,
    pub binding: Option<&'a crate::NativeMemoryContextBindingV1>,
}

/// Handles must name private, exclusively owned regular files. The witness is
/// retained independently of the journal; it must not be copied from that journal.
pub struct NativeMemoryShadowFilesV1 {
    pub journal: File,
    pub witness: File,
    pub start: NativeMemoryShadowStartV1,
}

pub enum NativeMemoryShadowStartV1 {
    Bootstrap,
    Recover,
}

/// Sparse parameters and limits are supplied by the host and bound to the
/// actual decoder profile. This configuration makes no calibration claim.
pub struct NativeMemoryShadowProfileV1 {
    pub cell_id: StableId,
    pub sparse: SparseConfig,
    pub limits: NeuronResourceEnvelopeV1,
    pub max_records: usize,
}

pub(crate) fn open_runtime(
    files: NativeMemoryShadowFilesV1,
    profile: NativeMemoryShadowProfileV1,
    model: &NativeMemoryModelConfigV1,
    source: &MemoryCellSourceBindingV1,
    owner: &str,
    context: NativeMemoryJournalContext<'_>,
) -> Result<(NeuronRuntime<FileAnchorWitnessStore>, Digest32), NativeMemoryError> {
    let NativeMemoryJournalContext {
        subject,
        objective,
        binding,
    } = context;
    model.validate().map_err(NativeMemoryError::Rejected)?;
    let config = NeuronShadowConfigV1 {
        config_id: StableId::new(model.config_id.clone()).map_err(reject)?,
        generation: Generation::new(model.generation).map_err(reject)?,
        model_id: StableId::new(model.model_id.clone()).map_err(reject)?,
        model_manifest_digest: parse_digest(&model.pins.manifest_sha256).map_err(reject)?,
        encoder_digest: Digest32::of_bytes(ENCODER),
        head_digest: Digest32::of_bytes(HEAD),
        weights_digest: parse_digest(&model.pins.weights_digest).map_err(reject)?,
        tokenizer_digest: parse_digest(&model.pins.tokenizer_digest).map_err(reject)?,
        preprocessor_digest: parse_digest(&model.pins.preprocessor_digest).map_err(reject)?,
        quantization_digest: parse_digest(&model.pins.quantization_digest).map_err(reject)?,
        runtime_digest: parse_digest(&model.pins.runtime_digest).map_err(reject)?,
        device_digest: parse_digest(&model.pins.device_digest).map_err(reject)?,
        normalization_digest: profile.sparse.normalization_digest,
        native_config_digest: profile.sparse.digest().map_err(reject)?,
        input_feature_dimension: 512,
        state_width: model.output_width,
        modulator_dimension: 1,
        resource_envelope: profile.limits,
    };
    let namespace = source_namespace(
        source,
        owner,
        subject,
        &profile.cell_id,
        model,
        config.semantic_digest().map_err(reject)?,
        binding,
    )?;
    // Keep the real objective in both journals. The independent witness's scope
    // also binds the source/model namespace before any recovery is attempted.
    let subject_raw = subject.as_str().as_bytes();
    let scope_digest = Digest32::of_parts(&[
        b"hepta.neuron.subject-scope.v1",
        &(subject_raw.len() as u32).to_be_bytes(),
        subject_raw,
    ]);
    let scope = JournalScope {
        scope_digest,
        objective_digest: objective,
    };
    let witness = FileAnchorWitnessStore::open(
        files.witness,
        JournalScope {
            scope_digest: namespace,
            objective_digest: objective,
        },
        config.generation,
        profile.max_records,
    )
    .map_err(reject)?;
    let runtime = match files.start {
        NativeMemoryShadowStartV1::Bootstrap => NeuronRuntime::bootstrap_shadow(
            files.journal,
            profile.sparse,
            scope,
            profile.max_records,
            config,
            witness,
        ),
        NativeMemoryShadowStartV1::Recover => {
            let anchor = witness.current().map_err(reject)?.ok_or_else(|| {
                NativeMemoryError::Rejected("independent acknowledged witness required".to_string())
            })?;
            NeuronRuntime::recover_shadow(
                files.journal,
                profile.sparse,
                scope,
                profile.max_records,
                config,
                anchor,
                witness,
            )
        }
    }
    .map_err(reject)?;
    Ok((runtime, namespace))
}

pub(crate) fn source_namespace(
    source: &MemoryCellSourceBindingV1,
    owner: &str,
    subject: &StableId,
    cell_id: &StableId,
    model: &NativeMemoryModelConfigV1,
    profile_digest: Digest32,
    context_binding: Option<&crate::NativeMemoryContextBindingV1>,
) -> Result<Digest32, NativeMemoryError> {
    // Query nonce/deadline are deliberately excluded from this stable source
    // cut. Every individual callback still binds them in NativeTickBindingV1.
    let bytes = serde_json::to_vec(&(
        "hepta.memory-cell.shadow-namespace.v1",
        owner,
        subject.as_str(),
        cell_id.as_str(),
        &source.memory,
        source.memory_content_sha256.as_str(),
        source.source_content_sha256.as_str(),
        source.event_digest.to_string(),
        source.production_receipt_digest.as_str(),
        &model.scope,
        model.rank,
        model.seed,
        &model.pins,
        profile_digest.to_string(),
    ))
    .map_err(reject)?;
    let source = Digest32::of_bytes(&bytes);
    Ok(match context_binding {
        None => source,
        Some(binding) => Digest32::of_parts(&[
            b"hepta.memory-cell.shadow-namespace.v2",
            source.as_array(),
            binding.digest().as_array(),
        ]),
    })
}

pub(crate) fn reject(error: impl std::fmt::Display) -> NativeMemoryError {
    NativeMemoryError::Rejected(error.to_string())
}

#[cfg(test)]
#[path = "native_memory_shadow_namespace_tests.rs"]
pub(crate) mod tests;
