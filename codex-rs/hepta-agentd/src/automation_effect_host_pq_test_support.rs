//! Controlled Unix trust services and local-only provider fixtures. These keys
//! exercise the native verifier; they are not deployment authority material.
use super::*;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocationUpdate;
use codex_hepta_contracts::authority_trust_unix::PqTrustOperationV2;
use codex_hepta_contracts::authority_trust_unix::PqTrustOutcomeV2;
use codex_hepta_contracts::authority_trust_unix::PqTrustRequestV2;
use codex_hepta_contracts::authority_trust_unix::PqTrustResponseBodyV2;
use codex_hepta_contracts::authority_trust_unix::SignedPqTrustResponseV2;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_paths::HeptaFleetRoot;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixListener;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::thread::JoinHandle;

pub(super) const SIGNER: &str = "automation-security-owner";
pub(super) const FEED: &str = "automation-revocation-owner";
use super::super::super::tests::Fixture;
pub(super) use super::super::super::tests::WIRE;
pub(super) use super::super::super::tests::effect_intent;
pub(super) use super::super::super::tests::prepare_effect;

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
    pub(super) available: Arc<AtomicBool>,
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
            ServiceRole::Clock => ("clock", 64),
            ServiceRole::Frontier => ("frontier", 65),
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
                                    value: *current.lock().map_err(|_| anyhow::anyhow!("frontier service state poisoned"))?,
                                },
                                (
                                    ServiceRole::Frontier,
                                    PqTrustOperationV2::FrontierCompareAndSet {
                                        owner_id,
                                        expected,
                                        next,
                                    },
                                ) if owner_id == SIGNER => {
                                    let mut value = current.lock().map_err(|_| anyhow::anyhow!("frontier service state poisoned"))?;
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
            available,
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

pub(super) struct PqFixture {
    pub(super) owner: Fixture,
    pub(super) clock: Service,
    pub(super) frontier: Service,
    pub(super) host_path: PathBuf,
    pub(super) feed_path: PathBuf,
    pub(super) config: Value,
    pub(super) issuer: PqNativeSigningKey,
    pub(super) feed_signer: PqNativeSigningKey,
    pub(super) contract: PqNativeSigningKey,
    pub(super) now: u64,
    _trust_directory: tempfile::TempDir,
}

impl PqFixture {
    pub(super) async fn new(provider_uri: &str) -> anyhow::Result<Self> {
        let owner = Fixture::new().await?;
        let trust = tempfile::tempdir()?;
        let root = trust.path().canonicalize()?;
        fs::set_permissions(&root, fs::Permissions::from_mode(0o700))?;
        let now = crate::authbus_ingress::now_ms()?;
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
        let contract = signing_key(/*seed*/ 61)?;
        let issuer = signing_key(/*seed*/ 62)?;
        let feed_signer = signing_key(/*seed*/ 63)?;
        let feed_path = root.join("signed-feed.json");
        let host_path = owner
            .identity
            .layout
            .automation_root()
            .join("pq-effect-host.json");
        let config = serde_json::json!({
            "schema_version":4,"authentication_profile":FinalUseAuthenticationProfile::MlDsa65V2, "agent_id":owner.identity.agent_id,
            "spawn_generation":owner.identity.spawn_generation,"provider_scope":"provider/fixture-v1", "destination_id":"provider:fixture",
            "final_use_scope_sha256":"", "contract_id":"agentd-pq-effect-contract", "contract_authority_epoch":9,
            "contract_root":pinned(&contract,"contract-root"), "contract_signature":[],
            "provider":{"kind":"http","dispatch_url":format!("{provider_uri}/dispatch"),"lookup_url_template":format!("{provider_uri}/status/{{key}}"),"headers":{},"timeout_ms":2000},
            "authority":{"signer_id":SIGNER,"issuer_keys":[pinned(&issuer,"grant-issuer")],"head":head,
                "revocation_distributor_id":FEED,"revocation_keys":[pinned(&feed_signer,"revocation-distributor")],"signed_revocations_file":feed_path,
                "external_clock":endpoint_policy(&clock.config),"external_frontier":endpoint_policy(&frontier.config)}
        });
        let mut fixture = Self {
            owner,
            clock,
            frontier,
            host_path,
            feed_path,
            config,
            issuer,
            feed_signer,
            contract,
            now,
            _trust_directory: trust,
        };
        fixture.write_feed(head, now + 60_000)?;
        fixture.sign_config()?;
        Ok(fixture)
    }

    pub(super) fn write_feed(&self, head: FinalUseRevocations, expires: u64) -> anyhow::Result<()> {
        let update = FinalUseRevocationUpdate::new_pq(
            FEED.into(),
            head,
            self.now.saturating_sub(1000),
            expires,
        );
        let signature = self
            .feed_signer
            .sign_exact_message(&update.signing_bytes()?)?
            .to_vec();
        write_private(
            &self.feed_path,
            &SignedFinalUseRevocationUpdate { update, signature },
        )
    }

    pub(super) fn sign_config(&mut self) -> anyhow::Result<()> {
        let parsed: HostV4 = serde_json::from_value(self.config.clone())?;
        let scope = parsed.scope()?;
        self.config["final_use_scope_sha256"] = serde_json::json!(scope.as_str());
        let digest = match &parsed.provider {
            ProviderV4::Http {
                dispatch_url,
                lookup_url_template,
                headers,
                timeout_ms,
            } => {
                let mut values = HeaderMap::new();
                for (name, value) in headers {
                    values.append(
                        HeaderName::from_bytes(name.as_bytes())?,
                        HeaderValue::from_str(value)?,
                    );
                }
                HttpProviderEffectConfig {
                    dispatch_url: dispatch_url.clone(),
                    lookup_url_template: lookup_url_template.clone(),
                    headers: values,
                    timeout: Duration::from_millis(*timeout_ms),
                    contract_id: parsed.contract_id.clone(),
                    attestation: None,
                }
                .contract_sha256()
                .map_err(anyhow::Error::msg)?
            }
            ProviderV4::Pon { .. } => {
                let mut bytes = b"hepta.agentd.pon-provider-contract.pq.v3\0".to_vec();
                bytes.extend(serde_json::to_vec(&parsed.provider)?);
                Sha256Digest::for_bytes(&bytes)
            }
        };
        let statement = HttpProviderEffectContractAttestation::statement_for_pq(
            &parsed.contract_id,
            &digest,
            parsed.contract_authority_epoch,
            &scope,
        );
        self.config["contract_signature"] =
            serde_json::json!(self.contract.sign_exact_message(&statement)?.to_vec());
        write_private(&self.host_path, &self.config)
    }

    pub(super) fn open(&self) -> Result<AgentdAutomationEffectHost, AgentdError> {
        AgentdAutomationEffectHost::open(&self.owner.identity, &self.host_path)
    }

    pub(super) fn scope(&self) -> anyhow::Result<Sha256Digest> {
        Ok(serde_json::from_value::<HostV4>(self.config.clone())?.scope()?)
    }

    pub(super) fn grant(
        &self,
        intent: &AuthorizedEffectIntent,
    ) -> anyhow::Result<SignedFinalUseGrant> {
        let grant = FinalUseGrant {
            schema_version: 2,
            signer_id: SIGNER.into(),
            authority_epoch: 9,
            grant_id: "pq-effect-grant".into(),
            nonce: [66; 32],
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

    pub(super) async fn state(
        &self,
        host: &AgentdAutomationEffectHost,
    ) -> anyhow::Result<(crate::AgentdState, FleetRegistry)> {
        let registry = FleetRegistry::open_existing(HeptaFleetRoot::parse(
            self.owner.identity.fleet_root.clone(),
        )?)?;
        let spawn = self.owner.identity.spawn_generation;
        registry.compare_and_transition(
            &self.owner.identity.agent_id,
            spawn - 1,
            AgentLifecycle::Starting,
        )?;
        let state = crate::AgentdState::new(self.owner.identity.clone(), registry.clone(), 32)?;
        state.attach_cognitive_store(Arc::new(
            codex_hepta_memory::CognitiveStore::open(&self.owner.identity.layout).await?,
        ))?;
        state.attach_automation_store(self.owner.store.clone())?;
        state.attach_automation_effect_host(Arc::new(host.clone()))?;
        registry.compare_and_transition(
            &self.owner.identity.agent_id,
            spawn,
            AgentLifecycle::Running,
        )?;
        state.refresh_generation()?;
        state.mark_runtime_prerequisites_ready()?;
        state.mark_app_server_ready()?;
        assert!(state.automation_admission_ready()?);
        Ok((state, registry))
    }
}
