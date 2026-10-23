use crate::hmi_fixture::{Fixture,Profile,INPUT,ANSWER,sends};
use anyhow::{Context,Result,ensure};
use codex_app_server_protocol::{ThreadItem,TurnStatus};
use core_test_support::responses;
use serde_json::json;
use std::time::Duration;
use wiremock::{Mock,ResponseTemplate};
use wiremock::matchers::{method,path_regex};

#[tokio::test(flavor="multi_thread",worker_threads=4)]
async fn complete_agentd_restart_recovers_the_original_request_without_dispatch_then_accepts_next_turn()->Result<()> {
    let model=responses::start_mock_server().await;
    responses::mount_sse_once(&model,responses::sse(vec![responses::ev_assistant_message("before-restart",ANSWER),responses::ev_completed("before-restart-response")])).await;
    let mut fixture=Fixture::new(&model,Profile::Text).await?;
    let original=fixture.request(1)?;
    let mut ui=fixture.ui().await?;ui.send(json!({"type":"submit","request":original})).await?;
    let admission=ui.until("admission").await?;
    let delivery=admission["receipt"]["delivery_id"].as_str().context("original ID")?.to_owned();
    ui.completed().await?;ui.send(json!({"type":"stop"})).await?;ui.until("sessionTerminal").await?;drop(ui);
    let before=fixture.read_thread().await?;let turn=before.thread.turns[0].id.clone();
    fixture.restart().await?;
    let mut ui=fixture.ui().await?;
    let current=fixture.request(2)?;
    ui.send(json!({"type":"attach","request":current})).await?;
    ui.until("attached").await?;
    ui.send(json!({"type":"reconcile","delivery_id":delivery,"text":INPUT})).await?;
    let recovered=ui.until("reconciled").await?;
    ensure!(recovered["receipt"]["outcome"]["type"]=="persisted" && recovered["receipt"]["outcome"]["turnId"]==turn,"{recovered}");
    ui.send(json!({"type":"cancelRecovered","delivery_id":delivery,"text":INPUT})).await?;
    let cancelled=ui.until("recoveredInterruptRequested").await?;
    ensure!(cancelled["terminalObserved"]==false && sends(&model).await==1,"{cancelled}");
    ui.send(json!({"type":"submit","request":original})).await?;
    let stale=ui.next().await?;
    ensure!(stale["type"]=="inputError" && stale["error"].as_str().context("stale generation")?.contains("generation"),"{stale}");
    let after=fixture.read_thread().await?;
    ensure!(after.thread.turns.len()==1 && after.thread.turns[0].id==turn && after.thread.turns[0].status==TurnStatus::Completed);
    ensure!(after.thread.turns[0].items.iter().filter(|i|matches!(i,ThreadItem::UserMessage {..})).count()==1);
    responses::mount_sse_once(&model,responses::sse(vec![responses::ev_assistant_message("after-restart",ANSWER),responses::ev_completed("after-restart-response")])).await;
    ui.send(json!({"type":"submit","request":current})).await?;ui.until("admission").await?;ui.completed().await?;
    ensure!(sends(&model).await==2,"read-only recovery or cancellation redispatched the original input");
    ui.send(json!({"type":"stop"})).await?;ui.until("sessionTerminal").await?;
    Ok(())
}

#[tokio::test(flavor="multi_thread",worker_threads=4)]
async fn full_process_crash_during_a_live_turn_recovers_and_cancels_without_model_reexecution()->Result<()> {
    let model=responses::start_mock_server().await;
    Mock::given(method("POST")).and(path_regex(".*/responses$")).respond_with(ResponseTemplate::new(200)
        .insert_header("content-type","text/event-stream")
        .set_body_string(responses::sse(vec![responses::ev_assistant_message("crashed-response","must not replay"),responses::ev_completed("crashed-turn")]))
        .set_delay(Duration::from_secs(30))).mount(&model).await;
    let mut fixture=Fixture::new(&model,Profile::Text).await?;
    let mut ui=fixture.ui().await?;ui.send(json!({"type":"submit","request":fixture.request(1)?})).await?;
    let admission=ui.until("admission").await?;
    let delivery=admission["receipt"]["delivery_id"].as_str().context("active delivery")?.to_owned();
    tokio::time::timeout(Duration::from_secs(10),async {while sends(&model).await!=1 {tokio::time::sleep(Duration::from_millis(10)).await;}}).await?;
    let original=fixture.read_thread().await?;let turn=original.thread.turns[0].id.clone();
    ensure!(original.thread.turns[0].status==TurnStatus::InProgress);
    fixture.crash_and_restart().await?;drop(ui);
    let mut ui=fixture.ui().await?;ui.send(json!({"type":"attach","request":fixture.request(2)?})).await?;ui.until("attached").await?;
    ui.send(json!({"type":"reconcile","delivery_id":delivery,"text":INPUT})).await?;
    let recovered=ui.until("reconciled").await?;
    ensure!(recovered["receipt"]["outcome"]["type"]=="persisted" && recovered["receipt"]["outcome"]["turnId"]==turn,"{recovered}");
    ui.send(json!({"type":"cancelRecovered","delivery_id":delivery,"text":INPUT})).await?;
    let cancelled=ui.until("recoveredInterruptRequested").await?;
    ensure!(cancelled["terminalObserved"]==false);
    let cold=fixture.read_thread().await?;
    ensure!(cold.thread.turns.len()==1 && cold.thread.turns[0].id==turn && cold.thread.turns[0].status==TurnStatus::Interrupted,"{cold:?}");
    ensure!(cold.thread.turns[0].items.iter().filter(|i|matches!(i,ThreadItem::UserMessage {client_id:Some(id),..} if id==&format!("hepta.authbus:{delivery}"))).count()==1);
    ui.send(json!({"type":"stop"})).await?;ui.until("sessionTerminal").await?;
    ensure!(sends(&model).await==1,"process recovery/cancellation physically executed the original model input again");
    println!("CRASH_RECOVERY={{\"deliveryId\":\"{delivery}\",\"turnId\":\"{turn}\",\"persistedStatus\":\"interrupted\",\"modelRequests\":1,\"terminalAckClaimed\":false}}");
    Ok(())
}
