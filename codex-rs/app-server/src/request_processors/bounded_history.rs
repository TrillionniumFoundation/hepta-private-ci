use std::io::Write;

use super::thread_processor::paginated_history_list_error;
use super::thread_processor::stored_turn_to_api_turn;
use super::*;
use codex_app_server_protocol::HISTORY_READ_UNAVAILABLE_ERROR_CODE;

pub(super) fn unavailable(reason: &str) -> JSONRPCErrorError {
    JSONRPCErrorError {
        code: HISTORY_READ_UNAVAILABLE_ERROR_CODE,
        message: "complete bounded history is unavailable; retry without advancing recovery".into(),
        data: Some(serde_json::json!({"kind": "historyReadUnavailable", "reason": reason})),
    }
}

impl ThreadRequestProcessor {
    pub(super) async fn bounded_thread_turns_page(
        &self,
        thread_id: ThreadId,
        cursor: Option<String>,
        limit: Option<u32>,
        direction: Option<SortDirection>,
    ) -> Result<ThreadTurnsListResponse, JSONRPCErrorError> {
        let page = self
            .thread_store
            .list_full_turns_bounded(StoreListTurnsParams {
                thread_id,
                include_archived: true,
                cursor,
                page_size: limit.unwrap_or(100) as usize,
                sort_direction: match direction.unwrap_or(SortDirection::Desc) {
                    SortDirection::Asc => StoreSortDirection::Asc,
                    SortDirection::Desc => StoreSortDirection::Desc,
                },
                items_view: StoredTurnItemsView::NotLoaded,
            })
            .await
            .map_err(|error| match error {
                ThreadStoreError::HistoryReadUnavailable { reason } => unavailable(reason),
                error => paginated_history_list_error(error),
            })?;
        let data = page
            .turns
            .into_iter()
            .map(|(mut shell, items)| {
                shell.items = items;
                stored_turn_to_api_turn(shell, TurnItemsView::Full)
            })
            .collect::<Result<Vec<_>, _>>()?;
        let response = ThreadTurnsListResponse {
            data,
            next_cursor: page.next_cursor,
            backwards_cursor: page.backwards_cursor,
        };
        // Count the actual escaped wire representation without allocating another full response.
        serde_json::to_writer(ResponseBudget(4 * 1024 * 1024), &response)
            .map_err(|_| unavailable("responseBudgetExceeded"))?;
        Ok(response)
    }
}

struct ResponseBudget(usize);
impl Write for ResponseBudget {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        self.0 = self
            .0
            .checked_sub(bytes.len())
            .ok_or_else(|| std::io::Error::other("history response budget exceeded"))?;
        Ok(bytes.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

#[cfg(test)]
#[path = "bounded_history_budget_tests.rs"]
mod tests;
