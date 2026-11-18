//! Owns bounded FIFO admission alongside realtime event forwarding.

use super::RealtimeConversationEnd;
use super::RealtimeHandoffRequest;
use super::RealtimeStartOutput;
use super::realtime_delegation_from_handoff;
use super::send_realtime_conversation_closed;
use crate::session::session::Session;
use codex_api::RealtimeEvent;
use codex_protocol::protocol::Event;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::RealtimeConversationRealtimeEvent;
use std::sync::Arc;
use std::sync::atomic::Ordering;
use tokio::sync::oneshot;
use tracing::debug;
use tracing::info;

struct RoutedInput {
    text: String,
    handoff: Option<RealtimeHandoffRequest>,
    first_decision: Option<oneshot::Sender<()>>,
}

pub(super) async fn run(session: Arc<Session>, sub_id: String, start: RealtimeStartOutput) {
    let RealtimeStartOutput {
        realtime_active,
        handoff,
        stop_token,
        events_rx,
        transcript_tail_rx,
        sdp: _,
    } = start;
    // One queued request plus the router's one owned in-flight request. The
    // input pump still services outbound work when this FIFO backpressures it.
    let (routing_tx, routing_rx) = async_channel::bounded::<RoutedInput>(/*cap*/ 1);
    let forwarding_session = Arc::clone(&session);
    let forwarding_id = sub_id.clone();
    let forward = async move {
        let mut end = RealtimeConversationEnd::TransportClosed;
        // Already-parsed handoffs stay ahead of the original transcript tail.
        while let Ok(event) = events_rx.recv().await {
            match &event {
                RealtimeEvent::AudioOut(_) => {}
                _ => info!(event = ?event, "received realtime conversation event"),
            }
            if matches!(&event, RealtimeEvent::Error(_)) {
                end = RealtimeConversationEnd::Error;
            }
            if let RealtimeEvent::HandoffRequested(request) = &event
                && let Some(text) = realtime_delegation_from_handoff(request)
            {
                debug!(text = %text, "[realtime-text] realtime conversation text output");
                let (first_decision, decided) = oneshot::channel();
                let owner =
                    RealtimeHandoffRequest::new(handoff.clone(), request.handoff_id.clone());
                routing_tx
                    .send(RoutedInput {
                        text,
                        handoff: Some(owner),
                        first_decision: Some(first_decision),
                    })
                    .await
                    .unwrap_or_else(|_| panic!("the joined realtime router remains owned"));
                // Preserve normal start/steer ordering. An exact Finish wait
                // signals here before waiting, allowing following audio/events.
                let _ = decided.await;
            }
            forwarding_session
                .send_event_raw(Event {
                    id: forwarding_id.clone(),
                    msg: EventMsg::RealtimeConversationRealtime(
                        RealtimeConversationRealtimeEvent { payload: event },
                    ),
                })
                .await;
        }
        if let Ok(text) = transcript_tail_rx.recv().await {
            routing_tx
                .send(RoutedInput {
                    text,
                    handoff: None,
                    first_decision: None,
                })
                .await
                .unwrap_or_else(|_| panic!("the joined realtime router drains the original tail"));
        }
        drop(routing_tx);
        end
    };
    let routing_session = Arc::clone(&session);
    let route = async move {
        while let Ok(input) = routing_rx.recv().await {
            routing_session
                .route_realtime_text_input(
                    input.text,
                    input.handoff,
                    &stop_token,
                    input.first_decision,
                )
                .await;
        }
    };
    // These are two futures in the manager-owned fanout, not detached tasks.
    let (end, ()) = tokio::join!(forward, route);
    if realtime_active.swap(false, Ordering::Relaxed) {
        match end {
            RealtimeConversationEnd::TransportClosed => {
                info!("realtime conversation transport closed");
            }
            RealtimeConversationEnd::Requested | RealtimeConversationEnd::Error => {}
        }
        session
            .conversation
            .finish_if_active(&realtime_active)
            .await;
        send_realtime_conversation_closed(&session, sub_id, end).await;
    }
}

#[cfg(test)]
#[path = "routing_tests.rs"]
mod tests;
