use std::sync::Arc;
use std::thread;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_evidence::EvidenceFrontierBackend;
use codex_hepta_evidence::EvidenceFrontierBackendError;
use codex_hepta_evidence::EvidenceFrontierRecordV1;
use codex_hepta_evidence::InMemoryEvidenceFrontierBackend;

fn record(generation: u64, payload: &str) -> EvidenceFrontierRecordV1 {
    EvidenceFrontierRecordV1 {
        schema_version: 1,
        store_id: "store:frontier-contention".to_string(),
        generation,
        signed_frontier_json: payload.to_string(),
        signed_frontier_sha256: Sha256Digest::for_bytes(payload.as_bytes()),
        backend_audit_event_id: format!("audit:frontier-{generation}-{payload}"),
        committed_at_unix_ms: generation,
        backend_key_epoch: 1,
    }
}

#[test]
fn one_of_many_contending_first_publishers_wins_and_history_stays_linear() {
    let backend = Arc::new(
        InMemoryEvidenceFrontierBackend::new(
            "backend:frontier-contention".to_string(),
            "rollback:frontier-contention".to_string(),
        )
        .expect("backend"),
    );
    let workers = 32;
    let handles = (0..workers)
        .map(|worker| {
            let backend = Arc::clone(&backend);
            thread::spawn(move || {
                let payload = format!(r#"{{"generation":1,"worker":{worker}}}"#);
                backend.compare_and_swap(
                    "store:frontier-contention",
                    None,
                    record(1, &payload),
                )
            })
        })
        .collect::<Vec<_>>();

    let results = handles
        .into_iter()
        .map(|handle| handle.join().expect("worker did not panic"))
        .collect::<Vec<_>>();
    assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 1);
    assert_eq!(
        results
            .iter()
            .filter(|result| matches!(result, Err(EvidenceFrontierBackendError::CompareAndSwapConflict { .. })))
            .count(),
        workers - 1
    );
    assert_eq!(
        backend
            .get_history("store:frontier-contention", None, 1024)
            .expect("history")
            .len(),
        1
    );
}

#[test]
fn corrupted_frontier_bytes_are_rejected_before_any_state_change() {
    let backend = InMemoryEvidenceFrontierBackend::new(
        "backend:frontier-corruption".to_string(),
        "rollback:frontier-corruption".to_string(),
    )
    .expect("backend");
    let mut corrupted = record(1, r#"{"generation":1}"#);
    corrupted.signed_frontier_sha256 = Sha256Digest::for_bytes(b"different bytes");
    assert!(matches!(
        backend.compare_and_swap("store:frontier-contention", None, corrupted),
        Err(EvidenceFrontierBackendError::Invalid(_))
    ));
    assert!(
        backend
            .get_latest("store:frontier-contention")
            .expect("latest")
            .is_none()
    );
}

#[test]
fn backend_identity_cannot_claim_the_local_rollback_domain() {
    let backend = InMemoryEvidenceFrontierBackend::new(
        "backend:frontier-identity".to_string(),
        "rollback:same-domain".to_string(),
    )
    .expect("backend");
    let identity = backend.verify_backend_identity().expect("identity");
    assert!(matches!(
        identity.validate_for_production("rollback:same-domain"),
        Err(EvidenceFrontierBackendError::UnsafeForProduction(_))
    ));
}
