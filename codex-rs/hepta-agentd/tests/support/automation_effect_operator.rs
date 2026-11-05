//! Controlled operator material for one real Agentd process test only.
//! Its keys and in-test services are not independent deployment custody.
use super::*;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::FinalUseAuthenticationProfile;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocationUpdate;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::PqAuthorityTrustKey;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use codex_hepta_contracts::authority_trust_unix::PqTrustOperationV2;
use codex_hepta_contracts::authority_trust_unix::PqTrustOutcomeV2;
use codex_hepta_contracts::authority_trust_unix::PqTrustRequestV2;
use codex_hepta_contracts::authority_trust_unix::PqTrustResponseBodyV2;
use codex_hepta_contracts::authority_trust_unix::SignedPqTrustResponseV2;
use codex_hepta_contracts::authority_trust_unix::UnixPqAuthorityClock;
use codex_hepta_contracts::authority_trust_unix::UnixPqFinalUseFrontier;
use codex_hepta_contracts::authority_trust_unix::UnixPqTrustEndpointConfig;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use codex_model_provider::HttpProviderEffectConfig;
use codex_model_provider::HttpProviderEffectContractAttestation;
use reqwest::header::HeaderMap;
use std::collections::BTreeSet;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixListener;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::thread::JoinHandle;
use std::thread::{self};

const SIGNER: &str = "test-only-effect-grant-owner";
const FEED: &str = "test-only-effect-revocation-owner";

fn signing_key(seed: u8) -> anyhow::Result<PqNativeSigningKey> {
    let spki = PqNativeSigningKey::public_spki_from_seed(&[seed; 32].into());
    Ok(PqNativeSigningKey::from_owned_seed(
        [seed; 32].into(),
        ml_dsa_65_key_id_from_spki(&spki)?,
    )?)
}

fn pinned(key: &PqNativeSigningKey, name: &str) -> PqAuthorityTrustKey {
    PqAuthorityTrustKey {
        key_id: name.into(),
        public_key_id: key.public_key_id(),
        public_key_spki: key.public_spki().to_vec(),
        not_before_authority_epoch: 9,
        not_after_authority_epoch: 10,
    }
}

pub(super) fn write_private(path: &Path, value: &impl serde::Serialize) -> anyhow::Result<()> {
    fs::write(path, serde_json::to_vec(value)?)?;
    fs::set_permissions(path, fs::Permissions::from_mode(0o600))?;
    Ok(())
}

#[derive(Clone, Copy)]
enum ServiceRole {
    Clock,
    Frontier,
}

pub(super) struct Service {
    pub(super) config: UnixPqTrustEndpointConfig,
    pub(super) frontier: Arc<Mutex<FinalUseFrontier>>,
    pub(super) now: Arc<AtomicU64>,
    pub(super) cas_count: Arc<AtomicUsize>,
    _available: Arc<AtomicBool>,
    stop: Arc<AtomicBool>,
    join: Option<JoinHandle<anyhow::Result<()>>>,
}

impl Service {
    fn start(
        root: &Path,
        role: ServiceRole,
        initial: FinalUseFrontier,
        now_ms: u64,
    ) -> anyhow::Result<Self> {
        let (name, seed) = match role {
            ServiceRole::Clock => ("clock", 74),
            ServiceRole::Frontier => ("frontier", 75),
        };
        let signer = signing_key(seed)?;
        let socket_path = root.join(format!("{name}.sock"));
        let listener = UnixListener::bind(&socket_path)?;
        fs::set_permissions(&socket_path, fs::Permissions::from_mode(0o600))?;
        listener.set_nonblocking(true)?;
        let config = UnixPqTrustEndpointConfig {
            socket_path,
            peer_uid: fs::metadata(root)?.uid(),
            service_id: format!("pq-effect-{name}"),
            key_generation: 1,
            public_key_id: signer.public_key_id(),
            public_key_spki: signer.public_spki().to_vec(),
            timeout_ms: 2000,
        };
        let frontier = Arc::new(Mutex::new(initial));
        let current = Arc::clone(&frontier);
        let now = Arc::new(AtomicU64::new(now_ms));
        let clock = Arc::clone(&now);
        let cas_count = Arc::new(AtomicUsize::new(0));
        let cas = Arc::clone(&cas_count);
        let available = Arc::new(AtomicBool::new(true));
        let serving = Arc::clone(&available);
        let stop = Arc::new(AtomicBool::new(false));
        let stopping = Arc::clone(&stop);
        let join = thread::spawn(move || -> anyhow::Result<()> {
            let deadline = Instant::now() + Duration::from_secs(120);
            while !stopping.load(Ordering::SeqCst) && Instant::now() < deadline {
                match listener.accept() {
                    Ok((mut stream, _)) => {
                        stream.set_read_timeout(Some(Duration::from_secs(2)))?;
                        stream.set_write_timeout(Some(Duration::from_secs(2)))?;
                        let mut size = [0; 4];
                        stream.read_exact(&mut size)?;
                        let size = u32::from_be_bytes(size) as usize;
                        anyhow::ensure!(size <= 16 * 1024, "bounded trust request");
                        let mut bytes = vec![0; size];
                        stream.read_exact(&mut bytes)?;
                        let request: PqTrustRequestV2 = serde_json::from_slice(&bytes)?;
                        let outcome = if serving.load(Ordering::SeqCst) {
                            match (&role, &request.operation) {
                                (ServiceRole::Clock, PqTrustOperationV2::ClockNow) => {
                                    PqTrustOutcomeV2::Clock {
                                        unix_ms: clock.load(Ordering::SeqCst),
                                    }
                                }
                                (
                                    ServiceRole::Frontier,
                                    PqTrustOperationV2::FrontierLoad { owner_id },
                                ) if owner_id == SIGNER => PqTrustOutcomeV2::Frontier {
                                    value: *current.lock().unwrap(),
                                },
                                (
                                    ServiceRole::Frontier,
                                    PqTrustOperationV2::FrontierCompareAndSet {
                                        owner_id,
                                        expected,
                                        next,
                                    },
                                ) if owner_id == SIGNER => {
                                    let mut value = current.lock().unwrap();
                                    if &*value == expected {
                                        *value = *next;
                                        cas.fetch_add(1, Ordering::SeqCst);
                                        PqTrustOutcomeV2::CompareAndSetApplied { value: *next }
                                    } else {
                                        PqTrustOutcomeV2::Conflict
                                    }
                                }
                                (
                                    ServiceRole::Clock,
                                    PqTrustOperationV2::FrontierLoad { .. }
                                    | PqTrustOperationV2::FrontierCompareAndSet { .. }
                                    | PqTrustOperationV2::LearningFrontierLoad { .. }
                                    | PqTrustOperationV2::LearningFrontierCompareAndSet { .. },
                                )
                                | (
                                    ServiceRole::Frontier,
                                    PqTrustOperationV2::ClockNow
                                    | PqTrustOperationV2::FrontierLoad { .. }
                                    | PqTrustOperationV2::FrontierCompareAndSet { .. }
                                    | PqTrustOperationV2::LearningFrontierLoad { .. }
                                    | PqTrustOperationV2::LearningFrontierCompareAndSet { .. },
                                ) => PqTrustOutcomeV2::Unavailable,
                            }
                        } else {
                            PqTrustOutcomeV2::Unavailable
                        };
                        let body = PqTrustResponseBodyV2 {
                            schema_version: 2,
                            request,
                            valid_for_ms: 2000,
                            outcome,
                        };
                        let signature = signer.sign_exact_message(&body.signing_bytes()?)?.to_vec();
                        let bytes =
                            serde_json::to_vec(&SignedPqTrustResponseV2 { body, signature })?;
                        stream.write_all(&(bytes.len() as u32).to_be_bytes())?;
                        stream.write_all(&bytes)?;
                    }
                    Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                        thread::sleep(Duration::from_millis(1))
                    }
                    Err(error) => return Err(error.into()),
                }
            }
            Ok(())
        });
        Ok(Self {
            config,
            frontier,
            now,
            cas_count,
            _available: available,
            stop,
            join: Some(join),
        })
    }
}

impl Drop for Service {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::SeqCst);
        if let Some(join) = self.join.take() {
            match join.join() {
                Ok(Ok(())) => {}
                Ok(Err(error)) => panic!("PQ effect service failed: {error}"),
                Err(panic) => std::panic::resume_unwind(panic),
            }
        }
    }
}

pub(super) struct Operator {
    pub(super) clock: Service,
    pub(super) frontier: Service,
    pub(super) path: PathBuf,
    pub(super) config: Value,
    pub(super) now: u64,
    issuer: PqNativeSigningKey,
    contract: PqNativeSigningKey,
    _external: tempfile::TempDir,
}

impl Operator {
    pub(super) fn new(agent: &AgentFixture, generation: u64, uri: &str) -> Result<Self> {
        let external = tempfile::tempdir()?;
        let root = external.path().canonicalize()?;
        fs::set_permissions(&root, fs::Permissions::from_mode(0o700))?;
        let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
        let head = FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        };
        let initial = FinalUseFrontier::for_initial_head_with_profile(
            &head,
            FinalUseAuthenticationProfile::MlDsa65V2,
        )?;
        let clock = Service::start(&root, ServiceRole::Clock, initial, now)?;
        let frontier = Service::start(&root, ServiceRole::Frontier, initial, now)?;
        let contract = signing_key(/*seed*/ 71)?;
        let issuer = signing_key(/*seed*/ 72)?;
        let feed_signer = signing_key(/*seed*/ 73)?;
        let feed_path = root.join("signed-feed.json");
        let update = FinalUseRevocationUpdate::new_pq(
            FEED.into(),
            head.clone(),
            now.saturating_sub(1000),
            now + 60_000,
        );
        let signature = feed_signer
            .sign_exact_message(&update.signing_bytes()?)?
            .to_vec();
        write_private(
            &feed_path,
            &SignedFinalUseRevocationUpdate { update, signature },
        )?;
        fs::create_dir_all(agent.layout.automation_root())?;
        let path = agent.layout.automation_root().join("pq-effect-host.json");
        let config = serde_json::json!({
            "schema_version":4,"authentication_profile":FinalUseAuthenticationProfile::MlDsa65V2,
            "agent_id":agent.agent_id,"spawn_generation":generation,
            "provider_scope":PROVIDER_SCOPE,"destination_id":DESTINATION,
            "final_use_scope_sha256":"","contract_id":"controlled-process-effect-contract","contract_authority_epoch":9,
            "contract_root":pinned(&contract,"controlled-contract-root"),"contract_signature":[],
            "provider":{"kind":"http","dispatch_url":format!("{uri}/dispatch"),"lookup_url_template":format!("{uri}/status/{{key}}"),"headers":{},"timeout_ms":2000},
            "authority":{"signer_id":SIGNER,"issuer_keys":[pinned(&issuer,"controlled-grant-issuer")],"head":head,
                "revocation_distributor_id":FEED,"revocation_keys":[pinned(&feed_signer,"controlled-feed-owner")],"signed_revocations_file":feed_path,
                "external_clock":endpoint(&clock.config),"external_frontier":endpoint(&frontier.config)},
            "recovery_provider_policies":[],
        });
        let mut value = Self {
            clock,
            frontier,
            path,
            config,
            now,
            issuer,
            contract,
            _external: external,
        };
        value.sign_config()?;
        Ok(value)
    }

    /// Independent test owner follows the documented explicit serialization.
    /// It does not import a private Agentd parser or bypass the ordinary loader.
    pub(super) fn scope(&self) -> Result<Sha256Digest> {
        let c = &self.config;
        let a = &c["authority"];
        let value = serde_json::json!({
            "schema":"hepta-agentd-effect-owner-policy-pq-v4",
            "authentication_profile":c["authentication_profile"],
            "agent_id":c["agent_id"],"spawn_generation":c["spawn_generation"],
            "provider_scope":c["provider_scope"],"destination_id":c["destination_id"],
            "contract_id":c["contract_id"],"contract_authority_epoch":c["contract_authority_epoch"],
            "contract_root":c["contract_root"],"provider":c["provider"],
            "signer_id":a["signer_id"],"issuer_keys":a["issuer_keys"],
            "revocation_distributor_id":a["revocation_distributor_id"],"revocation_keys":a["revocation_keys"],
            "signed_revocations_file":a["signed_revocations_file"],
            "clock":a["external_clock"],"frontier":a["external_frontier"],
            "recovery_provider_policies":c["recovery_provider_policies"],
        });
        let mut bytes = b"hepta.agentd.effect-owner-policy.pq.v4\0".to_vec();
        bytes.extend(serde_json::to_vec(&value)?);
        Ok(Sha256Digest::for_bytes(&bytes))
    }

    fn sign_config(&mut self) -> Result<()> {
        let scope = self.scope()?;
        let contract_id = self.config["contract_id"].as_str().context("contract id")?;
        let p = &self.config["provider"];
        let digest = HttpProviderEffectConfig {
            dispatch_url: p["dispatch_url"].as_str().context("dispatch url")?.into(),
            lookup_url_template: p["lookup_url_template"]
                .as_str()
                .context("lookup url")?
                .into(),
            headers: HeaderMap::new(),
            timeout: Duration::from_millis(2000),
            contract_id: contract_id.into(),
            attestation: None,
        }
        .contract_sha256()
        .map_err(anyhow::Error::msg)?;
        let bytes = HttpProviderEffectContractAttestation::statement_for_pq(
            contract_id,
            &digest,
            9,
            &scope,
        );
        self.config["final_use_scope_sha256"] = serde_json::json!(scope);
        self.config["contract_signature"] =
            serde_json::json!(self.contract.sign_exact_message(&bytes)?.to_vec());
        write_private(&self.path, &self.config)
    }

    pub(super) fn authorize_recovery_generation(&mut self, generation: u64) -> Result<()> {
        let bytes = fs::read(&self.path)?;
        let old = self.path.with_file_name("original-generation-policy.json");
        fs::write(&old, &bytes)?;
        fs::set_permissions(&old, fs::Permissions::from_mode(0o600))?;
        self.config["spawn_generation"] = serde_json::json!(generation);
        self.config["recovery_provider_policies"] =
            serde_json::json!([{"path":old,"sha256":Sha256Digest::for_bytes(&bytes)}]);
        self.sign_config()
    }

    pub(super) fn grant(&self, intent: &AuthorizedEffectIntent) -> Result<SignedFinalUseGrant> {
        let grant = FinalUseGrant {
            schema_version: 2,
            signer_id: SIGNER.into(),
            authority_epoch: 9,
            grant_id: "controlled-process-effect-grant".into(),
            nonce: [76; 32],
            binding: intent.final_use_binding()?,
            not_before_unix_ms: self.now.saturating_sub(1000),
            expires_at_unix_ms: self.now + 30_000,
        };
        let signature = self
            .issuer
            .sign_exact_message(&grant.signing_bytes()?)?
            .to_vec();
        Ok(SignedFinalUseGrant { grant, signature })
    }

    /// Inspect only after both ordinary-process phases have completed and the
    /// second daemon has exited. This cannot repair state before the tested restart.
    pub(super) fn final_nonce_count(&self, agent: &AgentFixture) -> Result<usize> {
        let a = &self.config["authority"];
        let clock: Arc<dyn AuthorityClock> = Arc::new(UnixPqAuthorityClock::new(
            serde_json::from_value(a["external_clock"].clone())?,
        )?);
        let frontier = Arc::new(UnixPqFinalUseFrontier::new(serde_json::from_value(
            a["external_frontier"].clone(),
        )?)?);
        let owner = FinalUseAuthority::open_pq_state_dir_with_issuer_keys(
            &agent
                .layout
                .automation_root()
                .join("final-use-authority-pq-v2"),
            SIGNER.into(),
            serde_json::from_value(a["issuer_keys"].clone())?,
            serde_json::from_value(a["head"].clone())?,
            clock,
            frontier,
        )?;
        Ok(owner.capacity()?.used_nonces)
    }
}

fn endpoint(v: &UnixPqTrustEndpointConfig) -> Value {
    serde_json::json!({"socket_path":v.socket_path,"peer_uid":v.peer_uid,"service_id":v.service_id,
        "key_generation":v.key_generation,"public_key_id":v.public_key_id,"public_key_spki":v.public_key_spki,"timeout_ms":v.timeout_ms})
}

pub(super) async fn prepare_effect(
    agent: &AgentFixture,
    intent: &AuthorizedEffectIntent,
    now: u64,
) -> Result<()> {
    use codex_hepta_automation::AutomationStore;
    use codex_hepta_automation::TaskFlowCommand;
    use codex_hepta_automation::TaskFlowDefinition;
    use codex_hepta_automation::TaskFlowEdgeSpec;
    use codex_hepta_automation::TaskFlowFence;
    use codex_hepta_automation::TaskFlowNodeKind;
    use codex_hepta_automation::TaskFlowNodeSpec;
    use codex_hepta_automation::TaskFlowTransition;
    let store = AutomationStore::open(&agent.layout).await?;
    let definition = TaskFlowDefinition::new(
        "controlled-process-effect",
        1,
        "effect",
        vec![
            TaskFlowNodeSpec::effect("effect", "provider.deliver", "provider-key-v1"),
            TaskFlowNodeSpec::new("success", TaskFlowNodeKind::TerminalSuccess),
            TaskFlowNodeSpec::new("failure", TaskFlowNodeKind::TerminalFailure),
        ],
        vec![
            TaskFlowEdgeSpec::new("effect", "success"),
            TaskFlowEdgeSpec::new("effect", "failure"),
        ],
        vec!["provider.deliver".into()],
        Sha256Digest::for_bytes(b"controlled-process-effect-policy"),
    )?;
    let fence = TaskFlowFence::new(
        agent.agent_id.clone(),
        "controlled-process-effect-owner",
        1,
        1,
        "controlled-process-effect-fence",
    )?;
    store
        .register_taskflow_definition(&definition, &fence, now)
        .await?;
    store
        .create_taskflow_run(
            &intent.run_id,
            &definition.workflow_id,
            definition.version,
            definition.definition_digest(),
            "controlled-process-effect-thread",
            now,
        )
        .await?;
    let claimed = store
        .claim_taskflow_run(&intent.run_id, &fence, now + 1, 60_000)
        .await?;
    store
        .apply_taskflow_command(&TaskFlowCommand::new(
            &intent.run_id,
            "controlled-process-start",
            fence.clone(),
            claimed.revision,
            TaskFlowTransition::Start,
            now + 2,
        )?)
        .await?;
    let digest = intent.digest()?;
    store
        .prepare_taskflow_step(
            &intent.run_id,
            &intent.step_id,
            intent.attempt,
            &fence,
            &digest,
            &intent.payload_digest,
            "controlled-process-prepare",
            now + 3,
        )
        .await?;
    store
        .claim_taskflow_step(
            &intent.run_id,
            &intent.step_id,
            intent.attempt,
            &fence,
            &digest,
            &intent.payload_digest,
            "controlled-process-claim",
            now + 4,
        )
        .await?;
    store.close().await;
    Ok(())
}
