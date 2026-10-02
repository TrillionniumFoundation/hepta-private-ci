use super::*;
use codex_hepta_infer_core::durable_control::native::NativeBoundSourceRecordV2;
use sha2::Digest;
use sha2::Sha256;

type TestResult<T> = Result<T, Box<dyn std::error::Error>>;

fn fixture(id: &str) -> TestResult<(NativeRequest, NativeBoundSourceProof)> {
    let socket = std::env::temp_dir().join("bound-actor.sock");
    let context = "1".repeat(64);
    let envelope = "2".repeat(64);
    let bytes = serde_json::to_vec(&(
        "hepta.native-intelligence-request.v2",
        "private actor prompt",
        None::<String>,
        &socket,
        1000_u128,
        "actor-run",
        2_u64,
        &context,
        &envelope,
    ))?;
    let request = NativeRequest {
        request_id: id.to_string(),
        principal_id: "actor-principal".to_string(),
        worker_generation: 1,
        model: "actor-model".to_string(),
        payload_digest: format!("{:x}", Sha256::digest(bytes)),
    };
    let source = NativeBoundSourceRecordV2 {
        schema_version: 2,
        request_id: request.request_id.clone(),
        request_payload_sha256: request.payload_digest.clone(),
        run_id: "actor-run".to_string(),
        owner_pre_dispatch_revision: 2,
        context_sha256: context,
        envelope_sha256: envelope,
    };
    let proof = NativeBoundSourceProof::verify(
        &request,
        "private actor prompt",
        &None,
        &socket,
        1000,
        source,
    )?;
    Ok((request, proof))
}

#[tokio::test]
async fn bound_port_is_idempotent_and_reconstructs_after_actor_restart() {
    let paths = tempfile::tempdir().unwrap();
    let journal = paths.path().join("bound.journal");
    let actor = NativeJournalWriterActor::spawn(journal.clone(), 8).unwrap();
    let mut writer = actor.handle();
    let (request, proof) = fixture("bound").unwrap();
    let first = NativeControlPort::reserve_native_bound(&mut writer, request.clone(), 1, proof)
        .await
        .unwrap();
    let bytes = std::fs::read(&journal).unwrap();
    let (same_request, same_proof) = fixture("bound").unwrap();
    assert_eq!(
        writer
            .reserve_bound(same_request, 1, same_proof)
            .await
            .unwrap(),
        first
    );
    assert_eq!(std::fs::read(&journal).unwrap(), bytes);
    assert!(writer.reserve(request, 1).await.is_err());
    actor.shutdown().await.unwrap();
    let reopened = NativeJournalWriterActor::spawn(journal, 8).unwrap();
    assert_eq!(
        reopened.handle().record("bound".to_string()).await.unwrap(),
        Some(first)
    );
    reopened.shutdown().await.unwrap();
}

#[tokio::test]
async fn bound_reply_loss_preserves_exact_committed_relationship() {
    let paths = tempfile::tempdir().unwrap();
    let journal = paths.path().join("lost.journal");
    let actor = NativeJournalWriterActor::spawn(journal.clone(), 8).unwrap();
    let writer = actor.handle();
    let (request, proof) = fixture("lost").unwrap();
    let expected_source = proof.record().clone();
    let (reply, response) = oneshot::channel();
    drop(response);
    writer
        .send(Command::ReserveBound {
            request,
            maximum_in_flight: 1,
            proof,
            reply,
        })
        .unwrap();
    let record = writer.record("lost".to_string()).await.unwrap().unwrap();
    assert_eq!(record.bound_source, Some(expected_source));
    assert_eq!(writer.queue_metrics().unwrap().successful_replies_lost, 1);
    let (request, proof) = fixture("lost").unwrap();
    assert_eq!(
        writer.reserve_bound(request, 1, proof).await.unwrap(),
        record
    );
    actor.shutdown().await.unwrap();
    let reopened = DurableInferenceControl::open(journal, 8).unwrap();
    assert_eq!(reopened.native_record("lost"), Some(&record));
}

#[tokio::test]
async fn bound_admission_checks_request_proof_pair_inside_the_writer() {
    let paths = tempfile::tempdir().unwrap();
    let journal = paths.path().join("drift.journal");
    let actor = NativeJournalWriterActor::spawn(journal.clone(), 8).unwrap();
    let writer = actor.handle();
    let (mut request, proof) = fixture("original").unwrap();
    request.request_id = "substituted".to_string();
    let before = std::fs::read(&journal).unwrap();
    assert!(writer.reserve_bound(request, 1, proof).await.is_err());
    assert_eq!(writer.record("original".to_string()).await.unwrap(), None);
    assert_eq!(
        writer.record("substituted".to_string()).await.unwrap(),
        None
    );
    assert_eq!(std::fs::read(&journal).unwrap(), before);
    let (request, proof) = fixture("original").unwrap();
    assert!(writer.reserve_bound(request, 1, proof).await.is_ok());
    actor.shutdown().await.unwrap();
}
