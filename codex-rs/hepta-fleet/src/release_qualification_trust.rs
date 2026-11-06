//! Component-only external-owner fixture. Actual PQ challenge/response and
//! durable CAS are exercised; this is not independently operated key custody.

use std::fs;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixListener;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::thread::JoinHandle;
use std::time::Duration;

use codex_hepta_contracts::ReleaseFrontierV1;
use codex_hepta_contracts::authority_trust_unix::PqTrustOperationV2;
use codex_hepta_contracts::authority_trust_unix::PqTrustOutcomeV2;
use codex_hepta_contracts::authority_trust_unix::PqTrustRequestV2;
use codex_hepta_contracts::authority_trust_unix::PqTrustResponseBodyV2;
use codex_hepta_contracts::authority_trust_unix::SignedPqTrustResponseV2;
use codex_hepta_contracts::authority_trust_unix::UnixPqTrustEndpointConfig;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;

use crate::release_qualification::QualificationResult;

pub(crate) const OWNER: &str = "hepta.fleet.release.qualification";
pub(crate) const NOW: u64 = 1_800_000_000;
// These faults still execute and acknowledge the real CAS. They change its
// subsequent fresh observation; none of these fixtures bypass PQ signing.
pub(crate) const AFTER_CAS_LOAD_UNAVAILABLE: u8 = 4;
const NEXT_LOAD_UNAVAILABLE: u8 = 5;
pub(crate) const AFTER_CAS_FRONTIER_DRIFT: u8 = 6;

pub(crate) struct TrustService {
    pub config: UnixPqTrustEndpointConfig,
    pub now: Arc<AtomicU64>,
    pub advance_clock_after_reads: Arc<AtomicU64>,
    pub advance_clock_to_ms: Arc<AtomicU64>,
    pub cas_mode: Arc<AtomicU8>,
    pub cas_attempts: Arc<AtomicU64>,
    pub frontier_path: PathBuf,
    stop: Arc<AtomicBool>,
    join: Option<JoinHandle<QualificationResult<()>>>,
}

impl TrustService {
    pub fn start(root: &Path) -> QualificationResult<Self> {
        fs::create_dir(root)?;
        fs::set_permissions(root, fs::Permissions::from_mode(0o700))?;
        let socket_path = root.join("trust.sock");
        let frontier_path = root.join("release-frontier.json");
        let listener = UnixListener::bind(&socket_path)?;
        fs::set_permissions(&socket_path, fs::Permissions::from_mode(0o600))?;
        listener.set_nonblocking(true)?;
        let seed = [211; 32].into();
        let spki = PqNativeSigningKey::public_spki_from_seed(&seed);
        let id = ml_dsa_65_key_id_from_spki(&spki)?;
        let key = PqNativeSigningKey::from_owned_seed(seed, id)?;
        let config = UnixPqTrustEndpointConfig {
            socket_path,
            peer_uid: fs::metadata(root)?.uid(),
            service_id: "fleet-release-qualification".into(),
            key_generation: 1,
            public_key_id: id,
            public_key_spki: spki.to_vec(),
            timeout_ms: 2000,
        };
        let now = Arc::new(AtomicU64::new(NOW * 1000));
        let advance_clock_after_reads = Arc::new(AtomicU64::new(0));
        let advance_clock_to_ms = Arc::new(AtomicU64::new(0));
        let cas_mode = Arc::new(AtomicU8::new(0));
        let cas_attempts = Arc::new(AtomicU64::new(0));
        let stop = Arc::new(AtomicBool::new(false));
        let (clock, mode, attempts, stopping) = (
            Arc::clone(&now),
            Arc::clone(&cas_mode),
            Arc::clone(&cas_attempts),
            Arc::clone(&stop),
        );
        let path = frontier_path.clone();
        let clock_reads = Arc::clone(&advance_clock_after_reads);
        let clock_target = Arc::clone(&advance_clock_to_ms);
        let join = std::thread::spawn(move || -> QualificationResult<()> {
            let mut deferred = None;
            while !stopping.load(Ordering::Acquire) {
                let (mut stream, _) = match listener.accept() {
                    Ok(connection) => connection,
                    Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                        std::thread::sleep(Duration::from_millis(1));
                        continue;
                    }
                    Err(error) => return Err(error.into()),
                };
                // Darwin inherits the listener flag on accepted sockets.
                stream.set_nonblocking(false)?;
                stream.set_read_timeout(Some(Duration::from_secs(2)))?;
                stream.set_write_timeout(Some(Duration::from_secs(2)))?;
                let mut length = [0; 4];
                if stream.read_exact(&mut length).is_err() {
                    continue;
                }
                let length = u32::from_be_bytes(length) as usize;
                if length > 16 * 1024 {
                    continue;
                }
                let mut raw = vec![0; length];
                stream.read_exact(&mut raw)?;
                let request: PqTrustRequestV2 = serde_json::from_slice(&raw)?;
                if request.service_id != "fleet-release-qualification"
                    || request.key_generation != 1
                {
                    continue;
                }
                let current = read_frontier(&path)?;
                let outcome = match &request.operation {
                    PqTrustOperationV2::ClockNow => {
                        let target = clock_target.load(Ordering::Acquire);
                        if target != 0 {
                            if clock_reads.load(Ordering::Acquire) == 0 {
                                clock.store(target, Ordering::Release);
                                clock_target.store(0, Ordering::Release);
                            } else {
                                clock_reads.fetch_sub(1, Ordering::AcqRel);
                            }
                        }
                        PqTrustOutcomeV2::Clock {
                            unix_ms: clock.load(Ordering::Acquire),
                        }
                    }
                    PqTrustOperationV2::ReleaseFrontierLoad { owner_id } if owner_id == OWNER => {
                        if mode
                            .compare_exchange(
                                NEXT_LOAD_UNAVAILABLE,
                                /*new*/ 0,
                                Ordering::AcqRel,
                                Ordering::Acquire,
                            )
                            .is_ok()
                        {
                            PqTrustOutcomeV2::Unavailable
                        } else {
                            PqTrustOutcomeV2::ReleaseFrontier { value: current }
                        }
                    }
                    PqTrustOperationV2::ReleaseFrontierCompareAndSet {
                        owner_id,
                        expected,
                        next,
                    } if owner_id == OWNER && *expected == current => {
                        attempts.fetch_add(1, Ordering::AcqRel);
                        let behavior = mode.swap(0, Ordering::AcqRel);
                        if behavior == 2 {
                            continue;
                        }
                        let valid = next.validate().is_ok()
                            && match current {
                                None => next.generation == 1,
                                Some(old) => {
                                    old.generation.checked_add(1) == Some(next.generation)
                                        && old.initial_root_sha256 == next.initial_root_sha256
                                }
                            };
                        if !valid {
                            return Err("fixture received invalid release CAS".into());
                        }
                        if behavior == 3 {
                            deferred = Some((*expected, *next));
                            continue;
                        }
                        if let Some((prior_expected, prior_next)) = deferred.take() {
                            if prior_expected != current {
                                return Err(
                                    "deferred fixture CAS has a different predecessor".into()
                                );
                            }
                            write_frontier(&path, &prior_next)?;
                            PqTrustOutcomeV2::Conflict
                        } else {
                            write_frontier(&path, next)?;
                            if behavior == AFTER_CAS_LOAD_UNAVAILABLE {
                                mode.store(NEXT_LOAD_UNAVAILABLE, Ordering::Release);
                            }
                            if behavior == AFTER_CAS_FRONTIER_DRIFT {
                                let mut future = *next;
                                future.generation = future
                                    .generation
                                    .checked_add(1)
                                    .ok_or("fixture future generation overflow")?;
                                write_frontier(&path, &future)?;
                            }
                            if behavior == 1 {
                                continue;
                            }
                            PqTrustOutcomeV2::ReleaseCompareAndSetApplied { value: *next }
                        }
                    }
                    PqTrustOperationV2::ReleaseFrontierCompareAndSet { .. } => {
                        PqTrustOutcomeV2::Conflict
                    }
                    PqTrustOperationV2::ReleaseFrontierLoad { .. }
                    | PqTrustOperationV2::FrontierLoad { .. }
                    | PqTrustOperationV2::FrontierCompareAndSet { .. }
                    | PqTrustOperationV2::LearningFrontierLoad { .. }
                    | PqTrustOperationV2::LearningFrontierCompareAndSet { .. } => {
                        PqTrustOutcomeV2::Unavailable
                    }
                };
                let body = PqTrustResponseBodyV2 {
                    schema_version: 2,
                    request,
                    valid_for_ms: 2000,
                    outcome,
                };
                let signature = key.sign_exact_message(&body.signing_bytes()?)?.to_vec();
                let raw = serde_json::to_vec(&SignedPqTrustResponseV2 { body, signature })?;
                stream.write_all(&(raw.len() as u32).to_be_bytes())?;
                stream.write_all(&raw)?;
            }
            Ok(())
        });
        Ok(Self {
            config,
            now,
            advance_clock_after_reads,
            advance_clock_to_ms,
            cas_mode,
            cas_attempts,
            frontier_path,
            stop,
            join: Some(join),
        })
    }
}

fn write_frontier(path: &Path, next: &ReleaseFrontierV1) -> QualificationResult<()> {
    let temporary = path.with_extension("next");
    fs::write(&temporary, serde_json::to_vec(next)?)?;
    fs::File::open(&temporary)?.sync_all()?;
    fs::rename(&temporary, path)?;
    fs::File::open(path.parent().ok_or("missing fixture parent")?)?.sync_all()?;
    Ok(())
}

pub(crate) fn read_frontier(path: &Path) -> QualificationResult<Option<ReleaseFrontierV1>> {
    match fs::read(path) {
        Ok(bytes) => Ok(Some(serde_json::from_slice(&bytes)?)),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(error.into()),
    }
}

impl Drop for TrustService {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Release);
        if let Some(join) = self.join.take() {
            match join.join() {
                Ok(Ok(())) => {}
                Ok(Err(error)) => panic!("release trust fixture failed: {error}"),
                Err(payload) => std::panic::resume_unwind(payload),
            }
        }
    }
}
