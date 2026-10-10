//! A bounded CPU Q24 gated head driver for qualification.
//!
//! Executes actual, checked numerical head operations, not fabricated logits.
//! This implementation accepts precomputed Q24 features and cannot run a
//! Transformer encoder. The V1 request has no cell-principal field, so this
//! driver MUST NOT be treated as a production final-use authorizer, a
//! CAS-verified artifact loader, or proof of principal-isolated dispatch.

use std::collections::BTreeMap;
use std::time::Instant;

use codex_hepta_types::Digest32;

use super::DriverModelHandle;
use super::DriverNeuronFeatureObservation;
use super::DriverRunObservation;
use super::Error;
use super::ModelDriver;
use super::ModelManifest;
use super::NeuronFeatureBatchDriver;
use super::NeuronFeatureDriver;
use super::NeuronFeatureRequest;
use super::WorkerRequest;
use super::validate_manifest;

const Q24: i64 = 1 << 24;
const Q24_BOUND: i64 = 8 * Q24;
const MAX_DIM: usize = 512;
const MAX_HEAD_PARAMETERS: usize = 262_144;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GatedHeadCandidateV2 {
    pub cell_identity: String,
    pub encoder_digest: String,
    pub input_width: usize,
    pub output_width: usize,
    pub gate_q24: Vec<i64>,
    pub drive_weights_q24: Vec<i64>,
    pub prediction_weights_q24: Vec<i64>,
    pub drive_bias_q24: Vec<i64>,
    pub prediction_bias_q24: Vec<i64>,
}

#[derive(Clone, Debug)]
struct GatedHeadArtifactV2 {
    candidate: GatedHeadCandidateV2,
    head_digest: String,
    parameter_count: usize,
}

/// Qualification-only CPU driver; no signed artifact load/worker CAS.
///
/// The `observed_memory_bytes` field in this reference adapter counts owned
/// parameter tensors rather than full OS RSS, so it is not a production
/// resource receipt.
#[derive(Debug)]
pub struct GatedHeadCpuDriverV2 {
    selected_manifest: ModelManifest,
    heads: BTreeMap<String, GatedHeadArtifactV2>,
    loaded: bool,
    tensor_bytes: usize,
    batch_calls: usize,
}

impl GatedHeadCpuDriverV2 {
    pub fn new(selected_manifest: ModelManifest) -> Result<Self, Error> {
        validate_manifest(&selected_manifest)?;
        Ok(Self {
            selected_manifest,
            heads: BTreeMap::new(),
            loaded: false,
            tensor_bytes: 0,
            batch_calls: 0,
        })
    }

    /// Register only before the manifest is loaded into the worker. A new
    /// candidate creates a new digest rather than mutating selected weights.
    pub fn register_head(&mut self, candidate: GatedHeadCandidateV2) -> Result<String, Error> {
        if self.loaded {
            return Err(Error::ActiveRequests);
        }
        validate_candidate(&candidate)?;
        let parameter_count = parameter_count(&candidate)?;
        let bytes = parameter_count
            .checked_mul(std::mem::size_of::<i64>())
            .ok_or(Error::ArithmeticOverflow)?;
        let next_bytes = self.tensor_bytes.checked_add(bytes)
            .ok_or(Error::ArithmeticOverflow)?;
        let head_digest = candidate_digest(&candidate);
        if self.heads.contains_key(&head_digest) {
            return Err(Error::ModelAlreadyLoaded);
        }
        self.heads.insert(
            head_digest.clone(),
            GatedHeadArtifactV2 {
                candidate,
                head_digest: head_digest.clone(),
                parameter_count,
            },
        );
        self.tensor_bytes = next_bytes;
        Ok(head_digest)
    }

    pub fn parameter_bytes(&self) -> usize {
        self.tensor_bytes
    }

    pub fn batch_calls(&self) -> usize {
        self.batch_calls
    }

    fn verify_loaded(&self, handle: &DriverModelHandle) -> Result<(), Error> {
        if !self.loaded || handle.opaque_id != format!("gated.cpu:{}", self.selected_manifest.model_id) {
            return Err(Error::ModelNotLoaded);
        }
        Ok(())
    }

    fn compute(&self, request: &NeuronFeatureRequest) -> Result<(Vec<i64>, Vec<i64>), Error> {
        let head = self.heads.get(&request.head_digest).ok_or(Error::ModelNotLoaded)?;
        let candidate = &head.candidate;
        if head.head_digest != request.head_digest
            || candidate.encoder_digest != request.encoder_digest
            || request.expected_output_width != candidate.output_width
            || request.feature_vector_q24.len() != candidate.input_width
        {
            return Err(Error::FeatureOutputMismatch);
        }
        let gated: Vec<i64> = request
            .feature_vector_q24
            .iter()
            .zip(&candidate.gate_q24)
            .map(|(feature, gate)| q24_round_checked(i128::from(*feature) * i128::from(*gate)))
            .collect::<Result<_, _>>()?;
        let drive = dense_q24(
            &gated,
            &candidate.drive_weights_q24,
            &candidate.drive_bias_q24,
        )?;
        let prediction = dense_q24(
            &gated,
            &candidate.prediction_weights_q24,
            &candidate.prediction_bias_q24,
        )?;
        Ok((drive, prediction))
    }
}

impl ModelDriver for GatedHeadCpuDriverV2 {
    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        if *manifest != self.selected_manifest || self.loaded || self.heads.is_empty() {
            return Err(Error::ModelMismatch);
        }
        self.loaded = true;
        Ok(DriverModelHandle {
            opaque_id: format!("gated.cpu:{}", manifest.model_id),
            observed_memory_bytes: u64::try_from(self.tensor_bytes)
                .map_err(|_| Error::ArithmeticOverflow)?,
        })
    }

    fn run(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        // Never reinterpret a general provider request as Q24 Cell inference.
        Err(Error::FeatureContract)
    }

    fn unload(&mut self, handle: DriverModelHandle) -> Result<(), Error> {
        self.verify_loaded(&handle)?;
        self.loaded = false;
        Ok(())
    }
}

impl NeuronFeatureDriver for GatedHeadCpuDriverV2 {
    fn run_neuron_features(
        &mut self,
        handle: &DriverModelHandle,
        request: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, Error> {
        self.verify_loaded(handle)?;
        let started = Instant::now();
        let (drive, prediction) = self.compute(request)?;
        Ok(DriverNeuronFeatureObservation {
            terminal_observed: true,
            succeeded: true,
            encoder_digest: request.encoder_digest.clone(),
            head_digest: request.head_digest.clone(),
            drive_q24: drive,
            prediction_q24: prediction,
            observed_memory_bytes: handle.observed_memory_bytes,
            transient_allocation_bytes: transient_bytes(request)?,
            queue_age_micros: 0,
            latency_micros: u64::try_from(started.elapsed().as_micros())
                .map_err(|_| Error::ArithmeticOverflow)?,
        })
    }
}

impl NeuronFeatureBatchDriver for GatedHeadCpuDriverV2 {
    fn run_neuron_features_batch(
        &mut self,
        handle: &DriverModelHandle,
        requests: &[NeuronFeatureRequest],
    ) -> Result<Vec<DriverNeuronFeatureObservation>, Error> {
        self.verify_loaded(handle)?;
        self.batch_calls = self.batch_calls.checked_add(1).ok_or(Error::ArithmeticOverflow)?;
        let started = Instant::now();
        let mut observed = Vec::with_capacity(requests.len());
        // One bounded driver call; this reference CPU implementation uses
        // deterministic scalar head kernels and is NOT a GPU GEMM benchmark.
        for request in requests {
            let (drive, prediction) = self.compute(request)?;
            observed.push(DriverNeuronFeatureObservation {
                terminal_observed: true,
                succeeded: true,
                encoder_digest: request.encoder_digest.clone(),
                head_digest: request.head_digest.clone(),
                drive_q24: drive,
                prediction_q24: prediction,
                observed_memory_bytes: handle.observed_memory_bytes,
                transient_allocation_bytes: transient_bytes(request)?,
                queue_age_micros: 0,
                latency_micros: 0,
            });
        }
        let batch_micros = u64::try_from(started.elapsed().as_micros())
            .map_err(|_| Error::ArithmeticOverflow)?;
        for item in &mut observed {
            item.latency_micros = batch_micros;
        }
        Ok(observed)
    }
}

fn transient_bytes(request: &NeuronFeatureRequest) -> Result<u64, Error> {
    let count = request.feature_vector_q24.len()
        .checked_add(request.expected_output_width.checked_mul(2)
            .ok_or(Error::ArithmeticOverflow)?)
        .ok_or(Error::ArithmeticOverflow)?;
    let bytes = count.checked_mul(8).ok_or(Error::ArithmeticOverflow)?;
    u64::try_from(bytes).map_err(|_| Error::ArithmeticOverflow)
}

fn validate_candidate(candidate: &GatedHeadCandidateV2) -> Result<(), Error> {
    super::validate_identity(&candidate.cell_identity, "cell")?;
    super::validate_digest(&candidate.encoder_digest, "encoder")?;
    if candidate.input_width == 0
        || candidate.output_width == 0
        || candidate.input_width > MAX_DIM
        || candidate.output_width > MAX_DIM
        || candidate.gate_q24.len() != candidate.input_width
        || candidate.drive_weights_q24.len()
            != candidate.input_width.checked_mul(candidate.output_width)
                .ok_or(Error::ArithmeticOverflow)?
        || candidate.prediction_weights_q24.len() != candidate.drive_weights_q24.len()
        || candidate.drive_bias_q24.len() != candidate.output_width
        || candidate.prediction_bias_q24.len() != candidate.output_width
    {
        return Err(Error::FeatureLimit);
    }
    if parameter_count(candidate)? > MAX_HEAD_PARAMETERS {
        return Err(Error::FeatureLimit);
    }
    if [
        candidate.gate_q24.as_slice(),
        candidate.drive_weights_q24.as_slice(),
        candidate.prediction_weights_q24.as_slice(),
        candidate.drive_bias_q24.as_slice(),
        candidate.prediction_bias_q24.as_slice(),
    ]
    .iter()
    .flat_map(|group| group.iter())
    .any(|v| !(-Q24_BOUND..=Q24_BOUND).contains(v))
    {
        return Err(Error::FeatureLimit);
    }
    Ok(())
}

fn parameter_count(candidate: &GatedHeadCandidateV2) -> Result<usize, Error> {
    let dense = candidate.input_width
        .checked_mul(candidate.output_width)
        .and_then(|n| n.checked_mul(2))
        .ok_or(Error::ArithmeticOverflow)?;
    candidate.input_width.checked_add(dense)
        .and_then(|n| n.checked_add(candidate.output_width * 2))
        .ok_or(Error::ArithmeticOverflow)
}

fn candidate_digest(candidate: &GatedHeadCandidateV2) -> String {
    let mut bytes = b"hepta.infer.gated-cpu-head.v2".to_vec();
    bytes.extend_from_slice(&(candidate.cell_identity.len() as u32).to_be_bytes());
    bytes.extend_from_slice(candidate.cell_identity.as_bytes());
    bytes.extend_from_slice(candidate.encoder_digest.as_bytes());
    bytes.extend_from_slice(&(candidate.input_width as u64).to_be_bytes());
    bytes.extend_from_slice(&(candidate.output_width as u64).to_be_bytes());
    for block in [
        &candidate.gate_q24,
        &candidate.drive_weights_q24,
        &candidate.prediction_weights_q24,
        &candidate.drive_bias_q24,
        &candidate.prediction_bias_q24,
    ] {
        bytes.extend_from_slice(&(block.len() as u64).to_be_bytes());
        for value in block {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
    }
    Digest32::of_bytes(&bytes).to_string()
}

/// Exact signed round-to-nearest ties-to-even conversion from Q48 to Q24.
fn q24_round_checked(raw_q48: i128) -> Result<i64, Error> {
    let divisor = i128::from(Q24);
    let floor = raw_q48.div_euclid(divisor);
    let remainder = raw_q48.rem_euclid(divisor);
    let twice = remainder * 2;
    let rounded = floor
        + i128::from(twice > divisor || (twice == divisor && floor % 2 != 0));
    if !(-i128::from(Q24_BOUND)..=i128::from(Q24_BOUND)).contains(&rounded) {
        return Err(Error::FeatureOutputMismatch);
    }
    i64::try_from(rounded).map_err(|_| Error::ArithmeticOverflow)
}

fn dense_q24(input: &[i64], weights: &[i64], bias: &[i64]) -> Result<Vec<i64>, Error> {
    let mut result = Vec::with_capacity(bias.len());
    for (row, intercept) in weights.chunks_exact(input.len()).zip(bias.iter()) {
        let mut sum = i128::from(*intercept) * i128::from(Q24);
        for (weight, feature) in row.iter().zip(input) {
            sum = sum
                .checked_add(i128::from(*weight) * i128::from(*feature))
                .ok_or(Error::ArithmeticOverflow)?;
        }
        result.push(q24_round_checked(sum)?);
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    use super::super::{
        InferenceWorker, ResourceGrant, WorkerRequest, canonical_neuron_feature_payload_digest,
    };

    fn manifest() -> ModelManifest {
        ModelManifest {
            model_id: "model.gated".into(),
            model_digest: "2".repeat(64),
            weights_digest: "3".repeat(64),
            tokenizer_digest: "4".repeat(64),
            preprocessor_digest: "5".repeat(64),
            quantization_digest: "6".repeat(64),
            runtime_digest: "7".repeat(64),
            device_digest: "8".repeat(64),
            maximum_tokens: 128,
        }
    }

    fn head(cell: &str) -> GatedHeadCandidateV2 {
        GatedHeadCandidateV2 {
            cell_identity: cell.to_string(),
            encoder_digest: "a".repeat(64),
            input_width: 2,
            output_width: 1,
            gate_q24: vec![Q24, Q24],
            drive_weights_q24: vec![Q24, 0],
            prediction_weights_q24: vec![0, Q24],
            drive_bias_q24: vec![0],
            prediction_bias_q24: vec![0],
        }
    }

    fn feature(id: &str, head_digest: String) -> NeuronFeatureRequest {
        let mut request = NeuronFeatureRequest {
            authorization: WorkerRequest {
                request_id: id.into(),
                reservation_id: format!("reservation.{id}"),
                model_digest: "2".repeat(64),
                payload_digest: "0".repeat(64),
                maximum_tokens: 64,
                deadline_ms: 9000,
                lease_payload_digest: "0".repeat(64),
                reservation_model_digest: "2".repeat(64),
                reservation_maximum_tokens: 64,
                cancelled: false,
            },
            encoder_digest: "a".repeat(64),
            head_digest,
            weights_digest: "3".repeat(64),
            input_digest: "c".repeat(64),
            feature_vector_q24: vec![Q24 / 2, -Q24 / 4],
            expected_output_width: 1,
        };
        let payload = canonical_neuron_feature_payload_digest(&request);
        request.authorization.payload_digest = payload.clone();
        request.authorization.lease_payload_digest = payload;
        request
    }

    #[test]
    fn q24_rounding_is_ties_to_even_in_both_directions() {
        assert_eq!(q24_round_checked(i128::from(Q24) / 2).expect("round"), 0);
        assert_eq!(q24_round_checked(i128::from(Q24) * 3 / 2).expect("round"), 2);
        assert_eq!(q24_round_checked(-i128::from(Q24) / 2).expect("round"), 0);
        assert_eq!(q24_round_checked(-i128::from(Q24) * 3 / 2).expect("round"), -2);
    }

    #[test]
    fn actual_gated_cpu_batch_runs_independent_heads_and_does_not_fabricate_logits() {
        let mut driver = GatedHeadCpuDriverV2::new(manifest()).expect("driver");
        let ha = driver.register_head(head("cell.a")).expect("head a");
        let mut hb = head("cell.b");
        hb.gate_q24 = vec![Q24 * 2, Q24];
        let hb = driver.register_head(hb).expect("head b");
        assert_ne!(ha, hb);
        assert_eq!(driver.parameter_bytes(), 12 * 8);
        let grant = ResourceGrant {
            grant_id: "grant.1".into(),
            authority_epoch: 2,
            generation: 3,
            expires_at_ms: 10_000,
            revoked: false,
            maximum_models: 1,
            maximum_active_requests: 3,
            maximum_memory_bytes: 1024,
            semantic_digest: "1".repeat(64),
        };
        let mut worker = InferenceWorker::new(1, "worker.heads".into(), 3, grant, driver)
            .expect("worker");
        worker.load_model(1, manifest()).expect("load");
        let rows = worker.run_neuron_features_batch(100, "model.gated", vec![
            feature("req.a", ha),
            feature("req.b", hb),
        ]).expect("run actual cpu head");
        assert_eq!(rows.len(), 2);
        assert_eq!(rows[0].drive_q24, vec![Q24 / 2]);
        assert_eq!(rows[0].prediction_q24, vec![-Q24 / 4]);
        assert_eq!(rows[1].drive_q24, vec![Q24]);
        assert_eq!(rows[1].prediction_q24, vec![-Q24 / 4]);
        assert_eq!(worker.driver.batch_calls(), 1);
    }

    #[test]
    fn rejects_excess_capacity_and_stale_head_before_returning_output() {
        let mut driver = GatedHeadCpuDriverV2::new(manifest()).expect("driver");
        let mut invalid = head("cell.invalid");
        invalid.gate_q24.push(Q24);
        assert_eq!(driver.register_head(invalid), Err(Error::FeatureLimit));
        let digest = driver.register_head(head("cell.a")).expect("head");
        let mut unauthorized = feature("r", "f".repeat(64));
        let handle = driver.load(&manifest()).expect("load");
        assert_eq!(driver.run_neuron_features(&handle, &unauthorized), Err(Error::ModelNotLoaded));
        unauthorized.head_digest = digest;
        assert!(driver.run_neuron_features(&handle, &unauthorized).is_ok());
    }

    #[test]
    fn immutable_digest_changes_with_cell_identity_or_learning_proposal() {
        let a = head("cell.a");
        let b = head("cell.b");
        assert_ne!(candidate_digest(&a), candidate_digest(&b));
        let mut revised = a.clone();
        revised.gate_q24[0] += 1;
        assert_ne!(candidate_digest(&a), candidate_digest(&revised));
    }
}
