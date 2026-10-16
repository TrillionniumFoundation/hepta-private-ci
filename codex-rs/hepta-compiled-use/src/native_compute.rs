//! A safe, *actually evaluated* CPU compute Cell behind a fixed 256-byte ABI.
//!
//! This is a fixed, build-time compiled Q24 dot-product kernel. It deliberately
//! cannot load or generate executable bytes, issue capabilities or perform UI
//! effects. A caller-supplied digest/scope is an assertion, NOT authentication.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::{AuthorityPosture, Digest32};

pub const NATIVE_COMPUTE_FRAME_BYTES_V1: usize = 256;
pub const NATIVE_COMPUTE_RESULT_BYTES_V1: usize = 64;
pub const NATIVE_COMPUTE_MAX_LANES_V1: usize = 16;
const MAGIC: &[u8; 4] = b"HNC1";
const RESULT_MAGIC: &[u8; 4] = b"HNR1";
const Q24_SCALE: i128 = 1_i128 << 24;
const Q24_FEATURE_LIMIT: i32 = 8_i32 << 24;

#[must_use]
pub fn approved_q24_dot_kernel_digest_v1() -> Digest32 {
    Digest32::of_bytes(b"hepta.fastcell.native-compiled-q24-dot16.v1")
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NativeComputeErrorV1 {
    MissingBinding,
    UnsupportedKernel,
    GenerationMismatch,
    ScopeMismatch,
    LaneLimit,
    NonCanonicalFrame,
    InputLimit,
    ChecksumMismatch,
    ResultMismatch,
    SequenceMismatch,
    ArithmeticOverflow,
}

impl fmt::Display for NativeComputeErrorV1 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl StdError for NativeComputeErrorV1 {}

/// A data-only request. `task_digest` is bound by the verifier but cannot
/// establish where the data originated or whether the caller is authorized.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeComputeFrameV1 {
    pub generation: u64,
    pub sequence: u64,
    pub task_digest: Digest32,
    pub kernel_digest: Digest32,
    pub lanes: u8,
    pub features_q24: [i32; NATIVE_COMPUTE_MAX_LANES_V1],
    pub weights_q24: [i32; NATIVE_COMPUTE_MAX_LANES_V1],
}

impl NativeComputeFrameV1 {
    fn validate_shape(&self) -> Result<(), NativeComputeErrorV1> {
        if self.generation == 0 || self.sequence == 0 || self.task_digest.is_zero() {
            return Err(NativeComputeErrorV1::MissingBinding);
        }
        if self.kernel_digest != approved_q24_dot_kernel_digest_v1() {
            return Err(NativeComputeErrorV1::UnsupportedKernel);
        }
        let lanes = usize::from(self.lanes);
        if lanes == 0 || lanes > NATIVE_COMPUTE_MAX_LANES_V1 {
            return Err(NativeComputeErrorV1::LaneLimit);
        }
        for index in 0..NATIVE_COMPUTE_MAX_LANES_V1 {
            let (feature, weight) = (self.features_q24[index], self.weights_q24[index]);
            if feature < -Q24_FEATURE_LIMIT
                || feature > Q24_FEATURE_LIMIT
                || weight < -Q24_FEATURE_LIMIT
                || weight > Q24_FEATURE_LIMIT
            {
                return Err(NativeComputeErrorV1::InputLimit);
            }
            if index >= lanes && (feature != 0 || weight != 0) {
                return Err(NativeComputeErrorV1::NonCanonicalFrame);
            }
        }
        Ok(())
    }

    pub fn encode(&self) -> Result<[u8; NATIVE_COMPUTE_FRAME_BYTES_V1], NativeComputeErrorV1> {
        self.validate_shape()?;
        let mut bytes = [0_u8; NATIVE_COMPUTE_FRAME_BYTES_V1];
        bytes[..4].copy_from_slice(MAGIC);
        bytes[4..6].copy_from_slice(&1_u16.to_be_bytes());
        bytes[8..16].copy_from_slice(&self.generation.to_be_bytes());
        bytes[16..24].copy_from_slice(&self.sequence.to_be_bytes());
        bytes[24..56].copy_from_slice(self.task_digest.as_array());
        bytes[56..88].copy_from_slice(self.kernel_digest.as_array());
        bytes[88] = self.lanes;
        for (index, value) in self.features_q24.iter().enumerate() {
            let start = 96 + 4 * index;
            bytes[start..start + 4].copy_from_slice(&value.to_be_bytes());
        }
        for (index, value) in self.weights_q24.iter().enumerate() {
            let start = 160 + 4 * index;
            bytes[start..start + 4].copy_from_slice(&value.to_be_bytes());
        }
        let digest = Digest32::of_bytes(&bytes[..224]);
        bytes[224..].copy_from_slice(digest.as_array());
        Ok(bytes)
    }

    pub fn decode(
        bytes: &[u8; NATIVE_COMPUTE_FRAME_BYTES_V1],
    ) -> Result<Self, NativeComputeErrorV1> {
        if &bytes[..4] != MAGIC
            || bytes[4..6] != 1_u16.to_be_bytes()
            || bytes[6..8].iter().any(|byte| *byte != 0)
            || bytes[89..96].iter().any(|byte| *byte != 0)
        {
            return Err(NativeComputeErrorV1::NonCanonicalFrame);
        }
        if &bytes[224..] != Digest32::of_bytes(&bytes[..224]).as_array() {
            return Err(NativeComputeErrorV1::ChecksumMismatch);
        }
        let mut features_q24 = [0_i32; NATIVE_COMPUTE_MAX_LANES_V1];
        let mut weights_q24 = [0_i32; NATIVE_COMPUTE_MAX_LANES_V1];
        for (index, value) in features_q24.iter_mut().enumerate() {
            let start = 96 + 4 * index;
            *value = i32::from_be_bytes(bytes[start..start + 4].try_into().expect("fixed slice"));
        }
        for (index, value) in weights_q24.iter_mut().enumerate() {
            let start = 160 + 4 * index;
            *value = i32::from_be_bytes(bytes[start..start + 4].try_into().expect("fixed slice"));
        }
        let frame = Self {
            generation: u64::from_be_bytes(bytes[8..16].try_into().expect("fixed slice")),
            sequence: u64::from_be_bytes(bytes[16..24].try_into().expect("fixed slice")),
            task_digest: Digest32::from_array(bytes[24..56].try_into().expect("fixed slice")),
            kernel_digest: Digest32::from_array(bytes[56..88].try_into().expect("fixed slice")),
            lanes: bytes[88],
            features_q24,
            weights_q24,
        };
        frame.validate_shape()?;
        Ok(frame)
    }
}

/// The verifier represents only an immutable data check for this experiment.
/// It is not a FinalUse or hardware/executable-artifact authenticator.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NativeComputeVerifierV1 {
    pub generation: u64,
    pub task_digest: Digest32,
    pub kernel_digest: Digest32,
    pub maximum_lanes: u8,
}

impl NativeComputeVerifierV1 {
    pub fn verify(&self, request: &NativeComputeFrameV1) -> Result<(), NativeComputeErrorV1> {
        request.validate_shape()?;
        if self.generation == 0 || request.generation != self.generation {
            return Err(NativeComputeErrorV1::GenerationMismatch);
        }
        if self.task_digest.is_zero() || request.task_digest != self.task_digest {
            return Err(NativeComputeErrorV1::ScopeMismatch);
        }
        if self.kernel_digest != approved_q24_dot_kernel_digest_v1()
            || request.kernel_digest != self.kernel_digest
        {
            return Err(NativeComputeErrorV1::UnsupportedKernel);
        }
        if self.maximum_lanes == 0 || request.lanes > self.maximum_lanes {
            return Err(NativeComputeErrorV1::LaneLimit);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeComputeObservationV1 {
    pub generation: u64,
    pub sequence: u64,
    pub output_q24: i64,
    pub request_digest: Digest32,
    pub result_digest: Digest32,
    pub authority: AuthorityPosture,
}

fn observation_digest(request_digest: Digest32, output: i64) -> Digest32 {
    let mut bytes = b"hepta.fastcell.shadow-native-result.v1\0".to_vec();
    bytes.extend_from_slice(request_digest.as_array());
    bytes.extend_from_slice(&output.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

/// Real native Rust code executes the CPU arithmetic. No generated code,
/// system call, UI interaction, GPU launch or executable-memory write occurs.
pub fn run_shadow_native_compute_v1(
    verifier: NativeComputeVerifierV1,
    request: &NativeComputeFrameV1,
) -> Result<NativeComputeObservationV1, NativeComputeErrorV1> {
    verifier.verify(request)?;
    let mut accumulator = 0_i128;
    for index in 0..usize::from(request.lanes) {
        let product = i128::from(request.features_q24[index])
            .checked_mul(i128::from(request.weights_q24[index]))
            .ok_or(NativeComputeErrorV1::ArithmeticOverflow)?;
        accumulator = accumulator
            .checked_add(product)
            .ok_or(NativeComputeErrorV1::ArithmeticOverflow)?;
    }
    let magnitude = accumulator.unsigned_abs();
    let scale = Q24_SCALE as u128;
    let quotient = magnitude / scale;
    let remainder = magnitude % scale;
    let rounded = quotient
        + u128::from(remainder > scale / 2 || (remainder == scale / 2 && quotient % 2 == 1));
    let signed = i128::try_from(rounded).map_err(|_| NativeComputeErrorV1::ArithmeticOverflow)?
        * if accumulator < 0 { -1 } else { 1 };
    let output_q24 = i64::try_from(signed).map_err(|_| NativeComputeErrorV1::ArithmeticOverflow)?;
    let request_digest = Digest32::of_bytes(&request.encode()?);
    Ok(NativeComputeObservationV1 {
        generation: request.generation,
        sequence: request.sequence,
        output_q24,
        request_digest,
        result_digest: observation_digest(request_digest, output_q24),
        authority: AuthorityPosture::DENY_ALL,
    })
}

impl NativeComputeObservationV1 {
    pub fn encode(&self) -> Result<[u8; NATIVE_COMPUTE_RESULT_BYTES_V1], NativeComputeErrorV1> {
        if self.authority.grants_any() || self.sequence == 0 || self.generation == 0 {
            return Err(NativeComputeErrorV1::ResultMismatch);
        }
        if self.result_digest != observation_digest(self.request_digest, self.output_q24) {
            return Err(NativeComputeErrorV1::ResultMismatch);
        }
        let mut bytes = [0_u8; NATIVE_COMPUTE_RESULT_BYTES_V1];
        bytes[..4].copy_from_slice(RESULT_MAGIC);
        bytes[4..12].copy_from_slice(&self.generation.to_be_bytes());
        bytes[12..20].copy_from_slice(&self.sequence.to_be_bytes());
        bytes[20..28].copy_from_slice(&self.output_q24.to_be_bytes());
        bytes[28..60].copy_from_slice(self.result_digest.as_array());
        Ok(bytes)
    }
}

/// Consistency-only result decoding. The digest is recomputed against the
/// original request; it is NOT an authenticated peer or independent computation
/// witness. A hostile peer could fabricate a self-consistent result.
pub fn decode_shadow_native_result_v1(
    original: &NativeComputeFrameV1,
    result: &[u8; NATIVE_COMPUTE_RESULT_BYTES_V1],
) -> Result<NativeComputeObservationV1, NativeComputeErrorV1> {
    if &result[..4] != RESULT_MAGIC || result[60..].iter().any(|byte| *byte != 0) {
        return Err(NativeComputeErrorV1::NonCanonicalFrame);
    }
    let generation = u64::from_be_bytes(result[4..12].try_into().expect("fixed slice"));
    let sequence = u64::from_be_bytes(result[12..20].try_into().expect("fixed slice"));
    if generation != original.generation || sequence != original.sequence {
        return Err(NativeComputeErrorV1::SequenceMismatch);
    }
    let output_q24 = i64::from_be_bytes(result[20..28].try_into().expect("fixed slice"));
    let result_digest = Digest32::from_array(result[28..60].try_into().expect("fixed slice"));
    let request_digest = Digest32::of_bytes(&original.encode()?);
    if result_digest != observation_digest(request_digest, output_q24) {
        return Err(NativeComputeErrorV1::ChecksumMismatch);
    }
    Ok(NativeComputeObservationV1 {
        generation,
        sequence,
        output_q24,
        request_digest,
        result_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[cfg(test)]
#[path = "native_compute_tests.rs"]
mod tests;
