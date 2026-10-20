use std::sync::mpsc;
use std::time::Duration;

use super::*;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn recovery_frontier_keeps_receipts_and_replay_on_one_read_snapshot() {
    let temp = TempDir::new().expect("private evidence root");
    let sqlite = config(&temp);
    let writer = HeptaEvidenceStore::open(&sqlite).await.expect("writer");
    let (issuer, key) = issuer("issuer:frontier", /*seed*/ 47);
    let observed = now_ms();
    for sequence in 1..=128 {
        let envelope = evidence(
            &format!("evidence:frontier:{sequence}"),
            candidate('b'),
            EvidenceClaimClassV1::MandatoryTests,
            EvidenceIssuerRoleV1::Evaluator,
            observed,
            /*expires*/ None,
            json!({"sequence": sequence}),
        );
        append(&writer, &issuer, &key, &envelope, sequence)
            .await
            .expect("seed genuine authenticated receipt");
    }
    let before = writer.recovery_snapshot().await.expect("before cut");
    let reader = HeptaEvidenceStore::open_existing_read_only(&sqlite)
        .await
        .expect("read-only recovery observer");

    // The production read-only pool has one connection. Pause its SQLite VM
    // after the small migration query, during the seeded qualification scan.
    // A separate writer commits a genuine receipt and its replay fence while
    // that read is open. No timing sleep or production test hook is needed.
    let (entered, started) = tokio::sync::oneshot::channel();
    let (release, released) = mpsc::channel();
    let mut connection = reader.pool.acquire().await.expect("reader connection");
    let mut entered = Some(entered);
    connection
        .lock_handle()
        .await
        .expect("SQLite read handle")
        .set_progress_handler(/*num_ops*/ 500, move || {
            if let Some(entered) = entered.take() {
                if entered.send(()).is_err() {
                    return false;
                }
                return released.recv_timeout(Duration::from_secs(10)).is_ok();
            }
            true
        });
    drop(connection);

    let snapshot = tokio::spawn(async move {
        let snapshot = reader.recovery_snapshot().await;
        reader
            .pool
            .acquire()
            .await
            .expect("reader cleanup")
            .lock_handle()
            .await
            .expect("reader handle")
            .remove_progress_handler();
        reader.close().await;
        snapshot
    });
    tokio::time::timeout(Duration::from_secs(10), started)
        .await
        .expect("qualification scan reached VM barrier")
        .expect("reader still running");
    let envelope = evidence(
        "evidence:frontier:129",
        candidate('b'),
        EvidenceClaimClassV1::MandatoryTests,
        EvidenceIssuerRoleV1::Evaluator,
        observed,
        /*expires*/ None,
        json!({"sequence": 129}),
    );
    let appended = append(&writer, &issuer, &key, &envelope, 129).await;
    release.send(()).expect("release paused reader");
    appended.expect("writer commits while recovery snapshot is reading");
    let captured = snapshot
        .await
        .expect("reader joined")
        .expect("coherent read-only frontier");
    let after = writer.recovery_snapshot().await.expect("after cut");
    assert_eq!(before.qualification_max_seq, 128);
    assert_eq!(after.qualification_max_seq, 129);
    assert_ne!(
        before.authbus_replay_frontier_sha256,
        after.authbus_replay_frontier_sha256
    );
    assert_eq!(captured, before);
    writer.close().await;
    let reopened = HeptaEvidenceStore::open_existing_read_only(&sqlite)
        .await
        .expect("reopen reader");
    assert_eq!(
        reopened.recovery_snapshot().await.expect("reopened cut"),
        after
    );
    reopened.close().await;
}
