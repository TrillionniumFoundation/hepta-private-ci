//! Bounded framing for the existing single-request, connection-close gateway.
//!
//! Only the first HTTP header block reaches representation negotiation. This
//! reader does not introduce keep-alive, body handling or a second route owner.

use anyhow::Context;
use anyhow::Result;
use tokio::io::AsyncRead;
use tokio::io::AsyncReadExt;

use crate::MAX_REQUEST_BYTES;

pub(super) async fn read_request(stream: &mut (impl AsyncRead + Unpin)) -> Result<Vec<u8>> {
    let mut bytes = Vec::with_capacity(2048);
    let mut buffer = [0_u8; 2048];
    let mut searched = 0;
    loop {
        // Revisit only the last three old bytes: a delimiter can cross a read
        // boundary, but rescanning the full prefix for every byte is quadratic.
        if let Some(end) = bytes[searched..]
            .windows(4)
            .position(|window| window == b"\r\n\r\n")
        {
            bytes.truncate(searched + end + 4);
            return Ok(bytes);
        }
        searched = bytes.len().saturating_sub(3);
        let remaining = MAX_REQUEST_BYTES.saturating_sub(bytes.len());
        if remaining == 0 {
            anyhow::bail!("HTTP request headers exceed {MAX_REQUEST_BYTES} bytes");
        }
        // Never read beyond the header budget and only then reject. A valid
        // header ending exactly at the ceiling is accepted on the next loop.
        let allowance = buffer.len().min(remaining);
        let read = stream
            .read(&mut buffer[..allowance])
            .await
            .context("read loopback request")?;
        if read == 0 {
            anyhow::bail!("loopback request ended before complete headers");
        }
        bytes.extend_from_slice(&buffer[..read]);
    }
}

#[cfg(test)]
#[path = "request_head_tests.rs"]
mod tests;
