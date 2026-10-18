#![allow(clippy::expect_used, clippy::unwrap_used)]

use super::*;

async fn parse_frame(bytes: Vec<u8>) -> Result<NativeChatRootRequest> {
    let (mut writer, mut reader) = UnixStream::pair()?;
    let write = tokio::spawn(async move {
        writer.write_all(&bytes).await?;
        writer.shutdown().await
    });
    let result = read_request(&mut reader).await;
    // Oversized requests intentionally close without consuming the tail.
    drop(reader);
    let _ = write.await?;
    result
}

fn request() -> NativeChatRootRequest {
    NativeChatRootRequest::Attach {
        binding: NativeChatBinding {
            agent_id: "00000000-0000-4000-8000-000000000001".into(),
            supervisor_process_id: 10,
            agent_process_id: 11,
            control_fence: serde_json::json!({}),
        },
        session_id: "native-frame-session".into(),
    }
}

#[tokio::test]
async fn finite_frame_requires_exact_eof_including_buffered_tail() -> Result<()> {
    let expected = request();
    let mut bytes = serde_json::to_vec(&expected)?;
    bytes.push(b'\n');
    assert_eq!(parse_frame(bytes.clone()).await?, expected);
    bytes.extend_from_slice(b"{}\n");
    assert!(parse_frame(bytes).await.is_err());
    Ok(())
}

#[tokio::test]
async fn finite_frame_rejects_unterminated_and_oversized_input() -> Result<()> {
    assert!(parse_frame(serde_json::to_vec(&request())?).await.is_err());
    let mut bytes = vec![b' '; MAX_NATIVE_CHAT_REQUEST_BYTES];
    bytes.push(b'\n');
    assert!(parse_frame(bytes).await.is_err());
    Ok(())
}
