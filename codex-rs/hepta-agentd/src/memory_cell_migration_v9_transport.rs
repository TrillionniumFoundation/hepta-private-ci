use std::net::SocketAddr;
use std::net::TcpStream;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::ProviderEffectAdapter;
use codex_hepta_contracts::ProviderEffectDispatch;
use codex_hepta_contracts::ProviderEffectFuture;
use codex_hepta_contracts::ProviderEffectIdempotencyCapability;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::ProviderEffectLookup;
use codex_hepta_contracts::Sha256Digest;
use ed25519_dalek::SigningKey;
use ed25519_dalek::VerifyingKey;

use super::MAX_IMAGE_BYTES;
use super::failure;

#[path = "memory_cell_migration_v9_receiver.rs"]
mod receiver;
#[path = "memory_cell_migration_v9_wire.rs"]
mod wire;
pub use receiver::MemoryCellMigrationReceiverV9;
pub use wire::MemoryCellMigrationTrafficV9;
use wire::*;

static NEXT_NONCE: AtomicU64 = AtomicU64::new(1);

/// Adapter for the compiled-in durable migration receiver contract. Peer keys
/// and the destination are operator configuration, never request fields.
/// Instantiate only for a qualified receiver. This profile intentionally
/// restricts plaintext transport to loopback; remote hosts require a separately
/// qualified confidential transport. TaskFlow still consumes final-use grants.
#[derive(Clone)]
pub struct MemoryCellMigrationProviderV9 {
    endpoint: SocketAddr,
    destination: String,
    source_key: Arc<SigningKey>,
    receiver_key: VerifyingKey,
    traffic: Arc<Mutex<MemoryCellMigrationTrafficV9>>,
}

impl MemoryCellMigrationProviderV9 {
    pub fn new(
        endpoint: SocketAddr,
        destination: String,
        source_key: SigningKey,
        receiver_key: VerifyingKey,
    ) -> Result<Self, String> {
        if !endpoint.ip().is_loopback() || destination.is_empty() || destination.len() > 128 {
            return Err("migration requires a bounded configured loopback destination".into());
        }
        Ok(Self {
            endpoint,
            destination,
            source_key: Arc::new(source_key),
            receiver_key,
            traffic: Arc::new(Mutex::new(MemoryCellMigrationTrafficV9::default())),
        })
    }

    /// A restarted receiver may use another loopback port, but its configured
    /// destination and authenticated signing key cannot be substituted.
    pub fn reconnect(&mut self, endpoint: SocketAddr) -> Result<(), String> {
        if !endpoint.ip().is_loopback() {
            return Err("migration endpoint is not loopback".into());
        }
        self.endpoint = endpoint;
        Ok(())
    }

    pub fn traffic(&self) -> Result<MemoryCellMigrationTrafficV9, String> {
        self.traffic.lock().map(|value| *value).map_err(failure)
    }

    fn exchange(
        &self,
        action: Action,
        intent: ProviderEffectIntent,
        payload: &[u8],
    ) -> Result<Outcome, String> {
        let _attempt = Attempt::begin(Arc::clone(&self.traffic))?;
        intent.validate().map_err(|error| format!("{error:?}"))?;
        if payload.len() > MAX_IMAGE_BYTES {
            return Err("migration payload bound".into());
        }
        let nonce = serde_json::to_vec(&(
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_err(failure)?
                .as_nanos(),
            NEXT_NONCE.fetch_add(1, Ordering::Relaxed),
        ))
        .map_err(failure)?;
        let body = Request {
            destination: self.destination.clone(),
            action,
            intent,
            payload_bytes: payload.len() as u64,
            nonce: Sha256Digest::for_bytes(&nonce),
        };
        let request_digest = Sha256Digest::for_bytes(&serde_json::to_vec(&body).map_err(failure)?);
        let deadline = Instant::now() + DEADLINE;
        let stream = TcpStream::connect_timeout(&self.endpoint, DEADLINE).map_err(failure)?;
        let mut wire = Wire::new(stream, Arc::clone(&self.traffic), deadline);
        wire.send_json(&sign(body, &self.source_key, REQUEST_DOMAIN)?)?;
        wire.write(payload)?;
        let response: Signed<Response> = wire.receive_json()?;
        verify(&response, &self.receiver_key, RESPONSE_DOMAIN)?;
        if response.body.request_digest != request_digest {
            return Err("migration response request binding".into());
        }
        Ok(response.body.outcome)
    }
}

impl ProviderEffectAdapter for MemoryCellMigrationProviderV9 {
    fn capability(&self) -> ProviderEffectIdempotencyCapability {
        ProviderEffectIdempotencyCapability::KeyAndStatusLookup
    }

    fn dispatch<'a>(
        &'a self,
        _intent: &'a ProviderEffectIntent,
    ) -> ProviderEffectFuture<'a, ProviderEffectDispatch> {
        Box::pin(async {
            ProviderEffectDispatch::NotDispatched {
                reason_code: "migration_requires_exact_payload".into(),
            }
        })
    }

    fn dispatch_with_payload<'a>(
        &'a self,
        intent: &'a ProviderEffectIntent,
        payload: &'a [u8],
    ) -> ProviderEffectFuture<'a, ProviderEffectDispatch> {
        Box::pin(async move {
            if payload.is_empty()
                || payload.len() > MAX_IMAGE_BYTES
                || Sha256Digest::for_bytes(payload) != intent.payload_sha256
            {
                return ProviderEffectDispatch::NotDispatched {
                    reason_code: "migration_payload_binding".into(),
                };
            }
            let adapter = self.clone();
            let intent = intent.clone();
            let payload = payload.to_vec();
            match tokio::task::spawn_blocking(move || {
                adapter.exchange(Action::Commit, intent, &payload)
            })
            .await
            {
                Ok(Ok(Outcome::Dispatch(value))) => value,
                _ => ProviderEffectDispatch::Unknown,
            }
        })
    }

    fn lookup<'a>(
        &'a self,
        _key: &'a ProviderEffectKey,
    ) -> ProviderEffectFuture<'a, ProviderEffectLookup> {
        Box::pin(async { ProviderEffectLookup::Unknown })
    }

    fn lookup_for_intent<'a>(
        &'a self,
        intent: &'a ProviderEffectIntent,
    ) -> ProviderEffectFuture<'a, ProviderEffectLookup> {
        Box::pin(async move {
            let adapter = self.clone();
            let intent = intent.clone();
            match tokio::task::spawn_blocking(move || adapter.exchange(Action::Lookup, intent, &[]))
                .await
            {
                Ok(Ok(Outcome::Lookup(value))) => value,
                _ => ProviderEffectLookup::Unknown,
            }
        })
    }
}
