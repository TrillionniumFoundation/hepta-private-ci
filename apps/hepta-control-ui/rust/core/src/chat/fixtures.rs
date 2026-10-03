//! Explicit non-default visual fixture; never part of ordinary product artifacts.
use super::*;
use crate::chat_timeline::{History, Message, MessagePhase, Role, ViewFence};
pub fn owner_conversation_fixture() -> ChatWorkspace {
    let mut workspace = ChatWorkspace {
        presentation_note: Some("DETERMINISTIC OWNER FIXTURE · no live chat connection".into()),
        ..Default::default()
    };
    let fence = ViewFence {
        owner_session: "fixture-owner-session".into(),
        generation: 4,
    };
    let ticket = workspace
        .begin_history(0, "fixture-thread", fence)
        .expect("bounded fixture");
    workspace.receive_history(&ticket,History{thread_id:"fixture-thread".into(),title:"Interface review".into(),revision:7,event_sequence:20,messages:vec![
        Message{id:"fixture-user-1".into(),turn_id:"fixture-turn-1".into(),role:Role::User,text:"What changed in the conversation workspace?".into(),phase:MessagePhase::Observed},
        Message{id:"fixture-assistant-1".into(),turn_id:"fixture-turn-1".into(),role:Role::Assistant,text:"Conversations now lead the app. The timeline and composer stay together, while runtime tools live in the Console tab. Your draft remains intact when you switch tabs.".into(),phase:MessagePhase::Completed},
        Message{id:"fixture-user-2".into(),turn_id:"fixture-turn-2".into(),role:Role::User,text:"请保留中文输入、键盘焦点和滚动位置。\nAlso show uncertain outcomes honestly.".into(),phase:MessagePhase::Observed},
        Message{id:"fixture-assistant-2".into(),turn_id:"fixture-turn-2".into(),role:Role::Assistant,text:"I’m checking the narrow layout and input lifecycle. The owner has not supplied a completed result for this response yet…".into(),phase:MessagePhase::Streaming},
    ]}).expect("valid fixture projection");
    workspace
}

pub fn extend_scroll_fixture(workspace: &mut ChatWorkspace) {
    let mut history = workspace
        .timeline()
        .and_then(|timeline| timeline.history())
        .cloned()
        .expect("installed owner fixture");
    let original = history.messages.clone();
    history.messages.clear();
    for index in 0..16 {
        for (offset, mut message) in original.clone().into_iter().enumerate() {
            message.id = format!("{}-{index}", message.id);
            message.text = format!(
                "[Fixture {}] {}",
                index * original.len() + offset + 1,
                message.text
            );
            history.messages.push(message);
        }
    }
    history.revision += 1;
    let ticket = workspace
        .begin_history(
            workspace.active_id(),
            "fixture-thread",
            ViewFence {
                owner_session: "fixture-owner-session".into(),
                generation: 4,
            },
        )
        .unwrap();
    workspace.receive_history(&ticket, history).unwrap();
}
pub fn append_scroll_fixture(workspace: &mut ChatWorkspace) {
    let sequence = workspace
        .timeline()
        .and_then(|timeline| timeline.history())
        .unwrap()
        .event_sequence
        + 1;
    let ticket = workspace
        .begin_history(
            workspace.active_id(),
            "fixture-thread",
            ViewFence {
                owner_session: "fixture-owner-session".into(),
                generation: 4,
            },
        )
        .unwrap();
    workspace
        .receive_delta(
            &ticket,
            "fixture-assistant-2-15",
            sequence,
            " New deterministic fixture activity.",
        )
        .unwrap();
}
