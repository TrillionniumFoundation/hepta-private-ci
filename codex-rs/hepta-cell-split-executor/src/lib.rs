//! Readback-only native composition for the Cell Split Supervisor owner.
//!
//! This crate connects *actual* Artifact Owner and live CNS readback APIs to
//! the existing Supervisor saga without moving their writer authority into
//! Agentd or a generic executor. It deliberately cannot create an Artifact
//! publication or spend a Final-use grant to mutate CNS routes.
//!
//! Product callers must hold the original service and runtime owner handles;
//! no receipt is generated from a proposal digest or an in-memory fixture.
//! Migration, child bootstrapping, draining, writer fences, durable CNS route
//! publication, crash recovery and independent selection are NOT implemented
//! by this adapter. Until an independently fenced native owner implements
//! those stages and a persistent CNS route receipt exists, physical splitting
//! remains forbidden.

#![forbid(unsafe_code)]

use codex_hepta_learning_artifacts::ArtifactOwnerHostError;
use codex_hepta_learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_learning_artifacts::LearningArtifactOwnerServiceError;
use codex_hepta_runtime::HeptaRuntime;
use codex_hepta_runtime::RuntimeTopologyApplyReceiptV1;
use codex_hepta_supervisor::CellSplitBindingV1;
use codex_hepta_supervisor::CellSplitLookupV1;
use codex_hepta_supervisor::CellSplitNativeEvidenceV1;
use codex_hepta_supervisor::CellSplitNativeOwnerV1;
use codex_hepta_supervisor::CellSplitObservedReceiptV1;
use codex_hepta_supervisor::WriterHandoffPhaseV1;
use codex_hepta_supervisor::WriterHandoffPlanV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

/// Pre-registered mapping between two different native handoff protocols.
/// It MUST come from independent selection/admission, not from the generated
/// candidate. The supervisor and CNS handoff digests are deliberately separate:
/// their canonical encodings have different types and are not interchangeable.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductSplitBindingV1 {
    pub split: CellSplitBindingV1,
    pub artifact_id: StableId,
    pub cns_proposal_id: StableId,
    pub cns_candidate_id: StableId,
    pub cns_handoff_digest: Digest32,
    pub cns_final_use_request_digest: Digest32,
}

impl ProductSplitBindingV1 {
    /// Static source binding only. Signatures/selection authorization are
    /// checked by the caller's immutable admission and native owners.
    pub fn validate(&self, plan: &WriterHandoffPlanV1) -> bool {
        self.split.operation_id == plan.operation_id
            && !self.split.selected_artifact_digest.is_zero()
            && !self.split.predecessor_route_digest.is_zero()
            && !self.split.successor_route_digest.is_zero()
            && self.split.predecessor_route_digest != self.split.successor_route_digest
            && !self.cns_handoff_digest.is_zero()
            && !self.cns_final_use_request_digest.is_zero()
            && plan.validate().is_ok()
    }

    fn validate_cutover(
        &self,
        plan: &WriterHandoffPlanV1,
        native: &RuntimeTopologyApplyReceiptV1,
    ) -> bool {
        self.validate(plan)
            && native.proposal_id == self.cns_proposal_id
            && native.candidate_id == self.cns_candidate_id
            && native.predecessor_generation == plan.old_generation
            && native.successor_generation == plan.new_generation
            && native.predecessor_hierarchy_digest == self.split.predecessor_route_digest
            && native.successor_hierarchy_digest == self.split.successor_route_digest
            && native.handoff_plan_digest == self.cns_handoff_digest
            && native.final_use_request_digest == self.cns_final_use_request_digest
    }
}

/// The other seven stages require separately authenticated, persistent domain
/// owners. No blanket dummy successful implementation is provided.
pub trait ExternalCellSplitNativeOwnerV1 {
    type Error;
    fn lookup_external(
        &mut self,
        plan: &WriterHandoffPlanV1,
        phase: WriterHandoffPhaseV1,
    ) -> Result<CellSplitLookupV1, Self::Error>;

    fn execute_external(
        &mut self,
        plan: &WriterHandoffPlanV1,
        phase: WriterHandoffPhaseV1,
    ) -> Result<(), Self::Error>;
}

#[derive(Debug)]
pub enum ProductSplitNativeErrorV1<E> {
    PlanOrBindingMismatch,
    InvalidNativeReadback,
    Artifact(LearningArtifactOwnerServiceError),
    RuntimeReadbackUnavailable,
    External(E),
    /// This bridge never publishes CAS or routes. Such a request must be
    /// routed to a separately authorized, idempotent native operation owner.
    NativeEffectNotAuthorizedByBridge,
}

impl<E: std::fmt::Debug> std::fmt::Display for ProductSplitNativeErrorV1<E> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{self:?}")
    }
}
impl<E: std::fmt::Debug> std::error::Error for ProductSplitNativeErrorV1<E> {}

/// One owner-bound bridge for an exact immutable split plan. The Supervisor
/// journal owns local serialization; the underlying stores and CNS still
/// enforce their own durable fences. This object is not a production service
/// entry point or background task.
pub struct ProductSplitNativeReadbackV1<'a, O: ExternalCellSplitNativeOwnerV1> {
    plan: WriterHandoffPlanV1,
    binding: ProductSplitBindingV1,
    artifact: &'a LearningArtifactOwnerService,
    runtime: &'a HeptaRuntime,
    other: O,
    current_time: u64,
    cutover: Option<RuntimeTopologyApplyReceiptV1>,
}

impl<'a, O: ExternalCellSplitNativeOwnerV1> ProductSplitNativeReadbackV1<'a, O> {
    pub fn new(
        plan: WriterHandoffPlanV1,
        binding: ProductSplitBindingV1,
        artifact: &'a LearningArtifactOwnerService,
        runtime: &'a HeptaRuntime,
        other: O,
        current_time: u64,
    ) -> Result<Self, ProductSplitNativeErrorV1<O::Error>> {
        if current_time == 0 || !binding.validate(&plan) {
            return Err(ProductSplitNativeErrorV1::PlanOrBindingMismatch);
        }
        Ok(Self {
            plan,
            binding,
            artifact,
            runtime,
            other,
            current_time,
            cutover: None,
        })
    }

    /// Update expiry-sensitive Artifact CURRENT verification time. Rollback of
    /// this clock is forbidden; the production host must supply trusted time.
    pub fn advance_current_time(
        &mut self,
        now: u64,
    ) -> Result<(), ProductSplitNativeErrorV1<O::Error>> {
        if now < self.current_time {
            return Err(ProductSplitNativeErrorV1::PlanOrBindingMismatch);
        }
        self.current_time = now;
        Ok(())
    }

    /// Attach a real Final-use-guarded CNS apply receipt, after re-observing
    /// the live route inside the actual runtime owner. An arbitrary caller
    /// cannot fabricate a successful receipt with only a matching digest.
    ///
    /// The receipt is **volatile**. On restart it must be reconciled against
    /// an independently durable CNS owner before resuming this split.
    pub fn attach_live_cutover(
        &mut self,
        applied: RuntimeTopologyApplyReceiptV1,
    ) -> Result<(), ProductSplitNativeErrorV1<O::Error>> {
        if !self.binding.validate_cutover(&self.plan, &applied) {
            return Err(ProductSplitNativeErrorV1::PlanOrBindingMismatch);
        }
        self.runtime
            .observe_governed_topology_cutover(&applied)
            .map_err(|_| ProductSplitNativeErrorV1::RuntimeReadbackUnavailable)?;
        if self.cutover.is_some() {
            return Err(ProductSplitNativeErrorV1::PlanOrBindingMismatch);
        }
        self.cutover = Some(applied);
        Ok(())
    }

    /// The two native receipt paths implemented here *always* return either
    /// an actual owner readback or fail closed. No absence result is inferred
    /// from a missing file, an unacknowledged publication or lost volatile CNS
    /// state.
    fn lookup_owned(
        &self,
        phase: WriterHandoffPhaseV1,
    ) -> Result<CellSplitLookupV1, ProductSplitNativeErrorV1<O::Error>> {
        let evidence = match phase {
            WriterHandoffPhaseV1::Snapshotted => {
                let response = self.artifact.observe_cell_split_artifact_cas_v1(
                    &self.plan.operation_id,
                    &self.binding.artifact_id,
                    self.binding.split.selected_artifact_digest,
                    self.current_time,
                );
                let observed = match response {
                    Ok(receipt) => receipt,
                    Err(LearningArtifactOwnerServiceError::Host(
                        ArtifactOwnerHostError::Indeterminate,
                    )) => return Ok(CellSplitLookupV1::Indeterminate),
                    Err(error) => return Err(ProductSplitNativeErrorV1::Artifact(error)),
                };
                if observed.operation_id != self.plan.operation_id
                    || observed.artifact_id != self.binding.artifact_id
                    || observed.payload_digest != self.binding.split.selected_artifact_digest
                {
                    return Err(ProductSplitNativeErrorV1::InvalidNativeReadback);
                }
                CellSplitNativeEvidenceV1::ArtifactCasCommitted {
                    native_ack: observed.native_ack_digest,
                    payload_digest: observed.payload_digest,
                    readback_digest: observed.readback_digest,
                    registry_head_digest: observed.registry_head_digest,
                }
            }
            WriterHandoffPhaseV1::RoutePublished => {
                let Some(applied) = &self.cutover else {
                    return Ok(CellSplitLookupV1::Indeterminate);
                };
                if !self.binding.validate_cutover(&self.plan, applied) {
                    return Err(ProductSplitNativeErrorV1::InvalidNativeReadback);
                }
                let observed = self
                    .runtime
                    .observe_governed_topology_cutover(applied)
                    .map_err(|_| ProductSplitNativeErrorV1::RuntimeReadbackUnavailable)?;
                if observed.handoff_plan_digest != self.binding.cns_handoff_digest
                    || observed.final_use_request_digest
                        != self.binding.cns_final_use_request_digest
                {
                    return Err(ProductSplitNativeErrorV1::InvalidNativeReadback);
                }
                CellSplitNativeEvidenceV1::CnsRouteCutover {
                    native_ack: observed.native_ack_digest,
                    predecessor_digest: observed.predecessor_hierarchy_digest,
                    successor_digest: observed.successor_hierarchy_digest,
                    observed_generation: observed.observed_generation,
                }
            }
            _ => return Err(ProductSplitNativeErrorV1::PlanOrBindingMismatch),
        };
        CellSplitObservedReceiptV1::bind_observed_native(
            &self.plan,
            &self.binding.split,
            evidence,
        )
        .map(CellSplitLookupV1::Observed)
        .ok_or(ProductSplitNativeErrorV1::InvalidNativeReadback)
    }
}

impl<O: ExternalCellSplitNativeOwnerV1> CellSplitNativeOwnerV1
    for ProductSplitNativeReadbackV1<'_, O>
{
    type Error = ProductSplitNativeErrorV1<O::Error>;

    fn lookup(
        &mut self,
        plan: &WriterHandoffPlanV1,
        phase: WriterHandoffPhaseV1,
    ) -> Result<CellSplitLookupV1, Self::Error> {
        if plan != &self.plan {
            return Err(ProductSplitNativeErrorV1::PlanOrBindingMismatch);
        }
        match phase {
            WriterHandoffPhaseV1::Snapshotted | WriterHandoffPhaseV1::RoutePublished => {
                self.lookup_owned(phase)
            }
            WriterHandoffPhaseV1::Prepared | WriterHandoffPhaseV1::Quarantined => {
                Err(ProductSplitNativeErrorV1::PlanOrBindingMismatch)
            }
            _ => self
                .other
                .lookup_external(plan, phase)
                .map_err(ProductSplitNativeErrorV1::External),
        }
    }

    fn execute(
        &mut self,
        plan: &WriterHandoffPlanV1,
        phase: WriterHandoffPhaseV1,
    ) -> Result<(), Self::Error> {
        if plan != &self.plan {
            return Err(ProductSplitNativeErrorV1::PlanOrBindingMismatch);
        }
        match phase {
            // A native Artifact publication and Final-use CNS mutation
            // MUST execute through their original separately authorized
            // owners, not through the Supervisor proposal owner.
            WriterHandoffPhaseV1::Snapshotted | WriterHandoffPhaseV1::RoutePublished => {
                Err(ProductSplitNativeErrorV1::NativeEffectNotAuthorizedByBridge)
            }
            WriterHandoffPhaseV1::Prepared | WriterHandoffPhaseV1::Quarantined => {
                Err(ProductSplitNativeErrorV1::PlanOrBindingMismatch)
            }
            _ => self
                .other
                .execute_external(plan, phase)
                .map_err(ProductSplitNativeErrorV1::External),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_types::Generation;

    fn id(s: &str) -> StableId {
        StableId::new(s).unwrap_or_else(|_| unreachable!("constant id"))
    }
    fn d(s: &[u8]) -> Digest32 {
        Digest32::of_bytes(s)
    }

    #[test]
    fn product_binding_requires_independent_cns_handoff_and_final_use() {
        let plan = WriterHandoffPlanV1 {
            operation_id: id("split:1"),
            domain_id: id("scope:1"),
            source_writer: id("cell:parent"),
            target_writer: id("cell:child"),
            old_generation: Generation::new(1)
                .unwrap_or_else(|_| unreachable!("constant")),
            new_generation: Generation::new(2)
                .unwrap_or_else(|_| unreachable!("constant")),
            authority_epoch: 1,
            migration_plan_digest: d(b"migration"),
            schema_digest: d(b"schema"),
            rollback_predecessor_digest: d(b"rollback"),
        };
        let mut binding = ProductSplitBindingV1 {
            split: CellSplitBindingV1 {
                operation_id: plan.operation_id.clone(),
                selected_artifact_digest: d(b"artifact"),
                predecessor_route_digest: d(b"old-route"),
                successor_route_digest: d(b"new-route"),
            },
            artifact_id: id("artifact:1"),
            cns_proposal_id: id("topology:1"),
            cns_candidate_id: id("candidate:1"),
            cns_handoff_digest: d(b"runtime-handoff"),
            cns_final_use_request_digest: d(b"final-use"),
        };
        assert!(binding.validate(&plan));
        binding.cns_final_use_request_digest = Digest32::ZERO;
        assert!(!binding.validate(&plan));
        binding.cns_final_use_request_digest = d(b"final-use");
        binding.split.operation_id = id("another-split");
        assert!(!binding.validate(&plan));
    }
}
