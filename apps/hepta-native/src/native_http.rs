//! Small closed HTTP/1.1 reader with one total deadline and authenticated bodies.
use crate::backend::AuthenticatedRuntimeStatus;
use crate::error::ShellError;
use crate::model::sha256_hex;
use crate::security::now_unix_ms;
use codex_hepta_contracts::native_gateway::NativeGatewayRequestV2;
use std::io::Read as _;
use std::io::Write as _;
use std::net::SocketAddr;
use std::net::TcpStream;
use std::time::Duration;
use std::time::Instant;

const MAX_RESPONSE_BYTES: usize = 1024 * 1024;
const MAX_HEADERS_BYTES: usize = 16 * 1024;
const HTTP_TIMEOUT: Duration = Duration::from_secs(3);

pub(crate) fn get_json(
    address: SocketAddr,
    key: &[u8],
    path: &str,
    incarnation: [u8; 32],
) -> Result<AuthenticatedRuntimeStatus, ShellError> {
    let deadline = Instant::now() + HTTP_TIMEOUT;
    let mut nonce = [0; 32];
    getrandom::fill(&mut nonce)
        .map_err(|e| ShellError::Security(format!("native request entropy: {e}")))?;
    let proof = NativeGatewayRequestV2::sign(key, path, nonce, now_unix_ms()?, incarnation)
        .map_err(|e| ShellError::Security(e.to_string()))?;
    let request = format!(
        "GET {path} HTTP/1.1\r\nHost: {address}\r\nAccept: application/json\r\nAuthorization: {}\r\nConnection: close\r\n\r\n",
        proof.header_value()
    );
    let mut stream = TcpStream::connect_timeout(&address, remaining(deadline)?)?;
    let mut unwritten = request.as_bytes();
    while !unwritten.is_empty() {
        stream.set_write_timeout(Some(remaining(deadline)?))?;
        let written = stream.write(unwritten)?;
        if written == 0 {
            return Err(ShellError::Backend("gateway closed during request".into()));
        }
        unwritten = &unwritten[written..];
    }
    let mut response = Vec::with_capacity(4096);
    let mut framing = None;
    let mut buffer = [0; 4096];
    loop {
        stream.set_read_timeout(Some(remaining(deadline)?))?;
        let read = stream.read(&mut buffer)?;
        if read == 0 {
            return Err(ShellError::Backend(
                "gateway response ended before its declared body".into(),
            ));
        }
        response.extend_from_slice(&buffer[..read]);
        if response.len() > MAX_RESPONSE_BYTES {
            return Err(ShellError::Backend(
                "gateway response exceeded native bound".into(),
            ));
        }
        if framing.is_none() {
            if let Some(split) = response.windows(4).position(|p| p == b"\r\n\r\n") {
                if split > MAX_HEADERS_BYTES {
                    return Err(ShellError::Backend(
                        "gateway headers exceed native bound".into(),
                    ));
                }
                framing = Some(parse_headers(&response[..split], split + 4)?);
            } else if response.len() > MAX_HEADERS_BYTES {
                return Err(ShellError::Backend(
                    "gateway headers exceed native bound".into(),
                ));
            }
        }
        if let Some(headers) = &framing {
            if response.len() > headers.body_start + headers.body_length {
                return Err(ShellError::Backend(
                    "gateway sent trailing bytes after declared body".into(),
                ));
            }
            if response.len() == headers.body_start + headers.body_length {
                let body = &response[headers.body_start..];
                proof
                    .verify_response(key, headers.status, body, &headers.mac)
                    .map_err(|e| {
                        ShellError::Security(format!("gateway response authentication failed: {e}"))
                    })?;
                if headers.status != 200 {
                    return Err(ShellError::Backend(format!(
                        "authenticated gateway returned HTTP {}",
                        headers.status
                    )));
                }
                return Ok(AuthenticatedRuntimeStatus {
                    value: serde_json::from_slice(body)?,
                    body_digest: sha256_hex(body),
                });
            }
        }
    }
}

fn remaining(deadline: Instant) -> Result<Duration, ShellError> {
    deadline
        .checked_duration_since(Instant::now())
        .filter(|d| !d.is_zero())
        .ok_or_else(|| ShellError::Backend("gateway exceeded its total request deadline".into()))
}

struct Headers {
    status: u16,
    body_start: usize,
    body_length: usize,
    mac: String,
}
fn parse_headers(bytes: &[u8], body_start: usize) -> Result<Headers, ShellError> {
    let text = std::str::from_utf8(bytes)
        .map_err(|_| ShellError::Backend("invalid HTTP headers".into()))?;
    let invalid = || ShellError::Backend("invalid or ambiguous native HTTP framing".into());
    let mut lines = text.split("\r\n");
    let mut status = lines.next().ok_or_else(invalid)?.split_ascii_whitespace();
    if status.next() != Some("HTTP/1.1") {
        return Err(invalid());
    }
    let code: u16 = status
        .next()
        .ok_or_else(invalid)?
        .parse()
        .map_err(|_| invalid())?;
    if !(100..=599).contains(&code) {
        return Err(invalid());
    }
    let mut length = None;
    let mut mac = None;
    let mut content_type = None;
    for line in lines {
        let (name, value) = line.split_once(':').ok_or_else(invalid)?;
        if name.is_empty() || !name.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-') {
            return Err(invalid());
        }
        let value = value.trim();
        if name.eq_ignore_ascii_case("content-length") {
            if !value.bytes().all(|b| b.is_ascii_digit())
                || length
                    .replace(value.parse::<usize>().map_err(|_| invalid())?)
                    .is_some()
            {
                return Err(invalid());
            }
        } else if name.eq_ignore_ascii_case("transfer-encoding") {
            return Err(invalid()); // Native v2 always emits a bounded known-length body.
        } else if name.eq_ignore_ascii_case("x-hepta-response-mac") {
            if mac.replace(value.to_owned()).is_some() {
                return Err(invalid());
            }
        } else if name.eq_ignore_ascii_case("content-type") && content_type.replace(value).is_some()
        {
            return Err(invalid());
        }
    }
    let body_length = length.ok_or_else(invalid)?;
    if body_start
        .checked_add(body_length)
        .is_none_or(|total| total > MAX_RESPONSE_BYTES)
    {
        return Err(invalid());
    }
    if content_type.and_then(|v| v.split(';').next()) != Some("application/json") {
        return Err(invalid());
    }
    let mac =
        mac.ok_or_else(|| ShellError::Security("gateway response has no server proof".into()))?;
    Ok(Headers {
        status: code,
        body_start,
        body_length,
        mac,
    })
}

#[cfg(test)]
#[path = "native_http_tests.rs"]
mod tests;
