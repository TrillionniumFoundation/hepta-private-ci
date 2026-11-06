//! Real SQLite writer and signed FinalUse, with the existing explicitly
//! scripted HOS2 transport and clock. These are not native benchmark results.
use super::*;
use crate::CpuBudgetProposal;
use crate::CpuDemandSample;
use crate::CpuPolicy;
use crate::CpuPolicyConsumer;
use crate::CpuPolicyError;
use crate::CpuPolicyKind;
use crate::CpuPolicySubmission;
use crate::ObservedCpuDemand;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::HOS2_DESTINATION_V1;
use codex_hepta_memory::HOS2_INSTALL_TOPIC_V1;
use codex_hepta_memory::Hos2InstallAdmission;
use codex_hepta_memory::LocalOutcomeState;
use codex_hepta_memory::ProductionAuthorityLease;
use codex_hepta_memory::ProductionAuthorityToken;
use codex_hepta_memory::ProductionAuthorityVerifier;
use codex_hepta_memory::ProductionDurableWriter;
use codex_hepta_memory::ProductionFinalUseOutboxDispatcher;
use codex_hepta_memory::ProductionHos2Target;
use codex_hepta_memory::ProductionQueuedReceipt;
use codex_hepta_memory::ProductionWriterError;
use codex_hepta_operations::OperationIntentV1;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

const VALUES: [u64; 8] = [
    10_000_000_000,
    2_000_000_000,
    10_000_000_000,
    0,
    20_000_000,
    HOS2_CPU_PERIOD_NS,
    9,
    0,
];

struct PolicyFixture {
    writer: Arc<ProductionDurableWriter>,
    dispatcher: ProductionFinalUseOutboxDispatcher,
    consumer: Arc<CpuPolicyConsumer>,
    native: Arc<AgentdHos2Device>,
    initial: AgentdHos2Usage,
    clock: Arc<AtomicU64>,
    issuer: SigningKey,
    script: Arc<Mutex<Script>>,
    _root: tempfile::TempDir,
}

impl PolicyFixture {
    async fn open() -> TestResult<Self> {
        let root = tempfile::tempdir()?;
        let fleet_path = root.path().join("fleet");
        std::fs::create_dir(&fleet_path)?;
        let fleet = HeptaFleetRoot::parse(fleet_path.canonicalize()?)?;
        let owner = AgentId::parse("00000000-0000-4000-8000-00000000c061")?;
        let store = CognitiveStore::open(&fleet.layout().agent(&owner)).await?;
        let authority = ProductionAuthorityLease::from_verified_parts(
            owner,
            Sha256Digest::for_bytes(b"cpu-policy-fixture-source"),
            /*authority_epoch*/ 31,
            /*owner_epoch*/ 41,
            /*lease_expires_at_unix_seconds*/ 4_000_000_000,
            ProductionAuthorityToken::from_verified_bytes(b"cpu-policy-fixture-token".to_vec())?,
        )?;
        let verifier: Arc<dyn ProductionAuthorityVerifier> =
            Arc::new(|_: &ProductionAuthorityLease, _: &AgentId| Ok(()));
        let writer = Arc::new(
            ProductionDurableWriter::open_with_live_verifier(
                store,
                authority,
                verifier,
                "cpu-policy-fixture",
                /*generation*/ 1,
            )
            .await?,
        );
        let (native, script) = usage_fixture(1, Ok(usage_response(VALUES, 1)))?;
        let initial = native.read_usage(41)?;
        let clock = Arc::new(AtomicU64::new(VALUES[0]));
        let observed_clock = clock.clone();
        let native = Arc::new(native);
        let consumer = Arc::new(CpuPolicyConsumer::new(
            native.clone(),
            Arc::new(move || match observed_clock.load(Ordering::SeqCst) {
                u64::MAX => Err("explicit fixture clock unavailable".into()),
                now => Ok(now),
            }),
        ));
        let target = Arc::new(ProductionHos2Target::with_admission(
            native.clone(),
            consumer.clone(),
        ));
        let final_use_path = root.path().join("final-use");
        std::fs::create_dir(&final_use_path)?;
        std::fs::set_permissions(&final_use_path, std::fs::Permissions::from_mode(0o700))?;
        let issuer = SigningKey::from_bytes(&[51; 32]);
        let final_use = FinalUseAuthority::open_state_dir(
            &final_use_path,
            "cpu-policy-fixture-issuer".into(),
            issuer.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 71,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )?;
        let dispatcher = ProductionFinalUseOutboxDispatcher::attach(final_use, target);
        Ok(Self {
            writer,
            dispatcher,
            consumer,
            native,
            initial,
            clock,
            issuer,
            script,
            _root: root,
        })
    }

    fn proposal(&self, demand_lag: u64) -> TestResult<CpuBudgetProposal> {
        let mut policy = CpuPolicy::new(
            CpuPolicyKind::Fixed { cap_ns: 50_000_000 },
            50_000_000,
            &self.initial,
        )?;
        Ok(policy
            .propose(
                &self.initial,
                &CpuDemandSample {
                    boot_id: self.initial.boot_id,
                    observer_space_id: self.initial.observer_space_id,
                    sample_boottime_ns: VALUES[0] - demand_lag,
                    demand: ObservedCpuDemand::Stable,
                },
                VALUES[0],
            )?
            .ok_or("missing fixed proposal")?)
    }

    async fn retain(&self, demand_lag: u64) -> TestResult<CpuPolicySubmission> {
        let sequence = self
            .writer
            .next_hos2_delivery_sequence(self.initial.boot_id, self.initial.observer_space_id)
            .await?;
        self.reply(2, Ok(usage_response(VALUES, 1)))?;
        Ok(self
            .consumer
            .prepare(self.proposal(demand_lag)?, sequence)?)
    }

    async fn queue(&self, request: &Hos2InstallBudgetV1) -> TestResult<ProductionQueuedReceipt> {
        let payload = request.to_json()?;
        let operation = OperationIntentV1::new(
            StableId::new("cpu-policy:tick")?,
            StableId::new(self.writer.owner_agent_id().as_str())?,
            StableId::new(HOS2_DESTINATION_V1)?,
            Digest32::of_bytes(payload.as_bytes()),
            request.scope_digest(),
            Generation::new(1)?,
            /*expected_predecessor*/ None,
        )?;
        Ok(self
            .writer
            .prepare_operation(operation, HOS2_INSTALL_TOPIC_V1, payload)
            .await?)
    }

    async fn grant(
        &self,
        queued: &ProductionQueuedReceipt,
        nonce: u8,
    ) -> TestResult<(codex_hepta_contracts::FinalUseBinding, SignedFinalUseGrant)> {
        let binding = self
            .writer
            .final_use_binding(queued, HOS2_DESTINATION_V1)
            .await?;
        // An actual async boundary separates proposal/request preparation from
        // original signed-grant consumption. Tests change native state hereafter.
        tokio::task::yield_now().await;
        let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "cpu-policy-fixture-issuer".into(),
            authority_epoch: 71,
            grant_id: format!("cpu-policy-fixture-{nonce}"),
            nonce: [nonce; 32],
            binding: binding.clone(),
            not_before_unix_ms: now.saturating_sub(1_000),
            expires_at_unix_ms: now + 60_000,
        };
        let signature = self
            .issuer
            .sign(&grant.signing_bytes()?)
            .to_bytes()
            .to_vec();
        Ok((binding, SignedFinalUseGrant { grant, signature }))
    }

    fn reply(&self, opcode: u16, response: Result<Response, String>) -> TestResult {
        self.script
            .lock()
            .map_err(|error| error.to_string())?
            .replies
            .push_back((opcode, response));
        Ok(())
    }

    fn opcodes(&self) -> TestResult<Vec<u16>> {
        self.script
            .lock()
            .map_err(|error| error.to_string())?
            .requests
            .iter()
            .map(|frame| Ok(read_u16(frame, 8)?))
            .collect()
    }
}

#[tokio::test]
async fn cpu_policy_final_use_installs_only_after_the_consumer_observation() -> TestResult {
    let fixture = PolicyFixture::open().await?;
    let retained = fixture.retain(0).await?;
    let queued = fixture.queue(retained.request()).await?;
    let (binding, signed) = fixture.grant(&queued, 1).await?;
    fixture.reply(2, Ok(usage_response(VALUES, 1)))?;
    fixture.reply(3, Ok(acknowledgement()))?;
    fixture.reply(4, Ok(applied_query(1, HOS2_CPU_PERIOD_NS + 1_001, 999)))?;
    let result = fixture
        .dispatcher
        .dispatch(&fixture.writer, &signed, &binding, queued.clone())
        .await?;
    assert_eq!(
        (
            result.state,
            serde_json::to_value(result.target_disposition)?,
            result.external_effect
        ),
        (
            LocalOutcomeState::Committed,
            serde_json::json!("committed"),
            true
        )
    );
    assert_eq!(
        fixture
            .writer
            .retained_hos2_terminal(&queued.occurrence_key)
            .await?
            .request_json,
        retained.request().to_json()?
    );
    assert_eq!(fixture.opcodes()?, vec![1, 2, 2, 2, 3, 4]);
    Ok(())
}

#[tokio::test]
async fn cpu_policy_final_use_refuses_changed_identity_revision_age_and_missing_proposal()
-> TestResult {
    for change in [
        "boot",
        "space",
        "revision",
        "usage_age",
        "demand_age",
        "dropped",
        "observation_error",
    ] {
        let fixture = PolicyFixture::open().await?;
        let mut retained = Some(
            fixture
                .retain(if change == "demand_age" {
                    100_000_000
                } else {
                    0
                })
                .await?,
        );
        let mut request = retained.as_ref().ok_or("missing handle")?.request().clone();
        if change == "boot" {
            request.delivery.boot_id = [7; 16];
        }
        if change == "space" {
            request.delivery.space_id = [7; 16];
        }
        let queued = fixture.queue(&request).await?;
        let (binding, signed) = fixture.grant(&queued, 1).await?;
        let mut current = VALUES;
        if matches!(change, "usage_age" | "demand_age") {
            current[0] = 12_000_000_000;
            current[2] = current[0];
            fixture.clock.store(
                current[0] + u64::from(change == "usage_age"),
                Ordering::SeqCst,
            );
        }
        if change == "dropped" {
            drop(retained.take());
        }
        fixture.reply(
            2,
            if change == "observation_error" {
                Err("explicit fixture loses a read-only observation".into())
            } else {
                Ok(usage_response(
                    current,
                    if change == "revision" { 2 } else { 1 },
                ))
            },
        )?;
        let result = fixture
            .dispatcher
            .dispatch(&fixture.writer, &signed, &binding, queued.clone())
            .await;
        assert!(
            matches!(result, Err(ProductionWriterError::ConsumerEntryRejected(_))),
            "{change}: {result:?}"
        );
        assert_eq!(
            fixture.writer.status(&queued.occurrence_key).await?,
            LocalOutcomeState::Indeterminate
        );
        assert!(
            fixture
                .writer
                .retained_hos2_terminal(&queued.occurrence_key)
                .await
                .is_err()
        );
        assert!(
            !fixture.opcodes()?.contains(&3),
            "{change} entered InstallBudget"
        );
    }
    Ok(())
}

#[tokio::test]
async fn cpu_policy_final_use_retries_same_k_d_and_installs_once_with_a_fresh_proposal()
-> TestResult {
    let fixture = PolicyFixture::open().await?;
    let retained = fixture.retain(0).await?;
    let queued = fixture.queue(retained.request()).await?;
    let claim = fixture
        .writer
        .claim_dispatch_lease(&queued, /*lease_duration_ms*/ 5_000)
        .await?;
    let (binding, signed) = fixture.grant(&queued, 1).await?;
    fixture
        .clock
        .store(VALUES[0] + 2_000_000_001, Ordering::SeqCst);
    fixture.reply(2, Ok(usage_response(VALUES, 1)))?;
    assert!(matches!(
        fixture
            .dispatcher
            .dispatch(&fixture.writer, &signed, &binding, queued.clone())
            .await,
        Err(ProductionWriterError::ConsumerEntryRejected(_))
    ));
    assert!(
        fixture
            .dispatcher
            .dispatch(&fixture.writer, &signed, &binding, queued.clone())
            .await
            .is_err()
    );
    assert_eq!(fixture.opcodes()?, vec![1, 2, 2, 2]);
    let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    let delay = claim.next_eligible_at_unix_ms.saturating_sub(now);
    assert!(delay <= 6_000);
    tokio::time::sleep(Duration::from_millis(delay + 1)).await;
    let pending = fixture
        .writer
        .awaiting_authorization(HOS2_DESTINATION_V1, 1)
        .await?;
    let mut replay = queued.clone();
    replay.replayed = true;
    assert_eq!(
        serde_json::to_value(&pending)?,
        serde_json::to_value([&replay])?
    );
    assert!(
        fixture
            .writer
            .next_hos2_delivery_sequence([1; 16], [2; 16])
            .await
            .is_err()
    );
    drop(retained);
    let mut current = VALUES;
    current[0] = 14_000_000_000;
    current[2] = current[0];
    fixture.clock.store(current[0], Ordering::SeqCst);
    fixture.reply(2, Ok(usage_response(current, 1)))?;
    let usage = fixture.native.read_usage(42)?;
    let mut policy = CpuPolicy::new(
        CpuPolicyKind::Fixed { cap_ns: 50_000_000 },
        50_000_000,
        &usage,
    )?;
    let proposal = policy
        .propose(
            &usage,
            &CpuDemandSample {
                boot_id: usage.boot_id,
                observer_space_id: usage.observer_space_id,
                sample_boottime_ns: usage.sample_boottime_ns,
                demand: ObservedCpuDemand::Stable,
            },
            current[0],
        )?
        .ok_or("missing fresh proposal")?;
    fixture.reply(2, Ok(usage_response(current, 1)))?;
    let original = Hos2InstallBudgetV1::from_json(&replay.payload_json)?;
    let fresh = fixture
        .consumer
        .prepare(proposal, original.delivery.sequence()?)?;
    assert_eq!(fresh.request(), &original);
    let (binding, signed) = fixture.grant(&replay, 2).await?;
    fixture.reply(2, Ok(usage_response(current, 1)))?;
    let effective = current[0] + 1_001;
    fixture.reply(
        3,
        Ok(Response {
            status: 0,
            revision: 2,
            payload: [1, effective, 999]
                .into_iter()
                .flat_map(u64::to_le_bytes)
                .collect(),
        }),
    )?;
    fixture.reply(4, Ok(applied_query(1, effective, 999)))?;
    let result = fixture
        .dispatcher
        .dispatch(&fixture.writer, &signed, &binding, replay)
        .await?;
    assert_eq!(result.state, LocalOutcomeState::Committed);
    assert_eq!(fixture.opcodes()?, vec![1, 2, 2, 2, 2, 2, 2, 3, 4]);
    assert_eq!(
        fixture
            .writer
            .next_hos2_delivery_sequence([1; 16], [2; 16])
            .await?,
        2
    );
    Ok(())
}

#[tokio::test]
async fn cpu_policy_final_use_never_turns_entered_transport_failure_into_non_entry() -> TestResult {
    let fixture = PolicyFixture::open().await?;
    let retained = fixture.retain(0).await?;
    let queued = fixture.queue(retained.request()).await?;
    let (binding, signed) = fixture.grant(&queued, 1).await?;
    fixture.reply(2, Ok(usage_response(VALUES, 1)))?;
    fixture.reply(
        3,
        Err("explicit fixture loses response after entering device".into()),
    )?;
    let result = fixture
        .dispatcher
        .dispatch(&fixture.writer, &signed, &binding, queued.clone())
        .await?;
    assert_eq!(
        (
            result.state,
            serde_json::to_value(result.target_disposition)?
        ),
        (
            LocalOutcomeState::Indeterminate,
            serde_json::json!("indeterminate")
        )
    );
    let before = fixture.opcodes()?;
    assert_eq!(before, vec![1, 2, 2, 2, 3]);
    assert!(
        fixture
            .dispatcher
            .dispatch(&fixture.writer, &signed, &binding, queued)
            .await
            .is_err()
    );
    assert_eq!(fixture.opcodes()?, before);
    Ok(())
}

#[tokio::test]
async fn cpu_policy_consumer_preserves_one_proposal_and_fences_observed_event_loss() -> TestResult {
    let fixture = PolicyFixture::open().await?;
    let retained = fixture.retain(0).await?;
    assert!(matches!(
        fixture.consumer.prepare(fixture.proposal(0)?, 1),
        Err(CpuPolicyError::Busy)
    ));
    let mut lost = VALUES;
    lost[7] = 1;
    fixture.reply(2, Ok(usage_response(lost, 1)))?;
    assert_eq!(
        fixture.consumer.check(retained.request()).unwrap_err(),
        CpuPolicyError::EventLoss.to_string()
    );
    let before = fixture.opcodes()?;
    fixture.reply(2, Ok(usage_response(VALUES, 1)))?;
    assert_eq!(
        fixture.consumer.check(retained.request()).unwrap_err(),
        CpuPolicyError::EventLoss.to_string()
    );
    drop(retained);
    assert!(matches!(
        fixture.consumer.prepare(fixture.proposal(0)?, 1),
        Err(CpuPolicyError::EventLoss)
    ));
    assert_eq!(fixture.opcodes()?, before);
    Ok(())
}

#[tokio::test]
async fn cpu_policy_consumer_preparation_event_loss_also_fences_later_admission() -> TestResult {
    for now in [VALUES[0], u64::MAX, VALUES[0] + 2_000_000_001] {
        let fixture = PolicyFixture::open().await?;
        fixture.clock.store(now, Ordering::SeqCst);
        let mut lost = VALUES;
        lost[7] = 1;
        fixture.reply(2, Ok(usage_response(lost, 1)))?;
        assert!(matches!(
            fixture.consumer.prepare(fixture.proposal(0)?, 1),
            Err(CpuPolicyError::EventLoss)
        ));
        let before = fixture.opcodes()?;
        fixture.clock.store(VALUES[0], Ordering::SeqCst);
        fixture.reply(2, Ok(usage_response(VALUES, 1)))?;
        assert!(matches!(
            fixture.consumer.prepare(fixture.proposal(0)?, 1),
            Err(CpuPolicyError::EventLoss)
        ));
        assert_eq!(fixture.opcodes()?, before);
    }
    Ok(())
}
