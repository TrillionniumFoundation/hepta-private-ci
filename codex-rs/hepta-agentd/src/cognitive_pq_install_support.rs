//! Disposable signing keys and a signed Unix authority fixture, never a verifier substitute.
use super::*;
use codex_hepta_contracts::authority_trust_unix::*;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use ed25519_dalek::Signer as _;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixListener;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::thread::JoinHandle;
use std::time::Duration;

pub(super) enum TestKey {
    Classic(Box<ed25519_dalek::SigningKey>),
    Pq(Box<PqNativeSigningKey>),
}
impl TestKey {
    pub fn new(profile: LearningAuthenticationProfile, seed: u8) -> Self {
        match profile {
            LearningAuthenticationProfile::ClassicalV1 => {
                Self::Classic(Box::new(ed25519_dalek::SigningKey::from_bytes(&[seed; 32])))
            }
            LearningAuthenticationProfile::MlDsa65V2 => {
                let spki = PqNativeSigningKey::public_spki_from_seed(&[seed; 32].into());
                Self::Pq(Box::new(
                    PqNativeSigningKey::from_owned_seed(
                        [seed; 32].into(),
                        ml_dsa_65_key_id_from_spki(&spki).unwrap(),
                    )
                    .unwrap(),
                ))
            }
        }
    }
    pub fn key(&self) -> ledger::LearningVerificationKey {
        match self {
            Self::Classic(key) => key.verifying_key().to_bytes().into(),
            Self::Pq(key) => ledger::LearningVerificationKey::MlDsa65V2(key.public_spki().to_vec()),
        }
    }
    pub fn placeholder(&self) -> ledger::LearningSignature {
        match self {
            Self::Classic(_) => [0; 64].into(),
            Self::Pq(_) => ledger::LearningSignature::MlDsa65V2(Vec::new()),
        }
    }
    pub fn sign(&self, message: &[u8]) -> ledger::LearningSignature {
        match self {
            Self::Classic(key) => key.sign(message).to_bytes().into(),
            Self::Pq(key) => ledger::LearningSignature::MlDsa65V2(
                key.sign_exact_message(message).unwrap().to_vec(),
            ),
        }
    }
}

pub(super) struct Roles {
    pub keys: Vec<TestKey>,
    pub activated: ledger::ActivatedLearningTrustV1,
    pub distribution: ledger::SignedLearningTrustDistributionV1,
    pub root: ledger::LearningTrustRootV1,
    pub base: u64,
}
impl Roles {
    pub fn new(profile: LearningAuthenticationProfile) -> Self {
        let base = support::micros() - 60_000_000;
        let keys: Vec<_> = (71..77).map(|seed| TestKey::new(profile, seed)).collect();
        let names = ["generator", "evaluator", "observer", "selector"];
        let roles = [
            ledger::LearningEvidenceRoleV1::Generator,
            ledger::LearningEvidenceRoleV1::Evaluator,
            ledger::LearningEvidenceRoleV1::Observer,
            ledger::LearningEvidenceRoleV1::Selector,
        ];
        let trust = ledger::LearningEvidenceTrustV1 {
            scope_digest: hash("native-pq-install-scope"),
            objective_digest: hash("native-pq-install-objective"),
            authority_epoch: 1,
            signers: (0..4)
                .map(|i| ledger::TrustedLearningSignerV1 {
                    principal: ledger::AuthenticatedPrincipalV1 {
                        principal_id: id(names[i]),
                        credential_chain_digest: hash(names[i]),
                        signing_key_digest: Digest32::of_bytes(&keys[i].key()),
                        scope_digest: hash("native-pq-install-scope"),
                        authority_epoch: 1,
                        authenticated_at: base,
                        expires_at: base + 3_600_000_000,
                    },
                    controller_id: id(&format!("controller-{}", names[i])),
                    verifying_key: keys[i].key(),
                    roles: vec![roles[i]],
                    revoked_at: None,
                })
                .collect(),
        };
        let root = ledger::LearningTrustRootV1 {
            root_id: id("native-install-root"),
            scope_digest: trust.scope_digest,
            verifying_key: keys[5].key(),
            valid_from: base,
            expires_at: base + 3_600_000_000,
            revoked_at: None,
        };
        let mut distribution = ledger::SignedLearningTrustDistributionV1 {
            distribution: ledger::LearningTrustDistributionV1 {
                distribution_id: id("native-install-distribution"),
                generation: 1,
                effective_at: base,
                trust,
            },
            root_id: root.root_id.clone(),
            issued_at: base,
            expires_at: root.expires_at,
            signature: keys[5].placeholder(),
        };
        distribution.signature = keys[5].sign(&distribution.signing_bytes().unwrap());
        let activated = ledger::activate_learning_trust(
            &root,
            distribution.clone(),
            /*previous*/ None,
            base,
        )
        .unwrap();
        Self {
            keys,
            activated,
            distribution,
            root,
            base,
        }
    }
    pub fn evidence(
        &self,
        index: usize,
        payload: &[u8],
        offset: u64,
    ) -> ledger::SignedLearningEvidenceV1 {
        let trust = &self.distribution.distribution.trust;
        let signer = &trust.signers[index];
        let mut evidence = ledger::SignedLearningEvidenceV1 {
            evidence_id: id(&format!(
                "{}-{offset}-{}",
                signer.principal.principal_id,
                Digest32::of_bytes(payload)
            )),
            principal_id: signer.principal.principal_id.clone(),
            role: signer.roles[0],
            trust_digest: self.activated.verifier().trust_digest(),
            scope_digest: trust.scope_digest,
            objective_digest: trust.objective_digest,
            authority_epoch: 1,
            issued_at: self.base + offset,
            expires_at: self.root.expires_at,
            payload_digest: Digest32::of_bytes(payload),
            signature: self.keys[index].placeholder(),
        };
        evidence.signature = self.keys[index].sign(&evidence.signing_bytes());
        evidence
    }
}
impl publication::Publisher for Roles {
    fn key(&self) -> ledger::LearningVerificationKey {
        self.keys[4].key()
    }
    fn window(&self) -> (u64, u64) {
        (self.base, self.root.expires_at)
    }
    fn sign(&mut self, bytes: &[u8]) -> ledger::LearningSignature {
        self.keys[4].sign(bytes)
    }
}

// This service is outside history, CURRENT and Agentd-owned directories. Its
// independent test state is retained across all native consumer reopens.
pub(super) struct Service {
    pub config: UnixPqTrustEndpointConfig,
    pub frontier: Arc<Mutex<ledger::LearningTrustFrontier>>,
    pub clock: Arc<AtomicU64>,
    stop: Arc<AtomicBool>,
    join: Option<JoinHandle<()>>,
}
impl Service {
    pub fn start(root: &Path, roles: &Roles) -> Self {
        std::fs::create_dir(root).unwrap();
        std::fs::set_permissions(root, std::fs::Permissions::from_mode(0o700)).unwrap();
        let socket_path = root.join("authority.sock");
        let listener = UnixListener::bind(&socket_path).unwrap();
        std::fs::set_permissions(&socket_path, std::fs::Permissions::from_mode(0o600)).unwrap();
        listener.set_nonblocking(true).unwrap();
        let TestKey::Pq(signer) = TestKey::new(PQ, /*seed*/ 94) else {
            unreachable!()
        };
        let config = UnixPqTrustEndpointConfig {
            socket_path,
            peer_uid: std::fs::metadata(root).unwrap().uid(),
            service_id: "native-install-authority".into(),
            key_generation: 1,
            public_key_id: signer.public_key_id(),
            public_key_spki: signer.public_spki().to_vec(),
            timeout_ms: 2_000,
        };
        let frontier = Arc::new(Mutex::new(ledger::learning_trust_frontier(
            &roles.activated,
        )));
        let current = Arc::clone(&frontier);
        let stop = Arc::new(AtomicBool::new(false));
        let stopping = Arc::clone(&stop);
        let clock = Arc::new(AtomicU64::new((roles.base + 70_000_000) / 1_000));
        let now = Arc::clone(&clock);
        let join = std::thread::spawn(move || {
            while !stopping.load(Ordering::SeqCst) {
                match listener.accept() {
                    Ok((mut stream, _)) => {
                        stream
                            .set_read_timeout(Some(Duration::from_secs(2)))
                            .unwrap();
                        stream
                            .set_write_timeout(Some(Duration::from_secs(2)))
                            .unwrap();
                        let mut size = [0; 4];
                        stream.read_exact(&mut size).unwrap();
                        let size = u32::from_be_bytes(size) as usize;
                        assert!(size <= 16 * 1_024);
                        let mut bytes = vec![0; size];
                        stream.read_exact(&mut bytes).unwrap();
                        let request: PqTrustRequestV2 = serde_json::from_slice(&bytes).unwrap();
                        let outcome = match &request.operation {
                            PqTrustOperationV2::ClockNow => PqTrustOutcomeV2::Clock {
                                unix_ms: now.load(Ordering::SeqCst),
                            },
                            PqTrustOperationV2::LearningFrontierLoad { owner_id }
                                if owner_id
                                    == &format!(
                                        "hepta-learning-trust:{}",
                                        hash("local-three-generation-ledger")
                                    ) =>
                            {
                                PqTrustOutcomeV2::LearningFrontier {
                                    value: *current.lock().unwrap(),
                                }
                            }
                            _ => PqTrustOutcomeV2::Unavailable,
                        };
                        let body = PqTrustResponseBodyV2 {
                            schema_version: 2,
                            request,
                            valid_for_ms: 2_000,
                            outcome,
                        };
                        let signature = signer
                            .sign_exact_message(&body.signing_bytes().unwrap())
                            .unwrap()
                            .to_vec();
                        let bytes =
                            serde_json::to_vec(&SignedPqTrustResponseV2 { body, signature })
                                .unwrap();
                        stream
                            .write_all(&(bytes.len() as u32).to_be_bytes())
                            .unwrap();
                        stream.write_all(&bytes).unwrap();
                    }
                    Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                        std::thread::sleep(Duration::from_millis(1))
                    }
                    Err(error) => panic!("fixture authority: {error}"),
                }
            }
        });
        Self {
            config,
            frontier,
            clock,
            stop,
            join: Some(join),
        }
    }
}
impl Drop for Service {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::SeqCst);
        self.join.take().unwrap().join().unwrap();
    }
}
