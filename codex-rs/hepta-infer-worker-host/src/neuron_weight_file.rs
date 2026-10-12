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

use super::DriverModelHandle;
use super::Error;
use super::InferenceWorker;
use super::ModelDriver;
use super::ModelLoadObservation;
use super::ModelManifest;
use super::validate_manifest;

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


/// Separate physical-load contract: the Worker transfers OWNERSHIP of the same
/// preopened file that it just fully hashed. There is deliberately no fallback
/// to ModelDriver::load (which has no file input). Drivers must not reopen an
/// unrelated path or silently load a different checkpoint.
///
/// An external physical loader is still a separate trust boundary: the Worker
/// cannot attest that an opaque implementation actually used the transferred
/// descriptor, or that hostile writers did not mutate the file concurrently.
pub trait NeuronPreopenedWeightModelDriver: ModelDriver {
    fn load_from_preopened_weight_file(
        &mut self,
        manifest: &ModelManifest,
        weights: File,
    ) -> Result<DriverModelHandle, Error>;
}

const LOAD_DOMAIN: &[u8] = b"hepta.inference.worker.neuron-file-bound-load.diagnostic.v1\0";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronFileBoundModelLoadV1 {
    pub model_load: ModelLoadObservation,
    pub manifest_model_digest: Digest32,
    pub preloaded_file_digest: Digest32,
    pub file_bytes: u64,
    pub diagnostic_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl NeuronFileBoundModelLoadV1 {
    /// Self-consistency only; not a signed ArtifactLoadReceipt or CNS selection.
    #[must_use]
    pub fn computed_digest(&self) -> Digest32 {
        let mut bytes = LOAD_DOMAIN.to_vec();
        for id in [
            self.model_load.model_id.as_str(),
            self.model_load.handle_id.as_str(),
        ] {
            let raw = id.as_bytes();
            bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
            bytes.extend_from_slice(raw);
        }
        bytes.extend_from_slice(&self.model_load.worker_generation.to_be_bytes());
        bytes.extend_from_slice(&self.model_load.observed_memory_bytes.to_be_bytes());
        bytes.push(u8::from(self.model_load.terminal_observed));
        bytes.extend_from_slice(self.manifest_model_digest.as_array());
        bytes.extend_from_slice(self.preloaded_file_digest.as_array());
        bytes.extend_from_slice(&self.file_bytes.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }

    #[must_use]
    pub fn validate_integrity(&self) -> bool {
        self.authority == AuthorityPosture::DENY_ALL
            && self.model_load.terminal_observed
            && self.model_load.worker_generation > 0
            && self.model_load.observed_memory_bytes > 0
            && !self.model_load.model_id.is_empty()
            && !self.model_load.handle_id.is_empty()
            && !self.manifest_model_digest.is_zero()
            && !self.preloaded_file_digest.is_zero()
            && (1..=MAX_WEIGHT_FILE_BYTES).contains(&self.file_bytes)
            && !self.diagnostic_digest.is_zero()
            && self.diagnostic_digest == self.computed_digest()
    }
}

impl<D: NeuronPreopenedWeightModelDriver> InferenceWorker<D> {
    /// Strict opt-in physical-load path: stream-verify the entire host-opened
    /// weight file against the manifest, rewind it, and MOVE the same File to
    /// the driver for its load operation. Never call legacy path-based load.
    ///
    /// The caller must supply a trusted immutable CAS descriptor and actual
    /// trusted time/selection/Final-use fencing. Hash-before-load closes the
    /// obvious separate-file substitution but does NOT attest external code.
    pub fn load_model_from_preopened_weight_file_v1(
        &mut self,
        now_ms: u64,
        manifest: ModelManifest,
        mut weights: File,
    ) -> Result<NeuronFileBoundModelLoadV1, NeuronWeightFileDiagnosticErrorV1> {
        self.validate_current_grant(now_ms)?;
        validate_manifest(&manifest)?;
        if self.models.contains_key(&manifest.model_id) {
            return Err(Error::ModelAlreadyLoaded.into());
        }
        if self.models.len() >= self.grant.maximum_models.min(super::MAX_MODELS) {
            return Err(Error::ModelCapacity.into());
        }
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
        weights.seek(SeekFrom::Start(0))?;
        let measured = Digest32::of_reader(&mut weights, MAX_WEIGHT_FILE_BYTES)?;
        let after = weights.metadata()?;
        if !after.is_file()
            || after.len() != before.len()
            || after.modified()? != before_modified
        {
            return Err(NeuronWeightFileDiagnosticErrorV1::ChangedDuringRead);
        }
        if measured != expected {
            return Err(NeuronWeightFileDiagnosticErrorV1::DigestMismatch);
        }
        weights.seek(SeekFrom::Start(0))?;
        // File::try_clone retains the same opened inode/handle. Rehash after
        // the driver returns: a writer mutating this FD during load cannot
        // silently leave an admitted Worker model behind. The driver's only
        // loading input is STILL the original, single-moved File.
        let mut postload_file = weights.try_clone()?;
        // load_model_with owns normal quarantine, resident budget, handle
        // uniqueness and failure clean-up. The FD is moved exactly once.
        let model_load = self.load_model_with(now_ms, manifest, move |driver, selected| {
            driver.load_from_preopened_weight_file(selected, weights)
        })?;
        // The loader might have returned a live handle. Any unknown I/O or
        // changed source content after that point permanently quarantines
        // this Worker generation; never return a successful load receipt.
        let postload_check: Result<(), NeuronWeightFileDiagnosticErrorV1> = (|| {
            let after = postload_file.metadata()?;
            if !after.is_file()
                || after.len() != before.len()
                || after.modified()? != before_modified
            {
                return Err(NeuronWeightFileDiagnosticErrorV1::ChangedDuringRead);
            }
            postload_file.seek(SeekFrom::Start(0))?;
            let rehashed = Digest32::of_reader(&mut postload_file, MAX_WEIGHT_FILE_BYTES)?;
            let after_hash = postload_file.metadata()?;
            if !after_hash.is_file()
                || after_hash.len() != before.len()
                || after_hash.modified()? != before_modified
            {
                return Err(NeuronWeightFileDiagnosticErrorV1::ChangedDuringRead);
            }
            if rehashed != measured {
                return Err(NeuronWeightFileDiagnosticErrorV1::DigestMismatch);
            }
            Ok(())
        })();
        if let Err(error) = postload_check {
            self.quarantined = true;
            return Err(error);
        }
        let mut receipt = NeuronFileBoundModelLoadV1 {
            model_load,
            manifest_model_digest: model_digest,
            preloaded_file_digest: measured,
            file_bytes: before.len(),
            diagnostic_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        receipt.diagnostic_digest = receipt.computed_digest();
        Ok(receipt)
    }
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

    struct FileDriver {
        seen: std::sync::Arc<std::sync::Mutex<Vec<Digest32>>>,
        fail_fd: bool,
    }

    impl ModelDriver for FileDriver {
        fn load(&mut self, _: &ModelManifest) -> Result<DriverModelHandle, Error> {
            Err(Error::DriverFailure("legacy pathless load not permitted".into()))
        }

        fn run(
            &mut self,
            _: &DriverModelHandle,
            _: &WorkerRequest,
        ) -> Result<DriverRunObservation, Error> {
            Err(Error::DriverFailure("not a Neuron forward test".into()))
        }

        fn unload(&mut self, _: DriverModelHandle) -> Result<(), Error> {
            Ok(())
        }
    }

    impl NeuronPreopenedWeightModelDriver for FileDriver {
        fn load_from_preopened_weight_file(
            &mut self,
            _: &ModelManifest,
            mut weights: File,
        ) -> Result<DriverModelHandle, Error> {
            let actual = Digest32::of_reader(&mut weights, MAX_WEIGHT_FILE_BYTES)
                .map_err(|error| Error::DriverFailure(error.to_string()))?;
            self.seen.lock().unwrap().push(actual);
            if self.fail_fd {
                return Err(Error::DriverFailure("unknown physical loader outcome".into()));
            }
            Ok(DriverModelHandle {
                opaque_id: "file-loaded.1".into(),
                observed_memory_bytes: 1_024,
            })
        }
    }

    #[test]
    fn file_owned_load_hashes_then_transfers_identical_preopened_fd_to_driver() {
        let bytes = vec![0x61_u8; 210_000];
        let seen = std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
        let mut worker = InferenceWorker::new(
            100,
            "worker.1".into(),
            3,
            grant(),
            FileDriver {
                seen: seen.clone(),
                fail_fd: false,
            },
        )
        .unwrap();
        let mut file = tempfile::tempfile().unwrap();
        file.write_all(&bytes).unwrap();
        file.seek(SeekFrom::Start(91)).unwrap();
        let receipt = worker
            .load_model_from_preopened_weight_file_v1(101, manifest(&bytes), file)
            .unwrap();
        assert!(receipt.validate_integrity());
        assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
        assert_eq!(receipt.preloaded_file_digest, Digest32::of_bytes(&bytes));
        assert_eq!(receipt.file_bytes, bytes.len() as u64);
        assert_eq!(receipt.model_load.handle_id, "file-loaded.1");
        assert_eq!(*seen.lock().unwrap(), vec![Digest32::of_bytes(&bytes)]);
        assert!(!worker.is_quarantined());
    }

    #[test]
    fn file_owned_load_rejects_wrong_digest_before_physical_driver_and_can_retry() {
        let bytes = vec![0x43_u8; 257];
        let seen = std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
        let mut worker = InferenceWorker::new(
            100,
            "worker.1".into(),
            3,
            grant(),
            FileDriver {
                seen: seen.clone(),
                fail_fd: false,
            },
        )
        .unwrap();
        let mut corrupt = tempfile::tempfile().unwrap();
        corrupt.write_all(b"wrong-weight-file").unwrap();
        assert_eq!(
            worker.load_model_from_preopened_weight_file_v1(
                101,
                manifest(&bytes),
                corrupt,
            ),
            Err(NeuronWeightFileDiagnosticErrorV1::DigestMismatch)
        );
        assert!(seen.lock().unwrap().is_empty());
        assert!(!worker.is_quarantined());
        let mut genuine = tempfile::tempfile().unwrap();
        genuine.write_all(&bytes).unwrap();
        let approved = worker
            .load_model_from_preopened_weight_file_v1(101, manifest(&bytes), genuine)
            .unwrap();
        assert!(approved.validate_integrity());
        assert_eq!(seen.lock().unwrap().len(), 1);
    }

    #[test]
    fn file_owned_load_unknown_driver_result_quarantines_worker_generation() {
        let bytes = vec![0x62_u8; 512];
        let seen = std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
        let mut worker = InferenceWorker::new(
            100,
            "worker.1".into(),
            3,
            grant(),
            FileDriver {
                seen: seen.clone(),
                fail_fd: true,
            },
        )
        .unwrap();
        let mut genuine = tempfile::tempfile().unwrap();
        genuine.write_all(&bytes).unwrap();
        assert!(matches!(
            worker.load_model_from_preopened_weight_file_v1(
                101,
                manifest(&bytes),
                genuine,
            ),
            Err(NeuronWeightFileDiagnosticErrorV1::Worker(Error::DriverFailure(_)))
        ));
        assert_eq!(seen.lock().unwrap().len(), 1);
        assert!(worker.is_quarantined());
        let mut second = tempfile::tempfile().unwrap();
        second.write_all(&bytes).unwrap();
        assert_eq!(
            worker.load_model_from_preopened_weight_file_v1(
                102,
                manifest(&bytes),
                second,
            ),
            Err(NeuronWeightFileDiagnosticErrorV1::Worker(Error::WorkerQuarantined))
        );
    }

    struct MutatingFileDriver;

    impl ModelDriver for MutatingFileDriver {
        fn load(&mut self, _: &ModelManifest) -> Result<DriverModelHandle, Error> {
            Err(Error::DriverFailure("legacy loader is prohibited".into()))
        }

        fn run(
            &mut self,
            _: &DriverModelHandle,
            _: &WorkerRequest,
        ) -> Result<DriverRunObservation, Error> {
            Err(Error::DriverFailure("quarantined model must not run".into()))
        }

        fn unload(&mut self, _: DriverModelHandle) -> Result<(), Error> {
            Ok(())
        }
    }

    impl NeuronPreopenedWeightModelDriver for MutatingFileDriver {
        fn load_from_preopened_weight_file(
            &mut self,
            _: &ModelManifest,
            mut weights: File,
        ) -> Result<DriverModelHandle, Error> {
            // Deliberately change the SAME descriptor after the Worker has
            // verified its digest but before model load returns.
            weights.seek(SeekFrom::Start(0))
                .map_err(|error| Error::DriverFailure(error.to_string()))?;
            weights
                .write_all(b"mutated-during-driver-load")
                .map_err(|error| Error::DriverFailure(error.to_string()))?;
            weights
                .flush()
                .map_err(|error| Error::DriverFailure(error.to_string()))?;
            Ok(DriverModelHandle {
                opaque_id: "untrusted-mutator-handle".into(),
                observed_memory_bytes: 1_024,
            })
        }
    }

    #[test]
    fn postload_rehash_detects_file_mutation_and_quarantines_live_worker() {
        let bytes = vec![0x71_u8; 5_120];
        let mut worker = InferenceWorker::new(
            100,
            "worker.1".into(),
            3,
            grant(),
            MutatingFileDriver,
        )
        .unwrap();
        let mut file = tempfile::tempfile().unwrap();
        file.write_all(&bytes).unwrap();
        file.flush().unwrap();
        let result = worker.load_model_from_preopened_weight_file_v1(
            101,
            manifest(&bytes),
            file,
        );
        assert!(matches!(
            result,
            Err(NeuronWeightFileDiagnosticErrorV1::ChangedDuringRead)
                | Err(NeuronWeightFileDiagnosticErrorV1::DigestMismatch)
        ));
        assert!(worker.is_quarantined());
        // Because the driver returned a handle before postload validation,
        // this worker must be retired by its Supervisor, not silently reused
        // or counted as a cleanly unloaded allocation.
        assert!(matches!(
            worker.unload_model(102, "model.1"),
            Err(Error::WorkerQuarantined)
        ));
        let mut second = tempfile::tempfile().unwrap();
        second.write_all(&bytes).unwrap();
        assert_eq!(
            worker.load_model_from_preopened_weight_file_v1(
                102,
                manifest(&bytes),
                second,
            ),
            Err(NeuronWeightFileDiagnosticErrorV1::Worker(
                Error::WorkerQuarantined
            ))
        );
    }
}
