//! The legacy path is exercised through the original public JSON-RPC owner.
use super::*;

#[tokio::test]
async fn thread_items_list_legacy_pages_original_items_and_rejects_removed_anchor() -> Result<()> {
    let server = create_mock_responses_server_repeating_assistant("Done").await;
    let home = TempDir::new()?;
    MockResponsesConfig::new(&server.uri()).write(home.path())?;
    let timestamp = "2025-01-05T12-00-00";
    let thread = create_fake_rollout_with_text_elements(
        home.path(),
        timestamp,
        "2025-01-05T12:00:00Z",
        "first",
        vec![],
        Some("mock_provider"),
        None,
    )?;
    let path = rollout_path(home.path(), timestamp, &thread);
    append_user_message(&path, "2025-01-05T12:01:00Z", "second")?;
    append_user_message(&path, "2025-01-05T12:02:00Z", "third")?;
    let mut client = TestAppServer::builder()
        .with_codex_home(home.path())
        .without_auto_env()
        .build_initialized()
        .await?;
    let thread_id = codex_protocol::ThreadId::from_string(&thread)?;
    let original = read_turns_page(
        &mut client,
        thread_id,
        None,
        Some(10),
        SortDirection::Asc,
        Some(TurnItemsView::Full),
    )
    .await?;
    let expected = original
        .data
        .into_iter()
        .flat_map(|turn| {
            turn.items
                .into_iter()
                .map(move |item| codex_app_server_protocol::ThreadItemEntry {
                    turn_id: turn.id.clone(),
                    item,
                })
        })
        .collect::<Vec<_>>();
    assert_eq!(expected.len(), 3);
    let first = read_items_page(
        &mut client,
        thread_id,
        None,
        None,
        Some(1),
        SortDirection::Asc,
    )
    .await?;
    assert_eq!(first.data, expected[..1]);
    // The same thread-wide cursor is valid with a different turn filter.
    let second = read_items_page(
        &mut client,
        thread_id,
        Some(&expected[1].turn_id),
        first.next_cursor,
        Some(1),
        SortDirection::Asc,
    )
    .await?;
    assert_eq!(second.data, expected[1..2]);
    let newest = read_items_page(
        &mut client,
        thread_id,
        None,
        None,
        Some(1),
        SortDirection::Desc,
    )
    .await?;
    assert_eq!(newest.data, expected[2..]);
    let forward = read_items_page(
        &mut client,
        thread_id,
        None,
        newest.backwards_cursor.clone(),
        Some(10),
        SortDirection::Asc,
    )
    .await?;
    assert_eq!(forward.data, expected[2..]);
    append_thread_rollback(&path, "2025-01-05T12:03:00Z", 1)?;
    let id = client
        .send_thread_items_list_request(ThreadItemsListParams {
            thread_id: thread,
            turn_id: None,
            cursor: newest.backwards_cursor,
            limit: Some(1),
            sort_direction: None,
        })
        .await?;
    let error = timeout(
        DEFAULT_READ_TIMEOUT,
        client.read_stream_until_error_message(RequestId::Integer(id)),
    )
    .await??;
    assert_eq!(
        error.error.message,
        "invalid cursor: anchor item is no longer present"
    );
    Ok(())
}

#[tokio::test]
async fn thread_items_list_legacy_rejects_other_thread_cursor() -> Result<()> {
    let server = create_mock_responses_server_repeating_assistant("Done").await;
    let home = TempDir::new()?;
    MockResponsesConfig::new(&server.uri()).write(home.path())?;
    let first = create_fake_rollout_with_text_elements(
        home.path(),
        "2025-01-05T12-00-00",
        "2025-01-05T12:00:00Z",
        "one",
        vec![],
        Some("mock_provider"),
        None,
    )?;
    let other = create_fake_rollout_with_text_elements(
        home.path(),
        "2025-01-06T12-00-00",
        "2025-01-06T12:00:00Z",
        "two",
        vec![],
        Some("mock_provider"),
        None,
    )?;
    let mut client = TestAppServer::builder()
        .with_codex_home(home.path())
        .without_auto_env()
        .build_initialized()
        .await?;
    let page = read_items_page(
        &mut client,
        codex_protocol::ThreadId::from_string(&first)?,
        None,
        None,
        Some(1),
        SortDirection::Asc,
    )
    .await?;
    let id = client
        .send_thread_items_list_request(ThreadItemsListParams {
            thread_id: other,
            turn_id: None,
            cursor: page.backwards_cursor,
            limit: Some(1),
            sort_direction: None,
        })
        .await?;
    let error = timeout(
        DEFAULT_READ_TIMEOUT,
        client.read_stream_until_error_message(RequestId::Integer(id)),
    )
    .await??;
    assert_eq!(error.error.message, "item cursor belongs to another thread");
    Ok(())
}
