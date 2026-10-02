use hepta_control_core::chat_transport::*;

fn request(command: ChatCommand) -> ChatRequest {
    ChatRequest {
        session_id: "session-1".into(),
        connection_generation: 1,
        command,
    }
}
#[test]
fn sends_require_exact_bounded_identity_and_content() {
    let base = request(ChatCommand::Send {
        thread_id: "thread-1".into(),
        operation_id: "operation-1".into(),
        text: "你好".into(),
    });
    assert_eq!(base.validate(), Ok(()));
    let mut generation = base.clone();
    generation.connection_generation = 0;
    assert!(generation.validate().is_err());
    let mut session = base;
    session.session_id = "x\ny".into();
    assert!(session.validate().is_err());
    for text in [
        String::new(),
        " \n".into(),
        "\0".into(),
        "é".repeat(MAX_CHAT_TEXT_BYTES),
    ] {
        assert!(
            request(ChatCommand::Send {
                thread_id: "thread-1".into(),
                operation_id: "operation-1".into(),
                text
            })
            .validate()
            .is_err()
        );
    }
}
#[test]
fn read_pages_and_cursors_are_bounded() {
    for limit in [0, MAX_CHAT_PAGE + 1, u32::MAX] {
        assert!(
            request(ChatCommand::List {
                cursor: None,
                limit
            })
            .validate()
            .is_err()
        );
    }
    assert!(
        request(ChatCommand::Timeline {
            thread_id: "thread-1".into(),
            cursor: Some("x".repeat(4097)),
            limit: 10
        })
        .validate()
        .is_err()
    );
    assert_eq!(
        request(ChatCommand::List {
            cursor: None,
            limit: MAX_CHAT_PAGE
        })
        .validate(),
        Ok(())
    );
}
#[test]
fn wire_has_one_explicit_command_and_rejects_unknown_authority_fields() {
    let send = request(ChatCommand::Send {
        thread_id: "thread-1".into(),
        operation_id: "stable-1".into(),
        text: "hello".into(),
    });
    let value = serde_json::to_value(&send).unwrap();
    assert_eq!(value["command"]["threadId"], "thread-1");
    assert_eq!(
        serde_json::from_value::<ChatRequest>(value.clone()).unwrap(),
        send
    );
    let mut forged = value;
    forged["authority"] = serde_json::json!("approved");
    assert!(serde_json::from_value::<ChatRequest>(forged).is_err());
}
#[test]
fn reconciliation_is_distinct_from_new_send_and_does_not_claim_completion() {
    let send = request(ChatCommand::Reconcile {
        thread_id: "thread-1".into(),
        operation_id: "stable-1".into(),
        text: "hello".into(),
    });
    assert_eq!(
        serde_json::to_value(send).unwrap()["command"]["type"],
        "reconcile"
    );
    let response = ChatResponse {
        session_id: "s".into(),
        connection_generation: 3,
        approval_required: true,
        result: ChatResult::Submission {
            operation_id: "stable-1".into(),
            state: SubmissionState::Queued {
                queue_id: "q".into(),
            },
        },
    };
    assert_eq!(
        serde_json::from_slice::<ChatResponse>(&serde_json::to_vec(&response).unwrap()).unwrap(),
        response
    );
}
#[test]
fn response_validation_rejects_cross_session_scope_and_excess_pages() {
    let request = request(ChatCommand::Timeline {
        thread_id: "thread-1".into(),
        cursor: None,
        limit: 1,
    });
    let mut response = ChatResponse {
        session_id: request.session_id.clone(),
        connection_generation: 1,
        approval_required: false,
        result: ChatResult::Timeline {
            thread_id: "thread-1".into(),
            data: vec![],
            next_cursor: None,
            active_turn_id: None,
        },
    };
    assert_eq!(response.validate_for(&request), Ok(()));
    response.connection_generation = 2;
    assert!(response.validate_for(&request).is_err());
    response.connection_generation = 1;
    response.session_id = "different".into();
    assert!(response.validate_for(&request).is_err());
    response.session_id = request.session_id.clone();
    response.result = ChatResult::Conversation {
        data: ChatConversation {
            id: "thread-1".into(),
            title: String::new(),
            preview: String::new(),
        },
    };
    assert!(response.validate_for(&request).is_err());
    response.result = ChatResult::Timeline {
        thread_id: "wrong".into(),
        data: vec![],
        next_cursor: None,
        active_turn_id: None,
    };
    assert!(response.validate_for(&request).is_err());
    let message = ChatMessage {
        id: "m".into(),
        turn_id: "t".into(),
        sender: "assistant".into(),
        body: "hi".into(),
    };
    response.result = ChatResult::Timeline {
        thread_id: "thread-1".into(),
        data: vec![message.clone(), message],
        next_cursor: None,
        active_turn_id: None,
    };
    assert!(response.validate_for(&request).is_err());
}
