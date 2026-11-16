//! Real signed Unix test services; these are local fixtures, not deployment evidence.

use std::fs;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixListener;
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::thread;
use std::thread::JoinHandle;
use std::time::Duration;

use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::PqAuthorityTrustKey;
use codex_hepta_contracts::authority_trust_unix::PqTrustOperationV2;
use codex_hepta_contracts::authority_trust_unix::PqTrustOutcomeV2;
use codex_hepta_contracts::authority_trust_unix::PqTrustRequestV2;
use codex_hepta_contracts::authority_trust_unix::PqTrustResponseBodyV2;
use codex_hepta_contracts::authority_trust_unix::SignedPqTrustResponseV2;
use codex_hepta_contracts::authority_trust_unix::UnixPqTrustEndpointConfig;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use serde_json::Value;

pub(super) fn key(seed: u8) -> anyhow::Result<(PqNativeSigningKey, PqAuthorityTrustKey)> {
    let spki = PqNativeSigningKey::public_spki_from_seed(&[seed; 32].into());
    let id = ml_dsa_65_key_id_from_spki(&spki)?;
    Ok((
        PqNativeSigningKey::from_owned_seed([seed; 32].into(), id)?,
        PqAuthorityTrustKey {
            key_id: format!("fixture-{seed}"),
            public_key_id: id,
            public_key_spki: spki.to_vec(),
            not_before_authority_epoch: 1,
            not_after_authority_epoch: 99,
        },
    ))
}

pub(super) fn write_private(path: &Path, bytes: &[u8]) -> anyhow::Result<()> {
    fs::write(path, bytes)?;
    fs::set_permissions(path, fs::Permissions::from_mode(0o600))?;
    fs::File::open(path)?.sync_all()?;
    Ok(())
}

pub(super) struct Service {
    pub(super) config: UnixPqTrustEndpointConfig,
    pub(super) requests: Arc<AtomicUsize>,
    stop: Arc<AtomicBool>,
    join: Option<JoinHandle<anyhow::Result<()>>>,
}

impl Service {
    pub(super) fn start(
        root: &Path,
        name: &str,
        seed: u8,
        mut handler: impl FnMut(&PqTrustOperationV2) -> anyhow::Result<PqTrustOutcomeV2>
        + Send
        + 'static,
    ) -> anyhow::Result<Self> {
        fs::set_permissions(root, fs::Permissions::from_mode(0o700))?;
        let socket_path = root.join(name);
        let listener = UnixListener::bind(&socket_path)?;
        fs::set_permissions(&socket_path, fs::Permissions::from_mode(0o600))?;
        listener.set_nonblocking(true)?;
        let (signer, pin) = key(seed)?;
        let config = UnixPqTrustEndpointConfig {
            socket_path,
            peer_uid: fs::metadata(root)?.uid(),
            service_id: name.to_string(),
            key_generation: 1,
            public_key_id: pin.public_key_id,
            public_key_spki: pin.public_key_spki,
            timeout_ms: 2000,
        };
        let stop = Arc::new(AtomicBool::new(false));
        let stopping = Arc::clone(&stop);
        let requests = Arc::new(AtomicUsize::new(0));
        let count = Arc::clone(&requests);
        let join = thread::spawn(move || -> anyhow::Result<()> {
            while !stopping.load(Ordering::SeqCst) {
                match listener.accept() {
                    Ok((mut stream, _)) => {
                        stream.set_nonblocking(false)?;
                        stream.set_read_timeout(Some(Duration::from_secs(2)))?;
                        stream.set_write_timeout(Some(Duration::from_secs(2)))?;
                        let mut prefix = [0; 4];
                        if stream.read_exact(&mut prefix).is_err() {
                            continue;
                        }
                        let size = u32::from_be_bytes(prefix) as usize;
                        anyhow::ensure!(size <= 16 * 1024, "request exceeds trust wire bound");
                        let mut raw = vec![0; size];
                        stream.read_exact(&mut raw)?;
                        let request: PqTrustRequestV2 = serde_json::from_slice(&raw)?;
                        count.fetch_add(1, Ordering::SeqCst);
                        let outcome = handler(&request.operation)?;
                        let body = PqTrustResponseBodyV2 {
                            schema_version: 2,
                            request,
                            valid_for_ms: 2000,
                            outcome,
                        };
                        let signature = signer.sign_exact_message(&body.signing_bytes()?)?.to_vec();
                        let raw = serde_json::to_vec(&SignedPqTrustResponseV2 { body, signature })?;
                        let _ = stream.write_all(&u32::try_from(raw.len())?.to_be_bytes());
                        let _ = stream.write_all(&raw);
                    }
                    Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                        thread::sleep(Duration::from_millis(1));
                    }
                    Err(error) => return Err(error.into()),
                }
            }
            Ok(())
        });
        Ok(Self {
            config,
            requests,
            stop,
            join: Some(join),
        })
    }

    pub(super) fn config_json(&self) -> Value {
        serde_json::json!({
            "socket_path": self.config.socket_path, "peer_uid": self.config.peer_uid,
            "service_id": self.config.service_id, "key_generation": self.config.key_generation,
            "public_key_id": self.config.public_key_id, "public_key_spki": self.config.public_key_spki,
            "timeout_ms": self.config.timeout_ms,
        })
    }
}

impl Drop for Service {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::SeqCst);
        if let Some(join) = self.join.take() {
            match join.join() {
                Ok(Ok(())) => {}
                Ok(Err(error)) => panic!("PQ fixture service: {error}"),
                Err(payload) => std::panic::resume_unwind(payload),
            }
        }
    }
}

pub(super) fn frontier_service(root: &Path, initial: FinalUseFrontier) -> anyhow::Result<Service> {
    let path = root.join("frontier.json");
    write_private(&path, &serde_json::to_vec(&initial)?)?;
    Service::start(root, "frontier.sock", /*seed*/ 85, move |operation| {
        let current: FinalUseFrontier = serde_json::from_slice(&fs::read(&path)?)?;
        Ok(match operation {
            PqTrustOperationV2::FrontierLoad { owner_id } if owner_id == "hcsn-test-issuer" => {
                PqTrustOutcomeV2::Frontier { value: current }
            }
            PqTrustOperationV2::FrontierCompareAndSet {
                owner_id,
                expected,
                next,
            } if owner_id == "hcsn-test-issuer" && *expected == current => {
                let temporary = path.with_extension("next");
                write_private(&temporary, &serde_json::to_vec(next)?)?;
                fs::rename(&temporary, &path)?;
                fs::File::open(path.parent().expect("frontier parent"))?.sync_all()?;
                PqTrustOutcomeV2::CompareAndSetApplied { value: *next }
            }
            PqTrustOperationV2::FrontierCompareAndSet { .. } => PqTrustOutcomeV2::Conflict,
            PqTrustOperationV2::FrontierLoad { .. } | PqTrustOperationV2::ClockNow => {
                PqTrustOutcomeV2::Unavailable
            }
        })
    })
}
