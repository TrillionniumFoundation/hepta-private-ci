//! The installation trust loader uses real Unix authenticated responses. These
//! controlled service keys do not establish independent administration.
use super::*;
use codex_hepta_contracts::authority_trust_unix::PqTrustOperationV2;
use codex_hepta_contracts::authority_trust_unix::PqTrustOutcomeV2;
use codex_hepta_contracts::authority_trust_unix::PqTrustRequestV2;
use codex_hepta_contracts::authority_trust_unix::PqTrustResponseBodyV2;
use codex_hepta_contracts::authority_trust_unix::SignedPqTrustResponseV2;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningSignature as NativeSignature;
use codex_hepta_learning_ledger::LearningTrustFrontier;
use codex_hepta_learning_ledger::LearningVerificationKey;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_learning_ledger::learning_trust_frontier;
use codex_hepta_types::StableId;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixListener;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::thread::JoinHandle;
use std::time::Duration;
use std::time::Instant;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn key(seed: u8) -> PqNativeSigningKey {
    let spki = PqNativeSigningKey::public_spki_from_seed(&[seed; 32].into());
    PqNativeSigningKey::from_owned_seed(
        [seed; 32].into(),
        ml_dsa_65_key_id_from_spki(&spki).unwrap(),
    )
    .unwrap()
}
fn signature(key: &PqNativeSigningKey, bytes: &[u8]) -> NativeSignature {
    NativeSignature::MlDsa65V2(key.sign_exact_message(bytes).unwrap().to_vec())
}

struct Service {
    config: UnixPqTrustEndpointConfig,
    frontier: Arc<Mutex<LearningTrustFrontier>>,
    stop: Arc<AtomicBool>,
    join: Option<JoinHandle<()>>,
}
impl Service {
    fn start(root: &Path, initial: LearningTrustFrontier, binding: Digest32) -> Self {
        std::fs::set_permissions(root, std::fs::Permissions::from_mode(0o700)).unwrap();
        let socket_path = root.join("pq-install.sock");
        let listener = UnixListener::bind(&socket_path).unwrap();
        std::fs::set_permissions(&socket_path, std::fs::Permissions::from_mode(0o600)).unwrap();
        listener.set_nonblocking(true).unwrap();
        let signer = key(/*seed*/ 93);
        let config = UnixPqTrustEndpointConfig {
            socket_path,
            peer_uid: std::fs::metadata(root).unwrap().uid(),
            service_id: "pq-install-trust".to_owned(),
            key_generation: 1,
            public_key_id: signer.public_key_id(),
            public_key_spki: signer.public_spki().to_vec(),
            timeout_ms: 2_000,
        };
        let frontier = Arc::new(Mutex::new(initial));
        let current = Arc::clone(&frontier);
        let stop = Arc::new(AtomicBool::new(false));
        let stopping = Arc::clone(&stop);
        let join = std::thread::spawn(move || {
            let deadline = Instant::now() + Duration::from_secs(30);
            while !stopping.load(Ordering::SeqCst) && Instant::now() < deadline {
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
                            PqTrustOperationV2::ClockNow => PqTrustOutcomeV2::Clock { unix_ms: 50 },
                            PqTrustOperationV2::LearningFrontierLoad { owner_id }
                                if owner_id == &format!("hepta-learning-trust:{binding}") =>
                            {
                                PqTrustOutcomeV2::LearningFrontier {
                                    value: *current.lock().unwrap(),
                                }
                            }
                            PqTrustOperationV2::LearningFrontierLoad { .. }
                            | PqTrustOperationV2::LearningFrontierCompareAndSet { .. }
                            | PqTrustOperationV2::FrontierLoad { .. }
                            | PqTrustOperationV2::FrontierCompareAndSet { .. } => {
                                PqTrustOutcomeV2::Unavailable
                            }
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
                    Err(error) => panic!("trust service: {error}"),
                }
            }
        });
        Self {
            config,
            frontier,
            stop,
            join: Some(join),
        }
    }
}
impl Drop for Service {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::SeqCst);
        if let Some(join) = self.join.take() {
            join.join().unwrap();
        }
    }
}

#[test]
fn pq_installation_authenticates_root_clock_and_current_floor_before_returning_roles() {
    let directory = tempfile::tempdir().unwrap();
    let root_path = directory.path().canonicalize().unwrap();
    let agent_id =
        codex_hepta_contracts::AgentId::parse("00000000-0000-4000-8000-000000000294").unwrap();
    let fleet = codex_hepta_paths::HeptaFleetRoot::parse(root_path.join("fleet")).unwrap();
    let layout = fleet.layout().agent(&agent_id);
    let identity = AgentdIdentity {
        agent_id,
        spawn_generation: 1,
        fleet_root: fleet.as_path().to_path_buf(),
        workspace: root_path.join("workspace"),
        resources: codex_hepta_fleet::ResourceBudget::local_default(),
        home_root: layout.home_root().to_path_buf(),
        run_root: layout.run_root().to_path_buf(),
        control_socket: layout.agentd_control_socket().to_path_buf(),
        app_server_socket: layout.app_server_socket().to_path_buf(),
        layout,
    };
    let role = key(/*seed*/ 91);
    let root_key = key(/*seed*/ 92);
    let binding = digest("pq-install-binding");
    let trust = LearningEvidenceTrustV1 {
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: 1,
        signers: vec![TrustedLearningSignerV1 {
            principal: AuthenticatedPrincipalV1 {
                principal_id: id("generator"),
                credential_chain_digest: digest("generator-credential"),
                signing_key_digest: Digest32::of_bytes(role.public_spki()),
                scope_digest: digest("scope"),
                authority_epoch: 1,
                authenticated_at: 1_000,
                expires_at: 100_000,
            },
            controller_id: id("generator-controller"),
            verifying_key: LearningVerificationKey::MlDsa65V2(role.public_spki().to_vec()),
            roles: vec![LearningEvidenceRoleV1::Generator],
            revoked_at: None,
        }],
    };
    let root = LearningTrustRootV1 {
        root_id: id("installation-root"),
        scope_digest: trust.scope_digest,
        verifying_key: LearningVerificationKey::MlDsa65V2(root_key.public_spki().to_vec()),
        valid_from: 1_000,
        expires_at: 100_000,
        revoked_at: None,
    };
    let mut signed = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("installation-distribution"),
            generation: 1,
            effective_at: 10_000,
            trust: trust.clone(),
        },
        root_id: root.root_id.clone(),
        issued_at: 5_000,
        expires_at: 90_000,
        signature: NativeSignature::MlDsa65V2(Vec::new()),
    };
    signed.signature = signature(&root_key, &signed.signing_bytes().unwrap());
    let activated = activate_learning_trust(
        &root,
        signed.clone(),
        /*previous*/ None,
        /*now*/ 50_000,
    )
    .unwrap();
    let authority_root = root_path.join("authority").join("nested");
    std::fs::create_dir_all(&authority_root).unwrap();
    let service = Service::start(
        &authority_root,
        learning_trust_frontier(&activated),
        binding,
    );
    let activation = || PqLearningActivationV2 {
        root_id: root.root_id.clone().into(),
        root_scope_digest: root.scope_digest.into(),
        root_verifying_key: root.verifying_key.clone().into(),
        root_valid_from: root.valid_from,
        root_expires_at: root.expires_at,
        root_revoked_at: None,
        distribution_id: signed.distribution.distribution_id.clone().into(),
        generation: 1,
        effective_at: 10_000,
        issued_at: 5_000,
        expires_at: 90_000,
        signature: signed.signature.clone().into(),
        clock: service.config.clone(),
        frontier: service.config.clone(),
    };
    let loaded = load(
        trust.clone(),
        LearningAuthenticationProfile::MlDsa65V2,
        Some(activation()),
        binding,
        &identity,
    )
    .unwrap();
    assert_eq!(
        loaded.verifier.authentication_profile(),
        LearningAuthenticationProfile::MlDsa65V2
    );
    assert_eq!(now_micros(&loaded.clock).unwrap(), 50_000);
    // The symlink is an ancestor, so lstat of the socket and its immediate
    // parent alone cannot enforce separation from the Agentd-owned tree.
    let alias = root_path.join("authority-alias");
    std::os::unix::fs::symlink(root_path.join("authority"), &alias).unwrap();
    let mut aliased = activation();
    aliased.clock.socket_path = alias.join("nested").join("pq-install.sock");
    aliased.frontier.socket_path = aliased.clock.socket_path.clone();
    let mut owned_identity = identity.clone();
    owned_identity.workspace = root_path.join("authority");
    let rejected = load(
        trust.clone(),
        LearningAuthenticationProfile::MlDsa65V2,
        Some(aliased),
        binding,
        &owned_identity,
    );
    assert!(matches!(rejected, Err(error) if error.to_string().contains("canonical")));
    let payload = b"install-role-evidence";
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id("generator-evidence"),
        principal_id: id("generator"),
        role: LearningEvidenceRoleV1::Generator,
        trust_digest: loaded.verifier.trust_digest(),
        scope_digest: trust.scope_digest,
        objective_digest: trust.objective_digest,
        authority_epoch: 1,
        issued_at: 45_000,
        expires_at: 90_000,
        payload_digest: Digest32::of_bytes(payload),
        signature: NativeSignature::MlDsa65V2(Vec::new()),
    };
    evidence.signature = signature(&role, &evidence.signing_bytes());
    let opaque = loaded
        .verifier
        .verify(
            LearningEvidenceRoleV1::Generator,
            &evidence,
            payload,
            /*now*/ 1,
        )
        .unwrap();
    assert_eq!(opaque.validate_at(/*supplied_now*/ 1), Ok(50_000));
    let mut downgrade = activation();
    downgrade.signature = NativeSignature::ClassicalV1(vec![0; 64]).into();
    assert!(
        load(
            trust.clone(),
            LearningAuthenticationProfile::MlDsa65V2,
            Some(downgrade),
            binding,
            &identity
        )
        .is_err()
    );
    assert!(
        load(
            trust.clone(),
            LearningAuthenticationProfile::MlDsa65V2,
            None,
            binding,
            &identity
        )
        .is_err()
    );
    assert!(
        load(
            trust.clone(),
            LearningAuthenticationProfile::ClassicalV1,
            Some(activation()),
            binding,
            &identity
        )
        .is_err()
    );
    {
        let mut current = service.frontier.lock().unwrap();
        current.generation += 1;
        current.distribution_digest = *digest("rotated-distribution").as_array();
    }
    assert!(opaque.validate_at(/*supplied_now*/ 50_000).is_err());
    assert!(
        load(
            trust,
            LearningAuthenticationProfile::MlDsa65V2,
            Some(activation()),
            binding,
            &identity
        )
        .is_err()
    );
    drop(service);
    assert!(
        loaded
            .verifier
            .verify(
                LearningEvidenceRoleV1::Generator,
                &evidence,
                payload,
                /*now*/ 50_000
            )
            .is_err()
    );
}
