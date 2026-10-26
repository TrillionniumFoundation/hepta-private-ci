use std::time::Duration;

use anyhow::Result;
use codex_protocol::ThreadId;
use codex_protocol::dynamic_tools::DynamicToolCallOutputContentItem;
use codex_protocol::items::DynamicToolCallItem;
use codex_protocol::items::DynamicToolCallStatus;
use codex_protocol::items::TurnItem;
use codex_protocol::models::BaseInstructions;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::ItemCompletedEvent;
use codex_protocol::protocol::ItemStartedEvent;
use codex_protocol::protocol::SessionSource;
use codex_protocol::protocol::ThreadHistoryMode;
use codex_utils_absolute_path::test_support::PathExt;
use pretty_assertions::assert_eq;
use serde_json::json;
use tempfile::TempDir;

use crate::RolloutConfig;
use crate::RolloutItem;
use crate::RolloutRecorder;
use crate::RolloutRecorderParams;
use crate::persisted_rollout_items;

#[tokio::test]
async fn dynamic_tool_terminals_survive_original_rollout_shutdown_and_readback() -> Result<()> {
    for history_mode in [ThreadHistoryMode::Legacy, ThreadHistoryMode::Paginated] {
        let home = TempDir::new()?;
        let config = RolloutConfig {
            codex_home: home.path().to_path_buf(),
            sqlite: codex_state::SqliteConfig::new_for_testing(home.path().abs()),
            cwd: home.path().to_path_buf(),
            model_provider_id: "test-provider".to_string(),
            generate_memories: true,
        };
        let thread_id = ThreadId::new();
        let recorder = RolloutRecorder::new(
            &config,
            RolloutRecorderParams::new(
                thread_id,
                /*forked_from_id*/ None,
                /*parent_thread_id*/ None,
                SessionSource::Exec,
                /*thread_source*/ None,
                "dynamic-tool-persistence-test".to_string(),
                BaseInstructions::default(),
                Vec::new(),
            )
            .with_history_mode(history_mode),
        )
        .await?;
        let mut live_items = Vec::new();
        let mut expected = Vec::new();
        for (status, success, error) in [
            (DynamicToolCallStatus::Completed, true, None),
            (
                DynamicToolCallStatus::Failed,
                false,
                Some("original client rejected this call".to_string()),
            ),
        ] {
            let started = DynamicToolCallItem {
                id: format!("call-{status:?}"),
                namespace: Some("test_namespace".to_string()),
                tool: "replace_note".to_string(),
                arguments: json!({"text": "原线程的审阅文本"}),
                status: DynamicToolCallStatus::InProgress,
                content_items: None,
                success: None,
                error: None,
                duration: None,
            };
            live_items.push(RolloutItem::EventMsg(EventMsg::ItemStarted(
                ItemStartedEvent {
                    thread_id,
                    turn_id: "original-turn".to_string(),
                    item: TurnItem::DynamicToolCall(started.clone()),
                    started_at_ms: 1_000,
                },
            )));
            let completed = RolloutItem::EventMsg(EventMsg::ItemCompleted(ItemCompletedEvent {
                thread_id,
                turn_id: "original-turn".to_string(),
                item: TurnItem::DynamicToolCall(DynamicToolCallItem {
                    status,
                    content_items: Some(vec![DynamicToolCallOutputContentItem::InputText {
                        text: format!("exact original result: {status:?}"),
                    }]),
                    success: Some(success),
                    error,
                    duration: Some(Duration::from_millis(250)),
                    ..started
                }),
                started_at_ms: Some(1_000),
                completed_at_ms: 1_250,
            }));
            live_items.push(completed.clone());
            expected.push(completed);
        }

        // LiveThread applies this policy before the original recorder sees the batch.
        let persisted = persisted_rollout_items(&live_items, history_mode);
        let expected_value = serde_json::to_value(&expected)?;
        assert_eq!(serde_json::to_value(&persisted)?, expected_value);
        recorder.record_canonical_items(&persisted).await?;
        recorder.flush().await?;
        let path = recorder.rollout_path().to_path_buf();
        recorder.shutdown().await?;
        drop(recorder);

        let (restored, restored_thread_id, parse_errors) =
            RolloutRecorder::load_rollout_items(&path).await?;
        assert_eq!(restored_thread_id, Some(thread_id));
        assert_eq!(parse_errors, 0);
        assert_eq!(restored.len(), expected.len() + 1);
        let RolloutItem::SessionMeta(meta) = &restored[0] else {
            anyhow::bail!("original rollout did not preserve session metadata");
        };
        assert_eq!(
            (meta.meta.id, meta.meta.history_mode),
            (thread_id, history_mode)
        );
        assert_eq!(serde_json::to_value(&restored[1..])?, expected_value);
        // The legacy AppServer reader reapplies the same policy to stored items.
        let visible = persisted_rollout_items(&restored[1..], history_mode);
        assert_eq!(serde_json::to_value(&visible)?, expected_value);
    }
    Ok(())
}
