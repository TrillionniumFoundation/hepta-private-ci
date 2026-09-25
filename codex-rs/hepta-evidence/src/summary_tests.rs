use codex_hepta_contracts::ActionId;
use codex_hepta_contracts::GOVERNANCE_SCHEMA_VERSION;
use codex_hepta_contracts::GovernanceDecision;
use codex_hepta_contracts::GovernanceDecisionRecord;
use codex_hepta_contracts::GovernanceMode;
use codex_hepta_contracts::GovernanceReceipt;
use codex_hepta_contracts::HandlerOutcome;
use codex_hepta_contracts::PROVIDER_EVIDENCE_SCHEMA_VERSION;
use codex_hepta_contracts::PolicyPhase;
use codex_hepta_contracts::PolicyStamp;
use codex_hepta_contracts::ProviderInvocationIntent;
use codex_hepta_contracts::ProviderInvocationReceipt;
use codex_hepta_contracts::ProviderRequestBinding;
use codex_hepta_contracts::ProviderRequestKind;
use codex_hepta_contracts::ProviderTerminal;
use codex_hepta_contracts::ProviderTransport;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::ToolAction;
use codex_hepta_contracts::ToolActionSource;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use tempfile::TempDir;

use crate::AppendDisposition;
use crate::EvidenceSummary;
use crate::HeptaEvidenceStore;

fn sqlite_config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    )
}

fn digest(value: &str) -> Sha256Digest {
    Sha256Digest::for_bytes(value.as_bytes())
}

fn decision() -> GovernanceDecisionRecord {
    GovernanceDecisionRecord::new(
        ToolAction {
            schema_version: GOVERNANCE_SCHEMA_VERSION,
            action_id: ActionId::for_tool_call("thread-1", "turn-1", "call-1"),
            thread_id: "thread-1".to_string(),
            turn_id: "turn-1".to_string(),
            call_id: "call-1".to_string(),
            tool_name: "exec_command".to_string(),
            source: ToolActionSource::Direct,
            payload_sha256: digest("payload"),
        },
        PolicyPhase::Admission,
        GovernanceMode::Shadow,
        PolicyStamp::new("hepta.summary.test.v1", 1, b"allow"),
        GovernanceDecision::Allow,
    )
}

fn provider_intent(nonce: [u8; 16]) -> ProviderInvocationIntent {
    ProviderInvocationIntent::new(
        nonce,
        ProviderRequestBinding {
            schema_version: PROVIDER_EVIDENCE_SCHEMA_VERSION,
            thread_id: "thread-1".to_string(),
            turn_id: "turn-1".to_string(),
            host_request_binding_id_sha256: digest("host-binding"),
            request_kind: ProviderRequestKind::Turn,
            provider_id: "fixture-provider".to_string(),
            provider_config_sha256: digest("provider-config"),
            model: "fixture-model".to_string(),
            transport: ProviderTransport::Http,
            endpoint_sha256: digest("/responses"),
            logical_request_sha256: digest("logical"),
            ephemeral_input_sha256: None,
            ephemeral_input_witness_sha256: None,
            wire_semantic_sha256: digest("wire"),
            previous_response_id_sha256: None,
            generate: true,
        },
    )
}

#[tokio::test]
async fn empty_summary_is_explicitly_zero_for_supported_families() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");

    assert_eq!(
        store.summary().await.expect("summary"),
        EvidenceSummary::default()
    );
}

#[tokio::test]
async fn governance_summary_moves_from_pending_to_terminal() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    let decision = decision();
    assert_eq!(
        store.append_decision(&decision).await.expect("decision"),
        AppendDisposition::Inserted
    );
    let pending = store.summary().await.expect("pending summary");
    assert_eq!(pending.governance.decisions, 1);
    assert_eq!(pending.governance.receipts, 0);
    assert_eq!(pending.governance.pending_actions, 1);

    let receipt = GovernanceReceipt::new(decision, None, false, HandlerOutcome::Blocked);
    assert_eq!(
        store.append_receipt(&receipt).await.expect("receipt"),
        AppendDisposition::Inserted
    );
    let terminal = store.summary().await.expect("terminal summary");
    assert_eq!(terminal.governance.decisions, 1);
    assert_eq!(terminal.governance.receipts, 1);
    assert_eq!(terminal.governance.pending_actions, 0);
}

#[tokio::test]
async fn provider_summary_distinguishes_pending_and_indeterminate_attempts() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    let pending = provider_intent([7; 16]);
    let indeterminate = provider_intent([8; 16]);
    store
        .append_provider_intent(&pending)
        .await
        .expect("append pending provider intent");
    store
        .append_provider_intent(&indeterminate)
        .await
        .expect("append indeterminate provider intent");
    store
        .append_provider_receipt(&ProviderInvocationReceipt::new(
            indeterminate,
            ProviderTerminal::Indeterminate {
                reason_code: "transport_lost".to_string(),
                partial_response_sha256: None,
            },
        ))
        .await
        .expect("append provider receipt");

    let summary = store.summary().await.expect("provider summary");
    assert_eq!(summary.provider.intents, 2);
    assert_eq!(summary.provider.receipts, 1);
    assert_eq!(summary.provider.pending_attempts, 1);
    assert_eq!(summary.provider.indeterminate_attempts, 1);
}

#[tokio::test]
async fn summary_fails_closed_when_supported_schema_is_missing() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    sqlx::query("DROP TABLE provider_invocation_terminals")
        .execute(&store.pool)
        .await
        .expect("damage fixture schema");

    let error = store
        .summary()
        .await
        .expect_err("missing supported schema must not project zero");
    assert!(error.to_string().contains("unavailable"));
}
