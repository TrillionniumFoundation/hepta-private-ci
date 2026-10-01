//! Real local execution of immutable Q24 encoder and two learned dense heads.
//! Loading checks bytes and the complete backend tuple; qualification and
//! resource admission remain with the existing artifact and worker owners.
use std::fs::File;
use std::io::Read;
use std::path::Component;
use std::path::Path;
use std::time::Instant;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use crate::model_worker::DriverModelHandle;
use crate::model_worker::DriverNeuronFeatureObservation;
use crate::model_worker::DriverRunObservation;
use crate::model_worker::Error;
use crate::model_worker::ModelDriver;
use crate::model_worker::ModelManifest;
use crate::model_worker::NeuronFeatureDriver;
use crate::model_worker::NeuronFeatureRequest;
use crate::model_worker::WorkerRequest;

pub const CPU_NEURON_RUNTIME_PROFILE_V1: &[u8] =
    b"hepta.cpu-neuron.dense-encoder-relu-two-heads.q24.v1";
pub const CPU_NEURON_QUANTIZATION_PROFILE_V1: &[u8] =
    b"signed-q24.i128-accumulation.nearest-ties-even.saturate-eight.v1";
pub const CPU_NEURON_PREPROCESSOR_PROFILE_V1: &[u8] = b"canonical-feature-vector.signed-q24.v1";
pub const CPU_NEURON_TOKENIZER_PROFILE_V1: &[u8] = b"numeric-feature-vector.no-text-tokenizer.v1";
const Q24: i64 = 1 << 24;
const LIMIT: i64 = 8 * Q24;
const MAX_BYTES: u64 = 16 * 1024 * 1024;

/// The model manifest is itself checksum pinned by the installed qualified
/// selection. The HPTNCPU1 payload is: magic, three u16 big-endian dimensions
/// (input, hidden, output), then encoder, drive and prediction matrices as
/// row-major i64 big-endian Q24 coefficients, with a bias after each row.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CpuNeuronManifestV1 {
    pub version: u32,
    pub model_id: String,
    pub weights_filename: String,
    pub weights_digest: String,
    pub encoder_digest: String,
    pub head_digest: String,
    pub tokenizer_digest: String,
    pub preprocessor_digest: String,
    pub quantization_digest: String,
    pub runtime_digest: String,
    pub device_digest: String,
    pub maximum_tokens: u32,
}

struct Weights {
    input: usize,
    hidden: usize,
    output: usize,
    encoder: Vec<i64>,
    drive: Vec<i64>,
    prediction: Vec<i64>,
}
pub struct CpuNeuronModelDriver {
    manifest: ModelManifest,
    pub(crate) encoder_digest: String,
    pub(crate) head_digest: String,
    weights: Option<Weights>,
    loaded: bool,
}

impl CpuNeuronModelDriver {
    pub fn open(path: &Path, expected: Digest32) -> Result<Self, Error> {
        let bytes = read_installed(path, 64 * 1024)?;
        if expected.is_zero() || Digest32::of_bytes(&bytes) != expected {
            return Err(Error::ModelMismatch);
        }
        let descriptor: CpuNeuronManifestV1 =
            serde_json::from_slice(&bytes).map_err(|_| Error::InvalidManifest)?;
        let mut components = Path::new(&descriptor.weights_filename).components();
        if descriptor.version != 1
            || !matches!(components.next(), Some(Component::Normal(_)))
            || components.next().is_some()
            || descriptor.weights_filename.len() > 255
            || descriptor.tokenizer_digest
                != Digest32::of_bytes(CPU_NEURON_TOKENIZER_PROFILE_V1).to_string()
            || descriptor.preprocessor_digest
                != Digest32::of_bytes(CPU_NEURON_PREPROCESSOR_PROFILE_V1).to_string()
            || descriptor.quantization_digest
                != Digest32::of_bytes(CPU_NEURON_QUANTIZATION_PROFILE_V1).to_string()
            || descriptor.runtime_digest
                != Digest32::of_bytes(CPU_NEURON_RUNTIME_PROFILE_V1).to_string()
            || descriptor.device_digest != cpu_neuron_device_digest_v1()?.to_string()
        {
            return Err(Error::InvalidManifest);
        }
        let payload = read_installed(
            &path
                .parent()
                .ok_or(Error::InvalidManifest)?
                .join(&descriptor.weights_filename),
            MAX_BYTES,
        )?;
        if descriptor.weights_digest != Digest32::of_bytes(&payload).to_string()
            || payload.len() < 14
            || &payload[..8] != b"HPTNCPU1"
        {
            return Err(Error::ModelMismatch);
        }
        let dimensions: Vec<usize> = payload[8..14]
            .chunks_exact(2)
            .map(|pair| u16::from_be_bytes([pair[0], pair[1]]) as usize)
            .collect();
        if dimensions.iter().any(|value| !(1..=512).contains(value)) {
            return Err(Error::FeatureLimit);
        }
        let [input, hidden, output] = [dimensions[0], dimensions[1], dimensions[2]];
        let encoder_end = 14 + hidden * (input + 1) * 8;
        let drive_end = encoder_end + output * (hidden + 1) * 8;
        let prediction_end = drive_end + output * (hidden + 1) * 8;
        if payload.len() != prediction_end
            || descriptor.encoder_digest
                != Digest32::of_bytes(&payload[14..encoder_end]).to_string()
            || descriptor.head_digest != Digest32::of_bytes(&payload[encoder_end..]).to_string()
        {
            return Err(Error::ModelMismatch);
        }
        let decode = |bytes: &[u8]| -> Result<Vec<i64>, Error> {
            bytes
                .chunks_exact(8)
                .map(|chunk| {
                    let value =
                        i64::from_be_bytes(chunk.try_into().map_err(|_| Error::InvalidManifest)?);
                    if !(-LIMIT..=LIMIT).contains(&value) {
                        return Err(Error::FeatureLimit);
                    }
                    Ok(value)
                })
                .collect()
        };
        let weights = Weights {
            input,
            hidden,
            output,
            encoder: decode(&payload[14..encoder_end])?,
            drive: decode(&payload[encoder_end..drive_end])?,
            prediction: decode(&payload[drive_end..])?,
        };
        Ok(Self {
            manifest: ModelManifest {
                model_id: descriptor.model_id,
                model_digest: expected.to_string(),
                weights_digest: descriptor.weights_digest,
                tokenizer_digest: descriptor.tokenizer_digest,
                preprocessor_digest: descriptor.preprocessor_digest,
                quantization_digest: descriptor.quantization_digest,
                runtime_digest: descriptor.runtime_digest,
                device_digest: descriptor.device_digest,
                maximum_tokens: descriptor.maximum_tokens,
            },
            encoder_digest: descriptor.encoder_digest,
            head_digest: descriptor.head_digest,
            weights: Some(weights),
            loaded: false,
        })
    }

    pub fn manifest(&self) -> &ModelManifest {
        &self.manifest
    }

    pub fn encoder_digest(&self) -> &str {
        &self.encoder_digest
    }

    pub fn head_digest(&self) -> &str {
        &self.head_digest
    }

    #[cfg(feature = "agentd-host")]
    pub(crate) fn feature_dimensions(&self) -> Result<(usize, usize), Error> {
        let weights = self.weights.as_ref().ok_or(Error::ModelNotLoaded)?;
        Ok((weights.input, weights.output))
    }
}

impl ModelDriver for CpuNeuronModelDriver {
    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        if self.loaded {
            return Err(Error::ModelAlreadyLoaded);
        }
        if manifest != &self.manifest {
            return Err(Error::ModelMismatch);
        }
        let weights = self.weights.as_ref().ok_or(Error::ModelNotLoaded)?;
        self.loaded = true;
        Ok(DriverModelHandle {
            opaque_id: self.manifest.model_digest.clone(),
            observed_memory_bytes: ((weights.encoder.capacity()
                + weights.drive.capacity()
                + weights.prediction.capacity())
                * std::mem::size_of::<i64>()) as u64,
        })
    }
    fn run(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        Err(Error::DriverFailure(
            "installed CPU feature backend requires a typed neuron request".into(),
        ))
    }
    fn unload(&mut self, handle: DriverModelHandle) -> Result<(), Error> {
        if !self.loaded || handle.opaque_id != self.manifest.model_digest {
            return Err(Error::ModelMismatch);
        }
        self.loaded = false;
        self.weights.take();
        Ok(())
    }
}
impl NeuronFeatureDriver for CpuNeuronModelDriver {
    fn run_neuron_features(
        &mut self,
        handle: &DriverModelHandle,
        request: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, Error> {
        let started = Instant::now();
        let weights = self.weights.as_ref().ok_or(Error::ModelNotLoaded)?;
        if !self.loaded
            || handle.opaque_id != self.manifest.model_digest
            || request.encoder_digest != self.encoder_digest
            || request.head_digest != self.head_digest
            || request.weights_digest != self.manifest.weights_digest
            || request.feature_vector_q24.len() != weights.input
            || request.expected_output_width != weights.output
            || request
                .feature_vector_q24
                .iter()
                .any(|value| !(-LIMIT..=LIMIT).contains(value))
        {
            return Err(Error::ModelMismatch);
        }
        let mut hidden = dense(
            &weights.encoder,
            &request.feature_vector_q24,
            weights.hidden,
        )?;
        for value in &mut hidden {
            *value = (*value).max(0);
        }
        let drive = dense(&weights.drive, &hidden, weights.output)?;
        let prediction = dense(&weights.prediction, &hidden, weights.output)?;
        let transient = ((hidden.capacity() + drive.capacity() + prediction.capacity())
            * std::mem::size_of::<i64>()) as u64;
        Ok(DriverNeuronFeatureObservation {
            terminal_observed: true,
            succeeded: true,
            encoder_digest: self.encoder_digest.clone(),
            head_digest: self.head_digest.clone(),
            drive_q24: drive,
            prediction_q24: prediction,
            observed_memory_bytes: handle.observed_memory_bytes,
            transient_allocation_bytes: transient,
            queue_age_micros: 0,
            latency_micros: u64::try_from(started.elapsed().as_micros())
                .map_err(|_| Error::ArithmeticOverflow)?,
        })
    }
}

fn dense(matrix: &[i64], input: &[i64], width: usize) -> Result<Vec<i64>, Error> {
    let mut output = Vec::with_capacity(width);
    for row in matrix.chunks_exact(input.len() + 1) {
        let mut sum = i128::from(row[input.len()]) * i128::from(Q24);
        for (weight, value) in row.iter().zip(input) {
            sum = sum
                .checked_add(i128::from(*weight) * i128::from(*value))
                .ok_or(Error::ArithmeticOverflow)?;
        }
        let magnitude = sum.abs();
        let mut rounded = magnitude / i128::from(Q24);
        let remainder = magnitude % i128::from(Q24);
        if remainder * 2 > i128::from(Q24) || remainder * 2 == i128::from(Q24) && rounded % 2 != 0 {
            rounded += 1;
        }
        let signed = if sum < 0 { -rounded } else { rounded };
        output.push(signed.clamp(-i128::from(LIMIT), i128::from(LIMIT)) as i64);
    }
    if output.len() != width {
        return Err(Error::FeatureOutputMismatch);
    }
    Ok(output)
}

pub fn cpu_neuron_device_digest_v1() -> Result<Digest32, Error> {
    let mut file = File::open("/proc/cpuinfo").map_err(driver_io)?;
    let mut bytes = Vec::new();
    file.by_ref()
        .take(2 * 1024 * 1024 + 1)
        .read_to_end(&mut bytes)
        .map_err(driver_io)?;
    if bytes.is_empty() || bytes.len() > 2 * 1024 * 1024 {
        return Err(Error::InvalidManifest);
    }
    // Clock MHz and scheduling-dependent bogomips are not device identity.
    let text = std::str::from_utf8(&bytes).map_err(|_| Error::InvalidManifest)?;
    let identity = text
        .lines()
        .filter(|line| !line.starts_with("cpu MHz") && !line.starts_with("bogomips"))
        .collect::<Vec<_>>()
        .join("\n");
    Ok(Digest32::of_parts(&[
        b"hepta.cpu-neuron.device.v1",
        std::env::consts::ARCH.as_bytes(),
        identity.as_bytes(),
    ]))
}
fn driver_io(error: std::io::Error) -> Error {
    Error::DriverFailure(error.to_string())
}
fn read_installed(path: &Path, maximum: u64) -> Result<Vec<u8>, Error> {
    if !path.is_absolute() || path.canonicalize().map_err(driver_io)? != path {
        return Err(Error::InvalidManifest);
    }
    let metadata = std::fs::symlink_metadata(path).map_err(driver_io)?;
    if !metadata.is_file()
        || metadata.file_type().is_symlink()
        || metadata.len() == 0
        || metadata.len() > maximum
    {
        return Err(Error::InvalidManifest);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if metadata.nlink() != 1
            || metadata.mode() & 0o022 != 0
            || metadata.uid() != 0 && metadata.uid() != rustix::process::geteuid().as_raw()
        {
            return Err(Error::InvalidManifest);
        }
    }
    let file = File::open(path).map_err(driver_io)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        let opened = file.metadata().map_err(driver_io)?;
        if opened.dev() != metadata.dev() || opened.ino() != metadata.ino() {
            return Err(Error::InvalidManifest);
        }
    }
    let mut bytes = Vec::new();
    file.take(maximum + 1)
        .read_to_end(&mut bytes)
        .map_err(driver_io)?;
    if bytes.len() as u64 != metadata.len() {
        return Err(Error::InvalidManifest);
    }
    Ok(bytes)
}

#[cfg(test)]
#[path = "local_cpu_model_tests.rs"]
mod tests;
