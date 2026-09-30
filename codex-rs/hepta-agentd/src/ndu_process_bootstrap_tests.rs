use super::*;
use codex_hepta_agent_protocol::NduControlRequestV1;
use codex_hepta_agent_protocol::NduControlResultV1;
use codex_hepta_agent_protocol::NduMutationOperationV1;
use codex_hepta_agent_protocol::NduMutationV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocationUpdate;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_ndu::NduOwnerError;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;

type TestResult = Result<(), Box<dyn std::error::Error>>;

#[test]
fn signed_feed_advance_during_admission_rejects_physical_mutation() -> TestResult {
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    let store = root.join("store");
    let authority_dir = root.join("authority");
    for path in [&store, &authority_dir] {
        std::fs::create_dir(path)?;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700))?;
    }
    let issuer = SigningKey::from_bytes(&[73; 32]);
    let distributor = SigningKey::from_bytes(&[74; 32]);
    let path = root.join("feed.json");
    let first = FinalUseRevocations {
        authority_epoch: 1,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let publish = |revision, revoked_grant_ids| -> Result<(), AgentdNduOwnerErrorV1> {
        let now = now_ms()?;
        let update = FinalUseRevocationUpdate::new(
            "feed".into(),
            FinalUseRevocations {
                authority_epoch: 1,
                revision,
                revoked_grant_ids,
            },
            now.saturating_sub(1_000),
            now + 240_000,
        );
        let signature = distributor
            .sign(&update.signing_bytes().map_err(invalid)?)
            .to_bytes()
            .to_vec();
        let bytes = serde_json::to_vec(&SignedFinalUseRevocationUpdate { update, signature })
            .map_err(invalid)?;
        let temporary = path.with_extension("tmp");
        std::fs::write(&temporary, bytes).map_err(invalid)?;
        std::fs::rename(temporary, &path).map_err(invalid)?;
        Ok(())
    };
    publish(1, BTreeSet::new())?;
    let authority = FinalUseAuthority::open_state_dir(
        &authority_dir,
        "issuer".into(),
        issuer.verifying_key().to_bytes(),
        first,
    )?;
    let policy: Policy = serde_json::from_value(serde_json::json!({
        "profile_id":"profile","policy_id":"policy",
        "axis_registry_digest":Digest32::of_bytes(b"axes").to_string(),
        "normalization_manifest_digest":Digest32::of_bytes(b"normalization").to_string(),
        "utility_axes":[{"id":"success","direction":"maximize","aggregation":"sum",
            "uncertainty_aggregation":"maximum","tolerance_raw":0}],
        "risk_axes":[],"resource_axes":[],"required_organs":["planner"],"scalarization":null
    }))?;
    let host = AgentdNduOwnerHostV1::open_with_feed(
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c79")?,
        1,
        AgentdNduOwnerBootstrapV1 {
            store_root: store,
            authority,
            policy: policy.native()?,
        },
        Some(NduRevocationSourceV1 {
            path: path.clone(),
            verifier: FinalUseRevocationFeedVerifier::new(
                "feed".into(),
                distributor.verifying_key().to_bytes(),
            )?,
            trust_digest: Digest32::of_bytes(b"test-trust"),
            clock: Arc::new(SystemAuthorityClock),
            production_caller: None,
        }),
    )?;
    let mutation = NduMutationV1 {
        operation: NduMutationOperationV1::AppendPreference,
        identity: [1; 32],
        objective: [2; 32],
        subject: [3; 32],
        projection: [4; 32],
        expected_predecessor: None,
    };
    let NduControlResultV1::Prepared {
        binding,
        journal_head,
    } = host.control(
        NduControlRequestV1::Prepare {
            mutation: mutation.clone(),
            expected_head: [0; 32],
        },
        || Ok(()),
    )?
    else {
        return Err("unexpected prepared result".into());
    };
    let now = now_ms()?;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "issuer".into(),
        authority_epoch: 1,
        grant_id: "late-revoked".into(),
        nonce: [7; 32],
        binding,
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 60_000,
    };
    let signature = issuer.sign(&grant.signing_bytes()?).to_bytes().to_vec();
    let mut observations = 0;
    let result = host.control(
        NduControlRequestV1::Apply {
            mutation: mutation.clone(),
            expected_head: journal_head,
            grant: Box::new(SignedFinalUseGrant { grant, signature }),
        },
        || {
            observations += 1;
            if observations == 2 {
                publish(2, BTreeSet::from(["late-revoked".to_string()]))?;
            }
            Ok(())
        },
    );
    assert_eq!(observations, 2);
    assert!(matches!(
        result,
        Err(AgentdNduOwnerErrorV1::Owner(NduOwnerError::InvalidContext(
            "revocation feed changed before mutation"
        )))
    ));
    assert!(matches!(
        host.control(
            NduControlRequestV1::Outcome {
                identity: mutation.identity
            },
            || Ok(())
        )?,
        NduControlResultV1::Outcome { entry: None }
    ));
    assert!(
        matches!(host.control(NduControlRequestV1::Context, || Ok(()))?, NduControlResultV1::Context { journal_head, .. } if journal_head == [0; 32])
    );
    Ok(())
}

fn now_ms() -> Result<u64, AgentdNduOwnerErrorV1> {
    SystemAuthorityClock.now_unix_ms().map_err(invalid)
}

// Deliberately test-only providers: their state is controlled to inject clock
// loss and an independently advanced authority frontier. They are not host
// attestation or durable external-service qualification.
struct QualificationClock(std::sync::atomic::AtomicU64);

impl AuthorityClock for QualificationClock {
    fn now_unix_ms(&self) -> Result<u64, codex_hepta_contracts::AuthorityTrustError> {
        let now = self.0.load(std::sync::atomic::Ordering::SeqCst);
        if now == u64::MAX {
            Err(codex_hepta_contracts::AuthorityTrustError::Unavailable)
        } else {
            Ok(now)
        }
    }
}

struct QualificationFrontier(std::sync::Mutex<FinalUseFrontier>);

impl AuthorityFrontierStore<FinalUseFrontier> for QualificationFrontier {
    fn load(
        &self,
        _owner: &str,
    ) -> Result<FinalUseFrontier, codex_hepta_contracts::AuthorityTrustError> {
        self.0
            .lock()
            .map(|value| *value)
            .map_err(|_| codex_hepta_contracts::AuthorityTrustError::Unavailable)
    }

    fn compare_and_set(
        &self,
        _owner: &str,
        expected: &FinalUseFrontier,
        next: &FinalUseFrontier,
    ) -> Result<(), codex_hepta_contracts::AuthorityTrustError> {
        let mut value = self
            .0
            .lock()
            .map_err(|_| codex_hepta_contracts::AuthorityTrustError::Unavailable)?;
        if *value != *expected {
            return Err(codex_hepta_contracts::AuthorityTrustError::Conflict);
        }
        *value = *next;
        Ok(())
    }
}

struct ProductionFixture {
    _directory: tempfile::TempDir,
    descriptor: PathBuf,
    identity: AgentdIdentity,
    clock: Arc<QualificationClock>,
    frontier: Arc<QualificationFrontier>,
    issuer: SigningKey,
    trust_digest: Digest32,
    authority_directory: PathBuf,
}

impl ProductionFixture {
    fn new() -> Result<Self, Box<dyn std::error::Error>> {
        use codex_hepta_fleet::AgentLifecycle;
        use codex_hepta_fleet::AgentManifest;
        use codex_hepta_fleet::FleetRegistry;
        use codex_hepta_fleet::ResourceBudget;
        use codex_hepta_fleet::WorkspaceBinding;
        use codex_hepta_paths::HeptaFleetRoot;

        let directory = tempfile::tempdir()?;
        let root = directory.path().canonicalize()?;
        let fleet_root = HeptaFleetRoot::parse(root.join("fleet"))?;
        let registry = FleetRegistry::initialize(fleet_root.clone())?;
        let workspace = root.join("workspace");
        std::fs::create_dir(&workspace)?;
        let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c79")?;
        let record = registry.register(AgentManifest::new(
            agent_id.clone(),
            WorkspaceBinding::new(workspace.clone(), &fleet_root)?,
            ResourceBudget::local_default(),
        )?)?;
        registry.compare_and_transition(&agent_id, 0, AgentLifecycle::Starting)?;
        let config = crate::AgentdConfig::load(
            root.join("fleet"),
            agent_id.clone(),
            1,
            record.layout.home_root().to_path_buf(),
            record.layout.run_root().to_path_buf(),
            record.layout.home_root().to_path_buf(),
            workspace,
        )?;
        let identity = config.identity().clone();
        let store = root.join("store");
        let authority_directory = root.join("authority");
        for path in [&store, &authority_directory] {
            std::fs::create_dir(path)?;
            std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700))?;
        }
        let issuer = SigningKey::from_bytes(&[31; 32]);
        let distributor = SigningKey::from_bytes(&[32; 32]);
        let feed_path = root.join("feed.json");
        let head = FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        };
        let frontier = Arc::new(QualificationFrontier(std::sync::Mutex::new(
            FinalUseFrontier::for_initial_head(&head)?,
        )));
        let update = FinalUseRevocationUpdate::new("test-distributor".into(), head, 1_000, 60_000);
        let signature = distributor
            .sign(&update.signing_bytes()?)
            .to_bytes()
            .to_vec();
        std::fs::write(
            &feed_path,
            serde_json::to_vec(&SignedFinalUseRevocationUpdate { update, signature })?,
        )?;
        let trust_digest = Digest32::of_bytes(b"qualification-provider-profile");
        let descriptor = root.join("production.json");
        std::fs::write(
            &descriptor,
            serde_json::to_vec(&serde_json::json!({
                "schema": "hepta.agentd.ndu-bootstrap.v2", "trust_profile": "protected-host-v1",
                "agent_id": agent_id.as_str(), "store_root": store,
                "authority_directory": authority_directory, "authority_signer": "test-issuer",
                "authority_key": issuer.verifying_key().to_bytes(),
                "revocation_distributor": "test-distributor",
                "revocation_key": distributor.verifying_key().to_bytes(),
                "revocation_update_path": feed_path,
                "production_trust": {"caller_id": "production-control", "profile_digest": trust_digest.to_string()},
                "policy": {
                    "profile_id": "profile", "policy_id": "policy",
                    "axis_registry_digest": Digest32::of_bytes(b"axes").to_string(),
                    "normalization_manifest_digest": Digest32::of_bytes(b"normalization").to_string(),
                    "utility_axes": [{"id":"success", "direction":"maximize", "aggregation":"sum",
                        "uncertainty_aggregation":"maximum", "tolerance_raw":0}],
                    "risk_axes": [], "resource_axes": [], "required_organs": ["planner"], "scalarization": null
                }
            }))?,
        )?;
        Ok(Self {
            _directory: directory,
            descriptor,
            identity,
            clock: Arc::new(QualificationClock(std::sync::atomic::AtomicU64::new(1_500))),
            frontier,
            issuer,
            trust_digest,
            authority_directory,
        })
    }

    fn descriptor_digest(&self) -> Result<Digest32, Box<dyn std::error::Error>> {
        Ok(Digest32::of_bytes(&std::fs::read(&self.descriptor)?))
    }

    fn open(&self) -> Result<Arc<AgentdNduOwnerHostV1>, Box<dyn std::error::Error>> {
        let trust = NduProductionHostTrustV1::new(
            StableId::new("production-control")?,
            self.trust_digest,
            self.clock.clone(),
            self.frontier.clone(),
        )?;
        Ok(load_ndu_production_bootstrap_v2(
            &self.descriptor,
            self.descriptor_digest()?,
            &self.identity,
            trust,
        )?)
    }

    fn wrap(
        &self,
        host: &AgentdNduOwnerHostV1,
        request: NduControlRequestV1,
        key: &str,
    ) -> Result<NduControlRequestV1, Box<dyn std::error::Error>> {
        let context = host.context()?;
        Ok(NduControlRequestV1::ExternalAdmissionV2 {
            schema_version: 2,
            request_id: key.to_string(),
            idempotency_key: key.to_string(),
            caller_id: "production-control".to_string(),
            issued_at_unix_ms: 1_000,
            deadline_unix_ms: 2_000,
            host_generation: 1,
            fence_digest: *context.fence_digest.as_array(),
            revocation_head_digest: *context.revocation_frontier_digest.as_array(),
            payload_digest: request.canonical_payload_digest_v2()?,
            request: Box::new(request),
            extensions: Vec::new(),
        })
    }
}

#[test]
fn production_bootstrap_uses_one_clock_and_external_authority_frontier_through_restart()
-> TestResult {
    let fixture = ProductionFixture::new()?;
    let host = fixture.open()?;
    let mutation = NduMutationV1 {
        operation: NduMutationOperationV1::AppendPreference,
        identity: [1; 32],
        objective: [2; 32],
        subject: [3; 32],
        projection: [4; 32],
        expected_predecessor: None,
    };
    assert!(matches!(
        host.control(
            NduControlRequestV1::Prepare {
                mutation: mutation.clone(),
                expected_head: [0; 32]
            },
            || Ok(())
        ),
        Err(AgentdNduOwnerErrorV1::Admission("NDU-ADMIT-012"))
    ));
    let prepare = fixture.wrap(
        &host,
        NduControlRequestV1::Prepare {
            mutation: mutation.clone(),
            expected_head: [0; 32],
        },
        "prepare",
    )?;
    let NduControlResultV1::Prepared { binding, .. } = host.control(prepare, || Ok(()))? else {
        return Err("expected protected-host preparation".into());
    };
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "test-issuer".to_string(),
        authority_epoch: 1,
        grant_id: "protected-grant".to_string(),
        nonce: [17; 32],
        binding,
        not_before_unix_ms: 1_000,
        expires_at_unix_ms: 2_000,
    };
    let signature = fixture
        .issuer
        .sign(&grant.signing_bytes()?)
        .to_bytes()
        .to_vec();
    let request = fixture.wrap(
        &host,
        NduControlRequestV1::Apply {
            mutation,
            expected_head: [0; 32],
            grant: Box::new(SignedFinalUseGrant { grant, signature }),
        },
        "apply",
    )?;
    let before = fixture.frontier.load("test-issuer")?;
    let committed = host.control(request.clone(), || Ok(()))?;
    assert!(matches!(&committed, NduControlResultV1::Committed { .. }));
    assert_ne!(fixture.frontier.load("test-issuer")?, before);
    assert_eq!(host.control(request.clone(), || Ok(()))?, committed);
    drop(host);
    let reopened = fixture.open()?;
    assert_eq!(reopened.control(request, || Ok(()))?, committed);
    // The same protected clock is used for envelope, feed and grant admission.
    // Test time intentionally differs from the machine's wall clock.
    fixture
        .clock
        .0
        .store(u64::MAX, std::sync::atomic::Ordering::SeqCst);
    assert!(matches!(
        reopened.control(NduControlRequestV1::Context, || Ok(())),
        Err(AgentdNduOwnerErrorV1::Admission("NDU-ADMIT-004"))
    ));
    assert!(matches!(
        reopened.control(NduControlRequestV1::MetricsV1, || Ok(()))?,
        NduControlResultV1::MetricsV1 { .. }
    ));
    Ok(())
}

#[test]
fn production_bootstrap_rejects_fallback_policy_drift_and_external_frontier_rollback() -> TestResult
{
    let fixture = ProductionFixture::new()?;
    assert!(
        load_ndu_process_bootstrap_v1(
            &fixture.descriptor,
            fixture.descriptor_digest()?,
            &fixture.identity
        )
        .is_err()
    );
    assert_eq!(std::fs::read_dir(&fixture.authority_directory)?.count(), 0);
    let mut descriptor: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&fixture.descriptor)?)?;
    descriptor["policy"]["scalarization"] = serde_json::json!({
        "profile_id": "invalid-mass", "weights": [{"axis":"success", "raw":0}]
    });
    std::fs::write(&fixture.descriptor, serde_json::to_vec(&descriptor)?)?;
    assert!(fixture.open().is_err());
    assert_eq!(std::fs::read_dir(&fixture.authority_directory)?.count(), 0);
    descriptor["policy"]["scalarization"] = serde_json::Value::Null;
    std::fs::write(&fixture.descriptor, serde_json::to_vec(&descriptor)?)?;
    let host = fixture.open()?;
    let mut wrong_caller = fixture.wrap(&host, NduControlRequestV1::Context, "caller")?;
    if let NduControlRequestV1::ExternalAdmissionV2 { caller_id, .. } = &mut wrong_caller {
        *caller_id = "other-caller".to_string();
    }
    assert!(matches!(
        host.control(wrong_caller, || Ok(())),
        Err(AgentdNduOwnerErrorV1::Admission("NDU-ADMIT-013"))
    ));
    drop(host);
    fixture
        .frontier
        .0
        .lock()
        .map_err(|_| "test frontier poisoned")?
        .revocation_revision += 1;
    assert!(fixture.open().is_err());
    Ok(())
}
