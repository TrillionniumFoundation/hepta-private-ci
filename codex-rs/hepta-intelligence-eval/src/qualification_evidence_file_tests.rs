use super::*;
use crate::IndependentEvaluationDecisionV1;
use crate::IndependentEvaluationDispositionV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

static NEXT: AtomicU64 = AtomicU64::new(0);
struct TestDir(PathBuf);
impl TestDir {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "hepta-product-evidence-{}-{}",
            std::process::id(),
            NEXT.fetch_add(/*val*/ 1, Ordering::Relaxed)
        ));
        if let Err(error) = fs::create_dir(&path) {
            panic!("create fixture directory: {error}");
        }
        match path.canonicalize() {
            Ok(path) => Self(path),
            Err(error) => panic!("canonical fixture directory: {error}"),
        }
    }
    fn path(&self) -> PathBuf {
        self.0.join("qualification.evidence")
    }
}
impl Drop for TestDir {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn id(value: &str) -> StableId {
    match StableId::new(value) {
        Ok(value) => value,
        Err(error) => panic!("invalid fixture id {value}: {error}"),
    }
}
fn decision() -> SignedEvaluationDecisionV1 {
    SignedEvaluationDecisionV1 {
        decision: IndependentEvaluationDecisionV1 {
            evaluation_id: id("evaluation"),
            candidate_id: id("candidate"),
            baseline_id: id("baseline"),
            disposition: IndependentEvaluationDispositionV1::Ineligible,
            failed_metrics: vec![id("quality"), id("retention")],
            evidence_digest: digest("full evidence"),
            authority: AuthorityPosture::DENY_ALL,
        },
        trust_digest: digest("independent trust"),
        authentication_digest: digest("verified signatures"),
    }
}
fn with_sync_fault<T>(path: &Path, action: impl FnOnce() -> T) -> T {
    struct Reset;
    impl Drop for Reset {
        fn drop(&mut self) {
            SYNC_FAULT.with(|fault| *fault.borrow_mut() = None);
        }
    }
    SYNC_FAULT.with(|fault| *fault.borrow_mut() = Some(path.to_owned()));
    let _reset = Reset;
    action()
}

#[test]
fn full_decision_roundtrip_exact_retry_and_pinned_bootstrap_read() {
    let dir = TestDir::new();
    let path = dir.path();
    let expected = decision();
    let execution = digest("execution");
    let mut sink = FileProductQualificationEvidenceSinkV1::new(&path).unwrap();
    let receipt = sink.persist(execution, &expected).unwrap();
    assert_eq!(receipt, Digest32::of_bytes(&fs::read(&path).unwrap()));
    assert_eq!(sink.persist(execution, &expected).unwrap(), receipt);
    drop(sink);
    let record = read_product_qualification_evidence_v1(&path, receipt).unwrap();
    assert_eq!(
        record,
        ProductQualificationEvidenceRecordV1 {
            execution_digest: execution,
            decision: expected.clone(),
            publication_digest: receipt,
        }
    );
    assert_eq!(
        FileProductQualificationEvidenceSinkV1::new(&path)
            .unwrap()
            .persist(execution, &expected)
            .unwrap(),
        receipt
    );
}

#[test]
fn complete_readable_bytes_after_failed_sync_are_not_success_until_real_retry() {
    let dir = TestDir::new();
    let path = dir.path();
    let mut sink = FileProductQualificationEvidenceSinkV1::new(&path).unwrap();
    let expected = decision();
    let execution = digest("execution");
    assert_eq!(
        with_sync_fault(&path, || sink.persist(execution, &expected)),
        Err(ProductEvidenceSinkErrorV1::Indeterminate)
    );
    let bytes = fs::read(&path).unwrap();
    let checksum = Digest32::of_bytes(&bytes);
    assert_eq!(
        with_sync_fault(&path, || sink.persist(execution, &expected)),
        Err(ProductEvidenceSinkErrorV1::Indeterminate)
    );
    assert_eq!(
        with_sync_fault(&path, || read_product_qualification_evidence_v1(
            &path, checksum
        )),
        Err(ProductEvidenceSinkErrorV1::Indeterminate)
    );
    assert_eq!(fs::read(&path).unwrap(), bytes);
    assert_eq!(sink.persist(execution, &expected).unwrap(), checksum);
    assert_eq!(
        read_product_qualification_evidence_v1(&path, checksum)
            .unwrap()
            .decision(),
        &expected
    );
}

#[test]
fn changed_full_decision_or_execution_never_overwrites_existing_record() {
    for mode in [
        "execution",
        "trust",
        "authentication",
        "disposition",
        "metric",
        "candidate",
        "evidence",
    ] {
        let dir = TestDir::new();
        let path = dir.path();
        let mut sink = FileProductQualificationEvidenceSinkV1::new(&path).unwrap();
        let mut expected = decision();
        let mut execution = digest("execution");
        let receipt = sink.persist(execution, &expected).unwrap();
        let original = fs::read(&path).unwrap();
        match mode {
            "execution" => execution = digest("changed"),
            "trust" => expected.trust_digest = digest("changed"),
            "authentication" => expected.authentication_digest = digest("changed"),
            "disposition" => {
                expected.decision.disposition =
                    IndependentEvaluationDispositionV1::InsufficientEvidence
            }
            "metric" => expected.decision.failed_metrics.pop().map(|_| ()).unwrap(),
            "candidate" => expected.decision.candidate_id = StableId::new("other").unwrap(),
            "evidence" => expected.decision.evidence_digest = digest("changed"),
            _ => unreachable!(),
        }
        assert_eq!(
            sink.persist(execution, &expected),
            Err(ProductEvidenceSinkErrorV1::Rejected)
        );
        assert_eq!(fs::read(&path).unwrap(), original);
        assert!(read_product_qualification_evidence_v1(&path, receipt).is_ok());
    }
}

#[test]
fn every_truncation_corruption_wrong_digest_and_noncanonical_decision_rejects() {
    let expected = decision();
    let execution = digest("execution");
    let bytes = codec::encode(execution, &expected).unwrap();
    for cut in 0..bytes.len() {
        let dir = TestDir::new();
        let path = dir.path();
        fs::write(&path, &bytes[..cut]).unwrap();
        let mut sink = FileProductQualificationEvidenceSinkV1::new(&path).unwrap();
        assert_eq!(
            sink.persist(execution, &expected),
            Err(ProductEvidenceSinkErrorV1::Rejected)
        );
        assert!(
            read_product_qualification_evidence_v1(&path, Digest32::of_bytes(&bytes[..cut]))
                .is_err()
        );
        assert_eq!(fs::read(&path).unwrap(), bytes[..cut]);
    }
    let dir = TestDir::new();
    let path = dir.path();
    fs::write(&path, &bytes).unwrap();
    assert!(read_product_qualification_evidence_v1(&path, digest("wrong digest")).is_err());
    let mut altered = bytes;
    altered[20] ^= 1;
    fs::write(&path, &altered).unwrap();
    assert!(read_product_qualification_evidence_v1(&path, Digest32::of_bytes(&altered)).is_err());
    // Rehashing the outer file and inner checksum cannot authorize grant bits
    // or extend the exact versioned record with unchecked trailing fields.
    for mode in ["authority", "trailing"] {
        let mut altered = codec::encode(execution, &expected).unwrap();
        altered.truncate(altered.len() - 32);
        if mode == "authority" {
            *altered.last_mut().unwrap() = 1;
        } else {
            altered.push(/*value*/ 0);
        }
        let checksum = Digest32::of_bytes(
            &[
                b"hepta.product-qualification-record.checksum.v1".as_slice(),
                altered.as_slice(),
            ]
            .concat(),
        );
        altered.extend_from_slice(checksum.as_array());
        fs::write(&path, &altered).unwrap();
        assert!(
            read_product_qualification_evidence_v1(&path, Digest32::of_bytes(&altered)).is_err()
        );
    }
    assert!(codec::encode(Digest32::ZERO, &expected).is_err());
    let mut noncanonical = expected;
    noncanonical.decision.failed_metrics.reverse();
    assert!(codec::encode(execution, &noncanonical).is_err());
    noncanonical.decision.failed_metrics = vec![StableId::new("metric").unwrap(); 129];
    assert!(codec::encode(execution, &noncanonical).is_err());
}

#[test]
fn symlinks_nonregular_paths_replaced_parent_and_oversized_files_fail_closed() {
    use std::os::unix::fs::symlink;
    let dir = TestDir::new();
    let target = dir.0.join("target");
    fs::write(&target, b"untouched").unwrap();
    let link = dir.path();
    symlink(&target, &link).unwrap();
    let mut sink = FileProductQualificationEvidenceSinkV1::new(&link).unwrap();
    assert!(sink.persist(digest("execution"), &decision()).is_err());
    assert!(read_product_qualification_evidence_v1(&link, digest("untouched")).is_err());
    assert_eq!(fs::read(&target).unwrap(), b"untouched");
    let directory = dir.0.join("directory");
    fs::create_dir(&directory).unwrap();
    assert!(
        FileProductQualificationEvidenceSinkV1::new(&directory)
            .unwrap()
            .persist(digest("execution"), &decision())
            .is_err()
    );
    let oversized = dir.0.join("oversized");
    fs::write(&oversized, vec![0; MAX_EVIDENCE_BYTES as usize + 1]).unwrap();
    assert!(read_product_qualification_evidence_v1(&oversized, digest("wrong")).is_err());
    assert!(FileProductQualificationEvidenceSinkV1::new("relative/path").is_err());
    let nested = dir.0.join("pinned");
    fs::create_dir(&nested).unwrap();
    let mut pinned = FileProductQualificationEvidenceSinkV1::new(nested.join("evidence")).unwrap();
    fs::rename(&nested, dir.0.join("retired-parent")).unwrap();
    fs::create_dir(&nested).unwrap();
    assert_eq!(
        pinned.persist(digest("execution"), &decision()),
        Err(ProductEvidenceSinkErrorV1::Indeterminate)
    );
    assert!(!nested.join("evidence").exists());
}

#[test]
fn concurrent_different_creators_cannot_both_acknowledge_and_busy_readers_refuse() {
    let dir = TestDir::new();
    let path = dir.path();
    let barrier = std::sync::Arc::new(std::sync::Barrier::new(/*n*/ 2));
    let mut jobs = Vec::new();
    for execution in [digest("first"), digest("second")] {
        let path = path.clone();
        let barrier = barrier.clone();
        jobs.push(std::thread::spawn(move || {
            let mut sink = FileProductQualificationEvidenceSinkV1::new(path).unwrap();
            barrier.wait();
            sink.persist(execution, &decision())
        }));
    }
    let results: Vec<_> = jobs.into_iter().map(|job| job.join().unwrap()).collect();
    assert!(results.iter().filter(|result| result.is_ok()).count() <= 1);
    if let Some(receipt) = results.into_iter().find_map(Result::ok) {
        assert!(read_product_qualification_evidence_v1(&path, receipt).is_ok());
    } else {
        // A loser may briefly lock a newly created empty file before its
        // creator locks it. Both callers may fail closed; no receipt is minted
        // and the immutable path is not repaired into a guessed outcome.
        assert!(
            read_product_qualification_evidence_v1(
                &path,
                Digest32::of_bytes(&fs::read(&path).unwrap())
            )
            .is_err()
        );
    }
    let path = dir.0.join("lock.evidence");
    let digest = FileProductQualificationEvidenceSinkV1::new(&path)
        .unwrap()
        .persist(digest("lock execution"), &decision())
        .unwrap();
    let guard = File::open(&path).unwrap();
    guard.try_lock().unwrap();
    assert_eq!(
        read_product_qualification_evidence_v1(&path, digest),
        Err(ProductEvidenceSinkErrorV1::Unavailable)
    );
    drop(guard);
    assert!(read_product_qualification_evidence_v1(&path, digest).is_ok());
}
