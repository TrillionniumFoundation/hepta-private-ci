//! Qualification inputs only. No fixture is a production trust source.

use super::*;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseIssuerTrustKey;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_memory::CognitiveRecoveryAnchor;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::ObjectiveSenderCheckpointError;
use codex_hepta_memory::ObjectiveSenderWriterFence;
use codex_hepta_memory::ProductionAuthorityToken;
use codex_hepta_memory::ProductionDispatchFuture;
use codex_hepta_memory::ProductionDispatchRequest;
use codex_hepta_memory::ProductionOutboxTarget;
use codex_hepta_memory::ProductionTargetOutcome;
use codex_hepta_paths::HeptaFleetRoot;
use ed25519_dalek::SigningKey;
use std::collections::BTreeSet;
use std::error::Error;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

pub(super) const EXPIRES: u64 = 4_000_000_000;
pub(super) const LIVE_MS: u64 = 2_000_000_000_000;

pub(super) struct Clock {
    pub now_ms: AtomicU64,
    pub unavailable: AtomicBool,
    pub calls: AtomicUsize,
}

impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        if self.unavailable.load(Ordering::SeqCst) {
            return Err(AuthorityTrustError::Unavailable);
        }
        Ok(self.now_ms.load(Ordering::SeqCst))
    }
}

pub(super) struct Verifier {
    pub calls: AtomicUsize,
    pub expire_at_call: AtomicUsize,
    pub unavailable_at_call: AtomicUsize,
    pub reject_at_call: AtomicUsize,
    clock: Arc<Clock>,
}

impl ProductionAuthorityVerifier for Verifier {
    fn verify(
        &self,
        authority: &ProductionAuthorityLease,
        expected: &AgentId,
    ) -> Result<(), String> {
        let call = self.calls.fetch_add(1, Ordering::SeqCst) + 1;
        if &authority.agent_id != expected
            || authority.grant_digest != Sha256Digest::for_bytes(b"composition-fixture")
            || call == self.reject_at_call.load(Ordering::SeqCst)
        {
            return Err("fixture original verifier rejected authority".to_string());
        }
        if call == self.expire_at_call.load(Ordering::SeqCst) {
            self.clock.now_ms.store(EXPIRES * 1_000, Ordering::SeqCst);
        }
        if call == self.unavailable_at_call.load(Ordering::SeqCst) {
            self.clock.unavailable.store(true, Ordering::SeqCst);
        }
        Ok(())
    }
}

pub(super) struct Frontier {
    head: FinalUseFrontier,
    pub denied: AtomicBool,
    pub loads: AtomicUsize,
}

impl AuthorityFrontierStore<FinalUseFrontier> for Frontier {
    fn load(&self, owner: &str) -> Result<FinalUseFrontier, AuthorityTrustError> {
        self.loads.fetch_add(1, Ordering::SeqCst);
        if owner != "composition-fixture-issuer" || self.denied.load(Ordering::SeqCst) {
            return Err(AuthorityTrustError::Unavailable);
        }
        Ok(self.head)
    }

    fn compare_and_set(
        &self,
        _owner: &str,
        _expected: &FinalUseFrontier,
        _next: &FinalUseFrontier,
    ) -> Result<(), AuthorityTrustError> {
        // Bootstrap must never claim a grant or mutate the external frontier.
        Err(AuthorityTrustError::Unavailable)
    }
}

#[derive(Clone, Copy)]
pub(super) enum CheckpointMode {
    Accept,
    Refuse,
    Hold,
    Mismatch,
    ExpireAfterAck,
    UnavailableAfterAck,
    RevokeAfterAck,
}

pub(super) struct Checkpoint {
    pub mode: Mutex<CheckpointMode>,
    pub seen: Mutex<Vec<(CognitiveRecoveryAnchor, ObjectiveSenderWriterFence)>>,
    clock: Arc<Clock>,
    verifier: Arc<Verifier>,
}

impl ObjectiveSenderCheckpoint for Checkpoint {
    async fn acknowledge_current(
        &self,
        current: &CognitiveRecoveryAnchor,
        writer: &ObjectiveSenderWriterFence,
    ) -> Result<CognitiveRecoveryAnchor, ObjectiveSenderCheckpointError> {
        let mode = *self.mode.lock().unwrap();
        self.seen
            .lock()
            .unwrap()
            .push((current.clone(), writer.clone()));
        match mode {
            CheckpointMode::Accept => {}
            CheckpointMode::Refuse => return Err(ObjectiveSenderCheckpointError::Refused),
            CheckpointMode::Hold => std::future::pending::<()>().await,
            CheckpointMode::Mismatch => {
                let mut other = current.clone();
                other.state_digest = Sha256Digest::for_bytes(b"wrong-bootstrap-cut");
                return Ok(other);
            }
            CheckpointMode::ExpireAfterAck => {
                self.clock.now_ms.store(EXPIRES * 1_000, Ordering::SeqCst);
            }
            CheckpointMode::UnavailableAfterAck => {
                self.clock.unavailable.store(true, Ordering::SeqCst);
            }
            CheckpointMode::RevokeAfterAck => {
                self.verifier.reject_at_call.store(
                    self.verifier.calls.load(Ordering::SeqCst) + 1,
                    Ordering::SeqCst,
                );
            }
        }
        Ok(current.clone())
    }
}

pub(super) struct Target {
    pub metadata_calls: AtomicUsize,
    pub effects: AtomicUsize,
    pub late_clock_fault: AtomicUsize,
    pub ack_failure: Mutex<Option<AckFailure>>,
    clock: Arc<Clock>,
    verifier: Arc<Verifier>,
}

pub(super) struct AckFailure {
    pub socket: UnixDatagram,
    pub observed: Option<serde_json::Value>,
    pub fault: usize,
}

impl ProductionOutboxTarget for Target {
    fn dispatch<'a>(&'a self, _request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        self.effects.fetch_add(1, Ordering::SeqCst);
        Box::pin(async {
            ProductionTargetOutcome::Rejected {
                reason: "bootstrap fixture never permits an effect".to_string(),
            }
        })
    }
}

impl FinalUseProductionOutboxTarget for Target {
    fn destination_id(&self) -> &str {
        self.metadata_calls.fetch_add(1, Ordering::SeqCst);
        if let Some(probe) = self.ack_failure.lock().unwrap().as_mut() {
            let mut bytes = [0_u8; 1024];
            match probe.socket.recv(&mut bytes) {
                Ok(length) => {
                    probe.observed = Some(serde_json::from_slice(&bytes[..length]).unwrap());
                    match probe.fault {
                        1 => self.clock.now_ms.store(EXPIRES * 1_000, Ordering::SeqCst),
                        2 => self.clock.unavailable.store(true, Ordering::SeqCst),
                        _ => self.verifier.reject_at_call.store(
                            self.verifier.calls.load(Ordering::SeqCst) + 1,
                            Ordering::SeqCst,
                        ),
                    }
                }
                Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {}
                result => panic!("unexpected fixture ACK observation: {result:?}"),
            }
        }
        // Preflight is original verifier call 1. Later metadata validation
        // occurs only after recovery's live authority checks have run.
        if self.verifier.calls.load(Ordering::SeqCst) > 1 {
            match self.late_clock_fault.load(Ordering::SeqCst) {
                1 => self.clock.now_ms.store(EXPIRES * 1_000, Ordering::SeqCst),
                2 => self.clock.unavailable.store(true, Ordering::SeqCst),
                _ => {}
            }
        }
        "composition-fixture-target"
    }
}

pub(super) struct Probes {
    pub clock: Arc<Clock>,
    pub verifier: Arc<Verifier>,
    pub target: Arc<Target>,
    pub frontier: Arc<Frontier>,
    pub checkpoint: Arc<Checkpoint>,
}

pub(super) struct Fixture {
    directory: tempfile::TempDir,
    next_inputs: AtomicUsize,
    pub cut: CognitiveRecoveryAnchor,
    authority: ProductionAuthorityLease,
}

impl Fixture {
    pub async fn new() -> Result<(AgentdConfig, Self), Box<dyn Error>> {
        let directory = tempfile::tempdir()?;
        let root = directory.path().canonicalize()?;
        fs::set_permissions(&root, fs::Permissions::from_mode(0o700))?;
        let fleet_path = root.join("fleet");
        let fleet = HeptaFleetRoot::parse(fleet_path.clone())?;
        let registry = FleetRegistry::initialize(fleet.clone())?;
        let workspace = root.join("workspace");
        fs::create_dir(&workspace)?;
        let owner = AgentId::parse("00000000-0000-4000-8000-00000000c062")?;
        let record = registry.register(AgentManifest::new(
            owner.clone(),
            WorkspaceBinding::new(workspace.clone(), &fleet)?,
            ResourceBudget::local_default(),
        )?)?;
        registry.compare_and_transition(&owner, 0, AgentLifecycle::Starting)?;
        let config = AgentdConfig::load(
            fleet_path,
            owner.clone(),
            1,
            record.layout.home_root().to_path_buf(),
            record.layout.run_root().to_path_buf(),
            record.layout.home_root().to_path_buf(),
            workspace,
        )?;
        // Qualification-only genesis. The product API accepts only an
        // independently retained current cut and never captures one itself.
        let store = CognitiveStore::open(&config.identity().layout).await?;
        let cut = store.recovery_anchor().await?;
        store.close().await;
        let authority = ProductionAuthorityLease::from_verified_parts(
            owner,
            Sha256Digest::for_bytes(b"composition-fixture"),
            13,
            17,
            EXPIRES,
            ProductionAuthorityToken::from_verified_bytes(b"composition-fixture-token".to_vec())?,
        )?;
        Ok((
            config,
            Self {
                directory,
                next_inputs: AtomicUsize::new(0),
                cut,
                authority,
            },
        ))
    }

    pub fn inputs(
        &self,
    ) -> Result<
        (
            AgentdProductionHostInputs<'_, Checkpoint>,
            Probes,
            UnixStream,
        ),
        Box<dyn Error>,
    > {
        let state_directory = self.directory.path().join(format!(
            "final-use-{}",
            self.next_inputs.fetch_add(1, Ordering::SeqCst)
        ));
        fs::create_dir(&state_directory)?;
        fs::set_permissions(&state_directory, fs::Permissions::from_mode(0o700))?;
        let head = FinalUseRevocations {
            authority_epoch: 19,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        };
        let clock = Arc::new(Clock {
            now_ms: AtomicU64::new(LIVE_MS),
            unavailable: AtomicBool::new(false),
            calls: AtomicUsize::new(0),
        });
        let verifier = Arc::new(Verifier {
            calls: AtomicUsize::new(0),
            expire_at_call: AtomicUsize::new(0),
            unavailable_at_call: AtomicUsize::new(0),
            reject_at_call: AtomicUsize::new(0),
            clock: clock.clone(),
        });
        let target = Arc::new(Target {
            metadata_calls: AtomicUsize::new(0),
            effects: AtomicUsize::new(0),
            late_clock_fault: AtomicUsize::new(0),
            ack_failure: Mutex::new(None),
            clock: clock.clone(),
            verifier: verifier.clone(),
        });
        let frontier = Arc::new(Frontier {
            head: FinalUseFrontier::for_initial_head(&head)?,
            denied: AtomicBool::new(false),
            loads: AtomicUsize::new(0),
        });
        let checkpoint = Arc::new(Checkpoint {
            mode: Mutex::new(CheckpointMode::Accept),
            seen: Mutex::new(Vec::new()),
            clock: clock.clone(),
            verifier: verifier.clone(),
        });
        let (issuer_stream, peer) = UnixStream::pair()?;
        let inputs = AgentdProductionHostInputs {
            current_cut: CognitiveRecoveryRequirement::ExactCurrentCut(&self.cut),
            checkpoint: Arc::clone(&checkpoint),
            checkpoint_deadline: Duration::from_secs(1),
            authority: self.authority.clone(),
            verifier: verifier.clone(),
            lease_id: "composition-fixture-lease".to_string(),
            lease_generation: 1,
            final_use: AgentdFinalUseHostInputs {
                state_directory,
                signer_id: "composition-fixture-issuer".to_string(),
                issuer_keys: vec![FinalUseIssuerTrustKey {
                    key_id: "fixture-only".to_string(),
                    verifying_key: SigningKey::from_bytes(&[61; 32]).verifying_key().to_bytes(),
                    not_before_authority_epoch: 19,
                    not_after_authority_epoch: 19,
                }],
                revocations: head,
                clock: clock.clone(),
                frontier_store: frontier.clone(),
            },
            issuer_stream,
            issuer_peer: AgentdFinalUseIssuerPeer {
                // SAFETY: geteuid has no preconditions and only reads process identity.
                uid: unsafe { libc::geteuid() },
                pid: std::process::id(),
            },
            issuer_timeout: Duration::from_secs(1),
            target: target.clone(),
            reconcile_interval: Duration::from_millis(20),
            notes: None,
        };
        Ok((
            inputs,
            Probes {
                clock,
                verifier,
                target,
                frontier,
                checkpoint,
            },
            peer,
        ))
    }
}
