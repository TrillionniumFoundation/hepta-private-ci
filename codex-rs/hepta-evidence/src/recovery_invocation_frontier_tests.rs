use codex_hepta_contracts::PROVIDER_EVIDENCE_SCHEMA_VERSION;
use codex_hepta_contracts::ProviderInvocationIntent;
use codex_hepta_contracts::ProviderInvocationReceipt;
use codex_hepta_contracts::ProviderRequestBinding;
use codex_hepta_contracts::ProviderRequestKind;
use codex_hepta_contracts::ProviderTerminal;
use codex_hepta_contracts::ProviderTransport;
use codex_hepta_contracts::Sha256Digest;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use tempfile::TempDir;

use crate::EvidenceError;
use crate::HeptaEvidenceStore;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

fn sqlite_config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    )
}

fn intent(nonce: u128) -> ProviderInvocationIntent {
    ProviderInvocationIntent::new(
        nonce.to_be_bytes(),
        ProviderRequestBinding {
            schema_version: PROVIDER_EVIDENCE_SCHEMA_VERSION,
            thread_id: "thread-1".into(),
            turn_id: "turn-1".into(),
            host_request_binding_id_sha256: Sha256Digest::for_bytes(&nonce.to_be_bytes()),
            request_kind: ProviderRequestKind::Turn,
            provider_id: "provider-fixture".into(),
            provider_config_sha256: Sha256Digest::for_bytes(b"provider-config"),
            model: "model-fixture".into(),
            transport: ProviderTransport::Http,
            endpoint_sha256: Sha256Digest::for_bytes(b"/responses"),
            logical_request_sha256: Sha256Digest::for_bytes(b"logical"),
            wire_semantic_sha256: Sha256Digest::for_bytes(b"wire"),
            ephemeral_input_sha256: None,
            ephemeral_input_witness_sha256: None,
            previous_response_id_sha256: None,
            generate: true,
        },
    )
}

#[tokio::test]
async fn recovery_snapshot_commits_pending_invocations_and_terminal_states() -> Result<()> {
    let temp = TempDir::new()?;
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp)).await?;
    let mut before = store.recovery_snapshot().await?;
    for (index, terminal) in [
        ProviderTerminal::Completed {
            response_id_sha256: Sha256Digest::for_bytes(b"response-id"),
            response_items_sha256: Sha256Digest::for_bytes(b"items"),
            token_usage_sha256: Sha256Digest::for_bytes(b"usage"),
            end_turn: Some(true),
        },
        ProviderTerminal::CompletedUnary {
            response_items_sha256: Sha256Digest::for_bytes(b"unary-items"),
        },
        ProviderTerminal::Rejected {
            reason_code: "rejected".into(),
        },
        ProviderTerminal::NotDispatched {
            reason_code: "not_sent".into(),
        },
        ProviderTerminal::Indeterminate {
            reason_code: "lost_response".into(),
            partial_response_sha256: Some(Sha256Digest::for_bytes(b"partial")),
        },
    ]
    .into_iter()
    .enumerate()
    {
        let intent = intent(index as u128);
        store.claim_provider_intent(&intent).await?;
        let pending = store.recovery_snapshot().await?;
        assert_ne!(pending, before);
        store
            .append_provider_receipt(&ProviderInvocationReceipt::new(intent, terminal))
            .await?;
        let finished = store.recovery_snapshot().await?;
        assert_ne!(finished, pending);
        assert_eq!(
            finished.provider_invocation_rows,
            pending.provider_invocation_rows + 1
        );
        assert_eq!(store.recovery_snapshot().await?, finished);
        before = finished;
    }
    Ok(())
}

#[tokio::test]
async fn recovery_snapshot_commits_invocations_after_the_first_page() -> Result<()> {
    let temp = TempDir::new()?;
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp)).await?;
    for nonce in 0..256 {
        store.append_provider_intent(&intent(nonce)).await?;
    }
    let first_page = store.recovery_snapshot().await?;
    store.append_provider_intent(&intent(/*nonce*/ 256)).await?;
    let next_page = store.recovery_snapshot().await?;
    assert_ne!(next_page, first_page);
    assert_eq!(next_page.provider_invocation_rows, 257);
    assert_eq!(store.recovery_snapshot().await?, next_page);
    Ok(())
}

#[tokio::test]
async fn recovery_snapshot_refuses_duplicate_terminal_hidden_at_page_boundary() -> Result<()> {
    let temp = TempDir::new()?;
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite).await?;
    for nonce in 0..256 {
        let intent = intent(nonce);
        store.append_provider_intent(&intent).await?;
        store
            .append_provider_receipt(&ProviderInvocationReceipt::new(
                intent,
                ProviderTerminal::CompletedUnary {
                    response_items_sha256: Sha256Digest::for_bytes(b"items"),
                },
            ))
            .await?;
    }
    store.recovery_snapshot().await?;
    let original_rows: Vec<(i64, String)> =
        sqlx::query_as("SELECT seq, payload_json FROM provider_invocation_terminals ORDER BY seq")
            .fetch_all(&store.pool)
            .await?;
    let table: String = sqlx::query_scalar(
        "SELECT sql FROM sqlite_schema WHERE name = 'provider_invocation_terminals'",
    )
    .fetch_one(&store.pool)
    .await?;
    let schema_objects: Vec<String> = sqlx::query_scalar(
        "SELECT sql FROM sqlite_schema WHERE tbl_name = 'provider_invocation_terminals'
         AND type IN ('index', 'trigger') AND sql IS NOT NULL ORDER BY name",
    )
    .fetch_all(&store.pool)
    .await?;
    let mut transaction = store.pool.begin().await?;
    sqlx::query("CREATE TEMP TABLE terminal_backup AS SELECT * FROM provider_invocation_terminals")
        .execute(&mut *transaction)
        .await?;
    sqlx::query("DROP TABLE provider_invocation_terminals")
        .execute(&mut *transaction)
        .await?;
    sqlx::query(
        &table
            .replace(
                "seq INTEGER PRIMARY KEY AUTOINCREMENT",
                "seq INTEGER NOT NULL",
            )
            .replace("TEXT NOT NULL UNIQUE", "TEXT NOT NULL"),
    )
    .execute(&mut *transaction)
    .await?;
    sqlx::query("INSERT INTO provider_invocation_terminals SELECT * FROM terminal_backup")
        .execute(&mut *transaction)
        .await?;
    sqlx::query(
        "INSERT INTO provider_invocation_terminals
         SELECT * FROM terminal_backup WHERE seq = 256",
    )
    .execute(&mut *transaction)
    .await?;
    for object in schema_objects {
        sqlx::query(&object).execute(&mut *transaction).await?;
    }
    sqlx::query("DROP TABLE terminal_backup")
        .execute(&mut *transaction)
        .await?;
    transaction.commit().await?;
    store.close().await;
    // This restored image still passes the existing manifest, quick-check and
    // foreign-key admission. Its duplicate is invisible to seq-only pagination.
    let observed = HeptaEvidenceStore::open_existing_read_only(&sqlite).await?;
    let physical_rows: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM provider_invocation_terminals")
            .fetch_one(&observed.pool)
            .await?;
    assert_eq!(physical_rows, 257);
    let page_query = "SELECT seq, payload_json FROM provider_invocation_terminals
                      WHERE seq >= ? ORDER BY seq LIMIT 256";
    let first_page: Vec<(i64, String)> = sqlx::query_as(page_query)
        .bind(i64::MIN)
        .fetch_all(&observed.pool)
        .await?;
    assert_eq!(first_page, original_rows);
    let next_seq = first_page.last().expect("full first page").0 + 1;
    let next_page: Vec<(i64, String)> = sqlx::query_as(page_query)
        .bind(next_seq)
        .fetch_all(&observed.pool)
        .await?;
    assert!(next_page.is_empty(), "counterexample must hide row 257");
    let error = observed
        .recovery_snapshot()
        .await
        .expect_err("weakened invocation schema admitted");
    assert!(matches!(error, EvidenceError::Corrupt(ref message)
        if message.contains("provider invocation recovery schema")));
    observed.close().await;
    Ok(())
}

#[tokio::test]
async fn recovery_snapshot_revalidates_invocation_payloads_and_projected_columns() -> Result<()> {
    let temp = TempDir::new()?;
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp)).await?;
    let intent = intent(/*nonce*/ 1);
    store.append_provider_intent(&intent).await?;
    let mut receipt = ProviderInvocationReceipt::new(
        intent,
        ProviderTerminal::CompletedUnary {
            response_items_sha256: Sha256Digest::for_bytes(b"items"),
        },
    );
    store.append_provider_receipt(&receipt).await?;
    let before = store.recovery_snapshot().await?;
    for table in [
        "provider_invocation_intents",
        "provider_invocation_terminals",
    ] {
        let original: String = sqlx::query_scalar(&format!("SELECT payload_json FROM {table}"))
            .fetch_one(&store.pool)
            .await?;
        sqlx::query(&format!("DROP TRIGGER {table}_no_update"))
            .execute(&store.pool)
            .await?;
        sqlx::query(&format!("UPDATE {table} SET thread_id = 'other-thread'"))
            .execute(&store.pool)
            .await?;
        assert!(matches!(
            store.recovery_snapshot().await,
            Err(EvidenceError::Corrupt(_))
        ));
        sqlx::query(&format!("UPDATE {table} SET thread_id = 'thread-1'"))
            .execute(&store.pool)
            .await?;
        // A retained digest cannot bless replacement bytes, and a recomputed
        // digest cannot bless a valid but noncanonical encoding.
        for (payload, digest) in [
            (
                "{}".to_string(),
                Sha256Digest::for_bytes(original.as_bytes()),
            ),
            (
                format!("\n{original}"),
                Sha256Digest::for_bytes(format!("\n{original}").as_bytes()),
            ),
        ] {
            sqlx::query(&format!(
                "UPDATE {table} SET payload_json = ?, payload_sha256 = ?"
            ))
            .bind(payload)
            .bind(digest.as_str())
            .execute(&store.pool)
            .await?;
            assert!(matches!(
                store.recovery_snapshot().await,
                Err(EvidenceError::Corrupt(_))
            ));
        }
        sqlx::query(&format!(
            "UPDATE {table} SET payload_json = ?, payload_sha256 = ?"
        ))
        .bind(&original)
        .bind(Sha256Digest::for_bytes(original.as_bytes()).as_str())
        .execute(&store.pool)
        .await?;
        assert_eq!(store.recovery_snapshot().await?, before);
    }
    // A different valid terminal with the same count, sequence and timestamp
    // must change the frontier even after its payload digest is recomputed.
    receipt.terminal = ProviderTerminal::CompletedUnary {
        response_items_sha256: Sha256Digest::for_bytes(b"different response"),
    };
    let payload = String::from_utf8(crate::canonical::canonical_json(&receipt)?)?;
    sqlx::query("UPDATE provider_invocation_terminals SET payload_json = ?, payload_sha256 = ?")
        .bind(&payload)
        .bind(Sha256Digest::for_bytes(payload.as_bytes()).as_str())
        .execute(&store.pool)
        .await?;
    assert_ne!(store.recovery_snapshot().await?, before);
    Ok(())
}

#[tokio::test]
async fn recovery_snapshot_requires_the_terminals_authoritative_intent() -> Result<()> {
    let temp = TempDir::new()?;
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp)).await?;
    let intent = intent(/*nonce*/ 1);
    store.append_provider_intent(&intent).await?;
    store
        .append_provider_receipt(&ProviderInvocationReceipt::new(
            intent,
            ProviderTerminal::Indeterminate {
                reason_code: "lost_response".into(),
                partial_response_sha256: None,
            },
        ))
        .await?;
    store.recovery_snapshot().await?;
    let mut connection = store.pool.acquire().await?;
    sqlx::query("PRAGMA foreign_keys = OFF")
        .execute(&mut *connection)
        .await?;
    sqlx::query("DROP TRIGGER provider_invocation_intents_no_delete")
        .execute(&mut *connection)
        .await?;
    sqlx::query("DELETE FROM provider_invocation_intents")
        .execute(&mut *connection)
        .await?;
    drop(connection);
    let error = store
        .recovery_snapshot()
        .await
        .expect_err("orphaned terminal admitted");
    assert!(
        matches!(error, EvidenceError::Corrupt(ref message) if message.contains("authoritative intent"))
    );
    Ok(())
}

#[tokio::test]
async fn recovery_snapshot_refuses_invocation_column_type_corruption_without_panicking()
-> Result<()> {
    for table in [
        "provider_invocation_intents",
        "provider_invocation_terminals",
    ] {
        let temp = TempDir::new()?;
        let sqlite = sqlite_config(&temp);
        let store = HeptaEvidenceStore::open(&sqlite).await?;
        let intent = intent(/*nonce*/ 1);
        store.append_provider_intent(&intent).await?;
        store
            .append_provider_receipt(&ProviderInvocationReceipt::new(
                intent,
                ProviderTerminal::CompletedUnary {
                    response_items_sha256: Sha256Digest::for_bytes(b"items"),
                },
            ))
            .await?;
        let trigger_name = format!("{table}_no_update");
        let trigger: String = sqlx::query_scalar("SELECT sql FROM sqlite_schema WHERE name = ?")
            .bind(&trigger_name)
            .fetch_one(&store.pool)
            .await?;
        let mut transaction = store.pool.begin().await?;
        sqlx::query(&format!("DROP TRIGGER {trigger_name}"))
            .execute(&mut *transaction)
            .await?;
        sqlx::query(&format!("UPDATE {table} SET thread_id = X'ff'"))
            .execute(&mut *transaction)
            .await?;
        sqlx::query(&trigger).execute(&mut *transaction).await?;
        transaction.commit().await?;
        store.close().await;

        // The original schema/triggers and canonical payload remain intact.
        // Structural admission passes; snapshot decoding must return an error.
        let observed = HeptaEvidenceStore::open_existing_read_only(&sqlite).await?;
        let error = observed
            .recovery_snapshot()
            .await
            .expect_err("BLOB in TEXT column admitted");
        assert!(matches!(error, EvidenceError::Corrupt(ref message)
            if message.contains("invalid provider thread_id column")));
        observed.close().await;
    }
    Ok(())
}

#[tokio::test]
async fn recovery_snapshot_binds_invocation_sequence_and_recording_time() -> Result<()> {
    let temp = TempDir::new()?;
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp)).await?;
    store.append_provider_intent(&intent(/*nonce*/ 1)).await?;
    let before = store.recovery_snapshot().await?;
    sqlx::query("DROP TRIGGER provider_invocation_intents_no_update")
        .execute(&store.pool)
        .await?;
    sqlx::query("UPDATE provider_invocation_intents SET recorded_at_ms = recorded_at_ms + 1")
        .execute(&store.pool)
        .await?;
    let recorded = store.recovery_snapshot().await?;
    assert_ne!(recorded, before);
    sqlx::query("UPDATE provider_invocation_intents SET seq = ?")
        .bind(i64::MAX)
        .execute(&store.pool)
        .await?;
    let last_seq = store.recovery_snapshot().await?;
    assert_ne!(last_seq, recorded);
    assert_eq!(last_seq.provider_invocation_rows, 1);
    sqlx::query("UPDATE provider_invocation_intents SET seq = 0")
        .execute(&store.pool)
        .await?;
    assert!(matches!(
        store.recovery_snapshot().await,
        Err(EvidenceError::Corrupt(_))
    ));
    Ok(())
}
