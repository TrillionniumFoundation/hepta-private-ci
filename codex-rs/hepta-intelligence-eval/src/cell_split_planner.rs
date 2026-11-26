//! Governed DecisionCell split planning from measured telemetry.
//!
//! This module is deliberately an authority-free planning boundary.  It turns
//! a typed observation into a replayable [`CellSplitProposalSignalV1`] and
//! turns that signal plus an explicitly admitted policy/context into a complete
//! [`CellSplitV1`] plan.  It does not write a registry, dispatch a route, or
//! claim that a source simulation is production evidence.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::CellBundleBindingV1;
use codex_hepta_types::CellBundleInheritanceV1;
use codex_hepta_types::CellBundleModeV1;
use codex_hepta_types::CellCachePolicyV1;
use codex_hepta_types::CellChildPortBindingV1;
use codex_hepta_types::CellChildV1;
use codex_hepta_types::CellInFlightPolicyV1;
use codex_hepta_types::CellParentDispositionV1;
use codex_hepta_types::CellParentRetirementPlanV1;
use codex_hepta_types::CellPortCompatibilityV1;
use codex_hepta_types::CellResourceDeltaV1;
use codex_hepta_types::CellRouteModeV1;
use codex_hepta_types::CellSplitContractErrorV1;
use codex_hepta_types::CellSplitEvaluationBindingV1;
use codex_hepta_types::CellSplitV1;
use codex_hepta_types::CellStateSplitPlanV1;
use codex_hepta_types::CellStateTransformKindV1;
use codex_hepta_types::CellStateTransformV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::CellSplitAutomationErrorV1;
use crate::CellSplitProposalSignalV1;
use crate::CellSplitProposalTriggerV1;

const MAX_CHILD_COUNT_V1: u8 = 64;
const MIN_CHILD_COUNT_V1: u8 = 2;
const MAX_ID_PREFIX_BYTES_V1: usize = 96;
const MAX_COVERAGE_PPM_V1: u32 = 1_000_000;

/// A single parent observation from a telemetry owner.
///
/// Values are integer, unit-bearing counters so the trigger decision is
/// deterministic across hosts. `utility_*_q24` are signed Q24 scores,
/// coverage is parts-per-million, and resource values use the units named by
/// their fields. The evidence digest must be issued by the telemetry owner;
/// this module never treats local wall-clock data as production evidence.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitTelemetryObservationV1 {
    pub parent_cell_id: StableId,
    pub parent_generation: Generation,
    pub parent_bundle_digest: Digest32,
    pub baseline_utility_q24: i64,
    pub observed_utility_q24: i64,
    pub observed_task_coverage_ppm: u32,
    pub target_task_coverage_ppm: u32,
    pub p95_latency_micros: u64,
    pub resident_bytes: u64,
    pub communication_bytes: u64,
    pub training_steps: u64,
    pub migration_bytes: u64,
    pub evidence_digest: Digest32,
    pub observation_sequence: u64,
    pub observed_at_micros: u64,
}

impl CellSplitTelemetryObservationV1 {
    pub fn validate(&self) -> Result<(), CellSplitPlannerErrorV1> {
        if self.parent_cell_id.as_str().is_empty()
            || self.parent_bundle_digest.is_zero()
            || self.evidence_digest.is_zero()
            || self.observation_sequence == 0
            || self.observed_at_micros == 0
            || self.observed_task_coverage_ppm > MAX_COVERAGE_PPM_V1
            || self.target_task_coverage_ppm > MAX_COVERAGE_PPM_V1
        {
            return Err(CellSplitPlannerErrorV1::InvalidTelemetry);
        }
        if self.target_task_coverage_ppm < self.observed_task_coverage_ppm {
            return Err(CellSplitPlannerErrorV1::InvalidTelemetry);
        }
        // The digest is an issuer-provided witness. It is intentionally not
        // recomputed here because production telemetry may be signed/enveloped
        // by a separate owner; the source adapter below still binds it into the
        // emitted signal digest.
        Ok(())
    }

    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.learning.cell-split.telemetry.v1".to_vec();
        push_id(&mut bytes, &self.parent_cell_id);
        bytes.extend_from_slice(&self.parent_generation.get().to_be_bytes());
        for digest in [self.parent_bundle_digest, self.evidence_digest] {
            bytes.extend_from_slice(digest.as_array());
        }
        for value in [
            self.baseline_utility_q24 as u64,
            self.observed_utility_q24 as u64,
            u64::from(self.observed_task_coverage_ppm),
            u64::from(self.target_task_coverage_ppm),
            self.p95_latency_micros,
            self.resident_bytes,
            self.communication_bytes,
            self.training_steps,
            self.migration_bytes,
            self.observation_sequence,
            self.observed_at_micros,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        Digest32::of_bytes(&bytes)
    }
}

/// Governed thresholds and shape controls. This is an immutable policy
/// artifact in production; its digest is copied into every proposal signal.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitProposalPolicyV1 {
    pub policy_id: StableId,
    pub proposer_id: StableId,
    pub evaluator_id: StableId,
    pub organ_id: StableId,
    pub utility_regression_threshold_q24: i64,
    pub task_coverage_gap_ppm: u32,
    pub latency_pressure_micros: u64,
    pub resident_pressure_bytes: u64,
    pub child_count: u8,
    pub child_id_prefix: StableId,
    pub parent_disposition: CellParentDispositionV1,
    pub base_mode: CellBundleModeV1,
    pub organ_adapter_mode: CellBundleModeV1,
    pub cell_adapter_mode: CellBundleModeV1,
    pub head_mode: CellBundleModeV1,
    pub recurrent_transform: CellStateTransformKindV1,
    pub eligibility_transform: CellStateTransformKindV1,
    pub optimizer_transform: CellStateTransformKindV1,
    pub cache_policy: CellCachePolicyV1,
    pub in_flight_policy: CellInFlightPolicyV1,
    pub training_steps_per_child: u64,
    pub evaluation_steps_per_child: u64,
    pub resident_bytes_per_child: u64,
    pub checkpoint_bytes_per_child: u64,
    pub communication_bytes_per_child: u64,
    pub migration_bytes_per_child: u64,
    policy_digest: Digest32,
}

impl CellSplitProposalPolicyV1 {
    pub fn new(
        policy_id: StableId,
        proposer_id: StableId,
        evaluator_id: StableId,
        organ_id: StableId,
        utility_regression_threshold_q24: i64,
        task_coverage_gap_ppm: u32,
        latency_pressure_micros: u64,
        resident_pressure_bytes: u64,
        child_count: u8,
        child_id_prefix: StableId,
        parent_disposition: CellParentDispositionV1,
        base_mode: CellBundleModeV1,
        organ_adapter_mode: CellBundleModeV1,
        cell_adapter_mode: CellBundleModeV1,
        head_mode: CellBundleModeV1,
        recurrent_transform: CellStateTransformKindV1,
        eligibility_transform: CellStateTransformKindV1,
        optimizer_transform: CellStateTransformKindV1,
        cache_policy: CellCachePolicyV1,
        in_flight_policy: CellInFlightPolicyV1,
        training_steps_per_child: u64,
        evaluation_steps_per_child: u64,
        resident_bytes_per_child: u64,
        checkpoint_bytes_per_child: u64,
        communication_bytes_per_child: u64,
        migration_bytes_per_child: u64,
    ) -> Result<Self, CellSplitPlannerErrorV1> {
        let policy = Self {
            policy_id,
            proposer_id,
            evaluator_id,
            organ_id,
            utility_regression_threshold_q24,
            task_coverage_gap_ppm,
            latency_pressure_micros,
            resident_pressure_bytes,
            child_count,
            child_id_prefix,
            parent_disposition,
            base_mode,
            organ_adapter_mode,
            cell_adapter_mode,
            head_mode,
            recurrent_transform,
            eligibility_transform,
            optimizer_transform,
            cache_policy,
            in_flight_policy,
            training_steps_per_child,
            evaluation_steps_per_child,
            resident_bytes_per_child,
            checkpoint_bytes_per_child,
            communication_bytes_per_child,
            migration_bytes_per_child,
            policy_digest: Digest32::ZERO,
        };
        policy.validate()?;
        let mut policy = policy;
        policy.policy_digest = policy.compute_digest();
        Ok(policy)
    }

    pub fn validate(&self) -> Result<(), CellSplitPlannerErrorV1> {
        for id in [
            &self.policy_id,
            &self.proposer_id,
            &self.evaluator_id,
            &self.organ_id,
            &self.child_id_prefix,
        ] {
            if id.as_str().is_empty() {
                return Err(CellSplitPlannerErrorV1::InvalidPolicy);
            }
        }
        if self.proposer_id == self.evaluator_id
            || !(MIN_CHILD_COUNT_V1..=MAX_CHILD_COUNT_V1).contains(&self.child_count)
            || self.utility_regression_threshold_q24 <= 0
            || self.task_coverage_gap_ppm == 0
            || self.task_coverage_gap_ppm > MAX_COVERAGE_PPM_V1
            || self.latency_pressure_micros == 0
            || self.resident_pressure_bytes == 0
            || self.child_id_prefix.as_str().len() > MAX_ID_PREFIX_BYTES_V1
            || (self.parent_disposition == CellParentDispositionV1::Retire
                && self.in_flight_policy == CellInFlightPolicyV1::Cancel)
        {
            return Err(CellSplitPlannerErrorV1::InvalidPolicy);
        }
        if self.policy_digest != Digest32::ZERO && self.policy_digest != self.compute_digest() {
            return Err(CellSplitPlannerErrorV1::PolicyDigest);
        }
        Ok(())
    }

    #[must_use]
    pub fn policy_digest(&self) -> Digest32 {
        self.policy_digest
    }

    fn compute_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.learning.cell-split.proposal-policy.v1".to_vec();
        for id in [
            &self.policy_id,
            &self.proposer_id,
            &self.evaluator_id,
            &self.organ_id,
            &self.child_id_prefix,
        ] {
            push_id(&mut bytes, id);
        }
        bytes.extend_from_slice(&self.utility_regression_threshold_q24.to_be_bytes());
        bytes.extend_from_slice(&self.task_coverage_gap_ppm.to_be_bytes());
        bytes.extend_from_slice(&self.latency_pressure_micros.to_be_bytes());
        bytes.extend_from_slice(&self.resident_pressure_bytes.to_be_bytes());
        bytes.push(self.child_count);
        bytes.push(parent_disposition_tag(self.parent_disposition));
        for mode in [
            self.base_mode,
            self.organ_adapter_mode,
            self.cell_adapter_mode,
            self.head_mode,
        ] {
            bytes.push(bundle_mode_tag(mode));
        }
        for transform in [
            self.recurrent_transform,
            self.eligibility_transform,
            self.optimizer_transform,
        ] {
            bytes.push(transform_tag(transform));
        }
        bytes.push(cache_policy_tag(self.cache_policy));
        bytes.push(in_flight_policy_tag(self.in_flight_policy));
        for value in [
            self.training_steps_per_child,
            self.evaluation_steps_per_child,
            self.resident_bytes_per_child,
            self.checkpoint_bytes_per_child,
            self.communication_bytes_per_child,
            self.migration_bytes_per_child,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        Digest32::of_bytes(&bytes)
    }
}

/// Immutable owner context for references that cannot be invented from a
/// trigger. In production these digests are resolved from the parent artifact,
/// organ and circuit registries before the planner is called.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitPlannerContextV1 {
    pub parent_scope_digest: Digest32,
    pub parent_definition_digest: Digest32,
    pub parent_input_port_digest: Digest32,
    pub parent_output_port_digest: Digest32,
    pub circuit_route_digest: Digest32,
    pub abi_digest: Digest32,
    pub base_digest: Digest32,
    pub organ_adapter_digest: Digest32,
    pub state_schema_digest: Digest32,
    pub compatibility_digest: Digest32,
    pub no_change_baseline_id: StableId,
    pub evaluation_id: StableId,
    pub rollback_predecessor_digest: Digest32,
}

impl CellSplitPlannerContextV1 {
    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.learning.cell-split.planner-context.v1".to_vec();
        for digest in [
            self.parent_scope_digest,
            self.parent_definition_digest,
            self.parent_input_port_digest,
            self.parent_output_port_digest,
            self.circuit_route_digest,
            self.abi_digest,
            self.base_digest,
            self.organ_adapter_digest,
            self.state_schema_digest,
            self.compatibility_digest,
            self.rollback_predecessor_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        push_id(&mut bytes, &self.no_change_baseline_id);
        push_id(&mut bytes, &self.evaluation_id);
        Digest32::of_bytes(&bytes)
    }

    pub fn validate(&self) -> Result<(), CellSplitPlannerErrorV1> {
        for digest in [
            self.parent_scope_digest,
            self.parent_definition_digest,
            self.parent_input_port_digest,
            self.parent_output_port_digest,
            self.circuit_route_digest,
            self.abi_digest,
            self.base_digest,
            self.organ_adapter_digest,
            self.state_schema_digest,
            self.compatibility_digest,
            self.rollback_predecessor_digest,
        ] {
            if digest.is_zero() {
                return Err(CellSplitPlannerErrorV1::InvalidContext);
            }
        }
        if self.no_change_baseline_id.as_str().is_empty() || self.evaluation_id.as_str().is_empty()
        {
            return Err(CellSplitPlannerErrorV1::InvalidContext);
        }
        Ok(())
    }
}

/// Evaluate telemetry against policy and emit the exact signal consumed by
/// [`CellSplitProposalSourceV1`]. Trigger priority is fixed and replayable:
/// utility regression, then task coverage, then resource pressure.
pub fn cell_split_signal_from_telemetry_v1(
    telemetry: &CellSplitTelemetryObservationV1,
    policy: &CellSplitProposalPolicyV1,
) -> Result<CellSplitProposalSignalV1, CellSplitPlannerErrorV1> {
    telemetry.validate()?;
    policy.validate()?;
    let trigger = if utility_regressed(telemetry, policy) {
        CellSplitProposalTriggerV1::UtilityRegression
    } else if task_coverage_opportunity(telemetry, policy) {
        CellSplitProposalTriggerV1::TaskCoverageOpportunity
    } else if resource_pressure(telemetry, policy) {
        CellSplitProposalTriggerV1::ResourcePressure
    } else {
        return Err(CellSplitPlannerErrorV1::NoTrigger);
    };
    CellSplitProposalSignalV1::new(
        telemetry.parent_cell_id.clone(),
        telemetry.parent_generation,
        telemetry.parent_bundle_digest,
        trigger,
        telemetry.content_digest(),
        policy.policy_digest(),
        telemetry.observation_sequence,
        telemetry.observed_at_micros,
    )
    .map_err(CellSplitPlannerErrorV1::Signal)
}

/// Source adapter boundary. A production implementation must bind the returned
/// observation to a signed, durable telemetry record before the planner is
/// admitted. The in-memory implementation is useful only for source tests.
pub trait CellSplitTelemetrySourceV1 {
    type Error: fmt::Display;

    fn observe(
        &mut self,
        parent_cell_id: &StableId,
    ) -> Result<CellSplitTelemetryObservationV1, Self::Error>;
}

pub fn collect_cell_split_signal_v1<Source>(
    source: &mut Source,
    parent_cell_id: &StableId,
    policy: &CellSplitProposalPolicyV1,
) -> Result<CellSplitProposalSignalV1, CellSplitPlannerErrorV1>
where
    Source: CellSplitTelemetrySourceV1,
{
    let telemetry = source
        .observe(parent_cell_id)
        .map_err(|error| CellSplitPlannerErrorV1::TelemetrySource(error.to_string()))?;
    if telemetry.parent_cell_id != *parent_cell_id {
        return Err(CellSplitPlannerErrorV1::Binding("telemetry parent"));
    }
    cell_split_signal_from_telemetry_v1(&telemetry, policy)
}

/// Deterministic, policy-governed plan synthesizer. It is intentionally
/// separate from proposal emission: the caller must supply registry-resolved
/// context and an admitted policy, and the resulting plan is still only an
/// evaluation subject until an independent evaluator supplies receipts.
pub struct CellSplitGovernedPlannerV1;

impl CellSplitGovernedPlannerV1 {
    pub fn synthesize(
        signal: &CellSplitProposalSignalV1,
        policy: &CellSplitProposalPolicyV1,
        context: &CellSplitPlannerContextV1,
        telemetry: &CellSplitTelemetryObservationV1,
    ) -> Result<CellSplitV1, CellSplitPlannerErrorV1> {
        signal
            .verify_digest()
            .map_err(CellSplitPlannerErrorV1::Signal)?;
        telemetry.validate()?;
        policy.validate()?;
        context.validate()?;
        if signal.policy_digest != policy.policy_digest()
            || signal.parent_cell_id != telemetry.parent_cell_id
            || signal.parent_generation != telemetry.parent_generation
            || signal.parent_bundle_digest != telemetry.parent_bundle_digest
            || signal.trigger_evidence_digest != telemetry.content_digest()
        {
            return Err(CellSplitPlannerErrorV1::Binding("signal policy/telemetry"));
        }
        let expected_signal = cell_split_signal_from_telemetry_v1(telemetry, policy)?;
        if expected_signal != *signal {
            return Err(CellSplitPlannerErrorV1::Binding("signal replay"));
        }
        let successor_generation = signal
            .parent_generation
            .next()
            .map_err(|_| CellSplitPlannerErrorV1::GenerationOverflow)?;
        let context_digest = context.content_digest();
        let split_id = stable_id_from_parts("cell-split", signal.signal_digest(), context_digest)?;
        let children = build_children(signal, policy, successor_generation)?;
        let inheritance = build_inheritance(signal, policy, context, &children);
        let state = build_state(signal, policy, context);
        let ports = build_ports(signal, policy, context, &children);
        let resources = build_resources(telemetry, policy)?;
        let retirement = CellParentRetirementPlanV1 {
            disposition: policy.parent_disposition,
            drain_watermark_digest: derive_digest("drain-watermark", signal, 0),
            tombstone_digest: derive_digest("tombstone", signal, 0),
            deletion_lineage_digest: derive_digest("deletion-lineage", signal, 0),
            rollback_digest: derive_digest("rollback", signal, 0),
        };
        let evaluation = CellSplitEvaluationBindingV1 {
            no_change_baseline_id: context.no_change_baseline_id.clone(),
            evaluation_id: context.evaluation_id.clone(),
            evaluator_id: policy.evaluator_id.clone(),
            evaluation_receipt_digest: Digest32::ZERO,
            retention_receipt_digest: Digest32::ZERO,
            negative_transfer_receipt_digest: Digest32::ZERO,
            cost_receipt_digest: Digest32::ZERO,
        };
        let split = CellSplitV1 {
            split_id,
            proposer_id: policy.proposer_id.clone(),
            evaluator_id: policy.evaluator_id.clone(),
            parent_cell_id: signal.parent_cell_id.clone(),
            organ_id: policy.organ_id.clone(),
            parent_scope_digest: context.parent_scope_digest,
            predecessor_generation: signal.parent_generation,
            successor_generation,
            parent_definition_digest: context.parent_definition_digest,
            parent_bundle_digest: signal.parent_bundle_digest,
            children,
            inheritance,
            state,
            ports,
            resources,
            retirement,
            evaluation,
            rollback_predecessor_digest: context.rollback_predecessor_digest,
            evidence_digest: derive_plan_digest(
                "plan-evidence",
                signal,
                context_digest,
                policy.policy_digest(),
            ),
        };
        split
            .validate_plan()
            .map_err(CellSplitPlannerErrorV1::Contract)?;
        Ok(split)
    }
}

fn utility_regressed(
    telemetry: &CellSplitTelemetryObservationV1,
    policy: &CellSplitProposalPolicyV1,
) -> bool {
    telemetry
        .baseline_utility_q24
        .checked_sub(telemetry.observed_utility_q24)
        .is_some_and(|delta| delta >= policy.utility_regression_threshold_q24)
}

fn task_coverage_opportunity(
    telemetry: &CellSplitTelemetryObservationV1,
    policy: &CellSplitProposalPolicyV1,
) -> bool {
    telemetry
        .target_task_coverage_ppm
        .checked_sub(telemetry.observed_task_coverage_ppm)
        .is_some_and(|gap| gap >= policy.task_coverage_gap_ppm)
}

fn resource_pressure(
    telemetry: &CellSplitTelemetryObservationV1,
    policy: &CellSplitProposalPolicyV1,
) -> bool {
    telemetry.p95_latency_micros >= policy.latency_pressure_micros
        || telemetry.resident_bytes >= policy.resident_pressure_bytes
}

fn build_children(
    signal: &CellSplitProposalSignalV1,
    policy: &CellSplitProposalPolicyV1,
    generation: Generation,
) -> Result<Vec<CellChildV1>, CellSplitPlannerErrorV1> {
    (0..policy.child_count)
        .map(|index| {
            let ordinal = u16::from(index) + 1;
            let id = StableId::new(format!("{}.{ordinal:02}", policy.child_id_prefix))
                .map_err(|_| CellSplitPlannerErrorV1::InvalidPolicy)?;
            Ok(CellChildV1 {
                child_cell_id: id,
                child_generation: generation,
                child_scope_digest: derive_digest("child-scope", signal, index),
                lineage_digest: derive_digest("child-lineage", signal, index),
                child_definition_digest: derive_digest("child-definition", signal, index),
                child_bundle_digest: derive_digest("child-bundle", signal, index),
                dataset_partition_digest: derive_digest("dataset-partition", signal, index),
                task_objective_digest: derive_digest("task-objective", signal, index),
                route_predicate_digest: derive_digest("route-predicate", signal, index),
                fallback_route_digest: derive_digest("fallback-route", signal, index),
                route_mode: CellRouteModeV1::Exclusive,
            })
        })
        .collect()
}

fn build_inheritance(
    signal: &CellSplitProposalSignalV1,
    policy: &CellSplitProposalPolicyV1,
    context: &CellSplitPlannerContextV1,
    children: &[CellChildV1],
) -> CellBundleInheritanceV1 {
    let children = children
        .iter()
        .enumerate()
        .map(|(index, child)| CellBundleBindingV1 {
            child_cell_id: child.child_cell_id.clone(),
            base_digest: inherited_component_digest(
                policy.base_mode,
                context.base_digest,
                "base-child",
                signal,
                index as u8,
            ),
            organ_adapter_digest: inherited_component_digest(
                policy.organ_adapter_mode,
                context.organ_adapter_digest,
                "organ-adapter-child",
                signal,
                index as u8,
            ),
            cell_adapter_digest: inherited_component_digest(
                policy.cell_adapter_mode,
                derive_digest("cell-adapter-shared", signal, 0),
                "cell-adapter",
                signal,
                index as u8,
            ),
            head_digest: inherited_component_digest(
                policy.head_mode,
                derive_digest("head-shared", signal, 0),
                "head",
                signal,
                index as u8,
            ),
            compatibility_digest: derive_digest("bundle-child-compatibility", signal, index as u8),
        })
        .collect();
    CellBundleInheritanceV1 {
        base_mode: policy.base_mode,
        organ_adapter_mode: policy.organ_adapter_mode,
        cell_adapter_mode: policy.cell_adapter_mode,
        head_mode: policy.head_mode,
        compatibility_digest: context.compatibility_digest,
        children,
    }
}

fn inherited_component_digest(
    mode: CellBundleModeV1,
    shared_digest: Digest32,
    child_domain: &str,
    signal: &CellSplitProposalSignalV1,
    index: u8,
) -> Digest32 {
    match mode {
        CellBundleModeV1::SharedImmutable => shared_digest,
        CellBundleModeV1::CloneMutable | CellBundleModeV1::Reset | CellBundleModeV1::Distill => {
            derive_digest(child_domain, signal, index)
        }
    }
}

fn build_state(
    signal: &CellSplitProposalSignalV1,
    policy: &CellSplitProposalPolicyV1,
    context: &CellSplitPlannerContextV1,
) -> CellStateSplitPlanV1 {
    let transform = |label: &str, kind: CellStateTransformKindV1| CellStateTransformV1 {
        kind,
        source_schema_digest: context.state_schema_digest,
        target_schema_digest: derive_digest(label, signal, 0),
        mapping_digest: match kind {
            CellStateTransformKindV1::Partition | CellStateTransformKindV1::Custom => {
                derive_digest("state-mapping", signal, 0)
            }
            CellStateTransformKindV1::Copy | CellStateTransformKindV1::Reset => Digest32::ZERO,
        },
    };
    CellStateSplitPlanV1 {
        recurrent: transform("recurrent-target-schema", policy.recurrent_transform),
        eligibility: transform("eligibility-target-schema", policy.eligibility_transform),
        optimizer: transform("optimizer-target-schema", policy.optimizer_transform),
        cache_policy: policy.cache_policy,
        in_flight_policy: policy.in_flight_policy,
        state_evidence_digest: derive_digest("state-evidence", signal, 0),
    }
}

fn build_ports(
    signal: &CellSplitProposalSignalV1,
    _policy: &CellSplitProposalPolicyV1,
    context: &CellSplitPlannerContextV1,
    children: &[CellChildV1],
) -> CellPortCompatibilityV1 {
    let children = children
        .iter()
        .enumerate()
        .map(|(index, child)| CellChildPortBindingV1 {
            child_cell_id: child.child_cell_id.clone(),
            input_port_digest: derive_digest("child-input-port", signal, index as u8),
            output_port_digest: derive_digest("child-output-port", signal, index as u8),
            termination_port_digest: derive_digest("child-termination-port", signal, index as u8),
            compatibility_digest: derive_digest("child-port-compatibility", signal, index as u8),
        })
        .collect();
    CellPortCompatibilityV1 {
        parent_input_port_digest: context.parent_input_port_digest,
        parent_output_port_digest: context.parent_output_port_digest,
        circuit_route_digest: context.circuit_route_digest,
        abi_digest: context.abi_digest,
        children,
    }
}

fn build_resources(
    telemetry: &CellSplitTelemetryObservationV1,
    policy: &CellSplitProposalPolicyV1,
) -> Result<CellResourceDeltaV1, CellSplitPlannerErrorV1> {
    let count = u64::from(policy.child_count);
    let resident_bytes = telemetry
        .resident_bytes
        .checked_add(
            policy
                .resident_bytes_per_child
                .checked_mul(count)
                .ok_or(CellSplitPlannerErrorV1::ResourceOverflow)?,
        )
        .ok_or(CellSplitPlannerErrorV1::ResourceOverflow)?;
    let checkpoint_bytes = telemetry
        .resident_bytes
        .checked_add(
            policy
                .checkpoint_bytes_per_child
                .checked_mul(count)
                .ok_or(CellSplitPlannerErrorV1::ResourceOverflow)?,
        )
        .ok_or(CellSplitPlannerErrorV1::ResourceOverflow)?;
    let communication_bytes = telemetry
        .communication_bytes
        .checked_add(
            policy
                .communication_bytes_per_child
                .checked_mul(count)
                .ok_or(CellSplitPlannerErrorV1::ResourceOverflow)?,
        )
        .ok_or(CellSplitPlannerErrorV1::ResourceOverflow)?;
    let migration_bytes = telemetry
        .migration_bytes
        .checked_add(
            policy
                .migration_bytes_per_child
                .checked_mul(count)
                .ok_or(CellSplitPlannerErrorV1::ResourceOverflow)?,
        )
        .ok_or(CellSplitPlannerErrorV1::ResourceOverflow)?;
    let training_steps = policy
        .training_steps_per_child
        .checked_mul(count)
        .ok_or(CellSplitPlannerErrorV1::ResourceOverflow)?;
    let evaluation_steps = policy
        .evaluation_steps_per_child
        .checked_mul(count)
        .ok_or(CellSplitPlannerErrorV1::ResourceOverflow)?;
    let resources = CellResourceDeltaV1 {
        inference_latency_micros: telemetry.p95_latency_micros,
        training_steps,
        communication_bytes,
        migration_bytes,
        evaluation_steps,
        resident_bytes,
        checkpoint_bytes,
    };
    resources
        .validate_for_planner()
        .map_err(|_| CellSplitPlannerErrorV1::ResourceOverflow)?;
    Ok(resources)
}

fn derive_digest(domain: &str, signal: &CellSplitProposalSignalV1, ordinal: u8) -> Digest32 {
    let mut bytes = b"hepta.learning.cell-split.plan-reference.v1".to_vec();
    bytes.extend_from_slice(domain.as_bytes());
    bytes.push(0);
    bytes.extend_from_slice(signal.signal_digest().as_array());
    bytes.push(ordinal);
    Digest32::of_bytes(&bytes)
}

fn stable_id_from_parts(
    prefix: &str,
    first: Digest32,
    second: Digest32,
) -> Result<StableId, CellSplitPlannerErrorV1> {
    let digest = Digest32::of_parts(&[first.as_array(), second.as_array()]);
    StableId::new(format!("{prefix}.{}", &digest.to_string()[..16]))
        .map_err(|_| CellSplitPlannerErrorV1::InvalidContext)
}

fn derive_plan_digest(
    domain: &str,
    signal: &CellSplitProposalSignalV1,
    context_digest: Digest32,
    policy_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.learning.cell-split.plan-evidence.v1".to_vec();
    bytes.extend_from_slice(domain.as_bytes());
    bytes.push(0);
    bytes.extend_from_slice(signal.signal_digest().as_array());
    bytes.extend_from_slice(context_digest.as_array());
    bytes.extend_from_slice(policy_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    let value = id.as_str().as_bytes();
    bytes.extend_from_slice(&(value.len() as u32).to_be_bytes());
    bytes.extend_from_slice(value);
}

fn bundle_mode_tag(mode: CellBundleModeV1) -> u8 {
    match mode {
        CellBundleModeV1::SharedImmutable => 0,
        CellBundleModeV1::CloneMutable => 1,
        CellBundleModeV1::Reset => 2,
        CellBundleModeV1::Distill => 3,
    }
}

fn transform_tag(kind: CellStateTransformKindV1) -> u8 {
    match kind {
        CellStateTransformKindV1::Copy => 0,
        CellStateTransformKindV1::Partition => 1,
        CellStateTransformKindV1::Reset => 2,
        CellStateTransformKindV1::Custom => 3,
    }
}

fn cache_policy_tag(policy: CellCachePolicyV1) -> u8 {
    match policy {
        CellCachePolicyV1::Drop => 0,
        CellCachePolicyV1::Partition => 1,
        CellCachePolicyV1::Revalidate => 2,
    }
}

fn in_flight_policy_tag(policy: CellInFlightPolicyV1) -> u8 {
    match policy {
        CellInFlightPolicyV1::Drain => 0,
        CellInFlightPolicyV1::Reassign => 1,
        CellInFlightPolicyV1::Cancel => 2,
    }
}

fn parent_disposition_tag(disposition: CellParentDispositionV1) -> u8 {
    match disposition {
        CellParentDispositionV1::Retire => 0,
        CellParentDispositionV1::Quarantine => 1,
        CellParentDispositionV1::KeepShadow => 2,
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellSplitPlannerErrorV1 {
    InvalidTelemetry,
    InvalidPolicy,
    InvalidContext,
    PolicyDigest,
    NoTrigger,
    Binding(&'static str),
    TelemetrySource(String),
    Signal(CellSplitAutomationErrorV1),
    Contract(CellSplitContractErrorV1),
    GenerationOverflow,
    ResourceOverflow,
}

impl fmt::Display for CellSplitPlannerErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CellSplitPlannerErrorV1 {}

// The resource contract keeps validation private in hepta-types because its
// public plan validator owns the full semantic record. This narrow extension
// avoids duplicating the overflow sum here while retaining the same bound.
trait ResourceValidation {
    fn validate_for_planner(&self) -> Result<(), ()>;
}

impl ResourceValidation for CellResourceDeltaV1 {
    fn validate_for_planner(&self) -> Result<(), ()> {
        let total = self
            .inference_latency_micros
            .checked_add(self.training_steps)
            .and_then(|value| value.checked_add(self.communication_bytes))
            .and_then(|value| value.checked_add(self.migration_bytes))
            .and_then(|value| value.checked_add(self.evaluation_steps))
            .and_then(|value| value.checked_add(self.resident_bytes))
            .and_then(|value| value.checked_add(self.checkpoint_bytes))
            .ok_or(())?;
        if total > (1_u64 << 60) {
            return Err(());
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("test id")
    }

    fn digest(seed: u8) -> Digest32 {
        Digest32::from_array([seed; 32])
    }

    fn policy() -> CellSplitProposalPolicyV1 {
        CellSplitProposalPolicyV1::new(
            id("policy.cell-split"),
            id("proposer.cell-split"),
            id("evaluator.cell-split"),
            id("organ.retrieval"),
            100,
            10_000,
            900,
            90_000,
            3,
            id("cell.child"),
            CellParentDispositionV1::KeepShadow,
            CellBundleModeV1::SharedImmutable,
            CellBundleModeV1::SharedImmutable,
            CellBundleModeV1::CloneMutable,
            CellBundleModeV1::CloneMutable,
            CellStateTransformKindV1::Partition,
            CellStateTransformKindV1::Partition,
            CellStateTransformKindV1::Reset,
            CellCachePolicyV1::Revalidate,
            CellInFlightPolicyV1::Drain,
            20,
            30,
            100,
            120,
            50,
            40,
        )
        .expect("policy")
    }

    fn telemetry() -> CellSplitTelemetryObservationV1 {
        CellSplitTelemetryObservationV1 {
            parent_cell_id: id("cell.parent"),
            parent_generation: Generation::new(7).expect("generation"),
            parent_bundle_digest: digest(1),
            baseline_utility_q24: 1_000,
            observed_utility_q24: 800,
            observed_task_coverage_ppm: 500_000,
            target_task_coverage_ppm: 700_000,
            p95_latency_micros: 500,
            resident_bytes: 50_000,
            communication_bytes: 100,
            training_steps: 2,
            migration_bytes: 3,
            evidence_digest: digest(2),
            observation_sequence: 4,
            observed_at_micros: 99,
        }
    }

    fn context() -> CellSplitPlannerContextV1 {
        CellSplitPlannerContextV1 {
            parent_scope_digest: digest(10),
            parent_definition_digest: digest(11),
            parent_input_port_digest: digest(12),
            parent_output_port_digest: digest(13),
            circuit_route_digest: digest(14),
            abi_digest: digest(15),
            base_digest: digest(16),
            organ_adapter_digest: digest(17),
            state_schema_digest: digest(18),
            compatibility_digest: digest(19),
            no_change_baseline_id: id("baseline.no-change"),
            evaluation_id: id("evaluation.cell-split"),
            rollback_predecessor_digest: digest(20),
        }
    }

    #[test]
    fn telemetry_signal_is_deterministic_and_uses_utility_priority() {
        let policy = policy();
        let telemetry = telemetry();
        let first = cell_split_signal_from_telemetry_v1(&telemetry, &policy).expect("signal");
        let second = cell_split_signal_from_telemetry_v1(&telemetry, &policy).expect("signal");
        assert_eq!(first, second);
        assert_eq!(first.trigger, CellSplitProposalTriggerV1::UtilityRegression);
        assert_eq!(first.policy_digest, policy.policy_digest());
        assert_eq!(first.trigger_evidence_digest, telemetry.content_digest());
    }

    #[test]
    fn telemetry_signal_rejects_no_trigger_and_bad_coverage() {
        let policy = policy();
        let mut observation = telemetry();
        observation.baseline_utility_q24 = observation.observed_utility_q24;
        observation.target_task_coverage_ppm = observation.observed_task_coverage_ppm;
        observation.p95_latency_micros = 1;
        observation.resident_bytes = 1;
        assert_eq!(
            cell_split_signal_from_telemetry_v1(&observation, &policy),
            Err(CellSplitPlannerErrorV1::NoTrigger)
        );
        observation.target_task_coverage_ppm = MAX_COVERAGE_PPM_V1 + 1;
        assert_eq!(
            cell_split_signal_from_telemetry_v1(&observation, &policy),
            Err(CellSplitPlannerErrorV1::InvalidTelemetry)
        );
    }

    #[test]
    fn governed_planner_replays_to_a_valid_complete_plan() {
        let policy = policy();
        let telemetry = telemetry();
        let signal = cell_split_signal_from_telemetry_v1(&telemetry, &policy).expect("signal");
        let first =
            CellSplitGovernedPlannerV1::synthesize(&signal, &policy, &context(), &telemetry)
                .expect("plan");
        let second =
            CellSplitGovernedPlannerV1::synthesize(&signal, &policy, &context(), &telemetry)
                .expect("plan");
        assert_eq!(first, second);
        assert_eq!(first.children.len(), 3);
        assert_eq!(first.predecessor_generation.get(), 7);
        assert_eq!(first.successor_generation.get(), 8);
        assert_eq!(first.children[0].child_cell_id, id("cell.child.01"));
        assert_eq!(first.children[2].child_cell_id, id("cell.child.03"));
        assert_eq!(first.inheritance.children[0].base_digest, digest(16));
        assert_ne!(
            first.inheritance.children[0].cell_adapter_digest,
            first.inheritance.children[1].cell_adapter_digest
        );
        assert!(first.evaluation.evaluation_receipt_digest.is_zero());
        assert!(first.validate_plan().is_ok());
    }

    #[test]
    fn planner_rejects_tampered_policy_and_telemetry_binding() {
        let policy = policy();
        let telemetry = telemetry();
        let signal = cell_split_signal_from_telemetry_v1(&telemetry, &policy).expect("signal");
        let mut other = telemetry.clone();
        other.observation_sequence += 1;
        assert_eq!(
            CellSplitGovernedPlannerV1::synthesize(&signal, &policy, &context(), &other),
            Err(CellSplitPlannerErrorV1::Binding("signal policy/telemetry"))
        );
        let mut tampered_policy = policy.clone();
        tampered_policy.child_count = 4;
        assert_eq!(
            CellSplitGovernedPlannerV1::synthesize(
                &signal,
                &tampered_policy,
                &context(),
                &telemetry
            ),
            Err(CellSplitPlannerErrorV1::PolicyDigest)
        );
    }

    struct Source {
        observation: CellSplitTelemetryObservationV1,
    }

    impl CellSplitTelemetrySourceV1 for Source {
        type Error = &'static str;

        fn observe(
            &mut self,
            _parent_cell_id: &StableId,
        ) -> Result<CellSplitTelemetryObservationV1, Self::Error> {
            Ok(self.observation.clone())
        }
    }

    #[test]
    fn telemetry_source_adapter_binds_parent() {
        let policy = policy();
        let mut source = Source {
            observation: telemetry(),
        };
        let signal =
            collect_cell_split_signal_v1(&mut source, &id("cell.parent"), &policy).expect("signal");
        assert_eq!(signal.parent_cell_id, id("cell.parent"));
        assert_eq!(
            collect_cell_split_signal_v1(&mut source, &id("cell.other"), &policy),
            Err(CellSplitPlannerErrorV1::Binding("telemetry parent"))
        );
    }
}
