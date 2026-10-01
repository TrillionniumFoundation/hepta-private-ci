use super::*;
use pretty_assertions::assert_eq;

const BODY: &[u8] = br#"{"model":"gpt-5.6-sol","stream":true,"store":false,"input":[]}"#;

#[tokio::test]
async fn fragmented_real_unix_request_preserves_exact_wire_body() {
    let (mut client, mut server) = UnixStream::pair().unwrap();
    let writer = tokio::spawn(async move {
        let header = format!(
            "POST {REQUEST_PATH} HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n",
            BODY.len()
        );
        for part in header.as_bytes().chunks(3).chain(BODY.chunks(2)) {
            client.write_all(part).await.unwrap();
            tokio::task::yield_now().await;
        }
        client.shutdown().await.unwrap();
    });
    let request = read_request(&mut server).await.unwrap();
    writer.await.unwrap();
    assert_eq!(request.body, BODY);
    assert_eq!(request.model, "gpt-5.6-sol");
}

#[test]
fn rejects_ambiguous_framing_and_foreign_routes() {
    for header in [
        "POST /hepta/v1/responses HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: 2\r\nContent-Length: 3\r\n\r\n",
        "POST /hepta/v1/responses HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n",
        "POST /responses HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\n\r\n",
    ] {
        assert!(parse_headers(header.as_bytes()).is_err());
    }
}

#[tokio::test]
async fn exact_length_rejects_short_noncanonical_and_pipelined_input() {
    for (length, body) in [
        ("02", b"{}".as_slice()),
        ("3", b"{}"),
        ("1", b"{}POST /next"),
    ] {
        let (mut client, mut server) = UnixStream::pair().unwrap();
        let header = format!(
            "POST {REQUEST_PATH} HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: {length}\r\n\r\n"
        );
        client.write_all(header.as_bytes()).await.unwrap();
        client.write_all(body).await.unwrap();
        client.shutdown().await.unwrap();
        assert!(read_request(&mut server).await.is_err());
    }
}

#[test]
fn rejects_ambiguous_admission_and_persisted_or_nonstreaming_requests() {
    let headers = BTreeMap::new();
    for body in [
        br#"{"model":"gpt-5.6-sol","model":"other","stream":true,"store":false,"input":[]}"#
            .as_slice(),
        br#"{"model":"gpt-5.6-sol","stream":false,"store":false,"input":[]}"#,
        br#"{"model":"gpt-5.6-sol","stream":true,"store":true,"input":[]}"#,
    ] {
        assert!(inspect_body(body, &headers).is_err());
    }
    assert_eq!(inspect_body(BODY, &headers).unwrap(), "gpt-5.6-sol");
}

#[test]
fn compressed_requests_keep_wire_digest_and_enforce_decoded_bound() {
    let headers = BTreeMap::from([("content-encoding".to_owned(), "zstd".to_owned())]);
    let compressed = zstd::stream::encode_all(BODY, 1).unwrap();
    assert_eq!(inspect_body(&compressed, &headers).unwrap(), "gpt-5.6-sol");
    let oversized = vec![b' '; MAX_DECOMPRESSED_BYTES + 1];
    let compressed = zstd::stream::encode_all(oversized.as_slice(), 1).unwrap();
    assert!(inspect_body(&compressed, &headers).is_err());
}

#[tokio::test]
async fn real_reqwest_unix_transport_receives_chunked_sse_without_private_headers() {
    let directory = tempfile::tempdir().unwrap();
    let socket = directory.path().join("model.sock");
    let listener = tokio::net::UnixListener::bind(&socket).unwrap();
    let owner = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let request = read_request(&mut stream).await.unwrap();
        assert_eq!(request.body, BODY);
        assert!(!request.headers.contains_key("authorization"));
        let headers = HeaderMap::from_iter([
            (
                reqwest::header::CONTENT_TYPE,
                reqwest::header::HeaderValue::from_static("text/event-stream"),
            ),
            (
                reqwest::header::SET_COOKIE,
                reqwest::header::HeaderValue::from_static("private-account=secret"),
            ),
        ]);
        start_response(&mut stream, 200, &headers).await.unwrap();
        chunk(&mut stream, b"data: {\"type\":\"response.created\"}\n\n")
            .await
            .unwrap();
        chunk(&mut stream, b"data: {\"type\":\"response.completed\"}\n\n")
            .await
            .unwrap();
        finish(&mut stream).await.unwrap();
    });
    let response = reqwest::Client::builder()
        .unix_socket(socket)
        .no_proxy()
        .build()
        .unwrap()
        .post("http://localhost/hepta/v1/responses")
        .header("content-type", "application/json")
        .body(BODY.to_vec())
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    assert!(!response.headers().contains_key("set-cookie"));
    assert_eq!(
        response.text().await.unwrap(),
        "data: {\"type\":\"response.created\"}\n\ndata: {\"type\":\"response.completed\"}\n\n"
    );
    owner.await.unwrap();
}
