use super::*;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_authbus::IssuerPurpose;
use codex_hepta_authbus::IssuerSpec;
use codex_hepta_authbus::PolicyEffect;
use codex_hepta_authbus::PolicySpec;
use codex_hepta_authbus::QuotaSpec;
use codex_hepta_authbus::SettlementEvidenceClaims;
use codex_hepta_authbus::SignedSettlementEvidence;
use codex_hepta_authbus::SignedTrustedTimeAttestation;
use codex_hepta_authbus::TrustedTimeAttestationClaims;
use codex_hepta_authbus::bootstrap_retryable;
use codex_hepta_bao_adapter::BaoAuthBusError;
use codex_hepta_bao_adapter::BaoToken;
use codex_hepta_bao_adapter::RegisteredBaoConsumer;
use codex_hepta_cognitive_store::CognitiveRecoveryAnchor;
use codex_hepta_cognitive_store::CognitiveRecoveryRequirement;
use codex_hepta_cognitive_store::DurableCognitiveStore;
use codex_hepta_cognitive_store::ProductionAuthorityLease;
use codex_hepta_cognitive_store::ProductionAuthorityToken;
use codex_hepta_cognitive_store::ProductionAuthorityVerifier;
use codex_hepta_cognitive_store::ProductionDurableWriter;
use codex_hepta_cognitive_store::ProductionEntryOutboxDispatcher;
use codex_hepta_cognitive_store::ProductionQueuedReceipt;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseApproval;
use codex_hepta_contracts::FinalUseApprovalVerifier;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
use codex_hepta_contracts::FinalUseRevocationUpdate;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use codex_hepta_memory::LocalOutcomeState;
use codex_hepta_operations::OperationIntentV1;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;

const SECRET: &str = "fixture-only-entry-secret";
type TestError = Box<dyn std::error::Error + Send + Sync>;

struct Clock(AtomicU64);
impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(self.0.load(Ordering::SeqCst))
    }
}

#[derive(Clone)]
struct Evidence {
    sequence: Arc<AtomicU64>,
    now: u64,
    bad_settlement: bool,
}
impl BaoAuthBusEvidenceProvider for Evidence {
    fn trusted_time(&mut self) -> Result<SignedTrustedTimeAttestation, BaoAuthBusError> {
        let revision = self.sequence.fetch_add(1, Ordering::SeqCst) + 1;
        let claims = TrustedTimeAttestationClaims {
            issuer_id: StableId::new("issuer:entry-time").unwrap(),
            key_epoch: Generation::new(1).unwrap(),
            wall_time_ms: self.now + revision,
            source_revision: revision,
            source_digest: Digest32::of_bytes(&revision.to_be_bytes()),
        };
        Ok(SignedTrustedTimeAttestation {
            signature: SigningKey::from_bytes(&[81; 32])
                .sign(&claims.signing_bytes())
                .to_bytes(),
            claims,
        })
    }
    fn settlement_evidence(
        &mut self,
        reservation: &QuotaReservation,
        status: SettlementStatus,
        observed_cost: u64,
        terminal_evidence_digest: Digest32,
        observed_at_ms: u64,
    ) -> Result<SignedSettlementEvidence, BaoAuthBusError> {
        let claims = SettlementEvidenceClaims {
            issuer_id: StableId::new("issuer:entry-settlement").unwrap(),
            key_epoch: Generation::new(1).unwrap(),
            reservation_id: reservation.reservation_id.clone(),
            operation_id: reservation.operation_id.clone(),
            status,
            observed_cost,
            terminal_evidence_digest,
            observed_at_ms,
            expires_at_ms: observed_at_ms + 30_000,
        };
        let key = if self.bad_settlement {
            [99; 32]
        } else {
            [82; 32]
        };
        Ok(SignedSettlementEvidence {
            signature: SigningKey::from_bytes(&key)
                .sign(&claims.signing_bytes())
                .to_bytes(),
            claims,
        })
    }
}

struct Provisioner {
    admission: BaoDurableAuthBusAdmission,
    grant: SignedFinalUseGrant,
    approval: SignedFinalUseApproval,
    evidence: Evidence,
    expire_owner: Option<Arc<Clock>>,
}
impl BaoOperationProvisioner for Provisioner {
    fn provision(
        &self,
        _: &ProductionDispatchRequest,
        binding: &FinalUseBinding,
    ) -> Result<BaoOperationInputs, String> {
        if binding != &self.grant.grant.binding {
            return Err("fixture binding mismatch".into());
        }
        if let Some(clock) = &self.expire_owner {
            clock.0.store(self.evidence.now + 30_001, Ordering::SeqCst);
        }
        Ok(BaoOperationInputs {
            admission: self.admission.clone(),
            grant: self.grant.clone(),
            approval: self.approval.clone(),
            evidence: Box::new(self.evidence.clone()),
        })
    }
}

fn state_dir(root: &std::path::Path, name: &str) -> std::path::PathBuf {
    let path = root.join(name);
    std::fs::create_dir(&path).unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700)).unwrap();
    path
}

fn authority_and_grant(
    root: &std::path::Path,
    name: &str,
    key: u8,
    binding: FinalUseBinding,
    clock: Arc<Clock>,
) -> (FinalUseAuthority, SignedFinalUseGrant) {
    let issuer = SigningKey::from_bytes(&[key; 32]);
    let now = clock.now_unix_ms().unwrap();
    let authority = FinalUseAuthority::open_state_dir_with_clock(
        &state_dir(root, name),
        name.into(),
        issuer.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: Default::default(),
        },
        clock,
    )
    .unwrap();
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: name.into(),
        authority_epoch: 1,
        grant_id: format!("{name}-grant"),
        nonce: [key; 32],
        binding,
        not_before_unix_ms: now - 1000,
        expires_at_unix_ms: now + 60_000,
    };
    let signature = issuer
        .sign(&grant.signing_bytes().unwrap())
        .to_bytes()
        .to_vec();
    (authority, SignedFinalUseGrant { grant, signature })
}

async fn authbus_fixture(
    root: &std::path::Path,
    binding: &FinalUseBinding,
    now: u64,
) -> (
    Arc<AuthBusAuthorityHost>,
    BaoDurableAuthBusAdmission,
    Evidence,
) {
    let database = state_dir(root, "authbus-database").join("authority.sqlite");
    let checkpoint = state_dir(root, "authbus-checkpoint").join("checkpoint.json");
    let host = Arc::new(
        bootstrap_retryable(&database, checkpoint, "entry-qualification")
            .await
            .unwrap(),
    );
    for (purpose, name, key) in [
        (IssuerPurpose::TrustedTime, "issuer:entry-time", 81),
        (IssuerPurpose::Settlement, "issuer:entry-settlement", 82),
    ] {
        host.admin()
            .enroll_issuer(
                purpose,
                IssuerSpec {
                    issuer_id: StableId::new(name).unwrap(),
                    key_epoch: Generation::new(1).unwrap(),
                    verifying_key: SigningKey::from_bytes(&[key; 32]).verifying_key(),
                },
            )
            .await
            .unwrap();
    }
    let mut evidence = Evidence {
        sequence: Arc::new(AtomicU64::new(0)),
        now,
        bad_settlement: false,
    };
    let time = host
        .execution()
        .observe_trusted_time_attestation(&evidence.trusted_time().unwrap())
        .await
        .unwrap();
    let policy = host
        .admin()
        .create_policy(
            PolicySpec {
                policy_id: StableId::new("policy:entry-bao").unwrap(),
                principal: StableId::new(&binding.subject_id).unwrap(),
                action: StableId::new("action:bao-read").unwrap(),
                scope_digest: Digest32::from_array(binding.scope_sha256),
                effect: PolicyEffect::Allow,
                not_before_ms: now - 1000,
                expires_at_ms: now + 60_000,
            },
            time,
        )
        .await
        .unwrap();
    let time = host
        .execution()
        .observe_trusted_time_attestation(&evidence.trusted_time().unwrap())
        .await
        .unwrap();
    let quota = host
        .admin()
        .create_quota(
            QuotaSpec {
                quota_key: StableId::new("quota:entry-bao").unwrap(),
                principal: policy.principal,
                scope_digest: Digest32::from_array(binding.scope_sha256),
                unit: StableId::new("unit:request").unwrap(),
                period_id: StableId::new("period:fixture").unwrap(),
                limit: 1,
            },
            time,
        )
        .await
        .unwrap();
    (
        host,
        BaoDurableAuthBusAdmission {
            policy_revision: 1,
            quota_key: quota.quota_key,
            expected_quota_revision: 1,
            amount: 1,
            expires_at_ms: now + 60_000,
        },
        evidence,
    )
}

fn lease_authority(
    agent: &AgentId,
    now: u64,
) -> (
    ProductionAuthorityLease,
    Arc<dyn ProductionAuthorityVerifier>,
) {
    let authority = ProductionAuthorityLease::from_verified_parts(
        agent.clone(),
        Sha256Digest::for_bytes(b"fixture-authority"),
        1,
        1,
        now / 1000 + 3600,
        ProductionAuthorityToken::from_verified_bytes(b"fixture-token".to_vec()).unwrap(),
    )
    .unwrap();
    let verifier: Arc<dyn ProductionAuthorityVerifier> =
        Arc::new(|lease: &ProductionAuthorityLease, owner: &AgentId| {
            if &lease.agent_id == owner {
                Ok(())
            } else {
                Err("fixture owner mismatch".into())
            }
        });
    (authority, verifier)
}

// Genuine cold handoff: the predecessor is fully gone before recovery reads it.
// This deliberately makes no claim about graceful in-process pool shutdown.
async fn cold_bootstrap(root: &std::path::Path, agent: &str, now: u64) {
    assert_eq!(root.canonicalize().unwrap(), root);
    assert!(!root.join("cold-anchor.json").exists());
    let mut child = tokio::process::Command::new(std::env::current_exe().unwrap())
        .arg("--exact")
        .arg("bao_operation_target::tests::cold_bootstrap_helper")
        .arg("--ignored")
        .arg("--nocapture")
        .env("HEPTA_BAO_COLD_ROOT", root)
        .env("HEPTA_BAO_COLD_AGENT", agent)
        .env("HEPTA_BAO_COLD_TIME", now.to_string())
        .kill_on_drop(true)
        .spawn()
        .unwrap();
    let (mut done, outcome) = tokio::sync::oneshot::channel();
    // A separate supervisor owns the Child. If the caller is canceled, the
    // receiver closes and the supervisor kills AND waits while this runtime lives.
    // Runtime shutdown may abort supervision; kill_on_drop is only a fallback,
    // not a claim of fully joined in-process shutdown.
    let supervisor = tokio::spawn(async move {
        let status = tokio::select! {
            result = child.wait() => Some(result),
            _ = done.closed() => None,
            _ = tokio::time::sleep(Duration::from_secs(30)) => None,
        };
        let result = match status {
            Some(status) => status.map_err(|error| error.to_string()),
            None => {
                let _ = child.start_kill();
                let status = child.wait().await;
                Err(format!(
                    "cold fixture timed out/canceled; reaped status: {status:?}"
                ))
            }
        };
        let _ = done.send(result);
    });
    let result = outcome.await;
    supervisor.await.expect("bootstrap supervisor joined");
    let status = result.unwrap().expect("bounded bootstrap child");
    assert!(status.success(), "bootstrap child exit: {status}");
}

#[tokio::test]
#[ignore = "cold bootstrap child fixture"]
async fn cold_bootstrap_helper() {
    let root =
        std::path::PathBuf::from(std::env::var_os("HEPTA_BAO_COLD_ROOT").expect("child-only root"));
    assert_eq!(root.canonicalize().unwrap(), root);
    let agent = AgentId::parse(&std::env::var("HEPTA_BAO_COLD_AGENT").unwrap()).unwrap();
    let now = std::env::var("HEPTA_BAO_COLD_TIME")
        .unwrap()
        .parse()
        .unwrap();
    let fleet = HeptaFleetRoot::parse(state_dir(&root, "fleet")).unwrap();
    let (authority, verifier) = lease_authority(&agent, now);
    let store = DurableCognitiveStore::open(&fleet.layout().agent(&agent))
        .await
        .unwrap();
    let _writer = ProductionDurableWriter::open_with_live_verifier(
        store.clone(),
        authority,
        verifier,
        "bao-entry-lease",
        1,
    )
    .await
    .unwrap();
    let anchor = store.recovery_anchor().await.unwrap();
    use std::io::Write;
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(root.join("cold-anchor.json"))
        .unwrap();
    file.write_all(&serde_json::to_vec(&anchor).unwrap())
        .unwrap();
    file.sync_all().unwrap();
}

async fn owner_fixture(
    root: &std::path::Path,
    read: &BaoReadRequest,
    binding: &FinalUseBinding,
    clock: Arc<Clock>,
) -> (ProductionDurableWriter, ProductionQueuedReceipt) {
    let now = clock.now_unix_ms().unwrap();
    cold_bootstrap(root, &read.subject_id, now).await;
    let fleet = HeptaFleetRoot::parse(root.join("fleet")).unwrap();
    let agent = AgentId::parse(&read.subject_id).unwrap();
    let layout = fleet.layout().agent(&agent);
    let (authority, verifier) = lease_authority(&agent, now);
    let anchor: CognitiveRecoveryAnchor =
        serde_json::from_slice(&std::fs::read(root.join("cold-anchor.json")).unwrap()).unwrap();
    assert_eq!(anchor.owner_agent_id, agent);
    let recovered = DurableCognitiveStore::open_with_recovery(
        &layout,
        CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
        &authority,
        verifier.as_ref(),
    )
    .await
    .unwrap_or_else(|error| {
        // Metadata only: diagnose cold handoff without changing guarded files.
        fn inventory(path: &std::path::Path) {
            let metadata = std::fs::symlink_metadata(path).unwrap();
            eprintln!(
                "cold recovery metadata: {} mode={:o} uid={} nlink={} bytes={}",
                path.display(),
                metadata.mode(),
                metadata.uid(),
                metadata.nlink(),
                metadata.len()
            );
            if metadata.is_dir() {
                for child in std::fs::read_dir(path).unwrap() {
                    inventory(&child.unwrap().path());
                }
            }
        }
        inventory(root);
        panic!("cold recovery failed: {error:?}");
    });
    let writer = ProductionDurableWriter::open_with_entry_clock(
        recovered,
        authority,
        verifier,
        clock,
        "bao-entry-lease",
        1,
    )
    .await
    .unwrap();
    let payload = serde_json::to_string(read).unwrap();
    let intent = OperationIntentV1::new(
        StableId::new("operation:registered-bao").unwrap(),
        StableId::new(&read.subject_id).unwrap(),
        StableId::new(BAO_DURABLE_OPERATION_DESTINATION).unwrap(),
        Digest32::of_bytes(payload.as_bytes()),
        Digest32::from_array(binding.scope_sha256),
        Generation::new(1).unwrap(),
        None,
    )
    .unwrap();
    let queued = writer
        .prepare_operation(intent, "bao.kv.read", payload)
        .await
        .unwrap();
    (writer, queued)
}

struct Fixture {
    _root: tempfile::TempDir,
    writer: ProductionDurableWriter,
    queued: ProductionQueuedReceipt,
    dispatcher: ProductionEntryOutboxDispatcher,
    owner_grant: SignedFinalUseGrant,
    owner_binding: FinalUseBinding,
    authbus: Arc<AuthBusAuthorityHost>,
    quota: StableId,
    delivered: Arc<AtomicUsize>,
}

async fn fixture(client: BaoClient, expire_owner: bool, bad_settlement: bool) -> Fixture {
    let root = tempfile::tempdir().unwrap();
    let canonical_root = root.path().canonicalize().unwrap();
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64;
    let owner_clock = Arc::new(Clock(AtomicU64::new(now)));
    let provider_clock = Arc::new(Clock(AtomicU64::new(now)));
    let read = BaoReadRequest {
        subject_id: "00000000-0000-4000-8000-00000000c061".into(),
        consumer_id: "entry-consumer".into(),
        namespace: "team".into(),
        mount: "secret".into(),
        path: "token".into(),
        field: "value".into(),
        version: 1,
        expected_secret_sha256: Digest32::of_bytes(SECRET.as_bytes()).into_array(),
    };
    let binding = client.binding(&read).unwrap();
    let (authbus, admission, mut evidence) = authbus_fixture(&canonical_root, &binding, now).await;
    evidence.bad_settlement = bad_settlement;
    let quota = admission.quota_key.clone();
    let (writer, queued) =
        owner_fixture(&canonical_root, &read, &binding, owner_clock.clone()).await;
    let owner_binding = writer
        .final_use_binding(&queued, BAO_DURABLE_OPERATION_DESTINATION)
        .await
        .unwrap();
    let (owner_authority, owner_grant) = authority_and_grant(
        &canonical_root,
        "operation-owner",
        71,
        owner_binding.clone(),
        owner_clock.clone(),
    );
    let (provider_authority, grant) = authority_and_grant(
        &canonical_root,
        "provider-owner",
        72,
        binding,
        provider_clock.clone(),
    );
    let approver = SigningKey::from_bytes(&[73; 32]);
    let distributor = SigningKey::from_bytes(&[74; 32]);
    let approval = FinalUseApproval::for_grant("operator-approval".into(), &grant.grant).unwrap();
    let approval = SignedFinalUseApproval {
        signature: approver
            .sign(&approval.signing_bytes().unwrap())
            .to_bytes()
            .to_vec(),
        approval,
    };
    let delivered = Arc::new(AtomicUsize::new(0));
    let count = delivered.clone();
    let registered = BaoFinalUseHost::new(
        provider_authority,
        FinalUseApprovalVerifier::new(
            "operator-approval".into(),
            approver.verifying_key().to_bytes(),
        )
        .unwrap(),
        FinalUseRevocationFeedVerifier::new(
            "feed-owner".into(),
            distributor.verifying_key().to_bytes(),
        )
        .unwrap(),
        provider_clock,
        [RegisteredBaoConsumer::new(
            "entry-consumer".into(),
            Arc::new(move |secret| {
                assert_eq!(secret, SECRET.as_bytes());
                count.fetch_add(1, Ordering::SeqCst);
                Ok(())
            }),
        )
        .unwrap()],
    )
    .unwrap();
    let update = FinalUseRevocationUpdate::new(
        "feed-owner".into(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 2,
            revoked_grant_ids: Default::default(),
        },
        now - 1000,
        now + 60_000,
    );
    registered
        .apply_revocation_update(&SignedFinalUseRevocationUpdate {
            signature: distributor
                .sign(&update.signing_bytes().unwrap())
                .to_bytes()
                .to_vec(),
            update,
        })
        .unwrap();
    let target = Arc::new(BaoOperationTarget {
        client: Arc::new(client),
        registered_host: Arc::new(registered),
        authbus: authbus.clone(),
        provisioner: Arc::new(Provisioner {
            admission,
            grant,
            approval,
            evidence,
            expire_owner: expire_owner.then_some(owner_clock),
        }),
    });
    let dispatcher = ProductionEntryOutboxDispatcher::attach(owner_authority, target);
    Fixture {
        _root: root,
        writer,
        queued,
        dispatcher,
        owner_grant,
        owner_binding,
        authbus,
        quota,
        delivered,
    }
}

type TlsServer = (
    BaoClient,
    tokio::task::JoinHandle<Result<(), TestError>>,
    tokio::sync::oneshot::Receiver<()>,
    tokio::sync::oneshot::Sender<()>,
);

async fn tls_server(pause: bool) -> Result<TlsServer, TestError> {
    let cert = rcgen::generate_simple_self_signed(vec!["localhost".into()])?;
    let pem = cert.cert.pem();
    let config = rustls::ServerConfig::builder_with_provider(Arc::new(
        rustls::crypto::aws_lc_rs::default_provider(),
    ))
    .with_safe_default_protocol_versions()?
    .with_no_client_auth()
    .with_single_cert(
        vec![cert.cert.der().clone()],
        rustls::pki_types::PrivatePkcs8KeyDer::from(cert.signing_key.serialize_der()).into(),
    )?;
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let client = BaoClient::new(
        &format!("https://localhost:{}/", listener.local_addr()?.port()),
        pem.as_bytes(),
        BaoToken::new("fixture-token".into())?,
        Duration::from_secs(5),
    )?;
    let (accepted, observed) = tokio::sync::oneshot::channel();
    let (release, released) = tokio::sync::oneshot::channel();
    let task = tokio::spawn(async move {
        tokio::time::timeout(Duration::from_secs(10), async move {
        let (socket, _) = listener.accept().await?;
        let mut stream = tokio_rustls::TlsAcceptor::from(Arc::new(config))
            .accept(socket)
            .await?;
        let mut request = Vec::new();
        while !request.ends_with(b"\r\n\r\n") && request.len() < 16384 {
            request.push(stream.read_u8().await?);
        }
        let _ = accepted.send(());
        if pause { released.await?; }
        let body = serde_json::json!({"data":{"data":{"value":SECRET},"metadata":{"version":1}}})
            .to_string();
        let headers = format!(
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
            body.len()
        );
        stream.write_all(headers.as_bytes()).await?;
        stream.write_all(body.as_bytes()).await?;
        Ok::<(), TestError>(())
        }).await?
    });
    Ok((client, task, observed, release))
}

#[tokio::test]
async fn real_carrier_delivery_and_signed_settlement_stay_indeterminate() {
    let (client, server, _observed, _release) = tls_server(false).await.unwrap();
    let f = fixture(client, false, false).await;
    let receipt = f
        .dispatcher
        .dispatch(
            &f.writer,
            &f.owner_grant,
            &f.owner_binding,
            f.queued.clone(),
        )
        .await
        .unwrap();
    assert_eq!(receipt.state, LocalOutcomeState::Indeterminate);
    assert_eq!(f.delivered.load(Ordering::SeqCst), 1);
    let quota = f.authbus.read().quota_snapshot(&f.quota).await.unwrap();
    assert_eq!((quota.available, quota.reserved, quota.consumed), (0, 0, 1));
    assert_eq!(f.dispatcher.reconcile(&f.writer, 1).await.unwrap(), 0);
    assert!(
        f.dispatcher
            .dispatch(&f.writer, &f.owner_grant, &f.owner_binding, f.queued)
            .await
            .is_err()
    );
    assert_eq!(f.delivered.load(Ordering::SeqCst), 1);
    server.await.unwrap().unwrap();
}

#[tokio::test]
async fn expired_real_carrier_after_preparation_never_enters_provider() {
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    listener.set_nonblocking(true).unwrap();
    let cert = rcgen::generate_simple_self_signed(vec!["localhost".into()]).unwrap();
    let client = BaoClient::new(
        &format!(
            "https://localhost:{}/",
            listener.local_addr().unwrap().port()
        ),
        cert.cert.pem().as_bytes(),
        BaoToken::new("fixture-token".into()).unwrap(),
        Duration::from_secs(2),
    )
    .unwrap();
    let f = fixture(client, true, false).await;
    let receipt = f
        .dispatcher
        .dispatch(&f.writer, &f.owner_grant, &f.owner_binding, f.queued)
        .await
        .unwrap();
    assert_eq!(receipt.state, LocalOutcomeState::Indeterminate);
    assert!(
        receipt
            .target_reason
            .unwrap()
            .contains("owner entry rejected")
    );
    assert_eq!(f.delivered.load(Ordering::SeqCst), 0);
    assert_eq!(
        listener.accept().unwrap_err().kind(),
        std::io::ErrorKind::WouldBlock
    );
    let quota = f.authbus.read().quota_snapshot(&f.quota).await.unwrap();
    assert_eq!((quota.available, quota.reserved, quota.consumed), (0, 1, 0));
}

#[tokio::test]
async fn invalid_signed_settlement_never_terminalizes_owner_or_refunds_hold() {
    let (client, server, _observed, _release) = tls_server(false).await.unwrap();
    let f = fixture(client, false, true).await;
    let receipt = f
        .dispatcher
        .dispatch(&f.writer, &f.owner_grant, &f.owner_binding, f.queued)
        .await
        .unwrap();
    assert_eq!(receipt.state, LocalOutcomeState::Indeterminate);
    assert!(
        receipt
            .target_reason
            .unwrap()
            .contains("signed settlement pending")
    );
    assert_eq!(f.delivered.load(Ordering::SeqCst), 1);
    let quota = f.authbus.read().quota_snapshot(&f.quota).await.unwrap();
    assert_eq!((quota.available, quota.reserved, quota.consumed), (0, 1, 0));
    server.await.unwrap().unwrap();
}

#[path = "bao_operation_target_cancellation_tests.rs"]
mod cancellation;
