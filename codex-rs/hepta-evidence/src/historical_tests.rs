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

use crate::HeptaEvidenceStore;
use crate::HistoricalEvidenceFamily;
use crate::HistoricalEvidenceSelector;
use crate::HistoricalEvidenceState;

fn digest(value: &str) -> Sha256Digest {
    Sha256Digest::for_bytes(value.as_bytes())
}

fn sqlite_config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    )
}

fn governance_decision() -> GovernanceDecisionRecord {
    GovernanceDecisionRecord::new(
        ToolAction {
            schema_version: GOVERNANCE_SCHEMA_VERSION,
            action_id: ActionId::for_tool_call("thread-1", "turn-1", "call-1"),
            thread_id: "thread-1".to_string(),
            turn_id: "turn-1".to_string(),
            call_id: "call-1".to_string(),
            tool_name: "exec_command".to_string(),
            source: ToolActionSource::Direct,
            payload_sha256: digest("governance-payload"),
        },
        PolicyPhase::Admission,
        GovernanceMode::Enforce,
        PolicyStamp::new("hepta.historical.clean.v1", 1, b"allow"),
        GovernanceDecision::Allow,
    )
}

fn provider_intent() -> ProviderInvocationIntent {
    ProviderInvocationIntent::new(
        [7; 16],
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
async fn supported_families_project_exact_pending_and_terminal_records() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");

    let governance = governance_decision();
    store
        .append_decision(&governance)
        .await
        .expect("append governance decision");
    let governance_selector = HistoricalEvidenceSelector::new(
        HistoricalEvidenceFamily::GovernanceAction,
        governance.action.action_id.as_str(),
    )
    .expect("governance selector");
    let pending_governance = store
        .historical_record(&governance_selector)
        .await
        .expect("governance pending read")
        .expect("governance record");
    assert_eq!(pending_governance.state(), HistoricalEvidenceState::Pending);
    pending_governance.validate().expect("valid pending record");
    store
        .append_receipt(&GovernanceReceipt::new(
            governance,
            None,
            false,
            HandlerOutcome::Blocked,
        ))
        .await
        .expect("append governance receipt");
    let terminal_governance = store
        .historical_record(&governance_selector)
        .await
        .expect("governance terminal read")
        .expect("governance record");
    assert_eq!(
        terminal_governance.state(),
        HistoricalEvidenceState::Blocked
    );
    terminal_governance
        .validate()
        .expect("valid terminal record");
    assert_eq!(
        terminal_governance.evidence_sha256().as_str(),
        "80d0e241acf0a00cfff9039cd47e020cae27d5848090245e799141654cc1e4fd"
    );
    assert_eq!(
        terminal_governance.record_sha256().as_str(),
        "4643d51d30887406cb8bf81a9b67caac1068fc127a00d1d494e1b8f409ec665f"
    );
    assert_ne!(
        terminal_governance.record_sha256(),
        pending_governance.record_sha256()
    );

    let provider = provider_intent();
    store
        .append_provider_intent(&provider)
        .await
        .expect("append provider intent");
    let provider_selector = HistoricalEvidenceSelector::new(
        HistoricalEvidenceFamily::ProviderAttempt,
        provider.attempt_id.as_str(),
    )
    .expect("provider selector");
    let pending_provider = store
        .historical_record(&provider_selector)
        .await
        .expect("provider pending read")
        .expect("provider record");
    assert_eq!(pending_provider.state(), HistoricalEvidenceState::Pending);
    store
        .append_provider_receipt(&ProviderInvocationReceipt::new(
            provider,
            ProviderTerminal::Completed {
                response_id_sha256: digest("response-id"),
                response_items_sha256: digest("response-items"),
                token_usage_sha256: digest("token-usage"),
                end_turn: Some(true),
            },
        ))
        .await
        .expect("append provider receipt");
    let terminal_provider = store
        .historical_record(&provider_selector)
        .await
        .expect("provider terminal read")
        .expect("provider record");
    assert_eq!(
        terminal_provider.state(),
        HistoricalEvidenceState::Completed
    );
    terminal_provider.validate().expect("valid provider record");
    assert_eq!(
        terminal_provider.evidence_sha256().as_str(),
        "dae31fa650a51d925958dd9614eaa79a4ed60472b398da909506708e02972527"
    );
    assert_eq!(
        terminal_provider.record_sha256().as_str(),
        "8197318225a1c5c6ef936fb0dc0d2077b90b2530af4b367c5402b70dc88cf921"
    );

    drop(store);
    let reopened = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("reopen evidence");
    assert_eq!(
        reopened
            .historical_record(&governance_selector)
            .await
            .expect("restart governance")
            .expect("restart record"),
        terminal_governance
    );
    assert_eq!(
        reopened
            .historical_record(&provider_selector)
            .await
            .expect("restart provider")
            .expect("restart record"),
        terminal_provider
    );
}

#[tokio::test]
async fn missing_exact_ids_return_none_without_cross_family_fallback() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    for (family, record_id) in [
        (
            HistoricalEvidenceFamily::GovernanceAction,
            format!("tool:v1:{}", "a".repeat(64)),
        ),
        (
            HistoricalEvidenceFamily::ProviderAttempt,
            format!("provider-attempt:v1:{}", "b".repeat(64)),
        ),
    ] {
        let selector = HistoricalEvidenceSelector::new(family, record_id).expect("selector");
        assert!(
            store
                .historical_record(&selector)
                .await
                .expect("historical read")
                .is_none()
        );
    }
    assert!(
        HistoricalEvidenceSelector::new(
            HistoricalEvidenceFamily::ProviderAttempt,
            format!("tool:v1:{}", "a".repeat(64)),
        )
        .is_err()
    );
}

#[tokio::test]
async fn historical_read_fails_closed_on_corrupt_authoritative_payload() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    let governance = governance_decision();
    store
        .append_decision(&governance)
        .await
        .expect("append governance decision");
    let selector = HistoricalEvidenceSelector::new(
        HistoricalEvidenceFamily::GovernanceAction,
        governance.action.action_id.as_str(),
    )
    .expect("governance selector");
    sqlx::query("DROP TRIGGER governance_decisions_no_update")
        .execute(&store.pool)
        .await
        .expect("remove immutability guard for corruption fixture");
    sqlx::query("UPDATE governance_decisions SET payload_json = '{}' WHERE action_id = ?")
        .bind(governance.action.action_id.as_str())
        .execute(&store.pool)
        .await
        .expect("damage fixture payload");

    let error = store
        .historical_record(&selector)
        .await
        .expect_err("corrupt evidence must not be projected");
    assert!(error.to_string().contains("corrupt"));
}

#[tokio::test]
async fn provider_historical_read_fails_closed_on_corrupt_authoritative_payload() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    let provider = provider_intent();
    store
        .append_provider_intent(&provider)
        .await
        .expect("append provider intent");
    let selector = HistoricalEvidenceSelector::new(
        HistoricalEvidenceFamily::ProviderAttempt,
        provider.attempt_id.as_str(),
    )
    .expect("provider selector");
    sqlx::query("DROP TRIGGER provider_invocation_intents_no_update")
        .execute(&store.pool)
        .await
        .expect("remove immutability guard for corruption fixture");
    sqlx::query("UPDATE provider_invocation_intents SET payload_json = '{}' WHERE attempt_id = ?")
        .bind(provider.attempt_id.as_str())
        .execute(&store.pool)
        .await
        .expect("damage fixture payload");

    let error = store
        .historical_record(&selector)
        .await
        .expect_err("corrupt provider evidence must not be projected");
    assert!(error.to_string().contains("corrupt"));
}
