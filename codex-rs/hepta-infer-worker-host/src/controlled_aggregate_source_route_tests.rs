use super::*;
use crate::controlled_aggregate::ControlledAggregateBinding;
use crate::controlled_aggregate::ControlledAggregateRegistration;
use crate::controlled_aggregate::ControlledAggregateTarget;
use crate::controlled_aggregate::DESTINATION as CONTROLLED_DESTINATION;
use crate::controlled_aggregate::ResourceBudget;
use crate::controlled_aggregate::ResourceScope;
use crate::controlled_aggregate::TOPIC;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

struct ControlledFixture {
    source: SourceFixture,
    target: Arc<ControlledAggregateTarget>,
    queued: ProductionQueuedReceipt,
    binding: FinalUseBinding,
    request: ProductionDispatchRequest,
    registration: ControlledAggregateRegistration,
    declared: ControlledAggregateBinding,
}

impl ControlledFixture {
    async fn new(change_target: impl FnOnce(&mut ControlledAggregateBinding)) -> Self {
        Self::with_controller_memory(8 * 1024 * 1024 * 1024, change_target).await
    }

    async fn with_controller_memory(
        controller_memory_bytes: u64,
        change_target: impl FnOnce(&mut ControlledAggregateBinding),
    ) -> Self {
        let source = SourceFixture::new(WorkerBehavior::ExitZero).await;
        let gib = 1024 * 1024 * 1024;
        let mut binding = ControlledAggregateBinding {
            subject_id: StableId::new(&source.binding.subject_id).expect("subject"),
            operation_id: StableId::new("controlled-source-effect").expect("operation"),
            lease_id: StableId::new(source.writer.lease_id()).expect("original lease"),
            reservation_id: StableId::new("declared-reservation-is-not-funding")
                .expect("reservation"),
            settlement_issuer_id: StableId::new("declared-issuer-is-not-authority")
                .expect("issuer"),
            settlement_key_epoch: 1,
            source_digest: Digest32::of_bytes(b"fixed-native-source"),
            scope_digest: Digest32::of_bytes(b"whole-unit-funding-scope"),
            policy_generation: Generation::new(1).expect("generation"),
            resource_scope: ResourceScope::WholeUnit,
            planned_budget: ResourceBudget {
                memory_bytes: 8 * gib,
                cpu_percent: 300,
                tasks: 128,
            },
            aggregate_budget: ResourceBudget {
                memory_bytes: 8 * gib,
                cpu_percent: 300,
                tasks: 128,
            },
            controller_budget: ResourceBudget {
                memory_bytes: controller_memory_bytes,
                cpu_percent: 100,
                tasks: 128,
            },
            observer_deadline_ms: 8_000,
        };
        let registration =
            ControlledAggregateRegistration::new(binding.clone()).expect("bounded declaration");
        let intent = registration.operation().expect("canonical intent");
        let queued = source
            .writer
            .prepare_operation(
                intent.clone(),
                TOPIC,
                &registration.payload_json().expect("payload"),
            )
            .await
            .expect("real signed-source journal");
        let final_use = source
            .writer
            .final_use_binding(&queued, CONTROLLED_DESTINATION)
            .await
            .expect("exact final-use binding");
        let request = ProductionDispatchRequest {
            schema_version: queued.schema_version,
            namespace: queued.namespace.clone(),
            lease_id: queued.lease_id.clone(),
            occurrence_key: queued.occurrence_key.clone(),
            topic: queued.topic.clone(),
            payload_json: queued.payload_json.clone(),
            payload_sha256: queued.payload_sha256.clone(),
            idempotency_key: queued.occurrence_key.clone(),
            operation_scope_sha256: Sha256Digest::parse(intent.scope_digest().to_string())
                .expect("scope digest"),
            operation_subject_id: intent.subject_id().as_str().to_owned(),
            operation_destination_id: CONTROLLED_DESTINATION.to_owned(),
            operation_semantic_sha256: Sha256Digest::parse(intent.semantic_digest().to_string())
                .expect("semantic digest"),
            operation_policy_generation: intent.policy_generation().get(),
            expected_predecessor_sha256: None,
            operation_digest: Sha256Digest::parse(
                Digest32::from_array(final_use.request_sha256).to_string(),
            )
            .expect("request digest"),
        };
        change_target(&mut binding);
        let target = Arc::new(ControlledAggregateTarget::unavailable(
            ControlledAggregateRegistration::new(binding.clone())
                .expect("fixed target declaration"),
            source.target.authority.clone(),
        ));
        Self {
            source,
            target,
            queued,
            binding: final_use,
            request,
            registration: ControlledAggregateRegistration::new(binding.clone())
                .expect("target declaration"),
            declared: binding,
        }
    }

    fn signed(&self) -> SignedFinalUseGrant {
        let mut signed = self.source.signed_grant("controlled-original-grant", 81);
        signed.grant.binding = self.binding.clone();
        signed.signature = SigningKey::from_bytes(&[113; 32])
            .sign(&signed.grant.signing_bytes().expect("exact signing input"))
            .to_bytes()
            .to_vec();
        signed
    }

    async fn assert_retained(&self) {
        let dispatcher = ProductionFinalUseOutboxDispatcher::attach(
            self.source.target.authority.clone(),
            self.target.clone(),
        );
        let signed = self.signed();
        let result = dispatcher
            .dispatch(
                &self.source.writer,
                &signed,
                &self.binding,
                self.queued.clone(),
            )
            .await
            .expect("actual verified dispatch refusal");
        assert_eq!(result.state, LocalOutcomeState::Indeterminate);
        assert_eq!(result.request, self.request);
        assert!(
            dispatcher
                .dispatch(
                    &self.source.writer,
                    &signed,
                    &self.binding,
                    self.queued.clone()
                )
                .await
                .is_err()
        );
        dispatcher
            .reconcile(&self.source.writer, 8)
            .await
            .expect("observer-only reconciliation");
        assert_eq!(
            self.source
                .writer
                .status("controlled-source-effect")
                .await
                .expect("retained source"),
            LocalOutcomeState::Indeterminate
        );
        let entries: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM ordinary_cpu_entries")
            .fetch_one(&self.source.pool)
            .await
            .expect("no native admission");
        assert_eq!(entries, 0);
        assert!(!self.source.temp.path().join("child-marker").exists());
    }
}

#[tokio::test]
async fn controlled_signed_memory_headroom_remains_indeterminate_without_funding() {
    let fixture = ControlledFixture::with_controller_memory(128 * 1024 * 1024, |_| {}).await;
    fixture
        .registration
        .validate(&fixture.request)
        .expect("exact signed-source headroom declaration");
    let payload: serde_json::Value =
        serde_json::from_str(&fixture.request.payload_json).expect("signed payload");
    assert_eq!(
        payload["controller_budget"],
        serde_json::json!({
            "memory_bytes": 128 * 1024 * 1024,
            "cpu_percent": 100,
            "tasks": 128,
        })
    );
    assert!(
        fixture.declared.aggregate_budget.memory_bytes
            + fixture.declared.controller_budget.memory_bytes
            < 16 * 1024 * 1024 * 1024
    );
    fixture.assert_retained().await;
}

#[tokio::test]
async fn controlled_signed_ids_never_become_funding_native_entry_or_terminal_release() {
    let fixture = ControlledFixture::new(|_| {}).await;
    assert_eq!(
        fixture.target.dispatch(fixture.request.clone()).await,
        ProductionTargetOutcome::Indeterminate {
            reason: "controlled aggregate requires original sealed FinalUse dispatch".to_owned()
        }
    );
    fixture.assert_retained().await;
    let fixture = ControlledFixture::new(|_| {}).await;
    let mut unsigned = fixture.signed();
    unsigned.signature.clear();
    let dispatcher = ProductionFinalUseOutboxDispatcher::attach(
        fixture.source.target.authority.clone(),
        fixture.target.clone(),
    );
    assert!(
        dispatcher
            .dispatch(
                &fixture.source.writer,
                &unsigned,
                &fixture.binding,
                fixture.queued.clone()
            )
            .await
            .is_err()
    );
    assert!(!fixture.source.temp.path().join("child-marker").exists());
}

#[tokio::test]
async fn controlled_cross_owner_is_rejected_before_any_entry() {
    let fixture = ControlledFixture::new(|_| {}).await;
    let foreign = authority(
        &fixture.source.temp,
        "controlled-foreign-owner",
        fixture.source.clock.clone(),
    );
    let dispatcher = ProductionFinalUseOutboxDispatcher::attach(foreign, fixture.target.clone());
    assert!(matches!(
        dispatcher
            .dispatch(
                &fixture.source.writer,
                &fixture.signed(),
                &fixture.binding,
                fixture.queued.clone()
            )
            .await,
        Err(ProductionWriterError::FinalUse(
            FinalUseError::BindingMismatch
        ))
    ));
    assert!(!fixture.source.temp.path().join("child-marker").exists());
}

#[tokio::test]
async fn controlled_original_operation_lease_reservation_and_issuer_cannot_be_rebound() {
    for field in [
        "subject",
        "operation",
        "lease",
        "reservation",
        "issuer",
        "source",
        "scope",
        "policy",
        "epoch",
        "budget",
        "plan",
        "deadline",
    ] {
        let fixture = ControlledFixture::new(|binding| match field {
            "subject" => binding.subject_id = StableId::new("other-subject").expect("id"),
            "operation" => binding.operation_id = StableId::new("other-operation").expect("id"),
            "lease" => binding.lease_id = StableId::new("other-lease").expect("id"),
            "reservation" => {
                binding.reservation_id = StableId::new("other-reservation").expect("id")
            }
            "issuer" => binding.settlement_issuer_id = StableId::new("other-issuer").expect("id"),
            "source" => binding.source_digest = Digest32::of_bytes(b"different source"),
            "scope" => binding.scope_digest = Digest32::of_bytes(b"different scope"),
            "policy" => binding.policy_generation = Generation::new(2).expect("generation"),
            "epoch" => binding.settlement_key_epoch = 2,
            "budget" => {
                binding.aggregate_budget.cpu_percent += 1;
                binding.controller_budget.cpu_percent -= 1;
            }
            "plan" => binding.planned_budget.cpu_percent -= 1,
            "deadline" => binding.observer_deadline_ms -= 1,
            _ => unreachable!(),
        })
        .await;
        assert!(fixture.registration.validate(&fixture.request).is_err());
        fixture.assert_retained().await;
    }
}

#[tokio::test]
async fn controlled_budget_and_child_scope_refuse_before_registration_without_changing_original_caps()
 {
    let fixture = ControlledFixture::new(|_| {}).await;
    let original = fixture.declared;
    for case in [
        "child",
        "default-model-16",
        "aggregate-over8",
        "unit-over16",
        "overflow",
        "zero-controller",
        "late",
    ] {
        let mut binding = original.clone();
        match case {
            "child" => binding.resource_scope = ResourceScope::ChildAggregate,
            "default-model-16" => binding.planned_budget.memory_bytes = 16 * 1024 * 1024 * 1024,
            "aggregate-over8" => binding.aggregate_budget.memory_bytes += 1,
            "unit-over16" => binding.controller_budget.memory_bytes += 1,
            "overflow" => binding.controller_budget.cpu_percent = u64::MAX,
            "zero-controller" => binding.controller_budget.tasks = 0,
            "late" => binding.observer_deadline_ms = 8_001,
            _ => unreachable!(),
        }
        assert!(
            ControlledAggregateRegistration::new(binding).is_err(),
            "{case}"
        );
    }
}
