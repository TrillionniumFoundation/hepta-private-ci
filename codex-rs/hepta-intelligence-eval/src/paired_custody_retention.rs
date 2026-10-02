//! Actual remeasurement of the same declared, already-public old task batch.
//! The baseline and candidate are run; a source hash alone is not retention.
use crate::AuthenticatedPairedRegistrationV1;
use crate::PairedReviewSourcePlanV1;
use crate::initial_neuron_operational_source::HostResult;
use crate::initial_neuron_operational_source::Source;
use crate::paired_custody_generator::Inputs;
use crate::paired_custody_numeric::Model;
use crate::paired_custody_numeric::{self};
use crate::paired_supervised_host_clock::PairedHostClockV1;
use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use serde::Deserialize;
use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::path::Path;
use std::time::Instant;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Config {
    pub generator: Source,
    pub declared_public_gold: Source,
    pub assignment_contract: Source,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Contract {
    schema: String,
    cost_semantics: String,
    unlearning_semantics: String,
    retention_public_gold_digest: String,
    pairs: Vec<Assignment>,
    withdrawal: crate::paired_custody_withdrawal::Config,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Assignment {
    evaluation_record_digest: String,
    old_record_digest: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Gold {
    schema: String,
    tasks: Vec<Task>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Task {
    source_record_digest: String,
    gold: String,
}

pub(super) fn measure(
    config: &Config,
    scorer: &Source,
    models: [&Model; 2],
    directory: &Path,
    main: &Inputs,
    trust: &ActivatedLearningTrustV1,
    registration: &AuthenticatedPairedRegistrationV1,
    deadline: Instant,
) -> HostResult<(BTreeMap<Digest32, [FixedQ32; 2]>, Digest32)> {
    let mut clock = PairedHostClockV1::system();
    let prepared = prepare(
        config,
        main,
        trust,
        clock.sample_registered(trust, registration)?,
    )?;
    let Prepared {
        original,
        labels,
        assignments,
        gold_bytes,
        contract_bytes,
    } = prepared;
    let mut values: BTreeMap<Digest32, [FixedQ32; 2]> = assignments
        .keys()
        .map(|id| (*id, [FixedQ32::ZERO; 2]))
        .collect();
    let mut trace = b"hepta.eval.paired-supervised.actual-public-retention.v1".to_vec();
    trace.extend_from_slice(Digest32::of_bytes(&gold_bytes).as_array());
    trace.extend_from_slice(Digest32::of_bytes(&contract_bytes).as_array());
    trace.extend_from_slice(original.plan.frozen_plan().plan_digest.as_array());
    trace.extend_from_slice(&original.generator.signing_bytes());
    trace.extend_from_slice(&original.generator.signature);
    for (index, model) in models.iter().enumerate() {
        let operation = directory.join(if index == 0 {
            "retention-candidate"
        } else {
            "retention-baseline"
        });
        if !operation.exists() {
            std::fs::create_dir(&operation)?;
            std::fs::set_permissions(
                &operation,
                std::os::unix::fs::PermissionsExt::from_mode(0o700),
            )?;
            std::fs::File::open(directory)?.sync_all()?;
        }
        let inputs = original
            .rows
            .values()
            .map(|row| row[index].clone())
            .collect::<Vec<_>>();
        clock.sample_registered(trust, registration)?;
        let execution =
            paired_custody_numeric::execute(scorer, model, &inputs, &operation, deadline)?;
        clock.sample_registered(trust, registration)?;
        for ((bytes, observed), id) in execution.rows.iter().zip(original.rows.keys()) {
            if observed.class() > 1 {
                return Err(
                    "retention observed a class outside the registered binary alphabet".into(),
                );
            }
            let new_id = assignments
                .iter()
                .find_map(|(new, old)| (old == id).then_some(new))
                .ok_or("original retention assignment")?;
            values.get_mut(new_id).ok_or("original new source")?[index] =
                if observed.class() == labels[id] {
                    FixedQ32::ONE
                } else {
                    FixedQ32::ZERO
                };
            trace.extend_from_slice(id.as_array());
            trace.extend_from_slice(Digest32::of_bytes(bytes).as_array());
        }
        trace.extend_from_slice(model.manifest.digest.parse::<Digest32>()?.as_array());
        trace.extend_from_slice(model.weights.digest.parse::<Digest32>()?.as_array());
    }
    if config.declared_public_gold.read(4 * 1024 * 1024)? != gold_bytes
        || config.assignment_contract.read(128 * 1024)? != contract_bytes
    {
        return Err("declared old public retention source changed during remeasurement".into());
    }
    clock.sample_registered(trust, registration)?;
    Ok((values, Digest32::of_bytes(&trace)))
}

struct Prepared {
    original: Inputs,
    labels: BTreeMap<Digest32, usize>,
    assignments: BTreeMap<Digest32, Digest32>,
    gold_bytes: Vec<u8>,
    contract_bytes: Vec<u8>,
}

pub(super) fn preflight(
    config: &Config,
    main: &Inputs,
    trust: &ActivatedLearningTrustV1,
    now: u64,
) -> HostResult<()> {
    prepare(config, main, trust, now).map(|_| ())
}

fn prepare(
    config: &Config,
    main: &Inputs,
    trust: &ActivatedLearningTrustV1,
    now: u64,
) -> HostResult<Prepared> {
    let original = Inputs::read(&config.generator, trust, now)?;
    if original.plan.policy.output_alphabet != main.plan.policy.output_alphabet
        || original.plan.runtime.deployed_baseline_digest
            != main.plan.runtime.deployed_baseline_digest
        || original.plan.runtime.baseline_runtime_digest
            != main.plan.runtime.baseline_runtime_digest
    {
        return Err(
            "original old-task source changed its class semantics or deployed comparator".into(),
        );
    }
    let contract_bytes = config.assignment_contract.read(128 * 1024)?;
    let contract: Contract = serde_json::from_slice(&contract_bytes)?;
    if contract.schema != "hepta.paired-public-measurement-contract.v1"
        || contract.cost_semantics != "original-scorer-monotonic-micros-derived-q32-milliseconds"
        || contract.unlearning_semantics
            != "original-ledger-withdrawal-and-current-delivery-denial-only"
        || main.original_contract != config.assignment_contract.digest.parse::<Digest32>()?
        || contract.retention_public_gold_digest != config.declared_public_gold.digest
    {
        return Err("retention assignment/cost/withdrawal definitions were not signed in original G contract".into());
    }
    crate::paired_custody_withdrawal::bind(
        &contract.withdrawal,
        &config.assignment_contract,
        &main.source,
    )?;
    let gold_bytes = config.declared_public_gold.read(4 * 1024 * 1024)?;
    let gold: Gold = serde_json::from_slice(&gold_bytes)?;
    if gold.schema != "hepta.public-seen-retention-gold.v1"
        || gold.tasks.is_empty()
        || gold.tasks.len() > 2048
    {
        return Err("retention requires a bounded predeclared already-public task cohort".into());
    }
    let mut labels = BTreeMap::new();
    for task in gold.tasks {
        let label = match task.gold.as_str() {
            "SUPPORT" => 0,
            "CONTRADICT" => 1,
            _ => return Err("declared retention binary policy".into()),
        };
        if labels
            .insert(task.source_record_digest.parse::<Digest32>()?, label)
            .is_some()
        {
            return Err("duplicate original retention task".into());
        }
    }
    if labels.len() != original.rows.len()
        || original.rows.keys().any(|id| !labels.contains_key(id))
    {
        return Err("retention must remeasure the same complete declared old task cohort".into());
    }
    let assignments = assignments(&main.source, &original.source, &contract.pairs)?;
    Ok(Prepared {
        original,
        labels,
        assignments,
        gold_bytes,
        contract_bytes,
    })
}

// A per-task old/new bijection makes the original paired estimator's sample
// count real. Old source dependencies enter the same frozen cluster graph.
fn assignments(
    main: &PairedReviewSourcePlanV1,
    old: &PairedReviewSourcePlanV1,
    pairs: &[Assignment],
) -> HostResult<BTreeMap<Digest32, Digest32>> {
    let main_ids = main
        .tasks
        .iter()
        .map(|task| task.source_record_digest)
        .collect::<BTreeSet<_>>();
    let old_ids = old
        .tasks
        .iter()
        .map(|task| task.source_record_digest)
        .collect::<BTreeSet<_>>();
    let mut result = BTreeMap::new();
    let mut assigned_old = BTreeSet::new();
    for pair in pairs {
        let new_id = pair.evaluation_record_digest.parse::<Digest32>()?;
        let old_id = pair.old_record_digest.parse::<Digest32>()?;
        if !main_ids.contains(&new_id)
            || !old_ids.contains(&old_id)
            || result.insert(new_id, old_id).is_some()
            || !assigned_old.insert(old_id)
        {
            return Err(
                "retention requires a predeclared bijection, never duplicated old-task averages"
                    .into(),
            );
        }
        let evaluation = main
            .source_records
            .iter()
            .find(|record| record.source_record_digest == new_id)
            .ok_or("original evaluation source")?;
        let old_record = old
            .source_records
            .iter()
            .find(|record| record.source_record_digest == old_id)
            .ok_or("original old source")?;
        if new_id != old_id
            && (!main.source_records.contains(old_record)
                || old_record.dependency_ids.is_empty()
                || old_record
                    .dependency_ids
                    .iter()
                    .any(|id| !evaluation.dependency_ids.contains(id)))
        {
            return Err(
                "paired dependency clusters do not include the mapped old-task source dependencies"
                    .into(),
            );
        }
    }
    if result.len() != main_ids.len() || assigned_old != old_ids {
        return Err(
            "all and only evaluation/old-retention tasks must be preregistered once".into(),
        );
    }
    Ok(result)
}

#[cfg(test)]
#[path = "paired_custody_retention_tests.rs"]
mod tests;
