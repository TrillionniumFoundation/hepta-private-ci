//! Bounded pages from the original App Server, with no UI-owned transcript.
use super::*;

#[derive(Clone, Debug, Serialize)]
pub struct TextHistorySnapshot {
    pub turns: Vec<Turn>,
    pub earlier_cursor: Option<String>,
    /// Presentation limitation only; never an admission or terminal proof.
    pub notice: Option<String>,
}

impl AgentdTextRequests {
    /// Fetch one existing-thread page. The cursor is kept only by this client;
    /// it cannot select another owner, thread, or original session.
    pub async fn history_page(
        &self,
        cursor: Option<String>,
    ) -> Result<TextHistorySnapshot, TextSessionError> {
        if cursor
            .as_ref()
            .is_some_and(|value| value.len() > 2048 || value.is_empty())
        {
            return Err(TextSessionError::Identity);
        }
        let latest = cursor.is_none();
        let (page, notice) = self.display_page(cursor).await?;
        let mut state = self.shared.current()?;
        if latest {
            state.snapshot_turns.retain(|_, terminal| !*terminal);
            for turn in &page.data {
                observe_snapshot(&mut state, turn)?;
            }
        }
        let mut turns = page.data;
        turns.reverse();
        Ok(TextHistorySnapshot {
            turns,
            earlier_cursor: page.next_cursor,
            notice,
        })
    }

    pub(super) fn has_snapshot_activity(&self) -> Result<bool, TextSessionError> {
        Ok(self
            .shared
            .current()?
            .snapshot_turns
            .values()
            .any(|terminal| !terminal))
    }

    /// Only turns already projected from snapshots are refreshed. Live turns
    /// continue using their original notification stream until a full snapshot
    /// is explicitly needed, avoiding overlap without inventing replay cursors.
    pub(super) async fn refresh_snapshot_activity(
        &self,
    ) -> Result<TextHistorySnapshot, TextSessionError> {
        let (page, notice) = self.display_page(None).await?;
        let mut state = self.shared.current()?;
        let mut turns = page
            .data
            .into_iter()
            .filter(|turn| state.snapshot_turns.get(&turn.id) == Some(&false))
            .collect::<Vec<_>>();
        for turn in &turns {
            observe_snapshot(&mut state, turn)?;
        }
        turns.reverse();
        Ok(TextHistorySnapshot {
            turns,
            earlier_cursor: page.next_cursor,
            notice,
        })
    }

    async fn display_page(
        &self,
        cursor: Option<String>,
    ) -> Result<(ThreadTurnsListResponse, Option<String>), TextSessionError> {
        // Re-page the SAME original cursor, reducing the turn count before
        // falling back to original metadata for one individually large turn.
        // Its next cursor remains navigable and no identity/outcome is lost.
        let mut limit = 16;
        let mut view = TurnItemsView::Full;
        loop {
            let page: ThreadTurnsListResponse = self
                .call(ClientRequest::ThreadTurnsList {
                    request_id: self.id(),
                    params: ThreadTurnsListParams {
                        thread_id: self.shared.config.thread_id.clone(),
                        cursor: cursor.clone(),
                        limit: Some(limit),
                        sort_direction: Some(SortDirection::Desc),
                        items_view: Some(view),
                    },
                })
                .await?;
            if page.data.len() > limit as usize
                || page
                    .data
                    .iter()
                    .any(|turn| turn.id.is_empty() || turn.items_view != view)
                || page
                    .next_cursor
                    .as_ref()
                    .is_some_and(|value| value.is_empty() || value.len() > 2048)
            {
                return Err(TextSessionError::Identity);
            }
            let bounded = serde_json::to_vec(&page).map_err(unavailable)?.len()
                <= MAX_OBSERVATION_BYTES
                && page.data.iter().map(|turn| turn.items.len()).sum::<usize>() <= 256
                && page.data.iter().all(|turn| turn.items.len() <= 128)
                && page.data.iter().flat_map(|turn| &turn.items).all(|item| {
                    serde_json::to_vec(item).is_ok_and(|bytes| bytes.len() <= 32 * 1024)
                });
            if bounded {
                let notice = (view == TurnItemsView::NotLoaded).then(|| "This original turn exceeds the native preview bound. Its content remains in the original App Server; Earlier messages can continue past it and sending remains available.".into());
                return Ok((page, notice));
            }
            if view == TurnItemsView::NotLoaded {
                return Err(TextSessionError::Capacity);
            }
            if limit > 1 {
                limit /= 2;
            } else {
                view = TurnItemsView::NotLoaded;
            }
        }
    }
}

fn observe_snapshot(state: &mut State, turn: &Turn) -> Result<(), TextSessionError> {
    for item in &turn.items {
        if let ThreadItem::UserMessage {
            client_id: Some(client),
            content,
            ..
        } = item
            && let Some(pending) = state
                .pending
                .values_mut()
                .find(|pending| &pending.client_id == client)
        {
            if content != &pending.input
                || pending.turn_id.as_ref().is_some_and(|id| id != &turn.id)
            {
                state.fenced = true;
                return Err(TextSessionError::Identity);
            }
            pending.turn_id = Some(turn.id.clone());
            pending.recovered = true;
            pending.terminal = turn.status != TurnStatus::InProgress;
        }
    }
    if state.snapshot_turns.len() >= 64 {
        state.snapshot_turns.retain(|_, terminal| !*terminal);
    }
    state
        .snapshot_turns
        .insert(turn.id.clone(), turn.status != TurnStatus::InProgress);
    Ok(())
}
