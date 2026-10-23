use crate::hmi_fixture::{Fixture,Profile,INPUT,ANSWER,sends,write_policy};
use anyhow::{Context,Result,ensure};
use codex_app_server_protocol::ThreadItem;
use codex_hepta_agentd::SignedAudioObservationV1;
use codex_hepta_types::Digest32;
use core_test_support::responses;
use serde_json::{Value,json};
use sqlx::sqlite::{SqliteConnectOptions,SqlitePoolOptions};

async fn rejected(fixture:&Fixture,request:&SignedAudioObservationV1,reason:&str)->Result<()> {
    let mut ui=fixture.ui().await?;ui.send(json!({"type":"submitAudio","request":request})).await?;
    for _ in 0..12 {
        let event=ui.next().await?;
        if event["type"]=="sessionError" || event["type"]=="inputError" {
            ensure!(event["error"].as_str().context("rejection reason")?.contains(reason),"{event}");
            return Ok(());
        }
        ensure!(event["type"]!="admission","invalid signed audio admitted: {event}");
    }
    anyhow::bail!("no audio rejection observed")
}

#[tokio::test(flavor="multi_thread",worker_threads=4)]
async fn actual_owner_audio_binds_signature_device_capture_interval_digest_and_original_thread()->Result<()> {
    let model=responses::start_mock_server().await;
    let observed=responses::mount_sse_once(&model,responses::sse(vec![responses::ev_assistant_message("audio-answer",ANSWER),responses::ev_completed("audio-response")])).await;
    let mut fixture=Fixture::new(&model,Profile::TemporaryAudio).await?;
    let pcm:Vec<u8>=(0i16..1600).flat_map(i16::to_le_bytes).collect();
    let request=fixture.audio(1,&pcm)?;
    let mut wrong=request.clone();wrong.signature_hex="00".repeat(64);
    rejected(&fixture,&wrong,"InvalidSignature").await?;
    let mut wrong=request.clone();wrong.body.source.stream.device_generation+=1;fixture.sign_audio(&mut wrong)?;
    rejected(&fixture,&wrong,"device/capture authority").await?;
    let mut wrong=request.clone();wrong.body.source.capture_generation+=1;wrong.body.source.asset_id="capture-4-1.pcm16".into();fixture.sign_audio(&mut wrong)?;
    rejected(&fixture,&wrong,"device/capture authority").await?;
    let mut wrong=request.clone();wrong.body.source.end_sample+=1;
    rejected(&fixture,&wrong,"sample interval").await?;
    let mut wrong=request.clone();wrong.body.source.start_sample+=1;wrong.body.source.end_sample+=1;
    rejected(&fixture,&wrong,"InvalidSignature").await?; // An otherwise valid interval is covered by the signature.
    let mut wrong=request.clone();wrong.body.source.sha256="00".repeat(32);fixture.sign_audio(&mut wrong)?;
    rejected(&fixture,&wrong,"media byte digest").await?;
    let mut wrong=request.clone();wrong.signature_hex=fixture.request(1)?.signature_hex;
    rejected(&fixture,&wrong,"InvalidSignature").await?; // A text-domain signature cannot become an audio observation.
    ensure!(sends(&model).await==0);
    let mut ui=fixture.ui().await?;ui.send(json!({"type":"submitAudio","request":request})).await?;
    let admission=ui.until("admission").await?;let receipt=&admission["receipt"]["audioObservation"];
    ensure!(receipt["source"]==serde_json::to_value(&request.body.source)?);
    ensure!(receipt["observationSha256"]==Digest32::of_bytes(&serde_json::to_vec(&request.body)?).to_string());
    let delivery=admission["receipt"]["delivery_id"].as_str().context("audio delivery")?.to_owned();
    ui.completed().await?;
    ensure!(observed.single_request().message_input_texts("user").iter().any(|t|t==INPUT));
    ui.send(json!({"type":"submitAudio","request":request})).await?;
    let duplicate=ui.until("admission").await?;
    ensure!(duplicate["receipt"]["delivery_id"]==delivery && sends(&model).await==1);
    ui.send(json!({"type":"stop"})).await?;ui.until("sessionTerminal").await?;drop(ui);
    let mut replay=request.clone();replay.message_id="audio:replay:new-id".into();fixture.sign_audio(&mut replay)?;
    rejected(&fixture,&replay,"Replay").await?;
    fixture.restart().await?;
    replay.body.spawn_generation=fixture.generation;
    replay.message_id="audio:replay:after-process-restart".into();fixture.sign_audio(&mut replay)?;
    rejected(&fixture,&replay,"Replay").await?;
    ensure!(sends(&model).await==1,"a durable audio replay fence was lost on actual process restart");
    let store=fixture.store().await?;
    let pool=SqlitePoolOptions::new().max_connections(1).connect_with(SqliteConnectOptions::new().filename(store.path()).read_only(true)).await?;
    let encoded:Vec<u8>=sqlx::query_scalar("SELECT payload FROM authbus_outbox WHERE delivery_id = ?").bind(delivery.parse::<Digest32>()?.as_array().as_slice()).fetch_one(&pool).await?;
    ensure!(serde_json::from_slice::<Value>(&encoded)?==serde_json::to_value(&request.body)?);
    let count:i64=sqlx::query_scalar("SELECT COUNT(*) FROM authbus_outbox").fetch_one(&pool).await?;
    ensure!(count==1,"rejections/replay created additional canonical observations");
    pool.close().await;store.close().await;
    let thread=fixture.read_thread().await?;
    ensure!(thread.thread.turns.len()==1);
    ensure!(thread.thread.turns[0].items.iter().filter(|i|matches!(i,ThreadItem::UserMessage{..})).count()==1);
    ensure!(thread.thread.turns[0].items.iter().any(|i|matches!(i,ThreadItem::UserMessage{client_id:Some(id),..} if id==&format!("hepta.authbus:{delivery}"))));
    println!("SIGNED_AUDIO_OBSERVATION={{\"deliveryId\":\"{delivery}\",\"sourceSha256\":\"{}\",\"byteLength\":{},\"canonicalRows\":{count},\"modelRequests\":1,\"physicalDevice\":false}}",request.body.source.sha256,pcm.len());
    Ok(())
}

#[tokio::test(flavor="multi_thread",worker_threads=4)]
async fn actual_owner_audio_current_device_revocation_fences_publication_and_further_admission()->Result<()> {
    let model=responses::start_mock_server().await;
    responses::mount_sse_once(&model,responses::sse(vec![responses::ev_assistant_message("audio-revocation",ANSWER),responses::ev_completed("audio-revocation-response")])).await;
    let fixture=Fixture::new(&model,Profile::TemporaryAudio).await?;
    let request=fixture.audio(1,&[0;3200])?;
    let mut ui=fixture.ui().await?;ui.send(json!({"type":"submitAudio","request":request})).await?;
    ui.until("admission").await?;ui.completed().await?;
    let path=fixture.audio_policy.as_ref().context("device policy")?;
    let mut policy:Value=serde_json::from_slice(&std::fs::read(path)?)?;policy["revoked"]=json!(true);write_policy(path,&policy)?;
    let terminal=ui.until("sessionTerminal").await?;
    ensure!(terminal["error"].as_str().context("live revocation")?.contains("device/capture authority changed"));
    drop(ui);
    rejected(&fixture,&request,"device/capture authority").await?;
    let second=fixture.audio(2,&[1;3200])?;
    rejected(&fixture,&second,"device/capture authority").await?;
    ensure!(sends(&model).await==1);
    Ok(())
}
