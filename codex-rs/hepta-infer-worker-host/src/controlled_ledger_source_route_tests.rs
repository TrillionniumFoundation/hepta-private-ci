use super::*;
use crate::controlled_funding::*;
use codex_hepta_authbus::*;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error + Send + Sync>>;

struct SignedClock(AtomicU64);

impl ControlledTrustedTimeProvider for SignedClock {
    fn signed_time(&self) -> Result<SignedTrustedTimeAttestation, String> {
        let revision = self.0.fetch_add(1, Ordering::SeqCst);
        let claims = TrustedTimeAttestationClaims {
            issuer_id: StableId::new("time:controlled").map_err(|e| e.to_string())?,
            key_epoch: Generation::new(1).map_err(|e| e.to_string())?,
            wall_time_ms: 1_000 + revision,
            source_revision: revision,
            source_digest: Digest32::of_bytes(&revision.to_be_bytes()),
        };
        let signature = SigningKey::from_bytes(&[121; 32])
            .sign(&claims.signing_bytes())
            .to_bytes();
        Ok(SignedTrustedTimeAttestation { claims, signature })
    }
}

struct Ledger {
    owner: Arc<AuthBusAuthorityHost>,
    clock: Arc<SignedClock>,
    admission: ControlledLedgerAdmission,
    database: PathBuf,
    checkpoint: PathBuf,
}

impl Ledger {
    async fn new(fixture: &ControlledFixture) -> TestResult<Self> {
        let root = fixture.source.temp.path();
        let database_dir = root.join("ledger");
        let checkpoint_dir = root.join("checkpoint");
        for directory in [&database_dir, &checkpoint_dir] {
            std::fs::create_dir(directory)?;
            std::fs::set_permissions(directory, std::fs::Permissions::from_mode(0o700))?;
        }
        let database = database_dir.join("authority.sqlite");
        let checkpoint = checkpoint_dir.join("frontier.json");
        let raw = AuthBusAuthorityStore::open(&database).await?;
        let frontier = raw.authority_frontier_digest().await?;
        drop(raw);
        let mut file = std::fs::OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .open(&checkpoint)?;
        serde_json::to_writer(
            &mut file,
            &serde_json::json!({
                "schema_version": 1, "owner_id": "controlled-owner",
                "generation": 1, "digest": frontier.to_string(),
            }),
        )?;
        file.sync_all()?;
        drop(file);
        let owner = Arc::new(
            AuthBusAuthorityHost::open(&database, checkpoint.clone(), "controlled-owner").await?,
        );
        let binding = &fixture.declared;
        for (purpose, issuer_id, key) in [
            (IssuerPurpose::TrustedTime, "time:controlled", [121; 32]),
            (
                IssuerPurpose::Settlement,
                binding.settlement_issuer_id.as_str(),
                [122; 32],
            ),
        ] {
            owner
                .enroll_issuer(
                    purpose,
                    IssuerSpec {
                        issuer_id: StableId::new(issuer_id)?,
                        key_epoch: Generation::new(1)?,
                        verifying_key: SigningKey::from_bytes(&key).verifying_key(),
                    },
                )
                .await?;
        }
        let clock = Arc::new(SignedClock(AtomicU64::new(1)));
        let time = owner
            .observe_trusted_time_attestation(&clock.signed_time()?)
            .await?;
        owner
            .create_policy(
                PolicySpec {
                    policy_id: StableId::new("policy:controlled")?,
                    principal: binding.subject_id.clone(),
                    action: StableId::new(CONTROLLED_LEDGER_ACTION)?,
                    scope_digest: binding.scope_digest,
                    effect: PolicyEffect::Allow,
                    not_before_ms: 1_000,
                    expires_at_ms: 60_000,
                },
                time,
            )
            .await?;
        let time = owner
            .observe_trusted_time_attestation(&clock.signed_time()?)
            .await?;
        let quota = owner
            .create_quota(
                QuotaSpec {
                    quota_key: StableId::new("quota:controlled")?,
                    principal: binding.subject_id.clone(),
                    scope_digest: binding.scope_digest,
                    unit: StableId::new(CONTROLLED_LEDGER_UNIT)?,
                    period_id: StableId::new("period:controlled")?,
                    limit: 1,
                },
                time,
            )
            .await?;
        Ok(Self {
            owner,
            clock,
            database,
            checkpoint,
            admission: ControlledLedgerAdmission {
                quota_key: quota.quota_key,
                expected_quota_revision: 1,
                policy_revision: 1,
                expires_at_ms: 50_000,
            },
        })
    }

    async fn fund(
        &self,
        fixture: &ControlledFixture,
    ) -> TestResult<LedgerFundedControlledAggregate> {
        let mut plan = fixture.declared.clone();
        plan.operation_id = StableId::new("funded-controlled-effect")?;
        Ok(LedgerFundedControlledAggregate::reserve(
            ControlledAggregateRegistration::new(plan)?,
            self.owner.clone(),
            self.admission.clone(),
            self.clock.clone(),
        )
        .await?)
    }

    async fn assert_reserved(&self) -> TestResult {
        let quota = self.owner.quota_snapshot(&self.admission.quota_key).await?;
        assert_eq!((quota.available, quota.reserved, quota.consumed), (0, 1, 0));
        Ok(())
    }
}

async fn prepared(
    fixture: &ControlledFixture,
    funded: LedgerFundedControlledAggregate,
) -> TestResult<(
    ProductionFinalUseOutboxDispatcher,
    ProductionQueuedReceipt,
    FinalUseBinding,
    SignedFinalUseGrant,
)> {
    let registration = funded.registration();
    let queued = fixture
        .source
        .writer
        .prepare_operation(
            registration.operation()?,
            TOPIC,
            &registration.payload_json()?,
        )
        .await?;
    let binding = fixture
        .source
        .writer
        .final_use_binding(&queued, CONTROLLED_DESTINATION)
        .await?;
    let mut grant = fixture.source.signed_grant("funded-controlled-grant", 91);
    grant.grant.binding = binding.clone();
    grant.signature = SigningKey::from_bytes(&[113; 32])
        .sign(&grant.grant.signing_bytes()?)
        .to_bytes()
        .to_vec();
    let target = Arc::new(ControlledAggregateTarget::ledger_funded_unavailable(
        funded,
        fixture.source.target.authority.clone(),
        binding.clone(),
    )?);
    Ok((
        ProductionFinalUseOutboxDispatcher::attach(fixture.source.target.authority.clone(), target),
        queued,
        binding,
        grant,
    ))
}

async fn assert_no_native(fixture: &ControlledFixture) -> TestResult {
    let entries: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM ordinary_cpu_entries")
        .fetch_one(&fixture.source.pool)
        .await?;
    assert_eq!(entries, 0);
    assert!(!fixture.source.temp.path().join("child-marker").exists());
    Ok(())
}

#[tokio::test]
async fn original_ledger_funding_reaches_signed_target_and_restart_retains_every_unit() -> TestResult
{
    let fixture = ControlledFixture::new(|_| {}).await;
    let ledger = Ledger::new(&fixture).await?;
    let funded = ledger.fund(&fixture).await?;
    let reservation_id = funded.registration().0.reservation_id.clone();
    assert_ne!(reservation_id, fixture.declared.reservation_id);
    let (dispatcher, queued, binding, grant) = prepared(&fixture, funded).await?;
    let actual_payload: serde_json::Value = serde_json::from_str(&queued.payload_json)?;
    assert_eq!(actual_payload["reservation_id"], reservation_id.as_str());
    let receipt = dispatcher
        .dispatch(&fixture.source.writer, &grant, &binding, queued.clone())
        .await?;
    assert_eq!(receipt.state, LocalOutcomeState::Indeterminate);
    assert_eq!(
        ledger.owner.reservation(&reservation_id).await?.state,
        ReservationState::Indeterminate
    );
    assert!(
        dispatcher
            .dispatch(&fixture.source.writer, &grant, &binding, queued)
            .await
            .is_err()
    );
    dispatcher.reconcile(&fixture.source.writer, 8).await?;
    ledger.assert_reserved().await?;
    assert_no_native(&fixture).await?;
    let database = ledger.database.clone();
    let checkpoint = ledger.checkpoint.clone();
    let quota_key = ledger.admission.quota_key.clone();
    drop(dispatcher);
    drop(ledger);
    let restarted = AuthBusAuthorityHost::open(&database, checkpoint, "controlled-owner").await?;
    let retained = restarted.reservation(&reservation_id).await?;
    assert_eq!(retained.state, ReservationState::Indeterminate);
    assert_eq!(
        (
            retained.terminal_evidence,
            retained.observed_cost,
            retained.settlement_digest
        ),
        (None, None, None)
    );
    let quota = restarted.quota_snapshot(&quota_key).await?;
    assert_eq!((quota.available, quota.reserved, quota.consumed), (0, 1, 0));
    assert_eq!(
        fixture
            .source
            .writer
            .status("funded-controlled-effect")
            .await?,
        LocalOutcomeState::Indeterminate
    );
    Ok(())
}

#[tokio::test]
async fn issuer_or_policy_revocation_after_funding_refuses_dispatch_without_refund() -> TestResult {
    for revoke in ["issuer", "policy", "time"] {
        let fixture = ControlledFixture::new(|_| {}).await;
        let ledger = Ledger::new(&fixture).await?;
        let funded = ledger.fund(&fixture).await?;
        let reservation_id = funded.registration().0.reservation_id.clone();
        if revoke == "policy" {
            let time = ledger
                .owner
                .observe_trusted_time_attestation(&ledger.clock.signed_time()?)
                .await?;
            ledger
                .owner
                .revoke_policy(&StableId::new("policy:controlled")?, 1, time)
                .await?;
        } else {
            let (purpose, id) = if revoke == "issuer" {
                (
                    IssuerPurpose::Settlement,
                    fixture.declared.settlement_issuer_id.clone(),
                )
            } else {
                (
                    IssuerPurpose::TrustedTime,
                    StableId::new("time:controlled")?,
                )
            };
            let second_owner = AuthBusAuthorityHost::open(
                &ledger.database,
                ledger.checkpoint.clone(),
                "controlled-owner",
            )
            .await?;
            second_owner
                .revoke_issuer(purpose, &id, Generation::new(1)?, 1)
                .await?;
        }
        let (dispatcher, queued, binding, grant) = prepared(&fixture, funded).await?;
        assert_eq!(
            dispatcher
                .dispatch(&fixture.source.writer, &grant, &binding, queued)
                .await?
                .state,
            LocalOutcomeState::Indeterminate
        );
        assert_eq!(
            ledger.owner.reservation(&reservation_id).await?.state,
            ReservationState::Held
        );
        ledger.assert_reserved().await?;
        assert_no_native(&fixture).await?;
    }
    Ok(())
}

#[tokio::test]
async fn wrong_sealed_authority_or_original_registration_cannot_touch_funding() -> TestResult {
    for foreign_owner in [false, true] {
        let fixture = ControlledFixture::new(|_| {}).await;
        let ledger = Ledger::new(&fixture).await?;
        let funded = ledger.fund(&fixture).await?;
        let reservation_id = funded.registration().0.reservation_id.clone();
        let registration = funded.registration();
        let actual = fixture
            .source
            .writer
            .prepare_operation(
                registration.operation()?,
                TOPIC,
                &registration.payload_json()?,
            )
            .await?;
        let binding = fixture
            .source
            .writer
            .final_use_binding(&actual, CONTROLLED_DESTINATION)
            .await?;
        let target = Arc::new(ControlledAggregateTarget::ledger_funded_unavailable(
            funded,
            fixture.source.target.authority.clone(),
            binding,
        )?);
        assert!(matches!(
            target.dispatch(fixture.request.clone()).await,
            ProductionTargetOutcome::Indeterminate { .. }
        ));
        let owner = if foreign_owner {
            authority(
                &fixture.source.temp,
                "foreign-ledger-target",
                fixture.source.clock.clone(),
            )
        } else {
            fixture.source.target.authority.clone()
        };
        let dispatcher = ProductionFinalUseOutboxDispatcher::attach(owner, target);
        let result = dispatcher
            .dispatch(
                &fixture.source.writer,
                &fixture.signed(),
                &fixture.binding,
                fixture.queued.clone(),
            )
            .await;
        if foreign_owner {
            assert!(matches!(
                result,
                Err(ProductionWriterError::FinalUse(
                    FinalUseError::BindingMismatch
                ))
            ));
        } else {
            assert_eq!(result?.state, LocalOutcomeState::Indeterminate);
        }
        assert_eq!(
            ledger.owner.reservation(&reservation_id).await?.state,
            ReservationState::Held
        );
        ledger.assert_reserved().await?;
        assert_no_native(&fixture).await?;
    }
    Ok(())
}

#[tokio::test]
async fn absent_issuer_and_exhausted_original_quota_never_mint_funding() -> TestResult {
    let fixture = ControlledFixture::new(|_| {}).await;
    let ledger = Ledger::new(&fixture).await?;
    let mut missing = fixture.declared.clone();
    missing.settlement_issuer_id = StableId::new("issuer:absent")?;
    assert!(
        LedgerFundedControlledAggregate::reserve(
            ControlledAggregateRegistration::new(missing)?,
            ledger.owner.clone(),
            ledger.admission.clone(),
            ledger.clock.clone(),
        )
        .await
        .is_err()
    );
    let quota = ledger
        .owner
        .quota_snapshot(&ledger.admission.quota_key)
        .await?;
    assert_eq!((quota.available, quota.reserved, quota.consumed), (1, 0, 0));
    let funded = ledger.fund(&fixture).await?;
    let mut another = fixture.declared.clone();
    another.operation_id = StableId::new("second-funded-operation")?;
    let mut admission = ledger.admission.clone();
    admission.expected_quota_revision = 2;
    assert!(
        LedgerFundedControlledAggregate::reserve(
            ControlledAggregateRegistration::new(another)?,
            ledger.owner.clone(),
            admission,
            ledger.clock.clone(),
        )
        .await
        .is_err()
    );
    ledger.assert_reserved().await?;
    assert_eq!(
        ledger
            .owner
            .reservation(&funded.registration().0.reservation_id)
            .await?
            .state,
        ReservationState::Held
    );
    assert_no_native(&fixture).await?;
    Ok(())
}

#[tokio::test]
async fn controlled_funding_domain_fixes_all_plan_and_admission_fields_before_actual_id()
-> TestResult {
    let fixture = ControlledFixture::new(|_| {}).await;
    let ledger = Ledger::new(&fixture).await?;
    let original = effect_digest(&fixture.registration, &ledger.admission)?;
    for field in [
        "subject",
        "operation",
        "lease",
        "issuer",
        "epoch",
        "source",
        "scope",
        "policy",
        "resource_scope",
        "plan_memory",
        "plan_cpu",
        "plan_tasks",
        "aggregate_memory",
        "aggregate_cpu",
        "aggregate_tasks",
        "controller_memory",
        "controller_cpu",
        "controller_tasks",
        "deadline",
        "quota",
        "quota_revision",
        "policy_revision",
        "expiry",
    ] {
        let mut registration = ControlledAggregateRegistration::new(fixture.declared.clone())?;
        let mut admission = ledger.admission.clone();
        match field {
            "subject" => registration.0.subject_id = StableId::new("other-subject")?,
            "operation" => registration.0.operation_id = StableId::new("other-operation")?,
            "lease" => registration.0.lease_id = StableId::new("other-lease")?,
            "issuer" => registration.0.settlement_issuer_id = StableId::new("other-issuer")?,
            "epoch" => registration.0.settlement_key_epoch += 1,
            "source" => registration.0.source_digest = Digest32::of_bytes(b"other-source"),
            "scope" => registration.0.scope_digest = Digest32::of_bytes(b"other-scope"),
            "policy" => registration.0.policy_generation = Generation::new(2)?,
            "resource_scope" => registration.0.resource_scope = ResourceScope::ChildAggregate,
            "plan_memory" => registration.0.planned_budget.memory_bytes -= 1,
            "plan_cpu" => registration.0.planned_budget.cpu_percent -= 1,
            "plan_tasks" => registration.0.planned_budget.tasks -= 1,
            "aggregate_memory" => registration.0.aggregate_budget.memory_bytes -= 1,
            "aggregate_cpu" => registration.0.aggregate_budget.cpu_percent -= 1,
            "aggregate_tasks" => registration.0.aggregate_budget.tasks -= 1,
            "controller_memory" => registration.0.controller_budget.memory_bytes -= 1,
            "controller_cpu" => registration.0.controller_budget.cpu_percent -= 1,
            "controller_tasks" => registration.0.controller_budget.tasks -= 1,
            "deadline" => registration.0.observer_deadline_ms -= 1,
            "quota" => admission.quota_key = StableId::new("other-quota")?,
            "quota_revision" => admission.expected_quota_revision += 1,
            "policy_revision" => admission.policy_revision += 1,
            "expiry" => admission.expires_at_ms -= 1,
            _ => unreachable!(),
        }
        assert_ne!(
            effect_digest(&registration, &admission)?,
            original,
            "{field}"
        );
    }
    let mut declared_id = ControlledAggregateRegistration::new(fixture.declared.clone())?;
    declared_id.0.reservation_id = StableId::new("different-declaration-not-ledger-id")?;
    assert_eq!(effect_digest(&declared_id, &ledger.admission)?, original);
    Ok(())
}

#[tokio::test]
async fn funded_request_root_is_fixed_even_when_other_signed_plan_fields_match() -> TestResult {
    let fixture = ControlledFixture::new(|_| {}).await;
    let ledger = Ledger::new(&fixture).await?;
    let funded = ledger.fund(&fixture).await?;
    let registration = funded.registration();
    let reservation_id = registration.0.reservation_id.clone();
    let queued = fixture
        .source
        .writer
        .prepare_operation(
            registration.operation()?,
            TOPIC,
            &registration.payload_json()?,
        )
        .await?;
    let binding = fixture
        .source
        .writer
        .final_use_binding(&queued, CONTROLLED_DESTINATION)
        .await?;
    let mut different = binding.clone();
    different.request_sha256[0] ^= 1;
    let target = Arc::new(ControlledAggregateTarget::ledger_funded_unavailable(
        funded,
        fixture.source.target.authority.clone(),
        different,
    )?);
    let dispatcher =
        ProductionFinalUseOutboxDispatcher::attach(fixture.source.target.authority.clone(), target);
    let mut grant = fixture.source.signed_grant("other-funded-request", 92);
    grant.grant.binding = binding.clone();
    grant.signature = SigningKey::from_bytes(&[113; 32])
        .sign(&grant.grant.signing_bytes()?)
        .to_bytes()
        .to_vec();
    assert_eq!(
        dispatcher
            .dispatch(&fixture.source.writer, &grant, &binding, queued)
            .await?
            .state,
        LocalOutcomeState::Indeterminate
    );
    assert_eq!(
        ledger.owner.reservation(&reservation_id).await?.state,
        ReservationState::Held
    );
    ledger.assert_reserved().await?;
    assert_no_native(&fixture).await?;
    Ok(())
}

#[tokio::test]
async fn bad_grant_stays_locally_rejected_and_cannot_retry_or_refund_original_funding() -> TestResult
{
    let fixture = ControlledFixture::new(|_| {}).await;
    let ledger = Ledger::new(&fixture).await?;
    let funded = ledger.fund(&fixture).await?;
    let reservation_id = funded.registration().0.reservation_id.clone();
    let (dispatcher, queued, binding, grant) = prepared(&fixture, funded).await?;
    let mut tampered = grant.clone();
    tampered.grant.binding.payload_sha256[0] ^= 1;
    assert!(
        dispatcher
            .dispatch(&fixture.source.writer, &tampered, &binding, queued.clone())
            .await
            .is_err()
    );
    assert_eq!(
        fixture
            .source
            .writer
            .status("funded-controlled-effect")
            .await?,
        LocalOutcomeState::Rejected
    );
    assert!(matches!(
        dispatcher
            .dispatch(&fixture.source.writer, &grant, &binding, queued)
            .await,
        Err(ProductionWriterError::StaleReceipt)
    ));
    assert_eq!(
        ledger.owner.reservation(&reservation_id).await?.state,
        ReservationState::Held
    );
    ledger.assert_reserved().await?;
    assert_no_native(&fixture).await?;
    Ok(())
}
