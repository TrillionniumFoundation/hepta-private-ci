use super::*;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

#[tokio::test]
async fn issuer_revocation_while_waiting_for_write_lock_rejects_without_consuming_identity() {
    let temp = TempDir::new().expect("temp");
    let sqlite = config(&temp);
    let holder = HeptaEvidenceStore::open(&sqlite).await.expect("holder");
    let contender = HeptaEvidenceStore::open(&sqlite).await.expect("contender");
    let locked = holder
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("writer lock");
    let observed = now_ms();
    let (issuer, key) = issuer("principal:current-evaluator", 91);
    let envelope = evidence(
        "evidence:current-evaluator",
        candidate('b'),
        EvidenceClaimClassV1::Causal,
        EvidenceIssuerRoleV1::Evaluator,
        observed,
        Some(observed + 60_000),
        json!({"actual": "publication"}),
    );
    let message = signed(&envelope, &issuer, &key, 1, observed + 60_000);
    let resolved = Arc::new(AtomicBool::new(false));
    let revoked = Arc::new(AtomicBool::new(false));
    let resolved_at_use = Arc::clone(&resolved);
    let revoked_at_use = Arc::clone(&revoked);
    let current = issuer_with_key(issuer.issuer_id.as_str(), &key);
    let qualification = contender.qualification();
    let append = qualification.append_receipt_with_current_issuer(
        move || {
            resolved_at_use.store(true, Ordering::SeqCst);
            Ok(IssuerRegistration {
                revoked: revoked_at_use.load(Ordering::SeqCst),
                ..current
            })
        },
        &message,
        &envelope,
    );
    tokio::pin!(append);
    tokio::select! {
        result = &mut append => panic!("append did not wait for owner lock: {result:?}"),
        () = tokio::time::sleep(Duration::from_millis(50)) => {}
    }
    assert!(
        !resolved.load(Ordering::SeqCst),
        "issuer was resolved before writer serialization"
    );
    revoked.store(true, Ordering::SeqCst);
    locked.rollback().await.expect("release writer lock");
    assert!(append.await.is_err(), "waiter accepted revoked issuer");
    assert!(resolved.load(Ordering::SeqCst));
    assert!(
        qualification
            .query_claim(&envelope.candidate, envelope.claim_class)
            .await
            .expect("query")
            .is_empty()
    );
    // A rejected admission did not consume the stable evidence/replay identity.
    qualification
        .append_receipt_with_current_issuer(
            || Ok(issuer_with_key(issuer.issuer_id.as_str(), &key)),
            &message,
            &envelope,
        )
        .await
        .expect("same identity after explicit host reauthorization");
    assert_eq!(
        qualification
            .query_claim(&envelope.candidate, envelope.claim_class)
            .await
            .expect("query")
            .len(),
        1
    );
}
