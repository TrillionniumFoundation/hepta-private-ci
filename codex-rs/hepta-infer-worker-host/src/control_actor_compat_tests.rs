use std::fs;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use crate::NativeJournalWriterActor;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeDispatch;
use codex_hepta_infer_core::durable_control::native::NativeRequest;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;

struct TestJournal {
    directory: PathBuf,
    journal: PathBuf,
}

impl TestJournal {
    fn new() -> Self {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let directory = std::env::temp_dir().join(format!(
            "hepta-inference-control-actor-{}-{nonce}",
            std::process::id()
        ));
        fs::create_dir_all(&directory).unwrap();
        Self {
            journal: directory.join("control.journal"),
            directory,
        }
    }
}

impl Drop for TestJournal {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.directory);
    }
}

#[tokio::test]
async fn one_writer_owns_the_journal_and_effect_capability_is_one_shot() {
    let paths = TestJournal::new();
    let actor = NativeJournalWriterActor::spawn(paths.journal.clone(), 8).unwrap();
    let writer = actor.handle();
    let request_id = "actor-request-1".to_string();
    let reserved = writer
        .reserve(
            NativeRequest {
                request_id: request_id.clone(),
                principal_id: "actor-principal".to_string(),
                worker_generation: 1,
                model: "actor-model".to_string(),
                payload_digest: "1".repeat(64),
            },
            1,
        )
        .await
        .unwrap();
    assert_eq!(reserved.state, NativeReservationState::Reserved);

    // A cloned command port is not a second owner. A separate durable owner
    // cannot acquire the same lifecycle lock while the actor is alive.
    assert!(DurableInferenceControl::open(&paths.journal, 8).is_err());

    let prepared = writer
        .prepare_dispatch(
            request_id.clone(),
            NativeDispatch {
                thread_id: "actor-thread-1".to_string(),
                model_provider: "actor-provider".to_string(),
                context_digest: "2".repeat(64),
                owner_context_digest: None,
                codex_payload_digest: None,
                codex_request_digest: None,
                app_server_version: None,
                protocol_id: None,
                codex_source_admission_digest: None,
                codex_home_digest: None,
                codex_connection_id: None,
                codex_session_id: None,
                codex_deadline_ms: None,
                codex_authority_epoch: None,
                codex_revocation_revision: None,
                codex_revocation_head_sha256: None,
                codex_authority_witness_sha256: None,
            },
        )
        .await
        .unwrap();
    assert_eq!(prepared.record().state, NativeReservationState::Dispatching);
    let released = prepared
        .abort_before_effect("effect executor never sent the request".to_string())
        .await
        .unwrap();
    assert_eq!(released.state, NativeReservationState::Released);

    let metrics = writer.metrics(1_000).await.unwrap();
    assert_eq!(metrics.released, 1);
    assert_eq!(metrics.dispatching, 0);
    let maintenance = writer.compact().await.unwrap();
    assert_eq!(maintenance.generation, 1);

    actor.shutdown().await.unwrap();
    let reopened = DurableInferenceControl::open(&paths.journal, 8).unwrap();
    assert_eq!(
        reopened.native_record(&request_id).unwrap().state,
        NativeReservationState::Released
    );
}
