//! One bounded HTTP/1.1 exchange per authenticated Unix connection.
//! Request smuggling, arbitrary routes and response-header credential leaks
//! are rejected; streaming backpressure stays on the original socket.

use std::collections::BTreeMap;
use std::io::Read;

use anyhow::Context;
use reqwest::header::HeaderMap;
use serde::Deserialize;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::UnixStream;

pub(super) const REQUEST_PATH: &str = "/hepta/v1/responses";
const MAX_HEADER_BYTES: usize = 16 * 1024;
const MAX_BODY_BYTES: usize = 4 * 1024 * 1024;
const MAX_DECOMPRESSED_BYTES: usize = 8 * 1024 * 1024;
pub(super) const MAX_RESPONSE_BYTES: usize = 64 * 1024 * 1024;

pub(super) struct Request {
    pub body: Vec<u8>,
    pub headers: BTreeMap<String, String>,
    pub model: String,
}

pub(super) async fn read_request(stream: &mut UnixStream) -> anyhow::Result<Request> {
    let mut prefix = Vec::new();
    let mut buffer = [0_u8; 2048];
    let header_end = loop {
        let count = stream.read(&mut buffer).await?;
        anyhow::ensure!(count != 0, "incomplete model relay headers");
        prefix.extend_from_slice(&buffer[..count]);
        if let Some(index) = prefix.windows(4).position(|bytes| bytes == b"\r\n\r\n") {
            anyhow::ensure!(index + 4 <= MAX_HEADER_BYTES, "model relay header bound");
            break index + 4;
        }
        anyhow::ensure!(prefix.len() <= MAX_HEADER_BYTES, "model relay header bound");
    };
    let headers = parse_headers(&prefix[..header_end])?;
    let raw_length = headers
        .get("content-length")
        .context("model request requires length")?;
    let length: usize = raw_length.parse()?;
    anyhow::ensure!(
        length != 0 && length <= MAX_BODY_BYTES && raw_length == &length.to_string(),
        "model relay body length bound"
    );
    let mut body = prefix.split_off(header_end);
    anyhow::ensure!(body.len() <= length, "pipelined model request is forbidden");
    let received = body.len();
    body.resize(length, 0);
    stream.read_exact(&mut body[received..]).await?;
    let model = inspect_body(&body, &headers)?;
    Ok(Request {
        model,
        body,
        headers,
    })
}

pub(super) fn parse_headers(bytes: &[u8]) -> anyhow::Result<BTreeMap<String, String>> {
    let text = std::str::from_utf8(bytes)?;
    let mut lines = text.split("\r\n");
    anyhow::ensure!(
        lines.next() == Some("POST /hepta/v1/responses HTTP/1.1"),
        "unsupported model relay route"
    );
    let mut headers = BTreeMap::new();
    for line in lines {
        if line.is_empty() {
            continue;
        }
        let (name, value) = line
            .split_once(':')
            .context("invalid model request header")?;
        anyhow::ensure!(
            !name.is_empty()
                && name
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
                && value
                    .bytes()
                    .all(|byte| byte == b'\t' || (32..127).contains(&byte)),
            "invalid model relay header bytes"
        );
        anyhow::ensure!(
            headers
                .insert(name.to_ascii_lowercase(), value.trim().to_owned())
                .is_none(),
            "duplicate model relay header"
        );
    }
    anyhow::ensure!(
        !headers.contains_key("transfer-encoding")
            && !headers.contains_key("expect")
            && !headers.contains_key("upgrade")
            && headers.get("host").is_some_and(|host| host == "localhost")
            && headers
                .get("content-type")
                .is_some_and(|value| value == "application/json"),
        "unsupported model relay HTTP framing"
    );
    Ok(headers)
}

pub(super) fn inspect_body(
    body: &[u8],
    headers: &BTreeMap<String, String>,
) -> anyhow::Result<String> {
    let mut decoded = Vec::new();
    let json = match headers.get("content-encoding").map(String::as_str) {
        None | Some("identity") => body,
        Some("zstd") => {
            let decoder = zstd::stream::read::Decoder::new(body)?;
            decoder
                .take(MAX_DECOMPRESSED_BYTES as u64 + 1)
                .read_to_end(&mut decoded)?;
            anyhow::ensure!(
                decoded.len() <= MAX_DECOMPRESSED_BYTES,
                "decoded model body bound"
            );
            decoded.as_slice()
        }
        _ => anyhow::bail!("unsupported model request compression"),
    };
    let UniqueObject(object): UniqueObject = serde_json::from_slice(json)?;
    anyhow::ensure!(
        object.get("stream") == Some(&serde_json::Value::Bool(true))
            && object.get("store") == Some(&serde_json::Value::Bool(false))
            && object.get("input").is_some_and(serde_json::Value::is_array),
        "model relay requires stateless streaming Responses"
    );
    Ok(object
        .get("model")
        .and_then(serde_json::Value::as_str)
        .context("model missing")?
        .to_owned())
}

// Responses evolves frequently, so accept its fields while rejecting
// duplicate top-level model/store/stream values with ambiguous admission.
struct UniqueObject(BTreeMap<String, serde_json::Value>);

impl<'de> Deserialize<'de> for UniqueObject {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct ObjectVisitor;
        impl<'de> serde::de::Visitor<'de> for ObjectVisitor {
            type Value = UniqueObject;
            fn expecting(&self, formatter: &mut std::fmt::Formatter) -> std::fmt::Result {
                formatter.write_str("a Responses object without duplicate fields")
            }
            fn visit_map<A: serde::de::MapAccess<'de>>(
                self,
                mut map: A,
            ) -> Result<Self::Value, A::Error> {
                let mut object = BTreeMap::new();
                while let Some((key, value)) = map.next_entry::<String, serde_json::Value>()? {
                    if object.insert(key, value).is_some() {
                        return Err(serde::de::Error::custom("duplicate Responses field"));
                    }
                }
                Ok(UniqueObject(object))
            }
        }
        deserializer.deserialize_map(ObjectVisitor)
    }
}

pub(super) async fn error(stream: &mut UnixStream, status: u16) -> anyhow::Result<()> {
    // Errors reveal neither credentials nor the upstream response body.
    stream.write_all(format!("HTTP/1.1 {status} Model relay unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").as_bytes()).await?;
    stream.shutdown().await?;
    Ok(())
}

pub(super) async fn start_response(
    stream: &mut UnixStream,
    status: u16,
    headers: &HeaderMap,
) -> anyhow::Result<()> {
    let mut output = format!(
        "HTTP/1.1 {status} Model response\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n"
    );
    // Deliberate allowlist: no cookies, authentication challenges, locations,
    // account metadata or diagnostics carrying reflected credential values.
    for name in ["content-type", "x-request-id", "retry-after"] {
        if let Some(value) = headers.get(name) {
            let value = value.to_str()?;
            anyhow::ensure!(
                value.len() <= 512 && !value.contains(['\r', '\n']),
                "response header bound"
            );
            output.push_str(&format!("{name}: {value}\r\n"));
        }
    }
    output.push_str("\r\n");
    stream.write_all(output.as_bytes()).await?;
    Ok(())
}

pub(super) async fn chunk(stream: &mut UnixStream, bytes: &[u8]) -> anyhow::Result<()> {
    if !bytes.is_empty() {
        stream
            .write_all(format!("{:x}\r\n", bytes.len()).as_bytes())
            .await?;
        stream.write_all(bytes).await?;
        stream.write_all(b"\r\n").await?;
    }
    Ok(())
}

pub(super) async fn finish(stream: &mut UnixStream) -> anyhow::Result<()> {
    stream.write_all(b"0\r\n\r\n").await?;
    stream.shutdown().await?;
    Ok(())
}

#[cfg(test)]
#[path = "local_model_relay_http_tests.rs"]
mod tests;
