//! Native v2 read-only request/response authentication. Legacy bearer clients
//! remain separate; the product native client never sends the keyring secret.
use super::GatewayAuth;
use anyhow::Context;
use anyhow::Result;
use codex_hepta_contracts::native_gateway::NativeGatewayRequestV2;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

const MAX_LIVE_NONCES: usize = 4096;

pub(super) fn authenticate(
    request: &str,
    auth: &GatewayAuth,
) -> Result<Option<NativeGatewayRequestV2>> {
    let mut values = request
        .lines()
        .skip(1)
        .take_while(|line| !line.is_empty())
        .filter_map(|line| line.split_once(':'))
        .filter(|(name, _)| name.trim().eq_ignore_ascii_case("authorization"));
    let Some((_, value)) = values.next() else {
        return Ok(None);
    };
    if values.next().is_some() {
        anyhow::bail!("duplicate authorization");
    }
    if !value.trim().starts_with("Hepta-MAC-V2 ") {
        return Ok(None);
    }
    let (headers, body) = request
        .split_once("\r\n\r\n")
        .context("incomplete native request")?;
    if !body.is_empty() {
        anyhow::bail!("native reads do not admit a request body");
    }
    let mut fields = headers
        .lines()
        .next()
        .context("missing request line")?
        .split_ascii_whitespace();
    if fields.next() != Some("GET") {
        anyhow::bail!("native gateway is read-only");
    }
    let target = fields.next().context("missing native target")?;
    if fields.next() != Some("HTTP/1.1") || fields.next().is_some() {
        anyhow::bail!("invalid native HTTP version");
    }
    let proof = NativeGatewayRequestV2::parse_header(value.trim())?;
    let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    proof.verify(
        auth.bearer_token.as_bytes(),
        target,
        now,
        &auth.server_incarnation,
    )?;
    let mut seen = auth
        .seen_nonces
        .lock()
        .map_err(|_| anyhow::anyhow!("native replay cache poisoned"))?;
    // Keep entries through their inclusive validity boundary.
    seen.retain(|_, expires| *expires >= now);
    if seen.len() >= MAX_LIVE_NONCES || seen.contains_key(&proof.nonce()) {
        anyhow::bail!("native replay or request capacity exhausted");
    }
    seen.insert(proof.nonce(), proof.expires_unix_ms());
    Ok(Some(proof))
}

pub(super) fn sign_response(
    mut response: Vec<u8>,
    proof: &NativeGatewayRequestV2,
    auth: &GatewayAuth,
) -> Result<Vec<u8>> {
    let split = response
        .windows(4)
        .position(|part| part == b"\r\n\r\n")
        .context("response framing")?;
    let status = std::str::from_utf8(&response[..split])?
        .lines()
        .next()
        .and_then(|line| line.split_ascii_whitespace().nth(1))
        .context("response status")?
        .parse()?;
    let tag = proof.response_tag(auth.bearer_token.as_bytes(), status, &response[split + 4..])?;
    response.splice(
        split + 2..split + 2,
        format!("X-Hepta-Response-MAC: {tag}\r\n").bytes(),
    );
    Ok(response)
}

#[cfg(test)]
#[path = "native_mac_tests.rs"]
mod tests;
