use std::io::Read;
use std::io::Write;
use std::net::TcpStream;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::ProviderEffectDispatch;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectLookup;
use codex_hepta_contracts::Sha256Digest;
use ed25519_dalek::Signature;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use serde::de::DeserializeOwned;

use super::super::MAX_HEADER_BYTES;
use super::super::failure;

pub(super) const DEADLINE: Duration = Duration::from_secs(15);
pub(super) const REQUEST_DOMAIN: &[u8] = b"hepta.memory.migration.request.v9\0";
pub(super) const RESPONSE_DOMAIN: &[u8] = b"hepta.memory.migration.response.v9\0";

#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub struct MemoryCellMigrationTrafficV9 {
    pub attempts: u64,
    pub transmitted_bytes: u64,
    pub received_bytes: u64,
    /// Sum of this endpoint's attempts, not exclusive/concurrent wall time.
    pub elapsed_nanos: u64,
}

#[derive(Clone, Copy, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum Action { Commit, Lookup }

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Request {
    pub destination: String,
    pub action: Action,
    pub intent: ProviderEffectIntent,
    pub payload_bytes: u64,
    pub nonce: Sha256Digest,
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "kind", content = "result", rename_all = "snake_case")]
pub(super) enum Outcome {
    Dispatch(ProviderEffectDispatch),
    Lookup(ProviderEffectLookup),
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Response {
    pub request_digest: Sha256Digest,
    pub outcome: Outcome,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Signed<T> {
    pub body: T,
    pub signature: Vec<u8>,
}

pub(super) fn sign<T: Serialize>(body: T, key: &SigningKey, domain: &[u8]) -> Result<Signed<T>, String> {
    let mut raw = domain.to_vec();
    raw.extend_from_slice(&serde_json::to_vec(&body).map_err(failure)?);
    let signature = key.sign(&raw).to_bytes().to_vec();
    Ok(Signed { body, signature })
}

pub(super) fn verify<T: Serialize>(value: &Signed<T>, key: &VerifyingKey, domain: &[u8]) -> Result<(), String> {
    let mut raw = domain.to_vec();
    raw.extend_from_slice(&serde_json::to_vec(&value.body).map_err(failure)?);
    key.verify_strict(&raw, &Signature::from_slice(&value.signature).map_err(failure)?).map_err(failure)
}

pub(super) struct Wire {
    stream: TcpStream,
    traffic: Arc<Mutex<MemoryCellMigrationTrafficV9>>,
    deadline: Instant,
}

impl Wire {
    pub fn new(stream: TcpStream, traffic: Arc<Mutex<MemoryCellMigrationTrafficV9>>, deadline: Instant) -> Self {
        Self { stream, traffic, deadline }
    }

    pub fn write(&mut self, mut raw: &[u8]) -> Result<(), String> {
        while !raw.is_empty() {
            self.stream.set_write_timeout(Some(self.remaining()?)).map_err(failure)?;
            let count = self.stream.write(raw).map_err(failure)?;
            if count == 0 { return Err("migration zero-byte transport write".into()); }
            self.traffic.lock().map_err(failure)?.transmitted_bytes += count as u64;
            raw = &raw[count..];
        }
        Ok(())
    }

    pub fn read(&mut self, count: usize) -> Result<Vec<u8>, String> {
        let mut raw = vec![0; count];
        let mut offset = 0;
        while offset < count {
            self.stream.set_read_timeout(Some(self.remaining()?)).map_err(failure)?;
            let length = self.stream.read(&mut raw[offset..]).map_err(failure)?;
            if length == 0 { return Err("migration truncated transport frame".into()); }
            self.traffic.lock().map_err(failure)?.received_bytes += length as u64;
            offset += length;
        }
        Ok(raw)
    }

    pub fn send_json(&mut self, value: &impl Serialize) -> Result<(), String> {
        let raw = serde_json::to_vec(value).map_err(failure)?;
        if raw.len() > MAX_HEADER_BYTES { return Err("migration transport header bound".into()); }
        self.write(&(raw.len() as u32).to_be_bytes())?;
        self.write(&raw)
    }

    pub fn receive_json<T: DeserializeOwned>(&mut self) -> Result<T, String> {
        let length = u32::from_be_bytes(self.read(4)?.as_slice().try_into().map_err(failure)?) as usize;
        if length > MAX_HEADER_BYTES { return Err("migration transport header bound".into()); }
        serde_json::from_slice(&self.read(length)?).map_err(failure)
    }

    fn remaining(&self) -> Result<Duration, String> {
        self.deadline.checked_duration_since(Instant::now()).filter(|value| !value.is_zero())
            .ok_or_else(|| "migration transport deadline elapsed".into())
    }
}

pub(super) struct Attempt {
    traffic: Arc<Mutex<MemoryCellMigrationTrafficV9>>,
    started: Instant,
}

impl Attempt {
    pub fn begin(traffic: Arc<Mutex<MemoryCellMigrationTrafficV9>>) -> Result<Self, String> {
        traffic.lock().map_err(failure)?.attempts += 1;
        Ok(Self { traffic, started: Instant::now() })
    }
}

impl Drop for Attempt {
    fn drop(&mut self) {
        if let Ok(mut traffic) = self.traffic.lock() {
            traffic.elapsed_nanos = traffic.elapsed_nanos.saturating_add(self.started.elapsed().as_nanos().try_into().unwrap_or(u64::MAX));
        }
    }
}
