use crate::hmi_fixture::Fixture;
use crate::hmi_fixture::INPUT;
use crate::hmi_fixture::Profile;
use crate::hmi_fixture::sends;
use crate::support::fleet::connect_app_server_with_experimental;
use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_app_server_client::RemoteAppServerClient;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ThreadQueueReconcileMode;
use codex_app_server_protocol::ThreadQueueReconcileOutcome;
use codex_app_server_protocol::ThreadQueueReconcileParams;
use codex_app_server_protocol::ThreadQueueReconcileResponse;
use codex_app_server_protocol::UserInput;
use codex_protocol::user_input::user_input_payload_sha256;
use core_test_support::responses;
use serde_json::json;
use std::time::Duration;
use wiremock::Mock;
use wiremock::ResponseTemplate;
use wiremock::matchers::method;
use wiremock::matchers::path_regex;

async fn exact_status(
    client: &RemoteAppServerClient,
    thread: &str,
    delivery: &str,
) -> Result<ThreadQueueReconcileResponse> {
    let input = vec![UserInput::Text {
        text: INPUT.into(),
        text_elements: Vec::new(),
    }];
    let core_input = input.iter().cloned().map(UserInput::into_core).collect::<Vec<_>>();
    Ok(client.request_typed(ClientRequest::ThreadQueueReconcile {
        request_id: RequestId::Integer(40),
        params: ThreadQueueReconcileParams {
            thread_id: thread.into(),
            input,
            client_user_message_id: format!("hepta.authbus:{delivery}"),
            expected_payload_sha256: user_input_payload_sha256(&core_input)?,
            mode: ThreadQueueReconcileMode::ReconcileOnly,
        },
    }).await?)
}

enum Boundary {
    Interrupt,
    Reconnect,
}

async fn queued_owner_cancellation(profile: Profile, boundary: Boundary) -> Result<()> {
    let model = responses::start_mock_server().await;
    Mock::given(method("POST"))
        .and(path_regex(".*/responses$"))
        .respond_with(ResponseTemplate::new(200)
            .insert_header("content-type", "text/event-stream")
            .set_body_string(responses::sse(vec![
                responses::ev_assistant_message("blocker", "held original turn"),
                responses::ev_completed("blocker-response"),
            ]))
            .set_delay(Duration::from_secs(30)))
        .mount(&model).await;
    let audio = matches!(profile, Profile::TemporaryAudio);
    let fixture = Fixture::new(&model, profile).await?;
    let control = fixture.fleet.control_client(&fixture.agent, fixture.generation)?;
    control.submit_authbus_text(fixture.request(1)?).await?;
    tokio::time::timeout(Duration::from_secs(10), async {
        while sends(&model).await != 1 {
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    }).await?;
    let ingress = control.session_ingress().await?;
    let client = connect_app_server_with_experimental(
        &ingress.socket_path, "hmi-interleaving-oracle", 64, /*experimental_api*/ true,
    ).await?;
    let mut ui = fixture.ui().await?;
    let submission = if audio {
        json!({"type":"submitAudio","request":fixture.audio(2, &[0; 3200])?})
    } else {
        json!({"type":"submit","request":fixture.request(2)?})
    };
    ui.send(submission.clone()).await?;
    let admission = ui.until("admission").await?;
    let delivery = admission["receipt"]["delivery_id"].as_str().context("queued delivery")?;
    tokio::time::timeout(Duration::from_secs(10), async {
        loop {
            if matches!(exact_status(&client, &fixture.thread, delivery).await?.outcome,
                ThreadQueueReconcileOutcome::Queued { .. }) {
                return Ok::<_, anyhow::Error>(());
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    }).await??;
    ensure!(sends(&model).await == 1, "queued HMI input already dispatched");
    match boundary {
        Boundary::Reconnect => {
            ui.send(json!({"type":"reconnect"})).await?;
            ui.until("reconnected").await?;
        }
        Boundary::Interrupt => {
            ui.send(json!({"type":"interrupt"})).await?;
            ui.until("outputRetired").await?;
            let interruption = ui.until("interruptRequested").await?;
            ensure!(interruption["outcome"]["terminalObserved"] == false);
        }
    }
    let after = exact_status(&client, &fixture.thread, delivery).await?;
    ensure!(matches!(after.outcome, ThreadQueueReconcileOutcome::Cancelled),
        "retired original HMI input remains executable in the canonical queue: {after:?}");
    // A duplicate retains the exact cancelled binding and cannot authorize replay.
    ui.send(submission).await?;
    let duplicate = ui.until("admission").await?;
    ensure!(duplicate["receipt"]["delivery_id"] == delivery);
    ensure!(matches!(exact_status(&client, &fixture.thread, delivery).await?.outcome,
        ThreadQueueReconcileOutcome::Cancelled));
    ensure!(sends(&model).await == 1);
    let pool = fixture.evidence_pool().await?;
    let rows: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM authbus_outbox").fetch_one(&pool).await?;
    ensure!(rows == 2, "cancellation or duplicate changed canonical observation count");
    pool.close().await;
    let thread = fixture.read_thread().await?;
    ensure!(thread.thread.turns.len() == 1);
    // Cancelling a queued input must free the one-input presentation slot.
    // A fresh intent can queue behind A without reviving the cancelled B.
    let fresh = if audio {
        json!({"type":"submitAudio","request":fixture.audio(3, &[0; 3200])?})
    } else {
        json!({"type":"submit","request":fixture.request(3)?})
    };
    ui.send(fresh).await?;
    let fresh_admission=ui.until("admission").await?;
    let fresh_id=fresh_admission["receipt"]["delivery_id"].as_str().context("fresh queued delivery")?;
    ensure!(fresh_id!=delivery);
    ensure!(sends(&model).await==1);
    ui.send(json!({"type":"stop"})).await?;
    let terminal=ui.until("sessionTerminal").await?;
    let fresh_status=exact_status(&client,&fixture.thread,fresh_id).await?;
    ensure!(matches!(fresh_status.outcome, ThreadQueueReconcileOutcome::Cancelled),
        "Stop did not retire the fresh owned queue input: {fresh_status:?}; terminal: {terminal}");
    client.shutdown().await?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn queued_text_interrupt_cancels_the_original_owner_input_without_dispatch() -> Result<()> {
    queued_owner_cancellation(Profile::Text, Boundary::Interrupt).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn queued_audio_reconnect_cancels_the_original_owner_input_without_dispatch() -> Result<()> {
    queued_owner_cancellation(Profile::TemporaryAudio, Boundary::Reconnect).await
}
