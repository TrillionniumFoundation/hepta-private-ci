//! Actual host and private endpoints with an explicit prior-receipt fixture.
use super::*;
use crate::AgentdNotesChannel;
use crate::AgentdNotesDocumentObserver;
use codex_hepta_memory::ProductionNotesTarget;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn notes_objective_previous_receipt_host_reconciles_without_registering_dispatch_or_issuer()
-> Result<(), Box<dyn Error>> {
    let NotesHostFixture {
        directory: _directory,
        config,
        host,
        final_use,
        issuer,
        primary_device,
        ..
    } = notes_host_fixture().await?;
    let golden: serde_json::Value =
        serde_json::from_str(include_str!("../tests/fixtures/notes-target-v1.json"))?;
    let payload = golden["request_utf8"]
        .as_str()
        .ok_or("payload")?
        .to_string();
    let source: serde_json::Value = serde_json::from_str(&payload)?;
    let old: NotesTargetIdentity = serde_json::from_value(source["target"].clone())?;
    let receipt = golden["application_response_utf8"]
        .as_str()
        .ok_or("receipt")?
        .to_string();
    let intent = notes_operation_intent(
        &old,
        &payload,
        StableId::new(config.identity().agent_id.as_str())?,
        Generation::new(1)?,
    )?;
    let queued = host
        .writer()
        .prepare_operation(intent, NOTES_REPLACE_TOPIC_V1, payload)
        .await?;
    host.writer()
        .mark_indeterminate(
            &queued.occurrence_key,
            "explicit fixture old application lost effect response",
        )
        .await?;
    let current = NotesTargetIdentity {
        session_instance: "3".repeat(32),
        task_id: 1,
        incarnation: "4".repeat(32),
    };
    let (effect, mut app_effect) = UnixStream::pair()?;
    app_effect.set_nonblocking(true)?;
    let (recovery, application) = UnixDatagram::pair()?;
    let target = ProductionNotesTarget::new(
        current.clone(),
        Arc::new(AgentdNotesChannel::from_private_channels(effect, recovery)?),
    )?;
    let observer = AgentdNotesDocumentObserver::new(target.document_observer());
    let host = host
        .attach_target(final_use.clone(), Arc::new(target), issuer.clone())?
        .attach_additional_target(
            final_use,
            Arc::new(ProductionHos2Target::new(primary_device)),
        )?;
    let expected_old = old.clone();
    let peer = std::thread::spawn(move || -> Result<(), String> {
        application
            .set_read_timeout(Some(Duration::from_secs(5)))
            .map_err(|error| error.to_string())?;
        for action in ["read_previous_receipt", "observe", "acknowledge_terminal"] {
            let mut bytes = [0_u8; 8192];
            let length = application
                .recv(&mut bytes)
                .map_err(|error| error.to_string())?;
            let request: serde_json::Value = serde_json::from_slice(&bytes[..length]).unwrap();
            assert_eq!(request["action"], action);
            let response = match action {
                "read_previous_receipt" => {
                    assert_eq!(request["target"], serde_json::to_value(&current).unwrap());
                    serde_json::to_vec(&serde_json::json!({"schema_version":1,"action":"previous_receipt","target":current,
                        "request_id":request["request_id"],"pending_receipt":serde_json::from_str::<serde_json::Value>(&receipt).unwrap()})).unwrap()
                }
                "observe" => {
                    assert_eq!(
                        request["target"],
                        serde_json::to_value(&expected_old).unwrap()
                    );
                    receipt.as_bytes().to_vec()
                }
                "acknowledge_terminal" => {
                    assert_eq!(
                        request["target"],
                        serde_json::to_value(&expected_old).unwrap()
                    );
                    assert_eq!(
                        request["receipt_sha256"],
                        Sha256Digest::for_bytes(receipt.as_bytes()).as_str()
                    );
                    serde_json::to_vec(&serde_json::json!({"schema_version":1,"target":expected_old,
                        "operation_id":request["operation_id"],"payload_sha256":request["payload_sha256"],
                        "receipt_sha256":request["receipt_sha256"],"status":"released"})).unwrap()
                }
                _ => unreachable!(),
            };
            application
                .send(&response)
                .map_err(|error| error.to_string())?;
        }
        Ok(())
    });
    let host = host.attach_previous_notes_recovery(&observer).await?;
    assert_eq!(
        host.destination_count(),
        2,
        "old receipt target must not become a third dispatcher"
    );
    assert_eq!(
        host.reconcile_for_destination(HOS2_DESTINATION_V1, /*limit*/ 1)
            .await?,
        0
    );
    assert_eq!(
        host.writer().status(&queued.occurrence_key).await?,
        LocalOutcomeState::Indeterminate
    );
    assert_eq!(
        host.reconcile_for_destination(&observer.target().destination_id(), /*limit*/ 1)
            .await?,
        1
    );
    assert_eq!(
        host.writer().status(&queued.occurrence_key).await?,
        LocalOutcomeState::Committed
    );
    assert!(
        host.dispatch_to_with_grant_provider(&old.destination_id(), queued)
            .await
            .is_err()
    );
    assert_eq!(issuer.requests.load(Ordering::SeqCst), 0);
    assert_eq!(
        app_effect.read(&mut [0_u8; 1]).unwrap_err().kind(),
        std::io::ErrorKind::WouldBlock
    );
    peer.join().expect("old receipt peer")?;
    Ok(())
}
