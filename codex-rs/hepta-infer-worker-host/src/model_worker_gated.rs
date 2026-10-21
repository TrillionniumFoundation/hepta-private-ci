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
use super::NeuronFeatureBatchItemObservationV2;
use super::NeuronFeatureDriver;
use super::NeuronFeatureRequest;
use super::NeuronSharedFeatureBatchDriverV2;
use super::SharedNeuronFeatureRequestV2;
use super::WorkerRequest;
use super::validate_manifest;

const Q24: i64 = 1 << 24;
const Q24_BOUND: i64 = 8 * Q24;
const MAX_DIM: usize = 512;
const MAX_HEAD_PARAMETERS: usize = 262_144;
const MAX_REGISTERED_HEADS: usize = 4_096;
const MAX_TENSOR_BYTES: usize = 512 * 1024 * 1024;

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
/// Its module and re-export remain crate-private; exposing this reference
/// backend as a public execution port would bypass signed Final-use review.
///
/// The `observed_memory_bytes` field in this reference adapter counts owned
/// parameter tensors rather than full OS RSS, so it is not a production
/// resource receipt.
#[derive(Debug)]
pub struct GatedHeadCpuDriverV2 {
    selected_manifest: ModelManifest,
    heads: BTreeMap<String, GatedHeadArtifactV2>,
    loaded: bool,
    sealed: bool,
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
            sealed: false,
            tensor_bytes: 0,
            batch_calls: 0,
        })
    }

    /// Register only before the manifest is loaded into the worker. A new
    /// candidate creates a new digest rather than mutating selected weights.
    pub fn register_head(&mut self, candidate: GatedHeadCandidateV2) -> Result<String, Error> {
        if self.sealed {
            return Err(Error::ActiveRequests);
        }
        if self.heads.len() >= MAX_REGISTERED_HEADS {
            return Err(Error::ModelCapacity);
        }
        validate_candidate(&candidate)?;
        if self
            .heads
            .values()
            .any(|head| head.candidate.cell_identity == candidate.cell_identity)
        {
            // Multiple active revisions for one Cell need separate generations.
            return Err(Error::ModelAlreadyLoaded);
        }
        let parameter_count = parameter_count(&candidate)?;
        let bytes = parameter_count
            .checked_mul(std::mem::size_of::<i64>())
            .ok_or(Error::ArithmeticOverflow)?;
        let next_bytes = self
            .tensor_bytes
            .checked_add(bytes)
            .ok_or(Error::ArithmeticOverflow)?;
        if next_bytes > MAX_TENSOR_BYTES {
            return Err(Error::ModelCapacity);
        }
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

    /// Calculate an exact bundle identity from the admitted immutable tensors,
    /// without trusting a manifest-supplied, unverified string.
    pub fn catalog_digest_for(candidates: &[GatedHeadCandidateV2]) -> Result<String, Error> {
        if candidates.is_empty() || candidates.len() > MAX_REGISTERED_HEADS {
            return Err(Error::ModelCapacity);
        }
        let mut digests = Vec::with_capacity(candidates.len());
        for candidate in candidates {
            validate_candidate(candidate)?;
            digests.push(candidate_digest(candidate));
        }
        digests.sort();
        if digests.windows(2).any(|pair| pair[0] == pair[1]) {
            return Err(Error::ModelAlreadyLoaded);
        }
        let mut cells = std::collections::BTreeSet::new();
        if candidates
            .iter()
            .any(|head| !cells.insert(head.cell_identity.as_str()))
        {
            return Err(Error::ModelAlreadyLoaded);
        }
        Ok(catalog_digest_sorted(&digests))
    }

    pub fn batch_calls(&self) -> usize {
        self.batch_calls
    }

    fn verify_loaded(&self, handle: &DriverModelHandle) -> Result<(), Error> {
        if !self.loaded
            || handle.opaque_id != format!("gated.cpu:{}", self.selected_manifest.model_id)
        {
            return Err(Error::ModelNotLoaded);
        }
        Ok(())
    }

    fn compute(&self, request: &NeuronFeatureRequest) -> Result<(Vec<i64>, Vec<i64>), Error> {
        self.compute_parts(
            &request.head_digest,
            &request.encoder_digest,
            &request.feature_vector_q24,
            request.expected_output_width,
            None,
        )
    }

    fn compute_parts(
        &self,
        head_digest: &str,
        encoder_digest: &str,
        features_q24: &[i64],
        output_width: usize,
        cell_id: Option<&str>,
    ) -> Result<(Vec<i64>, Vec<i64>), Error> {
        let head = self.heads.get(head_digest).ok_or(Error::ModelNotLoaded)?;
        let candidate = &head.candidate;
        if head.head_digest != head_digest
            || candidate.encoder_digest != encoder_digest
            || output_width != candidate.output_width
            || features_q24.len() != candidate.input_width
            || cell_id.is_some_and(|id| id != candidate.cell_identity.as_str())
        {
            return Err(Error::FeatureOutputMismatch);
        }
        let gated: Vec<i64> = features_q24
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
        let selected_catalog =
            catalog_digest_sorted(&self.heads.keys().cloned().collect::<Vec<_>>());
        if *manifest != self.selected_manifest
            || self.loaded
            || self.heads.is_empty()
            || selected_catalog != manifest.weights_digest
        {
            return Err(Error::ModelMismatch);
        }
        self.sealed = true;
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
    ) -> Result<Vec<NeuronFeatureBatchItemObservationV2>, Error> {
        self.verify_loaded(handle)?;
        // The low-level driver is still bounded even when called without the
        // Worker admission wrapper. Count only fully completed batches.
        if requests.is_empty() || requests.len() > 32 {
            return Err(Error::RequestCapacity);
        }
        let next_batch_calls = self
            .batch_calls
            .checked_add(1)
            .ok_or(Error::ArithmeticOverflow)?;
        let started = Instant::now();
        let mut observed = Vec::with_capacity(requests.len());
        // One bounded driver call; this reference CPU implementation uses
        // deterministic scalar head kernels and is NOT a GPU GEMM benchmark.
        for request in requests {
            let (drive, prediction) = self.compute(request)?;
            observed.push(NeuronFeatureBatchItemObservationV2 {
                request_id: request.authorization.request_id.clone(),
                payload_digest: request.authorization.payload_digest.clone(),
                feature: DriverNeuronFeatureObservation {
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
                },
            });
        }
        let batch_micros =
            u64::try_from(started.elapsed().as_micros()).map_err(|_| Error::ArithmeticOverflow)?;
        for item in &mut observed {
            item.feature.latency_micros = batch_micros;
        }
        self.batch_calls = next_batch_calls;
        Ok(observed)
    }
}

impl NeuronSharedFeatureBatchDriverV2 for GatedHeadCpuDriverV2 {
    fn run_shared_neuron_features_batch_v2(
        &mut self,
        handle: &DriverModelHandle,
        requests: &[SharedNeuronFeatureRequestV2],
    ) -> Result<Vec<NeuronFeatureBatchItemObservationV2>, Error> {
        self.verify_loaded(handle)?;
        // The low-level driver is still bounded even when called without the
        // Worker admission wrapper. Count only fully completed batches.
        if requests.is_empty() || requests.len() > 32 {
            return Err(Error::RequestCapacity);
        }
        let next_batch_calls = self
            .batch_calls
            .checked_add(1)
            .ok_or(Error::ArithmeticOverflow)?;
        let started = Instant::now();
        let mut observations = Vec::with_capacity(requests.len());
        // No feature Vec is created here; each Cell borrows the shared Arc's
        // immutable Q24 slice. This is scalar CPU math, NOT fused GPU GEMM.
        for request in requests {
            let (drive, prediction) = self.compute_parts(
                &request.head_digest,
                &request.snapshot.identity.encoder_digest.to_string(),
                &request.snapshot.features_q24,
                request.expected_output_width,
                Some(request.cell_id.as_str()),
            )?;
            observations.push(NeuronFeatureBatchItemObservationV2 {
                request_id: request.authorization.request_id.clone(),
                payload_digest: request.authorization.payload_digest.clone(),
                feature: DriverNeuronFeatureObservation {
                    terminal_observed: true,
                    succeeded: true,
                    encoder_digest: request.snapshot.identity.encoder_digest.to_string(),
                    head_digest: request.head_digest.clone(),
                    drive_q24: drive,
                    prediction_q24: prediction,
                    observed_memory_bytes: handle.observed_memory_bytes,
                    transient_allocation_bytes: transient_dimensions_bytes(
                        request.snapshot.features_q24.len(),
                        request.expected_output_width,
                    )?,
                    queue_age_micros: 0,
                    latency_micros: 0,
                },
            });
        }
        let elapsed =
            u64::try_from(started.elapsed().as_micros()).map_err(|_| Error::ArithmeticOverflow)?;
        for item in &mut observations {
            item.feature.latency_micros = elapsed;
        }
        self.batch_calls = next_batch_calls;
        Ok(observations)
    }
}

fn transient_bytes(request: &NeuronFeatureRequest) -> Result<u64, Error> {
    transient_dimensions_bytes(
        request.feature_vector_q24.len(),
        request.expected_output_width,
    )
}

fn transient_dimensions_bytes(input_width: usize, output_width: usize) -> Result<u64, Error> {
    let count = input_width
        .checked_add(
            output_width
                .checked_mul(2)
                .ok_or(Error::ArithmeticOverflow)?,
        )
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
            != candidate
                .input_width
                .checked_mul(candidate.output_width)
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
    let dense = candidate
        .input_width
        .checked_mul(candidate.output_width)
        .and_then(|n| n.checked_mul(2))
        .ok_or(Error::ArithmeticOverflow)?;
    candidate
        .input_width
        .checked_add(dense)
        .and_then(|n| n.checked_add(candidate.output_width * 2))
        .ok_or(Error::ArithmeticOverflow)
}

fn catalog_digest_sorted(digests: &[String]) -> String {
    let mut bytes = b"hepta.infer.gated-cpu-catalog.v2".to_vec();
    bytes.extend_from_slice(&(digests.len() as u64).to_be_bytes());
    for digest in digests {
        bytes.extend_from_slice(digest.as_bytes());
    }
    Digest32::of_bytes(&bytes).to_string()
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
    let rounded = floor + i128::from(twice > divisor || (twice == divisor && floor % 2 != 0));
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
    use super::super::InferenceWorker;
    use super::super::ResourceGrant;
    use super::super::WorkerRequest;
    use super::super::canonical_neuron_feature_payload_digest;
    use super::*;

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

    fn manifest_for(candidates: &[GatedHeadCandidateV2]) -> ModelManifest {
        let mut selected = manifest();
        selected.weights_digest =
            GatedHeadCpuDriverV2::catalog_digest_for(candidates).expect("catalog digest");
        selected
    }

    fn feature(id: &str, head_digest: String, weights_digest: String) -> NeuronFeatureRequest {
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
            weights_digest,
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
        assert_eq!(
            q24_round_checked(i128::from(Q24) * 3 / 2).expect("round"),
            2
        );
        assert_eq!(q24_round_checked(-i128::from(Q24) / 2).expect("round"), 0);
        assert_eq!(
            q24_round_checked(-i128::from(Q24) * 3 / 2).expect("round"),
            -2
        );
    }

    #[test]
    fn actual_gated_cpu_batch_runs_independent_heads_and_does_not_fabricate_logits() {
        let ha_candidate = head("cell.a");
        let mut hb_candidate = head("cell.b");
        hb_candidate.gate_q24 = vec![Q24 * 2, Q24];
        let selected = manifest_for(&[ha_candidate.clone(), hb_candidate.clone()]);
        let mut driver = GatedHeadCpuDriverV2::new(selected.clone()).expect("driver");
        let ha = driver.register_head(ha_candidate).expect("head a");
        let hb = driver.register_head(hb_candidate).expect("head b");
        assert_ne!(ha, hb);
        assert_eq!(driver.parameter_bytes(), 16 * 8);
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
        let mut worker =
            InferenceWorker::new(1, "worker.heads".into(), 3, grant, driver).expect("worker");
        worker.load_model(1, selected.clone()).expect("load");
        let rows = worker
            .run_neuron_features_batch(
                100,
                "model.gated",
                vec![
                    feature("req.a", ha, selected.weights_digest.clone()),
                    feature("req.b", hb, selected.weights_digest.clone()),
                ],
            )
            .expect("run actual cpu head");
        assert_eq!(rows.len(), 2);
        assert_eq!(rows[0].drive_q24, vec![Q24 / 2]);
        assert_eq!(rows[0].prediction_q24, vec![-Q24 / 4]);
        assert_eq!(rows[1].drive_q24, vec![Q24]);
        assert_eq!(rows[1].prediction_q24, vec![-Q24 / 4]);
        assert_eq!(worker.driver.batch_calls(), 1);
    }

    #[test]
    fn failed_or_empty_legacy_batch_never_counts_as_completed_physical_work() {
        let selected = manifest_for(&[head("cell.a")]);
        let mut driver = GatedHeadCpuDriverV2::new(selected.clone()).expect("driver");
        let selected_head = driver.register_head(head("cell.a")).expect("head");
        let handle = driver.load(&selected).expect("model");
        let valid = feature("request.ok", selected_head, selected.weights_digest.clone());
        let mut late_invalid = valid.clone();
        late_invalid.authorization.request_id = "request.late-invalid".to_string();
        late_invalid.head_digest = "f".repeat(64);
        assert!(matches!(
            driver.run_neuron_features_batch(&handle, &[]),
            Err(Error::RequestCapacity)
        ));
        assert!(matches!(
            driver.run_neuron_features_batch(&handle, &vec![valid.clone(); 33]),
            Err(Error::RequestCapacity)
        ));
        // First Cell computes successfully, second Cell fails. This is not a
        // completed physical batch and must not inflate performance evidence.
        assert!(matches!(
            driver.run_neuron_features_batch(&handle, &[valid.clone(), late_invalid]),
            Err(Error::ModelNotLoaded)
        ));
        assert_eq!(driver.batch_calls(), 0);
        assert_eq!(
            driver
                .run_neuron_features_batch(&handle, &[valid])
                .expect("valid bounded physical batch")
                .len(),
            1
        );
        assert_eq!(driver.batch_calls(), 1);
    }

    #[test]
    fn failed_shared_arc_batch_does_not_increment_successful_physical_count() {
        use codex_hepta_infer_core::shared_feature_v2::SharedFeatureCacheV2;
        use codex_hepta_infer_core::shared_feature_v2::SharedFeatureIdentityV2;
        use codex_hepta_types::Generation;
        use codex_hepta_types::StableId;
        use std::sync::Arc;

        let id = |x: &str| StableId::new(x.to_string()).expect("identity");
        let encoder = Digest32::of_bytes(b"frozen encoder");
        let mut candidate = head("cell.a");
        candidate.encoder_digest = encoder.to_string();
        let selected = manifest_for(&[candidate.clone()]);
        let mut driver = GatedHeadCpuDriverV2::new(selected.clone()).expect("driver");
        let digest = driver.register_head(candidate).expect("head");
        let handle = driver.load(&selected).expect("loaded");
        let identity = SharedFeatureIdentityV2 {
            principal_id: id("principal.a"),
            purpose_id: id("purpose.decision"),
            generation: Generation::new(1).expect("generation"),
            authority_epoch: 1,
            encoder_digest: encoder,
            tokenizer_digest: Digest32::of_bytes(b"tokenizer"),
            normalizer_digest: Digest32::of_bytes(b"normalizer"),
            quantization_digest: Digest32::of_bytes(b"quantizer"),
            input_digest: Digest32::of_bytes(b"state plus ordered options"),
        };
        let mut cache = SharedFeatureCacheV2::new(2, 256).expect("cache");
        let snapshot = cache
            .insert(1, identity, 1000, Arc::from([Q24 / 2, Q24 / 4]))
            .expect("feature");
        let valid = SharedNeuronFeatureRequestV2 {
            authorization: WorkerRequest {
                request_id: "request.a".into(),
                reservation_id: "reservation.a".into(),
                model_digest: selected.model_digest.clone(),
                payload_digest: "1".repeat(64),
                maximum_tokens: 16,
                deadline_ms: 500,
                lease_payload_digest: "1".repeat(64),
                reservation_model_digest: selected.model_digest.clone(),
                reservation_maximum_tokens: 16,
                cancelled: false,
            },
            principal_id: id("principal.a"),
            purpose_id: id("purpose.decision"),
            cell_id: id("cell.a"),
            snapshot,
            head_digest: digest,
            weights_digest: selected.weights_digest.clone(),
            expected_output_width: 1,
        };
        let mut late_invalid = valid.clone();
        late_invalid.cell_id = id("cell.b");
        assert!(matches!(
            driver.run_shared_neuron_features_batch_v2(&handle, &[]),
            Err(Error::RequestCapacity)
        ));
        assert!(matches!(
            driver.run_shared_neuron_features_batch_v2(&handle, &vec![valid.clone(); 33]),
            Err(Error::RequestCapacity)
        ));
        assert!(matches!(
            driver.run_shared_neuron_features_batch_v2(&handle, &[valid.clone(), late_invalid]),
            Err(Error::FeatureOutputMismatch)
        ));
        assert_eq!(driver.batch_calls(), 0);
        assert_eq!(
            driver
                .run_shared_neuron_features_batch_v2(&handle, &[valid])
                .expect("complete physical reference batch")
                .len(),
            1
        );
        assert_eq!(driver.batch_calls(), 1);
    }

    #[test]
    fn rejects_excess_capacity_and_stale_head_before_returning_output() {
        let selected = manifest_for(&[head("cell.a")]);
        let mut driver = GatedHeadCpuDriverV2::new(selected.clone()).expect("driver");
        let mut invalid = head("cell.invalid");
        invalid.gate_q24.push(Q24);
        assert_eq!(driver.register_head(invalid), Err(Error::FeatureLimit));
        let digest = driver.register_head(head("cell.a")).expect("head");
        let mut unauthorized = feature("r", "f".repeat(64), selected.weights_digest.clone());
        let handle = driver.load(&selected).expect("load");
        assert_eq!(
            driver.run_neuron_features(&handle, &unauthorized),
            Err(Error::ModelNotLoaded)
        );
        unauthorized.head_digest = digest;
        assert!(driver.run_neuron_features(&handle, &unauthorized).is_ok());
        assert_eq!(
            driver.register_head(head("cell.new")),
            Err(Error::ActiveRequests)
        );
    }

    #[test]
    fn a_manifest_without_the_actual_head_catalog_is_not_loadable() {
        let wrong = manifest();
        let mut driver = GatedHeadCpuDriverV2::new(wrong.clone()).expect("driver");
        driver.register_head(head("cell.a")).expect("register");
        assert_eq!(driver.load(&wrong), Err(Error::ModelMismatch));
    }

    #[test]
    fn shared_feature_arc_executes_two_distinct_cells_without_vec_materialization() {
        use codex_hepta_infer_core::shared_feature_v2::SharedFeatureCacheV2;
        use codex_hepta_infer_core::shared_feature_v2::SharedFeatureIdentityV2;
        use codex_hepta_types::Generation;
        use codex_hepta_types::StableId;

        let id = |value: &str| StableId::new(value.to_string()).expect("stable id");
        let mut first = head("cell.a");
        let encoder = Digest32::of_bytes(b"encoder");
        first.encoder_digest = encoder.to_string();
        let mut second = head("cell.b");
        second.encoder_digest = encoder.to_string();
        second.gate_q24[0] = 2 * Q24;
        let mut selected = manifest_for(&[first.clone(), second.clone()]);
        selected.tokenizer_digest = Digest32::of_bytes(b"tokenizer").to_string();
        selected.preprocessor_digest = Digest32::of_bytes(b"normalizer").to_string();
        selected.quantization_digest = Digest32::of_bytes(b"quantization").to_string();

        let mut driver = GatedHeadCpuDriverV2::new(selected.clone()).expect("driver");
        let h_first = driver.register_head(first.clone()).expect("head a");
        let h_second = driver.register_head(second.clone()).expect("head b");
        let mut cache = SharedFeatureCacheV2::new(2, 512).expect("cache");
        let identity = SharedFeatureIdentityV2 {
            principal_id: id("principal.a"),
            purpose_id: id("purpose.prediction"),
            generation: Generation::new(3).expect("generation"),
            authority_epoch: 2,
            encoder_digest: encoder,
            tokenizer_digest: Digest32::of_bytes(b"tokenizer"),
            normalizer_digest: Digest32::of_bytes(b"normalizer"),
            quantization_digest: Digest32::of_bytes(b"quantization"),
            input_digest: Digest32::of_bytes(b"complete question and choices"),
        };
        let snapshot = cache
            .insert(1, identity, 1000, std::sync::Arc::from([Q24 / 2, -Q24 / 4]))
            .expect("snapshot");

        let mk = |cell: &str, token: &str, head_digest: String| {
            let mut request = SharedNeuronFeatureRequestV2 {
                authorization: WorkerRequest {
                    request_id: token.to_string(),
                    reservation_id: format!("reservation.{token}"),
                    model_digest: selected.model_digest.clone(),
                    payload_digest: "1".repeat(64),
                    maximum_tokens: 32,
                    deadline_ms: 900,
                    lease_payload_digest: "1".repeat(64),
                    reservation_model_digest: selected.model_digest.clone(),
                    reservation_maximum_tokens: 32,
                    cancelled: false,
                },
                principal_id: id("principal.a"),
                purpose_id: id("purpose.prediction"),
                cell_id: id(cell),
                snapshot: std::sync::Arc::clone(&snapshot),
                head_digest,
                weights_digest: selected.weights_digest.clone(),
                expected_output_width: 1,
            };
            let digest =
                super::super::canonical_shared_neuron_payload_digest_v2(&request).expect("payload");
            request.authorization.payload_digest = digest.clone();
            request.authorization.lease_payload_digest = digest;
            request
        };
        let a = mk("cell.a", "request.a", h_first.clone());
        let b = mk("cell.b", "request.b", h_second.clone());
        assert!(std::sync::Arc::ptr_eq(&a.snapshot, &b.snapshot));

        // Both reservations are individually valid but the two Cells'
        // minimum output Vec allocations would exceed this grant. The Worker
        // must reject the *whole* cohort before dispatching any CPU work.
        let mut bounded_driver = GatedHeadCpuDriverV2::new(selected.clone()).expect("bounded");
        bounded_driver
            .register_head(first.clone())
            .expect("bounded head a");
        bounded_driver
            .register_head(second.clone())
            .expect("bounded head b");
        let resident = u64::try_from(bounded_driver.parameter_bytes()).expect("resident");
        let bounded_grant = ResourceGrant {
            grant_id: "grant.bounded".into(),
            authority_epoch: 2,
            generation: 3,
            expires_at_ms: 2000,
            revoked: false,
            maximum_models: 1,
            maximum_active_requests: 4,
            maximum_memory_bytes: resident + 16,
            semantic_digest: "1".repeat(64),
        };
        let mut bounded_worker =
            InferenceWorker::new(1, "worker.bounded".into(), 3, bounded_grant, bounded_driver)
                .expect("bounded worker");
        bounded_worker
            .load_model(1, selected.clone())
            .expect("bounded model load");
        assert_eq!(
            bounded_worker.run_shared_neuron_features_batch_v2(
                100,
                "model.gated",
                vec![a.clone(), b.clone()],
            ),
            Err(Error::ModelCapacity)
        );
        assert_eq!(bounded_worker.driver.batch_calls(), 0);

        // The same two Cells can reuse one immutable Arc under a tight grant.
        // Two equal-content but physically distinct Arc allocations cannot
        // exploit that grant to bypass memory admission before driver entry.
        let mut memory_driver = GatedHeadCpuDriverV2::new(selected.clone()).expect("memory driver");
        memory_driver
            .register_head(first.clone())
            .expect("memory head a");
        memory_driver
            .register_head(second.clone())
            .expect("memory head b");
        let memory_grant = ResourceGrant {
            grant_id: "grant.shared-memory".into(),
            authority_epoch: 2,
            generation: 3,
            expires_at_ms: 2000,
            revoked: false,
            maximum_models: 1,
            maximum_active_requests: 4,
            // Head tensors + two independent outputs + one shared 16-byte Arc.
            maximum_memory_bytes: resident + 48,
            semantic_digest: "1".repeat(64),
        };
        let mut memory_worker = InferenceWorker::new(
            1,
            "worker.shared-memory".into(),
            3,
            memory_grant,
            memory_driver,
        )
        .expect("memory worker");
        memory_worker
            .load_model(1, selected.clone())
            .expect("memory model load");
        let mut duplicated = b.clone();
        let mut duplicate_snapshot = (*duplicated.snapshot).clone();
        duplicate_snapshot.features_q24 =
            std::sync::Arc::from(duplicated.snapshot.features_q24.as_ref());
        duplicated.snapshot = std::sync::Arc::new(duplicate_snapshot);
        assert!(!std::sync::Arc::ptr_eq(
            &a.snapshot.features_q24,
            &duplicated.snapshot.features_q24
        ));
        assert_eq!(
            memory_worker.run_shared_neuron_features_batch_v2(
                100,
                "model.gated",
                vec![a.clone(), duplicated],
            ),
            Err(Error::ModelCapacity)
        );
        assert_eq!(memory_worker.driver.batch_calls(), 0);
        assert_eq!(
            memory_worker
                .run_shared_neuron_features_batch_v2(
                    100,
                    "model.gated",
                    vec![a.clone(), b.clone()],
                )
                .expect("shared Arc within budget")
                .len(),
            2
        );
        assert_eq!(memory_worker.driver.batch_calls(), 1);

        let grant = ResourceGrant {
            grant_id: "grant.ref".into(),
            authority_epoch: 2,
            generation: 3,
            expires_at_ms: 2000,
            revoked: false,
            maximum_models: 1,
            maximum_active_requests: 4,
            maximum_memory_bytes: 4096,
            semantic_digest: "1".repeat(64),
        };
        let mut worker =
            InferenceWorker::new(1, "worker.reference".into(), 3, grant, driver).expect("worker");
        worker.load_model(1, selected).expect("load");
        let mut aliased = b.clone();
        aliased.authorization.reservation_id = a.authorization.reservation_id.clone();
        let alias_digest = super::super::canonical_shared_neuron_payload_digest_v2(&aliased)
            .expect("alias digest");
        aliased.authorization.payload_digest = alias_digest.clone();
        aliased.authorization.lease_payload_digest = alias_digest;
        assert!(matches!(
            worker.run_shared_neuron_features_batch_v2(
                100,
                "model.gated",
                vec![a.clone(), aliased],
            ),
            Err(Error::FeatureContract)
        ));
        assert_eq!(worker.driver.batch_calls(), 0);
        // A well-formed row from another principal or purpose must not
        // enter the same *physical* backend invocation. Recompute its payload
        // and lease digests so the denial cannot be attributed to stale bytes.
        for change_principal in [true, false] {
            let mut mixed = b.clone();
            let mut isolated_snapshot = (*mixed.snapshot).clone();
            if change_principal {
                mixed.principal_id = id("principal.other");
                isolated_snapshot.identity.principal_id = mixed.principal_id.clone();
            } else {
                mixed.purpose_id = id("purpose.other");
                isolated_snapshot.identity.purpose_id = mixed.purpose_id.clone();
            }
            mixed.snapshot = std::sync::Arc::new(isolated_snapshot);
            let mixed_digest = super::super::canonical_shared_neuron_payload_digest_v2(&mixed)
                .expect("fresh mixed-partition payload");
            mixed.authorization.payload_digest = mixed_digest.clone();
            mixed.authorization.lease_payload_digest = mixed_digest;
            assert_eq!(
                worker.run_shared_neuron_features_batch_v2(
                    100,
                    "model.gated",
                    vec![a.clone(), mixed],
                ),
                Err(Error::FeatureContract)
            );
            assert_eq!(worker.driver.batch_calls(), 0);
        }
        // Even when the per-request lease payload is recomputed to match
        // forged metadata, real Q24 bytes must be hashed before dispatch.
        let mut forged = b.clone();
        let mut forged_snapshot = (*forged.snapshot).clone();
        forged_snapshot.content_digest = Digest32::of_bytes(b"forged-feature-content");
        forged.snapshot = std::sync::Arc::new(forged_snapshot);
        let forged_payload = super::super::canonical_shared_neuron_payload_digest_v2(&forged)
            .expect("forged payload binding");
        forged.authorization.payload_digest = forged_payload.clone();
        forged.authorization.lease_payload_digest = forged_payload;
        assert_eq!(
            worker
                .run_shared_neuron_features_batch_v2(100, "model.gated", vec![a.clone(), forged],),
            Err(Error::FeatureContract)
        );
        assert_eq!(worker.driver.batch_calls(), 0);
        assert!(worker.active_requests.is_empty());

        let results = worker
            .run_shared_neuron_features_batch_v2(100, "model.gated", vec![a.clone(), b.clone()])
            .expect("batched references");
        assert_eq!(results.len(), 2);
        assert_eq!(results[0].drive_q24, vec![Q24 / 2]);
        assert_eq!(results[1].drive_q24, vec![Q24]);
        assert_eq!(results[0].prediction_q24, vec![-Q24 / 4]);
        assert_eq!(results[1].prediction_q24, vec![-Q24 / 4]);
        assert_ne!(results[0].observation_digest, results[1].observation_digest);
        assert!(!results[0].authority.grants_any());
        assert_eq!(worker.driver.batch_calls(), 1);
        assert_eq!(cache.resident_bytes(), 16);

        // The second Cell's Head belongs to cell.b; swapping in cell.a's
        // digest with a freshly recomputed lease reaches the real driver,
        // which detects the mismatch after entry. The worker must not treat
        // this ambiguous execution as a safe request-local rejection.
        let mut wrong_head = b;
        wrong_head.head_digest = a.head_digest.clone();
        let payload = super::super::canonical_shared_neuron_payload_digest_v2(&wrong_head)
            .expect("rebind wrong head");
        wrong_head.authorization.payload_digest = payload.clone();
        wrong_head.authorization.lease_payload_digest = payload;
        assert_eq!(
            worker.run_shared_neuron_features_batch_v2(
                100,
                "model.gated",
                vec![a.clone(), wrong_head],
            ),
            Err(Error::FeatureOutputMismatch)
        );
        // The CPU reference driver counts only completed batches. The
        // rejected mixed-head cohort entered the driver but did not complete,
        // so it cannot increment successful batch accounting.
        assert_eq!(worker.driver.batch_calls(), 1);
        assert!(worker.poisoned);
        assert!(worker.active_requests.is_empty());
        assert_eq!(
            worker.run_shared_neuron_features_batch_v2(100, "model.gated", vec![a]),
            Err(Error::IndeterminateLifecycle)
        );
        // A poisoned worker never starts another physical batch.
        assert_eq!(worker.driver.batch_calls(), 1);
    }

    #[test]
    fn wrong_cell_head_pair_never_falls_through_to_another_cells_tensor() {
        let a = head("cell.a");
        let b = head("cell.b");
        let selected = manifest_for(&[a.clone(), b.clone()]);
        let mut driver = GatedHeadCpuDriverV2::new(selected.clone()).expect("driver");
        let ha = driver.register_head(a).expect("a");
        driver.register_head(b).expect("b");
        let handle = driver.load(&selected).expect("load");
        let mismatch = driver.compute_parts(
            &ha,
            "a".repeat(64).as_str(),
            &[Q24 / 2, Q24 / 4],
            1,
            Some("cell.b"),
        );
        assert_eq!(mismatch, Err(Error::FeatureOutputMismatch));
        assert!(driver.verify_loaded(&handle).is_ok());
    }

    #[test]
    fn forbids_two_selected_head_revisions_for_one_cell() {
        let first = head("cell.a");
        let mut second = first.clone();
        second.gate_q24[0] += 1;
        assert_eq!(
            GatedHeadCpuDriverV2::catalog_digest_for(&[first.clone(), second.clone()]),
            Err(Error::ModelAlreadyLoaded)
        );
        let selected = manifest_for(&[first.clone()]);
        let mut driver = GatedHeadCpuDriverV2::new(selected).expect("driver");
        driver.register_head(first).expect("first");
        assert_eq!(driver.register_head(second), Err(Error::ModelAlreadyLoaded));
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
