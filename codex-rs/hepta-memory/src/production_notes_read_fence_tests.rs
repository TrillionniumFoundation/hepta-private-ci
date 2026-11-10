//! Original SQLite source evidence; application responses below are explicit
//! observer fixtures. Real Session/App reattachment is a separate qualification.

use super::*;
use crate::NotesDocumentState;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn notes_document_floor_survives_original_owner_reopen() -> TestResult {
    let temp = tempfile::tempdir()?;
    let fleet_path = temp.path().join("fleet");
    std::fs::create_dir(&fleet_path)?;
    let fleet = HeptaFleetRoot::parse(fleet_path.canonicalize()?)?;
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2d51")?;
    let layout = fleet.layout().agent(&owner);
    let store = CognitiveStore::open(&layout).await?;
    let authority = source(&owner, 1)?;
    let writer = ProductionDurableWriter::open_with_live_verifier(
        store.clone(),
        authority.clone(),
        Arc::new(Verifier),
        LEASE,
        /*generation*/ 1,
    )
    .await?;
    let (payload, identity, target) = fixture()?;
    let operation = prepare(&writer, payload, &identity).await?;
    let response: serde_json::Value = serde_json::from_str(&target.receipt)?;
    let document = NotesDocumentState {
        target: identity.clone(),
        revision: response["result"]["revision"].as_u64().ok_or("revision")?,
        text_sha256: Sha256Digest::parse(
            response["result"]["text_sha256"].as_str().ok_or("text")?,
        )?,
        receipt_pending: false,
    };
    let stale = NotesDocumentState {
        revision: 0,
        ..document.clone()
    };
    // An unresolved operation is not a committed floor or absence proof.
    writer.validate_notes_document_read(&stale).await?;
    assert_eq!(
        writer.reconcile_target_batch(&target, /*limit*/ 1).await?,
        1
    );
    assert_eq!(
        writer.status(&operation).await?,
        LocalOutcomeState::Committed
    );
    let before = writer.recovery_anchor().await?;
    writer.validate_notes_document_read(&document).await?;
    writer
        .validate_notes_document_read(&NotesDocumentState {
            receipt_pending: true,
            ..document.clone()
        })
        .await?;
    assert!(writer.validate_notes_document_read(&stale).await.is_err());
    assert!(
        writer
            .validate_notes_document_read(&NotesDocumentState {
                text_sha256: Sha256Digest::for_bytes(b"different at the same revision"),
                ..document.clone()
            })
            .await
            .is_err()
    );
    // External later edits need not have a source-side effect receipt.
    writer
        .validate_notes_document_read(&NotesDocumentState {
            revision: document.revision + 1,
            text_sha256: Sha256Digest::for_bytes(b"later local edit"),
            ..document.clone()
        })
        .await?;
    let mut another = stale.clone();
    another.target.incarnation = "33333333333333333333333333333333".into();
    writer.validate_notes_document_read(&another).await?;
    assert_eq!(writer.recovery_anchor().await?, before);
    assert_eq!(target.observations.load(Ordering::SeqCst), 1);
    assert_eq!(target.retirements.load(Ordering::SeqCst), 1);
    drop(writer);
    store.close().await;
    let reopened = ProductionDurableWriter::open_with_live_verifier(
        CognitiveStore::open(&layout).await?,
        authority,
        Arc::new(Verifier),
        LEASE,
        /*generation*/ 1,
    )
    .await?;
    assert!(reopened.validate_notes_document_read(&stale).await.is_err());
    reopened.validate_notes_document_read(&document).await?;
    assert_eq!(reopened.recovery_anchor().await?, before);
    let successor_store = reopened.store().clone();
    reopened.release().await?;
    drop(reopened);
    let successor = ProductionDurableWriter::open_with_live_verifier(
        successor_store,
        source(&owner, 2)?,
        Arc::new(Verifier),
        "notes-read-floor-successor",
        /*generation*/ 1,
    )
    .await?;
    let successor_anchor = successor.recovery_anchor().await?;
    // The new lease has no Notes receipts of its own. Its read floor must
    // still include the original lease's retained committed effect.
    assert!(
        successor
            .validate_notes_document_read(&stale)
            .await
            .is_err()
    );
    successor.validate_notes_document_read(&document).await?;
    assert_eq!(successor.recovery_anchor().await?, successor_anchor);
    Ok(())
}

#[tokio::test]
async fn notes_document_floor_uses_exact_maximum_and_rejects_source_contradiction() -> TestResult {
    let temp = tempfile::tempdir()?;
    let fleet_path = temp.path().join("fleet");
    std::fs::create_dir(&fleet_path)?;
    let fleet = HeptaFleetRoot::parse(fleet_path.canonicalize()?)?;
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2d52")?;
    let store = CognitiveStore::open(&fleet.layout().agent(&owner)).await?;
    let writer = ProductionDurableWriter::open_with_live_verifier(
        store,
        source(&owner, 1)?,
        Arc::new(Verifier),
        LEASE,
        /*generation*/ 1,
    )
    .await?;
    let (template, identity, _) = fixture()?;
    // These actual source journal entries use explicit target-response models
    // to exercise publication order and contradictions, not real App history.
    for (id, revision, text) in [
        ("floor-max", u64::MAX, "highest"),
        ("floor-later-source-lower-document", u64::MAX - 1, "lower"),
        ("floor-conflicting-source", u64::MAX, "contradictory"),
    ] {
        let mut request: serde_json::Value = serde_json::from_str(&template)?;
        request["operation_id"] = serde_json::json!(id);
        request["expected_revision"] = serde_json::json!(revision - 1);
        request["text"] = serde_json::json!(text);
        let payload = serde_json::to_string(&request)?;
        let target = Observer {
            destination: identity.destination_id(),
            receipt: serde_json::to_string(&serde_json::json!({
                "schema_version":1,"target":identity,"operation_id":id,
                "payload_sha256":Sha256Digest::for_bytes(payload.as_bytes()).as_str(),
                "result":{"status":"applied","previous_revision":revision - 1,
                    "revision":revision,"text_sha256":Sha256Digest::for_bytes(text.as_bytes()).as_str()}
            }))?,
            observations: AtomicUsize::new(0),
            retirements: AtomicUsize::new(0),
            lose_first_ack: AtomicBool::new(false),
        };
        prepare(&writer, payload, &identity).await?;
        assert_eq!(
            writer.reconcile_target_batch(&target, /*limit*/ 1).await?,
            1
        );
        let high = NotesDocumentState {
            target: identity.clone(),
            revision: u64::MAX,
            text_sha256: Sha256Digest::for_bytes(b"highest"),
            receipt_pending: false,
        };
        if id == "floor-conflicting-source" {
            assert!(writer.validate_notes_document_read(&high).await.is_err());
            assert!(
                writer
                    .validate_notes_document_read(&NotesDocumentState {
                        text_sha256: Sha256Digest::for_bytes(b"contradictory"),
                        ..high
                    })
                    .await
                    .is_err()
            );
        } else {
            writer.validate_notes_document_read(&high).await?;
            assert!(
                writer
                    .validate_notes_document_read(&NotesDocumentState {
                        revision: u64::MAX - 1,
                        text_sha256: Sha256Digest::for_bytes(b"lower"),
                        ..high
                    })
                    .await
                    .is_err()
            );
        }
    }
    Ok(())
}

#[tokio::test]
#[ignore = "explicit original-owner Notes history capacity qualification"]
async fn notes_document_floor_history_cap_refuses_without_ignoring_later_commits() -> TestResult {
    let temp = tempfile::tempdir()?;
    let fleet_path = temp.path().join("fleet");
    std::fs::create_dir(&fleet_path)?;
    let fleet = HeptaFleetRoot::parse(fleet_path.canonicalize()?)?;
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2d53")?;
    let store = CognitiveStore::open(&fleet.layout().agent(&owner)).await?;
    let writer = ProductionDurableWriter::open_with_live_verifier(
        store,
        source(&owner, 1)?,
        Arc::new(Verifier),
        LEASE,
        /*generation*/ 1,
    )
    .await?;
    let (template, identity, _) = fixture()?;
    let text = "bounded original-owner history";
    for predecessor in 0_u64..1025 {
        if predecessor == 1024 {
            writer
                .validate_notes_document_read(&NotesDocumentState {
                    target: identity.clone(),
                    revision: predecessor,
                    text_sha256: Sha256Digest::for_bytes(text.as_bytes()),
                    receipt_pending: false,
                })
                .await?;
        }
        let operation_id = format!("notes-read-cap-{predecessor}");
        let mut request: serde_json::Value = serde_json::from_str(&template)?;
        request["operation_id"] = serde_json::json!(operation_id);
        request["expected_revision"] = serde_json::json!(predecessor);
        request["text"] = serde_json::json!(text);
        let payload = serde_json::to_string(&request)?;
        let target = Observer {
            destination: identity.destination_id(),
            receipt: serde_json::to_string(&serde_json::json!({
                "schema_version":1,"target":identity,"operation_id":operation_id,
                "payload_sha256":Sha256Digest::for_bytes(payload.as_bytes()).as_str(),
                "result":{"status":"applied","previous_revision":predecessor,
                    "revision":predecessor + 1,"text_sha256":Sha256Digest::for_bytes(text.as_bytes()).as_str()}
            }))?,
            observations: AtomicUsize::new(0),
            retirements: AtomicUsize::new(0),
            lose_first_ack: AtomicBool::new(false),
        };
        prepare(&writer, payload, &identity).await?;
        assert_eq!(
            writer.reconcile_target_batch(&target, /*limit*/ 1).await?,
            1
        );
    }
    let before = writer.recovery_anchor().await?;
    let error = writer
        .validate_notes_document_read(&NotesDocumentState {
            target: identity,
            revision: 1025,
            text_sha256: Sha256Digest::for_bytes(text.as_bytes()),
            receipt_pending: false,
        })
        .await
        .expect_err("history over the cap must remain unavailable");
    assert!(matches!(error, ProductionWriterError::Durability(reason)
        if reason.contains("exceeds its bounded scan")));
    assert_eq!(writer.recovery_anchor().await?, before);
    Ok(())
}
