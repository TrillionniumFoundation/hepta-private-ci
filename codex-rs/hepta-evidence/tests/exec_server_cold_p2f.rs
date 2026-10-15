//! Native original Evidence owner roundtrip of the already admitted P2c *inspection* subset.
//!
//! Test-only composition: no RPC send, physical executor, signer, Final-use, or tool grant.
//! This is deliberately a separate integration test so production call sites stay unchanged.

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::exec_server_start_p2c::CODEX_EXEC_SERVER_P2C_DESTINATION;
use codex_hepta_contracts::exec_server_start_p2c::CODEX_EXEC_SERVER_P2C_EFFECT_AUTHORITY;
use codex_hepta_contracts::exec_server_start_p2c::inspect_codex_exec_server_start_v1;
use codex_hepta_contracts::execution_contract_v1::EXECUTION_ENVELOPE_SCHEMA_VERSION_V1;
use codex_hepta_contracts::execution_contract_v1::ExecutionIntentV1;
use codex_hepta_contracts::execution_contract_v1::ExecutionTargetV1;
use codex_hepta_evidence::EvidenceError;
use codex_hepta_evidence::ExecutionEffectEntryDeniedV1;
use codex_hepta_evidence::ExecutionPreparationReadbackStatusV1;
use codex_hepta_evidence::HeptaEvidenceStore;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use serde::Deserialize;
use tempfile::TempDir;

const EXPECTED_ACCEPTED: usize = 6;

#[derive(Deserialize)]
struct Case {
    id: String,
    raw: String,
    hepta_accepts: bool,
}

#[derive(Deserialize)]
struct Corpus {
    schema: u32,
    authority: String,
    operation_id: String,
    cases: Vec<Case>,
}

fn corpus() -> Corpus {
    let corpus: Corpus = serde_json::from_str(include_str!(
        "../../../qualification/codex-exec-p2e/corpus.json"
    ))
    .expect("frozen shared P2e corpus");
    assert_eq!(corpus.schema, 1);
    assert_eq!(corpus.authority, "DENY_ALL");
    assert_eq!(corpus.cases.len(), 50);
    assert_eq!(
        corpus
            .cases
            .iter()
            .filter(|case| case.hepta_accepts)
            .count(),
        EXPECTED_ACCEPTED
    );
    corpus
}

fn intent_for(operation_id: &str, raw: &[u8]) -> ExecutionIntentV1 {
    ExecutionIntentV1 {
        schema_version: EXECUTION_ENVELOPE_SCHEMA_VERSION_V1,
        operation_id: operation_id.into(),
        subject_id: "agent:p2f".into(),
        scope_id: "scope:p2f".into(),
        destination_id: CODEX_EXEC_SERVER_P2C_DESTINATION.into(),
        target: ExecutionTargetV1::CodexExecServerProcess,
        generation: 3,
        fence: 4,
        authority_epoch: 5,
        payload_sha256: Sha256Digest::for_bytes(raw),
        payload_bytes: u32::try_from(raw.len()).expect("P2c max physical bytes"),
        deadline_unix_ms: 1_800_000_000_000,
        max_wall_ms: 2000,
    }
}

fn config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("test directory"),
    )
}

#[tokio::test]
async fn every_admitted_wire_survives_original_sqlite_cold_recovery_but_is_denied() {
    const { assert!(!CODEX_EXEC_SERVER_P2C_EFFECT_AUTHORITY) };
    let corpus = corpus();
    let mut admitted = 0_usize;
    for case in corpus.cases.iter().filter(|case| case.hepta_accepts) {
        let raw = case.raw.as_bytes();
        let intent = intent_for(&corpus.operation_id, raw);
        let observation = inspect_codex_exec_server_start_v1(&intent, raw)
            .unwrap_or_else(|error| panic!("{}: P2c inspection: {error}", case.id));
        assert_eq!(observation.original_wire_sha256, intent.payload_sha256);
        let temp = TempDir::new().expect("test directory");
        let cfg = config(&temp);
        let writer = HeptaEvidenceStore::open(&cfg)
            .await
            .expect("original writer");
        let prepared = writer
            .prepare_execution_intent_v1(&intent, raw)
            .await
            .expect("original Evidence atomic preparation");
        assert_eq!(
            prepared.readback.status,
            ExecutionPreparationReadbackStatusV1::RecordedOnly
        );
        writer.close().await;

        let reader = HeptaEvidenceStore::open_existing_read_only(&cfg)
            .await
            .expect("cold original Evidence reopen");
        let recovered = reader
            .recover_execution_preparation_by_key_v1(&prepared.readback.provider_effect_key)
            .await
            .expect("source-free original lookup")
            .expect("complete original envelope");
        assert_eq!(recovered.intent, intent, "{}", case.id);
        assert_eq!(
            recovered.readback.request_sha256,
            observation.request_sha256
        );
        assert_eq!(
            recovered.readback.status,
            ExecutionPreparationReadbackStatusV1::RecordedOnly
        );
        let decision = reader
            .audit_execution_effect_entry_denied_v1(&recovered.intent, raw)
            .await
            .expect("original read-only deny audit");
        assert_eq!(
            decision.denied,
            ExecutionEffectEntryDeniedV1::IndependentFinalUseAndPhysicalOwnerUnavailable,
            "{}",
            case.id
        );
        assert_eq!(decision.request_sha256, observation.request_sha256);

        let mut changed_wire = raw.to_vec();
        changed_wire.push(b' ');
        assert!(inspect_codex_exec_server_start_v1(&intent, &changed_wire).is_err());
        assert!(matches!(
            reader
                .audit_execution_effect_entry_denied_v1(&recovered.intent, &changed_wire)
                .await,
            Err(EvidenceError::InvalidRecord(_))
        ));
        let stale = ExecutionIntentV1 {
            fence: intent.fence + 1,
            ..intent
        };
        assert!(matches!(
            reader
                .audit_execution_effect_entry_denied_v1(&stale, raw)
                .await,
            Err(EvidenceError::IdempotencyConflict { .. })
        ));
        reader.close().await;
        admitted += 1;
    }
    assert_eq!(admitted, EXPECTED_ACCEPTED);
}

#[tokio::test]
async fn indeterminate_original_after_cold_reopen_remains_denied_without_retry() {
    let corpus = corpus();
    let case = corpus
        .cases
        .iter()
        .find(|case| case.hepta_accepts)
        .expect("P2c admitted case");
    let raw = case.raw.as_bytes();
    let intent = intent_for(&corpus.operation_id, raw);
    inspect_codex_exec_server_start_v1(&intent, raw).expect("original P2c preflight");

    let temp = TempDir::new().expect("test directory");
    let cfg = config(&temp);
    let writer = HeptaEvidenceStore::open(&cfg)
        .await
        .expect("original writer");
    let prepared = writer
        .prepare_execution_intent_v1(&intent, raw)
        .await
        .expect("atomic original prepare");
    writer
        .mark_provider_effect_indeterminate(
            &prepared.readback.provider_effect_key,
            "p2f_indeterminate_no_replay",
        )
        .await
        .expect("original ambiguity quarantine");
    writer.close().await;

    let reader = HeptaEvidenceStore::open_existing_read_only(&cfg)
        .await
        .expect("cold original Evidence reopen");
    let recovered = reader
        .recover_execution_preparation_by_key_v1(&prepared.readback.provider_effect_key)
        .await
        .expect("original owner recovery")
        .expect("complete original intent");
    assert_eq!(recovered.intent, intent);
    assert_eq!(
        recovered.readback.status,
        ExecutionPreparationReadbackStatusV1::OriginalOwnerReconciliationRequired
    );
    let denial = reader
        .audit_execution_effect_entry_denied_v1(&recovered.intent, raw)
        .await
        .expect("must refuse ambiguous original");
    assert_eq!(
        denial.denied,
        ExecutionEffectEntryDeniedV1::OriginalOwnerReconciliationRequired
    );
    reader.close().await;
}

#[test]
fn all_unadmitted_wires_are_rejected_before_test_only_evidence_composition() {
    let corpus = corpus();
    let mut excluded = 0_usize;
    for case in corpus.cases.iter().filter(|case| !case.hepta_accepts) {
        let raw = case.raw.as_bytes();
        let intent = intent_for(&corpus.operation_id, raw);
        assert!(
            inspect_codex_exec_server_start_v1(&intent, raw).is_err(),
            "unexpected admitted wire: {}",
            case.id
        );
        excluded += 1;
    }
    assert_eq!(excluded, 50 - EXPECTED_ACCEPTED);
}
