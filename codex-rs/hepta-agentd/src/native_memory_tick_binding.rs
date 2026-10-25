//! The tick digest and the admitted query/source cut have distinct meanings.

use codex_hepta_memory::MemoryCellSourceBindingV1;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_types::Digest32;
use serde::Serialize;

use crate::native_memory_types::NativeMemoryError;

#[derive(Clone, Debug, Serialize)]
pub(crate) struct NativeTickBindingV1 {
    schema: &'static str,
    tick_id: String,
    subject_id: String,
    logical_sequence: u64,
    monotonic_time_micros: u64,
    checkpoint_digest: String,
    input_feature_digest: String,
    objective_digest: String,
    ndu_snapshot_digest: String,
    body_generation: Option<u64>,
    modulator_digest: Option<String>,
    tick_digest: String,
    query_digest: String,
    source_binding_digest: String,
    joint_digest: String,
}

impl NativeTickBindingV1 {
    pub(crate) fn new(
        input: &NeuronTickInputV1,
        source: &MemoryCellSourceBindingV1,
    ) -> Result<Self, NativeMemoryError> {
        let tick = input
            .semantic_digest()
            .map_err(|e| NativeMemoryError::Rejected(e.to_string()))?;
        let joint = Digest32::of_parts(&[
            b"hepta.memory-cell.source-query-tick.v1",
            source.binding_digest.as_array(),
            source.query_digest.as_array(),
            tick.as_array(),
        ]);
        Ok(Self {
            schema: "hepta.memory-cell.native-tick-binding.v1",
            tick_id: input.tick_id.as_str().to_string(),
            subject_id: input.subject_id.as_str().to_string(),
            logical_sequence: input.logical_sequence,
            monotonic_time_micros: input.monotonic_time_micros,
            checkpoint_digest: input.checkpoint_digest.to_string(),
            input_feature_digest: input.input_feature_digest.to_string(),
            objective_digest: input.objective_digest.to_string(),
            ndu_snapshot_digest: input.ndu_snapshot_digest.to_string(),
            body_generation: input.body_generation,
            modulator_digest: input.modulator_digest.map(|d| d.to_string()),
            tick_digest: tick.to_string(),
            query_digest: source.query_digest.to_string(),
            source_binding_digest: source.binding_digest.to_string(),
            joint_digest: joint.to_string(),
        })
    }
}
