//! Real SQLite owner/reopen tests. The destination is an explicit durable test
//! device; actual HOS2 guest qualification is a separate, required native gate.

use super::*;
use crate::HOS2_CPU_PERIOD_NS;
use crate::HOS2_DESTINATION_V1;
use crate::HOS2_INSTALL_TOPIC_V1;
use crate::Hos2DeliveryId;
use crate::Hos2DeliveryObservation;
use crate::Hos2Device;
use crate::Hos2InstallBudgetV1;
use crate::Hos2InstallContradiction;
use crate::Hos2InstallOutcome;
use crate::ProductionHos2Target;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::collections::BTreeSet;
use std::error::Error;
use std::fs;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;
const OPERATION: &str = "hos2:recovery:operation";
const LEASE: &str = "production:hos2:recovery-test";

struct Verifier;
impl ProductionAuthorityVerifier for Verifier {
    fn verify(
        &self,
        _authority: &ProductionAuthorityLease,
        _owner: &AgentId,
    ) -> Result<(), String> {
        Ok(())
    }
}

struct EntryClock {
    base: u64,
    calls: AtomicUsize,
    expire_at_entry: AtomicBool,
}

impl AuthorityClock for EntryClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        let calls = self.calls.fetch_add(1, Ordering::SeqCst);
        Ok(
            if self.expire_at_entry.load(Ordering::SeqCst) && calls >= 2 {
                self.base + 120_000
            } else {
                self.base
            },
        )
    }
}

#[derive(Deserialize, Serialize)]
struct DeviceRecord {
    request: Hos2InstallBudgetV1,
    observation: Hos2DeliveryObservation,
}

struct DiskDevice {
    path: PathBuf,
    calls: AtomicUsize,
    queries: AtomicUsize,
    lose_ack: AtomicBool,
    terminal_status: AtomicUsize,
    retire_calls: AtomicUsize,
    lose_retire_ack: AtomicBool,
}

impl DiskDevice {
    fn effect_path(&self, sequence: u64) -> PathBuf {
        if sequence == 1 {
            self.path.clone()
        } else {
            self.path.with_extension(format!("{sequence:016x}.json"))
        }
    }

    fn retired_through(&self) -> Result<u64, String> {
        match fs::read_to_string(self.path.with_extension("retired")) {
            Ok(value) => value
                .parse()
                .map_err(|error| format!("invalid fixture retirement: {error}")),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(0),
            Err(error) => Err(error.to_string()),
        }
    }
}

impl Hos2Device for DiskDevice {
    fn install(&self, request: &Hos2InstallBudgetV1) -> Result<Hos2InstallOutcome, String> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        if request.cap_ns > 50_000_000 {
            return Ok(Hos2InstallOutcome::Contradiction(
                Hos2InstallContradiction::BudgetExceedsGrant {
                    maximum_cap_ns: 50_000_000,
                },
            ));
        }
        match fs::read(self.effect_path(request.delivery.sequence()?)) {
            Ok(bytes) => {
                let existing: DeviceRecord =
                    serde_json::from_slice(&bytes).map_err(|error| error.to_string())?;
                if existing.request != *request {
                    return Ok(Hos2InstallOutcome::Contradiction(
                        Hos2InstallContradiction::ConflictStatus,
                    ));
                }
                return Err("fixture received a second install for an existing D".to_string());
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(error.to_string()),
        }
        let status = self.terminal_status.load(Ordering::SeqCst);
        let observation = if status == 0 {
            Hos2DeliveryObservation::Applied {
                stable_object_id: [9; 16],
                previous_revision: request.expected_revision,
                revision: request.expected_revision + 1,
                effective_ns: HOS2_CPU_PERIOD_NS + 1_001,
                consumed_ns: 999,
            }
        } else {
            Hos2DeliveryObservation::NotApplied {
                status: u16::try_from(status).map_err(|error| error.to_string())?,
            }
        };
        let record = DeviceRecord {
            request: request.clone(),
            observation,
        };
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(self.effect_path(request.delivery.sequence()?))
            .map_err(|error| error.to_string())?;
        file.write_all(&serde_json::to_vec(&record).map_err(|error| error.to_string())?)
            .map_err(|error| error.to_string())?;
        file.sync_all().map_err(|error| error.to_string())?;
        checkpoint("after-effect").map_err(|error| error.to_string())?;
        if self.lose_ack.load(Ordering::SeqCst) {
            return Err(
                "fixture loses acknowledgement after the persisted device effect".to_string(),
            );
        }
        self.query(&request.delivery)
            .map(Hos2InstallOutcome::Observed)
    }

    fn observe(&self, request: &Hos2InstallBudgetV1) -> Result<Hos2InstallOutcome, String> {
        request.to_json()?;
        if request.cap_ns > 50_000_000 {
            return Ok(Hos2InstallOutcome::Contradiction(
                Hos2InstallContradiction::BudgetExceedsGrant {
                    maximum_cap_ns: 50_000_000,
                },
            ));
        }
        self.query(&request.delivery)
            .map(Hos2InstallOutcome::Observed)
    }

    fn query(&self, delivery: &Hos2DeliveryId) -> Result<Hos2DeliveryObservation, String> {
        self.queries.fetch_add(1, Ordering::SeqCst);
        if delivery.boot_id != [1; 16] || delivery.space_id != [2; 16] {
            return Err("fixture history capability has another namespace".to_string());
        }
        let sequence = delivery.sequence()?;
        if sequence <= self.retired_through()? {
            return Ok(Hos2DeliveryObservation::Retired);
        }
        let payload = match fs::read(self.effect_path(sequence)) {
            Ok(payload) => payload,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                return Ok(Hos2DeliveryObservation::NotSeen);
            }
            Err(error) => return Err(error.to_string()),
        };
        let record: DeviceRecord =
            serde_json::from_slice(&payload).map_err(|error| error.to_string())?;
        if &record.request.delivery != delivery {
            return Err("fixture was queried for another D".to_string());
        }
        Ok(record.observation)
    }

    fn retire(&self, permit: &Hos2RetirementPermit) -> Result<Hos2RetirementObservation, String> {
        self.retire_calls.fetch_add(1, Ordering::SeqCst);
        let through = permit.through();
        if through.boot_id != [1; 16] || through.space_id != [2; 16] {
            return Err("fixture acknowledgement capability has another namespace".to_string());
        }
        let requested = through.sequence()?;
        let old = self.retired_through()?;
        let mut next_sequence = 1;
        while self.effect_path(next_sequence).exists() && next_sequence <= 100_000 {
            let record: DeviceRecord = serde_json::from_slice(
                &fs::read(self.effect_path(next_sequence)).map_err(|error| error.to_string())?,
            )
            .map_err(|error| error.to_string())?;
            if record.request.delivery.boot_id != through.boot_id
                || record.request.delivery.space_id != through.space_id
                || record.request.delivery.sequence()? != next_sequence
                || !matches!(
                    record.observation,
                    Hos2DeliveryObservation::Applied { .. }
                        | Hos2DeliveryObservation::NotApplied { status: 1..=7 }
                )
            {
                return Err("fixture refuses a nonterminal or foreign prefix".to_string());
            }
            next_sequence += 1;
        }
        if requested >= next_sequence {
            return Err("fixture terminal prefix has a gap".to_string());
        }
        let retired_through = requested.max(old);
        let mut file = OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .open(self.path.with_extension("retired"))
            .map_err(|error| error.to_string())?;
        file.write_all(retired_through.to_string().as_bytes())
            .map_err(|error| error.to_string())?;
        file.sync_all().map_err(|error| error.to_string())?;
        if self.lose_retire_ack.load(Ordering::SeqCst) {
            return Err("fixture loses acknowledgement after native retirement".to_string());
        }
        Ok(Hos2RetirementObservation {
            retired_through,
            next_sequence,
        })
    }
}

struct Fixture {
    writer: Arc<ProductionDurableWriter>,
    issuer: SigningKey,
    authority: FinalUseAuthority,
    clock: Arc<EntryClock>,
    device: Arc<DiskDevice>,
    dispatcher: ProductionFinalUseOutboxDispatcher,
    target: Arc<ProductionHos2Target>,
}

impl Fixture {
    async fn open(root: &Path) -> TestResult<Self> {
        Self::open_generation(root, /*generation*/ 1, /*expiry*/ 4_000_000_000).await
    }

    async fn open_generation(root: &Path, generation: u64, expiry: u64) -> TestResult<Self> {
        let fleet_path = root.join("fleet");
        fs::create_dir_all(&fleet_path)?;
        let fleet = HeptaFleetRoot::parse(fleet_path.canonicalize()?)?;
        let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2d19")?;
        let store = CognitiveStore::open(&fleet.layout().agent(&owner)).await?;
        let source = ProductionAuthorityLease::from_verified_parts(
            owner,
            Sha256Digest::for_bytes(
                format!("hos2-fixture-external-source-grant-{generation}").as_bytes(),
            ),
            /*authority_epoch*/ 31,
            /*owner_epoch*/ 40 + generation,
            expiry,
            ProductionAuthorityToken::from_verified_bytes(
                format!("hos2-fixture-source-token-{generation}").into_bytes(),
            )?,
        )?;
        let writer = Arc::new(
            ProductionDurableWriter::open_with_live_verifier(
                store,
                source,
                Arc::new(Verifier),
                LEASE,
                generation,
            )
            .await?,
        );
        let authority_path = root.join("final-use");
        fs::create_dir_all(&authority_path)?;
        fs::set_permissions(&authority_path, fs::Permissions::from_mode(0o700))?;
        let issuer = SigningKey::from_bytes(&[51; 32]);
        let clock = Arc::new(EntryClock {
            base: now_unix_ms()?,
            calls: AtomicUsize::new(0),
            expire_at_entry: AtomicBool::new(false),
        });
        let authority = FinalUseAuthority::open_state_dir_with_clock(
            &authority_path,
            "hos2-fixture-external-issuer".to_string(),
            issuer.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 71,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
            clock.clone(),
        )?;
        let device = Arc::new(DiskDevice {
            path: root.join("device-effect.json"),
            calls: AtomicUsize::new(0),
            queries: AtomicUsize::new(0),
            lose_ack: AtomicBool::new(false),
            terminal_status: AtomicUsize::new(0),
            retire_calls: AtomicUsize::new(0),
            lose_retire_ack: AtomicBool::new(false),
        });
        let target = Arc::new(ProductionHos2Target::new(device.clone()));
        let dispatcher =
            ProductionFinalUseOutboxDispatcher::attach(authority.clone(), target.clone());
        Ok(Self {
            writer,
            issuer,
            authority,
            clock,
            device,
            dispatcher,
            target,
        })
    }

    fn request(&self, sequence: u64) -> TestResult<Hos2InstallBudgetV1> {
        Ok(Hos2InstallBudgetV1 {
            schema_version: 1,
            delivery: Hos2DeliveryId::new([1; 16], [2; 16], sequence)?,
            manage_slot: 2,
            manage_generation: 1,
            expected_revision: 1,
            period_ns: HOS2_CPU_PERIOD_NS,
            cap_ns: 1_001,
        })
    }

    fn operation(&self, id: &str, request: &Hos2InstallBudgetV1) -> TestResult<OperationIntentV1> {
        Ok(OperationIntentV1::new(
            StableId::new(id)?,
            StableId::new(self.writer.owner_agent_id().as_str())?,
            StableId::new(HOS2_DESTINATION_V1)?,
            Digest32::of_bytes(request.to_json()?.as_bytes()),
            request.scope_digest(),
            Generation::new(1)?,
            /*expected_predecessor*/ None,
        )?)
    }

    async fn prepare(&self, id: &str, sequence: u64) -> TestResult<ProductionQueuedReceipt> {
        let request = self.request(sequence)?;
        Ok(self
            .writer
            .prepare_operation(
                self.operation(id, &request)?,
                HOS2_INSTALL_TOPIC_V1,
                request.to_json()?,
            )
            .await?)
    }

    async fn signed(
        &self,
        queued: &ProductionQueuedReceipt,
        nonce: u8,
    ) -> TestResult<(FinalUseBinding, SignedFinalUseGrant)> {
        let binding = self
            .writer
            .final_use_binding(queued, HOS2_DESTINATION_V1)
            .await?;
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "hos2-fixture-external-issuer".to_string(),
            authority_epoch: 71,
            grant_id: format!("hos2-fixture-grant-{nonce}"),
            nonce: [nonce; 32],
            binding: binding.clone(),
            not_before_unix_ms: self.clock.base.saturating_sub(1_000),
            expires_at_unix_ms: self.clock.base + 60_000,
        };
        let signature = self
            .issuer
            .sign(&grant.signing_bytes()?)
            .to_bytes()
            .to_vec();
        Ok((binding, SignedFinalUseGrant { grant, signature }))
    }

    async fn reject_claim(
        &self,
        queued: &ProductionQueuedReceipt,
    ) -> TestResult<DurableDispatchClaim> {
        // Use the original public claim-lease API; production's default 30s
        // lease/backoff is not changed. This fixture retains a bounded 5s lease.
        let claim = self
            .writer
            .claim_dispatch_lease(queued, /*lease_duration_ms*/ 5_000)
            .await?;
        let (binding, mut signed) = self.signed(queued, /*nonce*/ 1).await?;
        signed.signature[0] ^= 1;
        assert!(matches!(
            self.dispatcher
                .dispatch(&self.writer, &signed, &binding, queued.clone())
                .await,
            Err(ProductionWriterError::FinalUse(
                FinalUseError::InvalidSignature
            ))
        ));
        assert_eq!(
            self.writer.status(&queued.occurrence_key).await?,
            LocalOutcomeState::Indeterminate
        );
        assert_eq!(self.device.calls.load(Ordering::SeqCst), 0);
        Ok(claim)
    }

    async fn wait_eligible(&self, claim: &DurableDispatchClaim) -> TestResult {
        let delay = claim
            .next_eligible_at_unix_ms
            .saturating_sub(now_unix_ms()?);
        assert!(delay <= 6_000, "fixture wait must stay bounded");
        tokio::time::sleep(Duration::from_millis(delay + 1)).await;
        Ok(())
    }
}

#[tokio::test]
async fn hos2_binding_is_atomic_unique_and_reopens_with_unsigned_d() -> TestResult {
    let temp = tempfile::tempdir()?;
    let fixture = Fixture::open(temp.path()).await?;
    let unsigned_sequence = i64::MAX as u64 + 19;
    let unsigned = fixture.request(unsigned_sequence)?;
    let unsigned_json = unsigned.to_json()?;
    let sqlite_sequence: String =
        sqlx::query_scalar("SELECT json_extract(?, '$.delivery.sequence')")
            .bind(&unsigned_json)
            .fetch_one(&fixture.writer.store.pool)
            .await?;
    assert_eq!(sqlite_sequence, format!("{unsigned_sequence:016x}"));
    assert_eq!(
        Hos2InstallBudgetV1::from_json(&unsigned_json)?
            .delivery
            .sequence()?,
        unsigned_sequence
    );
    assert!(
        fixture.prepare(OPERATION, unsigned_sequence).await.is_err(),
        "a new namespace cannot skip to a large sequence"
    );
    let sequence = 1;
    let request = fixture.request(sequence)?;
    let failed = fixture
        .writer
        .lease
        .admit_operation_with_fault(
            fixture.operation("hos2:aborted", &request)?,
            HOS2_INSTALL_TOPIC_V1,
            request.to_json()?,
            crate::LocalAdmissionFault::AfterOperationBeforeCommit,
        )
        .await;
    assert!(matches!(
        failed,
        Err(LocalLeaseOutboxError::TransactionAborted(_))
    ));
    let rows: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_operation_ledger")
        .fetch_one(&fixture.writer.store.pool)
        .await?;
    assert_eq!(rows, 0);
    let queued = fixture.prepare(OPERATION, sequence).await?;
    assert!(fixture.prepare("hos2:other-k", sequence).await.is_err());
    assert!(fixture.prepare(OPERATION, sequence + 1).await.is_err());
    let mut changed_request = request.clone();
    changed_request.cap_ns = 2_002;
    assert!(
        fixture
            .writer
            .prepare_operation(
                fixture.operation(OPERATION, &changed_request)?,
                HOS2_INSTALL_TOPIC_V1,
                changed_request.to_json()?
            )
            .await
            .is_err()
    );
    let cut = fixture.writer.recovery_anchor().await?;
    drop(fixture);
    let reopened = Fixture::open(temp.path()).await?;
    let replay = reopened.prepare(OPERATION, sequence).await?;
    assert_eq!(
        (&replay.event_id, &replay.outbox_id, &replay.payload_json),
        (&queued.event_id, &queued.outbox_id, &queued.payload_json)
    );
    assert_eq!(reopened.writer.recovery_anchor().await?, cut);
    assert!(reopened.prepare("hos2:other-k", sequence).await.is_err());
    assert_eq!(
        Hos2InstallBudgetV1::from_json(&replay.payload_json)?
            .delivery
            .sequence()?,
        sequence
    );
    Ok(())
}

#[tokio::test]
async fn hos2_lost_ack_reconciles_original_d_without_resending() -> TestResult {
    let temp = tempfile::tempdir()?;
    let fixture = Fixture::open(temp.path()).await?;
    let queued = fixture.prepare(OPERATION, /*sequence*/ 1).await?;
    let (binding, signed) = fixture.signed(&queued, /*nonce*/ 1).await?;
    fixture.device.lose_ack.store(true, Ordering::SeqCst);
    let outcome = fixture
        .dispatcher
        .dispatch(&fixture.writer, &signed, &binding, queued.clone())
        .await?;
    assert_eq!(outcome.state, LocalOutcomeState::Indeterminate);
    assert_eq!(fixture.device.calls.load(Ordering::SeqCst), 1);
    assert!(
        fixture
            .writer
            .awaiting_authorization(HOS2_DESTINATION_V1, /*limit*/ 8)
            .await?
            .is_empty()
    );
    drop(fixture);
    let reopened = Fixture::open(temp.path()).await?;
    assert_eq!(
        reopened
            .dispatcher
            .reconcile(&reopened.writer, /*limit*/ 8)
            .await?,
        1
    );
    assert_eq!(
        reopened.writer.status(OPERATION).await?,
        LocalOutcomeState::Committed
    );
    assert_eq!(reopened.device.calls.load(Ordering::SeqCst), 0);
    let (binding, fresh) = reopened.signed(&queued, /*nonce*/ 2).await?;
    assert!(
        reopened
            .dispatcher
            .dispatch(&reopened.writer, &fresh, &binding, queued)
            .await
            .is_err()
    );
    assert_eq!(reopened.device.calls.load(Ordering::SeqCst), 0);
    Ok(())
}

#[tokio::test]
async fn claim_rejection_preserves_same_k_d_until_fresh_external_authorization() -> TestResult {
    let temp = tempfile::tempdir()?;
    let fixture = Fixture::open(temp.path()).await?;
    let queued = fixture.prepare(OPERATION, /*sequence*/ 1).await?;
    let claim = fixture.reject_claim(&queued).await?;
    assert_eq!(
        fixture
            .dispatcher
            .reconcile(&fixture.writer, /*limit*/ 8)
            .await?,
        0
    );
    assert_eq!(fixture.device.queries.load(Ordering::SeqCst), 0);
    let (binding, old_nonce) = fixture.signed(&queued, /*nonce*/ 1).await?;
    assert!(
        fixture
            .dispatcher
            .dispatch(&fixture.writer, &old_nonce, &binding, queued.clone())
            .await
            .is_err()
    );
    fixture.wait_eligible(&claim).await?;
    let pending = fixture
        .writer
        .awaiting_authorization(HOS2_DESTINATION_V1, /*limit*/ 8)
        .await?;
    assert_eq!(pending.len(), 1);
    let mut expected_receipt = queued.clone();
    expected_receipt.replayed = true;
    assert_eq!(pending, vec![expected_receipt]);
    assert_eq!(
        fixture.writer.status(OPERATION).await?,
        LocalOutcomeState::Indeterminate
    );
    // The generic queue gate remains closed. Fresh authorization must reach
    // the original dispatcher's private current-proof branch instead.
    assert!(matches!(
        fixture
            .writer
            .lease
            .verify_queued_receipt_binding(
                &pending[0].occurrence_key,
                &pending[0].event_id,
                &pending[0].outbox_id,
                &pending[0].topic,
                &pending[0].payload_json,
                &pending[0].payload_sha256,
            )
            .await,
        Err(LocalLeaseOutboxError::StaleFence(_))
    ));
    let (binding, fresh) = fixture.signed(&pending[0], /*nonce*/ 2).await?;
    let mut wrong_event = pending[0].clone();
    wrong_event.event_id.push_str(":other");
    let mut wrong_outbox = pending[0].clone();
    wrong_outbox.outbox_id.push_str(":other");
    for forged in [wrong_event, wrong_outbox] {
        assert!(
            fixture
                .dispatcher
                .dispatch(&fixture.writer, &fresh, &binding, forged)
                .await
                .is_err()
        );
        assert_eq!(
            fixture
                .writer
                .awaiting_authorization(HOS2_DESTINATION_V1, /*limit*/ 8)
                .await?,
            pending
        );
        assert_eq!(fixture.device.calls.load(Ordering::SeqCst), 0);
    }
    let result = fixture
        .dispatcher
        .dispatch(&fixture.writer, &fresh, &binding, pending[0].clone())
        .await?;
    assert_eq!(result.state, LocalOutcomeState::Committed);
    assert_eq!(fixture.device.calls.load(Ordering::SeqCst), 1);
    assert!(
        fixture
            .writer
            .awaiting_authorization(HOS2_DESTINATION_V1, /*limit*/ 8)
            .await?
            .is_empty()
    );
    Ok(())
}

#[tokio::test]
async fn entry_rejection_keeps_nonce_consumed_and_requires_a_new_grant() -> TestResult {
    let temp = tempfile::tempdir()?;
    let fixture = Fixture::open(temp.path()).await?;
    let queued = fixture.prepare(OPERATION, /*sequence*/ 1).await?;
    let claim = fixture
        .writer
        .claim_dispatch_lease(&queued, /*lease_duration_ms*/ 5_000)
        .await?;
    let (binding, signed) = fixture.signed(&queued, /*nonce*/ 1).await?;
    fixture.clock.calls.store(0, Ordering::SeqCst);
    fixture.clock.expire_at_entry.store(true, Ordering::SeqCst);
    assert!(matches!(
        fixture
            .dispatcher
            .dispatch(&fixture.writer, &signed, &binding, queued.clone())
            .await,
        Err(ProductionWriterError::FinalUse(_))
    ));
    fixture.clock.expire_at_entry.store(false, Ordering::SeqCst);
    assert!(matches!(
        fixture.authority.claim(&signed, &binding),
        Err(FinalUseError::AlreadyClaimed)
    ));
    let stage: String = sqlx::query_scalar("SELECT json_extract(proof_json, '$.stage') FROM cognitive_operation_pre_boundary_rejections")
        .fetch_one(&fixture.writer.store.pool).await?;
    assert_eq!(stage, "entry");
    assert_eq!(fixture.device.calls.load(Ordering::SeqCst), 0);
    fixture.wait_eligible(&claim).await?;
    let (binding, fresh) = fixture.signed(&queued, /*nonce*/ 2).await?;
    assert_eq!(
        fixture
            .dispatcher
            .dispatch(&fixture.writer, &fresh, &binding, queued)
            .await?
            .state,
        LocalOutcomeState::Committed
    );
    assert_eq!(fixture.device.calls.load(Ordering::SeqCst), 1);
    Ok(())
}

#[tokio::test]
async fn reconciliation_wins_before_reauthorization_entry_and_foreign_fences_fail() -> TestResult {
    let temp = tempfile::tempdir()?;
    let fixture = Fixture::open(temp.path()).await?;
    let queued = fixture.prepare(OPERATION, /*sequence*/ 1).await?;
    let claim = fixture.reject_claim(&queued).await?;
    let request = fixture
        .writer
        .reconciliation_request(OPERATION, HOS2_DESTINATION_V1)
        .await?;
    let binding = fixture.writer.reauthorization_binding(&request);
    let mut foreign = binding.clone();
    foreign.owner_generation += 1;
    assert!(!operation_claims::has_rejection_proof(&fixture.writer.store, &foreign).await?);
    assert!(
        !operation_claims::awaiting_reauthorization(
            &fixture.writer.store,
            &foreign,
            claim.next_eligible_at_unix_ms
        )
        .await?
    );
    assert!(
        operation_claims::claim_reauthorization(
            &fixture.writer.store,
            &foreign,
            &queued,
            [2; 32],
            claim.next_eligible_at_unix_ms,
            PRODUCTION_DISPATCH_CLAIM_LEASE_MS
        )
        .await
        .is_err()
    );
    let mut foreign = binding.clone();
    foreign.fencing_token.push_str(":other");
    assert!(
        operation_claims::claim_reauthorization(
            &fixture.writer.store,
            &foreign,
            &queued,
            [2; 32],
            claim.next_eligible_at_unix_ms,
            PRODUCTION_DISPATCH_CLAIM_LEASE_MS
        )
        .await
        .is_err()
    );
    let mut foreign = binding.clone();
    foreign.authority_epoch += 1;
    assert!(
        operation_claims::claim_reauthorization(
            &fixture.writer.store,
            &foreign,
            &queued,
            [2; 32],
            claim.next_eligible_at_unix_ms,
            PRODUCTION_DISPATCH_CLAIM_LEASE_MS
        )
        .await
        .is_err()
    );
    let mut foreign = binding.clone();
    foreign.owner_epoch += 1;
    assert!(
        operation_claims::claim_reauthorization(
            &fixture.writer.store,
            &foreign,
            &queued,
            [2; 32],
            claim.next_eligible_at_unix_ms,
            PRODUCTION_DISPATCH_CLAIM_LEASE_MS
        )
        .await
        .is_err()
    );
    let mut foreign = binding.clone();
    foreign.authority_grant_sha256 = Sha256Digest::for_bytes(b"different source issuer grant");
    assert!(
        operation_claims::claim_reauthorization(
            &fixture.writer.store,
            &foreign,
            &queued,
            [2; 32],
            claim.next_eligible_at_unix_ms,
            PRODUCTION_DISPATCH_CLAIM_LEASE_MS
        )
        .await
        .is_err()
    );
    let retry = operation_claims::claim_reauthorization(
        &fixture.writer.store,
        &binding,
        &queued,
        [2; 32],
        claim.next_eligible_at_unix_ms,
        PRODUCTION_DISPATCH_CLAIM_LEASE_MS,
    )
    .await?
    .ok_or("expected the internal proof to produce one retry claim")?;
    fixture
        .writer
        .reconcile(OPERATION, LocalReconcileOutcome::StillIndeterminate)
        .await?;
    assert!(
        operation_claims::enter_reauthorization(
            &fixture.writer.store,
            &binding,
            &retry.claim,
            &retry.dispatch_event_id,
            claim.next_eligible_at_unix_ms
        )
        .await
        .is_err()
    );
    assert_eq!(
        fixture.writer.status(OPERATION).await?,
        LocalOutcomeState::Indeterminate
    );
    assert_eq!(fixture.device.calls.load(Ordering::SeqCst), 0);
    assert!(
        fixture
            .writer
            .awaiting_authorization(HOS2_DESTINATION_V1, /*limit*/ 8)
            .await?
            .is_empty()
    );
    Ok(())
}

#[tokio::test]
async fn a_reconciliation_event_before_retry_claim_invalidates_the_original_proof() -> TestResult {
    let temp = tempfile::tempdir()?;
    let fixture = Fixture::open(temp.path()).await?;
    let queued = fixture.prepare(OPERATION, /*sequence*/ 1).await?;
    let claim = fixture.reject_claim(&queued).await?;
    let request = fixture
        .writer
        .reconciliation_request(OPERATION, HOS2_DESTINATION_V1)
        .await?;
    let binding = fixture.writer.reauthorization_binding(&request);
    fixture
        .writer
        .reconcile(OPERATION, LocalReconcileOutcome::StillIndeterminate)
        .await?;
    assert!(
        operation_claims::claim_reauthorization(
            &fixture.writer.store,
            &binding,
            &queued,
            [2; 32],
            claim.next_eligible_at_unix_ms,
            PRODUCTION_DISPATCH_CLAIM_LEASE_MS
        )
        .await?
        .is_none()
    );
    assert!(
        fixture
            .writer
            .awaiting_authorization(HOS2_DESTINATION_V1, /*limit*/ 8)
            .await?
            .is_empty()
    );
    assert_eq!(
        fixture.writer.status(OPERATION).await?,
        LocalOutcomeState::Indeterminate
    );
    assert_eq!(fixture.device.calls.load(Ordering::SeqCst), 0);
    Ok(())
}

#[tokio::test]
async fn not_seen_and_reason_strings_cannot_create_a_reauthorization_proof() -> TestResult {
    let temp = tempfile::tempdir()?;
    let fixture = Fixture::open(temp.path()).await?;
    let queued = fixture.prepare(OPERATION, /*sequence*/ 1).await?;
    fixture
        .writer
        .mark_indeterminate(OPERATION, "final-use claim rejected: NotSeen before entry")
        .await?;
    assert_eq!(
        fixture
            .dispatcher
            .reconcile(&fixture.writer, /*limit*/ 8)
            .await?,
        1
    );
    assert_eq!(
        fixture.writer.status(OPERATION).await?,
        LocalOutcomeState::Indeterminate
    );
    assert!(
        fixture
            .writer
            .awaiting_authorization(HOS2_DESTINATION_V1, /*limit*/ 8)
            .await?
            .is_empty()
    );
    let (binding, fresh) = fixture.signed(&queued, /*nonce*/ 2).await?;
    assert!(
        fixture
            .dispatcher
            .dispatch(&fixture.writer, &fresh, &binding, queued)
            .await
            .is_err()
    );
    let count: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_operation_pre_boundary_rejections")
            .fetch_one(&fixture.writer.store.pool)
            .await?;
    assert_eq!(count, 0);
    assert_eq!(fixture.device.calls.load(Ordering::SeqCst), 0);
    Ok(())
}

pub(super) fn checkpoint(phase: &str) -> std::io::Result<()> {
    if std::env::var("HEPTA_HOS2_REAUTH_TEST_PHASE")
        .ok()
        .as_deref()
        != Some(phase)
    {
        return Ok(());
    }
    let path = std::env::var_os("HEPTA_HOS2_REAUTH_TEST_READY")
        .ok_or_else(|| std::io::Error::other("child checkpoint requires a ready path"))?;
    let mut ready = OpenOptions::new().write(true).create_new(true).open(path)?;
    ready.write_all(phase.as_bytes())?;
    ready.sync_all()?;
    loop {
        std::thread::park();
    }
}

#[path = "production_hos2_process_tests.rs"]
mod process_tests;

#[path = "production_hos2_ordering_tests.rs"]
mod ordering_tests;

#[path = "production_hos2_conflict_tests.rs"]
mod conflict_tests;

#[path = "production_hos2_native_profile_tests.rs"]
mod native_profile_tests;
