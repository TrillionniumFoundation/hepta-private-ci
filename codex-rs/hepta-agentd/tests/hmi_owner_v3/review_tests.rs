//! Fresh review regressions; original signer and actual owner/Core process.
use crate::hmi_fixture::ANSWER;
use crate::hmi_fixture::Fixture;
use crate::hmi_fixture::Profile;
use crate::hmi_fixture::Ui;
use crate::hmi_fixture::sends;
use crate::hmi_fixture::write_policy;
use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use core_test_support::responses;
use serde_json::Value;
use serde_json::json;

async fn input_failure(ui: &mut Ui) -> Result<Value> {
    loop {
        let event = ui.next().await?;
        ensure!(
            event["type"] != "sessionError" && event["type"] != "admission",
            "expected a bounded input failure, got {event}"
        );
        if event["type"] == "inputError" {
            return Ok(event);
        }
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn session_profile_cannot_change_when_text_and_audio_identity_fields_overlap() -> Result<()> {
    let model = responses::start_mock_server().await;
    responses::mount_sse_once(
        &model,
        responses::sse(vec![
            responses::ev_assistant_message("profile-review", ANSWER),
            responses::ev_completed("profile-review-response"),
        ]),
    )
    .await;
    let fixture = Fixture::new(&model, Profile::TemporaryAudio).await?;
    let path = fixture
        .audio_policy
        .as_ref()
        .context("fixture audio policy")?;
    let mut policy: Value = serde_json::from_slice(&std::fs::read(path)?)?;
    // Deliberately use identical valid labels. A signature profile is not an ID string.
    policy["device_id"] = json!(format!("agent-ui:{}", fixture.agent.agent_id));
    policy["device_generation"] = json!(1);
    policy["organ_id"] = json!("hmi:text");
    policy["organ_generation"] = json!(fixture.generation);
    write_policy(path, &policy)?;
    let mut audio = fixture.audio(1, &[0; 3200])?;
    audio.body.source.stream.device_id = policy["device_id"]
        .as_str()
        .context("profile device")?
        .into();
    audio.body.source.stream.device_generation = 1;
    audio.body.source.stream.organ_id = "hmi:text".into();
    audio.body.source.stream.organ_generation = fixture.generation;
    fixture.sign_audio(&mut audio)?;
    let mut text_ui = fixture.ui().await?;
    text_ui
        .send(json!({"type":"attach","request":fixture.request(1)?}))
        .await?;
    text_ui.until("attached").await?;
    text_ui
        .send(json!({"type":"submitAudio","request":audio}))
        .await?;
    let rejected = input_failure(&mut text_ui).await?;
    ensure!(
        rejected["error"]
            .as_str()
            .context("text/audio profile rejection")?
            .contains("profile"),
        "{rejected}"
    );
    ensure!(sends(&model).await == 0);
    text_ui.send(json!({"type":"stop"})).await?;
    text_ui.until("sessionTerminal").await?;
    drop(text_ui);
    let mut audio_ui = fixture.ui().await?;
    audio_ui
        .send(json!({"type":"submitAudio","request":audio}))
        .await?;
    audio_ui.until("admission").await?;
    audio_ui.completed().await?;
    audio_ui
        .send(json!({"type":"submit","request":fixture.request(1)?}))
        .await?;
    let rejected = input_failure(&mut audio_ui).await?;
    ensure!(
        rejected["error"]
            .as_str()
            .context("audio/text profile rejection")?
            .contains("profile"),
        "{rejected}"
    );
    ensure!(sends(&model).await == 1);
    let pool = fixture.evidence_pool().await?;
    let rows: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM authbus_outbox")
        .fetch_one(&pool)
        .await?;
    pool.close().await;
    ensure!(rows == 1);
    audio_ui.send(json!({"type":"stop"})).await?;
    audio_ui.until("sessionTerminal").await?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn post_commit_checkpoint_failure_keeps_the_actual_observation_receipt_and_unknown_readiness()
-> Result<()> {
    let model = responses::start_mock_server().await;
    let fixture = Fixture::new(&model, Profile::TemporaryAudio).await?;
    let request = fixture.audio(1, &[0; 3200])?;
    let witness = fixture
        ._checkpoint
        .path()
        .join("authbus-replay-checkpoint.json");
    let retained_witness = std::fs::read(&witness)?;
    // Inject a schema fault in disposable owner state; never invent a frontier.
    std::fs::write(&witness, b"{}")?;
    let mut ui = fixture.ui().await?;
    ui.send(json!({"type":"submitAudio","request":request}))
        .await?;
    let failure = input_failure(&mut ui).await?;
    let pool = fixture.evidence_pool().await?;
    let rows: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM authbus_outbox")
        .fetch_one(&pool)
        .await?;
    pool.close().await;
    ensure!(
        rows == 1,
        "fault must occur after the actual observation committed"
    );
    ensure!(
        failure["committedAudioObservation"].is_object(),
        "known committed observation was lost in the failure outcome: {failure}"
    );
    ensure!(
        failure["committedAudioObservation"]["source"]
            == serde_json::to_value(&request.body.source)?
    );
    ensure!(
        failure["admissionReady"] == false,
        "failed external replay checkpoint cannot become ready admission: {failure}"
    );
    ensure!(
        sends(&model).await == 0,
        "pending replay witness allowed model dispatch"
    );
    std::fs::write(&witness, &retained_witness)?; // Restore the exact pre-fault retained witness, not a new digest.
    ui.send(json!({"type":"stop"})).await?;
    ui.until("sessionTerminal").await?;
    Ok(())
}
