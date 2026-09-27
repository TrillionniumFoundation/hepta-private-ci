//! Selected-host persistent publication store and composed product facade.

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
use crate::ProductEvaluationAttemptReceiptV1;
use crate::ProductEvaluationError;
use crate::ProductQualificationPublicationRecordV1;
use crate::ProductQualificationPublicationRequestV1;
use crate::ProductQualificationPublicationStoreErrorV1;
use crate::ProductQualificationPublicationStoreV1;
use crate::ReconciledProductQualificationSinkV1;
use crate::RecordedProductEvaluationErrorV1;
use crate::RecordedProductEvaluationRunnerV1;
use crate::SignedEvaluationDecisionV1;
use crate::reconcile_product_attempt_publication_v1;

const MAGIC: &[u8; 8] = b"HQPUBF01";
const FILE_BYTES: usize = 8 + (8 * 32);
static NEXT_TEMP: AtomicU64 = AtomicU64::new(0);

struct LockedQualificationPublicationStoreV1 {
    root: PathBuf,
    host_binding: Digest32,
}

impl LockedQualificationPublicationStoreV1 {
    fn new(
        root: impl Into<PathBuf>,
        host_binding: Digest32,
    ) -> Result<Self, ProductQualificationPublicationStoreErrorV1> {
        if host_binding.is_zero() {
            return Err(ProductQualificationPublicationStoreErrorV1::Rejected);
        }
        let root = root.into();
        fs::create_dir_all(&root).map_err(map_io)?;
        let metadata = fs::symlink_metadata(&root).map_err(map_io)?;
        if !metadata.file_type().is_dir() {
            return Err(ProductQualificationPublicationStoreErrorV1::Rejected);
        }
        Ok(Self { root, host_binding })
    }

    fn path_for(&self, execution_digest: Digest32) -> PathBuf {
        self.root.join(format!("{execution_digest}.qpublication"))
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
            Err(error) => return Err(map_io(error)),
        };
        if !metadata.file_type().is_file() || metadata.len() as usize != FILE_BYTES {
            return Err(ProductQualificationPublicationStoreErrorV1::Rejected);
        }
        let mut bytes = Vec::with_capacity(FILE_BYTES);
        File::open(path)
            .map_err(map_io)?
            .read_to_end(&mut bytes)
            .map_err(map_io)?;
        decode_record(&bytes, self.host_binding, execution_digest).map(Some)
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
        let bytes = encode_record(record, self.host_binding)?;
        let ordinal = NEXT_TEMP.fetch_add(1, Ordering::Relaxed);
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
                .map_err(map_io)?;
            file.write_all(&bytes).map_err(map_io)?;
            file.sync_all().map_err(map_io)?;
            match fs::hard_link(&temp, &final_path) {
                Ok(()) => {
                    File::open(&self.root)
                        .map_err(map_io)?
                        .sync_all()
                        .map_err(map_io)?;
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
                Err(error) => Err(map_io(error)),
            }
        })();
        let _ = fs::remove_file(temp);
        result
    }
}

impl ProductQualificationPublicationStoreV1 for LockedQualificationPublicationStoreV1 {
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
    /// Concrete single-host composition: complete qualification inputs and the
    /// publication record are both durable and bound to the same selected-host
    /// identity before a success receipt is returned.
    #[allow(clippy::too_many_arguments)]
    pub fn qualify_and_persist_on_selected_host<J: DurableProductEvaluationAttemptJournalV1>(
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
        publication_root: impl AsRef<Path>,
        selected_host_binding: Digest32,
        sealed_temporal_receipt: Vec<u8>,
        sealed_qualification_context: Vec<u8>,
        sealed_signed_evidence: Vec<u8>,
        sealed_timing_evidence: Vec<u8>,
    ) -> Result<crate::ProductQualificationReceiptV1, RecordedProductEvaluationErrorV1> {
        let store = LockedQualificationPublicationStoreV1::new(
            publication_root.as_ref(),
            selected_host_binding,
        )
        .map_err(map_store_to_recorded)?;
        let mut sink = ReconciledProductQualificationSinkV1::new(store);
        self.qualify_and_persist_with_artifacts(
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
            sealed_temporal_receipt,
            sealed_qualification_context,
            sealed_signed_evidence,
            sealed_timing_evidence,
            &mut sink,
        )
    }

    /// Resume a prewrite artifact against the concrete selected-host
    /// publication store. Current evidence is re-verified by the supplied host
    /// codec; a Pending attempt is never routed through this first-write path.
    #[allow(clippy::too_many_arguments)]
    pub fn recover_selected_host_qualification<J, F>(
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
        let store = LockedQualificationPublicationStoreV1::new(
            publication_root.as_ref(),
            selected_host_binding,
        )
        .map_err(map_store_to_recorded)?;
        let mut sink = ReconciledProductQualificationSinkV1::new(store);
        self.recover_persisted_qualification(
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

    /// Resolve QualificationDecided/PublicationPending by read-verifying the
    /// persistent publication record. This operation never calls a writer.
    pub fn reconcile_selected_host_publication<J: DurableProductEvaluationAttemptJournalV1>(
        journal: &mut J,
        attempt_id: &StableId,
        publication_root: impl AsRef<Path>,
        selected_host_binding: Digest32,
    ) -> Result<ProductEvaluationAttemptReceiptV1, ProductAttemptRecoveryErrorV1> {
        let mut store = LockedQualificationPublicationStoreV1::new(
            publication_root.as_ref(),
            selected_host_binding,
        )
        .map_err(|_| ProductAttemptRecoveryErrorV1::Unresolved)?;
        reconcile_product_attempt_publication_v1(journal, &mut store, attempt_id)
    }
}

fn encode_record(
    record: &ProductQualificationPublicationRecordV1,
    host_binding: Digest32,
) -> Result<Vec<u8>, ProductQualificationPublicationStoreErrorV1> {
    record.validate()?;
    let mut bytes = Vec::with_capacity(FILE_BYTES);
    bytes.extend_from_slice(MAGIC);
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

fn decode_record(
    bytes: &[u8],
    expected_binding: Digest32,
    expected_execution: Digest32,
) -> Result<ProductQualificationPublicationRecordV1, ProductQualificationPublicationStoreErrorV1>
{
    if bytes.len() != FILE_BYTES || &bytes[..MAGIC.len()] != MAGIC {
        return Err(ProductQualificationPublicationStoreErrorV1::Rejected);
    }
    let mut cursor = MAGIC.len();
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

fn map_io(error: io::Error) -> ProductQualificationPublicationStoreErrorV1 {
    match error.kind() {
        io::ErrorKind::PermissionDenied | io::ErrorKind::WouldBlock => {
            ProductQualificationPublicationStoreErrorV1::Unavailable
        }
        _ => ProductQualificationPublicationStoreErrorV1::Indeterminate,
    }
}

fn map_store_to_recorded(
    error: ProductQualificationPublicationStoreErrorV1,
) -> RecordedProductEvaluationErrorV1 {
    let label = match error {
        ProductQualificationPublicationStoreErrorV1::Conflict => {
            "selected-host publication conflict"
        }
        ProductQualificationPublicationStoreErrorV1::Rejected => {
            "selected-host publication rejected"
        }
        ProductQualificationPublicationStoreErrorV1::Unavailable => {
            "selected-host publication unavailable"
        }
        ProductQualificationPublicationStoreErrorV1::Indeterminate => {
            "selected-host publication indeterminate"
        }
    };
    RecordedProductEvaluationErrorV1::Invariant(label)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::IndependentEvaluationDecisionV1;
    use crate::IndependentEvaluationDispositionV1;
    use codex_hepta_types::AuthorityPosture;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid id")
    }

    fn request(execution: &[u8]) -> ProductQualificationPublicationRequestV1 {
        ProductQualificationPublicationRequestV1::new(
            Digest32::of_bytes(execution),
            &SignedEvaluationDecisionV1 {
                decision: IndependentEvaluationDecisionV1 {
                    evaluation_id: id("evaluation:persistent"),
                    candidate_id: id("candidate:persistent"),
                    baseline_id: id("baseline:persistent"),
                    disposition:
                        IndependentEvaluationDispositionV1::EligibleForIndependentSelection,
                    failed_metrics: Vec::new(),
                    evidence_digest: Digest32::of_bytes(b"evidence"),
                    authority: AuthorityPosture::DENY_ALL,
                },
                trust_digest: Digest32::of_bytes(b"trust"),
                authentication_digest: Digest32::of_bytes(b"authentication"),
            },
        )
        .expect("request")
    }

    #[test]
    fn publication_survives_restart_and_is_idempotent() {
        let root = std::env::temp_dir().join(format!(
            "hepta-publication-store-{}-{}",
            std::process::id(),
            NEXT_TEMP.fetch_add(1, Ordering::Relaxed)
        ));
        let binding = Digest32::of_bytes(b"selected-host");
        let request = request(b"execution");
        let first = {
            let mut store =
                LockedQualificationPublicationStoreV1::new(&root, binding).expect("store");
            store.compare_and_publish(None, &request).expect("publish")
        };
        let second = {
            let mut store =
                LockedQualificationPublicationStoreV1::new(&root, binding).expect("reopen");
            let loaded = store
                .load(request.execution_digest)
                .expect("load")
                .expect("record");
            assert_eq!(loaded, first);
            store
                .compare_and_publish(None, &request)
                .expect("idempotent")
        };
        assert_eq!(second, first);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn conflicting_request_and_host_binding_fail_closed() {
        let root = std::env::temp_dir().join(format!(
            "hepta-publication-conflict-{}-{}",
            std::process::id(),
            NEXT_TEMP.fetch_add(1, Ordering::Relaxed)
        ));
        let binding = Digest32::of_bytes(b"selected-host");
        let request = request(b"execution");
        let mut store =
            LockedQualificationPublicationStoreV1::new(&root, binding).expect("store");
        store.compare_and_publish(None, &request).expect("publish");

        let conflict = ProductQualificationPublicationRequestV1 {
            authentication_digest: Digest32::of_bytes(b"different"),
            ..request.clone()
        };
        assert!(matches!(
            store.compare_and_publish(None, &conflict),
            Err(ProductQualificationPublicationStoreErrorV1::Conflict)
                | Err(ProductQualificationPublicationStoreErrorV1::Rejected)
        ));

        let mut wrong = LockedQualificationPublicationStoreV1::new(
            &root,
            Digest32::of_bytes(b"other-host"),
        )
        .expect("wrong store");
        assert!(matches!(
            wrong.load(request.execution_digest),
            Err(ProductQualificationPublicationStoreErrorV1::Rejected)
        ));
        let _ = fs::remove_dir_all(root);
    }
}
