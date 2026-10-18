//! Persisted pages remain authoritative. Live inserts require complete active-
//! turn membership proof and free capacity; no cache entry can evict a row.
use super::*;
impl AgentChatSession {
    pub(super) async fn timeline(
        &self,
        thread_id: String,
        cursor: Option<String>,
        limit: u32,
    ) -> Result<ChatResult> {
        self.scoped_thread(&thread_id).await?;
        let latest_page = cursor.is_none();
        let latest: ThreadTurnsListResponse = self
            .transport
            .request(ClientRequest::ThreadTurnsList {
                request_id: self.transport.request_id(),
                params: ThreadTurnsListParams {
                    thread_id: thread_id.clone(),
                    cursor: None,
                    limit: Some(1),
                    sort_direction: Some(SortDirection::Desc),
                    items_view: Some(TurnItemsView::NotLoaded),
                },
            })
            .await?;
        let active_turn_id = latest
            .data
            .into_iter()
            .next()
            .filter(|turn| turn.status == TurnStatus::InProgress)
            .map(|turn| turn.id);
        // Reserve one slot without ever removing a row returned by the store.
        // Cursors retain the exact page boundary of this bounded read.
        let page_limit = if latest_page && active_turn_id.is_some() {
            limit.saturating_sub(1).max(1)
        } else {
            limit
        };
        let response: ThreadItemsListResponse = self
            .transport
            .request(ClientRequest::ThreadItemsList {
                request_id: self.transport.request_id(),
                params: ThreadItemsListParams {
                    thread_id: thread_id.clone(),
                    turn_id: None,
                    cursor,
                    limit: Some(page_limit),
                    sort_direction: Some(SortDirection::Desc),
                },
            })
            .await?;
        if response.data.len() > page_limit as usize {
            return Err(invalid("oversized persisted timeline page"));
        }
        let mut data: Vec<_> = response.data.into_iter().filter_map(message).collect();
        data.reverse();
        if latest_page && let Some(active) = active_turn_id.as_deref() {
            let persisted: ThreadItemsListResponse = self
                .transport
                .request(ClientRequest::ThreadItemsList {
                    request_id: self.transport.request_id(),
                    params: ThreadItemsListParams {
                        thread_id: thread_id.clone(),
                        turn_id: Some(active.into()),
                        cursor: None,
                        limit: Some(MAX_CHAT_PAGE),
                        sort_direction: Some(SortDirection::Desc),
                    },
                })
                .await?;
            let window = live::ActiveItemWindow::from_response(persisted, active);
            self.live
                .lock()
                .map_err(|_| invalid("chat observations unavailable"))?
                .merge(&thread_id, &mut data, limit, active, &window);
        }
        Ok(ChatResult::Timeline {
            thread_id,
            data,
            next_cursor: response.next_cursor,
            active_turn_id,
        })
    }
}
