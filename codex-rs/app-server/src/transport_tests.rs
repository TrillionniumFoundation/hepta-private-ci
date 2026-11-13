use super::*;
use crate::message_processor::InitializedConnectionSessionState;
use crate::outgoing_message::ConnectionRequestId;
use crate::outgoing_message::OutgoingMessageSender;
use codex_app_server_protocol::ConfigWarningNotification;
use codex_app_server_protocol::InitializeResponse;
use codex_app_server_protocol::RemoteControlConnectionStatus;
use codex_app_server_protocol::RemoteControlStatusChangedNotification;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ServerNotification;
use codex_app_server_protocol::ServerNotificationEnvelope;
use codex_app_server_protocol::ThreadRealtimeStartedNotification;
use codex_protocol::protocol::RealtimeConversationVersion;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use serde_json::json;
use tokio::time::Duration;
use tokio::time::timeout;

fn absolute_path(path: &str) -> AbsolutePathBuf {
    AbsolutePathBuf::from_absolute_path(path).expect("absolute path")
}

fn thread_realtime_started_notification() -> ServerNotification {
    ServerNotification::ThreadRealtimeStarted(ThreadRealtimeStartedNotification {
        thread_id: "thread-1".to_string(),
        realtime_session_id: None,
        version: RealtimeConversationVersion::V1,
    })
}

fn app_server_notification(notification: ServerNotification) -> OutgoingMessage {
    OutgoingMessage::AppServerNotification(ServerNotificationEnvelope {
        notification,
        emitted_at_ms: Some(1_234),
    })
}

#[tokio::test]
async fn to_connection_notification_respects_opt_out_filters() {
    let connection_id = ConnectionId(7);
    let (writer_tx, mut writer_rx) = mpsc::channel(1);
    let initialized = Arc::new(AtomicBool::new(true));
    let opted_out_notification_methods =
        Arc::new(RwLock::new(HashSet::from(["configWarning".to_string()])));

    let mut connections = HashMap::new();
    connections.insert(
        connection_id,
        OutboundConnectionState::new(
            writer_tx,
            initialized,
            Arc::new(AtomicBool::new(true)),
            opted_out_notification_methods,
            /*disconnect_sender*/ None,
        ),
    );

    route_outgoing_envelope(
        &mut connections,
        OutgoingEnvelope::ToConnection {
            connection_id,
            message: app_server_notification(ServerNotification::ConfigWarning(
                ConfigWarningNotification {
                    summary: "task_started".to_string(),
                    details: None,
                    path: None,
                    range: None,
                },
            )),
            write_complete_tx: None,
        },
    )
    .await;

    assert!(
        writer_rx.try_recv().is_err(),
        "opted-out notification should be dropped"
    );
}

#[tokio::test]
async fn to_connection_notifications_are_dropped_for_opted_out_clients() {
    let connection_id = ConnectionId(10);
    let (writer_tx, mut writer_rx) = mpsc::channel(1);

    let mut connections = HashMap::new();
    connections.insert(
        connection_id,
        OutboundConnectionState::new(
            writer_tx,
            Arc::new(AtomicBool::new(true)),
            Arc::new(AtomicBool::new(true)),
            Arc::new(RwLock::new(HashSet::from(["configWarning".to_string()]))),
            /*disconnect_sender*/ None,
        ),
    );

    route_outgoing_envelope(
        &mut connections,
        OutgoingEnvelope::ToConnection {
            connection_id,
            message: app_server_notification(ServerNotification::ConfigWarning(
                ConfigWarningNotification {
                    summary: "task_started".to_string(),
                    details: None,
                    path: None,
                    range: None,
                },
            )),
            write_complete_tx: None,
        },
    )
    .await;

    assert!(
        writer_rx.try_recv().is_err(),
        "opted-out notifications should not reach clients"
    );
}

#[tokio::test]
async fn to_connection_notifications_are_preserved_for_non_opted_out_clients() {
    let connection_id = ConnectionId(11);
    let (writer_tx, mut writer_rx) = mpsc::channel(1);

    let mut connections = HashMap::new();
    connections.insert(
        connection_id,
        OutboundConnectionState::new(
            writer_tx,
            Arc::new(AtomicBool::new(true)),
            Arc::new(AtomicBool::new(true)),
            Arc::new(RwLock::new(HashSet::new())),
            /*disconnect_sender*/ None,
        ),
    );

    route_outgoing_envelope(
        &mut connections,
        OutgoingEnvelope::ToConnection {
            connection_id,
            message: app_server_notification(ServerNotification::ConfigWarning(
                ConfigWarningNotification {
                    summary: "task_started".to_string(),
                    details: None,
                    path: None,
                    range: None,
                },
            )),
            write_complete_tx: None,
        },
    )
    .await;

    let message = writer_rx
        .recv()
        .await
        .expect("notification should reach non-opted-out clients");
    assert!(matches!(
        message.message,
        OutgoingMessage::AppServerNotification(ServerNotificationEnvelope {
            notification: ServerNotification::ConfigWarning(ConfigWarningNotification { summary, .. }),
            ..
        }) if summary == "task_started"
    ));
}

#[tokio::test]
async fn experimental_notifications_are_dropped_without_capability() {
    let connection_id = ConnectionId(12);
    let (writer_tx, mut writer_rx) = mpsc::channel(1);

    let mut connections = HashMap::new();
    connections.insert(
        connection_id,
        OutboundConnectionState::new(
            writer_tx,
            Arc::new(AtomicBool::new(true)),
            Arc::new(AtomicBool::new(false)),
            Arc::new(RwLock::new(HashSet::new())),
            /*disconnect_sender*/ None,
        ),
    );

    route_outgoing_envelope(
        &mut connections,
        OutgoingEnvelope::ToConnection {
            connection_id,
            message: app_server_notification(thread_realtime_started_notification()),
            write_complete_tx: None,
        },
    )
    .await;

    assert!(
        writer_rx.try_recv().is_err(),
        "experimental notifications should not reach clients without capability"
    );
}

#[tokio::test]
async fn experimental_notifications_are_preserved_with_capability() {
    let connection_id = ConnectionId(13);
    let (writer_tx, mut writer_rx) = mpsc::channel(1);

    let mut connections = HashMap::new();
    connections.insert(
        connection_id,
        OutboundConnectionState::new(
            writer_tx,
            Arc::new(AtomicBool::new(true)),
            Arc::new(AtomicBool::new(true)),
            Arc::new(RwLock::new(HashSet::new())),
            /*disconnect_sender*/ None,
        ),
    );

    route_outgoing_envelope(
        &mut connections,
        OutgoingEnvelope::ToConnection {
            connection_id,
            message: app_server_notification(thread_realtime_started_notification()),
            write_complete_tx: None,
        },
    )
    .await;

    let message = writer_rx
        .recv()
        .await
        .expect("experimental notification should reach opted-in client");
    assert!(matches!(
        message.message,
        OutgoingMessage::AppServerNotification(ServerNotificationEnvelope {
            notification: ServerNotification::ThreadRealtimeStarted(_),
            ..
        })
    ));
}

#[tokio::test]
async fn command_execution_request_approval_strips_additional_permissions_without_capability() {
    let connection_id = ConnectionId(8);
    let (writer_tx, mut writer_rx) = mpsc::channel(1);

    let mut connections = HashMap::new();
    connections.insert(
        connection_id,
        OutboundConnectionState::new(
            writer_tx,
            Arc::new(AtomicBool::new(true)),
            Arc::new(AtomicBool::new(false)),
            Arc::new(RwLock::new(HashSet::new())),
            /*disconnect_sender*/ None,
        ),
    );

    route_outgoing_envelope(
        &mut connections,
        OutgoingEnvelope::ToConnection {
            connection_id,
            message: OutgoingMessage::Request(ServerRequest::CommandExecutionRequestApproval {
                request_id: RequestId::Integer(1),
                params: codex_app_server_protocol::CommandExecutionRequestApprovalParams {
                    thread_id: "thr_123".to_string(),
                    turn_id: "turn_123".to_string(),
                    item_id: "call_123".to_string(),
                    started_at_ms: 0,
                    approval_id: None,
                    environment_id: None,
                    reason: Some("Need extra read access".to_string()),
                    network_approval_context: None,
                    command: Some("cat file".to_string()),
                    cwd: Some(absolute_path("/tmp").into()),
                    command_actions: None,
                    additional_permissions: Some(
                        codex_app_server_protocol::AdditionalPermissionProfile {
                            network: None,
                            file_system: Some(
                                codex_app_server_protocol::AdditionalFileSystemPermissions {
                                    read: Some(vec![absolute_path("/tmp/allowed").into()]),
                                    write: None,
                                    glob_scan_max_depth: None,
                                    entries: None,
                                },
                            ),
                        },
                    ),
                    proposed_execpolicy_amendment: None,
                    proposed_network_policy_amendments: None,
                    available_decisions: None,
                },
            }),
            write_complete_tx: None,
        },
    )
    .await;

    let message = writer_rx
        .recv()
        .await
        .expect("request should be delivered to the connection");
    let json = serde_json::to_value(message.message).expect("request should serialize");
    assert_eq!(json["params"].get("additionalPermissions"), None);
}

#[tokio::test]
async fn command_execution_request_approval_keeps_additional_permissions_with_capability() {
    let connection_id = ConnectionId(9);
    let (writer_tx, mut writer_rx) = mpsc::channel(1);

    let mut connections = HashMap::new();
    connections.insert(
        connection_id,
        OutboundConnectionState::new(
            writer_tx,
            Arc::new(AtomicBool::new(true)),
            Arc::new(AtomicBool::new(true)),
            Arc::new(RwLock::new(HashSet::new())),
            /*disconnect_sender*/ None,
        ),
    );

    route_outgoing_envelope(
        &mut connections,
        OutgoingEnvelope::ToConnection {
            connection_id,
            message: OutgoingMessage::Request(ServerRequest::CommandExecutionRequestApproval {
                request_id: RequestId::Integer(1),
                params: codex_app_server_protocol::CommandExecutionRequestApprovalParams {
                    thread_id: "thr_123".to_string(),
                    turn_id: "turn_123".to_string(),
                    item_id: "call_123".to_string(),
                    started_at_ms: 0,
                    approval_id: None,
                    environment_id: None,
                    reason: Some("Need extra read access".to_string()),
                    network_approval_context: None,
                    command: Some("cat file".to_string()),
                    cwd: Some(absolute_path("/tmp").into()),
                    command_actions: None,
                    additional_permissions: Some(
                        codex_app_server_protocol::AdditionalPermissionProfile {
                            network: None,
                            file_system: Some(
                                codex_app_server_protocol::AdditionalFileSystemPermissions {
                                    read: Some(vec![absolute_path("/tmp/allowed").into()]),
                                    write: None,
                                    glob_scan_max_depth: None,
                                    entries: None,
                                },
                            ),
                        },
                    ),
                    proposed_execpolicy_amendment: None,
                    proposed_network_policy_amendments: None,
                    available_decisions: None,
                },
            }),
            write_complete_tx: None,
        },
    )
    .await;

    let message = writer_rx
        .recv()
        .await
        .expect("request should be delivered to the connection");
    let json = serde_json::to_value(message.message).expect("request should serialize");
    let allowed_path = absolute_path("/tmp/allowed").to_string_lossy().into_owned();
    assert_eq!(
        json["params"]["additionalPermissions"],
        json!({
            "network": null,
            "fileSystem": {
                "read": [allowed_path],
            "write": null,
            },
        })
    );
}

#[tokio::test]
async fn broadcast_does_not_block_on_slow_connection() {
    let fast_connection_id = ConnectionId(1);
    let slow_connection_id = ConnectionId(2);

    let (fast_writer_tx, mut fast_writer_rx) = mpsc::channel(1);
    let (slow_writer_tx, mut slow_writer_rx) = mpsc::channel(1);
    let fast_disconnect_token = CancellationToken::new();
    let slow_disconnect_token = CancellationToken::new();

    let mut connections = HashMap::new();
    connections.insert(
        fast_connection_id,
        OutboundConnectionState::new(
            fast_writer_tx,
            Arc::new(AtomicBool::new(true)),
            Arc::new(AtomicBool::new(true)),
            Arc::new(RwLock::new(HashSet::new())),
            Some(fast_disconnect_token.clone()),
        ),
    );
    connections.insert(
        slow_connection_id,
        OutboundConnectionState::new(
            slow_writer_tx.clone(),
            Arc::new(AtomicBool::new(true)),
            Arc::new(AtomicBool::new(true)),
            Arc::new(RwLock::new(HashSet::new())),
            Some(slow_disconnect_token.clone()),
        ),
    );

    let queued_message = app_server_notification(ServerNotification::ConfigWarning(
        ConfigWarningNotification {
            summary: "already-buffered".to_string(),
            details: None,
            path: None,
            range: None,
        },
    ));
    slow_writer_tx
        .try_send(QueuedOutgoingMessage::new(queued_message))
        .expect("channel should have room");

    let broadcast_message = app_server_notification(ServerNotification::ConfigWarning(
        ConfigWarningNotification {
            summary: "test".to_string(),
            details: None,
            path: None,
            range: None,
        },
    ));
    timeout(
        Duration::from_millis(100),
        route_outgoing_envelope(
            &mut connections,
            OutgoingEnvelope::Broadcast {
                message: broadcast_message,
            },
        ),
    )
    .await
    .expect("broadcast should return even when one connection is slow");
    assert!(!connections.contains_key(&slow_connection_id));
    assert!(slow_disconnect_token.is_cancelled());
    assert!(!fast_disconnect_token.is_cancelled());
    let fast_message = fast_writer_rx
        .try_recv()
        .expect("fast connection should receive the broadcast notification");
    assert!(matches!(
        fast_message.message,
        OutgoingMessage::AppServerNotification(ServerNotificationEnvelope {
            notification: ServerNotification::ConfigWarning(ConfigWarningNotification { summary, .. }),
            ..
        }) if summary == "test"
    ));

    let slow_message = slow_writer_rx
        .try_recv()
        .expect("slow connection should retain its original buffered message");
    assert!(matches!(
        slow_message.message,
        OutgoingMessage::AppServerNotification(ServerNotificationEnvelope {
            notification: ServerNotification::ConfigWarning(ConfigWarningNotification { summary, .. }),
            ..
        }) if summary == "already-buffered"
    ));
}

#[tokio::test]
async fn to_connection_stdio_waits_instead_of_disconnecting_when_writer_queue_is_full() {
    let connection_id = ConnectionId(3);
    let (writer_tx, mut writer_rx) = mpsc::channel(1);
    writer_tx
        .send(QueuedOutgoingMessage::new(app_server_notification(
            ServerNotification::ConfigWarning(ConfigWarningNotification {
                summary: "queued".to_string(),
                details: None,
                path: None,
                range: None,
            }),
        )))
        .await
        .expect("channel should accept the first queued message");

    let mut connections = HashMap::new();
    connections.insert(
        connection_id,
        OutboundConnectionState::new(
            writer_tx,
            Arc::new(AtomicBool::new(true)),
            Arc::new(AtomicBool::new(true)),
            Arc::new(RwLock::new(HashSet::new())),
            /*disconnect_sender*/ None,
        ),
    );

    let route_task = tokio::spawn(async move {
        route_outgoing_envelope(
            &mut connections,
            OutgoingEnvelope::ToConnection {
                connection_id,
                message: app_server_notification(ServerNotification::ConfigWarning(
                    ConfigWarningNotification {
                        summary: "second".to_string(),
                        details: None,
                        path: None,
                        range: None,
                    },
                )),
                write_complete_tx: None,
            },
        )
        .await
    });

    let first = timeout(Duration::from_millis(100), writer_rx.recv())
        .await
        .expect("first queued message should be readable")
        .expect("first queued message should exist");
    timeout(Duration::from_millis(100), route_task)
        .await
        .expect("routing should finish after the first queued message is drained")
        .expect("routing task should succeed");

    assert!(matches!(
        first.message,
        OutgoingMessage::AppServerNotification(ServerNotificationEnvelope {
            notification: ServerNotification::ConfigWarning(ConfigWarningNotification { summary, .. }),
            ..
        }) if summary == "queued"
    ));
    let second = writer_rx
        .try_recv()
        .expect("second notification should be delivered once the queue has room");
    assert!(matches!(
        second.message,
        OutgoingMessage::AppServerNotification(ServerNotificationEnvelope {
            notification: ServerNotification::ConfigWarning(ConfigWarningNotification { summary, .. }),
            ..
        }) if summary == "second"
    ));
}

fn initialize_remote_control_test_session(connection: &ConnectionState) {
    assert_eq!(
        connection
            .session
            .initialize(InitializedConnectionSessionState {
                experimental_api_enabled: true,
                process_indeterminate_enabled: false,
                opted_out_notification_methods: HashSet::new(),
                app_server_client_name: "remote-status-test".to_string(),
                client_version: "0.0.0".to_string(),
                request_attestation: false,
                client_mcp_extensions: connection.session.client_mcp_extensions(),
            }),
        Ok(())
    );
}

#[tokio::test]
async fn remote_control_status_queued_before_initialize_cannot_overtake_its_response() {
    // Exercise both an empty recipient snapshot and a nonempty one. A broadcast
    // accidentally retained in either path would pick up the late-ready client.
    for existing_connection_id in [None, Some(ConnectionId(31))] {
        let late_connection_id = ConnectionId(32);
        let (outgoing_tx, mut outgoing_rx) = mpsc::channel(/*buffer*/ 4);
        let outgoing = OutgoingMessageSender::new(
            outgoing_tx,
            codex_analytics::AnalyticsEventsClient::disabled(),
        );
        let mut connection_states = HashMap::new();
        let mut outbound_connections = HashMap::new();
        let mut existing_writer_rx = None;

        if let Some(connection_id) = existing_connection_id {
            let initialized = Arc::new(AtomicBool::new(/*v*/ true));
            let experimental_api_enabled = Arc::new(AtomicBool::new(/*v*/ true));
            let opted_out = Arc::new(RwLock::new(HashSet::new()));
            let connection = ConnectionState::new(
                ConnectionOrigin::Stdio,
                Arc::clone(&initialized),
                Arc::clone(&experimental_api_enabled),
                Arc::clone(&opted_out),
            );
            initialize_remote_control_test_session(&connection);
            connection_states.insert(connection_id, connection);
            let (writer_tx, writer_rx) = mpsc::channel(/*buffer*/ 4);
            outbound_connections.insert(
                connection_id,
                OutboundConnectionState::new(
                    writer_tx,
                    initialized,
                    experimental_api_enabled,
                    opted_out,
                    /*disconnect_sender*/ None,
                ),
            );
            existing_writer_rx = Some(writer_rx);
        }

        let initialized = Arc::new(AtomicBool::new(/*v*/ false));
        let experimental_api_enabled = Arc::new(AtomicBool::new(/*v*/ true));
        let opted_out = Arc::new(RwLock::new(HashSet::new()));
        connection_states.insert(
            late_connection_id,
            ConnectionState::new(
                ConnectionOrigin::Stdio,
                Arc::clone(&initialized),
                Arc::clone(&experimental_api_enabled),
                Arc::clone(&opted_out),
            ),
        );
        let (writer_tx, mut writer_rx) = mpsc::channel(/*buffer*/ 4);
        outbound_connections.insert(
            late_connection_id,
            OutboundConnectionState::new(
                writer_tx,
                Arc::clone(&initialized),
                experimental_api_enabled,
                opted_out,
                /*disconnect_sender*/ None,
            ),
        );
        let status = RemoteControlStatusChangedNotification {
            status: RemoteControlConnectionStatus::Disabled,
            server_name: "remote-status-test".to_string(),
            installation_id: "remote-status-installation".to_string(),
            environment_id: None,
        };

        // Use the production producer, while intentionally retaining every
        // envelope in its real channel until initialization has completed.
        send_remote_control_status_to_initialized_connections(
            &connection_states,
            &outgoing,
            status.clone(),
        )
        .await;

        let connection = &connection_states[&late_connection_id];
        initialize_remote_control_test_session(connection);
        let request_id = ConnectionRequestId {
            connection_id: late_connection_id,
            request_id: RequestId::Integer(7),
        };
        let Ok(codex_home) = AbsolutePathBuf::from_absolute_path(std::env::temp_dir()) else {
            panic!("temporary directory should provide an absolute test path");
        };
        let response = InitializeResponse {
            user_agent: "remote-status-test".to_string(),
            codex_home,
            platform_family: std::env::consts::FAMILY.to_string(),
            platform_os: std::env::consts::OS.to_string(),
            process_indeterminate: false,
        };
        let Ok(expected_response) = serde_json::to_value(&response) else {
            panic!("initialize response should serialize");
        };
        outgoing.send_response(request_id.clone(), response).await;
        outgoing
            .send_server_notification_to_connections(
                &[late_connection_id],
                ServerNotification::RemoteControlStatusChanged(status.clone()),
            )
            .await;
        initialized.store(true, Ordering::Release);

        // Dequeue only after the same ready transition that the old broadcast
        // route observed. This is a producer/channel/router test, not a call to
        // the complete initialize request handler.
        while let Ok(envelope) = outgoing_rx.try_recv() {
            route_outgoing_envelope(&mut outbound_connections, envelope).await;
        }
        let Ok(first) = writer_rx.try_recv() else {
            panic!("initialize response must be the first delivered message");
        };
        let OutgoingMessage::Response(response) = first.message else {
            panic!("a pre-initialize notification must not overtake the response");
        };
        let Ok(actual_response) = serde_json::to_value(response.result) else {
            panic!("delivered initialize response should serialize");
        };
        assert_eq!(
            (response.id, actual_response),
            (request_id.request_id, expected_response)
        );
        let Ok(initial_status) = writer_rx.try_recv() else {
            panic!("initial cached remote-control status should be delivered");
        };
        let OutgoingMessage::AppServerNotification(ServerNotificationEnvelope {
            notification: ServerNotification::RemoteControlStatusChanged(actual_status),
            ..
        }) = initial_status.message
        else {
            panic!("initial message after the response must carry remote-control status");
        };
        assert_eq!(actual_status, status);
        assert!(matches!(
            writer_rx.try_recv(),
            Err(mpsc::error::TryRecvError::Empty)
        ));

        if let Some(existing_writer_rx) = existing_writer_rx.as_mut() {
            let Ok(update) = existing_writer_rx.try_recv() else {
                panic!("already initialized connection should receive the update");
            };
            let OutgoingMessage::AppServerNotification(ServerNotificationEnvelope {
                notification: ServerNotification::RemoteControlStatusChanged(actual_status),
                ..
            }) = update.message
            else {
                panic!("existing connection should receive remote-control status");
            };
            assert_eq!(actual_status, status);
            assert!(matches!(
                existing_writer_rx.try_recv(),
                Err(mpsc::error::TryRecvError::Empty)
            ));
        }
        assert!(matches!(
            outgoing_rx.try_recv(),
            Err(mpsc::error::TryRecvError::Empty)
        ));
    }
}
