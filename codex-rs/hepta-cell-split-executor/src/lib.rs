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

use codex_hepta_intelligence_eval::SelfEvolutionSelectionReceiptV1;
use codex_hepta_intelligence_eval::VerifiedSelfEvolutionSelectionV1;
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
use codex_hepta_supervisor::CellSplitOwnerErrorV1;
use codex_hepta_supervisor::CellSplitOwnerV1;
use codex_hepta_supervisor::DurableWriterHandoffJournalV1;
use codex_hepta_supervisor::WriterHandoffCheckpointV1;
use codex_hepta_supervisor::WriterHandoffPhaseV1;
use codex_hepta_supervisor::WriterHandoffPlanV1;
use codex_hepta_types::AuthorityPosture;
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
    /// Candidate identity selected by the independent, signed NDU Selector.
    /// This is distinct from the CNS topology proposal/candidate IDs.
    pub selected_candidate_id: StableId,
    pub selection_id: StableId,
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
            && !self.split.selection_digest.is_zero()
            && !self.split.predecessor_route_digest.is_zero()
            && !self.split.successor_route_digest.is_zero()
            && self.split.predecessor_route_digest != self.split.successor_route_digest
            && !self.cns_handoff_digest.is_zero()
            && !self.cns_final_use_request_digest.is_zero()
            && plan.validate().is_ok()
    }

    /// Only the independently verified opaque selection token can pass this
    /// check at the product bridge construction boundary. For testable policy
    /// purity the private helper consumes its signed receipt projection too.
    fn validate_selection(
        &self,
        plan: &WriterHandoffPlanV1,
        selected: &VerifiedSelfEvolutionSelectionV1,
    ) -> bool {
        self.validate_selection_receipt(
            plan,
            selected.receipt(),
            selected.selection_digest(),
            selected.selector_evidence_digest(),
        )
    }

    fn validate_selection_receipt(
        &self,
        plan: &WriterHandoffPlanV1,
        receipt: &SelfEvolutionSelectionReceiptV1,
        selection_digest: Digest32,
        selector_evidence_digest: Digest32,
    ) -> bool {
        self.validate(plan)
            && !selector_evidence_digest.is_zero()
            && receipt.authority == AuthorityPosture::DENY_ALL
            && receipt.selection_id == self.selection_id
            && receipt.candidate_id == self.selected_candidate_id
            && receipt.predecessor_generation == plan.old_generation
            && receipt.candidate_generation == plan.new_generation
            && receipt.candidate_artifact_digest == self.split.selected_artifact_digest
            && selection_digest == self.split.selection_digest
            && !receipt.objective_digest.is_zero()
            && !receipt.no_change_baseline_digest.is_zero()
            && !receipt.dataset_digest.is_zero()
            && !receipt.ledger_head_digest.is_zero()
            && !receipt.evaluation_evidence_digest.is_zero()
            && !receipt.evaluation_authentication_digest.is_zero()
            && !receipt.frozen_plan_digest.is_zero()
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
    /// Opaque independent selection, retained throughout the operation.
    selection: &'a VerifiedSelfEvolutionSelectionV1,
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
        selection: &'a VerifiedSelfEvolutionSelectionV1,
        other: O,
        current_time: u64,
    ) -> Result<Self, ProductSplitNativeErrorV1<O::Error>> {
        if current_time == 0
            || !binding.validate_selection(&plan, selection)
        {
            return Err(ProductSplitNativeErrorV1::PlanOrBindingMismatch);
        }
        Ok(Self {
            plan,
            binding,
            artifact,
            runtime,
            selection,
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
        if !self.binding.validate_selection(&self.plan, self.selection)
            || !self.binding.validate_cutover(&self.plan, &applied)
        {
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

    /// Advance one already independently admitted split phase using the
    /// Supervisor's exclusive fsync-backed journal and these actual native
    /// readback owners. No loop, selection, retry after unknown effects or
    /// hidden deployment action occurs here. Missing product authority must
    /// be enforced by each native effect owner and before constructing this
    /// bridge.
    pub fn advance_receipt_gated_phase(
        &mut self,
        journal: &mut DurableWriterHandoffJournalV1,
    ) -> Result<
        WriterHandoffCheckpointV1,
        CellSplitOwnerErrorV1<ProductSplitNativeErrorV1<O::Error>>,
    > {
        if !self.binding.validate_selection(&self.plan, self.selection) {
            return Err(CellSplitOwnerErrorV1::Native(
                ProductSplitNativeErrorV1::PlanOrBindingMismatch,
            ));
        }
        let binding = self.binding.split.clone();
        let mut coordinator = CellSplitOwnerV1::new(journal, self, binding)?;
        coordinator.advance_once()
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
        if plan != &self.plan
            || !self.binding.validate_selection(&self.plan, self.selection)
        {
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
        if plan != &self.plan
            || !self.binding.validate_selection(&self.plan, self.selection)
        {
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
                selection_digest: d(b"selection"),
                predecessor_route_digest: d(b"old-route"),
                successor_route_digest: d(b"new-route"),
            },
            artifact_id: id("artifact:1"),
            selected_candidate_id: id("cell-candidate:1"),
            selection_id: id("selection:1"),
            cns_proposal_id: id("topology:1"),
            cns_candidate_id: id("candidate:1"),
            cns_handoff_digest: d(b"runtime-handoff"),
            cns_final_use_request_digest: d(b"final-use"),
        };
        assert!(binding.validate(&plan));
        let mut selector_receipt = SelfEvolutionSelectionReceiptV1 {
            selection_id: id("selection:1"),
            objective_digest: d(b"objective"),
            predecessor_id: id("cell:parent"),
            predecessor_generation: plan.old_generation,
            predecessor_artifact_digest: d(b"predecessor-model"),
            candidate_id: id("cell-candidate:1"),
            candidate_generation: plan.new_generation,
            candidate_artifact_digest: d(b"artifact"),
            no_change_baseline_id: id("no-change:1"),
            no_change_baseline_digest: d(b"frozen-no-change"),
            dataset_digest: d(b"dataset"),
            ledger_head_digest: d(b"ledger-head"),
            evaluation_evidence_digest: d(b"independent-evaluation"),
            evaluation_authentication_digest: d(b"evaluation-signature"),
            evaluation_trust_digest: d(b"evaluation-trust"),
            frozen_plan_digest: d(b"frozen-plan"),
            minimum_dataset_records: 8,
            minimum_future_window_micros: 1_000,
            authority: AuthorityPosture::DENY_ALL,
        };
        assert!(binding.validate_selection_receipt(
            &plan, &selector_receipt, d(b"selection"), d(b"selector-signature"),
        ));
        selector_receipt.no_change_baseline_digest = Digest32::ZERO;
        assert!(!binding.validate_selection_receipt(
            &plan, &selector_receipt, d(b"selection"), d(b"selector-signature"),
        ));
        selector_receipt.no_change_baseline_digest = d(b"frozen-no-change");
        selector_receipt.candidate_artifact_digest = d(b"other-artifact");
        assert!(!binding.validate_selection_receipt(
            &plan, &selector_receipt, d(b"selection"), d(b"selector-signature"),
        ));
        selector_receipt.candidate_artifact_digest = d(b"artifact");
        assert!(!binding.validate_selection_receipt(
            &plan, &selector_receipt, d(b"unrelated-selection"), d(b"selector-signature"),
        ));
        assert!(!binding.validate_selection_receipt(
            &plan, &selector_receipt, d(b"selection"), Digest32::ZERO,
        ));
        binding.cns_final_use_request_digest = Digest32::ZERO;
        assert!(!binding.validate(&plan));
        binding.cns_final_use_request_digest = d(b"final-use");
        binding.split.operation_id = id("another-split");
        assert!(!binding.validate(&plan));
    }
}
