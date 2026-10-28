//! Stream framing and interruption regressions for the bounded model transport.

use super::*;
use codex_http_client::OutboundProxyPolicy;
use pretty_assertions::assert_eq;
use serde_json::json;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::TcpListener;

#[test]
fn fragmented_utf8_crlf_and_multiline_frames_preserve_values() -> Result<()> {
    let mut decoder = SseDecoder::new(4096);
    let wire = ": keepalive\r\n\r\ndata: {\"type\":\"response.output_text.delta\",\r\ndata: \"delta\":\"细胞\"}\r\n\r\n";
    for byte in wire.as_bytes() {
        decoder.push(&[*byte])?;
    }
    assert_eq!(
        decoder.pop()?,
        Some(json!({"type":"response.output_text.delta","delta":"细胞"}))
    );
    assert_eq!(decoder.pop()?, None);
    Ok(())
}

#[test]
fn incomplete_frame_is_bounded_before_json_parsing() -> Result<()> {
    let mut decoder = SseDecoder::new(32);
    decoder.push(b"data: ")?;
    assert!(decoder.push(&[b'a'; 27]).is_err());
    Ok(())
}

async fn stream_with_body(body: &str) -> Result<ResponsesStream> {
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let address = listener.local_addr()?;
    let body = body.to_owned();
    tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await?;
        let mut input = [0_u8; 4096];
        let _ = socket.read(&mut input).await?;
        let response = format!(
            "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
            body.len()
        );
        socket.write_all(response.as_bytes()).await?;
        socket.shutdown().await
    });
    ResponsesModel::new(
        &HttpClientFactory::new(OutboundProxyPolicy::ReqwestDefault),
        format!("http://{address}/v1/responses"),
        None,
        Duration::from_secs(2),
        4096,
    )?
    .open(&ModelRequest {
        operation_id: "original-model-operation".to_owned(),
        body: b"{}".to_vec(),
    })
    .await
}

#[tokio::test]
async fn eof_after_a_tool_proposal_is_never_model_completion() -> Result<()> {
    let body = concat!(
        "data: {\"type\":\"response.created\",\"response\":{\"id\":\"resp-1\"}}\n\n",
        "data: {\"type\":\"response.output_item.done\",\"item\":{\"type\":\"function_call\",\"call_id\":\"call-1\",\"name\":\"tool\",\"arguments\":\"{}\"}}\n\n"
    );
    let mut stream = stream_with_body(body).await?;
    assert_eq!(
        stream.next().await?,
        Some(ModelEvent::Created("resp-1".to_owned()))
    );
    assert!(matches!(stream.next().await?, Some(ModelEvent::Item(_))));
    assert!(stream.next().await.is_err());
    Ok(())
}

#[tokio::test]
async fn changed_terminal_response_identity_is_rejected() -> Result<()> {
    let body = concat!(
        "data: {\"type\":\"response.created\",\"response\":{\"id\":\"resp-1\"}}\n\n",
        "data: {\"type\":\"response.completed\",\"response\":{\"id\":\"resp-2\",\"status\":\"completed\"}}\n\n"
    );
    let mut stream = stream_with_body(body).await?;
    let _ = stream.next().await?;
    assert!(stream.next().await.is_err());
    Ok(())
}
