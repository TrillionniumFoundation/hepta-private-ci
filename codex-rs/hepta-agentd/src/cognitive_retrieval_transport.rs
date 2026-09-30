//! Bounded loopback transport for a separately managed retrieval frontier owner.
//! Transport bytes are not authority: the leased provider verifies signatures.

use std::io::Read;
use std::io::Write;
use std::net::SocketAddr;
use std::net::TcpStream;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_agent_components::contracts::AgentId;
use codex_hepta_agent_components::types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::MemoryRetrievalFrontierOwnerV1;
use super::MemoryRetrievalFrontierV1;

const SCHEMA: &str = "hepta.agentd.retrieval-frontier.rpc.v1";
const MAX_FRAME_BYTES: usize = 4096;

pub(super) struct LoopbackFrontierClient {
    endpoint: SocketAddr,
    timeout: Duration,
}

impl LoopbackFrontierClient {
    pub(super) fn new(endpoint: SocketAddr, timeout: Duration) -> Result<Self, String> {
        if !endpoint.ip().is_loopback() || endpoint.port() == 0 {
            return Err("retrieval frontier endpoint must be an explicit loopback address".into());
        }
        if !(Duration::from_millis(10)..=Duration::from_secs(5)).contains(&timeout) {
            return Err("retrieval frontier timeout must be between 10 ms and 5 s".into());
        }
        Ok(Self { endpoint, timeout })
    }
}

#[derive(Serialize)]
struct Request<'a> {
    schema: &'static str,
    owner: &'a str,
    body_generation: u64,
    challenge: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Response {
    schema: String,
    owner: String,
    body_generation: u64,
    authority_epoch: u64,
    sequence: u64,
    publication_digest: Option<String>,
    expires_unix_ms: u64,
    challenge: String,
    signature: String,
}

impl MemoryRetrievalFrontierOwnerV1 for LoopbackFrontierClient {
    fn observe(
        &self,
        owner: &AgentId,
        body_generation: u64,
        challenge: [u8; 32],
    ) -> Result<MemoryRetrievalFrontierV1, String> {
        let deadline = Instant::now()
            .checked_add(self.timeout)
            .ok_or_else(|| "retrieval frontier deadline overflow".to_string())?;
        self.observe_before(owner, body_generation, challenge, deadline)
    }

    fn observe_before(
        &self,
        owner: &AgentId,
        body_generation: u64,
        challenge: [u8; 32],
        request_deadline: Instant,
    ) -> Result<MemoryRetrievalFrontierV1, String> {
        let configured_deadline = Instant::now()
            .checked_add(self.timeout)
            .ok_or_else(|| "retrieval frontier deadline overflow".to_string())?;
        let deadline = request_deadline.min(configured_deadline);
        remaining(deadline)?;
        let request = serde_json::to_vec(&Request {
            schema: SCHEMA,
            owner: owner.as_str(),
            body_generation,
            challenge: hex(&challenge),
        })
        .map_err(|_| "retrieval frontier request encoding failed".to_string())?;
        if request.len() > MAX_FRAME_BYTES {
            return Err("retrieval frontier request exceeds frame bound".into());
        }
        let mut stream = TcpStream::connect_timeout(&self.endpoint, remaining(deadline)?)
            .map_err(|_| "retrieval frontier connection unavailable".to_string())?;
        let length = u32::try_from(request.len())
            .map_err(|_| "retrieval frontier request length overflow".to_string())?;
        let mut frame = length.to_be_bytes().to_vec();
        frame.extend_from_slice(&request);
        let mut sent = 0;
        while sent < frame.len() {
            stream
                .set_write_timeout(Some(remaining(deadline)?))
                .map_err(|_| "retrieval frontier write deadline unavailable".to_string())?;
            match stream.write(&frame[sent..]) {
                Ok(0) => return Err("retrieval frontier write closed".into()),
                Ok(count) => sent += count,
                Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
                Err(_) => return Err("retrieval frontier write failed or timed out".into()),
            }
        }
        let mut header = [0_u8; 4];
        read_bounded(&mut stream, &mut header, deadline)?;
        let length = usize::try_from(u32::from_be_bytes(header))
            .map_err(|_| "retrieval frontier response length overflow".to_string())?;
        if !(1..=MAX_FRAME_BYTES).contains(&length) {
            return Err("retrieval frontier response exceeds frame bound".into());
        }
        let mut body = vec![0_u8; length];
        read_bounded(&mut stream, &mut body, deadline)?;
        let result = decode(&body, owner, body_generation, challenge)?;
        remaining(deadline)?;
        Ok(result)
    }
}

fn remaining(deadline: Instant) -> Result<Duration, String> {
    deadline
        .checked_duration_since(Instant::now())
        .filter(|duration| !duration.is_zero())
        .ok_or_else(|| "retrieval frontier total deadline exceeded".to_string())
}

fn read_bounded(
    stream: &mut TcpStream,
    output: &mut [u8],
    deadline: Instant,
) -> Result<(), String> {
    let mut offset = 0;
    while offset < output.len() {
        stream
            .set_read_timeout(Some(remaining(deadline)?))
            .map_err(|_| "retrieval frontier read deadline unavailable".to_string())?;
        match stream.read(&mut output[offset..]) {
            Ok(0) => return Err("retrieval frontier returned a truncated frame".into()),
            Ok(count) => offset += count,
            Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(_) => return Err("retrieval frontier read failed or timed out".into()),
        }
    }
    Ok(())
}

fn decode(
    body: &[u8],
    owner: &AgentId,
    body_generation: u64,
    challenge: [u8; 32],
) -> Result<MemoryRetrievalFrontierV1, String> {
    if body.len() > MAX_FRAME_BYTES {
        return Err("retrieval frontier response exceeds frame bound".into());
    }
    let response: Response = serde_json::from_slice(body)
        .map_err(|_| "retrieval frontier response is not the strict v1 schema".to_string())?;
    if response.schema != SCHEMA
        || response.owner != owner.as_str()
        || response.body_generation != body_generation
        || unhex::<32>(&response.challenge)? != challenge
    {
        return Err("retrieval frontier response identity/challenge mismatch".into());
    }
    let publication_digest = response
        .publication_digest
        .map(|value| {
            unhex::<32>(&value)?;
            value
                .parse::<Digest32>()
                .map_err(|_| "invalid retrieval publication digest".to_string())
        })
        .transpose()?;
    Ok(MemoryRetrievalFrontierV1 {
        owner: owner.clone(),
        body_generation,
        authority_epoch: response.authority_epoch,
        sequence: response.sequence,
        publication_digest,
        expires_unix_ms: response.expires_unix_ms,
        challenge,
        signature: unhex::<64>(&response.signature)?,
    })
}

fn hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut encoded = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        encoded.push(char::from(DIGITS[usize::from(byte >> 4)]));
        encoded.push(char::from(DIGITS[usize::from(byte & 15)]));
    }
    encoded
}

fn unhex<const N: usize>(value: &str) -> Result<[u8; N], String> {
    if value.len() != N * 2 {
        return Err("retrieval frontier hex field length mismatch".into());
    }
    let mut decoded = [0_u8; N];
    for (index, pair) in value.as_bytes().chunks_exact(2).enumerate() {
        let nibble = |byte: u8| match byte {
            b'0'..=b'9' => Ok(byte - b'0'),
            b'a'..=b'f' => Ok(byte - b'a' + 10),
            _ => Err("retrieval frontier hex fields must be canonical lowercase".to_string()),
        };
        decoded[index] = (nibble(pair[0])? << 4) | nibble(pair[1])?;
    }
    Ok(decoded)
}

#[cfg(test)]
#[path = "cognitive_retrieval_transport_tests.rs"]
mod tests;
