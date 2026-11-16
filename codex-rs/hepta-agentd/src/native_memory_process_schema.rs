//! Closed, pinned startup configuration. No query accepts paths or policies.

use std::path::PathBuf;

use codex_hepta_memory::MemoryCellKeyV1;
use codex_hepta_ndu as ndu;
use codex_hepta_neuron::InhibitoryEdge;
use codex_hepta_neuron::NeuronResourceEnvelopeV1;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;

use crate::NativeMemoryModelConfigV1;
use crate::NativeMemoryShadowProfileV1;
use crate::native_memory_process_trust::FilePin;
use crate::native_memory_process_trust::string;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ProcessDescriptor {
    pub schema: String,
    pub trust_profile: String,
    pub agent_id: String,
    pub spawn_generation: u64,
    pub linux_boot_id: String,
    pub control_socket: PathBuf,
    pub source: SourceDescriptor,
    pub ndu: NduDescriptor,
    pub shadow: ShadowDescriptor,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct SourceDescriptor {
    pub anchor: FilePin,
    pub grant: FilePin,
    pub signer_id: String,
    pub verifying_key: [u8; 32],
    pub lease_id: String,
    pub lease_generation: u64,
    pub key: MemoryCellKeyV1,
    pub claim: FilePin,
    pub model: FilePin,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct NduDescriptor {
    pub root: PathBuf,
    pub journal_sha256: String,
    pub authority_state: PathBuf,
    pub authority_snapshot_sha256: String,
    pub authority_claims_sha256: String,
    pub signer_id: String,
    pub verifying_key: [u8; 32],
    pub feed: FilePin,
    pub feed_distributor_id: String,
    pub feed_verifying_key: [u8; 32],
    pub owner_id: String,
    pub principal_scope_digest: String,
    pub fence_digest: String,
    pub revocation_frontier_digest: String,
    pub policy: PolicyDescriptor,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PolicyDescriptor {
    pub profile_id: String,
    pub axis_registry_digest: String,
    pub normalization_manifest_digest: String,
    pub dimensions: Vec<(String, Direction)>,
    pub risk_ceilings: Vec<(String, i64)>,
    pub resource_ceilings: Vec<(String, i64)>,
    pub required_organs: Vec<String>,
    pub evaluation_id: String,
    pub utility_rules: Vec<(String, Aggregation)>,
    pub risk_rules: Vec<(String, Aggregation)>,
    pub resource_rules: Vec<(String, Aggregation)>,
    pub uncertainty_rules: Vec<(String, Aggregation)>,
    pub pareto_tolerances_q32: Vec<(String, i64)>,
    pub scalarization: Option<(String, Vec<(String, i64)>)>,
}

#[derive(Clone, Copy, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum Direction {
    Maximize,
    Minimize,
}

#[derive(Clone, Copy, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum Aggregation {
    Sum,
    Maximum,
    Minimum,
    RequireEqual,
}

impl PolicyDescriptor {
    pub fn build(&self) -> Result<ndu::NduProductionPolicyV1, String> {
        let limits = |values: &[(String, i64)]| -> Result<Vec<ndu::AxisLimit>, String> {
            values
                .iter()
                .map(|(axis, raw)| {
                    Ok(ndu::AxisLimit {
                        axis: id(axis)?,
                        maximum: FixedQ32::from_raw(*raw),
                    })
                })
                .collect()
        };
        let rules =
            |values: &[(String, Aggregation)]| -> Result<Vec<ndu::AxisAggregationRule>, String> {
                values
                    .iter()
                    .map(|(axis, operator)| {
                        Ok(ndu::AxisAggregationRule {
                            axis: id(axis)?,
                            operator: match operator {
                                Aggregation::Sum => ndu::AggregationOperator::Sum,
                                Aggregation::Maximum => ndu::AggregationOperator::Maximum,
                                Aggregation::Minimum => ndu::AggregationOperator::Minimum,
                                Aggregation::RequireEqual => ndu::AggregationOperator::RequireEqual,
                            },
                        })
                    })
                    .collect()
            };
        Ok(ndu::NduProductionPolicyV1 {
            utility_profile: ndu::UtilityProfile {
                profile_id: id(&self.profile_id)?,
                axis_registry_digest: digest(&self.axis_registry_digest)?,
                normalization_manifest_digest: digest(&self.normalization_manifest_digest)?,
                dimensions: self
                    .dimensions
                    .iter()
                    .map(|(axis, direction)| {
                        Ok((
                            id(axis)?,
                            match direction {
                                Direction::Maximize => ndu::AxisDirection::Maximize,
                                Direction::Minimize => ndu::AxisDirection::Minimize,
                            },
                        ))
                    })
                    .collect::<Result<_, String>>()?,
                risk_ceilings: limits(&self.risk_ceilings)?,
                resource_ceilings: limits(&self.resource_ceilings)?,
                required_organs: ndu::RequiredOrganSet {
                    organ_ids: self
                        .required_organs
                        .iter()
                        .map(|v| id(v))
                        .collect::<Result<_, _>>()?,
                },
            },
            evaluation_policy: ndu::EvaluationPolicyV1 {
                policy_id: id(&self.evaluation_id)?,
                utility_rules: rules(&self.utility_rules)?,
                risk_rules: rules(&self.risk_rules)?,
                resource_rules: rules(&self.resource_rules)?,
                uncertainty_rules: rules(&self.uncertainty_rules)?,
                pareto_absolute_tolerances: values(&self.pareto_tolerances_q32)?,
            },
            scalarization: self
                .scalarization
                .as_ref()
                .map(|(name, weights)| {
                    Ok::<_, String>(ndu::ScalarizationProfile {
                        profile_id: id(name)?,
                        weights: values(weights)?,
                    })
                })
                .transpose()?,
        })
    }
}

fn values(input: &[(String, i64)]) -> Result<Vec<ndu::AxisValue>, String> {
    input
        .iter()
        .map(|(axis, raw)| {
            Ok(ndu::AxisValue {
                axis: id(axis)?,
                value: FixedQ32::from_raw(*raw),
            })
        })
        .collect()
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ShadowDescriptor {
    pub cell_id: String,
    pub journal: PathBuf,
    pub witness: PathBuf,
    pub recover: bool,
    pub max_records: usize,
    pub sparse: SparseDescriptor,
    pub limits: LimitsDescriptor,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct SparseDescriptor {
    pub normalization_digest: String,
    pub top_k: usize,
    pub temporal_decay_q24: i64,
    pub inhibition_gain_q24: i64,
    pub inhibition: Vec<(usize, usize, i64)>,
    pub activity_decay_q24: i64,
    pub target_activity_q24: i64,
    pub threshold_rate_q24: i64,
    pub threshold_min_q24: i64,
    pub threshold_max_q24: i64,
    pub eligibility_decay_q24: i64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct LimitsDescriptor {
    pub p95_latency_micros: u64,
    pub p99_latency_micros: u64,
    pub transient_allocation_bytes: u64,
    pub checkpoint_bytes: u64,
    pub write_amplification_ppm: u32,
}

impl ShadowDescriptor {
    pub fn profile(
        &self,
        model: &NativeMemoryModelConfigV1,
    ) -> Result<NativeMemoryShadowProfileV1, String> {
        if !(1..=4096).contains(&self.max_records) || self.inhibition_too_large() {
            return Err("bounded shadow configuration required".into());
        }
        let sparse = &self.sparse;
        Ok(NativeMemoryShadowProfileV1 {
            cell_id: id(&self.cell_id)?,
            sparse: SparseConfig {
                model_digest: Digest32::of_bytes(crate::native_memory_types::HEAD),
                normalization_digest: digest(&sparse.normalization_digest)?,
                generation: Generation::new(model.generation).map_err(string)?,
                width: model.output_width,
                top_k: sparse.top_k,
                temporal_decay_q24: sparse.temporal_decay_q24,
                inhibition_gain_q24: sparse.inhibition_gain_q24,
                inhibition: sparse
                    .inhibition
                    .iter()
                    .map(|(source, target, weight)| InhibitoryEdge {
                        source: *source,
                        target: *target,
                        weight_q24: *weight,
                    })
                    .collect(),
                activity_decay_q24: sparse.activity_decay_q24,
                target_activity_q24: sparse.target_activity_q24,
                threshold_rate_q24: sparse.threshold_rate_q24,
                threshold_min_q24: sparse.threshold_min_q24,
                threshold_max_q24: sparse.threshold_max_q24,
                eligibility_decay_q24: sparse.eligibility_decay_q24,
            },
            limits: NeuronResourceEnvelopeV1 {
                p95_latency_micros: self.limits.p95_latency_micros,
                p99_latency_micros: self.limits.p99_latency_micros,
                transient_allocation_bytes: self.limits.transient_allocation_bytes,
                checkpoint_bytes: self.limits.checkpoint_bytes,
                write_amplification_ppm: self.limits.write_amplification_ppm,
            },
            max_records: self.max_records,
        })
    }

    fn inhibition_too_large(&self) -> bool {
        self.sparse.inhibition.len() > 1024
    }
}

pub(crate) fn id(value: &str) -> Result<StableId, String> {
    StableId::new(value).map_err(string)
}
pub(crate) fn digest(value: &str) -> Result<Digest32, String> {
    crate::native_memory_types::parse_digest(value)
}
