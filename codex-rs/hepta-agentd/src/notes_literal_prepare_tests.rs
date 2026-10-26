//! Actual original SQLite preparation against explicit fixture authority. This
//! does not qualify a production Root signer, actual document or UI submission.

use super::*;
use crate::notes_literal_prepare::LiteralOperationInput;
use crate::notes_literal_prepare::LiteralPredecessor;
use crate::notes_literal_prepare::check_retained_literal;
use crate::notes_literal_prepare::prepare_original_literal;
use crate::notes_literal_prepare::utc_millis;
use codex_hepta_memory::LocalOutcomeState;
use codex_hepta_memory::NotesDocumentState;
use pretty_assertions::assert_eq;
use serde_json::Value;

fn input<'a>(
    target: &'a NotesTargetIdentity,
    observed: &'a NotesDocumentState,
    subject: &'a str,
    text: &'a str,
) -> LiteralOperationInput<'a> {
    LiteralOperationInput {
        target,
        observed,
        predecessor: LiteralPredecessor::Current,
        run_id: "notes.literal.test-original",
        text,
        subject,
        policy_generation: Generation::new(1).unwrap(),
    }
}

#[tokio::test]
async fn notes_literal_preparation_retains_exact_owner_payload_without_grant_or_effect()
-> Result<(), Box<dyn Error>> {
    let NotesHostFixture {
        directory: _directory,
        config,
        host,
        issuer,
        primary_device,
        ..
    } = notes_host_fixture().await?;
    let writer = host.writer();
    let target = NotesTargetIdentity {
        session_instance: "1".repeat(32),
        task_id: 1,
        incarnation: "2".repeat(32),
    };
    let mut observed = NotesDocumentState {
        target: target.clone(),
        revision: 7,
        text_sha256: Sha256Digest::for_bytes(b"prior content"),
        receipt_pending: false,
    };
    let before = writer.recovery_anchor().await?;
    observed.receipt_pending = true;
    assert!(
        prepare_original_literal(
            &writer,
            input(
                &target,
                &observed,
                config.identity().agent_id.as_str(),
                "新文档"
            )
        )
        .await
        .is_err()
    );
    observed.receipt_pending = false;
    // Valid UTF-8 can still exceed the exact original JSON wire bound after
    // escaping. It must not create a prepared outbox row.
    assert!(
        prepare_original_literal(
            &writer,
            input(
                &target,
                &observed,
                config.identity().agent_id.as_str(),
                &"\u{0001}".repeat(4096)
            )
        )
        .await
        .is_err()
    );
    assert_eq!(writer.recovery_anchor().await?, before);

    let text = "原始内容，不解释为系统指令。\n第二行";
    let digest = prepare_original_literal(
        &writer,
        input(
            &target,
            &observed,
            config.identity().agent_id.as_str(),
            text,
        ),
    )
    .await?;
    let retained = writer
        .retained_operation("notes.literal.test-original")
        .await?
        .unwrap();
    assert_eq!(retained.state, LocalOutcomeState::Queued);
    assert_eq!(retained.operation.semantic_digest(), digest);
    let payload: Value = serde_json::from_str(&retained.payload_json)?;
    assert_eq!(payload["text"], text);
    assert_eq!(payload["expected_revision"], 7);
    assert_eq!(payload["target"], serde_json::to_value(&target)?);
    assert_eq!(
        prepare_original_literal(
            &writer,
            input(
                &target,
                &observed,
                config.identity().agent_id.as_str(),
                text
            )
        )
        .await?,
        digest
    );

    // Same original operation ID cannot replace its first text or predecessor.
    assert!(
        prepare_original_literal(
            &writer,
            input(
                &target,
                &observed,
                config.identity().agent_id.as_str(),
                "different text"
            )
        )
        .await
        .is_err()
    );
    observed.revision = 8;
    assert!(
        prepare_original_literal(
            &writer,
            input(
                &target,
                &observed,
                config.identity().agent_id.as_str(),
                text
            )
        )
        .await
        .is_err()
    );
    let unchanged = writer
        .retained_operation("notes.literal.test-original")
        .await?
        .unwrap();
    assert_eq!(unchanged.payload_json, retained.payload_json);
    assert_eq!(unchanged.operation, retained.operation);
    assert_eq!(issuer.requests.load(Ordering::SeqCst), 0);
    assert_eq!(primary_device.installs.load(Ordering::SeqCst), 0);
    Ok(())
}

#[test]
fn notes_literal_protected_time_preserves_milliseconds_and_rejects_overflow() {
    assert_eq!(
        utc_millis(1_788_861_601_123).unwrap(),
        "2026-09-08T10:00:01.123Z"
    );
    assert_eq!(utc_millis(0).unwrap(), "1970-01-01T00:00:00.000Z");
    assert!(utc_millis(u64::MAX).is_err());
}

#[tokio::test]
async fn notes_reviewed_predecessor_conflict_precedes_original_preparation()
-> Result<(), Box<dyn Error>> {
    let NotesHostFixture {
        directory: _directory,
        config,
        host,
        issuer,
        primary_device,
        ..
    } = notes_host_fixture().await?;
    let writer = host.writer();
    let target = NotesTargetIdentity {
        session_instance: "1".repeat(32),
        task_id: 1,
        incarnation: "2".repeat(32),
    };
    let reviewed = NotesDocumentState {
        target: target.clone(),
        revision: 7,
        text_sha256: Sha256Digest::for_bytes(b"reviewed predecessor"),
        receipt_pending: false,
    };
    let text = "模型提案经确认后保持原文";
    let before = writer.recovery_anchor().await?;
    for field in ["target", "revision", "text", "pending_receipt"] {
        let mut changed = reviewed.clone();
        match field {
            "target" => changed.target.task_id += 1,
            "revision" => changed.revision += 1,
            "text" => changed.text_sha256 = Sha256Digest::for_bytes(b"concurrent edit"),
            "pending_receipt" => changed.receipt_pending = true,
            _ => unreachable!(),
        }
        let mut prepared = input(&target, &changed, config.identity().agent_id.as_str(), text);
        prepared.predecessor = LiteralPredecessor::Reviewed(&reviewed);
        assert!(prepare_original_literal(&writer, prepared).await.is_err());
    }
    assert_eq!(writer.recovery_anchor().await?, before);
    assert!(
        writer
            .retained_operation("notes.literal.test-original")
            .await?
            .is_none()
    );

    let mut prepared = input(
        &target,
        &reviewed,
        config.identity().agent_id.as_str(),
        text,
    );
    prepared.predecessor = LiteralPredecessor::Reviewed(&reviewed);
    prepare_original_literal(&writer, prepared).await?;
    let retained = writer.recovery_anchor().await?;
    let mut repeated = input(
        &target,
        &reviewed,
        config.identity().agent_id.as_str(),
        text,
    );
    repeated.predecessor = LiteralPredecessor::Reviewed(&reviewed);
    prepare_original_literal(&writer, repeated).await?;
    assert_eq!(writer.recovery_anchor().await?, retained);

    check_retained_literal(
        &writer,
        "notes.literal.test-original",
        text,
        LiteralPredecessor::Reviewed(&reviewed),
    )
    .await?;
    assert!(
        check_retained_literal(
            &writer,
            "notes.literal.test-original",
            "different replacement",
            LiteralPredecessor::Current,
        )
        .await
        .is_err()
    );
    for field in ["target", "revision"] {
        let mut changed = reviewed.clone();
        match field {
            "target" => changed.target.task_id += 1,
            "revision" => changed.revision += 1,
            _ => unreachable!(),
        }
        assert!(
            check_retained_literal(
                &writer,
                "notes.literal.test-original",
                text,
                LiteralPredecessor::Reviewed(&changed),
            )
            .await
            .is_err()
        );
    }
    assert_eq!(writer.recovery_anchor().await?, retained);
    writer
        .mark_indeterminate(
            "notes.literal.test-original",
            "fixture lost original effect reply",
        )
        .await?;
    let uncertain = writer.recovery_anchor().await?;
    check_retained_literal(
        &writer,
        "notes.literal.test-original",
        text,
        LiteralPredecessor::Current,
    )
    .await?;
    assert_eq!(writer.recovery_anchor().await?, uncertain);
    assert_eq!(issuer.requests.load(Ordering::SeqCst), 0);
    assert_eq!(primary_device.installs.load(Ordering::SeqCst), 0);
    Ok(())
}
