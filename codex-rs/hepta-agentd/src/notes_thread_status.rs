//! Bounded read-only navigation of original Core items, never model history.
use std::collections::HashSet;
use std::future::Future;

use codex_app_server_protocol::SortDirection;
use codex_app_server_protocol::ThreadItemsListParams;
use codex_app_server_protocol::ThreadItemsListResponse;
use codex_app_server_protocol::ThreadTurnsListParams;
use codex_app_server_protocol::ThreadTurnsListResponse;
use codex_app_server_protocol::TurnItemsView;

use super::*;

#[derive(Deserialize)]
#[serde(untagged)]
pub(super) enum StatusArguments {
    Exact(ExactStatusArguments),
    Selected(SelectedStatusArguments),
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ExactStatusArguments {
    pub turn_id: String,
    pub call_id: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct SelectedStatusArguments {
    pub selector: StatusSelector,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct StatusSelector {
    pub kind: StatusSelectorKind,
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum StatusSelectorKind {
    LatestOriginalReplace,
}

impl StatusArguments {
    pub(super) fn validate(&self) -> Result<(), AgentdError> {
        if let Self::Exact(exact) = self
            && (exact.turn_id.is_empty()
                || exact.turn_id.len() > 128
                || exact.call_id.is_empty()
                || exact.call_id.len() > 128)
        {
            return Err(invalid("original Notes status navigation bound"));
        }
        Ok(())
    }
}

/// Only original Core read APIs are available to this navigator. Production
/// implements them on the same seed-verified connection that owns the callback.
pub(super) trait OriginalStatusHistory {
    fn turns(
        &mut self,
        params: ThreadTurnsListParams,
    ) -> impl Future<Output = Result<ThreadTurnsListResponse, AgentdError>> + Send;

    fn items(
        &mut self,
        params: ThreadItemsListParams,
    ) -> impl Future<Output = Result<ThreadItemsListResponse, AgentdError>> + Send;
}

#[derive(Debug, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum StatusUnknownReason {
    WindowExhausted,
    OriginalReplaceNotObserved,
    DeadlineElapsed,
}

pub(super) enum StatusDiscovery {
    Found(VerifiedNotesThreadOperation),
    Unknown(StatusUnknownReason),
}

pub(super) async fn discover_latest_original_replace(
    route: &AgentdTextSessionConfig,
    history: &mut impl OriginalStatusHistory,
) -> Result<StatusDiscovery, AgentdError> {
    const TURNS: usize = 16;
    const PAGE_ITEMS: usize = 64;
    const TURN_PAGES: usize = 4;
    const TOTAL_ITEMS: usize = 1024;
    const RPCS: usize = 64;
    let end = tokio::time::Instant::now() + Duration::from_secs(5);
    let turns = tokio::time::timeout_at(
        end,
        history.turns(ThreadTurnsListParams {
            thread_id: route.thread_id.clone(),
            cursor: None,
            limit: Some(TURNS as u32),
            sort_direction: Some(SortDirection::Desc),
            items_view: Some(TurnItemsView::NotLoaded),
        }),
    )
    .await;
    let Ok(turns) = turns else {
        return Ok(StatusDiscovery::Unknown(
            StatusUnknownReason::DeadlineElapsed,
        ));
    };
    let turns = turns?;
    let mut seen_turns = HashSet::new();
    if turns.data.len() > TURNS
        || turns.data.iter().any(|turn| {
            turn.id.is_empty()
                || turn.id.len() > 128
                || !seen_turns.insert(turn.id.clone())
                || turn.items_view != TurnItemsView::NotLoaded
                || !turn.items.is_empty()
        })
    {
        return Err(invalid("original Notes discovery turn page mismatch"));
    }
    let mut rpc_count = 1;
    let mut item_count = 0;
    for turn in turns.data {
        let mut cursor = None;
        let mut seen_cursors = HashSet::new();
        for _ in 0..TURN_PAGES {
            if rpc_count >= RPCS || item_count >= TOTAL_ITEMS {
                return Ok(StatusDiscovery::Unknown(
                    StatusUnknownReason::WindowExhausted,
                ));
            }
            rpc_count += 1;
            let page = tokio::time::timeout_at(
                end,
                history.items(ThreadItemsListParams {
                    thread_id: route.thread_id.clone(),
                    turn_id: Some(turn.id.clone()),
                    cursor,
                    limit: Some(PAGE_ITEMS as u32),
                    sort_direction: Some(SortDirection::Asc),
                }),
            )
            .await;
            let Ok(page) = page else {
                return Ok(StatusDiscovery::Unknown(
                    StatusUnknownReason::DeadlineElapsed,
                ));
            };
            let page = page?;
            item_count += page.data.len();
            if page.data.len() > PAGE_ITEMS
                || item_count > TOTAL_ITEMS
                || page.data.iter().any(|entry| entry.turn_id != turn.id)
            {
                return Err(invalid("original Notes discovery item page mismatch"));
            }
            for entry in page.data {
                if let codex_app_server_protocol::ThreadItem::DynamicToolCall {
                    id,
                    namespace,
                    tool,
                    ..
                } = &entry.item
                    && namespace.is_none()
                    && tool == REPLACE_TOOL
                {
                    // Ascending original items designate the FIRST write of
                    // the latest matching turn, including a lost tool reply.
                    return Ok(StatusDiscovery::Found(
                        VerifiedNotesThreadOperation::from_original_item(
                            route,
                            &turn.id,
                            id,
                            &entry.item,
                        )?,
                    ));
                }
            }
            cursor = page.next_cursor;
            let Some(next) = &cursor else { break };
            if next.is_empty() || next.len() > 2048 || !seen_cursors.insert(next.clone()) {
                return Err(invalid("original Notes discovery cursor mismatch"));
            }
        }
        // An incomplete newer turn must never be skipped in favor of an older
        // write: its first original replace may lie beyond this hard window.
        if cursor.is_some() {
            return Ok(StatusDiscovery::Unknown(
                StatusUnknownReason::WindowExhausted,
            ));
        }
    }
    Ok(StatusDiscovery::Unknown(if turns.next_cursor.is_some() {
        StatusUnknownReason::WindowExhausted
    } else {
        StatusUnknownReason::OriginalReplaceNotObserved
    }))
}

#[cfg(test)]
#[path = "notes_thread_status_tests.rs"]
mod tests;
