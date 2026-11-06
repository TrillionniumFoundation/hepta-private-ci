use assert_matches::assert_matches;
use codex_core::StartThreadOptions;
use codex_core::SuspendTurnOutcome;
use codex_core::TurnInputRequest;
use codex_features::Feature;
use codex_history::RolloutItem;
use codex_history::RolloutLine;
use std::sync::Arc;
use std::time::Duration;

use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::Op;
use codex_protocol::protocol::SessionSource;
use codex_protocol::protocol::SubAgentSource;
use codex_protocol::user_input::UserInput;
use core_test_support::responses::ev_completed;
use core_test_support::responses::ev_function_call;
use core_test_support::responses::ev_response_created;
use core_test_support::responses::mount_response_once;
use core_test_support::responses::mount_sse_once;
use core_test_support::responses::mount_sse_sequence;
use core_test_support::responses::sse;
use core_test_support::responses::sse_response;
use core_test_support::responses::start_mock_server;
use core_test_support::test_codex::test_codex;
use core_test_support::wait_for_event;
use regex_lite::Regex;
use serde_json::json;

/// Integration test: spawn a long‑running exec_command tool via a mocked Responses SSE
/// function call, then interrupt the session and expect TurnAborted.
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn interrupt_long_running_tool_emits_turn_aborted() {
    let command = "sleep 60";

    let args = json!({
        "cmd": command,
        "yield_time_ms": 60_000
    })
    .to_string();
    let body = sse(vec![
        ev_function_call("call_sleep", "exec_command", &args),
        ev_completed("done"),
    ]);

    let server = start_mock_server().await;
    mount_sse_once(&server, body).await;

    let fixture = test_codex()
        .with_model("gpt-5.4")
        .build(&server)
        .await
        .unwrap();
    let codex = Arc::clone(&fixture.codex);

    // Kick off a turn that triggers the function call.
    codex
        .start_or_steer_turn(TurnInputRequest::user_input(vec![UserInput::Text {
            text: "start sleep".into(),
            text_elements: Vec::new(),
        }]))
        .await
        .unwrap();

    // Wait until the exec begins to avoid a race, then interrupt.
    wait_for_event(&codex, |ev| matches!(ev, EventMsg::ExecCommandBegin(_))).await;

    codex.submit(Op::Interrupt).await.unwrap();

    // Expect TurnAborted soon after.
    wait_for_event(&codex, |ev| matches!(ev, EventMsg::TurnAborted(_))).await;
    codex.submit(Op::CleanBackgroundTerminals).await.unwrap();
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn root_turn_suspension_preserves_unfinished_turn_history() {
    let server = start_mock_server().await;
    // Waiting on the mocked response keeps the turn active on local and remote executors
    // without requiring an OS-specific command or a working sandboxed child process.
    let original_request = mount_response_once(
        &server,
        sse_response(sse(vec![
            ev_response_created("suspended_response"),
            ev_completed("suspended_response"),
        ]))
        .set_delay(Duration::from_secs(60)),
    )
    .await;
    let test = test_codex()
        .with_config(|config| {
            let _ = config.features.enable(Feature::HeptaTurnRecovery);
        })
        .with_model("gpt-5.4")
        .build_with_auto_env(&server)
        .await
        .expect("start persistent root thread");
    let codex = Arc::clone(&test.codex);
    let descendant = test
        .thread_manager
        .start_thread(StartThreadOptions {
            session_source: Some(SessionSource::SubAgent(SubAgentSource::ThreadSpawn {
                parent_thread_id: test.session_configured.thread_id,
                depth: 1,
                agent_path: None,
                agent_nickname: None,
                agent_role: None,
            })),
            ..StartThreadOptions::new(test.config.clone())
        })
        .await
        .expect("start a currently loaded descendant");
    let submitted = codex
        .start_or_steer_turn(TurnInputRequest::user_input(vec![UserInput::Text {
            text: "preserve this exact unfinished turn".into(),
            text_elements: Vec::new(),
        }]))
        .await
        .expect("start root turn");
    let codex_core::TurnInputSubmission::Started { turn_id } = submitted else {
        panic!("expected a started root turn");
    };
    wait_for_event(&codex, |event| matches!(event, EventMsg::TurnStarted(_))).await;
    // A started task is not yet a durable recovery checkpoint. Observe the
    // actual request, which is sent only after input, context, and Ready flush.
    tokio::time::timeout(Duration::from_secs(5), async {
        while original_request.requests().is_empty() {
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .expect("original turn should reach the provider before suspension");
    original_request.single_request();

    assert_eq!(
        codex
            .suspend_turn_and_shutdown()
            .await
            .expect("reject handoff while a descendant remains loaded"),
        SuspendTurnOutcome::HasLiveDescendants,
    );
    descendant
        .thread
        .shutdown_and_wait()
        .await
        .expect("stop the descendant before root handoff");
    test.thread_manager
        .remove_thread(&descendant.thread_id)
        .await
        .expect("remove the stopped descendant from the live thread inventory");

    // A previously admitted descendant no longer blocks handoff once it is stopped
    // and removed; suspension only consults the current live subtree.
    assert_eq!(
        codex
            .suspend_turn_and_shutdown()
            .await
            .expect("stop and close the old writer"),
        SuspendTurnOutcome::Suspended {
            turn_id: turn_id.clone(),
        },
    );
    let rollout_path = codex.rollout_path().expect("rollout path");
    let rollout = tokio::fs::read_to_string(&rollout_path)
        .await
        .expect("read durable rollout");
    let items = rollout
        .lines()
        .map(|line| {
            serde_json::from_str::<RolloutLine>(line)
                .expect("parse durable rollout")
                .item
        })
        .collect::<Vec<_>>();
    assert!(items.iter().all(|item| !matches!(
        item,
        RolloutItem::EventMsg(EventMsg::TurnAborted(_) | EventMsg::TurnComplete(_))
    )));
    assert_eq!(
        items.iter().rev().find_map(|item| match item {
            RolloutItem::EventMsg(EventMsg::TurnRecoveryCandidate(marker))
                if marker.turn_id == turn_id =>
                Some(&marker.state),
            _ => None,
        }),
        Some(&codex_protocol::protocol::TurnRecoveryCandidateState::Ready)
    );
    test.thread_manager
        .remove_thread(&test.session_configured.thread_id)
        .await
        .expect("unload the suspended root");
    let recovered_request = mount_sse_once(
        &server,
        sse(vec![
            ev_response_created("recovered_response"),
            ev_completed("recovered_response"),
        ]),
    )
    .await;
    // A replacement runtime must retain the selected executor, cwd, model,
    // permissions, and deployment endpoint of the exact interrupted request.
    let original_config = test.config.clone();
    let original_environments = codex.environment_selections().await;
    let auth_manager = test.thread_manager.auth_manager();
    let state_db = codex_core::init_state_db(&original_config).await;
    let thread_store = codex_core::thread_store_from_config(&original_config, state_db.clone());
    let resumed_manager = codex_core::ThreadManager::new(
        &original_config,
        Arc::clone(&auth_manager),
        codex_core::build_models_manager(&original_config, Arc::clone(&auth_manager)),
        codex_core::CodexAppsToolsCache::default(),
        SessionSource::Exec,
        test.thread_manager.environment_manager(),
        codex_extension_api::empty_extension_registry(),
        Arc::new(codex_home::CodexHomeUserInstructionsProvider::new(
            original_config.codex_home.clone(),
        )),
        /*analytics_events_client*/ None,
        thread_store,
        codex_core::local_agent_graph_store_from_state_db(state_db.as_ref()),
        codex_core::resolve_installation_id(&original_config.codex_home)
            .await
            .expect("reuse the persisted installation identity"),
        /*attestation_provider*/ None,
        /*external_time_provider*/ None,
    );
    let resumed_manager = if original_config.features.enabled(Feature::CodeModeHost)
        && let Ok(host_program) = codex_utils_cargo_bin::cargo_bin("codex-code-mode-host")
    {
        codex_core::test_support::with_code_mode_host_program(
            resumed_manager,
            host_program,
            &original_config,
        )
    } else {
        resumed_manager
    };
    // Rebuild the thread registry and history while retaining the actual executor.
    // The original selections keep remote paths in their executor's convention.
    let initial_history = codex_core::RolloutRecorder::get_rollout_history(&rollout_path)
        .await
        .expect("load the suspended root's durable history");
    let resumed = resumed_manager
        .resume_thread_with_history_and_environments(
            original_config,
            initial_history,
            auth_manager,
            /*parent_trace*/ None,
            codex_protocol::mcp::ClientMcpExtensions::default(),
            Some(original_environments.clone()),
        )
        .await
        .expect("resume the suspended root on a replacement runtime");
    assert_eq!(
        resumed.thread.environment_selections().await,
        original_environments,
    );
    let expected_epoch = resumed
        .thread
        .recovery_epoch_if_idle(&turn_id)
        .await
        .expect("suspended history must expose an idle recovery candidate");
    assert_eq!(
        resumed
            .thread
            .recover_turn_if_idle(codex_core::RecoverTurnRequest {
                turn_id: turn_id.clone(),
                // Bind the request to the replacement runtime's current candidate.
                expected_epoch,
                thread_settings: Default::default(),
                trace: None,
            })
            .await
            .expect("recover the unfinished turn"),
        codex_core::StartIfIdleSubmission::Started {
            turn_id: turn_id.clone(),
        },
    );
    let completed = wait_for_event(&resumed.thread, |event| {
        matches!(event, EventMsg::TurnComplete(_))
    })
    .await;
    let EventMsg::TurnComplete(completed) = completed else {
        unreachable!("wait_for_event returned unexpected event");
    };
    assert_eq!(completed.turn_id, turn_id);
    recovered_request.single_request();
    original_request.single_request();
}

/// After an interrupt we expect the next request to the model to include both
/// the original tool call and an `"aborted"` `function_call_output`. This test
/// exercises the follow-up flow: it sends another user turn, inspects the mock
/// responses server, and ensures the model receives the synthesized abort.
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn interrupt_tool_records_history_entries() {
    let command = "sleep 60";
    let call_id = "call-history";

    let args = json!({
        "cmd": command,
        "yield_time_ms": 60_000
    })
    .to_string();
    let first_body = sse(vec![
        ev_response_created("resp-history"),
        ev_function_call(call_id, "exec_command", &args),
        ev_completed("resp-history"),
    ]);
    let follow_up_body = sse(vec![
        ev_response_created("resp-followup"),
        ev_completed("resp-followup"),
    ]);

    let server = start_mock_server().await;
    let response_mock = mount_sse_sequence(&server, vec![first_body, follow_up_body]).await;

    let fixture = test_codex()
        .with_model("gpt-5.4")
        .build(&server)
        .await
        .unwrap();
    let codex = Arc::clone(&fixture.codex);

    codex
        .start_or_steer_turn(TurnInputRequest::user_input(vec![UserInput::Text {
            text: "start history recording".into(),
            text_elements: Vec::new(),
        }]))
        .await
        .unwrap();

    wait_for_event(&codex, |ev| matches!(ev, EventMsg::ExecCommandBegin(_))).await;

    tokio::time::sleep(Duration::from_secs_f32(0.1)).await;
    codex.submit(Op::Interrupt).await.unwrap();

    wait_for_event(&codex, |ev| matches!(ev, EventMsg::TurnAborted(_))).await;

    codex
        .start_or_steer_turn(TurnInputRequest::user_input(vec![UserInput::Text {
            text: "follow up".into(),
            text_elements: Vec::new(),
        }]))
        .await
        .unwrap();

    wait_for_event(&codex, |ev| matches!(ev, EventMsg::TurnComplete(_))).await;

    let requests = response_mock.requests();
    assert!(
        requests.len() == 2,
        "expected two calls to the responses API, got {}",
        requests.len()
    );

    assert!(
        response_mock.saw_function_call(call_id),
        "function call not recorded in responses payload"
    );
    let output = response_mock
        .function_call_output_text(call_id)
        .expect("missing function_call_output text");
    let re = Regex::new(r"^Wall time: ([0-9]+(?:\.[0-9])?) seconds\naborted by user$")
        .expect("compile regex");
    let captures = re.captures(&output);
    assert_matches!(
        captures.as_ref(),
        Some(caps) if caps.get(1).is_some(),
        "aborted message with elapsed seconds"
    );
    let secs: f32 = captures
        .expect("aborted message with elapsed seconds")
        .get(1)
        .unwrap()
        .as_str()
        .parse()
        .unwrap();
    assert!(
        secs >= 0.1,
        "expected at least one tenth of a second of elapsed time, got {secs}"
    );
    codex.submit(Op::CleanBackgroundTerminals).await.unwrap();
}

/// After an interrupt we persist a model-visible `<turn_aborted>` marker in the conversation
/// history. This test asserts that the marker is included in the next `/responses` request.
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn interrupt_persists_turn_aborted_marker_in_next_request() {
    let command = "sleep 60";
    let call_id = "call-turn-aborted-marker";

    let args = json!({
        "cmd": command,
        "yield_time_ms": 60_000
    })
    .to_string();
    let first_body = sse(vec![
        ev_response_created("resp-marker"),
        ev_function_call(call_id, "exec_command", &args),
        ev_completed("resp-marker"),
    ]);
    let follow_up_body = sse(vec![
        ev_response_created("resp-followup"),
        ev_completed("resp-followup"),
    ]);

    let server = start_mock_server().await;
    let response_mock = mount_sse_sequence(&server, vec![first_body, follow_up_body]).await;

    let fixture = test_codex()
        .with_model("gpt-5.4")
        .build(&server)
        .await
        .unwrap();
    let codex = Arc::clone(&fixture.codex);

    codex
        .start_or_steer_turn(TurnInputRequest::user_input(vec![UserInput::Text {
            text: "start interrupt marker".into(),
            text_elements: Vec::new(),
        }]))
        .await
        .unwrap();

    wait_for_event(&codex, |ev| matches!(ev, EventMsg::ExecCommandBegin(_))).await;

    tokio::time::sleep(Duration::from_secs_f32(0.1)).await;
    codex.submit(Op::Interrupt).await.unwrap();

    wait_for_event(&codex, |ev| matches!(ev, EventMsg::TurnAborted(_))).await;

    codex
        .start_or_steer_turn(TurnInputRequest::user_input(vec![UserInput::Text {
            text: "follow up".into(),
            text_elements: Vec::new(),
        }]))
        .await
        .unwrap();

    wait_for_event(&codex, |ev| matches!(ev, EventMsg::TurnComplete(_))).await;

    let requests = response_mock.requests();
    assert_eq!(requests.len(), 2, "expected two calls to the responses API");

    let follow_up_request = &requests[1];
    let user_texts = follow_up_request.message_input_texts("user");
    assert!(
        user_texts
            .iter()
            .any(|text| text.contains("<turn_aborted>")),
        "expected <turn_aborted> marker in follow-up request"
    );
    codex.submit(Op::CleanBackgroundTerminals).await.unwrap();
}
