//! Proposal-only, legacy Plasticity split admission.
//!
//! [`CellSplitV1`](codex_hepta_types::CellSplitV1) describes topology and
//! state migration.  This module adds the role-side evidence join that is
//! required before a Plasticity candidate can be considered by an independent
//! evaluator. New role types must use [`crate::RoleSplitMetricAdmissionV1`],
//! which binds every metric dynamically instead of reusing the historical
//! retention/forgetting field names. It deliberately does not publish an
//! artifact, change a route, advance a generation, or install an online
//! update.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::CellRoleV1;
use codex_hepta_types::CellSplitV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::role_gates::CellRoleGateErrorV1;
use crate::role_gates::CellRoleMetricKindV1;
use crate::role_gates::CellRoleMetricProfileV1;
use crate::role_gates::CellRoleMetricReceiptV1;

pub const ROLE_SPLIT_ADMISSION_SCHEMA_V1: &str = "hepta.cell-role.role-split-admission.v1";

/// Evidence required to bind a role-specific split to a candidate artifact
/// and to the independent role metrics.  All fields are digests or stable
/// identifiers owned by external artifact/evaluation owners; this value does
/// not claim that any of them has been durably published.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RoleSplitAdmissionEvidenceV1 {
    pub role: CellRoleV1,
    pub candidate_artifact_digest: Digest32,
    pub candidate_artifact_receipt_digest: Digest32,
    pub candidate_qualification_digest: Digest32,
    pub trust_region_digest: Digest32,
    pub rollback_predecessor_digest: Digest32,
    pub no_change_baseline_digest: Digest32,
    pub retention_receipt_digest: Digest32,
    pub forgetting_receipt_digest: Digest32,
    pub rollback_receipt_digest: Digest32,
    pub resource_receipt_digest: Digest32,
    pub future_window_digest: Digest32,
    pub metric_profile_digest: Digest32,
    pub metric_receipt_digest: Digest32,
    pub proposer_id: StableId,
    pub evaluator_id: StableId,
    pub authority: AuthorityPosture,
}

/// Authority-free result of role-specific split admission.  The receipt is a
/// replayable binding only.  Selection, canary, publication, route cutover,
/// retention, quarantine and rollback remain external owner operations.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RoleSplitAdmissionReceiptV1 {
    pub schema: &'static str,
    pub role: CellRoleV1,
    pub parent_cell_id: StableId,
    pub predecessor_generation: Generation,
    pub successor_generation: Generation,
    pub split_subject_digest: Digest32,
    pub evidence: RoleSplitAdmissionEvidenceV1,
    pub admission_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RoleSplitAdmissionErrorV1 {
    Split(codex_hepta_types::CellSplitContractErrorV1),
    Gate(CellRoleGateErrorV1),
    EmptyId(&'static str),
    EmptyDigest(&'static str),
    RoleMismatch,
    ProposerMismatch,
    EvaluatorMismatch,
    GenerationMismatch,
    CandidateEqualsParent,
    BaselineMismatch,
    FutureWindowMismatch,
    ProfileDigestMismatch,
    MetricReceiptDigestMismatch,
    MetricObservationMismatch(CellRoleMetricKindV1),
    RollbackMismatch,
    AuthorityGranted,
    AdmissionDigestMismatch,
}

impl fmt::Display for RoleSplitAdmissionErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for RoleSplitAdmissionErrorV1 {}

impl From<codex_hepta_types::CellSplitContractErrorV1> for RoleSplitAdmissionErrorV1 {
    fn from(value: codex_hepta_types::CellSplitContractErrorV1) -> Self {
        Self::Split(value)
    }
}

impl From<CellRoleGateErrorV1> for RoleSplitAdmissionErrorV1 {
    fn from(value: CellRoleGateErrorV1) -> Self {
        Self::Gate(value)
    }
}

pub struct RoleSplitAdmissionV1;

impl RoleSplitAdmissionV1 {
    /// Join a complete semantic split and role metrics into an immutable
    /// admission receipt.  This is intentionally a preparation step: no
    /// artifact or state owner is called and no authority is returned.
    pub fn admit(
        split: &CellSplitV1,
        evidence: RoleSplitAdmissionEvidenceV1,
        profile: &CellRoleMetricProfileV1,
        metrics: &CellRoleMetricReceiptV1,
    ) -> Result<RoleSplitAdmissionReceiptV1, RoleSplitAdmissionErrorV1> {
        split.validate()?;
        validate_evidence(split, &evidence, profile, metrics)?;
        let split_subject_digest = split.evaluation_subject_digest()?;
        let mut receipt = RoleSplitAdmissionReceiptV1 {
            schema: ROLE_SPLIT_ADMISSION_SCHEMA_V1,
            role: evidence.role,
            parent_cell_id: split.parent_cell_id.clone(),
            predecessor_generation: split.predecessor_generation,
            successor_generation: split.successor_generation,
            split_subject_digest,
            evidence,
            admission_digest: Digest32::ZERO,
        };
        receipt.admission_digest = digest_receipt(&receipt);
        Ok(receipt)
    }

    pub fn verify(
        split: &CellSplitV1,
        receipt: &RoleSplitAdmissionReceiptV1,
        profile: &CellRoleMetricProfileV1,
        metrics: &CellRoleMetricReceiptV1,
    ) -> Result<(), RoleSplitAdmissionErrorV1> {
        if receipt.schema != ROLE_SPLIT_ADMISSION_SCHEMA_V1
            || receipt.admission_digest.is_zero()
            || receipt.admission_digest != digest_receipt(receipt)
        {
            return Err(RoleSplitAdmissionErrorV1::AdmissionDigestMismatch);
        }
        if receipt.parent_cell_id != split.parent_cell_id
            || receipt.predecessor_generation != split.predecessor_generation
            || receipt.successor_generation != split.successor_generation
        {
            return Err(RoleSplitAdmissionErrorV1::GenerationMismatch);
        }
        if receipt.split_subject_digest != split.evaluation_subject_digest()? {
            return Err(RoleSplitAdmissionErrorV1::AdmissionDigestMismatch);
        }
        validate_evidence(split, &receipt.evidence, profile, metrics)
    }
}

fn validate_evidence(
    split: &CellSplitV1,
    evidence: &RoleSplitAdmissionEvidenceV1,
    profile: &CellRoleMetricProfileV1,
    metrics: &CellRoleMetricReceiptV1,
) -> Result<(), RoleSplitAdmissionErrorV1> {
    if evidence.role != CellRoleV1::Plasticity {
        return Err(RoleSplitAdmissionErrorV1::RoleMismatch);
    }
    for (label, id) in [
        ("proposer", &evidence.proposer_id),
        ("evaluator", &evidence.evaluator_id),
    ] {
        if id.as_str().is_empty() {
            return Err(RoleSplitAdmissionErrorV1::EmptyId(label));
        }
    }
    for (label, digest) in [
        ("candidate artifact", evidence.candidate_artifact_digest),
        (
            "candidate artifact receipt",
            evidence.candidate_artifact_receipt_digest,
        ),
        (
            "candidate qualification",
            evidence.candidate_qualification_digest,
        ),
        ("trust region", evidence.trust_region_digest),
        ("rollback predecessor", evidence.rollback_predecessor_digest),
        ("no-change baseline", evidence.no_change_baseline_digest),
        ("retention", evidence.retention_receipt_digest),
        ("forgetting", evidence.forgetting_receipt_digest),
        ("rollback", evidence.rollback_receipt_digest),
        ("resource", evidence.resource_receipt_digest),
        ("future window", evidence.future_window_digest),
        ("metric profile", evidence.metric_profile_digest),
        ("metric receipt", evidence.metric_receipt_digest),
    ] {
        if digest.is_zero() {
            return Err(RoleSplitAdmissionErrorV1::EmptyDigest(label));
        }
    }
    if evidence.authority.grants_any() {
        return Err(RoleSplitAdmissionErrorV1::AuthorityGranted);
    }
    if evidence.proposer_id != split.proposer_id {
        return Err(RoleSplitAdmissionErrorV1::ProposerMismatch);
    }
    if evidence.evaluator_id != split.evaluator_id
        || evidence.evaluator_id != split.evaluation.evaluator_id
    {
        return Err(RoleSplitAdmissionErrorV1::EvaluatorMismatch);
    }
    if evidence.proposer_id == evidence.evaluator_id {
        return Err(RoleSplitAdmissionErrorV1::EvaluatorMismatch);
    }
    if evidence.rollback_predecessor_digest != split.rollback_predecessor_digest {
        return Err(RoleSplitAdmissionErrorV1::RollbackMismatch);
    }
    if evidence.candidate_artifact_digest == split.parent_bundle_digest {
        return Err(RoleSplitAdmissionErrorV1::CandidateEqualsParent);
    }
    if profile.role != evidence.role || metrics.role != evidence.role {
        return Err(RoleSplitAdmissionErrorV1::RoleMismatch);
    }
    profile.validate()?;
    if evidence.metric_profile_digest != profile.content_digest()? {
        return Err(RoleSplitAdmissionErrorV1::ProfileDigestMismatch);
    }
    if evidence.no_change_baseline_digest != profile.no_change_baseline_digest {
        return Err(RoleSplitAdmissionErrorV1::BaselineMismatch);
    }
    if evidence.future_window_digest != profile.future_window_digest
        || metrics.evaluation_window_digest != evidence.future_window_digest
    {
        return Err(RoleSplitAdmissionErrorV1::FutureWindowMismatch);
    }
    if metrics.proposer_id != evidence.proposer_id || metrics.evaluator_id != evidence.evaluator_id
    {
        return Err(RoleSplitAdmissionErrorV1::EvaluatorMismatch);
    }
    if metrics.cell_id != split.parent_cell_id || metrics.generation != split.successor_generation {
        return Err(RoleSplitAdmissionErrorV1::GenerationMismatch);
    }
    if evidence.metric_receipt_digest != metrics.content_digest(profile)? {
        return Err(RoleSplitAdmissionErrorV1::MetricReceiptDigestMismatch);
    }
    let required = [
        (
            CellRoleMetricKindV1::PlasticityRetention,
            evidence.retention_receipt_digest,
        ),
        (
            CellRoleMetricKindV1::PlasticityForgetting,
            evidence.forgetting_receipt_digest,
        ),
        (
            CellRoleMetricKindV1::PlasticityRollback,
            evidence.rollback_receipt_digest,
        ),
        (
            CellRoleMetricKindV1::PlasticityResourceCost,
            evidence.resource_receipt_digest,
        ),
    ];
    for (kind, expected_observation) in required {
        let metric = metrics
            .metrics
            .iter()
            .find(|metric| metric.kind == kind)
            .ok_or(RoleSplitAdmissionErrorV1::Gate(
                CellRoleGateErrorV1::MissingMetric(kind),
            ))?;
        if metric.observation_digest != expected_observation {
            return Err(RoleSplitAdmissionErrorV1::MetricObservationMismatch(kind));
        }
    }
    Ok(())
}

fn digest_receipt(receipt: &RoleSplitAdmissionReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.cell-role.role-split-admission.v1".to_vec();
    bytes.push(receipt.role.tag());
    push_id(&mut bytes, &receipt.parent_cell_id);
    bytes.extend_from_slice(&receipt.predecessor_generation.get().to_be_bytes());
    bytes.extend_from_slice(&receipt.successor_generation.get().to_be_bytes());
    bytes.extend_from_slice(receipt.split_subject_digest.as_array());
    let evidence = &receipt.evidence;
    for digest in [
        evidence.candidate_artifact_digest,
        evidence.candidate_artifact_receipt_digest,
        evidence.candidate_qualification_digest,
        evidence.trust_region_digest,
        evidence.rollback_predecessor_digest,
        evidence.no_change_baseline_digest,
        evidence.retention_receipt_digest,
        evidence.forgetting_receipt_digest,
        evidence.rollback_receipt_digest,
        evidence.resource_receipt_digest,
        evidence.future_window_digest,
        evidence.metric_profile_digest,
        evidence.metric_receipt_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_id(&mut bytes, &evidence.proposer_id);
    push_id(&mut bytes, &evidence.evaluator_id);
    bytes.push(evidence.authority.flags().wire_mask());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u32).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::CellRoleMetricV1;
    use codex_hepta_types::CellBundleBindingV1;
    use codex_hepta_types::CellBundleInheritanceV1;
    use codex_hepta_types::CellCachePolicyV1;
    use codex_hepta_types::CellChildPortBindingV1;
    use codex_hepta_types::CellChildV1;
    use codex_hepta_types::CellInFlightPolicyV1;
    use codex_hepta_types::CellParentDispositionV1;
    use codex_hepta_types::CellParentRetirementPlanV1;
    use codex_hepta_types::CellPortCompatibilityV1;
    use codex_hepta_types::CellResourceDeltaV1;
    use codex_hepta_types::CellRouteModeV1;
    use codex_hepta_types::CellSplitEvaluationBindingV1;
    use codex_hepta_types::CellStateSplitPlanV1;
    use codex_hepta_types::CellStateTransformKindV1;
    use codex_hepta_types::CellStateTransformV1;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn digest(seed: u8) -> Digest32 {
        Digest32::from_array([seed; 32])
    }

    fn transform(seed: u8, kind: CellStateTransformKindV1) -> CellStateTransformV1 {
        CellStateTransformV1 {
            kind,
            source_schema_digest: digest(seed),
            target_schema_digest: digest(seed + 1),
            mapping_digest: match kind {
                CellStateTransformKindV1::Partition | CellStateTransformKindV1::Custom => {
                    digest(seed + 2)
                }
                CellStateTransformKindV1::Copy | CellStateTransformKindV1::Reset => Digest32::ZERO,
            },
        }
    }

    fn split() -> CellSplitV1 {
        let children = vec![
            CellChildV1 {
                child_cell_id: id("cell.a"),
                child_generation: Generation::new(8).expect("generation"),
                child_scope_digest: digest(10),
                lineage_digest: digest(17),
                child_definition_digest: digest(11),
                child_bundle_digest: digest(12),
                dataset_partition_digest: digest(13),
                task_objective_digest: digest(14),
                route_predicate_digest: digest(15),
                fallback_route_digest: digest(16),
                route_mode: CellRouteModeV1::Exclusive,
            },
            CellChildV1 {
                child_cell_id: id("cell.b"),
                child_generation: Generation::new(8).expect("generation"),
                child_scope_digest: digest(20),
                lineage_digest: digest(27),
                child_definition_digest: digest(21),
                child_bundle_digest: digest(22),
                dataset_partition_digest: digest(23),
                task_objective_digest: digest(24),
                route_predicate_digest: digest(25),
                fallback_route_digest: digest(26),
                route_mode: CellRouteModeV1::Exclusive,
            },
        ];
        let inheritance_children = children
            .iter()
            .enumerate()
            .map(|(index, child)| CellBundleBindingV1 {
                child_cell_id: child.child_cell_id.clone(),
                base_digest: digest(30),
                organ_adapter_digest: digest(40),
                cell_adapter_digest: digest(50 + index as u8),
                head_digest: digest(60 + index as u8),
                compatibility_digest: digest(70 + index as u8),
            })
            .collect();
        let port_children = children
            .iter()
            .enumerate()
            .map(|(index, child)| CellChildPortBindingV1 {
                child_cell_id: child.child_cell_id.clone(),
                input_port_digest: digest(80 + index as u8),
                output_port_digest: digest(90 + index as u8),
                termination_port_digest: digest(100 + index as u8),
                compatibility_digest: digest(110 + index as u8),
            })
            .collect();
        CellSplitV1 {
            split_id: id("split.1"),
            proposer_id: id("proposer"),
            evaluator_id: id("evaluator"),
            parent_cell_id: id("cell.parent"),
            organ_id: id("organ.memory"),
            parent_scope_digest: digest(1),
            predecessor_generation: Generation::new(7).expect("generation"),
            successor_generation: Generation::new(8).expect("generation"),
            parent_definition_digest: digest(2),
            parent_bundle_digest: digest(3),
            children,
            inheritance: CellBundleInheritanceV1 {
                base_mode: codex_hepta_types::CellBundleModeV1::SharedImmutable,
                organ_adapter_mode: codex_hepta_types::CellBundleModeV1::SharedImmutable,
                cell_adapter_mode: codex_hepta_types::CellBundleModeV1::CloneMutable,
                head_mode: codex_hepta_types::CellBundleModeV1::CloneMutable,
                compatibility_digest: digest(4),
                children: inheritance_children,
            },
            state: CellStateSplitPlanV1 {
                recurrent: transform(120, CellStateTransformKindV1::Partition),
                eligibility: transform(123, CellStateTransformKindV1::Partition),
                optimizer: transform(126, CellStateTransformKindV1::Reset),
                cache_policy: CellCachePolicyV1::Revalidate,
                in_flight_policy: CellInFlightPolicyV1::Drain,
                state_evidence_digest: digest(129),
            },
            ports: CellPortCompatibilityV1 {
                parent_input_port_digest: digest(130),
                parent_output_port_digest: digest(131),
                circuit_route_digest: digest(132),
                abi_digest: digest(133),
                children: port_children,
            },
            resources: CellResourceDeltaV1 {
                inference_latency_micros: 100,
                training_steps: 200,
                communication_bytes: 300,
                migration_bytes: 400,
                evaluation_steps: 500,
                resident_bytes: 600,
                checkpoint_bytes: 700,
            },
            retirement: CellParentRetirementPlanV1 {
                disposition: CellParentDispositionV1::Retire,
                drain_watermark_digest: digest(134),
                tombstone_digest: digest(135),
                deletion_lineage_digest: digest(136),
                rollback_digest: digest(137),
            },
            evaluation: CellSplitEvaluationBindingV1 {
                no_change_baseline_id: id("baseline"),
                evaluation_id: id("evaluation"),
                evaluator_id: id("evaluator"),
                evaluation_receipt_digest: digest(138),
                retention_receipt_digest: digest(139),
                negative_transfer_receipt_digest: digest(140),
                cost_receipt_digest: digest(141),
            },
            rollback_predecessor_digest: digest(142),
            evidence_digest: digest(143),
        }
    }

    fn profile() -> CellRoleMetricProfileV1 {
        CellRoleMetricProfileV1::standard_for_role(
            CellRoleV1::Plasticity,
            digest(150),
            digest(151),
            digest(152),
            digest(153),
        )
    }

    fn metrics(split: &CellSplitV1, profile: &CellRoleMetricProfileV1) -> CellRoleMetricReceiptV1 {
        CellRoleMetricReceiptV1 {
            cell_id: split.parent_cell_id.clone(),
            generation: split.successor_generation,
            role: CellRoleV1::Plasticity,
            proposer_id: split.proposer_id.clone(),
            evaluator_id: split.evaluator_id.clone(),
            profile_digest: profile.content_digest().expect("profile"),
            baseline_digest: profile.no_change_baseline_digest,
            evaluation_window_digest: profile.future_window_digest,
            metrics: profile
                .required_metrics
                .iter()
                .map(|kind| CellRoleMetricV1 {
                    kind: *kind,
                    unit: kind.unit(),
                    value: 1,
                    sample_count: 1,
                    observation_digest: digest(kind.tag()),
                })
                .collect(),
            evidence_digest: digest(154),
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    fn evidence(
        split: &CellSplitV1,
        profile: &CellRoleMetricProfileV1,
        metrics: &CellRoleMetricReceiptV1,
    ) -> RoleSplitAdmissionEvidenceV1 {
        let observation = |kind| {
            metrics
                .metrics
                .iter()
                .find(|metric| metric.kind == kind)
                .expect("metric")
                .observation_digest
        };
        RoleSplitAdmissionEvidenceV1 {
            role: CellRoleV1::Plasticity,
            candidate_artifact_digest: digest(160),
            candidate_artifact_receipt_digest: digest(161),
            candidate_qualification_digest: digest(162),
            trust_region_digest: digest(163),
            rollback_predecessor_digest: split.rollback_predecessor_digest,
            no_change_baseline_digest: profile.no_change_baseline_digest,
            retention_receipt_digest: observation(CellRoleMetricKindV1::PlasticityRetention),
            forgetting_receipt_digest: observation(CellRoleMetricKindV1::PlasticityForgetting),
            rollback_receipt_digest: observation(CellRoleMetricKindV1::PlasticityRollback),
            resource_receipt_digest: observation(CellRoleMetricKindV1::PlasticityResourceCost),
            future_window_digest: profile.future_window_digest,
            metric_profile_digest: profile.content_digest().expect("profile"),
            metric_receipt_digest: metrics.content_digest(profile).expect("metrics"),
            proposer_id: split.proposer_id.clone(),
            evaluator_id: split.evaluator_id.clone(),
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    #[test]
    fn admission_binds_candidate_artifact_and_role_metrics_without_activation() {
        let split = split();
        let profile = profile();
        let metrics = metrics(&split, &profile);
        let evidence = evidence(&split, &profile, &metrics);
        let receipt =
            RoleSplitAdmissionV1::admit(&split, evidence, &profile, &metrics).expect("admission");
        RoleSplitAdmissionV1::verify(&split, &receipt, &profile, &metrics).expect("replay");
        assert_eq!(receipt.evidence.authority, AuthorityPosture::DENY_ALL);
        assert_ne!(
            receipt.evidence.candidate_artifact_digest,
            split.parent_bundle_digest
        );
    }

    #[test]
    fn admission_rejects_candidate_parent_reuse() {
        let split = split();
        let profile = profile();
        let metrics = metrics(&split, &profile);
        let mut evidence = evidence(&split, &profile, &metrics);
        evidence.candidate_artifact_digest = split.parent_bundle_digest;
        assert_eq!(
            RoleSplitAdmissionV1::admit(&split, evidence, &profile, &metrics),
            Err(RoleSplitAdmissionErrorV1::CandidateEqualsParent)
        );
    }

    #[test]
    fn admission_rejects_future_window_mismatch() {
        let split = split();
        let profile = profile();
        let metrics = metrics(&split, &profile);
        let mut evidence = evidence(&split, &profile, &metrics);
        evidence.future_window_digest = digest(200);
        assert_eq!(
            RoleSplitAdmissionV1::admit(&split, evidence, &profile, &metrics),
            Err(RoleSplitAdmissionErrorV1::FutureWindowMismatch)
        );
    }
}
