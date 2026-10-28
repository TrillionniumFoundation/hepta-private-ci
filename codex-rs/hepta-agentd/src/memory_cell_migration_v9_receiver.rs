use std::net::TcpStream;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Instant;

use codex_hepta_contracts::ProviderEffectDispatch;
use codex_hepta_contracts::Sha256Digest;
use ed25519_dalek::SigningKey;
use ed25519_dalek::VerifyingKey;

use super::super::MAX_IMAGE_BYTES;
use super::super::failure;
use super::super::store::MemoryCellMigrationStoreV9;
use super::wire::*;

/// Authenticated receiver for an independently configured destination image.
/// Holding this server is not a final-use grant; its caller must admit only
/// operator-configured source/destination identities and use the TaskFlow
/// effect owner for dispatch. It never resolves arbitrary filesystem paths.
pub struct MemoryCellMigrationReceiverV9 {
    store: MemoryCellMigrationStoreV9,
    destination: String,
    source_key: VerifyingKey,
    receiver_key: SigningKey,
    traffic: Arc<Mutex<MemoryCellMigrationTrafficV9>>,
}

impl MemoryCellMigrationReceiverV9 {
    pub fn new(store: MemoryCellMigrationStoreV9, destination: String, source_key: VerifyingKey, receiver_key: SigningKey) -> Self {
        Self { store, destination, source_key, receiver_key, traffic: Arc::new(Mutex::new(MemoryCellMigrationTrafficV9::default())) }
    }

    pub fn traffic(&self) -> Result<MemoryCellMigrationTrafficV9, String> {
        self.traffic.lock().map(|value| *value).map_err(failure)
    }

    pub fn serve_stream(&self, stream: TcpStream) -> Result<(), String> {
        self.serve_observed(stream, &mut |_| {})
    }

    pub(crate) fn serve_observed(&self, stream: TcpStream, observe: &mut dyn FnMut(&str)) -> Result<(), String> {
        let _attempt = Attempt::begin(Arc::clone(&self.traffic))?;
        if !stream.peer_addr().map_err(failure)?.ip().is_loopback() {
            return Err("migration receiver requires loopback transport".into());
        }
        let mut wire = Wire::new(stream, Arc::clone(&self.traffic), Instant::now() + DEADLINE);
        let request: Signed<Request> = wire.receive_json()?;
        verify(&request, &self.source_key, REQUEST_DOMAIN)?;
        let request_digest = Sha256Digest::for_bytes(&serde_json::to_vec(&request.body).map_err(failure)?);
        let request = request.body;
        if request.destination != self.destination || request.payload_bytes > MAX_IMAGE_BYTES as u64 {
            return Err("migration destination or payload bound mismatch".into());
        }
        let outcome = match request.action {
            Action::Commit => {
                let raw = wire.read(usize::try_from(request.payload_bytes).map_err(failure)?)?;
                let result = match self.store.commit(&request.intent, &raw, observe) {
                    Ok(receipt) => ProviderEffectDispatch::Ack(receipt),
                    Err(_) => ProviderEffectDispatch::Rejected { reason_code: "migration_image_rejected".into() },
                };
                Outcome::Dispatch(result)
            }
            Action::Lookup => {
                if request.payload_bytes != 0 { return Err("migration lookup contains payload".into()); }
                Outcome::Lookup(self.store.lookup(&request.intent)?)
            }
        };
        wire.send_json(&sign(Response { request_digest, outcome }, &self.receiver_key, RESPONSE_DOMAIN)?)
    }
}
