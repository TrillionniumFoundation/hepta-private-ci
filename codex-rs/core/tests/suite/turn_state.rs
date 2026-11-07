#![allow(clippy::unwrap_used)]

use anyhow::Result;
use codex_config::Constrained;
use codex_protocol::models::PermissionProfile;
use codex_protocol::protocol::AskForApproval;
use core_test_support::responses::WebSocketConnectionConfig;
use core_test_support::responses::ev_assistant_message;
use core_test_support::responses::ev_completed;
use core_test_support::responses::ev_exec_command_call;
use core_test_support::responses::ev_reasoning_item;
use core_test_support::responses::ev_response_created;
use core_test_support::responses::mount_response_sequence;
use core_test_support::responses::sse;
use core_test_support::responses::sse_response;
use core_test_support::responses::start_mock_server;
use core_test_support::responses::start_websocket_server_with_headers;
use core_test_support::skip_if_no_network;
use core_test_support::test_codex::test_codex;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

const TURN_STATE_HEADER: &str = "x-codex-turn-state";

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn responses_turn_state_persists_within_turn_and_resets_after() -> Result<()> {
    skip_if_no_network!(Ok(()));

    let server = start_mock_server().await;
    let call_id = "shell-turn-state";

    let first_response = sse(vec![
        ev_response_created("resp-1"),
        ev_reasoning_item("rsn-1", &["thinking"], &[]),
        ev_exec_command_call(call_id, "echo turn-state"),
        ev_completed("resp-1"),
    ]);
    let second_response = sse(vec![
        ev_response_created("resp-2"),
        ev_assistant_message("msg-1", "done"),
        ev_completed("resp-2"),
    ]);
    let third_response = sse(vec![
        ev_response_created("resp-3"),
        ev_assistant_message("msg-2", "done"),
        ev_completed("resp-3"),
    ]);

    // First response sets turn_state; follow-up request in the same turn should echo it.
    let responses = vec![
        sse_response(first_response).insert_header(TURN_STATE_HEADER, "ts-1"),
        sse_response(second_response),
        sse_response(third_response),
    ];
    let request_log = mount_response_sequence(&server, responses).await;

    let test = test_codex().build(&server).await?;
    test.submit_turn("run a shell command").await?;
    test.submit_turn("second turn").await?;

    let requests = request_log.requests();
    assert_eq!(requests.len(), 3);
    // Initial turn request has no header; follow-up has it; next turn clears it.
    assert_eq!(requests[0].header(TURN_STATE_HEADER), None);
    assert_eq!(
        requests[1].header(TURN_STATE_HEADER),
        Some("ts-1".to_string())
    );
    assert_eq!(requests[2].header(TURN_STATE_HEADER), None);

    let parse_turn_id = |header: Option<String>| {
        let value = header?;
        let parsed: Value = serde_json::from_str(&value).ok()?;
        parsed
            .get("turn_id")
            .and_then(Value::as_str)
            .map(str::to_string)
    };

    let first_turn_id = parse_turn_id(requests[0].header("x-codex-turn-metadata"))
        .expect("first request should include turn metadata turn_id");
    let second_turn_id = parse_turn_id(requests[1].header("x-codex-turn-metadata"))
        .expect("follow-up request should include turn metadata turn_id");
    let third_turn_id = parse_turn_id(requests[2].header("x-codex-turn-metadata"))
        .expect("new turn request should include turn metadata turn_id");

    assert_eq!(first_turn_id, second_turn_id);
    assert_ne!(second_turn_id, third_turn_id);

    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn websocket_turn_state_persists_within_turn_and_resets_after() -> Result<()> {
    skip_if_no_network!(Ok(()));

    let server = start_websocket_server_with_headers(vec![
        WebSocketConnectionConfig {
            requests: vec![vec![ev_response_created("warm-1"), ev_completed("warm-1")]],
            response_headers: Vec::new(),
            accept_delay: None,
            close_after_requests: true,
        },
        WebSocketConnectionConfig {
            requests: vec![
                vec![
                    json!({
                        "type": "response.metadata",
                        "headers": {(TURN_STATE_HEADER): "ts-1"},
                    }),
                    ev_response_created("resp-1"),
                    ev_reasoning_item("rsn-1", &["thinking"], &[]),
                    ev_exec_command_call("ws-shell-turn-state", "echo websocket"),
                    ev_completed("resp-1"),
                ],
                vec![
                    ev_response_created("resp-2"),
                    ev_assistant_message("msg-1", "done"),
                    ev_completed("resp-2"),
                ],
                vec![
                    ev_response_created("resp-4"),
                    ev_assistant_message("msg-2", "done"),
                    ev_completed("resp-4"),
                ],
            ],
            response_headers: Vec::new(),
            accept_delay: None,
            close_after_requests: false,
        },
    ])
    .await;

    let mut builder = test_codex();
    let test = builder.build_with_websocket_server(&server).await?;
    // Phase 1: read-only startup prewarm has its own connection and empty response.
    // Phase 2: the danger-full-access turn uses a new connection and mints state.
    test.submit_turn("run the echo command").await?;
    // Phase 3: the follow-up replays that state on the same physical connection.
    // Phase 4: the next logical turn reuses the connection but starts with empty state.
    test.submit_turn("start another turn").await?;

    assert_eq!(server.handshakes().len(), 2);
    let connections = server.connections();
    assert_eq!(connections.len(), 2);
    assert_eq!(
        connections.iter().map(Vec::len).collect::<Vec<_>>(),
        vec![1, 3]
    );
    let requests = connections.into_iter().flatten().collect::<Vec<_>>();
    assert_eq!(requests.len(), 4);
    let bodies = requests
        .iter()
        .map(core_test_support::responses::WebSocketRequest::body_json)
        .collect::<Vec<_>>();
    assert_eq!(
        bodies
            .iter()
            .map(|body| body["client_metadata"][TURN_STATE_HEADER].clone())
            .collect::<Vec<_>>(),
        vec![json!(null), json!(null), json!("ts-1"), json!(null)]
    );
    let turn_metadata = bodies
        .iter()
        .map(|body| {
            serde_json::from_str::<Value>(
                body["client_metadata"]["x-codex-turn-metadata"]
                    .as_str()
                    .expect("websocket request should include turn metadata"),
            )
        })
        .collect::<Result<Vec<_>, _>>()?;
    assert_eq!(
        turn_metadata
            .iter()
            .map(|metadata| metadata["request_kind"].clone())
            .collect::<Vec<_>>(),
        vec![
            json!("prewarm"),
            json!("turn"),
            json!("turn"),
            json!("turn"),
        ]
    );
    assert_eq!(bodies[0]["generate"], json!(false));
    assert!(bodies[1..].iter().all(|body| body["generate"].is_null()));
    assert_eq!(
        turn_metadata
            .iter()
            .map(|metadata| metadata["sandbox_mode"].clone())
            .collect::<Vec<_>>(),
        vec![
            json!("read-only"),
            json!("danger-full-access"),
            json!("danger-full-access"),
            json!("danger-full-access"),
        ]
    );
    let first_turn_id = turn_metadata[1]["turn_id"]
        .as_str()
        .expect("first turn should include turn_id");
    let follow_up_turn_id = turn_metadata[2]["turn_id"]
        .as_str()
        .expect("same-turn follow-up should include turn_id");
    let next_turn_id = turn_metadata[3]["turn_id"]
        .as_str()
        .expect("next turn should include turn_id");
    assert_eq!(first_turn_id, follow_up_turn_id);
    assert_ne!(follow_up_turn_id, next_turn_id);

    server.shutdown().await;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn websocket_turn_state_is_stable_within_turn() -> Result<()> {
    skip_if_no_network!(Ok(()));

    let server = start_websocket_server_with_headers(vec![WebSocketConnectionConfig {
        requests: vec![
            vec![ev_response_created("warm-1"), ev_completed("warm-1")],
            vec![
                json!({
                    "type": "response.metadata",
                    "headers": {(TURN_STATE_HEADER): "ts-1"},
                }),
                ev_response_created("resp-1"),
                ev_exec_command_call("ws-shell-1", "echo one"),
                ev_completed("resp-1"),
            ],
            vec![
                json!({
                    "type": "response.metadata",
                    "headers": {(TURN_STATE_HEADER): "ts-2"},
                }),
                ev_response_created("resp-2"),
                ev_exec_command_call("ws-shell-2", "echo two"),
                ev_completed("resp-2"),
            ],
            vec![
                ev_response_created("resp-3"),
                ev_assistant_message("msg-1", "done"),
                ev_completed("resp-3"),
            ],
        ],
        response_headers: Vec::new(),
        accept_delay: None,
        close_after_requests: false,
    }])
    .await;
    // Keep prewarm and the original submit_turn permission identity identical.
    let mut builder = test_codex().with_config(|config| {
        config.permissions.approval_policy = Constrained::allow_any(AskForApproval::Never);
        config
            .permissions
            .set_permission_profile(PermissionProfile::Disabled)
            .expect("set the same permission profile for prewarm and business requests");
    });
    let test = builder.build_with_websocket_server(&server).await?;

    // Phase 1: prewarm consumes only its separate empty response.
    // Phase 2: the first business request receives state and the first tool call.
    // Phase 3: its follow-up replays that state and executes the second tool.
    // Phase 4: the second tool follow-up still sends the first state, not ts-2.
    test.submit_turn("run two echo commands").await?;

    assert_eq!(server.handshakes().len(), 1);
    let requests = server.single_connection();
    assert_eq!(requests.len(), 4);
    let bodies = requests
        .iter()
        .map(core_test_support::responses::WebSocketRequest::body_json)
        .collect::<Vec<_>>();
    assert_eq!(bodies[0]["generate"], json!(false));
    assert!(bodies[1..].iter().all(|body| body["generate"].is_null()));
    assert_eq!(bodies[0]["client_metadata"][TURN_STATE_HEADER], json!(null));
    assert_eq!(
        bodies[1..]
            .iter()
            .map(|body| body["client_metadata"][TURN_STATE_HEADER].clone())
            .collect::<Vec<_>>(),
        vec![json!(null), json!("ts-1"), json!("ts-1")]
    );
    let turn_metadata = bodies
        .iter()
        .map(|body| {
            serde_json::from_str::<Value>(
                body["client_metadata"]["x-codex-turn-metadata"]
                    .as_str()
                    .expect("websocket request should include turn metadata"),
            )
        })
        .collect::<Result<Vec<_>, _>>()?;
    assert_eq!(
        turn_metadata
            .iter()
            .map(|metadata| metadata["request_kind"].clone())
            .collect::<Vec<_>>(),
        vec![
            json!("prewarm"),
            json!("turn"),
            json!("turn"),
            json!("turn"),
        ]
    );
    assert_eq!(
        turn_metadata
            .iter()
            .map(|metadata| metadata["sandbox_mode"].clone())
            .collect::<Vec<_>>(),
        vec![json!("danger-full-access"); 4]
    );
    for (body, call_id, expected_output) in [
        (&bodies[2], "ws-shell-1", "one\n"),
        (&bodies[3], "ws-shell-2", "two\n"),
    ] {
        let outputs = body["input"]
            .as_array()
            .expect("tool follow-up should include input items")
            .iter()
            .filter(|item| item["type"] == "function_call_output" && item["call_id"] == call_id)
            .collect::<Vec<_>>();
        assert_eq!(outputs.len(), 1, "expected one output for {call_id}");
        let payload = &outputs[0]["output"];
        let output = payload
            .as_str()
            .or_else(|| payload.get("content").and_then(Value::as_str))
            .expect("exec_command should return its text output")
            .replace("\r\n", "\n");
        let (header, stdout) = output
            .split_once("\nOutput:\n")
            .expect("exec_command should include its output section");
        assert_eq!(
            header
                .lines()
                .filter(|line| {
                    line.starts_with("Process exited with code ")
                        || line.starts_with("Process running with session ID ")
                })
                .collect::<Vec<_>>(),
            vec!["Process exited with code 0"],
            "{call_id} should have finished successfully"
        );
        assert_eq!(stdout, expected_output, "unexpected output for {call_id}");
    }

    server.shutdown().await;
    Ok(())
}
