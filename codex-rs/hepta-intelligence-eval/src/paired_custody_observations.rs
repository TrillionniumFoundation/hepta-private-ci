//! Multiple genuine withdrawal observations share the existing owner/CAS spine.
//! Assignment does not create independence: the original G source graph must
//! bind the exact causal events derived by each physically executed inspector.
use crate::PairedReviewSourcePlanV1;
use crate::initial_neuron_operational_source::HostResult;
use crate::initial_neuron_operational_source::Source;
use crate::paired_custody_withdrawal::Inspection;
use crate::paired_custody_withdrawal::ProbeBinding;
use crate::paired_custody_withdrawal::{self as withdrawal};
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::path::Path;
use std::time::Instant;

#[derive(Deserialize)]
#[serde(untagged)]
pub(super) enum Config {
    Original(withdrawal::Config),
    Multiple(Multiple),
}
#[derive(Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub(super) struct Multiple {
    schema: String,
    observations: Vec<Observation>,
    assignments: Vec<Assignment>,
}
#[derive(Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
struct Observation {
    withdrawal_request_digest: String,
    provider: withdrawal::Config,
    causal_dependencies: Vec<String>,
}
#[derive(Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
struct Assignment {
    evaluation_record_digest: String,
    withdrawal_request_digest: String,
}
pub(super) struct Bound {
    observations: Vec<(withdrawal::Config, ProbeBinding, Option<BTreeSet<StableId>>)>,
    assignments: BTreeMap<Digest32, usize>,
}
pub(super) struct Batch {
    observations: Vec<Inspection>,
    pub receipt: Digest32,
}

impl Config {
    pub(super) fn version(&self) -> u8 {
        match self {
            Self::Original(_) => 1,
            Self::Multiple(_) => 2,
        }
    }
    pub(super) fn bind(
        &self,
        contract: &Source,
        source: &PairedReviewSourcePlanV1,
    ) -> HostResult<Bound> {
        match self {
            Self::Original(config) => Ok(Bound {
                observations: vec![(
                    config.clone(),
                    withdrawal::bind(config, contract, source)?,
                    None,
                )],
                assignments: source
                    .tasks
                    .iter()
                    .map(|task| (task.source_record_digest, 0))
                    .collect(),
            }),
            Self::Multiple(config) => {
                let declared: serde_json::Value =
                    serde_json::from_slice(&contract.read(128 * 1024)?)?;
                let declared_config: Multiple =
                    serde_json::from_value(declared["withdrawal"].clone())?;
                if &declared_config != config
                    || declared["schema"] != "hepta.paired-public-measurement-contract.v2"
                {
                    return Err(
                        "original signed G contract changed the V2 provider assignment".into(),
                    );
                }
                let assignments = config.assignment_map(source)?;
                let mut observations = Vec::new();
                let mut owner = None;
                for observation in &config.observations {
                    let binding = withdrawal::descriptor(&observation.provider)?;
                    if binding.probe.schema
                        != "hepta.cpu-neuron.dataset-withdrawal-current-probe.v2"
                        || binding.probe.withdrawal_request.digest
                            != observation.withdrawal_request_digest
                    {
                        return Err("V2 observation must pin the actual original request and current-prefix inspector".into());
                    }
                    let identity = (
                        observation.provider.program.clone(),
                        binding.probe.current_owner.clone(),
                    );
                    if owner.as_ref().is_some_and(|old| old != &identity) {
                        return Err("V2 observations must use the same independently current original owner".into());
                    }
                    owner = Some(identity);
                    observations.push((
                        observation.provider.clone(),
                        binding,
                        Some(observation.dependencies()?),
                    ));
                }
                Ok(Bound {
                    observations,
                    assignments,
                })
            }
        }
    }
}
impl Observation {
    fn dependencies(&self) -> HostResult<BTreeSet<StableId>> {
        let request: Digest32 = self.withdrawal_request_digest.parse()?;
        if request.is_zero()
            || request.to_string() != self.withdrawal_request_digest
            || !(5..=128).contains(&self.causal_dependencies.len())
            || self
                .causal_dependencies
                .windows(2)
                .any(|pair| pair[0] >= pair[1])
        {
            return Err("canonical bounded original causal identities required".into());
        }
        let mut source_count = 0;
        let mut event_count = 0;
        let mut artifact_count = 0;
        let mut support_count = 0;
        let mut input_count = 0;
        let mut dependencies = BTreeSet::new();
        for value in &self.causal_dependencies {
            let rest = value
                .strip_prefix("withdrawal.v2.")
                .ok_or("withdrawal causal namespace")?;
            let (kind, pin) = rest.split_once('.').ok_or("withdrawal causal kind")?;
            match kind {
                "source" => source_count += 1,
                "event" => event_count += 1,
                "artifact" => artifact_count += 1,
                "support" => support_count += 1,
                "input" => input_count += 1,
                _ => return Err("withdrawal causal kind".into()),
            }
            let digest: Digest32 = pin.parse()?;
            if digest.is_zero() || digest.to_string() != pin {
                return Err("canonical original causal digest".into());
            }
            dependencies.insert(StableId::new(value)?);
        }
        if source_count == 0
            || event_count != 1
            || artifact_count == 0
            || support_count == 0
            || input_count == 0
        {
            return Err(
                "actual SourceACK lineage, original numeric input, registration and one withdrawal event required".into(),
            );
        }
        Ok(dependencies)
    }
}
impl Multiple {
    fn assignment_map(
        &self,
        source: &PairedReviewSourcePlanV1,
    ) -> HostResult<BTreeMap<Digest32, usize>> {
        if self.schema != "hepta.paired-withdrawal-observations.v2"
            || self.observations.is_empty()
            || self.observations.len() > 64
            || self.assignments.len() != source.tasks.len()
        {
            return Err("bounded complete V2 observation assignment required".into());
        }
        let mut by_request = BTreeMap::new();
        let mut dependencies = Vec::new();
        for (index, observation) in self.observations.iter().enumerate() {
            dependencies.push(observation.dependencies()?);
            if by_request
                .insert(&observation.withdrawal_request_digest, index)
                .is_some()
            {
                return Err("duplicate original withdrawal observation".into());
            }
        }
        let mut assignments = BTreeMap::new();
        let tasks: BTreeSet<_> = source
            .tasks
            .iter()
            .map(|task| task.source_record_digest)
            .collect();
        for assignment in &self.assignments {
            let task: Digest32 = assignment.evaluation_record_digest.parse()?;
            let index = *by_request
                .get(&assignment.withdrawal_request_digest)
                .ok_or("assignment names absent original observation")?;
            let record = source
                .source_records
                .iter()
                .find(|record| record.source_record_digest == task)
                .ok_or("assignment source record missing")?;
            if !tasks.contains(&task)
                || dependencies[index]
                    .iter()
                    .any(|id| !record.dependency_ids.contains(id))
                || assignments.insert(task, index).is_some()
            {
                return Err(
                    "assignment is duplicated, foreign, or missing original causal graph edges"
                        .into(),
                );
            }
        }
        if assignments.keys().copied().collect::<BTreeSet<_>>() != tasks
            || assignments.values().copied().collect::<BTreeSet<_>>().len()
                != self.observations.len()
        {
            return Err(
                "every final task and declared observation must be used exactly as preregistered"
                    .into(),
            );
        }
        Ok(assignments)
    }
}
impl Bound {
    pub(super) fn inspect(&self, directory: &Path, deadline: Instant) -> HostResult<Batch> {
        let mut observations = Vec::new();
        let mut receipts = Vec::new();
        for (index, (config, binding, expected)) in self.observations.iter().enumerate() {
            let operation = if expected.is_some() {
                directory.join(format!("observation-{index}"))
            } else {
                directory.to_owned()
            };
            if expected.is_some() {
                std::fs::create_dir(&operation)?;
                std::fs::set_permissions(
                    &operation,
                    std::os::unix::fs::PermissionsExt::from_mode(0o700),
                )?;
                std::fs::File::open(directory)?.sync_all()?;
            }
            let (inspection, receipt) =
                crate::paired_custody_withdrawal::inspect(config, binding, &operation, deadline)?;
            if expected
                .as_ref()
                .is_some_and(|expected| expected != inspection.causal_dependencies())
                || observations
                    .last()
                    .is_some_and(|first: &Inspection| !inspection.same_current_authority(first))
            {
                return Err("actual causal events or independently current frontier differ from original assignment".into());
            }
            observations.push(inspection);
            receipts.push(receipt);
        }
        let receipt = if self.observations[0].2.is_none() {
            receipts[0]
        } else {
            let mut bytes =
                b"hepta.eval.paired-supervised.original-withdrawal-observation-set.v2".to_vec();
            for receipt in receipts {
                bytes.extend_from_slice(receipt.as_array());
            }
            for (task, index) in &self.assignments {
                bytes.extend_from_slice(task.as_array());
                bytes.extend_from_slice(&u64::try_from(*index)?.to_be_bytes());
            }
            Digest32::of_bytes(&bytes)
        };
        Ok(Batch {
            observations,
            receipt,
        })
    }
    pub(super) fn values(&self, batch: &Batch) -> HostResult<BTreeMap<Digest32, FixedQ32>> {
        if batch.observations.len() != self.observations.len() {
            return Err("original observation set incomplete".into());
        }
        self.assignments
            .iter()
            .map(|(task, index)| {
                Ok((
                    *task,
                    batch.observations[*index].delivery_denial_fraction()?,
                ))
            })
            .collect()
    }
}
impl Batch {
    pub(super) fn same_original_facts(&self, earlier: &Self) -> bool {
        self.observations.len() == earlier.observations.len()
            && self
                .observations
                .iter()
                .zip(&earlier.observations)
                .all(|(after, before)| after.same_original_facts(before))
    }
}

#[cfg(test)]
#[path = "paired_custody_observations_tests.rs"]
mod tests;
