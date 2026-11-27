//! Item pages use the original store. Legacy rollouts share the existing turn
//! reconstruction and live overlay, without creating another history index.
use super::*;

#[derive(serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct LegacyItemCursor {
    thread_id: ThreadId,
    turn_id: String,
    item_id: String,
    include_anchor: bool,
}

impl ThreadRequestProcessor {
    pub(super) async fn thread_items_list_response_inner(
        &self,
        params: ThreadItemsListParams,
    ) -> Result<ThreadItemsListResponse, JSONRPCErrorError> {
        let thread_id = ThreadId::from_string(&params.thread_id)
            .map_err(|err| invalid_request(format!("invalid thread id: {err}")))?;
        match self
            .thread_store
            .read_thread(StoreReadThreadParams {
                thread_id,
                include_archived: true,
                include_history: false,
            })
            .await
        {
            Ok(thread) if thread.history_mode == ThreadHistoryMode::Paginated => {}
            Ok(_) => return self.legacy_thread_items_page(thread_id, params).await,
            Err(ThreadStoreError::ThreadNotFound { thread_id: missing })
                if missing == thread_id =>
            {
                return self.legacy_thread_items_page(thread_id, params).await;
            }
            Err(ThreadStoreError::InvalidRequest { message })
                if message == format!("no rollout found for thread id {thread_id}") =>
            {
                return self.legacy_thread_items_page(thread_id, params).await;
            }
            Err(error) => return Err(paginated_history_list_error(error)),
        }
        let page = self
            .thread_store
            .list_items(StoreListItemsParams {
                thread_id,
                turn_id: params.turn_id,
                include_archived: true,
                cursor: params.cursor,
                page_size: params
                    .limit
                    .map(|value| value as usize)
                    .unwrap_or(THREAD_ITEMS_DEFAULT_LIMIT)
                    .clamp(1, THREAD_ITEMS_MAX_LIMIT),
                sort_direction: match params.sort_direction.unwrap_or(SortDirection::Asc) {
                    SortDirection::Asc => StoreSortDirection::Asc,
                    SortDirection::Desc => StoreSortDirection::Desc,
                },
                sort_key: StoreItemSortKey::CreatedAtOrdinal,
                after_updated_at_ordinal: None,
            })
            .await
            .map_err(paginated_history_list_error)?;
        let data = page
            .items
            .into_iter()
            .map(|stored_item| {
                let turn_id = stored_item.turn_id.clone();
                let item = deserialize_stored_thread_item(stored_item)?;
                Ok(ThreadItemEntry { turn_id, item })
            })
            .collect::<Result<Vec<_>, JSONRPCErrorError>>()?;
        Ok(ThreadItemsListResponse {
            data,
            next_cursor: page.next_cursor,
            backwards_cursor: page.backwards_cursor,
        })
    }

    async fn legacy_thread_items_page(
        &self,
        thread_id: ThreadId,
        params: ThreadItemsListParams,
    ) -> Result<ThreadItemsListResponse, JSONRPCErrorError> {
        let items = self
            .load_thread_turns_list_history(thread_id)
            .await
            .map_err(thread_read_view_error)?;
        let loaded = self.thread_manager.get_thread(thread_id).await.ok();
        let running = match loaded.as_ref() {
            Some(thread) => matches!(thread.agent_status().await, AgentStatus::Running),
            None => false,
        };
        let active = if loaded.is_some() {
            let state = self.thread_state_manager.thread_state(thread_id).await;

            state.lock().await.active_turn_snapshot()
        } else {
            None
        };
        let turns = reconstruct_thread_turns_for_turns_list(
            &items,
            self.thread_watch_manager
                .loaded_status_for_thread(&thread_id.to_string())
                .await,
            running,
            active,
        );
        // Like legacy turn pages this replays the original rollout, including
        // rollback/compaction, but only the requested item page crosses RPC.
        let mut entries = turns
            .into_iter()
            .flat_map(|turn| {
                turn.items.into_iter().map(move |item| ThreadItemEntry {
                    turn_id: turn.id.clone(),
                    item,
                })
            })
            .enumerate()
            .collect::<Vec<_>>();
        let anchor: Option<LegacyItemCursor> = params
            .cursor
            .as_ref()
            .map(|cursor| {
                if cursor.len() > 2048 {
                    return Err(invalid_request("invalid item cursor"));
                }
                serde_json::from_str(cursor).map_err(|_| invalid_request("invalid item cursor"))
            })
            .transpose()?;
        if anchor
            .as_ref()
            .is_some_and(|anchor| anchor.thread_id != thread_id)
        {
            return Err(invalid_request("item cursor belongs to another thread"));
        }
        let anchor_index = anchor.as_ref().and_then(|anchor| {
            entries.iter().position(|(_, entry)| {
                entry.turn_id == anchor.turn_id && entry.item.id() == anchor.item_id
            })
        });
        if anchor.is_some() && anchor_index.is_none() {
            return Err(invalid_request(
                "invalid cursor: anchor item is no longer present",
            ));
        }
        let direction = params.sort_direction.unwrap_or(SortDirection::Asc);
        entries.retain(|(index, entry)| {
            params
                .turn_id
                .as_ref()
                .is_none_or(|turn| turn == &entry.turn_id)
                && match (anchor.as_ref(), anchor_index, direction) {
                    (Some(anchor), Some(position), SortDirection::Asc) => {
                        *index > position || (anchor.include_anchor && *index == position)
                    }
                    (Some(anchor), Some(position), SortDirection::Desc) => {
                        *index < position || (anchor.include_anchor && *index == position)
                    }
                    _ => true,
                }
        });
        if direction == SortDirection::Desc {
            entries.reverse();
        }
        let size = params
            .limit
            .map(|value| value as usize)
            .unwrap_or(THREAD_ITEMS_DEFAULT_LIMIT)
            .clamp(1, THREAD_ITEMS_MAX_LIMIT);
        let has_more = entries.len() > size;
        entries.truncate(size);
        let encode = |entry: &ThreadItemEntry, include_anchor| {
            serde_json::to_string(&LegacyItemCursor {
                thread_id,
                turn_id: entry.turn_id.clone(),
                item_id: entry.item.id().to_string(),
                include_anchor,
            })
            .map_err(|err| internal_error(format!("failed to serialize item cursor: {err}")))
        };
        let backwards_cursor = entries
            .first()
            .map(|(_, entry)| encode(entry, true))
            .transpose()?;
        let next_cursor = if has_more {
            entries
                .last()
                .map(|(_, entry)| encode(entry, false))
                .transpose()?
        } else {
            None
        };
        Ok(ThreadItemsListResponse {
            data: entries.into_iter().map(|(_, entry)| entry).collect(),
            next_cursor,
            backwards_cursor,
        })
    }
}
