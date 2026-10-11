use std::borrow::Cow;

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
use sqlx::migrate::Migrator;
use tempfile::TempDir;

use crate::AppendDisposition;
use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::ProviderBindingState;
use crate::ProviderIntentClaimDisposition;

fn sqlite_config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    )
}

fn binding(thread_id: &str, logical: &[u8], wire: &[u8]) -> ProviderRequestBinding {
    ProviderRequestBinding {
        schema_version: PROVIDER_EVIDENCE_SCHEMA_VERSION,
        thread_id: thread_id.to_string(),
        turn_id: "turn-1".to_string(),
        host_request_binding_id_sha256: Sha256Digest::for_bytes(b"host-request-binding-1"),
        request_kind: ProviderRequestKind::Turn,
        provider_id: "provider-fixture".to_string(),
        provider_config_sha256: Sha256Digest::for_bytes(b"provider-config"),
        model: "model-fixture".to_string(),
        transport: ProviderTransport::Http,
        endpoint_sha256: Sha256Digest::for_bytes(b"/responses"),
        logical_request_sha256: Sha256Digest::for_bytes(logical),
        wire_semantic_sha256: Sha256Digest::for_bytes(wire),
        ephemeral_input_sha256: None,
        ephemeral_input_witness_sha256: None,
        previous_response_id_sha256: None,
        generate: true,
    }
}

#[tokio::test]
async fn provider_intent_rejects_orphaned_ephemeral_digests_before_insert() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    for (nonce, input_present) in [(91, true), (92, false)] {
        let mut binding = binding("thread-1", b"logical", b"wire");
        if input_present {
            binding.ephemeral_input_sha256 = Some(Sha256Digest::for_bytes(b"orphaned-input"));
        } else {
            binding.ephemeral_input_witness_sha256 =
                Some(Sha256Digest::for_bytes(b"orphaned-witness"));
        }
        let intent = ProviderInvocationIntent::new([nonce; 16], binding);

        let error = store
            .append_provider_intent(&intent)
            .await
            .expect_err("orphaned ephemeral digest must fail closed");
        assert!(matches!(error, EvidenceError::InvalidRecord(_)));
    }
    assert_eq!(
        store
            .pending_provider_attempt_count()
            .await
            .expect("pending count"),
        0
    );
}

fn intent(nonce: u8) -> ProviderInvocationIntent {
    ProviderInvocationIntent::new([nonce; 16], binding("thread-1", b"logical", b"wire"))
}

fn ephemeral_intent(nonce: u8, thread_id: &str) -> ProviderInvocationIntent {
    let mut binding = binding(thread_id, b"logical-with-ephemeral", b"wire-with-ephemeral");
    binding.ephemeral_input_sha256 = Some(Sha256Digest::for_bytes(b"ephemeral-input"));
    binding.ephemeral_input_witness_sha256 =
        Some(Sha256Digest::for_bytes(b"ephemeral-input-witness"));
    ProviderInvocationIntent::new([nonce; 16], binding)
}

fn migrator_through(version: i64) -> Migrator {
    let migrator = sqlx::migrate!("./migrations");
    Migrator {
        migrations: Cow::Owned(
            migrator
                .migrations
                .iter()
                .filter(|migration| migration.version <= version)
                .cloned()
                .collect(),
        ),
        ignore_missing: migrator.ignore_missing,
        locking: migrator.locking,
        table_name: migrator.table_name.clone(),
        create_schemas: migrator.create_schemas.clone(),
        no_tx: migrator.no_tx,
    }
}

async fn insert_pre_0006_intent(
    pool: &sqlx::SqlitePool,
    intent: &ProviderInvocationIntent,
    recorded_at_ms: i64,
) {
    let payload = crate::canonical::canonical_json(intent).expect("canonical provider intent");
    let payload_json = String::from_utf8(payload.clone()).expect("UTF-8 provider intent");
    let payload_sha256 = Sha256Digest::for_bytes(&payload);
    let binding = &intent.binding;
    sqlx::query(
        "INSERT INTO provider_invocation_intents (
            attempt_id, request_binding_id, attempt_nonce_sha256,
            host_request_binding_id_sha256, thread_id, turn_id,
            request_kind, provider_id, provider_config_sha256, model, transport,
            endpoint_sha256, logical_request_sha256, wire_semantic_sha256,
            previous_response_id_sha256, generate, schema_version,
            payload_json, payload_sha256, recorded_at_ms
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(intent.attempt_id.as_str())
    .bind(intent.request_binding_id.as_str())
    .bind(intent.attempt_nonce_sha256.as_str())
    .bind(binding.host_request_binding_id_sha256.as_str())
    .bind(&binding.thread_id)
    .bind(&binding.turn_id)
    .bind(binding.request_kind.as_str())
    .bind(&binding.provider_id)
    .bind(binding.provider_config_sha256.as_str())
    .bind(&binding.model)
    .bind(binding.transport.as_str())
    .bind(binding.endpoint_sha256.as_str())
    .bind(binding.logical_request_sha256.as_str())
    .bind(binding.wire_semantic_sha256.as_str())
    .bind(
        binding
            .previous_response_id_sha256
            .as_ref()
            .map(Sha256Digest::as_str),
    )
    .bind(binding.generate)
    .bind(i64::from(PROVIDER_EVIDENCE_SCHEMA_VERSION))
    .bind(payload_json)
    .bind(payload_sha256.as_str())
    .bind(recorded_at_ms)
    .execute(pool)
    .await
    .expect("insert pre-0006 provider intent");
}

async fn insert_pre_0006_receipt(
    pool: &sqlx::SqlitePool,
    receipt: &ProviderInvocationReceipt,
    recorded_at_ms: i64,
) {
    let payload = crate::canonical::canonical_json(receipt).expect("canonical provider receipt");
    let payload_json = String::from_utf8(payload.clone()).expect("UTF-8 provider receipt");
    let payload_sha256 = Sha256Digest::for_bytes(&payload);
    sqlx::query(
        "INSERT INTO provider_invocation_terminals (
            receipt_id, attempt_id, request_binding_id, thread_id, turn_id,
            terminal_kind, schema_version, payload_json, payload_sha256, recorded_at_ms
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(receipt.receipt_id.as_str())
    .bind(receipt.attempt_id.as_str())
    .bind(receipt.request_binding_id.as_str())
    .bind(&receipt.intent.binding.thread_id)
    .bind(&receipt.intent.binding.turn_id)
    .bind(receipt.terminal.kind())
    .bind(i64::from(PROVIDER_EVIDENCE_SCHEMA_VERSION))
    .bind(payload_json)
    .bind(payload_sha256.as_str())
    .bind(recorded_at_ms)
    .execute(pool)
    .await
    .expect("insert pre-0006 provider receipt");
}

fn completed(intent: ProviderInvocationIntent, output: &[u8]) -> ProviderInvocationReceipt {
    ProviderInvocationReceipt::new(
        intent,
        ProviderTerminal::Completed {
            response_id_sha256: Sha256Digest::for_bytes(b"response-id"),
            response_items_sha256: Sha256Digest::for_bytes(output),
            token_usage_sha256: Sha256Digest::for_bytes(b"token-usage"),
            end_turn: Some(true),
        },
    )
}

#[tokio::test]
async fn migration_0006_backfills_ephemeral_projection_without_rewriting_evidence() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let path = sqlite.home().join("hepta_evidence_2.sqlite");
    let pre_0006 = sqlite
        .open_durable_evidence_pool(&path)
        .await
        .expect("open pre-0006 evidence");
    migrator_through(5)
        .run(&pre_0006)
        .await
        .expect("apply lineage through 0005");

    let attached = ephemeral_intent(81, "thread-attached");
    let receipt = completed(attached.clone(), b"attached-output");
    let mut plain_binding = binding("thread-plain", b"plain-logical", b"plain-wire");
    plain_binding.host_request_binding_id_sha256 = Sha256Digest::for_bytes(b"plain-host-binding");
    let plain = ProviderInvocationIntent::new([82; 16], plain_binding);
    insert_pre_0006_intent(&pre_0006, &attached, 8_100).await;
    insert_pre_0006_receipt(&pre_0006, &receipt, 8_101).await;
    insert_pre_0006_intent(&pre_0006, &plain, 8_200).await;
    let intent_before = sqlx::query_as::<_, (String, String, String, String, i64)>(
        "SELECT attempt_id, request_binding_id, payload_json, payload_sha256, recorded_at_ms
         FROM provider_invocation_intents WHERE attempt_id = ?",
    )
    .bind(attached.attempt_id.as_str())
    .fetch_one(&pre_0006)
    .await
    .expect("read pre-0006 intent");
    let receipt_before = sqlx::query_as::<_, (String, String, String, String, i64)>(
        "SELECT receipt_id, attempt_id, payload_json, payload_sha256, recorded_at_ms
         FROM provider_invocation_terminals WHERE receipt_id = ?",
    )
    .bind(receipt.receipt_id.as_str())
    .fetch_one(&pre_0006)
    .await
    .expect("read pre-0006 receipt");
    pre_0006.close().await;

    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("upgrade evidence through 0006");
    let raw = sqlite
        .open_durable_evidence_pool(store.path())
        .await
        .expect("open upgraded evidence");
    let intent_after = sqlx::query_as::<_, (String, String, String, String, i64)>(
        "SELECT attempt_id, request_binding_id, payload_json, payload_sha256, recorded_at_ms
         FROM provider_invocation_intents WHERE attempt_id = ?",
    )
    .bind(attached.attempt_id.as_str())
    .fetch_one(&raw)
    .await
    .expect("read upgraded intent");
    let receipt_after = sqlx::query_as::<_, (String, String, String, String, i64)>(
        "SELECT receipt_id, attempt_id, payload_json, payload_sha256, recorded_at_ms
         FROM provider_invocation_terminals WHERE receipt_id = ?",
    )
    .bind(receipt.receipt_id.as_str())
    .fetch_one(&raw)
    .await
    .expect("read upgraded receipt");
    assert_eq!(intent_after, intent_before);
    assert_eq!(receipt_after, receipt_before);

    let attached_projection = sqlx::query_as::<_, (Option<String>, Option<String>)>(
        "SELECT ephemeral_input_sha256, ephemeral_input_witness_sha256
         FROM provider_invocation_intents WHERE attempt_id = ?",
    )
    .bind(attached.attempt_id.as_str())
    .fetch_one(&raw)
    .await
    .expect("read attached projection");
    assert_eq!(
        attached_projection,
        (
            attached
                .binding
                .ephemeral_input_sha256
                .as_ref()
                .map(|digest| digest.as_str().to_string()),
            attached
                .binding
                .ephemeral_input_witness_sha256
                .as_ref()
                .map(|digest| digest.as_str().to_string()),
        )
    );
    let plain_projection = sqlx::query_as::<_, (Option<String>, Option<String>)>(
        "SELECT ephemeral_input_sha256, ephemeral_input_witness_sha256
         FROM provider_invocation_intents WHERE attempt_id = ?",
    )
    .bind(plain.attempt_id.as_str())
    .fetch_one(&raw)
    .await
    .expect("read plain projection");
    assert_eq!(plain_projection, (None, None));
    raw.close().await;

    let stored = store
        .get_provider_attempt(&attached.attempt_id)
        .await
        .expect("read migrated attempt")
        .expect("migrated attempt");
    assert_eq!(stored.intent.intent, attached);
    assert_eq!(stored.receipt.expect("migrated receipt").receipt, receipt);
    assert_eq!(
        store
            .append_provider_intent(&attached)
            .await
            .expect("replay migrated intent"),
        AppendDisposition::AlreadyPresent
    );
    assert_eq!(
        store
            .append_provider_receipt(&receipt)
            .await
            .expect("replay migrated receipt"),
        AppendDisposition::AlreadyPresent
    );
    assert_eq!(
        store
            .list_pending_provider_intents("thread-plain", 0, 10)
            .await
            .expect("read migrated pending intents")[0]
            .intent,
        plain
    );

    let mut retry_binding = attached.binding.clone();
    retry_binding.ephemeral_input_witness_sha256 =
        Some(Sha256Digest::for_bytes(b"rotated-witness"));
    let retry = ProviderInvocationIntent::new([83; 16], retry_binding);
    assert_eq!(
        store
            .claim_provider_intent(&retry)
            .await
            .expect("claim after migration"),
        ProviderIntentClaimDisposition::BlockedByBinding(ProviderBindingState::Completed)
    );
}

#[tokio::test]
async fn ephemeral_projection_round_trips_and_detects_projection_corruption() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let intent = ephemeral_intent(84, "thread-ephemeral");
    store
        .append_provider_intent(&intent)
        .await
        .expect("append ephemeral intent");
    assert_eq!(
        store
            .list_pending_provider_intents("thread-ephemeral", 0, 10)
            .await
            .expect("read ephemeral pending intent")[0]
            .intent,
        intent
    );
    drop(store);

    let reopened = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("reopen evidence");
    assert_eq!(
        reopened
            .get_provider_attempt(&intent.attempt_id)
            .await
            .expect("read ephemeral attempt")
            .expect("ephemeral attempt")
            .intent
            .intent,
        intent
    );
    let raw = sqlite
        .open_durable_evidence_pool(reopened.path())
        .await
        .expect("open raw evidence");
    sqlx::query("DROP TRIGGER provider_invocation_intents_no_update")
        .execute(&raw)
        .await
        .expect("disable immutable trigger for corruption simulation");
    let error = sqlx::query(
        "UPDATE provider_invocation_intents SET ephemeral_input_sha256 = NULL
         WHERE attempt_id = ?",
    )
    .bind(intent.attempt_id.as_str())
    .execute(&raw)
    .await
    .expect_err("one-sided ephemeral projection must violate its CHECK");
    assert!(error.to_string().contains("CHECK constraint failed"));
    sqlx::query(
        "UPDATE provider_invocation_intents SET ephemeral_input_sha256 = ?
         WHERE attempt_id = ?",
    )
    .bind(Sha256Digest::for_bytes(b"drifted-ephemeral-input").as_str())
    .bind(intent.attempt_id.as_str())
    .execute(&raw)
    .await
    .expect("simulate valid-shape projection corruption");
    assert!(matches!(
        reopened
            .get_provider_attempt(&intent.attempt_id)
            .await
            .expect_err("projection corruption must fail closed"),
        EvidenceError::Corrupt(_)
    ));
    sqlx::query(
        "CREATE TRIGGER provider_invocation_intents_no_update
         BEFORE UPDATE ON provider_invocation_intents
         BEGIN
             SELECT RAISE(ABORT, 'provider invocation intents are immutable');
         END",
    )
    .execute(&raw)
    .await
    .expect("restore immutable trigger");
    raw.close().await;
    drop(reopened);

    let error = match HeptaEvidenceStore::open(&sqlite).await {
        Ok(_) => panic!("startup projection scan must fail closed"),
        Err(error) => error,
    };
    assert!(matches!(error, EvidenceError::Corrupt(_)));
}

#[tokio::test]
async fn migration_0006_rejects_invalid_payload_shapes_and_rolls_back() {
    for (offset, corruption) in ["explicit-null", "non-text", "orphan", "malformed"]
        .into_iter()
        .enumerate()
    {
        let temp = TempDir::new().expect("temp dir");
        let sqlite = sqlite_config(&temp);
        let path = sqlite.home().join("hepta_evidence_2.sqlite");
        let pre_0006 = sqlite
            .open_durable_evidence_pool(&path)
            .await
            .expect("open pre-0006 evidence");
        migrator_through(5)
            .run(&pre_0006)
            .await
            .expect("apply lineage through 0005");
        let intent = ephemeral_intent(90 + offset as u8, "thread-invalid-migration");
        insert_pre_0006_intent(&pre_0006, &intent, 9_000 + offset as i64).await;
        let original: String = sqlx::query_scalar(
            "SELECT payload_json FROM provider_invocation_intents WHERE attempt_id = ?",
        )
        .bind(intent.attempt_id.as_str())
        .fetch_one(&pre_0006)
        .await
        .expect("read canonical pre-0006 payload");
        let input_field = format!(
            "\"ephemeral_input_sha256\":\"{}\"",
            intent
                .binding
                .ephemeral_input_sha256
                .as_ref()
                .expect("input digest")
                .as_str()
        );
        let witness_field = format!(
            ",\"ephemeral_input_witness_sha256\":\"{}\"",
            intent
                .binding
                .ephemeral_input_witness_sha256
                .as_ref()
                .expect("witness digest")
                .as_str()
        );
        let invalid = match corruption {
            "explicit-null" => {
                original.replacen(&input_field, "\"ephemeral_input_sha256\":null", 1)
            }
            "non-text" => original.replacen(&input_field, "\"ephemeral_input_sha256\":17", 1),
            "orphan" => original.replacen(&witness_field, "", 1),
            "malformed" => "{".to_string(),
            _ => unreachable!(),
        };
        assert_ne!(invalid, original, "{corruption} fixture must mutate JSON");
        let invalid_sha256 = Sha256Digest::for_bytes(invalid.as_bytes());
        let mut fixture_connection = pre_0006
            .acquire()
            .await
            .expect("acquire legacy corruption fixture connection");
        sqlx::query("DROP TRIGGER provider_invocation_intents_no_update")
            .execute(&mut *fixture_connection)
            .await
            .expect("disable immutable trigger for legacy corruption fixture");
        sqlx::query(
            "UPDATE provider_invocation_intents
             SET payload_json = ?, payload_sha256 = ? WHERE attempt_id = ?",
        )
        .bind(invalid)
        .bind(invalid_sha256.as_str())
        .bind(intent.attempt_id.as_str())
        .execute(&mut *fixture_connection)
        .await
        .expect("write invalid legacy payload shape");
        sqlx::query(
            "CREATE TRIGGER provider_invocation_intents_no_update
             BEFORE UPDATE ON provider_invocation_intents
             BEGIN
                 SELECT RAISE(ABORT, 'provider invocation intents are immutable');
             END",
        )
        .execute(&mut *fixture_connection)
        .await
        .expect("restore pre-0006 immutable trigger");
        drop(fixture_connection);
        pre_0006.close().await;

        let error = match HeptaEvidenceStore::open(&sqlite).await {
            Ok(_) => panic!("{corruption} legacy payload must fail migration"),
            Err(error) => error,
        };
        assert!(
            matches!(error, EvidenceError::Corrupt(_)),
            "{corruption}: {error:?}"
        );
        let rolled_back = sqlite
            .open_durable_evidence_pool(&path)
            .await
            .expect("open rolled-back evidence");
        let projected_columns: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM pragma_table_info('provider_invocation_intents')
             WHERE name IN ('ephemeral_input_sha256', 'ephemeral_input_witness_sha256')",
        )
        .fetch_one(&rolled_back)
        .await
        .expect("inspect rolled-back columns");
        assert_eq!(projected_columns, 0, "{corruption}");
        let migration_rows: i64 =
            sqlx::query_scalar("SELECT COUNT(*) FROM _sqlx_migrations WHERE version = 6")
                .fetch_one(&rolled_back)
                .await
                .expect("inspect rolled-back migration ledger");
        assert_eq!(migration_rows, 0, "{corruption}");
        let immutable_trigger: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM sqlite_schema
             WHERE type = 'trigger' AND name = 'provider_invocation_intents_no_update'",
        )
        .fetch_one(&rolled_back)
        .await
        .expect("inspect rolled-back immutable trigger");
        assert_eq!(immutable_trigger, 1, "{corruption}");
        rolled_back.close().await;
    }
}

#[tokio::test]
async fn provider_records_are_idempotent_pending_and_persistent() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let intent = intent(1);
    let receipt = completed(intent.clone(), b"output");

    assert_eq!(
        store.append_provider_intent(&intent).await.expect("intent"),
        AppendDisposition::Inserted
    );
    assert_eq!(
        store
            .append_provider_intent(&intent)
            .await
            .expect("intent replay"),
        AppendDisposition::AlreadyPresent
    );
    assert_eq!(
        store
            .pending_provider_attempt_count()
            .await
            .expect("pending count"),
        1
    );
    let pending = store
        .list_pending_provider_intents("thread-1", 0, 10)
        .await
        .expect("pending intents");
    assert_eq!(pending.len(), 1);
    assert_eq!(pending[0].intent, intent);

    assert_eq!(
        store
            .append_provider_receipt(&receipt)
            .await
            .expect("terminal"),
        AppendDisposition::Inserted
    );
    assert_eq!(
        store
            .append_provider_receipt(&receipt)
            .await
            .expect("terminal replay"),
        AppendDisposition::AlreadyPresent
    );
    assert_eq!(
        store
            .pending_provider_attempt_count()
            .await
            .expect("terminal count"),
        0
    );
    drop(store);

    let reopened = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("reopen evidence");
    let stored = reopened
        .get_provider_attempt(&receipt.attempt_id)
        .await
        .expect("read provider attempt")
        .expect("provider attempt");
    assert_eq!(stored.intent.intent, intent);
    assert_eq!(stored.receipt.expect("provider terminal").receipt, receipt);
}

#[tokio::test]
async fn provider_terminal_conflict_never_overwrites_original() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    let intent = intent(2);
    let completed = completed(intent.clone(), b"first-output");
    let rejected = ProviderInvocationReceipt::new(
        intent.clone(),
        ProviderTerminal::Rejected {
            reason_code: "provider_unauthorized".to_string(),
        },
    );
    store.append_provider_intent(&intent).await.expect("intent");
    store
        .append_provider_receipt(&completed)
        .await
        .expect("first terminal");

    assert!(matches!(
        store
            .append_provider_receipt(&rejected)
            .await
            .expect_err("different terminal for one attempt must conflict"),
        EvidenceError::IdempotencyConflict { .. }
    ));
    let stored = store
        .get_provider_receipt(&completed.receipt_id)
        .await
        .expect("read terminal")
        .expect("stored terminal");
    assert_eq!(stored.receipt, completed);
}

#[tokio::test]
async fn unary_completion_persists_without_synthetic_provider_fields() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let intent = intent(21);
    let receipt = ProviderInvocationReceipt::new(
        intent.clone(),
        ProviderTerminal::CompletedUnary {
            response_items_sha256: Sha256Digest::for_bytes(b"compacted-items"),
        },
    );
    store.append_provider_intent(&intent).await.expect("intent");
    store
        .append_provider_receipt(&receipt)
        .await
        .expect("unary terminal");

    let stored = store
        .get_provider_attempt(&intent.attempt_id)
        .await
        .expect("read provider attempt")
        .expect("provider attempt")
        .receipt
        .expect("unary receipt");
    assert_eq!(stored.receipt, receipt);
    let raw = sqlite
        .open_durable_evidence_pool(store.path())
        .await
        .expect("raw evidence pool");
    let terminal_kind: String =
        sqlx::query_scalar("SELECT terminal_kind FROM provider_invocation_terminals")
            .fetch_one(&raw)
            .await
            .expect("terminal projection");
    assert_eq!(terminal_kind, "completed");
}

#[tokio::test]
async fn concurrent_provider_intent_replay_inserts_exactly_once() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let first = HeptaEvidenceStore::open(&sqlite).await.expect("first pool");
    let second = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("second pool");
    let intent = intent(3);

    let (left, right) = tokio::join!(
        first.append_provider_intent(&intent),
        second.append_provider_intent(&intent)
    );
    let dispositions = [left.expect("left append"), right.expect("right append")];
    assert!(dispositions.contains(&AppendDisposition::Inserted));
    assert!(dispositions.contains(&AppendDisposition::AlreadyPresent));
    assert_eq!(
        first
            .pending_provider_attempt_count()
            .await
            .expect("pending count"),
        1
    );
}

#[tokio::test]
async fn concurrent_provider_terminal_conflict_preserves_one_terminal() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let first = HeptaEvidenceStore::open(&sqlite).await.expect("first pool");
    let second = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("second pool");
    let intent = intent(4);
    first.append_provider_intent(&intent).await.expect("intent");
    let completed = completed(intent.clone(), b"completed-output");
    let indeterminate = ProviderInvocationReceipt::new(
        intent,
        ProviderTerminal::Indeterminate {
            reason_code: "stream_eof_before_completed".to_string(),
            partial_response_sha256: Some(Sha256Digest::for_bytes(b"partial")),
        },
    );

    let (left, right) = tokio::join!(
        first.append_provider_receipt(&completed),
        second.append_provider_receipt(&indeterminate)
    );
    let inserted = usize::from(matches!(left, Ok(AppendDisposition::Inserted)))
        + usize::from(matches!(right, Ok(AppendDisposition::Inserted)));
    let conflicts = usize::from(matches!(
        left,
        Err(EvidenceError::IdempotencyConflict { .. })
    )) + usize::from(matches!(
        right,
        Err(EvidenceError::IdempotencyConflict { .. })
    ));
    assert_eq!(inserted, 1, "left={left:?}, right={right:?}");
    assert_eq!(conflicts, 1, "left={left:?}, right={right:?}");
    assert_eq!(
        first
            .pending_provider_attempt_count()
            .await
            .expect("pending count"),
        0
    );
}

#[tokio::test]
async fn provider_terminal_requires_exact_durable_intent() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    let receipt = completed(intent(5), b"output");

    assert!(matches!(
        store
            .append_provider_receipt(&receipt)
            .await
            .expect_err("terminal without durable intent must fail"),
        EvidenceError::Corrupt(_)
    ));
    assert_eq!(
        store
            .pending_provider_attempt_count()
            .await
            .expect("pending count"),
        0
    );
}

#[tokio::test]
async fn provider_tables_are_immutable_and_foreign_key_bound() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let intent = intent(6);
    let receipt = completed(intent.clone(), b"output");
    store.append_provider_intent(&intent).await.expect("intent");
    store
        .append_provider_receipt(&receipt)
        .await
        .expect("terminal");
    let raw = sqlite
        .open_durable_evidence_pool(store.path())
        .await
        .expect("raw evidence pool");

    for statement in [
        "UPDATE provider_invocation_intents SET recorded_at_ms = recorded_at_ms + 1",
        "DELETE FROM provider_invocation_intents",
        "UPDATE provider_invocation_terminals SET recorded_at_ms = recorded_at_ms + 1",
        "DELETE FROM provider_invocation_terminals",
    ] {
        let error = sqlx::query(statement)
            .execute(&raw)
            .await
            .expect_err("provider evidence mutation must fail");
        assert!(error.to_string().contains("immutable"));
    }

    let error = sqlx::query(
        "INSERT INTO provider_invocation_terminals (
            receipt_id, attempt_id, request_binding_id, thread_id, turn_id,
            terminal_kind, schema_version, payload_json, payload_sha256, recorded_at_ms
         ) VALUES (?, ?, ?, ?, ?, 'indeterminate', 1, '{}', ?, 0)",
    )
    .bind(format!("provider-receipt:v1:{}", "a".repeat(64)))
    .bind(format!("provider-attempt:v1:{}", "b".repeat(64)))
    .bind(format!("provider-request:v1:{}", "c".repeat(64)))
    .bind("thread-1")
    .bind("turn-1")
    .bind("0".repeat(64))
    .execute(&raw)
    .await
    .expect_err("terminal must reference its exact intent");
    assert!(error.to_string().contains("FOREIGN KEY constraint failed"));
}

#[tokio::test]
async fn provider_evidence_never_persists_prompt_token_header_or_output_plaintext() {
    const PROMPT: &[u8] = b"fixture-prompt-ultra-private-871";
    const TOKEN: &[u8] = b"fixture-bearer-token-ultra-private-872";
    const HEADER: &[u8] = b"fixture-auth-header-ultra-private-873";
    const OUTPUT: &[u8] = b"fixture-provider-output-ultra-private-874";
    const ENDPOINT: &[u8] = b"https://provider.invalid/responses?secret=875";
    const EPHEMERAL_INPUT: &[u8] = b"fixture-ephemeral-input-ultra-private-876";
    const EPHEMERAL_WITNESS: &[u8] = b"fixture-ephemeral-witness-ultra-private-877";

    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let mut binding = binding("thread-secret-test", PROMPT, HEADER);
    binding.provider_config_sha256 = Sha256Digest::for_bytes(TOKEN);
    binding.endpoint_sha256 = Sha256Digest::for_bytes(ENDPOINT);
    binding.ephemeral_input_sha256 = Some(Sha256Digest::for_bytes(EPHEMERAL_INPUT));
    binding.ephemeral_input_witness_sha256 = Some(Sha256Digest::for_bytes(EPHEMERAL_WITNESS));
    let intent = ProviderInvocationIntent::new([7; 16], binding);
    let receipt = completed(intent.clone(), OUTPUT);
    store.append_provider_intent(&intent).await.expect("intent");
    store
        .append_provider_receipt(&receipt)
        .await
        .expect("terminal");
    let raw = sqlite
        .open_durable_evidence_pool(store.path())
        .await
        .expect("raw evidence pool");
    let rows: Vec<String> = sqlx::query_scalar(
        "SELECT payload_json FROM provider_invocation_intents
         UNION ALL
         SELECT payload_json FROM provider_invocation_terminals",
    )
    .fetch_all(&raw)
    .await
    .expect("provider JSON rows");
    let joined = rows.join("\n");
    for forbidden in [
        PROMPT,
        TOKEN,
        HEADER,
        OUTPUT,
        ENDPOINT,
        EPHEMERAL_INPUT,
        EPHEMERAL_WITNESS,
    ] {
        assert!(
            !joined
                .as_bytes()
                .windows(forbidden.len())
                .any(|w| w == forbidden)
        );
    }
}

#[tokio::test]
async fn provider_projection_and_digest_corruption_fail_closed() {
    for (nonce, corruption) in [(8, "projection"), (9, "digest")] {
        let temp = TempDir::new().expect("temp dir");
        let sqlite = sqlite_config(&temp);
        let store = HeptaEvidenceStore::open(&sqlite)
            .await
            .expect("open evidence");
        let intent = intent(nonce);
        store.append_provider_intent(&intent).await.expect("intent");
        let raw = sqlite
            .open_durable_evidence_pool(store.path())
            .await
            .expect("raw evidence pool");
        sqlx::query("DROP TRIGGER provider_invocation_intents_no_update")
            .execute(&raw)
            .await
            .expect("disable immutable trigger for corruption simulation");
        if corruption == "projection" {
            sqlx::query(
                "UPDATE provider_invocation_intents SET provider_id = 'drifted-provider'
                 WHERE attempt_id = ?",
            )
            .bind(intent.attempt_id.as_str())
            .execute(&raw)
            .await
            .expect("corrupt provider projection");
        } else {
            sqlx::query(
                "UPDATE provider_invocation_intents SET payload_sha256 = ? WHERE attempt_id = ?",
            )
            .bind("0".repeat(64))
            .bind(intent.attempt_id.as_str())
            .execute(&raw)
            .await
            .expect("corrupt provider digest");
        }

        assert!(matches!(
            store
                .get_provider_attempt(&intent.attempt_id)
                .await
                .expect_err("provider corruption must fail closed"),
            EvidenceError::Corrupt(_)
        ));
    }
}

#[tokio::test]
async fn open_rejects_missing_provider_schema_object() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let raw = sqlite
        .open_durable_evidence_pool(store.path())
        .await
        .expect("raw evidence pool");
    sqlx::query("DROP TRIGGER provider_invocation_terminals_no_delete")
        .execute(&raw)
        .await
        .expect("drop provider immutable trigger");
    raw.close().await;
    drop(store);

    let error = match HeptaEvidenceStore::open(&sqlite).await {
        Ok(_) => panic!("missing provider schema object must be rejected"),
        Err(error) => error,
    };
    assert!(matches!(error, EvidenceError::Corrupt(_)));
}

#[tokio::test]
async fn open_rejects_legacy_provider_rows_without_host_binding_digest() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let raw = sqlite
        .open_durable_evidence_pool(store.path())
        .await
        .expect("raw evidence pool");
    sqlx::query("DROP TRIGGER provider_invocation_intents_host_binding_required")
        .execute(&raw)
        .await
        .expect("drop host binding trigger");
    sqlx::query(
        "INSERT INTO provider_invocation_intents (
            attempt_id, request_binding_id, attempt_nonce_sha256, thread_id, turn_id,
            request_kind, provider_id, provider_config_sha256, model, transport,
            endpoint_sha256, logical_request_sha256, wire_semantic_sha256,
            previous_response_id_sha256, generate, schema_version,
            payload_json, payload_sha256, recorded_at_ms
         ) VALUES (?, ?, ?, ?, ?, 'turn', ?, ?, ?, 'http', ?, ?, ?, NULL, 1, 1, '{}', ?, 0)",
    )
    .bind(format!("provider-attempt:v1:{}", "1".repeat(64)))
    .bind(format!("provider-request:v1:{}", "2".repeat(64)))
    .bind("3".repeat(64))
    .bind("thread-legacy")
    .bind("turn-legacy")
    .bind("provider-legacy")
    .bind("4".repeat(64))
    .bind("model-legacy")
    .bind("5".repeat(64))
    .bind("6".repeat(64))
    .bind("7".repeat(64))
    .bind(Sha256Digest::for_bytes(b"{}").as_str())
    .execute(&raw)
    .await
    .expect("insert legacy row");
    sqlx::query(
        "CREATE TRIGGER provider_invocation_intents_host_binding_required
         BEFORE INSERT ON provider_invocation_intents
         WHEN NEW.host_request_binding_id_sha256 IS NULL
         BEGIN
             SELECT RAISE(ABORT, 'provider invocation intent requires host request binding digest');
         END",
    )
    .execute(&raw)
    .await
    .expect("restore host binding trigger");
    raw.close().await;
    drop(store);

    let error = match HeptaEvidenceStore::open(&sqlite).await {
        Ok(_) => panic!("legacy unbound row must require explicit migration"),
        Err(error) => error,
    };
    assert!(matches!(
        error,
        EvidenceError::Corrupt(detail)
            if detail.contains("predate host request binding evidence")
    ));
}
