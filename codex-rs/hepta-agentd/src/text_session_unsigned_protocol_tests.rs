//! Credential-bound Unix protocol fixtures, not a deployed human Root owner.
use super::*;

fn endpoint(socket_path: PathBuf) -> TextSignerEndpoint {
    TextSignerEndpoint {
        socket_path,
        owner_uid: unsafe { libc::geteuid() },
        owner_pid: std::process::id(),
    }
}

#[tokio::test]
async fn only_prewrite_failures_prove_non_transmission() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("phase.sock");
    let missing = signed_input(
        &endpoint(path.clone()),
        &owner().route,
        "text:human-scope:3",
        "text",
        false,
    )
    .await;
    assert!(matches!(missing, Err(TextSessionError::NotTransmitted(_))));
    let listener = tokio::net::UnixListener::bind(&path).unwrap();
    let rejected_peer = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let mut byte = [0];
        assert_eq!(stream.read(&mut byte).await.unwrap(), 0);
    });
    let mut wrong = endpoint(path);
    wrong.owner_pid += 1;
    assert!(matches!(
        signed_input(&wrong, &owner().route, "text:human-scope:3", "text", false).await,
        Err(TextSessionError::NotTransmitted(_))
    ));
    rejected_peer.await.unwrap();

    let path = directory.path().join("received.sock");
    let listener = tokio::net::UnixListener::bind(&path).unwrap();
    let received = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let size = stream.read_u32().await.unwrap() as usize;
        let mut bytes = vec![0; size];
        stream.read_exact(&mut bytes).await.unwrap();
        let request: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
        assert_eq!(request["operation"], "sign");
        // Unknown response: a real Root may already have committed the original.
    });
    assert!(matches!(
        signed_input(
            &endpoint(path),
            &owner().route,
            "text:human-scope:3",
            "text",
            false
        )
        .await,
        Err(TextSessionError::Unavailable(_))
    ));
    received.await.unwrap();
}

fn closed_outcome(through_sequence: u64, text: &str) -> TextUnsignedClosure {
    let body = crate::AuthBusTextBody {
        spawn_generation: 2,
        thread_id: "original-thread".into(),
        text: text.into(),
    };
    TextUnsignedClosure::Closed {
        through_sequence,
        payload_sha256: *codex_hepta_types::Digest32::of_bytes(
            &crate::authbus_ingress::payload(&body).unwrap(),
        )
        .as_array(),
    }
}

#[tokio::test]
async fn lost_close_reply_stays_unknown_until_matching_original_closure_proof() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("close.sock");
    let listener = tokio::net::UnixListener::bind(&path).unwrap();
    let server =
        tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();
            let size = stream.read_u32().await.unwrap() as usize;
            let mut bytes = vec![0; size];
            stream.read_exact(&mut bytes).await.unwrap();
            let lost: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
            drop(stream);
            let retry = response(&listener, serde_json::json!({
            "schema_version":1,"operation":"close_unsigned","request_id":"text:human-scope:3",
            "outcome":closed_outcome(3, "same input"),
        })).await;
            assert_eq!(lost, retry);
            assert_eq!(retry["operation"], "close_unsigned");
        });
    let endpoint = endpoint(path);
    assert!(matches!(
        close_unsigned(
            &endpoint,
            &owner().route,
            "text:human-scope:3",
            "same input"
        )
        .await,
        Err(TextSessionError::Unavailable(_))
    ));
    assert_eq!(
        close_unsigned(
            &endpoint,
            &owner().route,
            "text:human-scope:3",
            "same input"
        )
        .await
        .unwrap(),
        closed_outcome(3, "same input")
    );
    server.await.unwrap();
}

#[tokio::test]
async fn unsigned_closure_rejects_wrong_payload_watermark_and_preserves_a_retained_old_generation()
{
    for outcome in [
        closed_outcome(2, "same input"),
        closed_outcome(3, "different input"),
    ] {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("invalid.sock");
        let listener = tokio::net::UnixListener::bind(&path).unwrap();
        let server = tokio::spawn(async move {
            response(&listener, serde_json::json!({
            "schema_version":1,"operation":"close_unsigned","request_id":"text:human-scope:3","outcome":outcome,
        })).await;
        });
        assert!(matches!(
            close_unsigned(
                &endpoint(path),
                &owner().route,
                "text:human-scope:3",
                "same input"
            )
            .await,
            Err(TextSessionError::Identity)
        ));
        server.await.unwrap();
    }
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("retained.sock");
    let listener = tokio::net::UnixListener::bind(&path).unwrap();
    let original: AuthBusTextIngress =
        serde_json::from_value(entry("text:human-scope", 3)["envelope"].clone()).unwrap();
    let expected = original.clone();
    let server =
        tokio::spawn(async move {
            response(&listener, serde_json::json!({
        "schema_version":1,"operation":"close_unsigned","request_id":"text:human-scope:3",
        "outcome":TextUnsignedClosure::Retained { envelope: original },
    })).await;
        });
    assert_eq!(
        close_unsigned(
            &endpoint(path),
            &owner().route,
            "text:human-scope:3",
            &expected.body.text
        )
        .await
        .unwrap(),
        TextUnsignedClosure::Retained { envelope: expected }
    );
    server.await.unwrap();
}
