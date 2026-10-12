//! Actual local CPU Q24 affine + hard-gated Head computation for frozen
//! Neuron feature vectors. This is NOT a text Encoder, Laya implementation,
//! a GPU tensor batch, cross-scope cache or production performance attestation.
//!
//! The backend owns only read-only numeric Head tensors. The upstream owner
//! remains responsible for approved feature extraction, scope, generations,
//! grants, WAL durability and provenance.

use std::collections::BTreeMap;
use std::time::Instant;

use super::*;

const Q: i128 = 1_i128 << 24;
const MAX_INPUT: usize = 512;
const MAX_OUTPUT: usize = 512;

/// Read-only, Q24 affine Head: one hard-sigmoid gate for drive and prediction.
/// Nonempty matrices are row-major [output_width, input_width]. An empty\n/// prediction or gate matrix means a canonical constant-zero matrix; only\n/// drive weights must be dense. Compact profiles count actual stored tensors.
#[derive(Clone, Debug, Eq, PartialEq, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CpuGatedHead {
    pub input_width: usize,
    pub output_width: usize,
    pub drive_weights_q24: Vec<i64>,
    pub prediction_weights_q24: Vec<i64>,
    pub gate_weights_q24: Vec<i64>,
    pub drive_bias_q24: Vec<i64>,
    pub prediction_bias_q24: Vec<i64>,
    pub gate_bias_q24: Vec<i64>,
}

impl CpuGatedHead {
    fn validate(&self) -> Result<(), Error> {
        if self.input_width == 0
            || self.input_width > MAX_INPUT
            || self.output_width == 0
            || self.output_width > MAX_OUTPUT
        {
            return Err(Error::FeatureLimit);
        }
        let n = self
            .input_width
            .checked_mul(self.output_width)
            .ok_or(Error::ArithmeticOverflow)?;
        if self.drive_weights_q24.len() != n
            || !(self.prediction_weights_q24.is_empty() || self.prediction_weights_q24.len() == n)
            || !(self.gate_weights_q24.is_empty() || self.gate_weights_q24.len() == n)
            || self.drive_bias_q24.len() != self.output_width
            || self.prediction_bias_q24.len() != self.output_width
            || self.gate_bias_q24.len() != self.output_width
        {
            return Err(Error::FeatureLimit);
        }
        if self.all_tensors().iter().any(|items| {
            items
                .iter()
                .any(|v| !(-Q24_STATE_LIMIT..=Q24_STATE_LIMIT).contains(v))
        }) {
            return Err(Error::FeatureLimit);
        }
        Ok(())
    }

    fn all_tensors(&self) -> [&[i64]; 6] {
        [
            &self.drive_weights_q24,
            &self.prediction_weights_q24,
            &self.gate_weights_q24,
            &self.drive_bias_q24,
            &self.prediction_bias_q24,
            &self.gate_bias_q24,
        ]
    }

    /// Digest binds dimensions, tensor order and exact Q24 coefficients.
    pub fn digest(&self) -> Result<String, Error> {
        self.validate()?;
        let mut bytes = b"hepta.cpu-gated-head.v1".to_vec();
        bytes.extend_from_slice(&(self.input_width as u64).to_be_bytes());
        bytes.extend_from_slice(&(self.output_width as u64).to_be_bytes());
        for tensor in self.all_tensors() {
            bytes.extend_from_slice(&(tensor.len() as u64).to_be_bytes());
            for value in tensor {
                bytes.extend_from_slice(&value.to_be_bytes());
            }
        }
        Ok(Digest32::of_bytes(&bytes).to_string())
    }

    fn tracked_parameter_bytes(&self) -> Result<u64, Error> {
        self.all_tensors().iter().try_fold(0u64, |total, tensor| {
            let len = u64::try_from(tensor.len()).map_err(|_| Error::ArithmeticOverflow)?;
            total
                .checked_add(len.checked_mul(8).ok_or(Error::ArithmeticOverflow)?)
                .ok_or(Error::ArithmeticOverflow)
        })
    }

    fn dot(&self, weights: &[i64], bias: i64, row: usize, input: &[i64]) -> Result<i64, Error> {
        if weights.is_empty() {
            // Canonical constant-zero matrix profile: reduces physical Head
            // tensors for compact Linear/no-prediction or constant-gate cells.
            return Ok(bias);
        }
        let start = row
            .checked_mul(self.input_width)
            .ok_or(Error::ArithmeticOverflow)?;
        let mut acc = (bias as i128) * Q;
        for (x, w) in input.iter().zip(&weights[start..start + self.input_width]) {
            acc += (*x as i128) * (*w as i128);
        }
        round_q48_to_q24(acc)
    }

    fn infer(&self, input: &[i64]) -> Result<(Vec<i64>, Vec<i64>), Error> {
        if input.len() != self.input_width
            || input
                .iter()
                .any(|v| !(-Q24_STATE_LIMIT..=Q24_STATE_LIMIT).contains(v))
        {
            return Err(Error::FeatureLimit);
        }
        let mut drive = Vec::with_capacity(self.output_width);
        let mut prediction = Vec::with_capacity(self.output_width);
        for row in 0..self.output_width {
            let gate_pre = self.dot(&self.gate_weights_q24, self.gate_bias_q24[row], row, input)?;
            // Hard sigmoid: clamp((gate_pre + 1) / 2, 0, 1).
            // The division itself is a Q24 quantization boundary: apply
            // ties-to-even rather than truncation, including for odd negative
            // gate_pre values. Otherwise a Cell Head can drift by one Q24 LSB.
            let numerator = (gate_pre as i128 + Q).clamp(0, 2 * Q);
            let half = numerator / 2;
            let gate = half + i128::from(numerator % 2 != 0 && half % 2 != 0);
            let d = self.dot(
                &self.drive_weights_q24,
                self.drive_bias_q24[row],
                row,
                input,
            )?;
            let p = self.dot(
                &self.prediction_weights_q24,
                self.prediction_bias_q24[row],
                row,
                input,
            )?;
            drive.push(round_q48_to_q24((d as i128) * gate)?);
            prediction.push(round_q48_to_q24((p as i128) * gate)?);
        }
        Ok((drive, prediction))
    }

    /// Execute Q24 affine operations by output row across several Cell inputs.
    /// Each read-only Head coefficient is fetched once per output/feature and
    /// applied to every lane in this group. This is CPU arithmetic over a
    /// contiguous buffer, NOT a fused Encoder/tensor-runtime or SIMD claim.
    ///
    /// Returned rows preserve the caller's lane order. No partially valid
    /// predictions escape when any member is malformed or overflows Q24.
    fn infer_batch(
        &self,
        packed_inputs: &[i64],
        lanes: &[usize],
        input_width: usize,
    ) -> Result<Vec<(Vec<i64>, Vec<i64>)>, Error> {
        self.validate()?;
        if lanes.is_empty()
            || lanes.len() > 32
            || input_width != self.input_width
            || packed_inputs.len() % input_width != 0
        {
            return Err(Error::FeatureBatchMismatch);
        }
        let available = packed_inputs.len() / input_width;
        let mut distinct = std::collections::BTreeSet::new();
        for &lane in lanes {
            if lane >= available || !distinct.insert(lane) {
                return Err(Error::FeatureBatchMismatch);
            }
            let start = lane
                .checked_mul(input_width)
                .ok_or(Error::ArithmeticOverflow)?;
            if packed_inputs[start..start + input_width]
                .iter()
                .any(|x| !(-Q24_STATE_LIMIT..=Q24_STATE_LIMIT).contains(x))
            {
                return Err(Error::FeatureLimit);
            }
        }

        let mut outputs = (0..lanes.len())
            .map(|_| {
                (
                    Vec::with_capacity(self.output_width),
                    Vec::with_capacity(self.output_width),
                )
            })
            .collect::<Vec<_>>();
        // Bounded at 32 lanes. Reuse Q48 accumulators across output rows.
        let mut acc = vec![[0_i128; 3]; lanes.len()];
        for row in 0..self.output_width {
            let baseline = [
                (self.gate_bias_q24[row] as i128) * Q,
                (self.drive_bias_q24[row] as i128) * Q,
                (self.prediction_bias_q24[row] as i128) * Q,
            ];
            acc.fill(baseline);
            let offset = row
                .checked_mul(input_width)
                .ok_or(Error::ArithmeticOverflow)?;
            for col in 0..input_width {
                let index = offset + col;
                let gate_w = self.gate_weights_q24.get(index).copied().unwrap_or(0) as i128;
                let drive_w = self.drive_weights_q24[index] as i128;
                let predict_w =
                    self.prediction_weights_q24.get(index).copied().unwrap_or(0) as i128;
                for (out, &lane) in acc.iter_mut().zip(lanes) {
                    let input_index = lane * input_width + col;
                    let x = packed_inputs[input_index] as i128;
                    out[0] += x * gate_w;
                    out[1] += x * drive_w;
                    out[2] += x * predict_w;
                }
            }
            for (output, values) in outputs.iter_mut().zip(&acc) {
                let gate_pre = round_q48_to_q24(values[0])?;
                let numerator = (gate_pre as i128 + Q).clamp(0, 2 * Q);
                let half = numerator / 2;
                let gate = half + i128::from(numerator % 2 != 0 && half % 2 != 0);
                let d = round_q48_to_q24(values[1])?;
                let p = round_q48_to_q24(values[2])?;
                output.0.push(round_q48_to_q24((d as i128) * gate)?);
                output.1.push(round_q48_to_q24((p as i128) * gate)?);
            }
        }
        Ok(outputs)
    }
}

fn round_q48_to_q24(value: i128) -> Result<i64, Error> {
    let floor = value.div_euclid(Q);
    let remainder = value.rem_euclid(Q);
    let twice = remainder * 2;
    let rounded = if twice > Q || (twice == Q && floor.rem_euclid(2) == 1) {
        floor.checked_add(1).ok_or(Error::ArithmeticOverflow)?
    } else {
        floor
    };
    let result = i64::try_from(rounded).map_err(|_| Error::FeatureOutputMismatch)?;
    if !(-Q24_STATE_LIMIT..=Q24_STATE_LIMIT).contains(&result) {
        return Err(Error::FeatureOutputMismatch);
    }
    Ok(result)
}

/// Binds exact installed Q24 Head matrices to an externally supplied
/// frozen Encoder feature identity. Does not authenticate Encoder execution.
pub fn cpu_gated_bundle_weights_digest(
    encoder_digest: &str,
    heads: &[CpuGatedHead],
) -> Result<String, Error> {
    validate_digest(encoder_digest, "encoder")?;
    if heads.is_empty() {
        return Err(Error::ModelNotLoaded);
    }
    let mut hashes = heads
        .iter()
        .map(CpuGatedHead::digest)
        .collect::<Result<Vec<_>, _>>()?;
    hashes.sort();
    if hashes.windows(2).any(|w| w[0] == w[1]) {
        return Err(Error::FeatureBatchMismatch);
    }
    let mut bytes = b"hepta.cpu-gated-bundle.v1".to_vec();
    bytes.extend_from_slice(encoder_digest.as_bytes());
    bytes.extend_from_slice(&(hashes.len() as u64).to_be_bytes());
    for head_digest in hashes {
        bytes.extend_from_slice(head_digest.as_bytes());
    }
    Ok(Digest32::of_bytes(&bytes).to_string())
}

/// Concrete numeric backend for the already-encoded Q24 Cell feature path.
/// The only execution shortcut is a single batch call with contiguous inputs.
#[derive(Debug)]
pub struct CpuGatedHeadDriver {
    manifest: ModelManifest,
    encoder_digest: String,
    heads: BTreeMap<String, CpuGatedHead>,
    tracked_weights_bytes: u64,
    loaded: bool,
    // In-process diagnostic count of actual native Head batch dispatches.
    // Not a signed hardware measurement or evidence of an Encoder batch.
    backend_batch_invocations: u64,
}

impl CpuGatedHeadDriver {
    pub fn new(
        manifest: ModelManifest,
        encoder_digest: String,
        specs: Vec<CpuGatedHead>,
    ) -> Result<Self, Error> {
        validate_manifest(&manifest)?;
        let digest = cpu_gated_bundle_weights_digest(&encoder_digest, &specs)?;
        if manifest.weights_digest != digest {
            return Err(Error::ModelMismatch);
        }
        let mut heads = BTreeMap::new();
        let mut weight_bytes = 0u64;
        for spec in specs {
            weight_bytes = weight_bytes
                .checked_add(spec.tracked_parameter_bytes()?)
                .ok_or(Error::ArithmeticOverflow)?;
            heads.insert(spec.digest()?, spec);
        }
        Ok(Self {
            manifest,
            encoder_digest,
            heads,
            tracked_weights_bytes: weight_bytes,
            loaded: false,
            backend_batch_invocations: 0,
        })
    }

    #[must_use]
    pub const fn observed_backend_batch_invocations(&self) -> u64 {
        self.backend_batch_invocations
    }

    fn validate_selected(
        &self,
        handle: &DriverModelHandle,
        request: &NeuronFeatureRequest,
    ) -> Result<&CpuGatedHead, Error> {
        if !self.loaded || handle.opaque_id != format!("cpu-gated:{}", self.manifest.model_id) {
            return Err(Error::ModelNotLoaded);
        }
        if request.authorization.model_digest != self.manifest.model_digest
            || request.weights_digest != self.manifest.weights_digest
            || request.encoder_digest != self.encoder_digest
        {
            return Err(Error::ModelMismatch);
        }
        let head = self
            .heads
            .get(&request.head_digest)
            .ok_or(Error::ModelMismatch)?;
        if head.input_width != request.feature_vector_q24.len()
            || head.output_width != request.expected_output_width
        {
            return Err(Error::FeatureLimit);
        }
        Ok(head)
    }
}

impl ModelDriver for CpuGatedHeadDriver {
    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        if self.loaded {
            return Err(Error::ModelAlreadyLoaded);
        }
        if manifest != &self.manifest {
            return Err(Error::ModelMismatch);
        }
        self.loaded = true;
        Ok(DriverModelHandle {
            opaque_id: format!("cpu-gated:{}", self.manifest.model_id),
            observed_memory_bytes: self.tracked_weights_bytes,
        })
    }

    fn run(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        Err(Error::DriverFailure(
            "Q24 gated Head driver cannot run a text/provider model".to_string(),
        ))
    }

    fn unload(&mut self, handle: DriverModelHandle) -> Result<(), Error> {
        if !self.loaded || handle.opaque_id != format!("cpu-gated:{}", self.manifest.model_id) {
            return Err(Error::ModelNotLoaded);
        }
        self.loaded = false;
        Ok(())
    }
}

impl NeuronFeatureDriver for CpuGatedHeadDriver {
    fn run_neuron_features(
        &mut self,
        handle: &DriverModelHandle,
        request: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, Error> {
        let started = Instant::now();
        let head = self.validate_selected(handle, request)?;
        let (drive, prediction) = head.infer(&request.feature_vector_q24)?;
        let transient =
            u64::try_from((drive.capacity() + prediction.capacity()) * std::mem::size_of::<i64>())
                .map_err(|_| Error::ArithmeticOverflow)?;
        Ok(DriverNeuronFeatureObservation {
            terminal_observed: true,
            succeeded: true,
            encoder_digest: request.encoder_digest.clone(),
            head_digest: request.head_digest.clone(),
            drive_q24: drive,
            prediction_q24: prediction,
            observed_memory_bytes: self.tracked_weights_bytes,
            transient_allocation_bytes: transient,
            queue_age_micros: 0, // no scheduler queue in this driver
            latency_micros: started.elapsed().as_micros().try_into().unwrap_or(u64::MAX),
        })
    }
}

impl NeuronBackendBatchDriver for CpuGatedHeadDriver {
    fn preflight_neuron_backend_batch_bytes(
        &self,
        handle: &DriverModelHandle,
        requests: &[NeuronFeatureRequest],
    ) -> Result<u64, Error> {
        if requests.is_empty() || requests.len() > 32 {
            return Err(Error::FeatureBatchLimit);
        }
        let input_width = requests[0].feature_vector_q24.len();
        let mut members_by_head = BTreeMap::<&str, usize>::new();
        let mut output_bytes = 0usize;
        for request in requests {
            let head = self.validate_selected(handle, request)?;
            if request.feature_vector_q24.len() != input_width {
                return Err(Error::FeatureBatchMismatch);
            }
            // This is a minimum tracked numeric allocation, not actual RSS.
            // Scalar and batch paths allocate both Q24 output arrays per Cell.
            let member_bytes = head
                .output_width
                .checked_mul(2)
                .and_then(|n| n.checked_mul(std::mem::size_of::<i64>()))
                .ok_or(Error::ArithmeticOverflow)?;
            output_bytes = output_bytes
                .checked_add(member_bytes)
                .ok_or(Error::ArithmeticOverflow)?;
            let count = members_by_head.entry(&request.head_digest).or_insert(0);
            *count = count.checked_add(1).ok_or(Error::ArithmeticOverflow)?;
        }
        let accumulator_bytes = members_by_head
            .values()
            .copied()
            .max()
            .unwrap_or(0)
            .checked_mul(3)
            .and_then(|n| n.checked_mul(std::mem::size_of::<i128>()))
            .ok_or(Error::ArithmeticOverflow)?;
        let input_bytes = requests
            .len()
            .checked_mul(input_width)
            .and_then(|n| n.checked_mul(std::mem::size_of::<i64>()))
            .ok_or(Error::ArithmeticOverflow)?;
        let transient = input_bytes
            .checked_add(output_bytes)
            .and_then(|n| n.checked_add(accumulator_bytes))
            .ok_or(Error::ArithmeticOverflow)?;
        self.tracked_weights_bytes
            .checked_add(u64::try_from(transient).map_err(|_| Error::ArithmeticOverflow)?)
            .ok_or(Error::ArithmeticOverflow)
    }

    fn run_neuron_backend_batch(
        &mut self,
        handle: &DriverModelHandle,
        batch_digest: &str,
        requests: &[NeuronFeatureRequest],
    ) -> Result<DriverNeuronBackendBatch, Error> {
        if requests.is_empty() {
            return Err(Error::FeatureBatchLimit);
        }
        let started = Instant::now();
        let width = requests[0].feature_vector_q24.len();
        let mut contiguous = Vec::with_capacity(
            requests
                .len()
                .checked_mul(width)
                .ok_or(Error::ArithmeticOverflow)?,
        );
        for request in requests {
            self.validate_selected(handle, request)?;
            if request.feature_vector_q24.len() != width {
                return Err(Error::FeatureBatchMismatch);
            }
            if request
                .feature_vector_q24
                .iter()
                .any(|value| !(-Q24_STATE_LIMIT..=Q24_STATE_LIMIT).contains(value))
            {
                return Err(Error::FeatureLimit);
            }
            contiguous.extend_from_slice(&request.feature_vector_q24);
        }
        // Count only a fully validated dispatch, not an invalid input batch.
        self.backend_batch_invocations = self
            .backend_batch_invocations
            .checked_add(1)
            .ok_or(Error::ArithmeticOverflow)?;
        // Batch by exact immutable Head digest. This kernel traverses each
        // Head's row weights across all of its lanes, rather than repeatedly
        // invoking the single-Cell Head kernel for every request.
        let mut head_lanes = BTreeMap::<&str, Vec<usize>>::new();
        for (index, request) in requests.iter().enumerate() {
            head_lanes
                .entry(request.head_digest.as_str())
                .or_default()
                .push(index);
        }
        let mut results = (0..requests.len())
            .map(|_| None)
            .collect::<Vec<Option<(Vec<i64>, Vec<i64>)>>>();
        let mut tracked_accumulator_peak = 0u64;
        for (head_digest, lanes) in head_lanes {
            let head = self.heads.get(head_digest).ok_or(Error::ModelMismatch)?;
            // A bounded Q48 workspace is allocated once per immutable Head
            // group and reused for each output row. Include its high-water
            // bound rather than undercounting the newly batched arithmetic.
            let accumulator_bytes = lanes
                .len()
                .checked_mul(3)
                .and_then(|n| n.checked_mul(std::mem::size_of::<i128>()))
                .ok_or(Error::ArithmeticOverflow)?;
            tracked_accumulator_peak = tracked_accumulator_peak
                .max(u64::try_from(accumulator_bytes).map_err(|_| Error::ArithmeticOverflow)?);
            for (&index, output) in
                lanes
                    .iter()
                    .zip(head.infer_batch(&contiguous, &lanes, width)?)
            {
                results[index] = Some(output);
            }
        }

        let mut members = Vec::with_capacity(requests.len());
        let mut tracked_outputs = 0u64;
        for (index, request) in requests.iter().enumerate() {
            let (drive, prediction) = results[index].take().ok_or(Error::FeatureBatchMismatch)?;
            let temporary = (drive.capacity() + prediction.capacity())
                .checked_mul(std::mem::size_of::<i64>())
                .ok_or(Error::ArithmeticOverflow)?;
            tracked_outputs = tracked_outputs
                .checked_add(u64::try_from(temporary).map_err(|_| Error::ArithmeticOverflow)?)
                .ok_or(Error::ArithmeticOverflow)?;
            members.push(DriverNeuronBatchMember {
                request_id: request.authorization.request_id.clone(),
                input_digest: request.input_digest.clone(),
                observation: DriverNeuronFeatureObservation {
                    terminal_observed: true,
                    succeeded: true,
                    encoder_digest: request.encoder_digest.clone(),
                    head_digest: request.head_digest.clone(),
                    drive_q24: drive,
                    prediction_q24: prediction,
                    observed_memory_bytes: self.tracked_weights_bytes,
                    transient_allocation_bytes: u64::try_from(temporary)
                        .map_err(|_| Error::ArithmeticOverflow)?,
                    queue_age_micros: 0,
                    // Set to the shared real backend-batch duration below:
                    // per-lane standalone compute time is not measurable after
                    // physically grouped coefficient traversal.
                    latency_micros: 0,
                },
            });
        }
        let input_bytes = contiguous
            .capacity()
            .checked_mul(std::mem::size_of::<i64>())
            .ok_or(Error::ArithmeticOverflow)?;
        // Only tracked numeric allocations; not process RSS or a GPU allocator peak.
        let peak = self
            .tracked_weights_bytes
            .checked_add(u64::try_from(input_bytes).map_err(|_| Error::ArithmeticOverflow)?)
            .and_then(|n| n.checked_add(tracked_outputs))
            .and_then(|n| n.checked_add(tracked_accumulator_peak))
            .ok_or(Error::ArithmeticOverflow)?;
        // All lanes complete at the same backend-batch boundary. Reporting
        // a fresh 0us timer *after* computing each lane would understate
        // latency; do not invent a per-Cell arithmetic share of batch time.
        let backend_elapsed_micros = started.elapsed().as_micros().try_into().unwrap_or(u64::MAX);
        for member in &mut members {
            member.observation.latency_micros = backend_elapsed_micros;
        }
        Ok(DriverNeuronBackendBatch {
            batch_digest: batch_digest.to_string(),
            members,
            observed_peak_memory_bytes: peak,
            backend_elapsed_micros,
        })
    }
}

#[cfg(test)]
#[path = "model_worker_cpu_head_tests.rs"]
mod tests;
