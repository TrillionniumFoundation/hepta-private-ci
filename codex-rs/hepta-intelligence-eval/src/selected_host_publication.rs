//! Selected-host publication storage shared by both qualification families.
//! The namespace must be owner-protected. Local durability is not independent
//! host authentication or qualification of a network filesystem.

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

use codex_hepta_types::Digest32;

use crate::ProductEvaluationError;
use crate::ProductEvidenceSinkErrorV1;
use crate::ProductQualificationPublicationRecordV1;
use crate::ProductQualificationPublicationRequestV1;
use crate::ProductQualificationPublicationStoreErrorV1;
use crate::ProductQualificationPublicationStoreV1;
use crate::RecordedProductEvaluationErrorV1;

#[path = "selected_host_facade.rs"]
mod facade;

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
        match fs::create_dir(&root) {
            Ok(()) => {
                #[cfg(unix)]
                {
                    use std::os::unix::fs::PermissionsExt;
                    fs::set_permissions(&root, fs::Permissions::from_mode(0o700))
                        .map_err(map_io)?;
                }
                let parent = root
                    .parent()
                    .filter(|path| !path.as_os_str().is_empty())
                    .unwrap_or(Path::new("."));
                File::open(parent)
                    .and_then(|file| file.sync_all())
                    .map_err(map_io)?;
            }
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {}
            Err(error) => return Err(map_io(error)),
        }
        Self::open_existing(root, host_binding)
    }

    fn open_existing(
        root: impl Into<PathBuf>,
        host_binding: Digest32,
    ) -> Result<Self, ProductQualificationPublicationStoreErrorV1> {
        if host_binding.is_zero() {
            return Err(ProductQualificationPublicationStoreErrorV1::Rejected);
        }
        let root = root.into();
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
        let file = File::open(path).map_err(map_io)?;
        if !file.metadata().map_err(map_io)?.file_type().is_file() {
            return Err(ProductQualificationPublicationStoreErrorV1::Rejected);
        }
        let mut bytes = Vec::with_capacity(FILE_BYTES);
        file.take(FILE_BYTES as u64 + 1)
            .read_to_end(&mut bytes)
            .map_err(map_io)?;
        decode_record(&bytes, self.host_binding, execution_digest).map(Some)
    }

    fn sync_record(&self, path: &Path) -> Result<(), ProductQualificationPublicationStoreErrorV1> {
        File::open(path)
            .and_then(|file| file.sync_all())
            .map_err(map_io)?;
        File::open(&self.root)
            .and_then(|file| file.sync_all())
            .map_err(map_io)
    }

    fn write_record(
        &self,
        record: &ProductQualificationPublicationRecordV1,
    ) -> Result<ProductQualificationPublicationRecordV1, ProductQualificationPublicationStoreErrorV1>
    {
        record.validate()?;
        let final_path = self.path_for(record.request.execution_digest);
        if let Some(existing) = self.read_path(&final_path, record.request.execution_digest)? {
            if existing.request != record.request {
                return Err(ProductQualificationPublicationStoreErrorV1::Conflict);
            }
            self.sync_record(&final_path)?;
            return Ok(existing);
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
            let mut options = OpenOptions::new();
            options.write(true).create_new(true);
            #[cfg(unix)]
            {
                use std::os::unix::fs::OpenOptionsExt;
                options.mode(0o600);
            }
            let mut file = options.open(&temp).map_err(map_io)?;
            file.write_all(&bytes)
                .and_then(|()| file.sync_all())
                .map_err(map_io)?;
            let observed = match fs::hard_link(&temp, &final_path) {
                Ok(()) => record.clone(),
                Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
                    let existing = self
                        .read_path(&final_path, record.request.execution_digest)?
                        .ok_or(ProductQualificationPublicationStoreErrorV1::Indeterminate)?;
                    if existing.request != record.request {
                        return Err(ProductQualificationPublicationStoreErrorV1::Conflict);
                    }
                    existing
                }
                Err(error) => return Err(map_io(error)),
            };
            self.sync_record(&final_path)?;
            Ok(observed)
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
        let path = self.path_for(execution_digest);
        let record = self.read_path(&path, execution_digest)?;
        if record.is_some() {
            // Durability acknowledgement after a prior unknown sync must not
            // be inferred from a merely readable directory entry. No new
            // logical record is written by this barrier.
            self.sync_record(&path)?;
        }
        Ok(record)
    }

    fn compare_and_publish(
        &mut self,
        expected_record_digest: Option<Digest32>,
        request: &ProductQualificationPublicationRequestV1,
    ) -> Result<ProductQualificationPublicationRecordV1, ProductQualificationPublicationStoreErrorV1>
    {
        if let Some(existing) = self.load(request.execution_digest)? {
            if existing.request != *request
                || expected_record_digest.is_some_and(|expected| expected != existing.record_digest)
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
        let record =
            ProductQualificationPublicationRecordV1::new(request.clone(), publication_digest)?;
        self.write_record(&record)
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
) -> Result<ProductQualificationPublicationRecordV1, ProductQualificationPublicationStoreErrorV1> {
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
    let cause = match error {
        ProductQualificationPublicationStoreErrorV1::Conflict
        | ProductQualificationPublicationStoreErrorV1::Rejected => {
            ProductEvidenceSinkErrorV1::Rejected
        }
        ProductQualificationPublicationStoreErrorV1::Unavailable => {
            ProductEvidenceSinkErrorV1::Unavailable
        }
        ProductQualificationPublicationStoreErrorV1::Indeterminate => {
            ProductEvidenceSinkErrorV1::Indeterminate
        }
    };
    RecordedProductEvaluationErrorV1::Evaluation(ProductEvaluationError::Sink(cause))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::IndependentEvaluationDecisionV1;
    use crate::IndependentEvaluationDispositionV1;
    use crate::SignedEvaluationDecisionV1;
    use codex_hepta_types::AuthorityPosture;
    use codex_hepta_types::StableId;

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
            let mut store = LockedQualificationPublicationStoreV1::open_existing(&root, binding)
                .expect("reopen");
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
        let mut store = LockedQualificationPublicationStoreV1::new(&root, binding).expect("store");
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
        let mut wrong = LockedQualificationPublicationStoreV1::open_existing(
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
