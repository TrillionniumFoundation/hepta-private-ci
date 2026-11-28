//! Bounded navigation on the same original Core connection. Selection is only
//! a lookup constraint; the selected user item still needs the full human proof.
use codex_app_server_protocol::SortDirection;
use codex_app_server_protocol::ThreadItem;
use codex_app_server_protocol::ThreadItemsListParams;
use codex_hepta_types::Digest32;

use super::*;

#[derive(Clone, Copy)]
pub(super) enum OriginalHumanInput {
    First,
    ExactDelivery(Digest32),
}

#[derive(Clone, Copy)]
pub(super) enum OriginalItemSelection<'a> {
    Call(&'a str),
    FirstReplace,
    UserInput(OriginalHumanInput),
}

pub(super) async fn find_original_item(
    thread_id: &str,
    original_turn_id: &str,
    selection: OriginalItemSelection<'_>,
    history: &mut impl status::OriginalStatusHistory,
) -> Result<ThreadItem, AgentdError> {
    let end = tokio::time::Instant::now() + Duration::from_secs(5);
    let mut cursor = None;
    for _ in 0..16 {
        let page = tokio::time::timeout_at(
            end,
            history.items(ThreadItemsListParams {
                thread_id: thread_id.into(),
                turn_id: Some(original_turn_id.into()),
                cursor,
                limit: Some(128),
                sort_direction: Some(SortDirection::Asc),
            }),
        )
        .await
        .map_err(|_| invalid("original callback preview deadline elapsed"))??;
        if page.data.len() > 128
            || page
                .data
                .iter()
                .any(|item| item.turn_id != original_turn_id)
        {
            return Err(invalid("original callback page escaped its turn"));
        }
        for entry in page.data {
            let selected = match selection {
                OriginalItemSelection::UserInput(human) => {
                    if let ThreadItem::UserMessage { client_id, .. } = &entry.item {
                        match human {
                            OriginalHumanInput::First => true,
                            OriginalHumanInput::ExactDelivery(delivery) => {
                                client_id.as_deref()
                                    == Some(format!("hepta.authbus:{delivery}").as_str())
                            }
                        }
                    } else {
                        false
                    }
                }
                OriginalItemSelection::Call(call_id) => {
                    matches!(&entry.item, ThreadItem::DynamicToolCall { id, .. } if id == call_id)
                }
                OriginalItemSelection::FirstReplace => {
                    matches!(&entry.item, ThreadItem::DynamicToolCall { namespace, tool, .. } if namespace.is_none() && tool == REPLACE_TOOL)
                }
            };
            if selected {
                return Ok(entry.item);
            }
        }
        cursor = page.next_cursor;
        if cursor.is_none() {
            break;
        }
    }
    Err(invalid(
        "original Core item is absent; no Notes operation prepared",
    ))
}

#[cfg(test)]
#[path = "notes_thread_items_tests.rs"]
mod tests;
