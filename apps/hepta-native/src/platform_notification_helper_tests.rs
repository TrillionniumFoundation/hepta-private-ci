use super::*;
use std::io::Cursor;

fn readiness(digest: &str, nonce: &str) -> Vec<u8> {
    let mut bytes = serde_json::to_vec(&Ready {
        schema: READY_SCHEMA.into(),
        binary_digest: digest.into(),
        nonce: nonce.into(),
    })
    .unwrap();
    bytes.push(b'\n');
    bytes
}

#[test]
fn notification_handoff_binds_nonce_binary_and_literal_payload() {
    let digest = "a".repeat(64);
    let nonce = "b".repeat(64);
    let mut output = Vec::new();
    exchange_request(
        &mut output,
        Cursor::new(readiness(&digest, &nonce)),
        digest,
        "标题 & <literal>".into(),
        "line 1\nline 2 \"quoted\"".into(),
    )
    .unwrap();
    let request: NotificationRequest = serde_json::from_slice(&output).unwrap();
    assert_eq!(
        request,
        NotificationRequest {
            schema: REQUEST_SCHEMA.into(),
            nonce,
            title: "标题 & <literal>".into(),
            body: "line 1\nline 2 \"quoted\"".into(),
        }
    );
}

#[test]
fn notification_handoff_rejects_wrong_image_before_sending_data() {
    let mut output = Vec::new();
    assert!(
        exchange_request(
            &mut output,
            Cursor::new(readiness(&"a".repeat(64), &"b".repeat(64))),
            "c".repeat(64),
            "private title".into(),
            "private body".into(),
        )
        .is_err()
    );
    assert!(output.is_empty());
}

#[test]
fn notification_handoff_rejects_unbounded_incomplete_and_invalid_ready() {
    for bytes in [
        vec![b'x'; 1025],
        b"{}".to_vec(),
        b"{}\n".to_vec(),
        readiness(&"a".repeat(64), "wrong"),
    ] {
        let mut output = Vec::new();
        assert!(
            exchange_request(
                &mut output,
                Cursor::new(bytes),
                "a".repeat(64),
                "title".into(),
                "body".into()
            )
            .is_err()
        );
        assert!(output.is_empty());
    }
}

#[test]
fn notification_helper_rejects_nonce_mismatch_oversized_text_and_unknown_fields() {
    let mut request = NotificationRequest {
        schema: REQUEST_SCHEMA.into(),
        nonce: "b".repeat(64),
        title: "title".into(),
        body: "body".into(),
    };
    assert!(request.validate(&"c".repeat(64)).is_err());
    request.body = "x".repeat(crate::model::MAX_NOTIFICATION_BODY_BYTES + 1);
    assert!(request.validate(&request.nonce).is_err());
    let mut value = serde_json::to_value(&request).unwrap();
    value["command"] = "unrelated effect".into();
    assert!(serde_json::from_value::<NotificationRequest>(value).is_err());
}

#[cfg(unix)]
#[test]
fn inherited_notification_stdout_cannot_extend_readiness_deadline() {
    let mut command = Command::new("/bin/sh");
    command.args(["-c", "sleep 1.5 & exit 0"]);
    let active = Arc::new(AtomicUsize::new(0));
    let started = Instant::now();
    assert!(
        run_process(
            command,
            &"a".repeat(64),
            "title",
            "body",
            &active,
            std::time::Duration::from_millis(30)
        )
        .is_err()
    );
    assert!(started.elapsed() < std::time::Duration::from_millis(750));
    assert_eq!(active.load(std::sync::atomic::Ordering::Acquire), 0);
}

#[cfg(unix)]
#[test]
fn notification_writer_cannot_block_when_descendant_holds_unread_stdin() {
    let digest = "a".repeat(64);
    let ready = String::from_utf8(readiness(&digest, &"b".repeat(64))).unwrap();
    let script = format!("printf '%s' '{}'; sleep 1.5 & sleep 1.5", ready);
    let mut command = Command::new("/bin/sh");
    command.args(["-c", &script]);
    let active = Arc::new(AtomicUsize::new(0));
    let started = Instant::now();
    assert!(
        run_process(
            command,
            &digest,
            "title",
            &"\u{1}".repeat(4096),
            &active,
            std::time::Duration::from_millis(30)
        )
        .is_err()
    );
    assert!(started.elapsed() < std::time::Duration::from_millis(750));
    assert_eq!(active.load(std::sync::atomic::Ordering::Acquire), 0);
}
