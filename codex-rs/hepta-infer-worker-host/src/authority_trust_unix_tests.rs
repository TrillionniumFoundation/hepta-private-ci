use super::*;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::PqAuthorityTrustKey;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use std::fs;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixListener;
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::thread::JoinHandle;
use std::thread::{self};
use std::time::Duration;
use std::time::Instant;
const MAX_REQUEST_BYTES: usize = 16 * 1024;
type TestResult<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

pub(crate) fn key(seed: u8) -> TestResult<(PqNativeSigningKey, PqAuthorityTrustKey)> {
    let spki = PqNativeSigningKey::public_spki_from_seed(&[seed; 32].into());
    let id = ml_dsa_65_key_id_from_spki(&spki)?;
    Ok((
        PqNativeSigningKey::from_owned_seed([seed; 32].into(), id)?,
        PqAuthorityTrustKey {
            key_id: format!("key-{seed}"),
            public_key_id: id,
            public_key_spki: spki.to_vec(),
            not_before_authority_epoch: 1,
            not_after_authority_epoch: u64::MAX,
        },
    ))
}
pub(crate) fn signed(
    request: PqTrustRequestV2,
    outcome: PqTrustOutcomeV2,
    key: &PqNativeSigningKey,
) -> TestResult<SignedPqTrustResponseV2> {
    let body = PqTrustResponseBodyV2 {
        schema_version: 2,
        request,
        valid_for_ms: 2000,
        outcome,
    };
    let signature = key.sign_exact_message(&body.signing_bytes()?)?.to_vec();
    Ok(SignedPqTrustResponseV2 { body, signature })
}
pub(crate) struct TestService {
    pub(crate) config: UnixPqTrustEndpointConfig,
    pub(crate) requests: Arc<AtomicUsize>,
    stop: Arc<AtomicBool>,
    join: Option<JoinHandle<TestResult<()>>>,
}
impl TestService {
    pub(crate) fn start(
        root: &Path,
        name: &str,
        seed: u8,
        handler: impl FnMut(
            PqTrustRequestV2,
            &PqNativeSigningKey,
        ) -> TestResult<SignedPqTrustResponseV2>
        + Send
        + 'static,
    ) -> TestResult<Self> {
        Self::start_with_lifetime(root, name, seed, Duration::from_secs(30), handler)
    }

    pub(crate) fn start_with_lifetime(
        root: &Path,
        name: &str,
        seed: u8,
        lifetime: Duration,
        mut handler: impl FnMut(
            PqTrustRequestV2,
            &PqNativeSigningKey,
        ) -> TestResult<SignedPqTrustResponseV2>
        + Send
        + 'static,
    ) -> TestResult<Self> {
        fs::set_permissions(root, fs::Permissions::from_mode(0o700))?;
        let socket_path = root.join(name);
        let listener = UnixListener::bind(&socket_path)?;
        fs::set_permissions(&socket_path, fs::Permissions::from_mode(0o600))?;
        listener.set_nonblocking(true)?;
        let (signer, pin) = key(seed)?;
        let config = UnixPqTrustEndpointConfig {
            socket_path,
            peer_uid: rustix::process::geteuid().as_raw(),
            service_id: name.into(),
            key_generation: 1,
            public_key_id: pin.public_key_id,
            public_key_spki: pin.public_key_spki,
            timeout_ms: 2000,
        };
        let stop = Arc::new(AtomicBool::new(false));
        let stopping = Arc::clone(&stop);
        let requests = Arc::new(AtomicUsize::new(0));
        let count = Arc::clone(&requests);
        let join = thread::spawn(move || -> TestResult<()> {
            let deadline = Instant::now() + lifetime;
            while !stopping.load(Ordering::Relaxed) && Instant::now() < deadline {
                match listener.accept() {
                    Ok((mut stream, _)) => {
                        stream.set_read_timeout(Some(Duration::from_secs(2)))?;
                        stream.set_write_timeout(Some(Duration::from_secs(2)))?;
                        let mut size = [0; 4];
                        if stream.read_exact(&mut size).is_err() {
                            continue;
                        }
                        let size = u32::from_be_bytes(size) as usize;
                        assert!(size <= MAX_REQUEST_BYTES);
                        let mut raw = vec![0; size];
                        stream.read_exact(&mut raw)?;
                        let request: PqTrustRequestV2 = serde_json::from_slice(&raw)?;
                        count.fetch_add(1, Ordering::Relaxed);
                        let response = handler(request, &signer)?;
                        let raw = serde_json::to_vec(&response)?;
                        let _ = stream.write_all(&(raw.len() as u32).to_be_bytes());
                        let _ = stream.write_all(&raw);
                    }
                    Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                        thread::sleep(Duration::from_millis(1))
                    }
                    Err(e) => return Err(e.into()),
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
}
impl Drop for TestService {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        if let Some(join) = self.join.take() {
            match join.join() {
                Ok(Ok(())) => {}
                Ok(Err(error)) => panic!("protected trust test service failed: {error}"),
                Err(payload) => std::panic::resume_unwind(payload),
            }
        }
    }
}

pub(crate) fn frontier_service(root: &Path, initial: FinalUseFrontier) -> TestResult<TestService> {
    frontier_service_with_lifetime(root, initial, Duration::from_secs(30))
}

pub(crate) fn frontier_service_with_lifetime(
    root: &Path,
    initial: FinalUseFrontier,
    lifetime: Duration,
) -> TestResult<TestService> {
    let path = root.join("external-frontier.json");
    fs::write(&path, serde_json::to_vec(&initial)?)?;
    fs::File::open(&path)?.sync_all()?;
    TestService::start_with_lifetime(
        root,
        "frontier.sock",
        /*seed*/ 81,
        lifetime,
        move |request, key| {
            let current: FinalUseFrontier = serde_json::from_slice(&fs::read(&path)?)?;
            let outcome = match &request.operation {
                PqTrustOperationV2::FrontierLoad { .. } => {
                    PqTrustOutcomeV2::Frontier { value: current }
                }
                PqTrustOperationV2::FrontierCompareAndSet { expected, next, .. }
                    if *expected == current =>
                {
                    let temporary = path.with_extension("next");
                    fs::write(&temporary, serde_json::to_vec(next)?)?;
                    fs::File::open(&temporary)?.sync_all()?;
                    fs::rename(&temporary, &path)?;
                    fs::File::open(
                        path.parent()
                            .ok_or("external frontier requires a parent directory")?,
                    )?
                    .sync_all()?;
                    PqTrustOutcomeV2::CompareAndSetApplied { value: *next }
                }
                PqTrustOperationV2::FrontierCompareAndSet { .. } => PqTrustOutcomeV2::Conflict,
                PqTrustOperationV2::ClockNow
                | PqTrustOperationV2::LearningFrontierLoad { .. }
                | PqTrustOperationV2::LearningFrontierCompareAndSet { .. } => {
                    PqTrustOutcomeV2::Unavailable
                }
            };
            signed(request, outcome, key)
        },
    )
}
