//! Authority-free DecisionCell split contract.
//!
//! This is a semantic plan, not a topology writer or a state/artifact owner.
//! It makes the information required for a cell split inspectable without
//! changing the older module-topology wire contract.  Large tensors, state
//! transforms and evaluation reports remain owned by their existing modules;
//! this record carries their typed policies and immutable digests.

use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;

use crate::Digest32;
use crate::Generation;
use crate::RuntimeTopologyCandidateV1;
use crate::RuntimeTopologyDeltaV1;
use crate::RuntimeTopologyOperationV1;
use crate::StableId;

pub const MAX_CELL_SPLIT_CHILDREN_V1: usize = 64;
const MAX_CELL_SPLIT_RESOURCE_UNITS_V1: u64 = 1_u64 << 60;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub enum CellBundleModeV1 {
    SharedImmutable,
    CloneMutable,
    Reset,
    Distill,
}

impl CellBundleModeV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::SharedImmutable => 0,
            Self::CloneMutable => 1,
            Self::Reset => 2,
            Self::Distill => 3,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub enum CellStateTransformKindV1 {
    Copy,
    Partition,
    Reset,
    Custom,
}

impl CellStateTransformKindV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Copy => 0,
            Self::Partition => 1,
            Self::Reset => 2,
            Self::Custom => 3,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub enum CellCachePolicyV1 {
    Drop,
    Partition,
    Revalidate,
}

impl CellCachePolicyV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Drop => 0,
            Self::Partition => 1,
            Self::Revalidate => 2,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub enum CellInFlightPolicyV1 {
    Drain,
    Reassign,
    Cancel,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub enum CellRouteModeV1 {
    Exclusive,
}

impl CellRouteModeV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Exclusive => 0,
        }
    }
}

impl CellInFlightPolicyV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Drain => 0,
            Self::Reassign => 1,
            Self::Cancel => 2,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub enum CellParentDispositionV1 {
    Retire,
    Quarantine,
    KeepShadow,
}

impl CellParentDispositionV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Retire => 0,
            Self::Quarantine => 1,
            Self::KeepShadow => 2,
        }
    }
}

/// A state transformation applies to one owned state domain (recurrent state,
/// eligibility traces or optimizer state).  `mapping_digest` is required for
/// partition/custom transforms and identifies the executable mapping owned by
/// `neuron.runtime` or its explicitly admitted migration owner.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CellStateTransformV1 {
    pub kind: CellStateTransformKindV1,
    pub source_schema_digest: Digest32,
    pub target_schema_digest: Digest32,
    pub mapping_digest: Digest32,
}

impl CellStateTransformV1 {
    fn validate(&self, label: &'static str) -> Result<(), CellSplitContractErrorV1> {
        require_digest(self.source_schema_digest, label)?;
        require_digest(self.target_schema_digest, label)?;
        match self.kind {
            CellStateTransformKindV1::Partition | CellStateTransformKindV1::Custom => {
                require_digest(self.mapping_digest, label)?;
            }
            CellStateTransformKindV1::Copy | CellStateTransformKindV1::Reset => {
                if !self.mapping_digest.is_zero() {
                    return Err(CellSplitContractErrorV1::UnexpectedTransformDigest(label));
                }
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellStateSplitPlanV1 {
    pub recurrent: CellStateTransformV1,
    pub eligibility: CellStateTransformV1,
    pub optimizer: CellStateTransformV1,
    pub cache_policy: CellCachePolicyV1,
    pub in_flight_policy: CellInFlightPolicyV1,
    pub state_evidence_digest: Digest32,
}

impl CellStateSplitPlanV1 {
    fn validate(&self) -> Result<(), CellSplitContractErrorV1> {
        self.recurrent.validate("recurrent state")?;
        self.eligibility.validate("eligibility state")?;
        self.optimizer.validate("optimizer state")?;
        require_digest(self.state_evidence_digest, "state evidence")
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellBundleBindingV1 {
    pub child_cell_id: StableId,
    pub base_digest: Digest32,
    pub organ_adapter_digest: Digest32,
    pub cell_adapter_digest: Digest32,
    pub head_digest: Digest32,
    pub compatibility_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellBundleInheritanceV1 {
    pub base_mode: CellBundleModeV1,
    pub organ_adapter_mode: CellBundleModeV1,
    pub cell_adapter_mode: CellBundleModeV1,
    pub head_mode: CellBundleModeV1,
    pub compatibility_digest: Digest32,
    pub children: Vec<CellBundleBindingV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellChildV1 {
    pub child_cell_id: StableId,
    pub child_generation: Generation,
    pub child_scope_digest: Digest32,
    pub lineage_digest: Digest32,
    pub child_definition_digest: Digest32,
    pub child_bundle_digest: Digest32,
    pub dataset_partition_digest: Digest32,
    pub task_objective_digest: Digest32,
    pub route_predicate_digest: Digest32,
    pub fallback_route_digest: Digest32,
    pub route_mode: CellRouteModeV1,
}

/// Route and data partition evidence shared by a child cell.  The semantic
/// payload remains in the owning dataset/task/router registries; this record
/// binds the exact revisions that the split admission reviewed.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellRoutePartitionV1 {
    pub dataset_partition_digest: Digest32,
    pub task_objective_digest: Digest32,
    pub route_predicate_digest: Digest32,
    pub fallback_route_digest: Digest32,
    pub route_mode: CellRouteModeV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellChildPortBindingV1 {
    pub child_cell_id: StableId,
    pub input_port_digest: Digest32,
    pub output_port_digest: Digest32,
    pub termination_port_digest: Digest32,
    pub compatibility_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellPortCompatibilityV1 {
    pub parent_input_port_digest: Digest32,
    pub parent_output_port_digest: Digest32,
    pub circuit_route_digest: Digest32,
    pub abi_digest: Digest32,
    pub children: Vec<CellChildPortBindingV1>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CellResourceDeltaV1 {
    pub inference_latency_micros: u64,
    pub training_steps: u64,
    pub communication_bytes: u64,
    pub migration_bytes: u64,
    pub evaluation_steps: u64,
    pub resident_bytes: u64,
    pub checkpoint_bytes: u64,
}

impl CellResourceDeltaV1 {
    fn validate(&self) -> Result<(), CellSplitContractErrorV1> {
        let total = self
            .inference_latency_micros
            .checked_add(self.training_steps)
            .and_then(|value| value.checked_add(self.communication_bytes))
            .and_then(|value| value.checked_add(self.migration_bytes))
            .and_then(|value| value.checked_add(self.evaluation_steps))
            .and_then(|value| value.checked_add(self.resident_bytes))
            .and_then(|value| value.checked_add(self.checkpoint_bytes))
            .ok_or(CellSplitContractErrorV1::ResourceOverflow)?;
        if total > MAX_CELL_SPLIT_RESOURCE_UNITS_V1 {
            return Err(CellSplitContractErrorV1::ResourceOverflow);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellParentRetirementPlanV1 {
    pub disposition: CellParentDispositionV1,
    pub drain_watermark_digest: Digest32,
    pub tombstone_digest: Digest32,
    pub deletion_lineage_digest: Digest32,
    pub rollback_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitEvaluationBindingV1 {
    pub no_change_baseline_id: StableId,
    pub evaluation_id: StableId,
    pub evaluator_id: StableId,
    pub evaluation_receipt_digest: Digest32,
    pub retention_receipt_digest: Digest32,
    pub negative_transfer_receipt_digest: Digest32,
    pub cost_receipt_digest: Digest32,
}

/// Complete semantic description of a cell split.  This record carries no
/// authority and cannot select, activate, publish or retire a cell by itself.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitV1 {
    pub split_id: StableId,
    pub proposer_id: StableId,
    pub evaluator_id: StableId,
    pub parent_cell_id: StableId,
    pub organ_id: StableId,
    pub parent_scope_digest: Digest32,
    pub predecessor_generation: Generation,
    pub successor_generation: Generation,
    pub parent_definition_digest: Digest32,
    pub parent_bundle_digest: Digest32,
    pub children: Vec<CellChildV1>,
    pub inheritance: CellBundleInheritanceV1,
    pub state: CellStateSplitPlanV1,
    pub ports: CellPortCompatibilityV1,
    pub resources: CellResourceDeltaV1,
    pub retirement: CellParentRetirementPlanV1,
    pub evaluation: CellSplitEvaluationBindingV1,
    pub rollback_predecessor_digest: Digest32,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellSplitContractErrorV1 {
    EmptyDigest(&'static str),
    EmptyId(&'static str),
    ChildCount,
    DuplicateChild(StableId),
    ChildOrder,
    ChildGenerationMismatch,
    ChildBinding(StableId),
    MissingChildBinding,
    PortBinding(StableId),
    MissingPortBinding,
    GenerationNotExactSuccessor,
    EvaluatorEqualsProposer,
    EvaluatorBindingMismatch,
    UnexpectedTransformDigest(&'static str),
    InvalidRoutePartition,
    InheritanceModeMismatch(&'static str),
    InvalidRetirementPlan,
    ResourceOverflow,
    RuntimeTopologyDigest,
}

impl fmt::Display for CellSplitContractErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for CellSplitContractErrorV1 {}

impl CellSplitV1 {
    /// Validate the complete split plan before evaluation receipts exist.
    ///
    /// This validates structure, ownership, state transforms, routes, ports,
    /// resources and retirement policy, but deliberately does not require the
    /// receipts produced by the independent evaluator after the plan runs.
    pub fn validate_plan(&self) -> Result<(), CellSplitContractErrorV1> {
        for (label, id) in [
            ("split", &self.split_id),
            ("proposer", &self.proposer_id),
            ("evaluator", &self.evaluator_id),
            ("parent cell", &self.parent_cell_id),
            ("organ", &self.organ_id),
            ("baseline", &self.evaluation.no_change_baseline_id),
            ("evaluation", &self.evaluation.evaluation_id),
            ("evaluation evaluator", &self.evaluation.evaluator_id),
        ] {
            if id.as_str().is_empty() {
                return Err(CellSplitContractErrorV1::EmptyId(label));
            }
        }
        if self.proposer_id == self.evaluator_id || self.proposer_id == self.evaluation.evaluator_id
        {
            return Err(CellSplitContractErrorV1::EvaluatorEqualsProposer);
        }
        if self.evaluator_id != self.evaluation.evaluator_id {
            return Err(CellSplitContractErrorV1::EvaluatorBindingMismatch);
        }
        for (label, digest) in [
            ("parent scope", self.parent_scope_digest),
            ("parent definition", self.parent_definition_digest),
            ("parent bundle", self.parent_bundle_digest),
            (
                "bundle compatibility",
                self.inheritance.compatibility_digest,
            ),
            ("port route", self.ports.circuit_route_digest),
            ("port ABI", self.ports.abi_digest),
            (
                "parent drain watermark",
                self.retirement.drain_watermark_digest,
            ),
            ("parent tombstone", self.retirement.tombstone_digest),
            ("deletion lineage", self.retirement.deletion_lineage_digest),
            ("rollback", self.retirement.rollback_digest),
            ("rollback predecessor", self.rollback_predecessor_digest),
            ("evidence", self.evidence_digest),
        ] {
            require_digest(digest, label)?;
        }
        if self.predecessor_generation.next() != Ok(self.successor_generation) {
            return Err(CellSplitContractErrorV1::GenerationNotExactSuccessor);
        }

        let count = self.children.len();
        if !(2..=MAX_CELL_SPLIT_CHILDREN_V1).contains(&count) {
            return Err(CellSplitContractErrorV1::ChildCount);
        }
        let mut child_ids = BTreeSet::new();
        let mut child_scopes = BTreeSet::new();
        let mut dataset_partitions = BTreeSet::new();
        let mut route_predicates = BTreeSet::new();
        let mut previous = None;
        for child in &self.children {
            if child.child_cell_id == self.parent_cell_id
                || !child_ids.insert(child.child_cell_id.clone())
            {
                return Err(CellSplitContractErrorV1::DuplicateChild(
                    child.child_cell_id.clone(),
                ));
            }
            if previous.is_some_and(|id| id >= &child.child_cell_id) {
                return Err(CellSplitContractErrorV1::ChildOrder);
            }
            previous = Some(&child.child_cell_id);
            if !child_scopes.insert(child.child_scope_digest)
                || !dataset_partitions.insert(child.dataset_partition_digest)
                || !route_predicates.insert(child.route_predicate_digest)
            {
                return Err(CellSplitContractErrorV1::InvalidRoutePartition);
            }
            if child.child_generation != self.successor_generation {
                return Err(CellSplitContractErrorV1::ChildGenerationMismatch);
            }
            validate_child(child)?;
        }

        self.inheritance.validate(&child_ids)?;
        self.ports.validate(&child_ids)?;
        self.state.validate()?;
        if self.retirement.disposition == CellParentDispositionV1::Retire
            && self.state.in_flight_policy == CellInFlightPolicyV1::Cancel
        {
            return Err(CellSplitContractErrorV1::InvalidRetirementPlan);
        }
        self.resources.validate()?;
        self.validate_route_partition()?;
        Ok(())
    }

    /// Validate the complete, post-evaluation split record.
    pub fn validate(&self) -> Result<(), CellSplitContractErrorV1> {
        self.validate_plan()?;
        for (label, digest) in [
            (
                "evaluation receipt",
                self.evaluation.evaluation_receipt_digest,
            ),
            (
                "retention receipt",
                self.evaluation.retention_receipt_digest,
            ),
            (
                "negative transfer receipt",
                self.evaluation.negative_transfer_receipt_digest,
            ),
            ("cost receipt", self.evaluation.cost_receipt_digest),
        ] {
            require_digest(digest, label)?;
        }
        Ok(())
    }

    fn validate_route_partition(&self) -> Result<(), CellSplitContractErrorV1> {
        if self
            .children
            .iter()
            .any(|child| child.route_mode != CellRouteModeV1::Exclusive)
        {
            return Err(CellSplitContractErrorV1::InvalidRoutePartition);
        }
        Ok(())
    }

    /// Canonical digest for the complete, post-evaluation split record.
    /// The method validates first, so malformed records cannot acquire a
    /// final content digest.
    pub fn content_digest(&self) -> Result<Digest32, CellSplitContractErrorV1> {
        self.validate()?;
        Ok(Digest32::of_bytes(
            &self.digest_preimage(b"hepta.learning.cell-split.v1", true),
        ))
    }

    /// Stable identity for a structurally valid split before independent
    /// evaluation has produced its receipts. The final evaluation receipts are
    /// intentionally excluded from this preimage.
    pub fn evaluation_subject_digest(&self) -> Result<Digest32, CellSplitContractErrorV1> {
        self.validate_plan()?;
        Ok(Digest32::of_bytes(&self.digest_preimage(
            b"hepta.learning.cell-split.evaluation-subject.v1",
            false,
        )))
    }

    fn digest_preimage(&self, domain: &[u8], include_evaluation_receipts: bool) -> Vec<u8> {
        let mut bytes = domain.to_vec();
        push_id(&mut bytes, &self.split_id);
        push_id(&mut bytes, &self.proposer_id);
        push_id(&mut bytes, &self.evaluator_id);
        push_id(&mut bytes, &self.parent_cell_id);
        push_id(&mut bytes, &self.organ_id);
        for digest in [
            self.parent_scope_digest,
            self.parent_definition_digest,
            self.parent_bundle_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.predecessor_generation.get().to_be_bytes());
        bytes.extend_from_slice(&self.successor_generation.get().to_be_bytes());
        for child in &self.children {
            encode_child(&mut bytes, child);
        }
        encode_inheritance(&mut bytes, &self.inheritance);
        encode_state(&mut bytes, &self.state);
        encode_ports(&mut bytes, &self.ports);
        for value in [
            self.resources.inference_latency_micros,
            self.resources.training_steps,
            self.resources.communication_bytes,
            self.resources.migration_bytes,
            self.resources.evaluation_steps,
            self.resources.resident_bytes,
            self.resources.checkpoint_bytes,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        bytes.push(self.retirement.disposition.tag());
        for digest in [
            self.retirement.drain_watermark_digest,
            self.retirement.tombstone_digest,
            self.retirement.deletion_lineage_digest,
            self.retirement.rollback_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        if include_evaluation_receipts {
            for digest in [
                self.evaluation.evaluation_receipt_digest,
                self.evaluation.retention_receipt_digest,
                self.evaluation.negative_transfer_receipt_digest,
                self.evaluation.cost_receipt_digest,
            ] {
                bytes.extend_from_slice(digest.as_array());
            }
        }
        for digest in [self.rollback_predecessor_digest, self.evidence_digest] {
            bytes.extend_from_slice(digest.as_array());
        }
        push_id(&mut bytes, &self.evaluation.no_change_baseline_id);
        push_id(&mut bytes, &self.evaluation.evaluation_id);
        push_id(&mut bytes, &self.evaluation.evaluator_id);
        bytes
    }

    /// Bind the typed cell operation to the existing generic runtime topology
    /// DTOs. The root `Split` is followed by one explicit `Add` for every child,
    /// which is the shape required by `RuntimeTopologyCandidateV1` validation.
    /// The generic executor still owns admission and migration; this helper
    /// prevents a caller from silently replacing a typed cell split with an
    /// unrelated module-level `Split` delta.
    pub fn runtime_topology_deltas(
        &self,
        module_id: StableId,
        predecessor_digest: Digest32,
        candidate_digest: Digest32,
    ) -> Result<Vec<RuntimeTopologyDeltaV1>, CellSplitContractErrorV1> {
        self.validate()?;
        require_digest(predecessor_digest, "topology predecessor")?;
        require_digest(candidate_digest, "topology candidate")?;
        let split_digest = self.content_digest()?;
        let mut deltas = vec![RuntimeTopologyDeltaV1 {
            module_id,
            operation: RuntimeTopologyOperationV1::Split,
            related_module_ids: self
                .children
                .iter()
                .map(|child| child.child_cell_id.clone())
                .collect(),
            predecessor_digest,
            candidate_digest,
            evidence_digest: split_digest,
        }];
        deltas.extend(self.children.iter().map(|child| RuntimeTopologyDeltaV1 {
            module_id: child.child_cell_id.clone(),
            operation: RuntimeTopologyOperationV1::Add,
            related_module_ids: Vec::new(),
            predecessor_digest: Digest32::ZERO,
            candidate_digest: child.child_definition_digest,
            evidence_digest: child.child_bundle_digest,
        }));
        Ok(deltas)
    }

    /// Construct a validated runtime candidate containing the typed split and
    /// every required child-add delta. This still grants no selection or apply
    /// authority; it only closes the payload-to-runtime-contract binding.
    pub fn runtime_topology_candidate(
        &self,
        proposal_digest: Digest32,
        candidate_id: StableId,
        module_id: StableId,
        predecessor_digest: Digest32,
        candidate_graph_digest: Digest32,
    ) -> Result<RuntimeTopologyCandidateV1, CellSplitContractErrorV1> {
        self.validate()?;
        require_digest(proposal_digest, "topology proposal")?;
        let deltas =
            self.runtime_topology_deltas(module_id, predecessor_digest, candidate_graph_digest)?;
        let mut candidate = RuntimeTopologyCandidateV1 {
            proposal_digest,
            candidate_id,
            candidate_digest: Digest32::ZERO,
            baseline_generation: self.predecessor_generation,
            candidate_generation: self.successor_generation,
            selected_topology_digest: predecessor_digest,
            evaluation_digest: self.evaluation.evaluation_receipt_digest,
            rollback_predecessor_digest: predecessor_digest,
            changed: true,
            deltas,
        };
        candidate.candidate_digest = candidate
            .content_digest()
            .map_err(|_| CellSplitContractErrorV1::RuntimeTopologyDigest)?;
        candidate
            .validate()
            .map_err(|_| CellSplitContractErrorV1::RuntimeTopologyDigest)?;
        Ok(candidate)
    }
}

impl CellBundleInheritanceV1 {
    fn validate(&self, child_ids: &BTreeSet<StableId>) -> Result<(), CellSplitContractErrorV1> {
        require_digest(self.compatibility_digest, "bundle compatibility")?;
        if self.children.len() != child_ids.len() {
            return Err(CellSplitContractErrorV1::ChildCount);
        }
        let mut seen = BTreeSet::new();
        let mut previous = None;
        for binding in &self.children {
            if !child_ids.contains(&binding.child_cell_id)
                || !seen.insert(binding.child_cell_id.clone())
            {
                return Err(CellSplitContractErrorV1::ChildBinding(
                    binding.child_cell_id.clone(),
                ));
            }
            if previous.is_some_and(|id| id >= &binding.child_cell_id) {
                return Err(CellSplitContractErrorV1::ChildOrder);
            }
            previous = Some(&binding.child_cell_id);
            for (label, digest) in [
                ("base", binding.base_digest),
                ("organ adapter", binding.organ_adapter_digest),
                ("cell adapter", binding.cell_adapter_digest),
                ("head", binding.head_digest),
                ("bundle compatibility", binding.compatibility_digest),
            ] {
                require_digest(digest, label)?;
            }
        }
        if seen.len() != child_ids.len() || seen.iter().any(|id| !child_ids.contains(id)) {
            return Err(CellSplitContractErrorV1::MissingChildBinding);
        }
        validate_shared_mode(
            self.base_mode,
            self.children.iter().map(|binding| binding.base_digest),
            "base",
        )?;
        validate_shared_mode(
            self.organ_adapter_mode,
            self.children
                .iter()
                .map(|binding| binding.organ_adapter_digest),
            "organ adapter",
        )?;
        Ok(())
    }
}

fn validate_shared_mode(
    mode: CellBundleModeV1,
    mut digests: impl Iterator<Item = Digest32>,
    label: &'static str,
) -> Result<(), CellSplitContractErrorV1> {
    if mode != CellBundleModeV1::SharedImmutable {
        return Ok(());
    }
    let Some(first) = digests.next() else {
        return Err(CellSplitContractErrorV1::InheritanceModeMismatch(label));
    };
    if digests.any(|digest| digest != first) {
        return Err(CellSplitContractErrorV1::InheritanceModeMismatch(label));
    }
    Ok(())
}

impl CellPortCompatibilityV1 {
    fn validate(&self, child_ids: &BTreeSet<StableId>) -> Result<(), CellSplitContractErrorV1> {
        for (label, digest) in [
            ("parent input port", self.parent_input_port_digest),
            ("parent output port", self.parent_output_port_digest),
            ("circuit route", self.circuit_route_digest),
            ("port ABI", self.abi_digest),
        ] {
            require_digest(digest, label)?;
        }
        if self.children.len() != child_ids.len() {
            return Err(CellSplitContractErrorV1::ChildCount);
        }
        let mut seen = BTreeSet::new();
        let mut previous = None;
        for binding in &self.children {
            if !child_ids.contains(&binding.child_cell_id)
                || !seen.insert(binding.child_cell_id.clone())
            {
                return Err(CellSplitContractErrorV1::PortBinding(
                    binding.child_cell_id.clone(),
                ));
            }
            if previous.is_some_and(|id| id >= &binding.child_cell_id) {
                return Err(CellSplitContractErrorV1::ChildOrder);
            }
            previous = Some(&binding.child_cell_id);
            for (label, digest) in [
                ("child input port", binding.input_port_digest),
                ("child output port", binding.output_port_digest),
                ("child termination port", binding.termination_port_digest),
                ("child port compatibility", binding.compatibility_digest),
            ] {
                require_digest(digest, label)?;
            }
        }
        if seen.len() != child_ids.len() || seen.iter().any(|id| !child_ids.contains(id)) {
            return Err(CellSplitContractErrorV1::MissingPortBinding);
        }
        Ok(())
    }
}

fn validate_child(child: &CellChildV1) -> Result<(), CellSplitContractErrorV1> {
    for (label, digest) in [
        ("child scope", child.child_scope_digest),
        ("child lineage", child.lineage_digest),
        ("child definition", child.child_definition_digest),
        ("child bundle", child.child_bundle_digest),
        ("dataset partition", child.dataset_partition_digest),
        ("task objective", child.task_objective_digest),
        ("route predicate", child.route_predicate_digest),
        ("fallback route", child.fallback_route_digest),
    ] {
        require_digest(digest, label)?;
    }
    Ok(())
}

fn require_digest(digest: Digest32, label: &'static str) -> Result<(), CellSplitContractErrorV1> {
    if digest.is_zero() {
        Err(CellSplitContractErrorV1::EmptyDigest(label))
    } else {
        Ok(())
    }
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    let raw = id.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u32).to_be_bytes());
    bytes.extend_from_slice(raw);
}

fn push_digest(bytes: &mut Vec<u8>, digest: Digest32) {
    bytes.extend_from_slice(digest.as_array());
}

fn encode_child(bytes: &mut Vec<u8>, child: &CellChildV1) {
    push_id(bytes, &child.child_cell_id);
    bytes.extend_from_slice(&child.child_generation.get().to_be_bytes());
    for digest in [
        child.child_scope_digest,
        child.lineage_digest,
        child.child_definition_digest,
        child.child_bundle_digest,
        child.dataset_partition_digest,
        child.task_objective_digest,
        child.route_predicate_digest,
        child.fallback_route_digest,
    ] {
        push_digest(bytes, digest);
    }
    bytes.push(child.route_mode.tag());
}

fn encode_inheritance(bytes: &mut Vec<u8>, value: &CellBundleInheritanceV1) {
    bytes.extend_from_slice(&[
        value.base_mode.tag(),
        value.organ_adapter_mode.tag(),
        value.cell_adapter_mode.tag(),
        value.head_mode.tag(),
    ]);
    push_digest(bytes, value.compatibility_digest);
    bytes.extend_from_slice(&(value.children.len() as u32).to_be_bytes());
    for child in &value.children {
        push_id(bytes, &child.child_cell_id);
        for digest in [
            child.base_digest,
            child.organ_adapter_digest,
            child.cell_adapter_digest,
            child.head_digest,
            child.compatibility_digest,
        ] {
            push_digest(bytes, digest);
        }
    }
}

fn encode_state(bytes: &mut Vec<u8>, value: &CellStateSplitPlanV1) {
    for state in [value.recurrent, value.eligibility, value.optimizer] {
        bytes.push(state.kind.tag());
        push_digest(bytes, state.source_schema_digest);
        push_digest(bytes, state.target_schema_digest);
        push_digest(bytes, state.mapping_digest);
    }
    bytes.push(value.cache_policy.tag());
    bytes.push(value.in_flight_policy.tag());
    push_digest(bytes, value.state_evidence_digest);
}

fn encode_ports(bytes: &mut Vec<u8>, value: &CellPortCompatibilityV1) {
    for digest in [
        value.parent_input_port_digest,
        value.parent_output_port_digest,
        value.circuit_route_digest,
        value.abi_digest,
    ] {
        push_digest(bytes, digest);
    }
    bytes.extend_from_slice(&(value.children.len() as u32).to_be_bytes());
    for child in &value.children {
        push_id(bytes, &child.child_cell_id);
        for digest in [
            child.input_port_digest,
            child.output_port_digest,
            child.termination_port_digest,
            child.compatibility_digest,
        ] {
            push_digest(bytes, digest);
        }
    }
}
