//! Bounded actual-file SHA-256 observation against the model manifest held
//! by the existing live inference Worker. No model load or final-use authority.
//!
//! The host must open an immutable, trusted CAS file and bind that SAME file
//! descriptor to the physical model loader independently. This method cannot
//! infer which bytes an opaque external ModelDriver actually loaded.

use std::fs::File;
use std::io;
use std::io::Seek;
use std::io::SeekFrom;
use std::str::FromStr;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use super::Error;
use super::InferenceWorker;
use super::ModelDriver;

const DOMAIN: &[u8] = b"hepta.inference.worker.neuron-weight-file.diagnostic.v1\0";
const MAX_WEIGHT_FILE_BYTES: u64 = 2 * 1024 * 1024 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronWeightFileDiagnosticV1 {
    worker_id: String,
    worker_generation: u64,
    model_id: String,
    loaded_handle_id: String,
    loaded_model_manifest_digest: Digest32,
    loaded_weights_digest: Digest32,
    file_bytes: u64,
    loaded_observed_memory_bytes: u64,
    diagnostic_digest: Digest32,
    authority: AuthorityPosture,
}

impl NeuronWeightFileDiagnosticV1 {
    #[must_use]
    pub fn model_id(&self) -> &str {
        &self.model_id
    }

    #[must_use]
    pub fn loaded_weights_digest(&self) -> Digest32 {
        self.loaded_weights_digest
    }

    #[must_use]
    pub fn file_bytes(&self) -> u64 {
        self.file_bytes
    }

    #[must_use]
    pub fn worker_generation(&self) -> u64 {
        self.worker_generation
    }

    #[must_use]
    pub fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    /// This is a checksum, NOT an independently signed proof of actual
    /// ModelDriver byte consumption, production selection or CAS final-use.
    #[must_use]
    pub fn computed_digest(&self) -> Digest32 {
        let mut bytes = DOMAIN.to_vec();
        for id in [
            self.worker_id.as_str(),
            self.model_id.as_str(),
            self.loaded_handle_id.as_str(),
        ] {
            let raw = id.as_bytes();
            bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
            bytes.extend_from_slice(raw);
        }
        bytes.extend_from_slice(&self.worker_generation.to_be_bytes());
        bytes.extend_from_slice(self.loaded_model_manifest_digest.as_array());
        bytes.extend_from_slice(self.loaded_weights_digest.as_array());
        bytes.extend_from_slice(&self.file_bytes.to_be_bytes());
        bytes.extend_from_slice(&self.loaded_observed_memory_bytes.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }

    #[must_use]
    pub fn validate_integrity(&self) -> bool {
        self.authority == AuthorityPosture::DENY_ALL
            && self.worker_generation != 0
            && !self.worker_id.is_empty()
            && !self.model_id.is_empty()
            && !self.loaded_handle_id.is_empty()
            && !self.loaded_model_manifest_digest.is_zero()
            && !self.loaded_weights_digest.is_zero()
            && (1..=MAX_WEIGHT_FILE_BYTES).contains(&self.file_bytes)
            && self.loaded_observed_memory_bytes > 0
            && !self.diagnostic_digest.is_zero()
            && self.diagnostic_digest == self.computed_digest()
    }
}

#[derive(Debug, Eq, PartialEq)]
pub enum NeuronWeightFileDiagnosticErrorV1 {
    Worker(Error),
    Io(io::ErrorKind),
    InvalidFile,
    TooLarge,
    ManifestDigest,
    ChangedDuringRead,
    DigestMismatch,
}

impl From<Error> for NeuronWeightFileDiagnosticErrorV1 {
    fn from(value: Error) -> Self {
        Self::Worker(value)
    }
}

impl From<io::Error> for NeuronWeightFileDiagnosticErrorV1 {
    fn from(value: io::Error) -> Self {
        Self::Io(value.kind())
    }
}

/// Hash the actual bytes of one host-opened safetensors file, comparing them
/// with the manifest retained by an actually loaded, non-quarantined Worker.
///
/// The caller supplies a pre-opened File, never a filesystem path or claimed
/// precomputed digest. The host MUST separately authorize the file provenance,
/// forbid concurrent writers, and prove the opaque driver consumed these bytes.
pub fn inspect_loaded_neuron_weight_file_v1<D: ModelDriver>(
    worker: &InferenceWorker<D>,
    now_ms: u64,
    model_id: &str,
    weights: &mut File,
) -> Result<NeuronWeightFileDiagnosticV1, NeuronWeightFileDiagnosticErrorV1> {
    let manifest = worker.inspected_neuron_manifest(now_ms, model_id)?;
    let loaded = worker
        .models
        .get(model_id)
        .ok_or(NeuronWeightFileDiagnosticErrorV1::Worker(
            Error::ModelNotLoaded,
        ))?;
    let expected = Digest32::from_str(&manifest.weights_digest)
        .map_err(|_| NeuronWeightFileDiagnosticErrorV1::ManifestDigest)?;
    let model_digest = Digest32::from_str(&manifest.model_digest)
        .map_err(|_| NeuronWeightFileDiagnosticErrorV1::ManifestDigest)?;
    if expected.is_zero() || model_digest.is_zero() {
        return Err(NeuronWeightFileDiagnosticErrorV1::ManifestDigest);
    }
    let before = weights.metadata()?;
    if !before.is_file() || before.len() == 0 {
        return Err(NeuronWeightFileDiagnosticErrorV1::InvalidFile);
    }
    if before.len() > MAX_WEIGHT_FILE_BYTES {
        return Err(NeuronWeightFileDiagnosticErrorV1::TooLarge);
    }
    let before_modified = before.modified()?;
    let saved_cursor = weights.stream_position()?;
    weights.seek(SeekFrom::Start(0))?;
    // Digest32::of_reader has a built-in maximum+1 check and constant 32 KiB
    // scratch memory. Always restore the caller's cursor after the attempt.
    let result = Digest32::of_reader(&mut *weights, MAX_WEIGHT_FILE_BYTES);
    let after = weights.metadata();
    let restored = weights.seek(SeekFrom::Start(saved_cursor));
    let observed = result?;
    let after = after?;
    restored?;
    if !after.is_file()
        || after.len() != before.len()
        || after.modified()? != before_modified
    {
        return Err(NeuronWeightFileDiagnosticErrorV1::ChangedDuringRead);
    }
    if observed != expected {
        return Err(NeuronWeightFileDiagnosticErrorV1::DigestMismatch);
    }
    let mut diagnostic = NeuronWeightFileDiagnosticV1 {
        worker_id: worker.worker_id().to_owned(),
        worker_generation: worker.worker_generation(),
        model_id: model_id.to_owned(),
        loaded_handle_id: loaded.handle.opaque_id.clone(),
        loaded_model_manifest_digest: model_digest,
        loaded_weights_digest: observed,
        file_bytes: before.len(),
        loaded_observed_memory_bytes: loaded.handle.observed_memory_bytes,
        diagnostic_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    diagnostic.diagnostic_digest = diagnostic.computed_digest();
    if !diagnostic.validate_integrity() {
        return Err(NeuronWeightFileDiagnosticErrorV1::InvalidFile);
    }
    Ok(diagnostic)
}

#[cfg(test)]
mod tests {
    use std::io::Read;
    use std::io::Seek;
    use std::io::SeekFrom;
    use std::io::Write;

    use super::*;
    use crate::model_worker::DriverModelHandle;
    use crate::model_worker::DriverRunObservation;
    use crate::model_worker::ModelManifest;
    use crate::model_worker::ResourceGrant;
    use crate::model_worker::WorkerRequest;

    struct Driver;

    impl ModelDriver for Driver {
        fn load(&mut self, _: &ModelManifest) -> Result<DriverModelHandle, Error> {
            Ok(DriverModelHandle {
                opaque_id: "loaded.1".to_owned(),
                observed_memory_bytes: 1_024,
            })
        }

        fn run(
            &mut self,
            _: &DriverModelHandle,
            _: &WorkerRequest,
        ) -> Result<DriverRunObservation, Error> {
            Err(Error::DriverFailure("never invoked in weight-file test".into()))
        }

        fn unload(&mut self, _: DriverModelHandle) -> Result<(), Error> {
            Ok(())
        }
    }

    fn grant() -> ResourceGrant {
        ResourceGrant {
            grant_id: "grant.1".to_owned(),
            authority_epoch: 1,
            generation: 3,
            expires_at_ms: 10_000,
            revoked: false,
            maximum_models: 1,
            maximum_active_requests: 1,
            maximum_memory_bytes: 4_096,
            semantic_digest: "1".repeat(64),
        }
    }

    fn manifest(weights: &[u8]) -> ModelManifest {
        ModelManifest {
            model_id: "model.1".to_owned(),
            model_digest: "2".repeat(64),
            weights_digest: Digest32::of_bytes(weights).to_string(),
            tokenizer_digest: "4".repeat(64),
            preprocessor_digest: "5".repeat(64),
            quantization_digest: "6".repeat(64),
            runtime_digest: "7".repeat(64),
            device_digest: "8".repeat(64),
            maximum_tokens: 128,
        }
    }

    #[test]
    fn actual_file_hash_binds_current_loaded_worker_and_restores_cursor() {
        let bytes = vec![0x35_u8; 200_000];
        let mut worker = InferenceWorker::new(
            100,
            "worker.1".to_owned(),
            3,
            grant(),
            Driver,
        )
        .unwrap();
        worker.load_model(100, manifest(&bytes)).unwrap();
        let mut file = tempfile::tempfile().unwrap();
        file.write_all(&bytes).unwrap();
        file.flush().unwrap();
        file.seek(SeekFrom::Start(19)).unwrap();
        let receipt =
            inspect_loaded_neuron_weight_file_v1(&worker, 101, "model.1", &mut file).unwrap();
        assert!(receipt.validate_integrity());
        assert_eq!(receipt.authority(), AuthorityPosture::DENY_ALL);
        assert_eq!(receipt.model_id(), "model.1");
        assert_eq!(receipt.worker_generation(), 3);
        assert_eq!(receipt.file_bytes(), bytes.len() as u64);
        assert_eq!(receipt.loaded_weights_digest(), Digest32::of_bytes(&bytes));
        assert_eq!(file.stream_position().unwrap(), 19);
        let mut flipped = [0_u8; 1];
        file.read_exact(&mut flipped).unwrap();
        file.seek(SeekFrom::Start(19)).unwrap();
        file.write_all(&[flipped[0] ^ 0x7f]).unwrap();
        file.flush().unwrap();
        assert_eq!(
            inspect_loaded_neuron_weight_file_v1(&worker, 102, "model.1", &mut file),
            Err(NeuronWeightFileDiagnosticErrorV1::DigestMismatch)
        );
        assert_eq!(file.stream_position().unwrap(), 19);
    }

    #[test]
    fn rejects_missing_model_expired_grant_and_revoked_worker() {
        let bytes = vec![0x24_u8; 512];
        let mut worker =
            InferenceWorker::new(100, "worker.1".to_owned(), 3, grant(), Driver).unwrap();
        let mut file = tempfile::tempfile().unwrap();
        file.write_all(&bytes).unwrap();
        worker.load_model(100, manifest(&bytes)).unwrap();
        assert!(matches!(
            inspect_loaded_neuron_weight_file_v1(&worker, 100, "absent", &mut file),
            Err(NeuronWeightFileDiagnosticErrorV1::Worker(Error::ModelNotLoaded))
        ));
        assert!(matches!(
            inspect_loaded_neuron_weight_file_v1(&worker, 10_000, "model.1", &mut file),
            Err(NeuronWeightFileDiagnosticErrorV1::Worker(Error::GrantExpired))
        ));
        worker.grant.revoked = true;
        assert!(matches!(
            inspect_loaded_neuron_weight_file_v1(&worker, 101, "model.1", &mut file),
            Err(NeuronWeightFileDiagnosticErrorV1::Worker(Error::GrantRevoked))
        ));
    }

    #[test]
    fn refuses_nonregular_empty_and_sparse_overlimit_before_streaming() {
        let bytes = vec![0x55_u8; 128];
        let mut worker =
            InferenceWorker::new(100, "worker.1".to_owned(), 3, grant(), Driver).unwrap();
        worker.load_model(100, manifest(&bytes)).unwrap();
        let mut file = tempfile::tempfile().unwrap();
        assert_eq!(
            inspect_loaded_neuron_weight_file_v1(&worker, 101, "model.1", &mut file),
            Err(NeuronWeightFileDiagnosticErrorV1::InvalidFile)
        );
        file.set_len(MAX_WEIGHT_FILE_BYTES + 1).unwrap();
        assert_eq!(
            inspect_loaded_neuron_weight_file_v1(&worker, 101, "model.1", &mut file),
            Err(NeuronWeightFileDiagnosticErrorV1::TooLarge)
        );
        let dir = tempfile::tempdir().unwrap();
        if let Ok(mut nonregular) = File::open(dir.path()) {
            assert_eq!(
                inspect_loaded_neuron_weight_file_v1(&worker, 101, "model.1", &mut nonregular),
                Err(NeuronWeightFileDiagnosticErrorV1::InvalidFile)
            );
        }
    }
}
