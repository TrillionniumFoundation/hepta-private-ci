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

pub(crate) fn key(seed: u8) -> (PqNativeSigningKey, PqAuthorityTrustKey) {
    let spki = PqNativeSigningKey::public_spki_from_seed(&[seed; 32].into());
    let id = ml_dsa_65_key_id_from_spki(&spki).unwrap();
    (
        PqNativeSigningKey::from_owned_seed([seed; 32].into(), id).unwrap(),
        PqAuthorityTrustKey {
            key_id: format!("key-{seed}"),
            public_key_id: id,
            public_key_spki: spki.to_vec(),
            not_before_authority_epoch: 1,
            not_after_authority_epoch: u64::MAX,
        },
    )
}
pub(crate) fn signed(
    request: PqTrustRequestV2,
    outcome: PqTrustOutcomeV2,
    key: &PqNativeSigningKey,
) -> SignedPqTrustResponseV2 {
    let body = PqTrustResponseBodyV2 {
        schema_version: 2,
        request,
        valid_for_ms: 2000,
        outcome,
    };
    let signature = key
        .sign_exact_message(&body.signing_bytes().unwrap())
        .unwrap()
        .to_vec();
    SignedPqTrustResponseV2 { body, signature }
}
pub(crate) struct TestService {
    pub(crate) config: UnixPqTrustEndpointConfig,
    pub(crate) requests: Arc<AtomicUsize>,
    stop: Arc<AtomicBool>,
    join: Option<JoinHandle<()>>,
}
impl TestService {
    pub(crate) fn start(
        root: &Path,
        name: &str,
        seed: u8,
        mut handler: impl FnMut(PqTrustRequestV2, &PqNativeSigningKey) -> SignedPqTrustResponseV2
        + Send
        + 'static,
    ) -> Self {
        fs::set_permissions(root, fs::Permissions::from_mode(0o700)).unwrap();
        let socket_path = root.join(name);
        let listener = UnixListener::bind(&socket_path).unwrap();
        fs::set_permissions(&socket_path, fs::Permissions::from_mode(0o600)).unwrap();
        listener.set_nonblocking(true).unwrap();
        let (signer, pin) = key(seed);
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
        let join = thread::spawn(move || {
            let deadline = Instant::now() + Duration::from_secs(30);
            while !stopping.load(Ordering::Relaxed) && Instant::now() < deadline {
                match listener.accept() {
                    Ok((mut stream, _)) => {
                        stream
                            .set_read_timeout(Some(Duration::from_secs(2)))
                            .unwrap();
                        stream
                            .set_write_timeout(Some(Duration::from_secs(2)))
                            .unwrap();
                        let mut size = [0; 4];
                        if stream.read_exact(&mut size).is_err() {
                            continue;
                        }
                        let size = u32::from_be_bytes(size) as usize;
                        assert!(size <= MAX_REQUEST_BYTES);
                        let mut raw = vec![0; size];
                        stream.read_exact(&mut raw).unwrap();
                        let request: PqTrustRequestV2 = serde_json::from_slice(&raw).unwrap();
                        count.fetch_add(1, Ordering::Relaxed);
                        let response = handler(request, &signer);
                        let raw = serde_json::to_vec(&response).unwrap();
                        let _ = stream.write_all(&(raw.len() as u32).to_be_bytes());
                        let _ = stream.write_all(&raw);
                    }
                    Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                        thread::sleep(Duration::from_millis(1))
                    }
                    Err(e) => panic!("test service: {e}"),
                }
            }
        });
        Self {
            config,
            requests,
            stop,
            join: Some(join),
        }
    }
}
impl Drop for TestService {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        if let Some(join) = self.join.take() {
            join.join().unwrap();
        }
    }
}

pub(crate) fn frontier_service(root: &Path, initial: FinalUseFrontier) -> TestService {
    let path = root.join("external-frontier.json");
    fs::write(&path, serde_json::to_vec(&initial).unwrap()).unwrap();
    fs::File::open(&path).unwrap().sync_all().unwrap();
    TestService::start(
        root,
        "frontier.sock",
        /*seed*/ 81,
        move |request, key| {
            let current: FinalUseFrontier =
                serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
            let outcome = match &request.operation {
                PqTrustOperationV2::FrontierLoad { .. } => {
                    PqTrustOutcomeV2::Frontier { value: current }
                }
                PqTrustOperationV2::FrontierCompareAndSet { expected, next, .. }
                    if *expected == current =>
                {
                    let temporary = path.with_extension("next");
                    fs::write(&temporary, serde_json::to_vec(next).unwrap()).unwrap();
                    fs::File::open(&temporary).unwrap().sync_all().unwrap();
                    fs::rename(&temporary, &path).unwrap();
                    fs::File::open(path.parent().unwrap())
                        .unwrap()
                        .sync_all()
                        .unwrap();
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
