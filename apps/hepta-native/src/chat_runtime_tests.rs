use super::*;
use std::io::Cursor;
fn request() -> ChatRequest {
    ChatRequest {
        session_id: "s".into(),
        connection_generation: 2,
        command: ChatCommand::List {
            cursor: None,
            limit: 5,
        },
    }
}
fn response() -> ChatResponse {
    ChatResponse {
        session_id: "s".into(),
        connection_generation: 2,
        approval_required: false,
        result: ChatResult::Conversations {
            data: vec![],
            next_cursor: None,
        },
    }
}
fn encoded(value: ChatResponse) -> Vec<u8> {
    let mut bytes = serde_json::to_vec(&serde_json::json!({"response":value})).unwrap();
    bytes.push(b'\n');
    bytes
}
#[test]
fn stdio_roundtrip_is_exact_and_line_delimited() {
    let mut written = vec![];
    assert_eq!(
        exchange(
            &mut written,
            &mut Cursor::new(encoded(response())),
            &request()
        ),
        Ok(response())
    );
    assert_eq!(written.last(), Some(&b'\n'));
    assert_eq!(
        serde_json::from_slice::<ChatRequest>(&written).unwrap(),
        request()
    );
}
#[test]
fn stale_generation_or_wrong_session_cannot_publish() {
    let mut stale = response();
    stale.connection_generation = 3;
    assert!(exchange(&mut vec![], &mut Cursor::new(encoded(stale)), &request()).is_err());
    let mut stale = response();
    stale.session_id = "different".into();
    assert!(exchange(&mut vec![], &mut Cursor::new(encoded(stale)), &request()).is_err());
}
#[test]
fn eof_partial_error_and_oversized_frames_fail_closed() {
    for bytes in [
        vec![],
        b"{}".to_vec(),
        b"{\"error\":\"failed\"}\n".to_vec(),
        vec![b'x'; MAX_CHAT_FRAME_BYTES + 1],
    ] {
        assert!(exchange(&mut vec![], &mut Cursor::new(bytes), &request()).is_err());
    }
}
