use super::*;
use crate::IndependentEvaluationDecisionV1;
use codex_hepta_types::AuthorityPosture;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn decision() -> SignedEvaluationDecisionV1 {
    SignedEvaluationDecisionV1 {
        decision: IndependentEvaluationDecisionV1 {
            evaluation_id: StableId::new("eval").unwrap_or_else(|e| panic!("id: {e}")),
            candidate_id: StableId::new("candidate").unwrap_or_else(|e| panic!("id: {e}")),
            baseline_id: StableId::new("deployed-baseline").unwrap_or_else(|e| panic!("id: {e}")),
            disposition: IndependentEvaluationDispositionV1::Ineligible,
            failed_metrics: Vec::new(),
            evidence_digest: digest("native-evidence"),
            authority: AuthorityPosture::DENY_ALL,
        },
        trust_digest: digest("admitted-trust"),
        authentication_digest: digest("real-signature-bindings"),
    }
}
fn file() -> (PathBuf, File) {
    static NEXT: AtomicU64 = AtomicU64::new(0);
    let path = std::env::temp_dir().join(format!(
        "hepta-product-evidence-{}-{}",
        std::process::id(),
        NEXT.fetch_add(1, Ordering::Relaxed)
    ));
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(&path)
        .unwrap_or_else(|e| panic!("physical file: {e}"));
    (path, file)
}
fn reopen(path: &std::path::Path) -> File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)
        .unwrap_or_else(|e| panic!("reopen: {e}"))
}
#[test]
fn physical_product_sink_keeps_full_original_request_and_exact_restart_replay() {
    let (path, file) = file();
    let execution = digest("execution");
    let request =
        b"full frozen plan + authentic raw observations + original G/O/E evidence preimages";
    let native = decision();
    let mut sink = LockedFileProductEvidenceSinkV1::open(
        file,
        execution,
        request,
        ProductPublicationRecoveryV1::Unacknowledged,
    )
    .unwrap_or_else(|e| panic!("sink: {e}"));
    let ack = sink
        .persist(execution, &native)
        .unwrap_or_else(|e| panic!("publish: {e}"));
    drop(sink);
    let bytes = std::fs::read(&path).unwrap_or_else(|e| panic!("bytes: {e}"));
    assert!(bytes.windows(request.len()).any(|window| window == request));
    assert_eq!(Digest32::of_bytes(&bytes), ack);
    let mut recovered = LockedFileProductEvidenceSinkV1::open(
        reopen(&path),
        execution,
        request,
        ProductPublicationRecoveryV1::Acknowledged(ack),
    )
    .unwrap_or_else(|e| panic!("recover: {e}"));
    assert_eq!(recovered.persist(execution, &native), Ok(ack));
    let mut altered = native;
    altered.authentication_digest = digest("different-signed-cut");
    assert_eq!(
        recovered.persist(execution, &altered),
        Err(ProductEvidenceSinkErrorV1::Rejected)
    );
    drop(recovered);
    assert_eq!(
        std::fs::read(&path).unwrap_or_else(|e| panic!("preserved: {e}")),
        bytes
    );
    assert!(
        LockedFileProductEvidenceSinkV1::open(
            reopen(&path),
            execution,
            b"unrelated original request",
            ProductPublicationRecoveryV1::Unacknowledged
        )
        .is_err()
    );
    std::fs::remove_file(path).unwrap_or_else(|e| panic!("remove: {e}"));
}
#[test]
fn physical_product_sink_rejects_torn_record_and_never_truncates() {
    let (path, file) = file();
    let execution = digest("execution");
    let request = b"original signed request";
    let mut sink = LockedFileProductEvidenceSinkV1::open(
        file,
        execution,
        request,
        ProductPublicationRecoveryV1::Unacknowledged,
    )
    .unwrap_or_else(|e| panic!("sink: {e}"));
    sink.persist(execution, &decision())
        .unwrap_or_else(|e| panic!("publish: {e}"));
    drop(sink);
    let mut bytes = std::fs::read(&path).unwrap_or_else(|e| panic!("bytes: {e}"));
    bytes.pop();
    std::fs::write(&path, &bytes).unwrap_or_else(|e| panic!("fault injection: {e}"));
    assert!(matches!(
        LockedFileProductEvidenceSinkV1::open(
            reopen(&path),
            execution,
            request,
            ProductPublicationRecoveryV1::Unacknowledged
        ),
        Err(ProductEvidenceSinkErrorV1::Indeterminate)
    ));
    assert_eq!(
        std::fs::read(&path).unwrap_or_else(|e| panic!("preserved: {e}")),
        bytes
    );
    std::fs::remove_file(path).unwrap_or_else(|e| panic!("remove: {e}"));
}
#[test]
fn physical_product_sink_exclusive_lock_and_execution_binding_fail_closed() {
    let (path, file) = file();
    let execution = digest("execution");
    let mut sink = LockedFileProductEvidenceSinkV1::open(
        file,
        execution,
        b"signed request",
        ProductPublicationRecoveryV1::Unacknowledged,
    )
    .unwrap_or_else(|e| panic!("sink: {e}"));
    assert!(matches!(
        LockedFileProductEvidenceSinkV1::open(
            reopen(&path),
            execution,
            b"signed request",
            ProductPublicationRecoveryV1::Unacknowledged
        ),
        Err(ProductEvidenceSinkErrorV1::Unavailable)
    ));
    assert_eq!(
        sink.persist(digest("different-execution"), &decision()),
        Err(ProductEvidenceSinkErrorV1::Rejected)
    );
    assert!(
        std::fs::read(&path)
            .unwrap_or_else(|e| panic!("empty: {e}"))
            .is_empty()
    );
    drop(sink);
    std::fs::remove_file(path).unwrap_or_else(|e| panic!("remove: {e}"));
}

#[test]
fn physical_product_sink_retained_ack_rejects_deleted_publication() {
    let (path, file) = file();
    let execution = digest("execution");
    let request = b"original signed request";
    let mut sink = LockedFileProductEvidenceSinkV1::open(
        file,
        execution,
        request,
        ProductPublicationRecoveryV1::Unacknowledged,
    )
    .unwrap_or_else(|e| panic!("sink: {e}"));
    let ack = sink
        .persist(execution, &decision())
        .unwrap_or_else(|e| panic!("publish: {e}"));
    drop(sink);
    std::fs::write(&path, []).unwrap_or_else(|e| panic!("rollback fault: {e}"));
    assert!(matches!(
        LockedFileProductEvidenceSinkV1::open(
            reopen(&path),
            execution,
            request,
            ProductPublicationRecoveryV1::Acknowledged(ack)
        ),
        Err(ProductEvidenceSinkErrorV1::Indeterminate)
    ));
    std::fs::remove_file(path).unwrap_or_else(|e| panic!("remove: {e}"));
}
