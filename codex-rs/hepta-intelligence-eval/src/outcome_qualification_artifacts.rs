//! Complete multi-outcome qualification artifacts and selected-host recovery.
//!
//! A selected host persists the exact sealed multi-outcome receipt, qualification
//! context, signed evidence and timing evidence before `QualificationDecided`.
//! Restart recovery is host-bound, re-verifies current trust and can invoke the
//! first publication write only from the durable prewrite decision phase.

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
use crate::ProductAttemptRecoveryErrorV1;
use crate::ProductEvaluationAttemptPhaseV1;
use crate::ProductEvaluationAttemptReceiptV1;
use crate::ProductEvaluationAttemptTransitionV1;
use crate::ProductEvaluationError;
use crate::ProductQualificationEvidenceSinkV1;
use crate::ProductQualificationPublicationRecordV1;
use crate::ProductQualificationPublicationRequestV1;
use crate::ProductQualificationPublicationStoreErrorV1;
use crate::ProductQualificationPublicationStoreV1;
use crate::ReconciledProductQualificationSinkV1;
use crate::RecordedProductEvaluationErrorV1;
use crate::RecordedProductEvaluationRunnerV1;
use crate::SignedEvaluationDecisionV1;
use crate::reconcile_product_attempt_publication_v1;

const ARTIFACT_MAGIC: &[u8; 8] = b"HOARTF01";
const PUBLICATION_MAGIC: &[u8; 8] = b"HQPUBF01";
const PUBLICATION_FILE_BYTES: usize = 8 + (8 * 32);
const MAX_OBJECT_BYTES: usize = 8 * 1024 * 1024;
const MAX_TOTAL_BYTES: usize = 32 * 1024 * 1024;
static NEXT_ARTIFACT_TEMP: AtomicU64 = AtomicU64::new(0);
static NEXT_PUBLICATION_TEMP: AtomicU64 = AtomicU64::new(0);

#[derive(Clone, Debug, Eq, PartialEq)]
struct OutcomeQualificationArtifactPayloadV1 {
    outcome_receipt: Vec<u8>,
    qualification_context: Vec<u8>,
    signed_evidence: Vec<u8>,
    timing_evidence: Vec<u8>,
}

impl OutcomeQualificationArtifactPayloadV1 {
    fn new(
        outcome_receipt: Vec<u8>,
        qualification_context: Vec<u8>,
        signed_evidence: Vec<u8>,
        timing_evidence: Vec<u8>,
    ) -> Result<Self, OutcomeQualificationArtifactErrorV1> {
        let value = Self {
            outcome_receipt,
            qualification_context,
            signed_evidence,
            timing_evidence,
        };
        value.validate()?;
        Ok(value)
    }

    fn validate(&self) -> Result<(), OutcomeQualificationArtifactErrorV1> {
        let objects = [
            self.outcome_receipt.as_slice(),
            self.qualification_context.as_slice(),
            self.signed_evidence.as_slice(),
            self.timing_evidence.as_slice(),
        ];
        let mut total = 0_usize;
        for object in objects {
            if object.is_empty() || object.len() > MAX_OBJECT_BYTES {
                return Err(OutcomeQualificationArtifactErrorV1::Bounds);
            }
            total = total
                .checked_add(object.len())
                .ok_or(OutcomeQualificationArtifactErrorV1::Bounds)?;
        }
        if total > MAX_TOTAL_BYTES {
            return Err(OutcomeQualificationArtifactErrorV1::Bounds);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct OutcomeQualificationArtifactSetV1 {
    attempt_id: StableId,
    plan_digest: Digest32,
    holdout_record_digest: Digest32,
    execution_digest: Digest32,
    payload: OutcomeQualificationArtifactPayloadV1,
    object_digest: Digest32,
}

impl OutcomeQualificationArtifactSetV1 {
    fn new(
        attempt_id: StableId,
        plan_digest: Digest32,
        holdout_record_digest: Digest32,
        execution_digest: Digest32,
        payload: OutcomeQualificationArtifactPayloadV1,
    ) -> Result<Self, OutcomeQualificationArtifactErrorV1> {
        if plan_digest.is_zero()
            || holdout_record_digest.is_zero()
            || execution_digest.is_zero()
        {
            return Err(OutcomeQualificationArtifactErrorV1::Binding);
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
        value.object_digest = Digest32::of_bytes(&encode_artifact_body(&value)?);
        Ok(value)
    }

    fn validate_integrity(&self) -> Result<(), OutcomeQualificationArtifactErrorV1> {
        self.payload.validate()?;
        if self.plan_digest.is_zero()
            || self.holdout_record_digest.is_zero()
            || self.execution_digest.is_zero()
            || self.object_digest != Digest32::of_bytes(&encode_artifact_body(self)?)
        {
            return Err(OutcomeQualificationArtifactErrorV1::Integrity);
        }
        Ok(())
    }
}

struct LockedOutcomeQualificationArtifactStoreV1 {
    root: PathBuf,
    host_binding: Digest32,
}

impl LockedOutcomeQualificationArtifactStoreV1 {
    fn new(
        root: impl Into<PathBuf>,
        host_binding: Digest32,
    ) -> Result<Self, OutcomeQualificationArtifactErrorV1> {
        if host_binding.is_zero() {
            return Err(OutcomeQualificationArtifactErrorV1::Binding);
        }
        let root = root.into();
        fs::create_dir_all(&root)?;
        let metadata = fs::symlink_metadata(&root)?;
        if !metadata.file_type().is_dir() {
            return Err(OutcomeQualificationArtifactErrorV1::NotDirectory);
        }
        Ok(Self { root, host_binding })
    }

    fn path_for(&self, attempt_id: &StableId) -> PathBuf {
        self.root.join(format!(
            "{}.oqartifact",
            outcome_artifact_key(attempt_id)
        ))
    }

    fn persist(
        &mut self,
        value: &OutcomeQualificationArtifactSetV1,
    ) -> Result<(), OutcomeQualificationArtifactErrorV1> {
        value.validate_integrity()?;
        let bytes = encode_artifact_file(value, self.host_binding)?;
        let final_path = self.path_for(&value.attempt_id);
        if final_path.exists() {
            let existing = self.read_path(&final_path, &value.attempt_id)?;
            return if existing == *value {
                Ok(())
            } else {
                Err(OutcomeQualificationArtifactErrorV1::Conflict)
            };
        }

        let ordinal = NEXT_ARTIFACT_TEMP.fetch_add(1, Ordering::Relaxed);
        let temp = self.root.join(format!(
            ".{}.{}.{}.tmp",
            outcome_artifact_key(&value.attempt_id),
            std::process::id(),
            ordinal
        ));
        let result = (|| -> Result<(), OutcomeQualificationArtifactErrorV1> {
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
                        Err(OutcomeQualificationArtifactErrorV1::Conflict)
                    }
                }
                Err(error) => Err(error.into()),
            }
        })();
        let _ = fs::remove_file(&temp);
        result
    }

    fn load(
        &mut self,
        attempt_id: &StableId,
    ) -> Result<OutcomeQualificationArtifactSetV1, OutcomeQualificationArtifactErrorV1> {
        self.read_path(&self.path_for(attempt_id), attempt_id)
    }

    fn read_path(
        &self,
        path: &Path,
        expected_attempt: &StableId,
    ) -> Result<OutcomeQualificationArtifactSetV1, OutcomeQualificationArtifactErrorV1> {
        let metadata = fs::symlink_metadata(path)?;
        if !metadata.file_type().is_file() {
            return Err(OutcomeQualificationArtifactErrorV1::NotRegular);
        }
        if metadata.len() > (MAX_TOTAL_BYTES as u64 + 16 * 1024) {
            return Err(OutcomeQualificationArtifactErrorV1::Bounds);
        }
        let mut bytes = Vec::with_capacity(metadata.len() as usize);
        File::open(path)?.read_to_end(&mut bytes)?;
        let value = decode_artifact_file(&bytes, self.host_binding)?;
        if &value.attempt_id != expected_attempt {
            return Err(OutcomeQualificationArtifactErrorV1::Binding);
        }
        Ok(value)
    }
}

struct LockedOutcomeQualificationPublicationStoreV1 {
    root: PathBuf,
    host_binding: Digest32,
}

impl LockedOutcomeQualificationPublicationStoreV1 {
    fn new(
        root: impl Into<PathBuf>,
        host_binding: Digest32,
    ) -> Result<Self, ProductQualificationPublicationStoreErrorV1> {
        if host_binding.is_zero() {
            return Err(ProductQualificationPublicationStoreErrorV1::Rejected);
        }
        let root = root.into();
        fs::create_dir_all(&root).map_err(map_publication_io)?;
        let metadata = fs::symlink_metadata(&root).map_err(map_publication_io)?;
        if !metadata.file_type().is_dir() {
            return Err(ProductQualificationPublicationStoreErrorV1::Rejected);
        }
        Ok(Self { root, host_binding })
    }

    fn path_for(&self, execution_digest: Digest32) -> PathBuf {
        self.root
            .join(format!("{execution_digest}.qpublication"))
    }

    fn read_path(
        &self,
        path: &Path,
        execution_digest: Digest32,
    ) -> Result<
        Option<ProductQualificationPublicationRecordV1>,
        ProductQualificationPublicationStoreErrorV1,
    > {
        let metadata = match fs::symlink_metadata(path) {
            Ok(value) => value,
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(map_publication_io(error)),
        };
        if !metadata.file_type().is_file()
            || metadata.len() as usize != PUBLICATION_FILE_BYTES
        {
            return Err(ProductQualificationPublicationStoreErrorV1::Rejected);
        }
        let mut bytes = Vec::with_capacity(PUBLICATION_FILE_BYTES);
        File::open(path)
            .map_err(map_publication_io)?
            .read_to_end(&mut bytes)
            .map_err(map_publication_io)?;
        decode_publication_record(&bytes, self.host_binding, execution_digest).map(Some)
    }

    fn write_record(
        &self,
        record: &ProductQualificationPublicationRecordV1,
    ) -> Result<
        ProductQualificationPublicationRecordV1,
        ProductQualificationPublicationStoreErrorV1,
    > {
        record.validate()?;
        let final_path = self.path_for(record.request.execution_digest);
        if let Some(existing) = self.read_path(&final_path, record.request.execution_digest)? {
            return if existing.request == record.request {
                Ok(existing)
            } else {
                Err(ProductQualificationPublicationStoreErrorV1::Conflict)
            };
        }
        let bytes = encode_publication_record(record, self.host_binding)?;
        let ordinal = NEXT_PUBLICATION_TEMP.fetch_add(1, Ordering::Relaxed);
        let temp = self.root.join(format!(
            ".{}.{}.{}.tmp",
            record.request.execution_digest,
            std::process::id(),
            ordinal
        ));
        let result = (|| {
            let mut file = OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&temp)
                .map_err(map_publication_io)?;
            file.write_all(&bytes).map_err(map_publication_io)?;
            file.sync_all().map_err(map_publication_io)?;
            match fs::hard_link(&temp, &final_path) {
                Ok(()) => {
                    File::open(&self.root)
                        .map_err(map_publication_io)?
                        .sync_all()
                        .map_err(map_publication_io)?;
                    Ok(record.clone())
                }
                Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
                    let existing = self
                        .read_path(&final_path, record.request.execution_digest)?
                        .ok_or(ProductQualificationPublicationStoreErrorV1::Indeterminate)?;
                    if existing.request == record.request {
                        Ok(existing)
                    } else {
                        Err(ProductQualificationPublicationStoreErrorV1::Conflict)
                    }
                }
                Err(error) => Err(map_publication_io(error)),
            }
        })();
        let _ = fs::remove_file(temp);
        result
    }
}

impl ProductQualificationPublicationStoreV1 for LockedOutcomeQualificationPublicationStoreV1 {
    fn load(
        &mut self,
        execution_digest: Digest32,
    ) -> Result<
        Option<ProductQualificationPublicationRecordV1>,
        ProductQualificationPublicationStoreErrorV1,
    > {
        if execution_digest.is_zero() {
            return Err(ProductQualificationPublicationStoreErrorV1::Rejected);
        }
        self.read_path(&self.path_for(execution_digest), execution_digest)
    }

    fn compare_and_publish(
        &mut self,
        expected_record_digest: Option<Digest32>,
        request: &ProductQualificationPublicationRequestV1,
    ) -> Result<
        ProductQualificationPublicationRecordV1,
        ProductQualificationPublicationStoreErrorV1,
    > {
        if let Some(existing) = self.load(request.execution_digest)? {
            if existing.request != *request
                || expected_record_digest
                    .is_some_and(|expected| expected != existing.record_digest)
            {
                return Err(ProductQualificationPublicationStoreErrorV1::Conflict);
            }
            return Ok(existing);
        }
        if expected_record_digest.is_some() {
            return Err(ProductQualificationPublicationStoreErrorV1::Conflict);
        }
        let publication_digest = Digest32::of_parts(&[
            b"hepta.learning-eval.selected-host-publication.v1",
            self.host_binding.as_array(),
            request.request_digest.as_array(),
        ]);
        let record = ProductQualificationPublicationRecordV1::new(
            request.clone(),
            publication_digest,
        )?;
        self.write_record(&record)
    }
}

impl<S: FinalHoldoutCasStoreV1> RecordedProductEvaluationRunnerV1<S> {
    /// Persist complete multi-outcome inputs before making the decision durable.
    #[allow(clippy::too_many_arguments)]
    pub fn qualify_outcomes_and_persist_with_artifacts<
        J: DurableProductEvaluationAttemptJournalV1,
    >(
        &self,
        attempt_id: &StableId,
        temporal: &crate::ProductOutcomeEvaluationReceiptV1,
        context: &crate::ProductQualificationContextV1,
        evidence: &crate::SignedEvaluationEvidenceV1,
        timing: crate::ProductTimingEvidenceV1<'_>,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
        journal: &mut J,
        artifact_root: impl AsRef<Path>,
        artifact_host_binding: Digest32,
        sealed_outcome_receipt: Vec<u8>,
        sealed_qualification_context: Vec<u8>,
        sealed_signed_evidence: Vec<u8>,
        sealed_timing_evidence: Vec<u8>,
        sink: &mut dyn ProductQualificationEvidenceSinkV1,
    ) -> Result<crate::ProductOutcomeQualificationReceiptV1, RecordedProductEvaluationErrorV1> {
        let latest = journal.latest(attempt_id)?.ok_or_else(|| {
            RecordedProductEvaluationErrorV1::AttemptRequiresRecovery {
                attempt_id: attempt_id.clone(),
            }
        })?;
        latest.validate_integrity()?;
        if latest.transition.phase != ProductEvaluationAttemptPhaseV1::ComparisonSealed
            || latest.transition.plan_digest
                != temporal.carrier.product_plan.frozen_plan.plan_digest
            || latest.transition.holdout_record_digest
                != temporal.carrier.holdout.record_digest
            || latest.transition.terminal_digest != temporal.execution_digest()
        {
            return Err(RecordedProductEvaluationErrorV1::AttemptRequiresRecovery {
                attempt_id: attempt_id.clone(),
            });
        }

        let payload = OutcomeQualificationArtifactPayloadV1::new(
            sealed_outcome_receipt,
            sealed_qualification_context,
            sealed_signed_evidence,
            sealed_timing_evidence,
        )
        .map_err(map_artifact)?;
        let artifacts = OutcomeQualificationArtifactSetV1::new(
            attempt_id.clone(),
            latest.transition.plan_digest,
            latest.transition.holdout_record_digest,
            latest.transition.terminal_digest,
            payload,
        )
        .map_err(map_artifact)?;
        let mut store = LockedOutcomeQualificationArtifactStoreV1::new(
            artifact_root.as_ref(),
            artifact_host_binding,
        )
        .map_err(map_artifact)?;
        store.persist(&artifacts).map_err(map_artifact)?;

        self.qualify_outcomes_and_persist(
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

    /// Recover a complete host-sealed multi-outcome decision under current trust.
    #[allow(clippy::too_many_arguments)]
    pub fn recover_persisted_outcome_qualification<J, F>(
        &self,
        journal: &mut J,
        attempt_id: &StableId,
        artifact_root: impl AsRef<Path>,
        artifact_host_binding: Digest32,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
        decode_and_verify: F,
        sink: &mut dyn ProductQualificationEvidenceSinkV1,
    ) -> Result<ProductEvaluationAttemptReceiptV1, RecordedProductEvaluationErrorV1>
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

        let mut store = LockedOutcomeQualificationArtifactStoreV1::new(
            artifact_root.as_ref(),
            artifact_host_binding,
        )
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
            &artifacts.payload.outcome_receipt,
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

    /// Concrete selected-host multi-outcome composition.
    #[allow(clippy::too_many_arguments)]
    pub fn qualify_outcomes_and_persist_on_selected_host<
        J: DurableProductEvaluationAttemptJournalV1,
    >(
        &self,
        attempt_id: &StableId,
        temporal: &crate::ProductOutcomeEvaluationReceiptV1,
        context: &crate::ProductQualificationContextV1,
        evidence: &crate::SignedEvaluationEvidenceV1,
        timing: crate::ProductTimingEvidenceV1<'_>,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
        journal: &mut J,
        artifact_root: impl AsRef<Path>,
        publication_root: impl AsRef<Path>,
        selected_host_binding: Digest32,
        sealed_outcome_receipt: Vec<u8>,
        sealed_qualification_context: Vec<u8>,
        sealed_signed_evidence: Vec<u8>,
        sealed_timing_evidence: Vec<u8>,
    ) -> Result<crate::ProductOutcomeQualificationReceiptV1, RecordedProductEvaluationErrorV1> {
        let store = LockedOutcomeQualificationPublicationStoreV1::new(
            publication_root.as_ref(),
            selected_host_binding,
        )
        .map_err(map_publication_to_recorded)?;
        let mut sink = ReconciledProductQualificationSinkV1::new(store);
        self.qualify_outcomes_and_persist_with_artifacts(
            attempt_id,
            temporal,
            context,
            evidence,
            timing,
            verifier,
            now,
            journal,
            artifact_root,
            selected_host_binding,
            sealed_outcome_receipt,
            sealed_qualification_context,
            sealed_signed_evidence,
            sealed_timing_evidence,
            &mut sink,
        )
    }

    /// Restart a prewrite selected-host multi-outcome qualification.
    #[allow(clippy::too_many_arguments)]
    pub fn recover_selected_host_outcome_qualification<J, F>(
        &self,
        journal: &mut J,
        attempt_id: &StableId,
        artifact_root: impl AsRef<Path>,
        publication_root: impl AsRef<Path>,
        selected_host_binding: Digest32,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
        decode_and_verify: F,
    ) -> Result<ProductEvaluationAttemptReceiptV1, RecordedProductEvaluationErrorV1>
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
        let store = LockedOutcomeQualificationPublicationStoreV1::new(
            publication_root.as_ref(),
            selected_host_binding,
        )
        .map_err(map_publication_to_recorded)?;
        let mut sink = ReconciledProductQualificationSinkV1::new(store);
        self.recover_persisted_outcome_qualification(
            journal,
            attempt_id,
            artifact_root,
            selected_host_binding,
            verifier,
            now,
            decode_and_verify,
            &mut sink,
        )
    }

    /// Reconcile an already committed multi-outcome publication without writing.
    pub fn reconcile_selected_host_outcome_publication<
        J: DurableProductEvaluationAttemptJournalV1,
    >(
        journal: &mut J,
        attempt_id: &StableId,
        publication_root: impl AsRef<Path>,
        selected_host_binding: Digest32,
    ) -> Result<ProductEvaluationAttemptReceiptV1, ProductAttemptRecoveryErrorV1> {
        let mut store = LockedOutcomeQualificationPublicationStoreV1::new(
            publication_root.as_ref(),
            selected_host_binding,
        )
        .map_err(|_| ProductAttemptRecoveryErrorV1::Unresolved)?;
        reconcile_product_attempt_publication_v1(journal, &mut store, attempt_id)
    }
}

fn outcome_artifact_key(attempt_id: &StableId) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.learning-eval.outcome-qualification-artifact-key.v1",
        attempt_id.as_str().as_bytes(),
    ])
}

fn encode_artifact_file(
    value: &OutcomeQualificationArtifactSetV1,
    host_binding: Digest32,
) -> Result<Vec<u8>, OutcomeQualificationArtifactErrorV1> {
    value.validate_integrity()?;
    let body = encode_artifact_body(value)?;
    let mut bytes = Vec::with_capacity(ARTIFACT_MAGIC.len() + 32 + body.len() + 32);
    bytes.extend_from_slice(ARTIFACT_MAGIC);
    bytes.extend_from_slice(host_binding.as_array());
    bytes.extend_from_slice(&body);
    bytes.extend_from_slice(value.object_digest.as_array());
    Ok(bytes)
}

fn decode_artifact_file(
    bytes: &[u8],
    expected_binding: Digest32,
) -> Result<OutcomeQualificationArtifactSetV1, OutcomeQualificationArtifactErrorV1> {
    let mut input = ArtifactInput::new(bytes);
    if input.take(ARTIFACT_MAGIC.len())? != ARTIFACT_MAGIC {
        return Err(OutcomeQualificationArtifactErrorV1::Integrity);
    }
    if input.digest()? != expected_binding {
        return Err(OutcomeQualificationArtifactErrorV1::Binding);
    }
    let attempt_id = input.id()?;
    let plan_digest = input.digest()?;
    let holdout_record_digest = input.digest()?;
    let execution_digest = input.digest()?;
    let payload = OutcomeQualificationArtifactPayloadV1 {
        outcome_receipt: input.bytes()?,
        qualification_context: input.bytes()?,
        signed_evidence: input.bytes()?,
        timing_evidence: input.bytes()?,
    };
    let object_digest = input.digest()?;
    if !input.done() {
        return Err(OutcomeQualificationArtifactErrorV1::Integrity);
    }
    let value = OutcomeQualificationArtifactSetV1 {
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

fn encode_artifact_body(
    value: &OutcomeQualificationArtifactSetV1,
) -> Result<Vec<u8>, OutcomeQualificationArtifactErrorV1> {
    value.payload.validate()?;
    let mut output = Vec::new();
    put_artifact_bytes(&mut output, value.attempt_id.as_str().as_bytes())?;
    output.extend_from_slice(value.plan_digest.as_array());
    output.extend_from_slice(value.holdout_record_digest.as_array());
    output.extend_from_slice(value.execution_digest.as_array());
    for object in [
        &value.payload.outcome_receipt,
        &value.payload.qualification_context,
        &value.payload.signed_evidence,
        &value.payload.timing_evidence,
    ] {
        put_artifact_bytes(&mut output, object)?;
    }
    Ok(output)
}

fn put_artifact_bytes(
    output: &mut Vec<u8>,
    value: &[u8],
) -> Result<(), OutcomeQualificationArtifactErrorV1> {
    let length =
        u32::try_from(value.len()).map_err(|_| OutcomeQualificationArtifactErrorV1::Bounds)?;
    output.extend_from_slice(&length.to_be_bytes());
    output.extend_from_slice(value);
    Ok(())
}

struct ArtifactInput<'a> {
    bytes: &'a [u8],
    cursor: usize,
}

impl<'a> ArtifactInput<'a> {
    fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, cursor: 0 }
    }

    fn take(
        &mut self,
        count: usize,
    ) -> Result<&'a [u8], OutcomeQualificationArtifactErrorV1> {
        let end = self
            .cursor
            .checked_add(count)
            .ok_or(OutcomeQualificationArtifactErrorV1::Integrity)?;
        let value = self
            .bytes
            .get(self.cursor..end)
            .ok_or(OutcomeQualificationArtifactErrorV1::Integrity)?;
        self.cursor = end;
        Ok(value)
    }

    fn digest(&mut self) -> Result<Digest32, OutcomeQualificationArtifactErrorV1> {
        let mut value = [0_u8; 32];
        value.copy_from_slice(self.take(32)?);
        Ok(Digest32::from_array(value))
    }

    fn bytes(&mut self) -> Result<Vec<u8>, OutcomeQualificationArtifactErrorV1> {
        let mut raw = [0_u8; 4];
        raw.copy_from_slice(self.take(4)?);
        let length = u32::from_be_bytes(raw) as usize;
        if length > MAX_OBJECT_BYTES {
            return Err(OutcomeQualificationArtifactErrorV1::Bounds);
        }
        Ok(self.take(length)?.to_vec())
    }

    fn id(&mut self) -> Result<StableId, OutcomeQualificationArtifactErrorV1> {
        let bytes = self.bytes()?;
        let value = std::str::from_utf8(&bytes)
            .map_err(|_| OutcomeQualificationArtifactErrorV1::Integrity)?;
        StableId::new(value).map_err(|_| OutcomeQualificationArtifactErrorV1::Integrity)
    }

    fn done(&self) -> bool {
        self.cursor == self.bytes.len()
    }
}

fn encode_publication_record(
    record: &ProductQualificationPublicationRecordV1,
    host_binding: Digest32,
) -> Result<Vec<u8>, ProductQualificationPublicationStoreErrorV1> {
    record.validate()?;
    let mut bytes = Vec::with_capacity(PUBLICATION_FILE_BYTES);
    bytes.extend_from_slice(PUBLICATION_MAGIC);
    for digest in [
        host_binding,
        record.request.execution_digest,
        record.request.decision_evidence_digest,
        record.request.trust_digest,
        record.request.authentication_digest,
        record.request.request_digest,
        record.publication_digest,
        record.record_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(bytes)
}

fn decode_publication_record(
    bytes: &[u8],
    expected_binding: Digest32,
    expected_execution: Digest32,
) -> Result<ProductQualificationPublicationRecordV1, ProductQualificationPublicationStoreErrorV1>
{
    if bytes.len() != PUBLICATION_FILE_BYTES
        || &bytes[..PUBLICATION_MAGIC.len()] != PUBLICATION_MAGIC
    {
        return Err(ProductQualificationPublicationStoreErrorV1::Rejected);
    }
    let mut cursor = PUBLICATION_MAGIC.len();
    let mut next = || {
        let mut value = [0_u8; 32];
        value.copy_from_slice(&bytes[cursor..cursor + 32]);
        cursor += 32;
        Digest32::from_array(value)
    };
    let binding = next();
    let execution_digest = next();
    let decision_evidence_digest = next();
    let trust_digest = next();
    let authentication_digest = next();
    let request_digest = next();
    let publication_digest = next();
    let record_digest = next();
    if binding != expected_binding || execution_digest != expected_execution {
        return Err(ProductQualificationPublicationStoreErrorV1::Rejected);
    }
    let record = ProductQualificationPublicationRecordV1 {
        request: ProductQualificationPublicationRequestV1 {
            execution_digest,
            decision_evidence_digest,
            trust_digest,
            authentication_digest,
            request_digest,
        },
        publication_digest,
        record_digest,
    };
    record.validate()?;
    Ok(record)
}

#[derive(Debug)]
enum OutcomeQualificationArtifactErrorV1 {
    Io(io::Error),
    Bounds,
    Binding,
    Integrity,
    Conflict,
    Missing,
    NotDirectory,
    NotRegular,
}

impl fmt::Display for OutcomeQualificationArtifactErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for OutcomeQualificationArtifactErrorV1 {}

impl From<io::Error> for OutcomeQualificationArtifactErrorV1 {
    fn from(value: io::Error) -> Self {
        if value.kind() == io::ErrorKind::NotFound {
            Self::Missing
        } else {
            Self::Io(value)
        }
    }
}

fn map_artifact(error: OutcomeQualificationArtifactErrorV1) -> RecordedProductEvaluationErrorV1 {
    match error {
        OutcomeQualificationArtifactErrorV1::Io(_) => {
            RecordedProductEvaluationErrorV1::Invariant("outcome qualification artifact I/O")
        }
        OutcomeQualificationArtifactErrorV1::Bounds => {
            RecordedProductEvaluationErrorV1::Invariant("outcome qualification artifact bounds")
        }
        OutcomeQualificationArtifactErrorV1::Binding => {
            RecordedProductEvaluationErrorV1::Invariant("outcome qualification artifact binding")
        }
        OutcomeQualificationArtifactErrorV1::Integrity => {
            RecordedProductEvaluationErrorV1::Invariant("outcome qualification artifact integrity")
        }
        OutcomeQualificationArtifactErrorV1::Conflict => {
            RecordedProductEvaluationErrorV1::Invariant("outcome qualification artifact conflict")
        }
        OutcomeQualificationArtifactErrorV1::Missing => {
            RecordedProductEvaluationErrorV1::Invariant("outcome qualification artifact missing")
        }
        OutcomeQualificationArtifactErrorV1::NotDirectory => {
            RecordedProductEvaluationErrorV1::Invariant("outcome qualification artifact root")
        }
        OutcomeQualificationArtifactErrorV1::NotRegular => {
            RecordedProductEvaluationErrorV1::Invariant("outcome qualification artifact type")
        }
    }
}

fn map_publication_io(error: io::Error) -> ProductQualificationPublicationStoreErrorV1 {
    match error.kind() {
        io::ErrorKind::PermissionDenied | io::ErrorKind::WouldBlock => {
            ProductQualificationPublicationStoreErrorV1::Unavailable
        }
        _ => ProductQualificationPublicationStoreErrorV1::Indeterminate,
    }
}

fn map_publication_to_recorded(
    error: ProductQualificationPublicationStoreErrorV1,
) -> RecordedProductEvaluationErrorV1 {
    let label = match error {
        ProductQualificationPublicationStoreErrorV1::Conflict => {
            "selected-host outcome publication conflict"
        }
        ProductQualificationPublicationStoreErrorV1::Rejected => {
            "selected-host outcome publication rejected"
        }
        ProductQualificationPublicationStoreErrorV1::Unavailable => {
            "selected-host outcome publication unavailable"
        }
        ProductQualificationPublicationStoreErrorV1::Indeterminate => {
            "selected-host outcome publication indeterminate"
        }
    };
    RecordedProductEvaluationErrorV1::Invariant(label)
}
