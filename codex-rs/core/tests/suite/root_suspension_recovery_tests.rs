use codex_core::NotSubmittedReason;
use codex_core::RecoverTurnRequest;
use codex_core::StartIfIdleSubmission;
use codex_core::SuspendTurnOutcome;
use codex_core::TurnInputRequest;
use codex_core::TurnInputSubmission;
use codex_features::Feature;
use codex_history::RolloutItem;
use codex_protocol::protocol::EventMsg;
use codex_protocol::user_input::UserInput;
use core_test_support::fs_wait;
use core_test_support::hooks::trust_discovered_hooks;
use core_test_support::responses::start_mock_server;
use core_test_support::test_codex::test_codex;
use pretty_assertions::assert_eq;
use serde_json::json;
use std::sync::Arc;
use std::time::Duration;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn root_suspension_before_ready_does_not_create_recovery_authority() {
    let server = start_mock_server().await;
    let test = test_codex()
        .with_pre_build_hook(|home| {
            let script = home.join("block_before_ready.py");
            let started = home.join("before_ready_hook_started");
            std::fs::write(&script, format!(
                "import json, sys, time\nfrom pathlib import Path\njson.load(sys.stdin)\nPath({}).write_text('started')\ntime.sleep(60)\n",
                serde_json::to_string(&started).expect("encode original hook path"),
            )).expect("write gated original UserPromptSubmit hook");
            std::fs::write(home.join("hooks.json"), json!({
                "hooks": { "UserPromptSubmit": [{ "hooks": [{
                    "type": "command",
                    "command": format!("python3 \"{}\"", script.display()),
                }] }] }
            }).to_string()).expect("write original hook configuration");
        })
        .with_config(|config| {
            trust_discovered_hooks(config);
            let _ = config.features.enable(Feature::HeptaTurnRecovery);
        })
        .build_with_auto_env(&server)
        .await
        .expect("start persistent root with a blocked input hook");
    let submission = test
        .codex
        .start_or_steer_turn(TurnInputRequest::user_input(vec![UserInput::Text {
            text: "input whose original hook has not completed".into(),
            text_elements: Vec::new(),
        }]))
        .await
        .expect("start original turn");
    let TurnInputSubmission::Started { turn_id } = submission else {
        panic!("expected the original root turn to start");
    };
    fs_wait::wait_for_path_exists(
        test.codex_home_path().join("before_ready_hook_started"),
        Duration::from_secs(5),
    )
    .await
    .expect("the original input hook must block before sampling");
    assert_eq!(
        test.codex
            .suspend_turn_and_shutdown()
            .await
            .expect("suspend the unready turn"),
        SuspendTurnOutcome::Suspended {
            turn_id: turn_id.clone()
        }
    );
    let rollout_path = test.codex.rollout_path().expect("original rollout path");
    let (items, _, parse_errors) =
        codex_rollout::RolloutRecorder::load_rollout_items(&rollout_path)
            .await
            .expect("read the closed original rollout");
    assert_eq!(parse_errors, 0);
    assert!(items.iter().all(|item| !matches!(
        item,
        RolloutItem::EventMsg(EventMsg::TurnAborted(_) | EventMsg::TurnComplete(_))
    )));
    assert!(items.iter().all(|item| !matches!(item,
        RolloutItem::EventMsg(EventMsg::TurnRecoveryCandidate(marker))
            if marker.state == codex_protocol::protocol::TurnRecoveryCandidateState::Ready
    )));
    assert!(
        !server
            .received_requests()
            .await
            .expect("read physical requests")
            .iter()
            .any(|request| request.url.path().ends_with("/responses"))
    );
    test.thread_manager
        .remove_thread(&test.session_configured.thread_id)
        .await
        .expect("unload the suspended original root");
    let resumed = test_codex()
        .with_config(|config| {
            let _ = config.features.enable(Feature::HeptaTurnRecovery);
        })
        .resume(&server, Arc::clone(&test.home), rollout_path)
        .await
        .expect("cold resume the original unready history");
    assert_eq!(resumed.codex.recovery_epoch_if_idle(&turn_id).await, None);
    assert_eq!(
        resumed
            .codex
            .recover_turn_if_idle(RecoverTurnRequest {
                turn_id,
                expected_epoch: 0,
                thread_settings: Default::default(),
                trace: None,
            })
            .await
            .expect("return the original recovery rejection"),
        StartIfIdleSubmission::NotSubmitted {
            reason: NotSubmittedReason::RecoveryStateChanged
        }
    );
    assert!(
        !server
            .received_requests()
            .await
            .expect("read final physical requests")
            .iter()
            .any(|request| request.url.path().ends_with("/responses"))
    );
}
