//! Canonical full policy preimage, with no authority or original seal decoder.

use codex_hepta_intelligence_eval::ProductEvaluationPolicyV2;

use super::Arm;
use super::DOMAIN;
use super::Error;
use super::OriginalCircuitOnPolicyComparisonPolicyV2;
use super::OriginalCircuitOnPolicyEvaluationPolicyV2;
use super::Pair;
use super::codec::MAX_POLICY_BYTES;
use super::codec::Read;
use super::codec::put_bytes;
use super::codec::put_id;
use crate::CellCostCoverageV1;
use crate::CellParameterCapacityV1;
use crate::CellRequiredCostMetricV1;
use crate::CellSelectiveUpdateV1;
use crate::CellTrainingBudgetV1;

pub(super) fn encode(policy: &OriginalCircuitOnPolicyEvaluationPolicyV2) -> Result<Vec<u8>, Error> {
    let mut out = DOMAIN.to_vec();
    for digest in [policy.legacy_rule, policy.task, policy.ledger, policy.baseline] {
        out.extend_from_slice(digest.as_array());
    }
    put_id(&mut out, &policy.snapshot);
    let product = codex_hepta_intelligence_eval::ProductEvaluationPolicyV2::canonical_commitment_bytes(&policy.product)
        .map_err(|_| Error::Binding("complete fixed Product policy encoding"))?;
    put_bytes(&mut out, &product);
    let value = &policy.comparison;
    for count in [
        value.capacity.total_parameters,
        value.capacity.trainable_parameters,
        value.capacity.maximum_active_parameters,
        value.cumulative.examples_seen,
        value.cumulative.optimizer_steps,
        value.cumulative.parameter_updates,
        value.cumulative.compute_units,
        value.selective_update.maximum_parameters_per_step,
    ] {
        out.extend_from_slice(&count.to_be_bytes());
    }
    for digest in [
        value.cumulative.compute_unit_contract,
        value.selective_update.policy_digest,
        value.selective_update.eligibility_digest,
        value.selective_update.schedule_digest,
        value.baseline_training_receipt_digest,
        value.cost_coverage.metering_contract_digest,
    ] {
        out.extend_from_slice(&digest);
    }
    out.extend_from_slice(&(value.cost_coverage.required_metrics.len() as u64).to_be_bytes());
    for metric in &value.cost_coverage.required_metrics {
        out.push(match metric {
            CellRequiredCostMetricV1::Wall => 0,
            CellRequiredCostMetricV1::Cpu => 1,
            CellRequiredCostMetricV1::Energy => 2,
            CellRequiredCostMetricV1::StorageRead => 3,
            CellRequiredCostMetricV1::StorageWrite => 4,
            CellRequiredCostMetricV1::StorageRetention => 5,
            CellRequiredCostMetricV1::Communication => 6,
        });
    }
    out.extend_from_slice(&(policy.pairs.len() as u64).to_be_bytes());
    for pair in &policy.pairs {
        put_id(&mut out, &pair.id);
        out.extend_from_slice(pair.input.as_array());
        out.extend_from_slice(pair.protocol.as_array());
        for arm in [&pair.candidate, &pair.baseline] {
            for id in [&arm.decision, &arm.principal, &arm.episode, &arm.run] {
                put_id(&mut out, id);
            }
        }
    }
    if out.len() > MAX_POLICY_BYTES {
        return Err(Error::Binding("bounded full policy declaration before B"));
    }
    Ok(out)
}

pub(super) fn decode(bytes: &[u8]) -> Result<OriginalCircuitOnPolicyEvaluationPolicyV2, Error> {
    let mut read = Read::new(bytes)?;
    read.literal(DOMAIN)?;
    let legacy_rule = read.digest()?;
    let task = read.digest()?;
    let ledger = read.digest()?;
    let baseline = read.digest()?;
    let snapshot = read.id()?;
    let product = ProductEvaluationPolicyV2::from_canonical_commitment_bytes(read.bytes()?)
        .map_err(|_| Error::Binding("strict original Product policy metadata"))?;
    let capacity = CellParameterCapacityV1 {
        total_parameters: read.u64()?,
        trainable_parameters: read.u64()?,
        maximum_active_parameters: read.u64()?,
    };
    let examples_seen = read.u64()?;
    let optimizer_steps = read.u64()?;
    let parameter_updates = read.u64()?;
    let compute_units = read.u64()?;
    let maximum_parameters_per_step = read.u64()?;
    let cumulative = CellTrainingBudgetV1 {
        examples_seen,
        optimizer_steps,
        parameter_updates,
        compute_units,
        compute_unit_contract: read.array()?,
    };
    let selective_update = CellSelectiveUpdateV1 {
        maximum_parameters_per_step,
        policy_digest: read.array()?,
        eligibility_digest: read.array()?,
        schedule_digest: read.array()?,
    };
    let baseline_training_receipt_digest = read.array()?;
    let metering_contract_digest = read.array()?;
    let mut required_metrics = Vec::new();
    for _ in 0..read.count(7)? {
        required_metrics.push(match read.u8()? {
            0 => CellRequiredCostMetricV1::Wall,
            1 => CellRequiredCostMetricV1::Cpu,
            2 => CellRequiredCostMetricV1::Energy,
            3 => CellRequiredCostMetricV1::StorageRead,
            4 => CellRequiredCostMetricV1::StorageWrite,
            5 => CellRequiredCostMetricV1::StorageRetention,
            6 => CellRequiredCostMetricV1::Communication,
            _ => return Err(Error::Binding("original cost coverage metric")),
        });
    }
    let comparison = OriginalCircuitOnPolicyComparisonPolicyV2 {
        capacity, cumulative, selective_update, baseline_training_receipt_digest,
        cost_coverage: CellCostCoverageV1 { metering_contract_digest, required_metrics },
    };
    let mut pairs = Vec::new();
    for _ in 0..read.count(31)? {
        let id = read.id()?;
        let input = read.digest()?;
        let protocol = read.digest()?;
        let mut arm = || -> Result<Arm, Error> {
            Ok(Arm { decision: read.id()?, principal: read.id()?, episode: read.id()?, run: read.id()? })
        };
        let candidate = arm()?;
        let baseline = arm()?;
        pairs.push(Pair { id, input, protocol, candidate, baseline });
    }
    read.finish()?;
    Ok(OriginalCircuitOnPolicyEvaluationPolicyV2 {
        legacy_rule, task, snapshot, ledger, product, comparison, baseline, pairs,
    })
}
