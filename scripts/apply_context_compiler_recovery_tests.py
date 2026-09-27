#!/usr/bin/env python3
"""Add process-reopen terminal reconciliation tests to the V3 runtime fixture."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "codex-rs/hepta-agentd/src/exact_context_delivery/registry_race_tests.rs"


def replace(old: str, new: str) -> None:
    text = PATH.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"registry_race_tests.rs: expected one recovery test anchor, found {count}")
    PATH.write_text(text.replace(old, new, 1), encoding="utf-8")


replace(
    '''struct Fixture {
    _directory: tempfile::TempDir,
    owner: Arc<AgentdExactContextDeliveryOwner>,
''',
    '''struct Fixture {
    directory: tempfile::TempDir,
    registry_path: PathBuf,
    runtime_path: PathBuf,
    owner: Arc<AgentdExactContextDeliveryOwner>,
''',
)
replace(
    '''        let request = PromptRuntimeFinalRequestV2 {
            attachment,
            attempt: PromptRuntimeExactAttemptV2 {
''',
    '''        let canonical_request = serde_json::to_vec(&serde_json::json!({
            "model": "model",
            "input": [{
                "role": "developer",
                "content": [{"type": "input_text", "text": context}]
            }]
        }))
        .expect("request JSON");
        let request = PromptRuntimeFinalRequestV2 {
            attachment,
            attempt: PromptRuntimeExactAttemptV2 {
''',
)
replace(
    '''                ephemeral_input_digest: None,
                ephemeral_input_witness_digest: None,
''',
    '''                ephemeral_input_digest: Some(Digest32::of_bytes(&canonical_request)),
                ephemeral_input_witness_digest: Some(digest("provider-input-witness")),
''',
)
replace(
    '''            canonical_request: serde_json::to_vec(&serde_json::json!({
                "model": "model",
                "input": [{
                    "role": "developer",
                    "content": [{"type": "input_text", "text": context}]
                }]
            }))
            .expect("request JSON"),
        };
        let owner = Arc::new(
            AgentdExactContextDeliveryOwner::open(
                &directory.path().join("runtime"),
                Arc::new(Mutex::new(registry)),
            )
            .expect("owner"),
        );
''',
    '''            canonical_request,
        };
        let runtime_path = directory.path().join("runtime");
        let owner = Arc::new(
            AgentdExactContextDeliveryOwner::open(
                &runtime_path,
                Arc::new(Mutex::new(registry)),
            )
            .expect("owner"),
        );
''',
)
replace(
    '''        Self {
            _directory: directory,
            owner,
''',
    '''        Self {
            directory,
            registry_path,
            runtime_path,
            owner,
''',
)

with PATH.open("a", encoding="utf-8") as stream:
    stream.write(r'''

async fn wait_for_path(path: &Path) {
    tokio::time::timeout(Duration::from_secs(3), async {
        while !path.exists() {
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    })
    .await
    .expect("fixture barrier");
}

fn terminal_for(
    request: &PromptRuntimeFinalRequestV2,
    terminal: PromptRuntimeProviderTerminalV2,
    observed_unix_ms: u64,
) -> PromptRuntimeFinalTerminalV2 {
    PromptRuntimeFinalTerminalV2 {
        attachment: request.attachment.clone(),
        attempt: request.attempt.clone(),
        terminal,
        observed_unix_ms,
    }
}

#[tokio::test]
async fn crash_reopen_reconciles_indeterminate_then_final_without_redispatch() {
    let Fixture {
        directory,
        registry_path,
        runtime_path,
        owner,
        request,
        entered,
        release,
        ..
    } = Fixture::new();
    let send = tokio::spawn(Arc::clone(&owner).observe_final_request(request.clone()));
    wait_for_path(&entered).await;
    std::fs::write(&release, b"release").expect("release tokenizer");
    assert_eq!(send.await.expect("join"), Ok(()));
    assert!(
        owner
            .state
            .lock()
            .expect("state")
            .durable
            .has_unresolved_attempt(&request.attempt.attempt_id)
    );
    drop(owner);

    let registry = DurablePromptRegistry::open_state_dir(&registry_path, 64)
        .expect("reopen registry");
    let reopened = Arc::new(
        AgentdExactContextDeliveryOwner::open(
            &runtime_path,
            Arc::new(Mutex::new(registry)),
        )
        .expect("reopen exact owner"),
    );
    let first_observed = current_unix_ms().expect("clock");
    reopened
        .observe_final_terminal(terminal_for(
            &request,
            PromptRuntimeProviderTerminalV2::Indeterminate {
                reason_code: "provider_pending".to_owned(),
                partial_response_digest: None,
            },
            first_observed,
        ))
        .await
        .expect("record recovered indeterminate");
    assert!(
        reopened
            .state
            .lock()
            .expect("state")
            .durable
            .has_unresolved_attempt(&request.attempt.attempt_id)
    );

    let final_observed = first_observed.saturating_add(1);
    let final_terminal = terminal_for(
        &request,
        PromptRuntimeProviderTerminalV2::CompletedUnary {
            response_items_digest: digest("recovered-response-items"),
        },
        final_observed,
    );
    reopened
        .observe_final_terminal(final_terminal.clone())
        .await
        .expect("reconcile recovered final");
    assert!(
        !reopened
            .state
            .lock()
            .expect("state")
            .durable
            .has_unresolved_attempt(&request.attempt.attempt_id)
    );
    reopened
        .observe_final_terminal(final_terminal)
        .await
        .expect("identical final is idempotent");

    let conflict = reopened
        .observe_final_terminal(terminal_for(
            &request,
            PromptRuntimeProviderTerminalV2::Rejected {
                reason_code: "different_terminal".to_owned(),
            },
            final_observed.saturating_add(1),
        ))
        .await;
    assert!(matches!(conflict, Err(ExactContextDeliveryError::Conflict(_))));
    drop(reopened);
    drop(directory);
}

#[tokio::test]
async fn legacy_digest_only_pre_send_remains_non_recoverable() {
    let directory = tempfile::tempdir().expect("tempdir");
    let (store, mut state) = ExactDeliveryStore::open(directory.path()).expect("open");
    state.pre_sends.insert(
        "legacy-attempt".to_owned(),
        stored_pre_send("legacy-thread", "legacy-turn", "legacy-attempt"),
    );
    store.persist(&state).expect("persist legacy record");
    drop(store);
    let (_store, reopened) = ExactDeliveryStore::open(directory.path()).expect("reopen");
    let legacy = reopened.pre_sends.get("legacy-attempt").expect("legacy record");
    assert!(legacy.recovery_archive.is_none());
    assert_eq!(legacy.recovery_binding_digest, [0; 32]);
    assert!(reopened.has_unresolved_attempt("legacy-attempt"));
}
''')
