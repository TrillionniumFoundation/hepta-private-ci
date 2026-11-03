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
    stream_with_body_at_limit(body, 4096).await
}

async fn stream_with_body_at_limit(body: &str, max_stream_bytes: usize) -> Result<ResponsesStream> {
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
        max_stream_bytes,
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

#[tokio::test]
async fn changed_delta_item_and_forged_final_text_cannot_complete() -> Result<()> {
    for changed_identity in [false, true] {
        let mut events = vec![
            json!({"type":"response.created","response":{"id":"resp-1"}}),
            json!({"type":"response.output_item.added","output_index":0,
                "item":{"type":"message","role":"assistant","id":"msg-original","content":[]}}),
            json!({"type":"response.output_text.delta","output_index":0,"content_index":0,
                "item_id":if changed_identity { "msg-other" } else { "msg-original" },"delta":"细胞"}),
        ];
        let final_item = json!({"type":"message","role":"assistant","id":"msg-original",
            "content":[{"type":"output_text","text":"different final text"}]});
        events.push(json!({"type":"response.output_item.done","output_index":0,"item":final_item}));
        let body: String = events
            .into_iter()
            .map(|event| format!("data: {event}\n\n"))
            .collect();
        let mut stream = stream_with_body(&body).await?;
        assert!(matches!(stream.next().await?, Some(ModelEvent::Created(_))));
        if !changed_identity {
            let Some(ModelEvent::TextDelta(delta)) = stream.next().await? else {
                bail!("delta missing");
            };
            assert_eq!(delta.text, "细胞");
            assert_eq!(delta.output_index, 0);
        }
        assert!(stream.next().await.is_err());
    }
    Ok(())
}

#[tokio::test]
async fn recorded_late_phase_stream_preserves_items_and_completes() -> Result<()> {
    let mut stream = stream_with_body_at_limit(RECORDED_LATE_PHASE_SSE, 32 * 1024).await?;
    let response_id = "resp_6kLkrbv85JxhIrO4fVxDk88es1OzOc0W";
    assert_eq!(
        stream.next().await?,
        Some(ModelEvent::Created(response_id.to_owned()))
    );
    let mut text = String::new();
    let mut deltas = 0;
    let mut items = Vec::new();
    let mut completed = false;
    while let Some(event) = stream.next().await? {
        match event {
            ModelEvent::TextDelta(delta) => {
                assert!(items.is_empty());
                assert_eq!(delta.response_id, response_id);
                assert_eq!(delta.item_id, "msg_DbgCXlRsjTEBWuoQkxZ6GDFIGp4fwJM2");
                assert_eq!((delta.output_index, delta.content_index), (1, 0));
                assert_eq!(delta.phase, None);
                text.push_str(&delta.text);
                deltas += 1;
            }
            ModelEvent::Item(item) => items.push(item),
            ModelEvent::Completed {
                response_id: id,
                usage,
            } => {
                assert_eq!(id, response_id);
                assert_eq!(items.len(), 2);
                assert_eq!(usage["input_tokens"], 2033);
                assert_eq!(usage["output_tokens"], 46);
                completed = true;
            }
            ModelEvent::Created(_) => bail!("recording created a second response"),
        }
    }
    assert!(completed);
    assert_eq!(deltas, 7);
    assert_eq!(text, "HEPTA_REPRESENTATIVE_OK");
    assert_eq!(items[0]["type"], "reasoning");
    assert_eq!(items[0]["id"], "rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE");
    assert_eq!(items[1]["id"], "msg_DbgCXlRsjTEBWuoQkxZ6GDFIGp4fwJM2");
    assert_eq!(items[1]["phase"], "final_answer");
    assert_eq!(items[1]["content"][0]["text"], text);
    Ok(())
}

#[tokio::test]
async fn optional_phase_refines_once_without_conflict_or_erasure() -> Result<()> {
    for (name, added_phase, delta_phase, completed_phase, accepted) in [
        (
            "late_delta",
            None,
            Some("final_answer"),
            Some("final_answer"),
            true,
        ),
        ("legacy_unknown", None, None, None, true),
        (
            "known_phase_omitted_on_deltas",
            Some("final_answer"),
            None,
            Some("final_answer"),
            true,
        ),
        (
            "delta_conflict",
            Some("commentary"),
            Some("final_answer"),
            Some("commentary"),
            false,
        ),
        (
            "completion_conflict",
            Some("commentary"),
            None,
            Some("final_answer"),
            false,
        ),
        (
            "latched_phase_conflict",
            None,
            Some("final_answer"),
            Some("commentary"),
            false,
        ),
        (
            "known_phase_erasure",
            Some("final_answer"),
            None,
            None,
            false,
        ),
        (
            "latched_phase_erasure",
            None,
            Some("final_answer"),
            None,
            false,
        ),
        (
            "unsupported_late_phase",
            None,
            None,
            Some("unsupported"),
            false,
        ),
    ] {
        let item = json!({"type":"message","role":"assistant","id":"msg-phase",
            "phase":completed_phase,"content":[{"type":"output_text","text":"细胞"}]});
        let body: String = [
            json!({"type":"response.created","response":{"id":"resp-phase"}}),
            json!({"type":"response.output_item.added","output_index":0,
                "item":{"type":"message","role":"assistant","id":"msg-phase",
                    "phase":added_phase,"content":[]}}),
            json!({"type":"response.output_text.delta","output_index":0,"content_index":0,
                "item_id":"msg-phase","delta":"细","phase":delta_phase}),
            json!({"type":"response.output_text.delta","output_index":0,"content_index":0,
                "item_id":"msg-phase","delta":"胞"}),
            json!({"type":"response.output_item.done","output_index":0,"item":item}),
            json!({"type":"response.completed","response":{
                "id":"resp-phase","status":"completed","output":[item]}}),
        ]
        .into_iter()
        .map(|event| format!("data: {event}\n\n"))
        .collect();
        let mut stream = stream_with_body(&body).await?;
        let mut phases = Vec::new();
        let mut completed = false;
        let failure = loop {
            match stream.next().await {
                Ok(Some(ModelEvent::TextDelta(delta))) => phases.push(delta.phase),
                Ok(Some(ModelEvent::Completed { .. })) => completed = true,
                Ok(Some(_)) => {}
                Ok(None) => break None,
                Err(error) => break Some(error),
            }
        };
        assert_eq!(failure.is_none(), accepted, "{name}: {failure:?}");
        assert_eq!(completed, accepted, "{name}");
        if accepted {
            let expected = delta_phase.or(added_phase).map(str::to_owned);
            assert_eq!(phases, vec![expected.clone(), expected], "{name}");
        } else {
            assert!(failure.unwrap().to_string().contains("phase"), "{name}");
        }
    }
    Ok(())
}

#[tokio::test]
async fn recorded_late_phase_rejects_changed_identity_and_terminal_phase() -> Result<()> {
    for mutation in [
        "done_identity",
        "terminal_item_identity",
        "terminal_item_phase",
    ] {
        let mut decoder = SseDecoder::new(32 * 1024);
        decoder.push(RECORDED_LATE_PHASE_SSE.as_bytes())?;
        let mut events = Vec::new();
        while let Some(mut event) = decoder.pop()? {
            if mutation == "done_identity"
                && event["type"] == "response.output_item.done"
                && event["item"]["type"] == "message"
            {
                event["item"]["id"] = json!("msg-replaced");
            }
            if event["type"] == "response.completed" {
                match mutation {
                    "terminal_item_identity" => {
                        event["response"]["output"][1]["id"] = json!("msg-replaced")
                    }
                    "terminal_item_phase" => {
                        event["response"]["output"][1]["phase"] = json!("commentary")
                    }
                    _ => {}
                }
            }
            events.push(event);
        }
        let body: String = events
            .into_iter()
            .map(|event| format!("data: {event}\n\n"))
            .collect();
        let mut stream = stream_with_body_at_limit(&body, 32 * 1024).await?;
        loop {
            match stream.next().await {
                Err(error) => {
                    let expected = if mutation == "done_identity" {
                        "completed item differs from the streamed message identity or phase"
                    } else {
                        "terminal output differs from the actual streamed output items"
                    };
                    assert_eq!(error.to_string(), expected, "{mutation}");
                    break;
                }
                Ok(None | Some(ModelEvent::Completed { .. })) => {
                    bail!("{mutation} was accepted as a terminal response")
                }
                Ok(Some(_)) => {}
            }
        }
    }
    Ok(())
}

// Exact observed-live native 00-edit response 04; 14,231 bytes.
// SHA256: 9bc36f9bf2e6f245fe9710b776fea2267aa2a5aca1884e216d8dda425bebed6a
// Embedded to avoid an external compile_data dependency in test builds.
pub(crate) const RECORDED_LATE_PHASE_SSE: &str = r####"event: response.created
data: {"type":"response.created","response":{"id":"resp_6kLkrbv85JxhIrO4fVxDk88es1OzOc0W","object":"response","status":"in_progress","created_at":1793425442,"model":"qwen38-flash-next-uc","output":[],"error":null,"incomplete_details":null,"store":false,"previous_response_id":null},"sequence_number":0}

event: response.in_progress
data: {"type":"response.in_progress","response":{"id":"resp_6kLkrbv85JxhIrO4fVxDk88es1OzOc0W","object":"response","status":"in_progress","created_at":1793425442,"model":"qwen38-flash-next-uc","output":[],"error":null,"incomplete_details":null,"store":false,"previous_response_id":null},"sequence_number":1}

event: response.output_item.added
data: {"type":"response.output_item.added","output_index":0,"item":{"id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","summary":[{"type":"summary_text","text":""}],"type":"reasoning","content":[],"encrypted_content":"","status":"in_progress"},"sequence_number":2}

event: response.reasoning_summary_part.added
data: {"type":"response.reasoning_summary_part.added","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"part":{"type":"summary_text","text":""},"sequence_number":3}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":"Since","sequence_number":4}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":" no","sequence_number":5}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":" errors","sequence_number":6}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":" were","sequence_number":7}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":" raised","sequence_number":8}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":",","sequence_number":9}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":" we","sequence_number":10}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":" can","sequence_number":11}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":" consider","sequence_number":12}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":" the","sequence_number":13}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":" test","sequence_number":14}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":" to","sequence_number":15}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":" have","sequence_number":16}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":" passed","sequence_number":17}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":".","sequence_number":18}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":" We","sequence_number":19}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":" should","sequence_number":20}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":" continue","sequence_number":21}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":" working","sequence_number":22}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":" toward","sequence_number":23}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":" the","sequence_number":24}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":" objective","sequence_number":25}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":" of","sequence_number":26}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":" \"","sequence_number":27}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":"return","sequence_number":28}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":"ing","sequence_number":29}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":" exactly","sequence_number":30}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":" HE","sequence_number":31}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":"PT","sequence_number":32}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":"A","sequence_number":33}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":"_RE","sequence_number":34}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":"PRESENT","sequence_number":35}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":"ATIVE","sequence_number":36}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":"_OK","sequence_number":37}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":"\".","sequence_number":38}

event: response.reasoning_summary_text.delta
data: {"type":"response.reasoning_summary_text.delta","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"delta":"\n","sequence_number":39}

event: response.output_item.added
data: {"type":"response.output_item.added","output_index":1,"item":{"content":[{"type":"output_text","text":"","annotations":[]}],"id":"msg_DbgCXlRsjTEBWuoQkxZ6GDFIGp4fwJM2","role":"assistant","status":"in_progress","type":"message"},"sequence_number":40}

event: response.content_part.added
data: {"type":"response.content_part.added","item_id":"msg_DbgCXlRsjTEBWuoQkxZ6GDFIGp4fwJM2","output_index":1,"content_index":0,"part":{"type":"output_text","text":"","annotations":[]},"sequence_number":41}

event: response.output_text.delta
data: {"type":"response.output_text.delta","item_id":"msg_DbgCXlRsjTEBWuoQkxZ6GDFIGp4fwJM2","output_index":1,"content_index":0,"delta":"HE","logprobs":[],"sequence_number":42}

event: response.output_text.delta
data: {"type":"response.output_text.delta","item_id":"msg_DbgCXlRsjTEBWuoQkxZ6GDFIGp4fwJM2","output_index":1,"content_index":0,"delta":"PT","logprobs":[],"sequence_number":43}

event: response.output_text.delta
data: {"type":"response.output_text.delta","item_id":"msg_DbgCXlRsjTEBWuoQkxZ6GDFIGp4fwJM2","output_index":1,"content_index":0,"delta":"A","logprobs":[],"sequence_number":44}

event: response.output_text.delta
data: {"type":"response.output_text.delta","item_id":"msg_DbgCXlRsjTEBWuoQkxZ6GDFIGp4fwJM2","output_index":1,"content_index":0,"delta":"_RE","logprobs":[],"sequence_number":45}

event: response.output_text.delta
data: {"type":"response.output_text.delta","item_id":"msg_DbgCXlRsjTEBWuoQkxZ6GDFIGp4fwJM2","output_index":1,"content_index":0,"delta":"PRESENT","logprobs":[],"sequence_number":46}

event: response.output_text.delta
data: {"type":"response.output_text.delta","item_id":"msg_DbgCXlRsjTEBWuoQkxZ6GDFIGp4fwJM2","output_index":1,"content_index":0,"delta":"ATIVE","logprobs":[],"sequence_number":47}

event: response.output_text.delta
data: {"type":"response.output_text.delta","item_id":"msg_DbgCXlRsjTEBWuoQkxZ6GDFIGp4fwJM2","output_index":1,"content_index":0,"delta":"_OK","logprobs":[],"sequence_number":48}

event: response.reasoning_summary_text.done
data: {"type":"response.reasoning_summary_text.done","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"text":"Since no errors were raised, we can consider the test to have passed. We should continue working toward the objective of \"returning exactly HEPTA_REPRESENTATIVE_OK\".\n","sequence_number":49}

event: response.reasoning_summary_part.done
data: {"type":"response.reasoning_summary_part.done","item_id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","output_index":0,"summary_index":0,"part":{"type":"summary_text","text":"Since no errors were raised, we can consider the test to have passed. We should continue working toward the objective of \"returning exactly HEPTA_REPRESENTATIVE_OK\".\n"},"sequence_number":50}

event: response.output_item.done
data: {"type":"response.output_item.done","output_index":0,"item":{"id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","summary":[{"type":"summary_text","text":"Since no errors were raised, we can consider the test to have passed. We should continue working toward the objective of \"returning exactly HEPTA_REPRESENTATIVE_OK\".\n"}],"type":"reasoning","content":[],"encrypted_content":"","status":"completed"},"sequence_number":51}

event: response.output_text.done
data: {"type":"response.output_text.done","item_id":"msg_DbgCXlRsjTEBWuoQkxZ6GDFIGp4fwJM2","output_index":1,"content_index":0,"text":"HEPTA_REPRESENTATIVE_OK","logprobs":[],"sequence_number":52}

event: response.content_part.done
data: {"type":"response.content_part.done","item_id":"msg_DbgCXlRsjTEBWuoQkxZ6GDFIGp4fwJM2","output_index":1,"content_index":0,"part":{"type":"output_text","text":"HEPTA_REPRESENTATIVE_OK","annotations":[]},"sequence_number":53}

event: response.output_item.done
data: {"type":"response.output_item.done","output_index":1,"item":{"content":[{"type":"output_text","text":"HEPTA_REPRESENTATIVE_OK","annotations":[]}],"id":"msg_DbgCXlRsjTEBWuoQkxZ6GDFIGp4fwJM2","role":"assistant","status":"completed","type":"message","phase":"final_answer"},"sequence_number":54}

event: response.completed
data: {"type":"response.completed","response":{"id":"resp_6kLkrbv85JxhIrO4fVxDk88es1OzOc0W","object":"response","status":"completed","created_at":1793425443,"model":"qwen38-flash-next-uc","output":[{"id":"rs_kVdEE9h8gdz7arw0QRDCMyI4yfBs51eE","summary":[{"type":"summary_text","text":"Since no errors were raised, we can consider the test to have passed. We should continue working toward the objective of \"returning exactly HEPTA_REPRESENTATIVE_OK\".\n"}],"type":"reasoning","content":[],"encrypted_content":"","status":"completed"},{"content":[{"type":"output_text","text":"HEPTA_REPRESENTATIVE_OK","annotations":[]}],"id":"msg_DbgCXlRsjTEBWuoQkxZ6GDFIGp4fwJM2","role":"assistant","status":"completed","type":"message","phase":"final_answer"}],"error":null,"incomplete_details":null,"store":false,"previous_response_id":null,"usage":{"input_tokens":2033,"output_tokens":46,"total_tokens":2079,"input_tokens_details":{"cached_tokens":1985}}},"sequence_number":55}

"####;
