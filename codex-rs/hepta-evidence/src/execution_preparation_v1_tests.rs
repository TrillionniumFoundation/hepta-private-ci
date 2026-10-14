use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::execution_contract_v1::ExecutionIntentV1;
use codex_hepta_contracts::execution_contract_v1::ExecutionTargetV1;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use tempfile::TempDir;

use crate::AppendDisposition;
use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::execution_preparation_v1::ExecutionPreparationReadbackStatusV1;

const PAYLOAD: &[u8] = b"synthetic-no-tool-effect";

fn sqlite(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("private absolute test home"),
    )
}

fn intent() -> ExecutionIntentV1 {
    ExecutionIntentV1 {
        schema_version: 1,
        operation_id: "operation:execution-p2a-test".into(),
        subject_id: "agent:research".into(),
        scope_id: "scope:isolated".into(),
        destination_id: "codex:exec-server".into(),
        target: ExecutionTargetV1::CodexExecServerProcess,
        generation: 7,
        fence: 8,
        authority_epoch: 9,
        payload_sha256: Sha256Digest::for_bytes(PAYLOAD),
        payload_bytes: PAYLOAD.len() as u32,
        deadline_unix_ms: 1_800_000_000_000,
        max_wall_ms: 10_000,
    }
}

#[tokio::test]
async fn original_sqlite_owner_persists_exact_envelope_without_any_tool_effect() {
    let temp = TempDir::new().expect("temp");
    let store = HeptaEvidenceStore::open(&sqlite(&temp)).await.expect("store");
    let source = intent();
    let receipt = store
        .prepare_execution_intent_v1(&source, PAYLOAD)
        .await
        .expect("durable prepare");
    assert_eq!(receipt.disposition, AppendDisposition::Inserted);
    assert_eq!(
        receipt.readback.status,
        ExecutionPreparationReadbackStatusV1::RecordedOnly
    );
    assert_eq!(
        receipt.readback.request_sha256,
        source.binding_proposal().expect("binding").request_sha256
    );
    let original = store
        .get_provider_effect(&receipt.readback.provider_effect_key)
        .await
        .expect("read original")
        .expect("durable source");
    assert!(original.acknowledgements.is_empty());
    assert!(original.uncertainties.is_empty());
    assert_eq!(
        original.intent.intent.payload_sha256,
        Sha256Digest::for_bytes(&serde_json::to_vec(&source).expect("serialized envelope"))
    );
    assert_ne!(
        original.intent.intent.payload_sha256,
        source.payload_sha256,
        "control envelope must not masquerade as external payload"
    );
}

#[tokio::test]
async fn cold_restart_reads_original_then_identical_stage_is_idempotent() {
    let temp = TempDir::new().expect("temp");
    let config = sqlite(&temp);
    let source = intent();
    let store = HeptaEvidenceStore::open(&config).await.expect("open");
    let first = store
        .prepare_execution_intent_v1(&source, PAYLOAD)
        .await
        .expect("first write");
    store.close().await;
    let reopened = HeptaEvidenceStore::open(&config).await.expect("cold reopen");
    let read = reopened
        .read_execution_preparation_v1(&source)
        .await
        .expect("original persisted");
    assert_eq!(read, first.readback);
    let second = reopened
        .prepare_execution_intent_v1(&source, PAYLOAD)
        .await
        .expect("idempotent re-presentation");
    assert_eq!(second.disposition, AppendDisposition::AlreadyPresent);
    assert_eq!(second.readback, first.readback);
    reopened.close().await;
}

#[tokio::test]
async fn missing_preparation_never_reports_success() {
    let temp = TempDir::new().expect("temp");
    let store = HeptaEvidenceStore::open(&sqlite(&temp)).await.expect("store");
    assert_eq!(
        store
            .read_execution_preparation_v1(&intent())
            .await
            .expect("no record")
            .status,
        ExecutionPreparationReadbackStatusV1::Absent
    );
}

#[tokio::test]
async fn same_operation_changed_generation_fence_target_and_deadline_conflict() {
    let temp = TempDir::new().expect("temp");
    let store = HeptaEvidenceStore::open(&sqlite(&temp)).await.expect("store");
    let original = intent();
    store
        .prepare_execution_intent_v1(&original, PAYLOAD)
        .await
        .expect("original");
    let variants = [
        ExecutionIntentV1 {
            generation: 17,
            ..original.clone()
        },
        ExecutionIntentV1 {
            fence: 18,
            ..original.clone()
        },
        ExecutionIntentV1 {
            authority_epoch: 19,
            ..original.clone()
        },
        ExecutionIntentV1 {
            destination_id: "codex:another".into(),
            ..original.clone()
        },
        ExecutionIntentV1 {
            target: ExecutionTargetV1::CodexAppServerModelOnly,
            ..original.clone()
        },
        ExecutionIntentV1 {
            deadline_unix_ms: original.deadline_unix_ms + 1,
            ..original.clone()
        },
        ExecutionIntentV1 {
            max_wall_ms: original.max_wall_ms + 1,
            ..original.clone()
        },
    ];
    for variant in variants {
        let result = store.prepare_execution_intent_v1(&variant, PAYLOAD).await;
        assert!(
            matches!(result, Err(EvidenceError::IdempotencyConflict { .. })),
            "same logical occurrence must reject changed identity: {result:?}"
        );
        assert!(matches!(
            store.read_execution_preparation_v1(&variant).await,
            Err(EvidenceError::IdempotencyConflict { .. })
        ));
    }
    assert_eq!(
        store
            .read_execution_preparation_v1(&original)
            .await
            .expect("unchanged original")
            .status,
        ExecutionPreparationReadbackStatusV1::RecordedOnly
    );
}

#[tokio::test]
async fn payload_byte_or_digest_tamper_never_creates_an_original_record() {
    let temp = TempDir::new().expect("temp");
    let store = HeptaEvidenceStore::open(&sqlite(&temp)).await.expect("store");
    let original = intent();
    assert!(matches!(
        store.prepare_execution_intent_v1(&original, b"changed bytes").await,
        Err(EvidenceError::InvalidRecord(_))
    ));
    let mut substituted = original.clone();
    substituted.payload_sha256 = Sha256Digest::for_bytes(b"changed bytes");
    assert!(matches!(
        store.prepare_execution_intent_v1(&substituted, PAYLOAD).await,
        Err(EvidenceError::InvalidRecord(_))
    ));
    assert_eq!(
        store
            .read_execution_preparation_v1(&original)
            .await
            .expect("no writes")
            .status,
        ExecutionPreparationReadbackStatusV1::Absent
    );
}

#[tokio::test]
async fn distinct_scope_and_principal_never_reuse_the_same_effect_key() {
    let temp = TempDir::new().expect("temp");
    let store = HeptaEvidenceStore::open(&sqlite(&temp)).await.expect("store");
    let original = intent();
    let other_scope = ExecutionIntentV1 {
        scope_id: "scope:other".into(),
        ..original.clone()
    };
    let other_principal = ExecutionIntentV1 {
        subject_id: "agent:other".into(),
        ..original.clone()
    };
    let a = store
        .prepare_execution_intent_v1(&original, PAYLOAD)
        .await
        .expect("original");
    let b = store
        .prepare_execution_intent_v1(&other_scope, PAYLOAD)
        .await
        .expect("separate scope");
    let c = store
        .prepare_execution_intent_v1(&other_principal, PAYLOAD)
        .await
        .expect("separate subject");
    assert_ne!(a.readback.provider_effect_key, b.readback.provider_effect_key);
    assert_ne!(a.readback.provider_effect_key, c.readback.provider_effect_key);
    assert_ne!(b.readback.provider_effect_key, c.readback.provider_effect_key);
}

#[tokio::test]
async fn quarantine_mutation_never_looks_like_authorized_prepare_or_completion() {
    let temp = TempDir::new().expect("temp");
    let store = HeptaEvidenceStore::open(&sqlite(&temp)).await.expect("store");
    let source = intent();
    let receipt = store
        .prepare_execution_intent_v1(&source, PAYLOAD)
        .await
        .expect("prepare");
    let key = receipt.readback.provider_effect_key;
    store
        .mark_provider_effect_indeterminate(&key, "execution_ambiguous")
        .await
        .expect("real owner quarantine");
    assert_eq!(
        store
            .read_execution_preparation_v1(&source)
            .await
            .expect("read")
            .status,
        ExecutionPreparationReadbackStatusV1::OriginalOwnerReconciliationRequired
    );
    assert!(matches!(
        store.prepare_execution_intent_v1(&source, PAYLOAD).await,
        Err(EvidenceError::Corrupt(_))
    ));
    let quarantined = store
        .get_provider_effect(&key)
        .await
        .expect("recovered record")
        .expect("original");
    assert_eq!(quarantined.uncertainties.len(), 1);
    assert!(quarantined.acknowledgements.is_empty());
}

#[tokio::test]
async fn simultaneous_identical_prepare_uses_one_original_sqlite_row() {
    let temp = TempDir::new().expect("temp");
    let store = HeptaEvidenceStore::open(&sqlite(&temp)).await.expect("store");
    let a = store.clone();
    let b = store.clone();
    let request_a = intent();
    let request_b = request_a.clone();
    let (r1, r2) = tokio::join!(
        a.prepare_execution_intent_v1(&request_a, PAYLOAD),
        b.prepare_execution_intent_v1(&request_b, PAYLOAD)
    );
    let r1 = r1.expect("first");
    let r2 = r2.expect("second");
    assert_eq!(
        [r1.disposition, r2.disposition]
            .into_iter()
            .filter(|value| *value == AppendDisposition::Inserted)
            .count(),
        1
    );
    assert_eq!(r1.readback, r2.readback);
    let original = store
        .get_provider_effect(&r1.readback.provider_effect_key)
        .await
        .expect("row")
        .expect("one record");
    assert!(original.acknowledgements.is_empty());
    assert!(original.uncertainties.is_empty());
}

#[tokio::test]
async fn reserved_prepare_namespace_is_not_a_production_execution_grant() {
    assert!(!crate::execution_preparation_v1::EXECUTION_PREPARE_P2A_FINAL_USE_AUTHORITY);
    assert!(!crate::execution_preparation_v1::EXECUTION_PREPARE_P2A_PRODUCTION_CALLER);
    assert!(!crate::execution_preparation_v1::EXECUTION_PREPARE_P2A_EXECUTE_ALLOWED);
    let temp = TempDir::new().expect("temp");
    let store = HeptaEvidenceStore::open(&sqlite(&temp)).await.expect("store");
    let receipt = store
        .prepare_execution_intent_v1(&intent(), PAYLOAD)
        .await
        .expect("stage");
    assert!(receipt.readback.provider_effect_key.as_str().starts_with("provider-effect:v1:"));
    assert_eq!(
        receipt.readback.status,
        ExecutionPreparationReadbackStatusV1::RecordedOnly
    );
}
