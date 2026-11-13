//! Full immutable Cell model/routing configuration, encoded as data only.
//! Construction repeats the original semantic validators; no writer, model
//! service, grant, inference port or task receipt is decoded from these bytes.

use codex_hepta_neuron::{CellCandidateKindV1, CellCandidateV1, CellDefinitionV1,
    InhibitoryEdge, NeuronCalibrationProfileV1, NeuronResourceEnvelopeV1,
    NeuronRuntimeConfigV1, SparseConfig};
use super::CircuitTaskErrorV1 as Error;
use super::root_bootstrap_codec::{Reader, Writer};

pub(crate) fn encode(out: &mut Writer, cell: &CellDefinitionV1) -> Result<(), Error> {
    cell.semantic_digest().map_err(|_| Error::InvalidBinding)?;
    out.id(&cell.cell_id)?;
    out.digest(cell.bundle_digest)?;
    out.digest(cell.state_schema_digest)?;
    runtime(out, &cell.runtime)?;
    native(out, &cell.native)?;
    out.count(cell.candidates.len(), 256)?;
    for candidate in &cell.candidates {
        out.id(&candidate.candidate_id)?;
        out.size(candidate.activation_index)?;
        out.byte(match candidate.kind { CellCandidateKindV1::Action => 1,
            CellCandidateKindV1::Abstain => 2, CellCandidateKindV1::SlowPath => 3 })?;
    }
    out.size(cell.max_input_bytes)?;
    out.u64(cell.max_queue_age_micros)?;
    out.u64(cell.max_resident_bytes)
}

pub(crate) fn decode(input: &mut Reader<'_>) -> Result<CellDefinitionV1, Error> {
    let cell_id = input.id()?;
    let bundle_digest = input.digest()?;
    let state_schema_digest = input.digest()?;
    let runtime = read_runtime(input)?;
    let native = read_native(input)?;
    let mut candidates = Vec::new();
    for _ in 0..input.count(256)? {
        candidates.push(CellCandidateV1 { candidate_id: input.id()?, activation_index: input.size()?,
            kind: match input.byte()? { 1 => CellCandidateKindV1::Action, 2 => CellCandidateKindV1::Abstain,
                3 => CellCandidateKindV1::SlowPath, _ => return Err(Error::InvalidBinding) } });
    }
    let cell = CellDefinitionV1 { cell_id, bundle_digest, state_schema_digest, runtime, native, candidates,
        max_input_bytes: input.size()?, max_queue_age_micros: input.u64()?, max_resident_bytes: input.u64()? };
    cell.semantic_digest().map_err(|_| Error::InvalidBinding)?;
    Ok(cell)
}

fn runtime(out: &mut Writer, value: &NeuronRuntimeConfigV1) -> Result<(), Error> {
    out.id(&value.config_id)?;
    out.generation(value.generation)?;
    out.id(&value.model_id)?;
    out.digest(value.model_manifest_digest)?;
    out.digest(value.encoder_digest)?;
    out.digest(value.head_digest)?;
    out.digest(value.weights_digest)?;
    out.digest(value.tokenizer_digest)?;
    out.digest(value.preprocessor_digest)?;
    out.digest(value.quantization_digest)?;
    out.digest(value.runtime_digest)?;
    out.digest(value.device_digest)?;
    out.digest(value.normalization_digest)?;
    out.digest(value.native_config_digest)?;
    out.size(value.input_feature_dimension)?;
    out.size(value.state_width)?;
    out.size(value.modulator_dimension)?;
    out.digest(value.calibration.calibration_artifact_digest)?;
    out.digest(value.calibration.ood_artifact_digest)?;
    out.generation(value.calibration.generation)?;
    out.u64(value.calibration.valid_from_sequence)?;
    out.u64(value.calibration.expires_after_sequence)?;
    out.i64(value.calibration.zero_confidence_error_q24)?;
    out.i64(value.calibration.maximum_in_domain_error_q24)?;
    out.u32(value.calibration.minimum_confidence_ppm)?;
    out.u32(value.calibration.maximum_ood_ppm)?;
    out.u32(value.calibration.minimum_active_ppm)?;
    out.u32(value.calibration.maximum_active_ppm)?;
    out.u32(value.calibration.maximum_projection_count)?;
    out.u32(value.calibration.measured_ece_ppm)?;
    out.u32(value.calibration.maximum_ece_ppm)?;
    out.u32(value.calibration.measured_false_acceptance_ppm)?;
    out.u32(value.calibration.maximum_false_acceptance_ppm)?;
    out.u64(value.resource_envelope.p95_latency_micros)?;
    out.u64(value.resource_envelope.p99_latency_micros)?;
    out.u64(value.resource_envelope.transient_allocation_bytes)?;
    out.u64(value.resource_envelope.checkpoint_bytes)?;
    out.u32(value.resource_envelope.write_amplification_ppm)?;
    Ok(())
}

fn read_runtime(input: &mut Reader<'_>) -> Result<NeuronRuntimeConfigV1, Error> {
    Ok(NeuronRuntimeConfigV1 {
        config_id: input.id()?,
        generation: input.generation()?,
        model_id: input.id()?,
        model_manifest_digest: input.digest()?,
        encoder_digest: input.digest()?,
        head_digest: input.digest()?,
        weights_digest: input.digest()?,
        tokenizer_digest: input.digest()?,
        preprocessor_digest: input.digest()?,
        quantization_digest: input.digest()?,
        runtime_digest: input.digest()?,
        device_digest: input.digest()?,
        normalization_digest: input.digest()?,
        native_config_digest: input.digest()?,
        input_feature_dimension: input.size()?,
        state_width: input.size()?,
        modulator_dimension: input.size()?,
        calibration: NeuronCalibrationProfileV1 {
        calibration_artifact_digest: input.digest()?,
        ood_artifact_digest: input.digest()?,
        generation: input.generation()?,
        valid_from_sequence: input.u64()?,
        expires_after_sequence: input.u64()?,
        zero_confidence_error_q24: input.i64()?,
        maximum_in_domain_error_q24: input.i64()?,
        minimum_confidence_ppm: input.u32()?,
        maximum_ood_ppm: input.u32()?,
        minimum_active_ppm: input.u32()?,
        maximum_active_ppm: input.u32()?,
        maximum_projection_count: input.u32()?,
        measured_ece_ppm: input.u32()?,
        maximum_ece_ppm: input.u32()?,
        measured_false_acceptance_ppm: input.u32()?,
        maximum_false_acceptance_ppm: input.u32()?,
        },
        resource_envelope: NeuronResourceEnvelopeV1 {
        p95_latency_micros: input.u64()?,
        p99_latency_micros: input.u64()?,
        transient_allocation_bytes: input.u64()?,
        checkpoint_bytes: input.u64()?,
        write_amplification_ppm: input.u32()?,
        },
    })
}

fn native(out: &mut Writer, value: &SparseConfig) -> Result<(), Error> {
    out.digest(value.model_digest)?;
    out.digest(value.normalization_digest)?;
    out.generation(value.generation)?;
    out.size(value.width)?;
    out.size(value.top_k)?;
    out.i64(value.temporal_decay_q24)?;
    out.i64(value.inhibition_gain_q24)?;
    out.count(value.inhibition.len(), 4096)?;
    for edge in &value.inhibition { out.size(edge.source)?; out.size(edge.target)?; out.i64(edge.weight_q24)?; }
    out.i64(value.activity_decay_q24)?;
    out.i64(value.target_activity_q24)?;
    out.i64(value.threshold_rate_q24)?;
    out.i64(value.threshold_min_q24)?;
    out.i64(value.threshold_max_q24)?;
    out.i64(value.eligibility_decay_q24)?;
    Ok(())
}

fn read_native(input: &mut Reader<'_>) -> Result<SparseConfig, Error> {
    let model_digest = input.digest()?;
    let normalization_digest = input.digest()?;
    let generation = input.generation()?;
    let width = input.size()?;
    let top_k = input.size()?;
    let temporal_decay_q24 = input.i64()?;
    let inhibition_gain_q24 = input.i64()?;
    let mut inhibition = Vec::new();
    for _ in 0..input.count(4096)? {
        inhibition.push(InhibitoryEdge { source: input.size()?, target: input.size()?, weight_q24: input.i64()? });
    }
    Ok(SparseConfig {
        model_digest,
        normalization_digest,
        generation,
        width,
        top_k,
        temporal_decay_q24,
        inhibition_gain_q24,
        inhibition,
        activity_decay_q24: input.i64()?,
        target_activity_q24: input.i64()?,
        threshold_rate_q24: input.i64()?,
        threshold_min_q24: input.i64()?,
        threshold_max_q24: input.i64()?,
        eligibility_decay_q24: input.i64()?,
    })
}
