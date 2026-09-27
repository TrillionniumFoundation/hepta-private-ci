//! Durable complete inputs for qualification publication and restart recovery.
//!
//! The selected host seals canonical encodings of the temporal receipt,
//! qualification context, signed evidence, and timing evidence. This module
//! commits those bytes before QualificationDecided. On restart, the host codec
//! must decode and re-verify them under the current trust store before a
//! prewrite publication can continue.

use std::error::Error as StdError;
use std::fmt;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::DurableProductEvaluationAttemptJournalV1;
use crate::FinalHoldoutCasStoreV1;
use crate::ProductEvaluationAttemptPhaseV1;
use crate::ProductEvaluationAttemptTransitionV1;
use crate::ProductEvaluationError;
use crate::ProductQualificationEvidenceSinkV1;
use crate::ProductQualificationPublicationRequestV1;
use crate::RecordedProductEvaluationErrorV1;
use crate::RecordedProductEvaluationRunnerV1;
use crate::SignedEvaluationDecisionV1;

const MAGIC: &[u8; 8] = b"HQARTF02";
const MAX_OBJECT_BYTES: usize = 8 * 1024 * 1024;
const MAX_TOTAL_BYTES: usize = 32 * 1024 * 1024;
static NEXT_TEMP: AtomicU64 = AtomicU64::new(0);

#[derive(Clone, Debug, Eq, PartialEq)]
struct QualificationArtifactPayloadV1 {
    temporal_receipt: Vec<u8>,
    qualification_context: Vec<u8>,
    signed_evidence: Vec<u8>,
    timing_evidence: Vec<u8>,
}

impl QualificationArtifactPayloadV1 {
    fn new(
        temporal_receipt: Vec<u8>,
        qualification_context: Vec<u8>,
        signed_evidence: Vec<u8>,
        timing_evidence: Vec<u8>,
    ) -> Result<Self, QualificationArtifactErrorV1> {
        let value = Self {
            temporal_receipt,
            qualification_context,
            signed_evidence,
            timing_evidence,
        };
        value.validate()?;
        Ok(value)
    }

    fn validate(&self) -> Result<(), QualificationArtifactErrorV1> {
        let objects = [
            self.temporal_receipt.as_slice(),
            self.qualification_context.as_slice(),
            self.signed_evidence.as_slice(),
            self.timing_evidence.as_slice(),
        ];
        let mut total = 0_usize;
        for object in objects {
            if object.is_empty() || object.len() > MAX_OBJECT_BYTES {
                return Err(QualificationArtifactErrorV1::Bounds);
            }
            total = total
                .checked_add(object.len())
                .ok_or(QualificationArtifactErrorV1::Bounds)?;
        }
        if total > MAX_TOTAL_BYTES {
            return Err(QualificationArtifactErrorV1::Bounds);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct QualificationArtifactSetV1 {
    attempt_id: StableId,
    plan_digest: Digest32,
    holdout_record_digest: Digest32,
    execution_digest: Digest32,
    payload: QualificationArtifactPayloadV1,
    object_digest: Digest32,
}

impl QualificationArtifactSetV1 {
    fn new(
        attempt_id: StableId,
        plan_digest: Digest32,
        holdout_record_digest: Digest32,
        execution_digest: Digest32,
        payload: QualificationArtifactPayloadV1,
    ) -> Result<Self, QualificationArtifactErrorV1> {
        if plan_digest.is_zero()
            || holdout_record_digest.is_zero()
            || execution_digest.is_zero()
        {
            return Err(QualificationArtifactErrorV1::Binding);
        }
        payload.validate()?;
        let mut value = Self {
            attempt_id,
            plan_digest,
            holdout_record_digest,
            execution_digest,
            payload,
            object_digest: Digest32::ZERO,
        };
        value.object_digest = Digest32::of_bytes(&encode_body(&value)?);
        Ok(value)
    }

    fn validate_integrity(&self) -> Result<(), QualificationArtifactErrorV1> {
        self.payload.validate()?;
        if self.plan_digest.is_zero()
            || self.holdout_record_digest.is_zero()
            || self.execution_digest.is_zero()
            || self.object_digest != Digest32::of_bytes(&encode_body(self)?)
        {
            return Err(QualificationArtifactErrorV1::Integrity);
        }
        Ok(())
    }

    fn key(&self) -> Digest32 {
        artifact_key(&self.attempt_id)
    }
}

#[derive(Debug)]
struct LockedQualificationArtifactStoreV1 {
    root: PathBuf,
    host_binding: Digest32,
}

impl LockedQualificationArtifactStoreV1 {
    fn new(
        root: impl Into<PathBuf>,
        host_binding: Digest32,
    ) -> Result<Self, QualificationArtifactErrorV1> {
        if host_binding.is_zero() {
            return Err(QualificationArtifactErrorV1::Binding);
        }
        let root = root.into();
        fs::create_dir_all(&root)?;
        let metadata = fs::symlink_metadata(&root)?;
        if !metadata.file_type().is_dir() {
            return Err(QualificationArtifactErrorV1::NotDirectory);
        }
        Ok(Self { root, host_binding })
    }

    fn path_for(&self, attempt_id: &StableId) -> PathBuf {
        self.root.join(format!("{}.qartifact", artifact_key(attempt_id)))
    }

    fn persist(
        &mut self,
        value: &QualificationArtifactSetV1,
    ) -> Result<(), QualificationArtifactErrorV1> {
        value.validate_integrity()?;
        let bytes = encode_file(value, self.host_binding)?;
        let final_path = self.path_for(&value.attempt_id);
        if final_path.exists() {
            let existing = self.read_path(&final_path, &value.attempt_id)?;
            return if existing == *value {
                Ok(())
            } else {
                Err(QualificationArtifactErrorV1::Conflict)
            };
        }

        let ordinal = NEXT_TEMP.fetch_add(1, Ordering::Relaxed);
        let temp = self.root.join(format!(
            ".{}.{}.{}.tmp",
            value.key(),
            std::process::id(),
            ordinal
        ));
        let write_result = (|| -> Result<(), QualificationArtifactErrorV1> {
            let mut file = OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&temp)?;
            file.write_all(&bytes)?;
            file.sync_all()?;
            match fs::hard_link(&temp, &final_path) {
                Ok(()) => {
                    File::open(&self.root)?.sync_all()?;
                    Ok(())
                }
                Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
                    let existing = self.read_path(&final_path, &value.attempt_id)?;
                    if existing == *value {
                        Ok(())
                    } else {
                        Err(QualificationArtifactErrorV1::Conflict)
                    }
                }
                Err(error) => Err(error.into()),
            }
        })();
        let _ = fs::remove_file(&temp);
        write_result
    }

    fn load(
        &mut self,
        attempt_id: &StableId,
    ) -> Result<QualificationArtifactSetV1, QualificationArtifactErrorV1> {
        self.read_path(&self.path_for(attempt_id), attempt_id)
    }

    fn read_path(
        &self,
        path: &Path,
        expected_attempt: &StableId,
    ) -> Result<QualificationArtifactSetV1, QualificationArtifactErrorV1> {
        let metadata = fs::symlink_metadata(path)?;
        if !metadata.file_type().is_file() {
            return Err(QualificationArtifactErrorV1::NotRegular);
        }
        if metadata.len() > (MAX_TOTAL_BYTES as u64 + 16 * 1024) {
            return Err(QualificationArtifactErrorV1::Bounds);
        }
        let mut bytes = Vec::with_capacity(metadata.len() as usize);
        File::open(path)?.read_to_end(&mut bytes)?;
        let value = decode_file(&bytes, self.host_binding)?;
        if &value.attempt_id != expected_attempt || value.key() != artifact_key(expected_attempt) {
            return Err(QualificationArtifactErrorV1::Binding);
        }
        Ok(value)
    }
}

/// Persist complete, host-sealed qualification inputs before any decision or
/// publication transition can be made durable.
///
/// The four byte vectors must be canonical, confidentiality-protected encodings
/// owned by the selected host. They are bounded, content-digested, tied to the
/// attempt/plan/holdout/execution, and create-only under `artifact_root`.
impl<S: FinalHoldoutCasStoreV1> RecordedProductEvaluationRunnerV1<S> {
    #[allow(clippy::too_many_arguments)]
    pub fn qualify_and_persist_with_artifacts<J: DurableProductEvaluationAttemptJournalV1>(
        &self,
        attempt_id: &StableId,
        temporal: &crate::ProductTemporalEvaluationReceiptV1,
        context: &crate::ProductQualificationContextV1,
        evidence: &crate::SignedEvaluationEvidenceV1,
        timing: crate::ProductTimingEvidenceV1<'_>,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
        journal: &mut J,
        artifact_root: impl AsRef<Path>,
        artifact_host_binding: Digest32,
        sealed_temporal_receipt: Vec<u8>,
        sealed_qualification_context: Vec<u8>,
        sealed_signed_evidence: Vec<u8>,
        sealed_timing_evidence: Vec<u8>,
        sink: &mut dyn ProductQualificationEvidenceSinkV1,
    ) -> Result<crate::ProductQualificationReceiptV1, RecordedProductEvaluationErrorV1> {
        let latest = journal.latest(attempt_id)?.ok_or_else(|| {
            RecordedProductEvaluationErrorV1::AttemptRequiresRecovery {
                attempt_id: attempt_id.clone(),
            }
        })?;
        latest.validate_integrity()?;
        if latest.transition.phase != ProductEvaluationAttemptPhaseV1::ComparisonSealed
            || latest.transition.plan_digest != temporal.product_plan.frozen_plan.plan_digest
            || latest.transition.holdout_record_digest != temporal.holdout.record_digest
            || latest.transition.terminal_digest != temporal.execution_digest
        {
            return Err(RecordedProductEvaluationErrorV1::AttemptRequiresRecovery {
                attempt_id: attempt_id.clone(),
            });
        }

        let payload = QualificationArtifactPayloadV1::new(
            sealed_temporal_receipt,
            sealed_qualification_context,
            sealed_signed_evidence,
            sealed_timing_evidence,
        )
        .map_err(map_artifact)?;
        let artifacts = QualificationArtifactSetV1::new(
            attempt_id.clone(),
            latest.transition.plan_digest,
            latest.transition.holdout_record_digest,
            latest.transition.terminal_digest,
            payload,
        )
        .map_err(map_artifact)?;
        let mut store =
            LockedQualificationArtifactStoreV1::new(artifact_root.as_ref(), artifact_host_binding)
                .map_err(map_artifact)?;
        store.persist(&artifacts).map_err(map_artifact)?;

        self.qualify_and_persist(
            attempt_id,
            temporal,
            context,
            evidence,
            timing,
            verifier,
            now,
            journal,
            sink,
        )
    }

    /// Rebuild a prewrite decision from the durable complete inputs.
    ///
    /// This method intentionally refuses PublicationPending: the sink may have
    /// committed and only the publication store's read-reconciliation protocol
    /// may resolve that state. For ComparisonSealed and QualificationDecided,
    /// the selected-host decoder must re-run current trust, expiry, revocation,
    /// role separation, timing and all object bindings.
    #[allow(clippy::too_many_arguments)]
    pub fn recover_persisted_qualification<J, F>(
        &self,
        journal: &mut J,
        attempt_id: &StableId,
        artifact_root: impl AsRef<Path>,
        artifact_host_binding: Digest32,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
        decode_and_verify: F,
        sink: &mut dyn ProductQualificationEvidenceSinkV1,
    ) -> Result<crate::ProductEvaluationAttemptReceiptV1, RecordedProductEvaluationErrorV1>
    where
        J: DurableProductEvaluationAttemptJournalV1,
        F: FnOnce(
            &[u8],
            &[u8],
            &[u8],
            &[u8],
            &LearningEvidenceVerifierV1,
            u64,
        ) -> Result<SignedEvaluationDecisionV1, ProductEvaluationError>,
    {
        let latest = journal.latest(attempt_id)?.ok_or_else(|| {
            RecordedProductEvaluationErrorV1::AttemptRequiresRecovery {
                attempt_id: attempt_id.clone(),
            }
        })?;
        latest.validate_integrity()?;
        if !matches!(
            latest.transition.phase,
            ProductEvaluationAttemptPhaseV1::ComparisonSealed
                | ProductEvaluationAttemptPhaseV1::QualificationDecided
        ) {
            return Err(RecordedProductEvaluationErrorV1::AttemptRequiresRecovery {
                attempt_id: attempt_id.clone(),
            });
        }

        let mut store =
            LockedQualificationArtifactStoreV1::new(artifact_root.as_ref(), artifact_host_binding)
                .map_err(map_artifact)?;
        let artifacts = store.load(attempt_id).map_err(map_artifact)?;
        artifacts.validate_integrity().map_err(map_artifact)?;
        if artifacts.plan_digest != latest.transition.plan_digest
            || artifacts.holdout_record_digest != latest.transition.holdout_record_digest
            || (latest.transition.phase == ProductEvaluationAttemptPhaseV1::ComparisonSealed
                && artifacts.execution_digest != latest.transition.terminal_digest)
        {
            return Err(RecordedProductEvaluationErrorV1::AttemptRequiresRecovery {
                attempt_id: attempt_id.clone(),
            });
        }

        let decision = decode_and_verify(
            &artifacts.payload.temporal_receipt,
            &artifacts.payload.qualification_context,
            &artifacts.payload.signed_evidence,
            &artifacts.payload.timing_evidence,
            verifier,
            now,
        )
        .map_err(RecordedProductEvaluationErrorV1::Evaluation)?;
        let request =
            ProductQualificationPublicationRequestV1::new(artifacts.execution_digest, &decision)
                .map_err(|error| {
                    RecordedProductEvaluationErrorV1::Evaluation(ProductEvaluationError::Sink(
                        error,
                    ))
                })?;

        if latest.transition.phase == ProductEvaluationAttemptPhaseV1::ComparisonSealed {
            journal.append(ProductEvaluationAttemptTransitionV1 {
                attempt_id: attempt_id.clone(),
                plan_digest: artifacts.plan_digest,
                phase: ProductEvaluationAttemptPhaseV1::QualificationDecided,
                holdout_record_digest: artifacts.holdout_record_digest,
                terminal_digest: request.request_digest,
            })?;
        } else if latest.transition.terminal_digest != request.request_digest {
            return Err(RecordedProductEvaluationErrorV1::AttemptRequiresRecovery {
                attempt_id: attempt_id.clone(),
            });
        }

        Self::resume_decided_publication(journal, attempt_id, &decision, sink)
    }
}

fn artifact_key(attempt_id: &StableId) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.learning-eval.qualification-artifact-key.v1",
        attempt_id.as_str().as_bytes(),
    ])
}

fn encode_file(
    value: &QualificationArtifactSetV1,
    host_binding: Digest32,
) -> Result<Vec<u8>, QualificationArtifactErrorV1> {
    value.validate_integrity()?;
    let body = encode_body(value)?;
    let mut bytes = Vec::with_capacity(MAGIC.len() + 32 + body.len() + 32);
    bytes.extend_from_slice(MAGIC);
    bytes.extend_from_slice(host_binding.as_array());
    bytes.extend_from_slice(&body);
    bytes.extend_from_slice(value.object_digest.as_array());
    Ok(bytes)
}

fn decode_file(
    bytes: &[u8],
    expected_binding: Digest32,
) -> Result<QualificationArtifactSetV1, QualificationArtifactErrorV1> {
    let mut input = Input::new(bytes);
    if input.take(MAGIC.len())? != MAGIC {
        return Err(QualificationArtifactErrorV1::Integrity);
    }
    if input.digest()? != expected_binding {
        return Err(QualificationArtifactErrorV1::Binding);
    }
    let attempt_id = input.id()?;
    let plan_digest = input.digest()?;
    let holdout_record_digest = input.digest()?;
    let execution_digest = input.digest()?;
    let payload = QualificationArtifactPayloadV1 {
        temporal_receipt: input.bytes()?,
        qualification_context: input.bytes()?,
        signed_evidence: input.bytes()?,
        timing_evidence: input.bytes()?,
    };
    let object_digest = input.digest()?;
    if !input.done() {
        return Err(QualificationArtifactErrorV1::Integrity);
    }
    let value = QualificationArtifactSetV1 {
        attempt_id,
        plan_digest,
        holdout_record_digest,
        execution_digest,
        payload,
        object_digest,
    };
    value.validate_integrity()?;
    Ok(value)
}

fn encode_body(
    value: &QualificationArtifactSetV1,
) -> Result<Vec<u8>, QualificationArtifactErrorV1> {
    value.payload.validate()?;
    let mut output = Vec::new();
    put_bytes(&mut output, value.attempt_id.as_str().as_bytes())?;
    output.extend_from_slice(value.plan_digest.as_array());
    output.extend_from_slice(value.holdout_record_digest.as_array());
    output.extend_from_slice(value.execution_digest.as_array());
    for object in [
        &value.payload.temporal_receipt,
        &value.payload.qualification_context,
        &value.payload.signed_evidence,
        &value.payload.timing_evidence,
    ] {
        put_bytes(&mut output, object)?;
    }
    Ok(output)
}

fn put_bytes(
    output: &mut Vec<u8>,
    value: &[u8],
) -> Result<(), QualificationArtifactErrorV1> {
    let length = u32::try_from(value.len()).map_err(|_| QualificationArtifactErrorV1::Bounds)?;
    output.extend_from_slice(&length.to_be_bytes());
    output.extend_from_slice(value);
    Ok(())
}

struct Input<'a> {
    bytes: &'a [u8],
    cursor: usize,
}

impl<'a> Input<'a> {
    fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, cursor: 0 }
    }

    fn take(&mut self, count: usize) -> Result<&'a [u8], QualificationArtifactErrorV1> {
        let end = self
            .cursor
            .checked_add(count)
            .ok_or(QualificationArtifactErrorV1::Integrity)?;
        let value = self
            .bytes
            .get(self.cursor..end)
            .ok_or(QualificationArtifactErrorV1::Integrity)?;
        self.cursor = end;
        Ok(value)
    }

    fn digest(&mut self) -> Result<Digest32, QualificationArtifactErrorV1> {
        let mut value = [0_u8; 32];
        value.copy_from_slice(self.take(32)?);
        Ok(Digest32::from_array(value))
    }

    fn bytes(&mut self) -> Result<Vec<u8>, QualificationArtifactErrorV1> {
        let mut raw = [0_u8; 4];
        raw.copy_from_slice(self.take(4)?);
        let length = u32::from_be_bytes(raw) as usize;
        if length > MAX_OBJECT_BYTES {
            return Err(QualificationArtifactErrorV1::Bounds);
        }
        Ok(self.take(length)?.to_vec())
    }

    fn id(&mut self) -> Result<StableId, QualificationArtifactErrorV1> {
        let bytes = self.bytes()?;
        let value =
            std::str::from_utf8(&bytes).map_err(|_| QualificationArtifactErrorV1::Integrity)?;
        StableId::new(value).map_err(|_| QualificationArtifactErrorV1::Integrity)
    }

    fn done(&self) -> bool {
        self.cursor == self.bytes.len()
    }
}

#[derive(Debug)]
enum QualificationArtifactErrorV1 {
    Io(io::Error),
    Bounds,
    Binding,
    Integrity,
    Conflict,
    Missing,
    NotDirectory,
    NotRegular,
}

impl fmt::Display for QualificationArtifactErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for QualificationArtifactErrorV1 {}
impl From<io::Error> for QualificationArtifactErrorV1 {
    fn from(value: io::Error) -> Self {
        if value.kind() == io::ErrorKind::NotFound {
            Self::Missing
        } else {
            Self::Io(value)
        }
    }
}

fn map_artifact(error: QualificationArtifactErrorV1) -> RecordedProductEvaluationErrorV1 {
    match error {
        QualificationArtifactErrorV1::Io(_) => {
            RecordedProductEvaluationErrorV1::Invariant("qualification artifact I/O")
        }
        QualificationArtifactErrorV1::Bounds => {
            RecordedProductEvaluationErrorV1::Invariant("qualification artifact bounds")
        }
        QualificationArtifactErrorV1::Binding => {
            RecordedProductEvaluationErrorV1::Invariant("qualification artifact binding")
        }
        QualificationArtifactErrorV1::Integrity => {
            RecordedProductEvaluationErrorV1::Invariant("qualification artifact integrity")
        }
        QualificationArtifactErrorV1::Conflict => {
            RecordedProductEvaluationErrorV1::Invariant("qualification artifact conflict")
        }
        QualificationArtifactErrorV1::Missing => {
            RecordedProductEvaluationErrorV1::Invariant("qualification artifact missing")
        }
        QualificationArtifactErrorV1::NotDirectory => {
            RecordedProductEvaluationErrorV1::Invariant("qualification artifact root")
        }
        QualificationArtifactErrorV1::NotRegular => {
            RecordedProductEvaluationErrorV1::Invariant("qualification artifact type")
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid id")
    }

    fn artifact(attempt: &str) -> QualificationArtifactSetV1 {
        QualificationArtifactSetV1::new(
            id(attempt),
            Digest32::of_bytes(b"plan"),
            Digest32::of_bytes(b"holdout"),
            Digest32::of_bytes(b"execution"),
            QualificationArtifactPayloadV1::new(
                b"sealed-receipt".to_vec(),
                b"sealed-context".to_vec(),
                b"sealed-evidence".to_vec(),
                b"qualification".to_vec(),
            )
            .expect("payload"),
        )
        .expect("artifact")
    }

    #[test]
    fn complete_inputs_survive_restart_and_reject_host_swap() {
        let root = std::env::temp_dir().join(format!(
            "hepta-qualification-artifacts-{}-{}",
            std::process::id(),
            NEXT_TEMP.fetch_add(1, Ordering::Relaxed)
        ));
        let binding = Digest32::of_bytes(b"selected-host");
        let value = artifact("attempt:artifact");
        {
            let mut store =
                LockedQualificationArtifactStoreV1::new(&root, binding).expect("store");
            store.persist(&value).expect("persist");
            store.persist(&value).expect("idempotent");
        }
        {
            let mut reopened =
                LockedQualificationArtifactStoreV1::new(&root, binding).expect("reopen");
            assert_eq!(
                reopened.load(&id("attempt:artifact")).expect("load"),
                value
            );
        }
        let mut wrong = LockedQualificationArtifactStoreV1::new(
            &root,
            Digest32::of_bytes(b"other-host"),
        )
        .expect("wrong store");
        assert!(matches!(
            wrong.load(&id("attempt:artifact")),
            Err(QualificationArtifactErrorV1::Binding)
        ));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn truncation_and_tampering_fail_closed() {
        let value = artifact("attempt:tamper");
        let binding = Digest32::of_bytes(b"host");
        let mut encoded = encode_file(&value, binding).expect("encode");
        encoded.truncate(encoded.len() - 7);
        assert!(matches!(
            decode_file(&encoded, binding),
            Err(QualificationArtifactErrorV1::Integrity)
        ));

        let mut encoded = encode_file(&value, binding).expect("encode");
        let index = encoded.len() / 2;
        encoded[index] ^= 0x01;
        assert!(matches!(
            decode_file(&encoded, binding),
            Err(QualificationArtifactErrorV1::Integrity)
                | Err(QualificationArtifactErrorV1::Binding)
        ));
    }
}
