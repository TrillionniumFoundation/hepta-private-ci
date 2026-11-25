use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::execution_contract_v1::ExecutionIntentV1;
use codex_hepta_contracts::execution_contract_v1::ExecutionTargetV1;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use tempfile::TempDir;

use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::execution_entry_deny_v1::ExecutionEffectEntryDeniedV1;

const PAYLOAD: &[u8] = b"no-physical-tool-call";

fn input() -> ExecutionIntentV1 {
    ExecutionIntentV1 {
        schema_version: 1,
        operation_id: "operation:p2b".into(),
        subject_id: "agent:p2b".into(),
        scope_id: "scope:test".into(),
        destination_id: "codex:exec-server".into(),
        target: ExecutionTargetV1::CodexExecServerProcess,
        generation: 3,
        fence: 4,
        authority_epoch: 5,
        payload_sha256: Sha256Digest::for_bytes(PAYLOAD),
        payload_bytes: PAYLOAD.len() as u32,
        deadline_unix_ms: 1_800_000_000_000,
        max_wall_ms: 5000,
    }
}

fn config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("test path"),
    )
}

#[tokio::test]
async fn no_record_denies_without_creating_one() {
    let tmp = TempDir::new().expect("temp");
    let store = HeptaEvidenceStore::open(&config(&tmp)).await.expect("open");
    let intent = input();
    let result = store
        .audit_execution_effect_entry_denied_v1(&intent, PAYLOAD)
        .await
        .expect("deny-only audit");
    assert_eq!(
        result.denied,
        ExecutionEffectEntryDeniedV1::NoOriginalPreparation
    );
    assert_eq!(result.generation, intent.generation);
    assert_eq!(result.fence, intent.fence);
    assert_eq!(
        store
            .read_execution_preparation_v1(&intent)
            .await
            .expect("read")
            .status,
        crate::ExecutionPreparationReadbackStatusV1::Absent
    );
}

#[tokio::test]
async fn even_a_real_durable_prepare_cannot_mint_a_tool_grant() {
    let tmp = TempDir::new().expect("temp");
    let store = HeptaEvidenceStore::open(&config(&tmp)).await.expect("open");
    let intent = input();
    store
        .prepare_execution_intent_v1(&intent, PAYLOAD)
        .await
        .expect("prepare");
    let denial = store
        .audit_execution_effect_entry_denied_v1(&intent, PAYLOAD)
        .await
        .expect("deny");
    assert_eq!(
        denial.denied,
        ExecutionEffectEntryDeniedV1::IndependentFinalUseAndPhysicalOwnerUnavailable
    );
    assert_eq!(
        denial.request_sha256,
        intent.binding_proposal().expect("binding").request_sha256
    );
    const {
        assert!(!crate::execution_entry_deny_v1::EXECUTION_EFFECT_ENTRY_P2B_PERMITTED);
    };
}

#[tokio::test]
async fn quarantined_original_never_reuses_or_resends() {
    let tmp = TempDir::new().expect("temp");
    let store = HeptaEvidenceStore::open(&config(&tmp)).await.expect("open");
    let intent = input();
    let receipt = store
        .prepare_execution_intent_v1(&intent, PAYLOAD)
        .await
        .expect("prepare");
    store
        .mark_provider_effect_indeterminate(
            &receipt.readback.provider_effect_key,
            "p2b_unknown_effect",
        )
        .await
        .expect("quarantine");
    let denial = store
        .audit_execution_effect_entry_denied_v1(&intent, PAYLOAD)
        .await
        .expect("deny");
    assert_eq!(
        denial.denied,
        ExecutionEffectEntryDeniedV1::OriginalOwnerReconciliationRequired
    );
}

#[tokio::test]
async fn stale_generation_and_wrong_payload_reject_before_entry() {
    let tmp = TempDir::new().expect("temp");
    let store = HeptaEvidenceStore::open(&config(&tmp)).await.expect("open");
    let intent = input();
    store
        .prepare_execution_intent_v1(&intent, PAYLOAD)
        .await
        .expect("prepare");
    let stale = ExecutionIntentV1 {
        generation: 99,
        ..intent.clone()
    };
    assert!(matches!(
        store
            .audit_execution_effect_entry_denied_v1(&stale, PAYLOAD)
            .await,
        Err(EvidenceError::IdempotencyConflict { .. })
    ));
    assert!(matches!(
        store
            .audit_execution_effect_entry_denied_v1(&intent, b"forged")
            .await,
        Err(EvidenceError::InvalidRecord(_))
    ));
}

#[tokio::test]
async fn read_only_reopen_can_deny_without_write_authority() {
    let tmp = TempDir::new().expect("temp");
    let cfg = config(&tmp);
    let writer = HeptaEvidenceStore::open(&cfg).await.expect("open");
    let intent = input();
    writer
        .prepare_execution_intent_v1(&intent, PAYLOAD)
        .await
        .expect("prepare");
    writer.close().await;
    let reader = HeptaEvidenceStore::open_existing_read_only(&cfg)
        .await
        .expect("read-only");
    let denial = reader
        .audit_execution_effect_entry_denied_v1(&intent, PAYLOAD)
        .await
        .expect("read-only deny");
    assert_eq!(
        denial.denied,
        ExecutionEffectEntryDeniedV1::IndependentFinalUseAndPhysicalOwnerUnavailable
    );
}
