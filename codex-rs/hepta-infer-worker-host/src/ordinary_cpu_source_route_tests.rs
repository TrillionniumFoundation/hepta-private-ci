use super::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::LocalOutcomeState;
use codex_hepta_memory::ProductionAuthorityLease;
use codex_hepta_memory::ProductionAuthorityToken;
use codex_hepta_memory::ProductionDurableWriter;
use codex_hepta_memory::ProductionFinalUseOutboxDispatcher;
use codex_hepta_memory::ProductionQueuedReceipt;
use codex_hepta_memory::ProductionWriterError;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

struct TestClock(AtomicU64);
impl AuthorityClock for TestClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(self.0.load(Ordering::SeqCst))
    }
}

#[derive(Clone, Copy)]
enum WorkerBehavior {
    ExitZero,
    ExitNonzero,
}

fn registered_worker(
    temp: &TempDir,
    agent: &AgentId,
    behavior: WorkerBehavior,
) -> OrdinaryCpuRegistration {
    let mut registration = registration(temp);
    registration.binding.subject_id = StableId::new(agent.as_str()).expect("owner subject");
    let code = match behavior {
        WorkerBehavior::ExitZero => 0,
        WorkerBehavior::ExitNonzero => 7,
    };
    #[cfg(unix)]
    {
        registration.arguments = vec![
            "-c".to_owned(),
            format!("printf 'x\\n' >> child-marker; exit {code}"),
        ];
    }
    #[cfg(windows)]
    {
        registration.arguments = vec![
            "/D".to_owned(),
            "/C".to_owned(),
            format!("echo x>>child-marker & exit /b {code}"),
        ];
    }
    registration
}

fn authority(temp: &TempDir, name: &str, clock: Arc<TestClock>) -> FinalUseAuthority {
    let path = temp.path().join(name);
    std::fs::create_dir(&path).expect("authority directory");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700))
            .expect("private authority");
    }
    FinalUseAuthority::open_state_dir_with_clock(
        &path,
        "ordinary-source-route-issuer".to_owned(),
        SigningKey::from_bytes(&[113; 32])
            .verifying_key()
            .to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
        clock,
    )
    .expect("original durable FinalUse owner")
}

fn source_authority_bytes(lease: &ProductionAuthorityLease) -> Result<Vec<u8>, String> {
    serde_json::to_vec(&(
        lease,
        lease.fencing_token_digest().map_err(|e| e.to_string())?,
    ))
    .map_err(|e| e.to_string())
}

struct SourceFixture {
    temp: TempDir,
    clock: Arc<TestClock>,
    pool: SqlitePool,
    target: Arc<OrdinaryCpuTarget>,
    writer: Arc<ProductionDurableWriter>,
    dispatcher: ProductionFinalUseOutboxDispatcher,
    queued: ProductionQueuedReceipt,
    binding: FinalUseBinding,
}

impl SourceFixture {
    async fn new(behavior: WorkerBehavior) -> Self {
        let temp = TempDir::new().expect("source route fixture");
        let pool = crate::ordinary_cpu_owner::tests::pool(&temp).await;
        let clock = Arc::new(TestClock(AtomicU64::new(1_000)));
        let authority = authority(&temp, "original-authority", clock.clone());
        let root = temp.path().join("fleet");
        std::fs::create_dir(&root).expect("fresh fixture fleet");
        let fleet =
            HeptaFleetRoot::parse(root.canonicalize().expect("fleet identity")).expect("fleet");
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2cff").expect("agent");
        let store = CognitiveStore::open(&fleet.layout().agent(&agent))
            .await
            .expect("original source journal");
        let lease = ProductionAuthorityLease::from_verified_parts(
            agent.clone(),
            Sha256Digest::for_bytes(b"external-fixture-source-grant"),
            1,
            1,
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .expect("time")
                .as_secs()
                + 3_600,
            ProductionAuthorityToken::from_verified_bytes(
                b"external-fixture-source-token".to_vec(),
            )
            .expect("external token"),
        )
        .expect("original source lease");
        // This fixture exercises the existing external-verifier seam with a
        // real signature and exact lease/token binding, not production custody.
        let source_issuer = SigningKey::from_bytes(&[117; 32]);
        let signature =
            source_issuer.sign(&source_authority_bytes(&lease).expect("source signing bytes"));
        let expected_lease = lease.clone();
        let verifier =
            move |candidate: &ProductionAuthorityLease, owner: &AgentId| -> Result<(), String> {
                if candidate != &expected_lease || owner != &expected_lease.agent_id {
                    return Err("source lease binding differs".to_owned());
                }
                source_issuer
                    .verifying_key()
                    .verify_strict(&source_authority_bytes(candidate)?, &signature)
                    .map_err(|e| e.to_string())
            };
        let writer = Arc::new(
            ProductionDurableWriter::open_with_live_verifier(
                store,
                lease,
                Arc::new(verifier),
                "ordinary-source-route",
                1,
            )
            .await
            .expect("real production writer"),
        );
        let registration = registered_worker(&temp, &agent, behavior);
        let payload = registration.payload_json().expect("fixed payload");
        let queued = writer
            .prepare_operation(
                registration
                    .operation(StableId::new("original-source-effect").expect("operation"))
                    .expect("canonical intent"),
                crate::ordinary_cpu_registration::TOPIC,
                &payload,
            )
            .await
            .expect("source durable prepare");
        let binding = writer
            .final_use_binding(&queued, DESTINATION)
            .await
            .expect("source final-use binding");
        let target = Arc::new(
            OrdinaryCpuTarget::from_migrated_pool(registration, authority.clone(), pool.clone())
                .await
                .expect("target"),
        );
        let dispatcher =
            ProductionFinalUseOutboxDispatcher::attach(authority.clone(), target.clone());
        Self {
            temp,
            clock,
            pool,
            target,
            writer,
            dispatcher,
            queued,
            binding,
        }
    }

    fn signed_grant(&self, label: &str, nonce: u8) -> SignedFinalUseGrant {
        let now = self.clock.0.load(Ordering::SeqCst);
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "ordinary-source-route-issuer".to_owned(),
            authority_epoch: 1,
            grant_id: label.to_owned(),
            nonce: [nonce; 32],
            binding: self.binding.clone(),
            not_before_unix_ms: now - 100,
            expires_at_unix_ms: now + 1_000,
        };
        let signature = SigningKey::from_bytes(&[113; 32])
            .sign(&grant.signing_bytes().expect("original grant bytes"))
            .to_bytes()
            .to_vec();
        SignedFinalUseGrant { grant, signature }
    }

    async fn wait_for_observed_exit(&self) {
        tokio::time::timeout(Duration::from_secs(2), async {
            loop {
                self.dispatcher
                    .reconcile(&self.writer, 1)
                    .await
                    .expect("source observer-only reconciliation");
                if self.target.children.lock().expect("children")[0]
                    .as_ref()
                    .expect("retained original Child")
                    .exit
                    .is_some()
                {
                    break;
                }
                tokio::time::sleep(Duration::from_millis(5)).await;
            }
        })
        .await
        .expect("bounded actual child observation");
    }

    fn assert_single_spawn(&self) {
        assert_eq!(
            std::fs::read_to_string(self.temp.path().join("child-marker"))
                .expect("actual spawn marker")
                .lines()
                .collect::<Vec<_>>(),
            vec!["x"]
        );
    }
}

#[tokio::test]
async fn signed_source_commits_only_after_original_child_observation_and_never_repeats() {
    let fixture = SourceFixture::new(WorkerBehavior::ExitZero).await;
    let signed = fixture.signed_grant("source-good", 1);
    let result = fixture
        .dispatcher
        .dispatch(
            &fixture.writer,
            &signed,
            &fixture.binding,
            fixture.queued.clone(),
        )
        .await
        .expect("real signed source route");
    assert_eq!(result.state, LocalOutcomeState::Indeterminate);
    fixture.wait_for_observed_exit().await;
    assert_eq!(
        fixture
            .writer
            .status("original-source-effect")
            .await
            .expect("source terminal"),
        LocalOutcomeState::Committed
    );
    assert!(
        fixture
            .dispatcher
            .dispatch(
                &fixture.writer,
                &signed,
                &fixture.binding,
                fixture.queued.clone()
            )
            .await
            .is_err()
    );
    fixture.assert_single_spawn();
}

#[tokio::test]
async fn wrong_original_authority_rejects_before_permanent_entry_or_spawn() {
    let fixture = SourceFixture::new(WorkerBehavior::ExitZero).await;
    let foreign = authority(
        &fixture.temp,
        "different-owner-same-key",
        fixture.clock.clone(),
    );
    let dispatcher = ProductionFinalUseOutboxDispatcher::attach(foreign, fixture.target.clone());
    let signed = fixture.signed_grant("wrong-owner", 2);
    assert!(matches!(
        dispatcher
            .dispatch(
                &fixture.writer,
                &signed,
                &fixture.binding,
                fixture.queued.clone()
            )
            .await,
        Err(ProductionWriterError::FinalUse(
            FinalUseError::BindingMismatch
        ))
    ));
    let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM ordinary_cpu_entries")
        .fetch_one(&fixture.pool)
        .await
        .expect("no admission");
    assert_eq!(count, 0);
    assert!(!fixture.temp.path().join("child-marker").exists());
    assert!(
        fixture
            .target
            .children
            .lock()
            .expect("children")
            .iter()
            .all(Option::is_none)
    );
}

#[tokio::test]
async fn nonzero_actual_child_never_becomes_source_rejected_or_applied() {
    let fixture = SourceFixture::new(WorkerBehavior::ExitNonzero).await;
    let signed = fixture.signed_grant("nonzero-child", 3);
    assert_eq!(
        fixture
            .dispatcher
            .dispatch(
                &fixture.writer,
                &signed,
                &fixture.binding,
                fixture.queued.clone()
            )
            .await
            .expect("signed entry")
            .state,
        LocalOutcomeState::Indeterminate
    );
    fixture.wait_for_observed_exit().await;
    assert_eq!(
        fixture.target.children.lock().expect("children")[0]
            .as_ref()
            .expect("Child")
            .exit
            .as_ref()
            .expect("actual exit")
            .status
            .code(),
        Some(7)
    );
    assert_eq!(
        fixture
            .writer
            .status("original-source-effect")
            .await
            .expect("source state"),
        LocalOutcomeState::Indeterminate
    );
    assert!(
        fixture
            .dispatcher
            .dispatch(
                &fixture.writer,
                &signed,
                &fixture.binding,
                fixture.queued.clone()
            )
            .await
            .is_err()
    );
    fixture.assert_single_spawn();
}
