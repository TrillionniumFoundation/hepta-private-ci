//! Original SQLite recovery and adversarial transaction tests.
//!
//! Real SQLite is used; no Codex, tools, signing issuer or provider effects.

use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::execution_contract_v1::ExecutionIntentV1;
use codex_hepta_contracts::execution_contract_v1::ExecutionTargetV1;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use tempfile::TempDir;

use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::execution_preparation_v1::ExecutionPreparationReadbackStatusV1;

const PAYLOAD: &[u8] = b"fake-execution-input-not-a-tool-call";

fn config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("private test home"),
    )
}

fn intent() -> ExecutionIntentV1 {
    ExecutionIntentV1 {
        schema_version: 1,
        operation_id: "operation:complete-restore".into(),
        subject_id: "agent:isolated".into(),
        scope_id: "scope:test".into(),
        destination_id: "codex:exec-server".into(),
        target: ExecutionTargetV1::CodexExecServerProcess,
        generation: 5,
        fence: 8,
        authority_epoch: 13,
        payload_sha256: Sha256Digest::for_bytes(PAYLOAD),
        payload_bytes: PAYLOAD.len() as u32,
        deadline_unix_ms: 1_800_000_000_000,
        max_wall_ms: 10_000,
    }
}

fn original_effect_intent(source: &ExecutionIntentV1) -> ProviderEffectIntent {
    let key = ProviderEffectKey::for_operation(
        "hepta.execution.prepare-only.v1",
        &format!("{}|{}", source.subject_id, source.scope_id),
        &source.operation_id,
    )
    .expect("occurrence key");
    ProviderEffectIntent::new(
        key,
        Sha256Digest::for_bytes(&serde_json::to_vec(source).expect("serializable")),
    )
}

#[tokio::test]
async fn source_free_cold_restore_reconstructs_full_original_intent() {
    let temp = TempDir::new().expect("temp");
    let sqlite = config(&temp);
    let source = intent();
    let store = HeptaEvidenceStore::open(&sqlite).await.expect("writer");
    let prepared = store
        .prepare_execution_intent_v1(&source, PAYLOAD)
        .await
        .expect("complete original atomic prepare");
    let key = prepared.readback.provider_effect_key.clone();
    store.close().await;

    let reader = HeptaEvidenceStore::open_existing_read_only(&sqlite)
        .await
        .expect("original read-only reopen");
    let recovered = reader
        .recover_execution_preparation_by_key_v1(&key)
        .await
        .expect("complete original")
        .expect("original row");
    assert_eq!(recovered.intent, source);
    assert_eq!(recovered.readback, prepared.readback);
    assert_eq!(
        recovered.readback.status,
        ExecutionPreparationReadbackStatusV1::RecordedOnly
    );
    assert_eq!(
        recovered.intent
            .binding_proposal()
            .expect("original unsigned binding")
            .request_sha256,
        prepared.readback.request_sha256
    );
    assert!(
        reader
            .prepare_execution_intent_v1(
                &ExecutionIntentV1 {
                    operation_id: "operation:read-only-cannot-write".into(),
                    ..source
                },
                PAYLOAD,
            )
            .await
            .is_err(),
        "read-only reopen must never admit writes"
    );
    reader.close().await;
}

#[tokio::test]
async fn injected_second_table_failure_rolls_back_original_provider_effect_row() {
    let temp = TempDir::new().expect("temp");
    let store = HeptaEvidenceStore::open(&config(&temp))
        .await
        .expect("open");
    sqlx::query(
        "CREATE TRIGGER block_complete_execution_insertion
         BEFORE INSERT ON execution_prepared_envelopes
         BEGIN SELECT RAISE(ABORT, 'injected full-envelope failure'); END",
    )
    .execute(&store.pool)
    .await
    .expect("install injected failure");
    let source = intent();
    let key = original_effect_intent(&source).key;
    let failed = store.prepare_execution_intent_v1(&source, PAYLOAD).await;
    assert!(failed.is_err(), "second-table failure must reject original commit");
    assert!(
        store
            .get_provider_effect(&key)
            .await
            .expect("inspect original")
            .is_none(),
        "the first provider intent write must roll back atomically"
    );
    sqlx::query("DROP TRIGGER block_complete_execution_insertion")
        .execute(&store.pool)
        .await
        .expect("remove injected failure");
    let prepared = store
        .prepare_execution_intent_v1(&source, PAYLOAD)
        .await
        .expect("fresh original atomic commit");
    assert_eq!(
        prepared.readback.status,
        ExecutionPreparationReadbackStatusV1::RecordedOnly
    );
    assert!(
        store
            .recover_execution_preparation_by_key_v1(&key)
            .await
            .expect("read after retry")
            .is_some()
    );
}

#[tokio::test]
async fn legacy_digest_only_orphan_cannot_be_laundered_into_a_complete_intent() {
    let temp = TempDir::new().expect("temp");
    let sqlite = config(&temp);
    let source = intent();
    let original = original_effect_intent(&source);
    let store = HeptaEvidenceStore::open(&sqlite).await.expect("writer");
    store
        .append_provider_effect_intent(&original)
        .await
        .expect("reproduce historical digest-only row");
    assert!(matches!(
        store
            .recover_execution_preparation_by_key_v1(&original.key)
            .await,
        Err(EvidenceError::Corrupt(_))
    ));
    assert!(matches!(
        store.prepare_execution_intent_v1(&source, PAYLOAD).await,
        Err(EvidenceError::Corrupt(_))
    ));
    store.close().await;
    let reader = HeptaEvidenceStore::open_existing_read_only(&sqlite)
        .await
        .expect("original schema still valid");
    assert!(matches!(
        reader
            .recover_execution_preparation_by_key_v1(&original.key)
            .await,
        Err(EvidenceError::Corrupt(_))
    ));
}

#[tokio::test]
async fn original_complete_intent_schema_is_immutable_under_direct_sql_attack() {
    let temp = TempDir::new().expect("temp");
    let store = HeptaEvidenceStore::open(&config(&temp))
        .await
        .expect("open");
    let source = intent();
    let receipt = store
        .prepare_execution_intent_v1(&source, PAYLOAD)
        .await
        .expect("original");
    let key = receipt.readback.provider_effect_key;
    let changed = sqlx::query(
        "UPDATE execution_prepared_envelopes
         SET intent_json = '{}' WHERE effect_key = ?",
    )
    .bind(key.as_str())
    .execute(&store.pool)
    .await;
    assert!(changed.is_err(), "immutable rows cannot be rewritten");
    let deleted = sqlx::query(
        "DELETE FROM execution_prepared_envelopes WHERE effect_key = ?",
    )
    .bind(key.as_str())
    .execute(&store.pool)
    .await;
    assert!(deleted.is_err(), "original lineage cannot be removed");
    let recovered = store
        .recover_execution_preparation_by_key_v1(&key)
        .await
        .expect("valid original")
        .expect("original exists");
    assert_eq!(recovered.intent, source);
}

#[tokio::test]
async fn restore_rejects_row_tamper_even_if_attacker_reinstates_original_trigger() {
    let temp = TempDir::new().expect("temp");
    let sqlite = config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite).await.expect("writer");
    let source = intent();
    let receipt = store
        .prepare_execution_intent_v1(&source, PAYLOAD)
        .await
        .expect("original");
    let key = receipt.readback.provider_effect_key;
    sqlx::query("DROP TRIGGER execution_prepared_envelopes_no_update")
        .execute(&store.pool)
        .await
        .expect("simulate filesystem/database compromise");
    sqlx::query(
        "UPDATE execution_prepared_envelopes
         SET intent_json = replace(intent_json, 'scope:test', 'scope:fake')
         WHERE effect_key = ?",
    )
    .bind(key.as_str())
    .execute(&store.pool)
    .await
    .expect("simulate malicious original content rewrite");
    sqlx::query(
        "CREATE TRIGGER execution_prepared_envelopes_no_update
         BEFORE UPDATE ON execution_prepared_envelopes
         BEGIN SELECT RAISE(ABORT, 'execution prepared envelopes are immutable'); END",
    )
    .execute(&store.pool)
    .await
    .expect("restore exact schema spelling");
    assert!(matches!(
        store.recover_execution_preparation_by_key_v1(&key).await,
        Err(EvidenceError::Corrupt(_))
    ));
    store.close().await;
    assert!(
        HeptaEvidenceStore::open_existing_read_only(&sqlite).await.is_err(),
        "startup verifier cannot accept a tampered complete envelope"
    );
}

#[tokio::test]
async fn restart_preserves_quarantine_and_never_replays_physical_execution() {
    let temp = TempDir::new().expect("temp");
    let sqlite = config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite).await.expect("writer");
    let source = intent();
    let receipt = store
        .prepare_execution_intent_v1(&source, PAYLOAD)
        .await
        .expect("prepared");
    let key = receipt.readback.provider_effect_key;
    store
        .mark_provider_effect_indeterminate(&key, "execution_unknown")
        .await
        .expect("persist original unknown");
    store.close().await;
    let reopened = HeptaEvidenceStore::open_existing_read_only(&sqlite)
        .await
        .expect("read only");
    let observed = reopened
        .recover_execution_preparation_by_key_v1(&key)
        .await
        .expect("original readback")
        .expect("persisted");
    assert_eq!(observed.intent, source);
    assert_eq!(
        observed.readback.status,
        ExecutionPreparationReadbackStatusV1::OriginalOwnerReconciliationRequired
    );
}

#[tokio::test]
async fn no_external_effect_or_signer_is_created_by_complete_recovery() {
    assert!(!crate::EXECUTION_PREPARE_P2A_EXECUTE_ALLOWED);
    assert!(!crate::EXECUTION_PREPARE_P2A_PRODUCTION_CALLER);
    assert!(!crate::EXECUTION_PREPARE_P2A_FINAL_USE_AUTHORITY);
    let temp = TempDir::new().expect("temp");
    let store = HeptaEvidenceStore::open(&config(&temp))
        .await
        .expect("store");
    assert!(store
        .recover_execution_preparation_by_key_v1(
            &ProviderEffectKey::for_operation(
                "hepta.execution.prepare-only.v1",
                "agent:isolated|scope:test",
                "operation:missing"
            ).expect("key")
        )
        .await
        .expect("empty")
        .is_none());
}
