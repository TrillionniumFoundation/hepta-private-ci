use hepta_control_core::chat_transport::{
    ChatCommand, ChatMessage, ChatRequest, ChatResponse, ChatResult,
};

fn request() -> ChatRequest {
    ChatRequest {
        session_id: "session-1".into(),
        connection_generation: 3,
        command: ChatCommand::Timeline {
            thread_id: "thread-1".into(),
            cursor: None,
            limit: 1,
        },
    }
}
fn response() -> ChatResponse {
    ChatResponse {
        session_id: "session-1".into(),
        connection_generation: 3,
        approval_required: false,
        result: ChatResult::Timeline {
            thread_id: "thread-1".into(),
            data: vec![ChatMessage {
                id: "message-1".into(),
                turn_id: "turn-1".into(),
                sender: "assistant".into(),
                body: "Observed reply".into(),
            }],
            next_cursor: None,
            active_turn_id: None,
        },
    }
}
#[test]
fn response_is_bound_to_session_generation_thread_and_result_kind() {
    let request = request();
    let valid = response();
    assert!(valid.validate_for(&request).is_ok());
    let mut wrong = valid.clone();
    wrong.connection_generation += 1;
    assert!(wrong.validate_for(&request).is_err());
    let mut wrong = valid.clone();
    wrong.session_id = "other".into();
    assert!(wrong.validate_for(&request).is_err());
    let mut wrong = valid.clone();
    if let ChatResult::Timeline { thread_id, .. } = &mut wrong.result {
        *thread_id = "other".into();
    }
    assert!(wrong.validate_for(&request).is_err());
    let mut wrong = valid;
    wrong.result = ChatResult::CancelRequested {
        thread_id: "thread-1".into(),
        turn_id: "turn-1".into(),
    };
    assert!(wrong.validate_for(&request).is_err());
}
#[test]
fn oversized_and_duplicate_observations_are_rejected_before_render() {
    let request = request();
    let mut wrong = response();
    if let ChatResult::Timeline { data, .. } = &mut wrong.result {
        data.push(data[0].clone());
    }
    assert!(wrong.validate_for(&request).is_err());
    let mut wrong = response();
    if let ChatResult::Timeline { data, .. } = &mut wrong.result {
        data[0].body = "a".repeat(16_385);
    }
    assert!(wrong.validate_for(&request).is_err());
    let mut wrong = response();
    if let ChatResult::Timeline { data, .. } = &mut wrong.result {
        data[0].sender = "system".into();
    }
    assert!(wrong.validate_for(&request).is_err());
}
