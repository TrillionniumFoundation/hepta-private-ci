//! Bounded PN4 declarations at the real sealed source route, not native authority.

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_memory::FinalUseProductionOutboxTarget;
use codex_hepta_memory::ProductionDispatchFuture;
use codex_hepta_memory::ProductionDispatchRequest;
use codex_hepta_memory::ProductionOutboxTarget;
use codex_hepta_memory::ProductionTargetOutcome;
use codex_hepta_memory::ProductionTerminalObservation;
use codex_hepta_memory::ProductionTerminalObservationFuture;
use codex_hepta_memory::ProductionVerifiedDispatch;
use codex_hepta_memory::ProductionVerifiedDispatchFuture;
use codex_hepta_operations::OperationIntentV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Serialize;

pub const DESTINATION: &str = "infer-worker-host.controlled-aggregate.v1";
pub const TOPIC: &str = "hepta.controlled-aggregate.v1";
const GIB: u64 = 1024 * 1024 * 1024;

/// A child's aggregate observation cannot establish whole-unit settlement.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ResourceScope {
    ChildAggregate,
    WholeUnit,
}

#[derive(Clone, Copy, Debug, Serialize)]
pub struct ResourceBudget {
    pub memory_bytes: u64,
    pub cpu_percent: u64,
    pub tasks: u64,
}

impl ResourceBudget {
    fn fits(self, other: Self) -> bool {
        self.memory_bytes > 0
            && self.memory_bytes <= other.memory_bytes
            && self.cpu_percent > 0
            && self.cpu_percent <= other.cpu_percent
            && self.tasks > 0
            && self.tasks <= other.tasks
    }
}

/// Host-frozen declarations only. Identifiers, source digests and signatures do
/// not establish an AuthBus reservation, registered issuer or original OS owner.
#[derive(Clone, Debug)]
pub struct ControlledAggregateBinding {
    pub subject_id: StableId,
    pub operation_id: StableId,
    pub lease_id: StableId,
    pub reservation_id: StableId,
    pub settlement_issuer_id: StableId,
    pub settlement_key_epoch: u64,
    pub source_digest: Digest32,
    pub scope_digest: Digest32,
    pub policy_generation: Generation,
    pub resource_scope: ResourceScope,
    pub planned_budget: ResourceBudget,
    pub aggregate_budget: ResourceBudget,
    pub controller_budget: ResourceBudget,
    pub observer_deadline_ms: u64,
}

/// One immutable registration, never a growable registry or funding capability.
pub struct ControlledAggregateRegistration(ControlledAggregateBinding);

impl ControlledAggregateRegistration {
    pub fn new(binding: ControlledAggregateBinding) -> Result<Self, String> {
        let aggregate = binding.aggregate_budget;
        let controller = binding.controller_budget;
        let unit = ResourceBudget {
            memory_bytes: 16 * GIB,
            cpu_percent: 400,
            tasks: 256,
        };
        let aggregate_limit = ResourceBudget {
            memory_bytes: 8 * GIB,
            ..unit
        };
        if [
            &binding.subject_id,
            &binding.operation_id,
            &binding.lease_id,
            &binding.reservation_id,
            &binding.settlement_issuer_id,
        ]
        .iter()
        .any(|id| id.as_str().len() > 128)
            || binding.settlement_key_epoch == 0
            || binding.source_digest.is_zero()
            || binding.scope_digest.is_zero()
            || binding.resource_scope != ResourceScope::WholeUnit
            || binding.observer_deadline_ms == 0
            || binding.observer_deadline_ms > 8_000
            || !binding.planned_budget.fits(aggregate)
            || !aggregate.fits(aggregate_limit)
            || !controller.fits(unit)
            || !aggregate
                .memory_bytes
                .checked_add(controller.memory_bytes)
                .is_some_and(|total| total <= unit.memory_bytes)
            || aggregate.cpu_percent.checked_add(controller.cpu_percent) != Some(unit.cpu_percent)
            || aggregate.tasks.checked_add(controller.tasks) != Some(unit.tasks)
        {
            return Err(
                "invalid, mismatched-scope or over-budget controlled aggregate declaration"
                    .to_owned(),
            );
        }
        Ok(Self(binding))
    }

    pub fn payload_json(&self) -> Result<String, String> {
        Ok(serde_json::json!({
            "schema_version": 1,
            "subject_id": self.0.subject_id.as_str(),
            "operation_id": self.0.operation_id.as_str(),
            "lease_id": self.0.lease_id.as_str(),
            "reservation_id": self.0.reservation_id.as_str(),
            "settlement_issuer_id": self.0.settlement_issuer_id.as_str(),
            "settlement_key_epoch": self.0.settlement_key_epoch,
            "source_digest": self.0.source_digest.to_string(),
            "scope_digest": self.0.scope_digest.to_string(),
            "policy_generation": self.0.policy_generation.get(),
            "resource_scope": self.0.resource_scope,
            "planned_budget": self.0.planned_budget,
            "aggregate_budget": self.0.aggregate_budget,
            "controller_budget": self.0.controller_budget,
            "observer_deadline_ms": self.0.observer_deadline_ms,
        })
        .to_string())
    }

    pub fn operation(&self) -> Result<OperationIntentV1, String> {
        OperationIntentV1::new(
            self.0.operation_id.clone(),
            self.0.subject_id.clone(),
            StableId::new(DESTINATION).map_err(|error| error.to_string())?,
            Digest32::of_bytes(self.payload_json()?.as_bytes()),
            self.0.scope_digest,
            self.0.policy_generation,
            None,
        )
        .map_err(|error| error.to_string())
    }

    pub fn validate(&self, request: &ProductionDispatchRequest) -> Result<(), String> {
        let intent = self.operation()?;
        if request.schema_version != codex_hepta_memory::PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION
            || request.namespace != codex_hepta_memory::PRODUCTION_DURABLE_WRITER_NAMESPACE
            || request.lease_id != self.0.lease_id.as_str()
            || request.occurrence_key != self.0.operation_id.as_str()
            || request.idempotency_key != request.occurrence_key
            || request.topic != TOPIC
            || request.payload_json != self.payload_json()?
            || request.payload_sha256.as_str() != intent.payload_digest().to_string()
            || request.operation_subject_id != self.0.subject_id.as_str()
            || request.operation_destination_id != DESTINATION
            || request.operation_scope_sha256.as_str() != self.0.scope_digest.to_string()
            || request.operation_policy_generation != self.0.policy_generation.get()
            || request.expected_predecessor_sha256.is_some()
            || request.operation_semantic_sha256.as_str() != intent.semantic_digest().to_string()
        {
            return Err(
                "controlled aggregate differs from its complete registered intent".to_owned(),
            );
        }
        Ok(())
    }
}

/// Register on the existing final-use dispatcher/Agentd destination seam. Until
/// original AuthBus funding and native whole-unit ownership are connected, this
/// adapter refuses admission and reconciliation, including correctly signed IDs.
/// It never consumes a physical-entry claim or releases an existing reservation.
pub struct ControlledAggregateTarget {
    registration: ControlledAggregateRegistration,
    authority: FinalUseAuthority,
}

impl ControlledAggregateTarget {
    pub fn unavailable(
        registration: ControlledAggregateRegistration,
        authority: FinalUseAuthority,
    ) -> Self {
        Self {
            registration,
            authority,
        }
    }
}

impl ProductionOutboxTarget for ControlledAggregateTarget {
    fn dispatch<'a>(&'a self, _request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        Box::pin(async {
            retained("controlled aggregate requires original sealed FinalUse dispatch")
        })
    }
}

impl FinalUseProductionOutboxTarget for ControlledAggregateTarget {
    fn destination_id(&self) -> &str {
        DESTINATION
    }

    fn dispatch_verified<'a>(
        &'a self,
        dispatch: ProductionVerifiedDispatch,
    ) -> ProductionVerifiedDispatchFuture<'a> {
        Box::pin(async move {
            dispatch.verify_target_authority(&self.authority)?;
            if self.registration.validate(dispatch.request()).is_err() {
                return Ok(retained("controlled aggregate registration does not match"));
            }
            // No caller-provided ID, private cgroup fact, std::process::Child
            // exit or dropped claim can become a native owner/funding witness.
            Ok(retained(
                "original funded reservation, issuer and whole-unit owner are unavailable",
            ))
        })
    }

    fn observe_terminal<'a>(
        &'a self,
        request: &'a ProductionDispatchRequest,
    ) -> ProductionTerminalObservationFuture<'a> {
        Box::pin(async move {
            let reason = if self.registration.validate(request).is_err() {
                "controlled aggregate registration does not match"
            } else {
                "original whole-unit settlement is unavailable; reservation retained"
            };
            ProductionTerminalObservation::Indeterminate {
                reason: reason.to_owned(),
            }
        })
    }
}

fn retained(reason: &str) -> ProductionTargetOutcome {
    // Even authorization/dispatch accounting may have spent CPU. This is not
    // AuthBus Rejected evidence and must not cause a full zero-cost release.
    ProductionTargetOutcome::Indeterminate {
        reason: reason.to_owned(),
    }
}
