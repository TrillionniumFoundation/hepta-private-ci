type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

use super::*;
use codex_history::TurnRecoveryEnvironmentSelection;
use codex_history::TurnRecoveryHistoryBoundary;
use codex_history::TurnRecoveryReplayV1;
use codex_history::TurnRecoveryRequestBinding;
use codex_history::TurnRecoveryStartState;
use codex_protocol::items::UserMessageItem;
use codex_protocol::protocol::ErrorEvent;
use codex_protocol::protocol::ItemStartedEvent;
use codex_protocol::protocol::SessionMeta;
use codex_protocol::protocol::SessionMetaLine;
use codex_protocol::protocol::TurnAbortReason;
use codex_protocol::protocol::TurnAbortedEvent;
use codex_protocol::protocol::TurnCompleteEvent;
use codex_protocol::protocol::TurnRecoveryCandidateEvent;
use codex_protocol::protocol::TurnStartedEvent;
use codex_protocol::protocol::UserMessageEvent;
use codex_state::SqliteConfig;
use codex_state::StateRuntime;
use codex_thread_store::LocalQueueStore;
use codex_utils_absolute_path::test_support::PathExt;
use pretty_assertions::assert_eq;
use std::collections::BTreeMap;
use std::io::Write;
use tempfile::TempDir;

#[tokio::test]
async fn incomplete_or_oversized_tail_discards_a_previously_seen_terminal() -> TestResult {
    let home = TempDir::new()?;
    let runtime = StateRuntime::init(
        SqliteConfig::new_for_testing(home.path().abs()),
        "test-provider".to_string(),
    )
    .await?;
    let observer = QueueHistoricalObserver::new(Arc::new(LocalQueueStore::new(runtime)));
    let thread_id = ThreadId::new();
    let digest = user_input_payload_sha256(&content("exact input"))?;
    let history = HistoryFile::new(
        thread_id,
        &[
            started("turn-a"),
            user_item(thread_id, "turn-a", "client-a", "exact input"),
            completed("turn-a", /*error*/ None),
        ],
    )?;
    for tail in [b"partial".to_vec(), vec![b'x'; 1024 * 1024 + 1]] {
        history.write(&[
            started("turn-a"),
            user_item(thread_id, "turn-a", "client-a", "exact input"),
            completed("turn-a", /*error*/ None),
        ])?;
        let mut file = std::fs::OpenOptions::new()
            .append(true)
            .open(&history.path)?;
        file.write_all(&tail)?;
        file.sync_all()?;
        assert_eq!(
            observer
                .observe(thread_id, Some(&history.path), "client-a", &digest)
                .await?
                .outcome,
            QueueHistoricalOutcome::Unknown
        );
    }
    Ok(())
}

struct HistoryFile {
    _directory: TempDir,
    path: PathBuf,
    thread_id: ThreadId,
}

impl HistoryFile {
    fn new(thread_id: ThreadId, items: &[RolloutItem]) -> TestResult<Self> {
        let directory = TempDir::new()?;
        let history = Self {
            path: directory.path().join("rollout.jsonl"),
            _directory: directory,
            thread_id,
        };
        history.write(items)?;
        Ok(history)
    }

    fn write(&self, items: &[RolloutItem]) -> TestResult {
        let metadata = RolloutItem::SessionMeta(SessionMetaLine {
            meta: SessionMeta {
                session_id: self.thread_id.into(),
                id: self.thread_id,
                timestamp: "2026-09-30T20:00:00Z".to_string(),
                ..Default::default()
            },
            git: None,
        });
        let mut file = std::fs::File::create(&self.path)?;
        for item in std::iter::once(&metadata).chain(items) {
            serde_json::to_writer(
                &mut file,
                &RolloutLine {
                    timestamp: "2026-09-30T20:00:00Z".to_string(),
                    ordinal: None,
                    item: item.clone(),
                },
            )?;
            file.write_all(b"\n")?;
        }
        file.sync_all()?;
        Ok(())
    }
}

fn content(text: &str) -> Vec<UserInput> {
    vec![UserInput::Text {
        text: text.to_string(),
        text_elements: Vec::new(),
    }]
}

fn started(turn_id: &str) -> RolloutItem {
    RolloutItem::EventMsg(EventMsg::TurnStarted(TurnStartedEvent {
        turn_id: turn_id.to_string(),
        trace_id: None,
        started_at: Some(100),
        model_context_window: None,
        collaboration_mode_kind: Default::default(),
    }))
}

fn user_item(thread_id: ThreadId, turn_id: &str, client_id: &str, text: &str) -> RolloutItem {
    RolloutItem::EventMsg(EventMsg::ItemStarted(ItemStartedEvent {
        thread_id,
        turn_id: turn_id.to_string(),
        item: TurnItem::UserMessage(UserMessageItem {
            id: "user-item".to_string(),
            client_id: Some(client_id.to_string()),
            content: content(text),
        }),
        started_at_ms: 100_000,
    }))
}

fn completed(turn_id: &str, error: Option<ErrorEvent>) -> RolloutItem {
    RolloutItem::EventMsg(EventMsg::TurnComplete(TurnCompleteEvent {
        turn_id: turn_id.to_string(),
        last_agent_message: None,
        error,
        started_at: Some(100),
        completed_at: Some(101),
        duration_ms: Some(1_000),
        time_to_first_token_ms: None,
    }))
}

fn aborted(turn_id: &str) -> RolloutItem {
    RolloutItem::EventMsg(EventMsg::TurnAborted(TurnAbortedEvent {
        turn_id: Some(turn_id.to_string()),
        reason: TurnAbortReason::Interrupted,
        started_at: Some(100),
        completed_at: Some(101),
        duration_ms: Some(1_000),
    }))
}

fn recovery_binding(turn_id: &str) -> RolloutItem {
    let boundary = TurnRecoveryHistoryBoundary {
        item_count: 1,
        prefix_sha256: "prefix".to_string(),
    };
    RolloutItem::TurnRecoveryRequestBinding(TurnRecoveryRequestBinding {
        turn_id: turn_id.to_string(),
        generation: 8,
        fingerprint_sha256: "fingerprint".to_string(),
        history_boundary: Some(boundary.clone()),
        replay: Some(TurnRecoveryReplayV1 {
            history_boundary: boundary,
            turn_context_sha256: "context".to_string(),
            start: TurnRecoveryStartState {
                final_output_json_schema: None,
                parent_turn_id: None,
                root_turn_id: Some(turn_id.to_string()),
                responses_metadata_extra: BTreeMap::new(),
            },
            environments: vec![TurnRecoveryEnvironmentSelection {
                environment_id: "environment".to_string(),
                cwd: "/tmp".to_string(),
                workspace_roots: vec!["/tmp".to_string()],
            }],
        }),
        replay_applied_from_generation: Some(7),
    })
}

async fn scan(
    file: &HistoryFile,
) -> Result<Option<(String, Option<QueueHistoricalTerminal>)>, QueueServiceError> {
    scan_history(
        Some(&file.path),
        "client-a",
        &user_input_payload_sha256(&content("exact input"))
            .map_err(|_| QueueServiceError::InvalidInput)?,
        PersistedClientJoinMode::ExactHistorical(file.thread_id),
    )
    .await
}

#[tokio::test]
async fn historical_scanner_requires_explicit_matching_terminal_records() -> TestResult {
    let thread_id = ThreadId::new();
    let prefix = vec![
        started("turn-a"),
        user_item(thread_id, "turn-a", "client-a", "exact input"),
    ];
    let history = HistoryFile::new(thread_id, &prefix)?;
    assert_eq!(scan(&history).await?, Some(("turn-a".to_string(), None)));
    for (terminal, expected) in [
        (
            completed("turn-a", /*error*/ None),
            QueueHistoricalTerminal::Completed,
        ),
        (aborted("turn-a"), QueueHistoricalTerminal::Interrupted),
        (
            completed(
                "turn-a",
                Some(ErrorEvent {
                    message: "provider failed".to_string(),
                    codex_error_info: None,
                }),
            ),
            QueueHistoricalTerminal::Failed,
        ),
    ] {
        let mut items = prefix.clone();
        items.push(terminal);
        history.write(&items)?;
        assert_eq!(
            scan(&history).await?,
            Some(("turn-a".to_string(), Some(expected)))
        );
    }
    Ok(())
}

#[tokio::test]
async fn historical_scanner_clears_prior_terminal_for_strict_recovery_restart() -> TestResult {
    let thread_id = ThreadId::new();
    let mut items = vec![
        started("turn-a"),
        user_item(thread_id, "turn-a", "client-a", "exact input"),
        aborted("turn-a"),
        RolloutItem::EventMsg(EventMsg::TurnRecoveryCandidate(
            TurnRecoveryCandidateEvent {
                turn_id: "turn-a".to_string(),
                generation: 8,
                state: TurnRecoveryCandidateState::Unready,
            },
        )),
        recovery_binding("turn-a"),
        started("turn-a"),
    ];
    let history = HistoryFile::new(thread_id, &items)?;
    assert_eq!(scan(&history).await?, Some(("turn-a".to_string(), None)));
    items.push(completed("turn-a", /*error*/ None));
    history.write(&items)?;
    assert_eq!(
        scan(&history).await?,
        Some((
            "turn-a".to_string(),
            Some(QueueHistoricalTerminal::Completed)
        ))
    );
    Ok(())
}

#[tokio::test]
async fn historical_scanner_rejects_payload_ambiguity_and_legacy_only_joins() -> TestResult {
    let thread_id = ThreadId::new();
    let history = HistoryFile::new(
        thread_id,
        &[
            started("turn-a"),
            user_item(thread_id, "turn-a", "client-a", "different input"),
        ],
    )?;
    assert!(matches!(
        scan(&history).await,
        Err(QueueServiceError::ClientIdPayloadConflict { .. })
    ));
    history.write(&[
        started("turn-a"),
        user_item(thread_id, "turn-a", "client-a", "exact input"),
        completed("turn-a", /*error*/ None),
        started("turn-b"),
        user_item(thread_id, "turn-b", "client-a", "exact input"),
    ])?;
    assert!(matches!(
        scan(&history).await,
        Err(QueueServiceError::AmbiguousClientIdBinding { .. })
    ));
    history.write(&[
        started("turn-a"),
        RolloutItem::EventMsg(EventMsg::UserMessage(UserMessageEvent {
            client_id: Some("client-a".to_string()),
            message: "exact input".to_string(),
            payload_sha256: Some(user_input_payload_sha256(&content("exact input"))?),
            ..Default::default()
        })),
        completed("turn-a", /*error*/ None),
    ])?;
    assert!(matches!(
        scan(&history).await,
        Err(QueueServiceError::LegacyClientIdBinding { .. })
    ));
    Ok(())
}

#[tokio::test]
async fn pure_observer_checks_thread_identity_and_missing_never_becomes_terminal() -> TestResult {
    let home = TempDir::new()?;
    let runtime = StateRuntime::init(
        SqliteConfig::new_for_testing(home.path().abs()),
        "test-provider".to_string(),
    )
    .await?;
    let observer = QueueHistoricalObserver::new(Arc::new(LocalQueueStore::new(runtime.clone())));
    let thread_id = ThreadId::new();
    let digest = user_input_payload_sha256(&content("exact input"))?;
    assert_eq!(
        observer
            .observe(thread_id, /*rollout_path*/ None, "client-a", &digest)
            .await?,
        QueueHistoricalObservation {
            client_user_message_id: "client-a".to_string(),
            payload_sha256: digest.clone(),
            outcome: QueueHistoricalOutcome::Missing
        }
    );
    let history = HistoryFile::new(
        thread_id,
        &[
            started("turn-a"),
            user_item(thread_id, "turn-a", "other-client", "exact input"),
            completed("turn-a", /*error*/ None),
        ],
    )?;
    assert_eq!(
        observer
            .observe(thread_id, Some(&history.path), "client-a", &digest)
            .await?
            .outcome,
        QueueHistoricalOutcome::Missing
    );
    assert!(
        observer
            .observe(ThreadId::new(), Some(&history.path), "client-a", &digest)
            .await
            .is_err()
    );
    assert_eq!(
        runtime
            .thread_queue()
            .list_page(thread_id, /*offset*/ 0, /*limit*/ 100)
            .await?,
        Vec::new()
    );
    assert_eq!(
        runtime
            .thread_queue()
            .observe_client_binding(thread_id, "client-a", &digest)
            .await?,
        None
    );
    history.write(&[
        started("turn-a"),
        user_item(thread_id, "turn-a", "client-a", "exact input"),
        completed("turn-a", /*error*/ None),
    ])?;
    assert_eq!(
        observer
            .observe(thread_id, Some(&history.path), "client-a", &digest)
            .await?
            .outcome,
        QueueHistoricalOutcome::Persisted {
            turn_id: "turn-a".to_string(),
            terminal: Some(QueueHistoricalTerminal::Completed)
        }
    );
    assert_eq!(
        runtime
            .thread_queue()
            .observe_client_binding(thread_id, "client-a", &digest)
            .await?,
        None
    );
    Ok(())
}
