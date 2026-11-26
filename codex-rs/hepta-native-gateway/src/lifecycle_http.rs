//! One bounded HTTP/1.1 frame. Request smuggling and trailing data fail closed.

use anyhow::Context;
use anyhow::Result;
use tokio::io::AsyncReadExt;
use tokio::net::TcpStream;

const MAX_HEADERS: usize = 16 * 1024;
const MAX_BODY: usize =
    codex_hepta_contracts::native_gateway::lifecycle::MAX_NATIVE_GATEWAY_LIFECYCLE_BODY_BYTES;

pub(super) struct Request<'a> {
    pub method: &'a str,
    pub path: &'a str,
    pub authorization: Option<&'a str>,
    pub body: &'a [u8],
}

pub(super) fn parse(bytes: &[u8]) -> Result<Request<'_>> {
    let split = bytes
        .windows(4)
        .position(|part| part == b"\r\n\r\n")
        .context("incomplete HTTP headers")?;
    let (method, path, authorization, length) = headers(&bytes[..split])?;
    if bytes.len() != split + 4 + length {
        anyhow::bail!("HTTP body length or trailing data is invalid");
    }
    Ok(Request {
        method,
        path,
        authorization,
        body: &bytes[split + 4..],
    })
}

fn headers(bytes: &[u8]) -> Result<(&str, &str, Option<&str>, usize)> {
    if bytes.len() > MAX_HEADERS {
        anyhow::bail!("HTTP headers exceeded bound");
    }
    let mut lines = std::str::from_utf8(bytes)?.split("\r\n");
    let mut fields = lines.next().context("missing request line")?.split(' ');
    let method = fields.next().context("missing method")?;
    let path = fields.next().context("missing target")?;
    if !matches!(method, "GET" | "POST")
        || fields.next() != Some("HTTP/1.1")
        || fields.next().is_some()
    {
        anyhow::bail!("invalid finite HTTP request line");
    }
    let mut length = None;
    let mut authorization = None;
    let mut content_type = None;
    for line in lines {
        let (name, value) = line.split_once(':').context("invalid header")?;
        if name.is_empty()
            || !name.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-')
            || !value
                .bytes()
                .all(|b| b == b'\t' || (0x20..=0x7e).contains(&b))
        {
            anyhow::bail!("invalid HTTP header bytes");
        }
        let value = value.trim_matches([' ', '\t']);
        if name.eq_ignore_ascii_case("content-length") {
            if value.is_empty()
                || !value.bytes().all(|b| b.is_ascii_digit())
                || length.replace(value.parse::<usize>()?).is_some()
            {
                anyhow::bail!("ambiguous content length");
            }
        } else if name.eq_ignore_ascii_case("transfer-encoding") {
            anyhow::bail!("transfer encoding is not accepted");
        } else if name.eq_ignore_ascii_case("content-type") {
            if content_type.replace(value).is_some() || value != "application/json" {
                anyhow::bail!("invalid JSON content type");
            }
        } else if name.eq_ignore_ascii_case("authorization")
            && authorization.replace(value).is_some()
        {
            anyhow::bail!("duplicate authorization");
        }
    }
    let length = length.unwrap_or(0);
    if length > MAX_BODY
        || (method == "POST" && (length == 0 || content_type != Some("application/json")))
        || (method == "GET" && length != 0)
    {
        anyhow::bail!("HTTP body exceeds the finite request bound");
    }
    Ok((method, path, authorization, length))
}

pub(super) async fn read(stream: &mut TcpStream) -> Result<Vec<u8>> {
    let mut bytes = Vec::new();
    let mut expected = None;
    let mut chunk = [0; 4096];
    loop {
        let count = stream.read(&mut chunk).await?;
        if count == 0 {
            anyhow::bail!("incomplete HTTP request");
        }
        bytes.extend_from_slice(&chunk[..count]);
        if bytes.len() > MAX_HEADERS + MAX_BODY + 4 {
            anyhow::bail!("HTTP request exceeded bound");
        }
        if expected.is_none() {
            if let Some(split) = bytes.windows(4).position(|part| part == b"\r\n\r\n") {
                let (_, _, _, length) = headers(&bytes[..split])?;
                expected = Some(split + 4 + length);
            } else if bytes.len() > MAX_HEADERS {
                anyhow::bail!("HTTP headers exceeded bound");
            }
        }
        if let Some(expected) = expected {
            if bytes.len() > expected {
                anyhow::bail!("trailing HTTP request bytes");
            }
            if bytes.len() == expected {
                parse(&bytes)?;
                return Ok(bytes);
            }
        }
    }
}

#[cfg(test)]
#[path = "lifecycle_http_tests.rs"]
mod tests;
