//! Out-of-process final-use grant channel for the native Codex worker.
//!
//! The worker sends only an exact, already-frozen operation binding. The
//! independent authority endpoint owns approval policy, epoch, nonce, grant id
//! and validity window. Returned grants are still cryptographically verified
//! and durably claimed by `FinalUseAuthority`; trust never comes from this
//! transport alone.

use std::path::Path;
use std::time::Duration;

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_uds::UnixStream;
use serde_json::json;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::time::timeout;

const IO_TIMEOUT: Duration = Duration::from_secs(5);
const MAX_REQUEST_BYTES: usize = 16 * 1024;
const MAX_RESPONSE_BYTES: usize = 32 * 1024;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

/// Request one independently signed grant for an exact binding.
///
/// Wire request (one JSON line):
/// `{"schemaVersion":1,"binding":{...},"expiresNoLaterThanUnixMs":N}`
///
/// The peer may apply any stricter policy. It must return exactly one
/// `SignedFinalUseGrant` JSON value. A mismatched binding or a validity window
/// extending beyond the operation deadline is rejected before claim.
pub async fn request_signed_grant(
    socket_path: &Path,
    binding: &FinalUseBinding,
    expires_no_later_than_unix_ms: u64,
) -> Result<SignedFinalUseGrant> {
    if !socket_path.is_absolute() {
        return Err("final-use authority socket must be absolute".into());
    }

    let mut stream = timeout(IO_TIMEOUT, UnixStream::connect(socket_path))
        .await
        .map_err(|_| "final-use authority connect timed out")??;

    let request = serde_json::to_vec(&json!({
        "schemaVersion": 1,
        "binding": binding,
        "expiresNoLaterThanUnixMs": expires_no_later_than_unix_ms,
    }))?;
    if request.len() > MAX_REQUEST_BYTES {
        return Err("final-use authority request exceeds 16 KiB".into());
    }

    timeout(IO_TIMEOUT, async {
        stream.write_all(&request).await?;
        stream.write_all(b"\n").await?;
        stream.flush().await
    })
    .await
    .map_err(|_| "final-use authority write timed out")??;

    let mut response = Vec::new();
    timeout(
        IO_TIMEOUT,
        stream
            .take((MAX_RESPONSE_BYTES + 1) as u64)
            .read_to_end(&mut response),
    )
    .await
    .map_err(|_| "final-use authority response timed out")??;
    if response.len() > MAX_RESPONSE_BYTES {
        return Err("final-use authority response exceeds 32 KiB".into());
    }
    while response.last().is_some_and(|byte| byte.is_ascii_whitespace()) {
        response.pop();
    }
    if response.is_empty() {
        return Err("final-use authority returned an empty response".into());
    }

    let signed: SignedFinalUseGrant = serde_json::from_slice(&response)?;
    if signed.grant.binding != *binding {
        return Err("final-use authority returned a different operation binding".into());
    }
    if signed.grant.expires_at_unix_ms > expires_no_later_than_unix_ms {
        return Err("final-use grant exceeds the operation deadline".into());
    }
    Ok(signed)
}
