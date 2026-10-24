//! Observe only already admitted turns; persisted history cannot admit work.

use std::collections::HashSet;

use codex_app_server_protocol::ThreadItem;
use codex_app_server_protocol::TurnItemsView;
use codex_app_server_protocol::TurnStatus;

use super::*;

impl<B: MatrixRuntimeBridge> MatrixRuntime<B> {
    pub(super) async fn recover_admitted_turn(
        &self,
        dispatch: InboxDispatchRecord,
        now_ms: u64,
        remaining_pages: &mut usize,
    ) -> Result<MatrixDispatchOutcome, MatrixRuntimeError> {
        if self
            .store
            .is_scope_quarantined(
                &dispatch.room_id,
                dispatch.binding_revision,
                dispatch.generation,
            )
            .await?
        {
            return Ok(MatrixDispatchOutcome::Quarantined {
                event_id: dispatch.event_id,
            });
        }
        if *remaining_pages == 0 {
            return Ok(MatrixDispatchOutcome::Admitted { dispatch });
        }
        let thread_id = dispatch.thread_id.as_deref().ok_or_else(|| {
            MatrixRuntimeError::Protocol("admitted Matrix dispatch has no thread".to_string())
        })?;
        let turn_id = dispatch.turn_id.as_deref().ok_or_else(|| {
            MatrixRuntimeError::Protocol("admitted Matrix dispatch has no turn".to_string())
        })?;
        let mut cursor = self.store.turn_recovery_cursor(&dispatch).await?;
        let mut seen_cursors = HashSet::new();
        if let Some(cursor) = &cursor {
            seen_cursors.insert(cursor.clone());
        }
        while *remaining_pages > 0 {
            *remaining_pages -= 1;
            let page = self
                .bridge
                .list_persisted_turns(thread_id, cursor.as_deref())
                .await?;
            if page.data.len() > crate::PERSISTED_TURN_PAGE_SIZE as usize {
                return Err(MatrixRuntimeError::Protocol(
                    "persisted Matrix turn page exceeded its requested bound".to_string(),
                ));
            }
            let mut matching = page.data.into_iter().filter(|turn| turn.id == turn_id);
            if let Some(turn) = matching.next() {
                if matching.next().is_some() {
                    return Err(MatrixRuntimeError::Protocol(
                        "persisted Matrix history repeated the exact turn identity".to_string(),
                    ));
                }
                if turn.status == TurnStatus::InProgress {
                    self.store
                        .advance_turn_recovery_cursor(
                            &dispatch,
                            cursor.as_deref(),
                            /*next*/ None,
                        )
                        .await?;
                    return Ok(MatrixDispatchOutcome::Admitted { dispatch });
                }
                let inbox = self
                    .store
                    .inbox(&dispatch.event_id)
                    .await?
                    .ok_or(MatrixRuntimeError::MissingInbox)?;
                let expected_input = supported_text_input(&inbox).ok_or_else(|| {
                    MatrixRuntimeError::Protocol(
                        "admitted Matrix turn no longer has its exact input".to_string(),
                    )
                })?;
                let mut exact_user_items = turn.items.iter().filter_map(|item| match item {
                    ThreadItem::UserMessage {
                        client_id: Some(client_id),
                        content,
                        ..
                    } if client_id == &dispatch.client_user_message_id => Some(content),
                    _ => None,
                });
                let exact_input = exact_user_items.next();
                if turn.items_view != TurnItemsView::Full
                    || exact_input.is_none()
                    || exact_user_items.next().is_some()
                    || crate::bridge_user_input_payload_sha256(
                        exact_input.expect("checked user item"),
                    )? != crate::bridge_user_input_payload_sha256(&expected_input)?
                {
                    return Err(MatrixRuntimeError::Protocol(
                        "persisted Matrix terminal turn lacks full exact client/input identity"
                            .to_string(),
                    ));
                }
                let mut item_ids = HashSet::new();
                for item in &turn.items {
                    if let ThreadItem::AgentMessage { id, .. } = item
                        && (id.is_empty() || !item_ids.insert(id))
                    {
                        return Err(MatrixRuntimeError::Protocol(
                            "persisted Matrix terminal turn has ambiguous agent item identities"
                                .to_string(),
                        ));
                    }
                }
                // Reset before projection. A crash after any final enqueue
                // replays the same durable ids and exact payload revisions.
                self.store
                    .advance_turn_recovery_cursor(&dispatch, cursor.as_deref(), /*next*/ None)
                    .await?;
                for item in turn.items {
                    if let ThreadItem::AgentMessage { id, text, .. } = item
                        && !text.is_empty()
                    {
                        self.enqueue_projection(
                            &dispatch,
                            &ProjectableEvent::Final {
                                thread_id: thread_id.to_string(),
                                turn_id: turn_id.to_string(),
                                item_id: id,
                                text,
                            },
                            now_ms,
                        )
                        .await?;
                    }
                }
                let status = match turn.status {
                    TurnStatus::Completed => "completed",
                    TurnStatus::Failed => "failed",
                    TurnStatus::Interrupted => "interrupted",
                    TurnStatus::InProgress => unreachable!("checked before terminal projection"),
                };
                self.enqueue_projection(
                    &dispatch,
                    &ProjectableEvent::Terminal {
                        thread_id: thread_id.to_string(),
                        turn_id: turn_id.to_string(),
                        status,
                    },
                    now_ms,
                )
                .await?;
                let admission = admission_from_dispatch(&dispatch, turn_id, now_ms)?;
                let completed = self
                    .store
                    .complete_inbox_dispatch(&admission, now_ms.max(dispatch.updated_at_ms))
                    .await?;
                return Ok(MatrixDispatchOutcome::Completed {
                    dispatch: completed,
                });
            }
            if let Some(next) = &page.next_cursor
                && !seen_cursors.insert(next.clone())
            {
                return Err(MatrixRuntimeError::Protocol(
                    "persisted Matrix turn history returned a repeated cursor".to_string(),
                ));
            }
            self.store
                .advance_turn_recovery_cursor(
                    &dispatch,
                    cursor.as_deref(),
                    page.next_cursor.as_deref(),
                )
                .await?;
            cursor = page.next_cursor;
            if cursor.is_none() {
                break;
            }
        }
        // Each page checkpoint survives restart, so turns older than one
        // bounded observation window remain reachable on the next poll.
        Ok(MatrixDispatchOutcome::Admitted { dispatch })
    }
}
