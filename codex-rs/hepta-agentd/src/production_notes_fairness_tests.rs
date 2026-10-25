//! Exercise the shared observer budget with two original durable destinations.
use super::*;
use crate::AgentdNotesChannel;
use codex_hepta_memory::FinalUseProductionOutboxTarget;
use codex_hepta_memory::ProductionDispatchFuture;
use codex_hepta_memory::ProductionDispatchRequest;
use codex_hepta_memory::ProductionNotesTarget;
use codex_hepta_memory::ProductionOutboxTarget;
use codex_hepta_memory::ProductionTerminalObservation;
use codex_hepta_memory::ProductionTerminalObservationFuture;
use pretty_assertions::assert_eq;

struct UnknownDestination(AtomicUsize);
impl ProductionOutboxTarget for UnknownDestination {
    fn dispatch<'a>(&'a self, _: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        panic!("reconciliation must not dispatch")
    }
}
impl FinalUseProductionOutboxTarget for UnknownDestination {
    fn destination_id(&self) -> &str {
        "aaa:unknown-first"
    }
    fn observe_terminal<'a>(
        &'a self,
        _: &'a ProductionDispatchRequest,
    ) -> ProductionTerminalObservationFuture<'a> {
        self.0.fetch_add(1, Ordering::SeqCst);
        Box::pin(async {
            ProductionTerminalObservation::Indeterminate {
                reason: "fixture destination remains unknown".into(),
            }
        })
    }
}

#[tokio::test]
async fn notes_later_destination_receives_terminal_observation_and_ack_despite_earlier_unknown()
-> Result<(), Box<dyn Error>> {
    let NotesHostFixture {
        directory: _directory,
        config,
        host,
        operations: _,
        issuer,
        final_use,
        primary_device: _,
    } = notes_host_fixture().await?;
    let unknown = Arc::new(UnknownDestination(AtomicUsize::new(0)));
    let host = host.attach_target(final_use.clone(), unknown.clone(), issuer.clone())?;
    let first = codex_hepta_operations::OperationIntentV1::new(
        StableId::new("unknown-first")?,
        StableId::new(config.identity().agent_id.as_str())?,
        StableId::new(unknown.destination_id())?,
        codex_hepta_types::Digest32::of_bytes(b"{}"),
        codex_hepta_types::Digest32::of_bytes(b"fixture-scope"),
        Generation::new(1)?,
        /*predecessor*/ None,
    )?;
    let first = host
        .writer()
        .prepare_operation(first, "fixture.unknown.v1", "{}".to_string())
        .await?;
    host.writer()
        .mark_indeterminate(&first.occurrence_key, "fixture lost reply")
        .await?;
    let identity = NotesTargetIdentity {
        session_instance: "1".repeat(32),
        task_id: 7,
        incarnation: "2".repeat(32),
    };
    let payload = serde_json::to_string(
        &serde_json::json!({"schema_version":1,"action":"replace_note",
        "operation_id":"notes-fairness","destination_id":identity.destination_id(),"target":identity,"expected_revision":0,"text":"fair Notes"}),
    )?;
    let receipt = serde_json::to_vec(
        &serde_json::json!({"schema_version":1,"target":identity,"operation_id":"notes-fairness",
        "payload_sha256":Sha256Digest::for_bytes(payload.as_bytes()).as_str(),"result":{"status":"applied","previous_revision":0,
        "revision":1,"text_sha256":Sha256Digest::for_bytes(b"fair Notes").as_str()}}),
    )?;
    let (effect, mut application_effect) = UnixStream::pair()?;
    let (recovery, application_recovery) = UnixDatagram::pair()?;
    application_recovery.set_read_timeout(Some(Duration::from_secs(10)))?;
    application_effect.set_nonblocking(true)?;
    let target = Arc::new(ProductionNotesTarget::new(
        identity.clone(),
        Arc::new(AgentdNotesChannel::from_private_channels(effect, recovery)?),
    )?);
    let host = host.attach_additional_target(final_use, target)?;
    let intent = notes_operation_intent(
        &identity,
        &payload,
        StableId::new(config.identity().agent_id.as_str())?,
        Generation::new(1)?,
    )?;
    let notes = host
        .writer()
        .prepare_operation(intent, NOTES_REPLACE_TOPIC_V1, payload)
        .await?;
    host.writer()
        .mark_indeterminate(&notes.occurrence_key, "fixture applied with lost reply")
        .await?;
    let peer = std::thread::spawn(move || {
        let mut bytes = [0_u8; 2048];
        let length = application_recovery
            .recv(&mut bytes)
            .expect("observe request");
        let query: serde_json::Value =
            serde_json::from_slice(&bytes[..length]).expect("observe schema");
        assert_eq!(query["action"], "observe");
        application_recovery
            .send(&receipt)
            .expect("applied response");
        let length = application_recovery.recv(&mut bytes).expect("terminal ACK");
        let mut ack: serde_json::Value =
            serde_json::from_slice(&bytes[..length]).expect("ACK schema");
        assert_eq!(ack["action"], "acknowledge_terminal");
        assert_eq!(
            ack["receipt_sha256"],
            Sha256Digest::for_bytes(&receipt).as_str()
        );
        ack.as_object_mut().expect("ACK object").remove("action");
        ack["status"] = serde_json::json!("released");
        application_recovery
            .send(&serde_json::to_vec(&ack).expect("ACK reply"))
            .expect("released response");
        assert_eq!(
            application_effect.read(&mut [0_u8; 1]).unwrap_err().kind(),
            std::io::ErrorKind::WouldBlock
        );
    });
    assert_eq!(host.reconcile(/*limit*/ 1).await?, 1);
    assert_eq!(
        host.writer().status(&notes.occurrence_key).await?,
        LocalOutcomeState::Indeterminate
    );
    assert_eq!(host.clone().reconcile(/*limit*/ 1).await?, 1);
    assert_eq!(
        host.writer().status(&notes.occurrence_key).await?,
        LocalOutcomeState::Committed
    );
    assert_eq!(
        host.writer().status(&first.occurrence_key).await?,
        LocalOutcomeState::Indeterminate
    );
    assert_eq!(unknown.0.load(Ordering::SeqCst), 1);
    assert_eq!(issuer.requests.load(Ordering::SeqCst), 0);
    peer.join()
        .map_err(|_| "application recovery fixture failed")?;
    host.close().await?;
    Ok(())
}
