use super::*;

use std::sync::Arc;
use std::sync::Mutex;

use crate::control_actor::NativeJournalWriterActor;
use crate::control_actor::NativeJournalWriterHandle;
use crate::output_protection::NativeOutputProtectionFuture;
use codex_hepta_infer_core::control_contracts::ControlTrustStore;
use codex_hepta_infer_core::control_contracts::OutputClassification;
use codex_hepta_infer_core::control_contracts::ProtectedOutput;
use codex_hepta_infer_core::control_contracts::verify_execution_plan;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

#[path = "control_actor_signed_fixture.rs"]
mod signed;

#[derive(Default)]
struct ProtectionFixture {
    observed_plaintext: Mutex<Vec<Vec<u8>>>,
}

impl NativeOutputProtector for ProtectionFixture {
    fn protect<'a>(
        &'a self,
        plan: &'a VerifiedExecutionPlan,
        plaintext: &'a [u8],
        now_unix_ms: u64,
    ) -> NativeOutputProtectionFuture<'a> {
        self.observed_plaintext
            .lock()
            .unwrap()
            .push(plaintext.to_vec());
        Box::pin(async move {
            ProtectedOutput::external_encrypted(
                now_unix_ms,
                plan.output_policy(),
                plaintext,
                "vault://fixture/object".to_string(),
                "c".repeat(64),
            )
            .map_err(|error| error.to_string())
        })
    }
}

fn encrypted_plan(id: &str, now: u64) -> VerifiedExecutionPlan {
    let (keys, mut signed) = signed::execution_authority(id, now);
    signed.bundle.output_policy.classification = OutputClassification::Confidential;
    signed.bundle.output_policy.storage_mode = OutputStorageMode::ExternalEncrypted;
    signed.bundle.output_policy.encryption_key_id = Some("fixture-key".to_string());
    signed.bundle.output_policy.encrypted_store_namespace = Some("fixture".to_string());
    let bytes = signed.bundle.signing_bytes().unwrap();
    for (index, signature) in signed.signatures.iter_mut().enumerate() {
        let seed = u8::try_from(index + 1).unwrap();
        signature.signature = SigningKey::from_bytes(&[seed; 32])
            .sign(&bytes)
            .to_bytes()
            .to_vec();
    }
    verify_execution_plan(now, &ControlTrustStore::new(keys).unwrap(), &signed).unwrap()
}

async fn prepared(
    journal: std::path::PathBuf,
    id: &str,
    plan: Arc<VerifiedExecutionPlan>,
) -> (NativeJournalWriterActor, NativeJournalWriterHandle) {
    let actor = NativeJournalWriterActor::spawn(journal, /*capacity*/ 8).unwrap();
    let writer = actor.handle();
    let now = unix_time_ms().unwrap();
    writer
        .reserve(signed::request(id), /*maximum_in_flight*/ 1)
        .await
        .unwrap();
    writer
        .bind_execution(id.to_string(), Arc::clone(&plan), now)
        .await
        .unwrap();
    writer
        .prepare_authorized_dispatch(id.to_string(), signed::dispatch("thread-1"), plan, now)
        .await
        .unwrap()
        .cross_effect_boundary()
        .started("turn-1".to_string())
        .await
        .unwrap();
    (actor, writer)
}

#[tokio::test]
async fn live_output_preserves_text_and_uses_durable_quota_denial() {
    let paths = tempfile::tempdir().unwrap();
    let journal = paths.path().join("control.journal");
    let plan = Arc::new(signed::plan("overrun", unix_time_ms().unwrap()));
    let (actor, mut writer) = prepared(journal.clone(), "overrun", Arc::clone(&plan)).await;
    let text = "live plaintext preserved without undoing quarantine";
    let mut raw = signed::terminal_output("thread-1", "turn-1", text);
    raw.observed_output_tokens = Some(plan.quota_lease().maximum_output_tokens + 1);
    assert!(raw.succeeded());
    let live = settle_authorized_native_output(
        &mut writer,
        "overrun",
        NativeExecutionAuthority {
            plan: &plan,
            output_protector: None,
        },
        raw,
    )
    .await
    .unwrap();
    let record = writer.record("overrun".to_string()).await.unwrap().unwrap();
    assert_eq!(record.state, NativeReservationState::Released);
    let mut expected = record.observation.clone().unwrap();
    assert_eq!(expected.boundary_status, NativeBoundaryStatus::Quarantined);
    assert!(!expected.succeeded());
    expected.output = text.to_string();
    assert_eq!(live, expected);
    assert!(!std::fs::read_to_string(journal).unwrap().contains(text));
    actor.shutdown().await.unwrap();
}

#[tokio::test]
async fn empty_encrypted_terminals_use_the_protector_and_release_capacity() {
    for (id, status, boundary) in [
        (
            "empty-completed",
            NativeRunStatus::Completed,
            NativeBoundaryStatus::Succeeded,
        ),
        (
            "empty-failed",
            NativeRunStatus::Failed,
            NativeBoundaryStatus::Failed,
        ),
        (
            "empty-interrupted",
            NativeRunStatus::Interrupted,
            NativeBoundaryStatus::Interrupted,
        ),
    ] {
        let paths = tempfile::tempdir().unwrap();
        let plan = Arc::new(encrypted_plan(id, unix_time_ms().unwrap()));
        let (actor, mut writer) =
            prepared(paths.path().join("control.journal"), id, Arc::clone(&plan)).await;
        let protector = ProtectionFixture::default();
        let mut observed = signed::terminal_output("thread-1", "turn-1", "");
        observed.status = status;
        observed.boundary_status = boundary;
        let live = settle_authorized_native_output(
            &mut writer,
            id,
            NativeExecutionAuthority {
                plan: &plan,
                output_protector: Some(&protector),
            },
            observed,
        )
        .await
        .unwrap();
        let record = writer.record(id.to_string()).await.unwrap().unwrap();
        assert_eq!(
            *protector.observed_plaintext.lock().unwrap(),
            vec![Vec::<u8>::new()]
        );
        assert_eq!(record.state, NativeReservationState::Released);
        assert!(record.protected_output.is_some());
        assert_eq!(live.status, status);
        assert_eq!(live.boundary_status, boundary);
        assert!(live.output.is_empty());
        actor.shutdown().await.unwrap();
    }
}

#[tokio::test]
async fn empty_nonterminal_has_no_protection_object_or_terminal_claim() {
    let paths = tempfile::tempdir().unwrap();
    let plan = Arc::new(encrypted_plan("empty-unknown", unix_time_ms().unwrap()));
    let (actor, mut writer) = prepared(
        paths.path().join("control.journal"),
        "empty-unknown",
        Arc::clone(&plan),
    )
    .await;
    let protector = ProtectionFixture::default();
    let mut observed = signed::terminal_output("thread-1", "turn-1", "");
    observed.status = NativeRunStatus::Indeterminate;
    observed.boundary_status = NativeBoundaryStatus::Indeterminate;
    observed.terminal_observed = false;
    observed.observed_output_tokens = None;
    observed.codex_terminal_correlation_digest = None;
    let live = settle_authorized_native_output(
        &mut writer,
        "empty-unknown",
        NativeExecutionAuthority {
            plan: &plan,
            output_protector: Some(&protector),
        },
        observed,
    )
    .await
    .unwrap();
    let record = writer
        .record("empty-unknown".to_string())
        .await
        .unwrap()
        .unwrap();
    assert!(protector.observed_plaintext.lock().unwrap().is_empty());
    assert_eq!(record.state, NativeReservationState::Indeterminate);
    assert!(record.protected_output.is_none());
    assert!(!live.terminal_observed);
    actor.shutdown().await.unwrap();
}
