//! Label-free statistical lineage for archived machine tasks.
//!
//! A statistical principal is a connected dependency component, not a human or
//! an evidence-signing service. Source custody must authenticate the archive,
//! record bytes and complete dependency graph before using this pure adapter.
//! Its digest must enter the frozen source/assumptions contract. It grants no
//! qualification authority and does not prove pretraining disjointness.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CrossFoldPartitionV1;
use crate::push_id;

const MAX_RECORDS: usize = 100_000;
const MAX_DEPENDENCIES: usize = 128;
const MAX_EDGES: usize = 1_000_000;
const MAX_SOURCE_GRAPH_BYTES: usize = 16 * 1024 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TaskSourceScopeV1 {
    pub objective_digest: Digest32,
    pub task_definition_digest: Digest32,
    pub source_archive_digest: Digest32,
}

/// One original source record, without labels, predictions or synthetic time.
/// For paired tasks, dependencies include all cited documents of the original
/// task, not only the document in this particular pair.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TaskSourceRecordV1 {
    pub source_file_digest: Digest32,
    pub source_row_index: u64,
    pub source_record_digest: Digest32,
    pub task_id: StableId,
    pub dependency_ids: Vec<StableId>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TaskCrossFoldInputsV1 {
    pub fold_id: StableId,
    pub training_records: Vec<Digest32>,
    pub holdout_records: Vec<Digest32>,
    pub training_windows: Vec<StableId>,
    pub holdout_windows: Vec<StableId>,
    pub model_digest: Digest32,
    pub predictions_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TaskLineageError {
    MissingDigest,
    ResourceLimit,
    SourceRow,
    DuplicateRecord,
    DuplicateDependency,
    InconsistentTask,
    UnknownRecord,
    DuplicateMembership,
    DependentSplit,
    InvalidWindow,
    InvalidEvent,
    InvalidActions,
    InvalidOutcome,
    InvalidPlan,
    FinalHoldoutLeakage,
    Identity,
}

impl fmt::Display for TaskLineageError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl Error for TaskLineageError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct TaskRecordLineageV1 {
    pub principal: StableId,
    pub episode: StableId,
    pub cluster: StableId,
}

/// Immutable, bounded graph. Repeated tasks and shared dependencies remain in
/// the same principal/cluster across records, folds and execution runs.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FrozenTaskSourceLineageV1 {
    pub(crate) objective_digest: Digest32,
    scope_digest: Digest32,
    source_graph_digest: Digest32,
    records: BTreeMap<Digest32, TaskRecordLineageV1>,
}

impl FrozenTaskSourceLineageV1 {
    pub fn freeze(
        scope: &TaskSourceScopeV1,
        records: &[TaskSourceRecordV1],
    ) -> Result<Self, TaskLineageError> {
        for digest in [
            scope.objective_digest,
            scope.task_definition_digest,
            scope.source_archive_digest,
        ] {
            require_digest(digest)?;
        }
        if records.is_empty() || records.len() > MAX_RECORDS {
            return Err(TaskLineageError::ResourceLimit);
        }
        let mut scope_bytes = b"hepta.eval.archived-task.scope.v1".to_vec();
        for digest in [
            scope.objective_digest,
            scope.task_definition_digest,
            scope.source_archive_digest,
        ] {
            scope_bytes.extend_from_slice(digest.as_array());
        }
        let scope_digest = Digest32::of_bytes(&scope_bytes);
        let mut ordered: Vec<_> = records.iter().collect();
        ordered.sort_by_key(|record| record.source_record_digest);
        let mut seen = BTreeSet::new();
        let mut positions = BTreeMap::new();
        let mut tasks = BTreeMap::new();
        let mut edges = 0_usize;
        let mut graph_bytes = b"hepta.eval.archived-task.source-graph.v1".to_vec();
        graph_bytes.extend_from_slice(scope_digest.as_array());
        graph_bytes.extend_from_slice(&(ordered.len() as u64).to_be_bytes());
        for record in &ordered {
            require_digest(record.source_file_digest)?;
            require_digest(record.source_record_digest)?;
            if record.source_row_index == 0 {
                return Err(TaskLineageError::SourceRow);
            }
            if let Some(previous) = positions.insert(
                (record.source_file_digest, record.source_row_index),
                &record.task_id,
            ) && previous != &record.task_id
            {
                return Err(TaskLineageError::InconsistentTask);
            }
            if !seen.insert(record.source_record_digest) {
                return Err(TaskLineageError::DuplicateRecord);
            }
            if record.dependency_ids.len() > MAX_DEPENDENCIES {
                return Err(TaskLineageError::ResourceLimit);
            }
            edges = edges
                .checked_add(record.dependency_ids.len())
                .filter(|count| *count <= MAX_EDGES)
                .ok_or(TaskLineageError::ResourceLimit)?;
            let dependencies: BTreeSet<_> = record.dependency_ids.iter().cloned().collect();
            if dependencies.len() != record.dependency_ids.len() {
                return Err(TaskLineageError::DuplicateDependency);
            }
            if let Some(previous) = tasks.insert(record.task_id.clone(), dependencies.clone())
                && previous != dependencies
            {
                return Err(TaskLineageError::InconsistentTask);
            }
            graph_bytes.extend_from_slice(record.source_file_digest.as_array());
            graph_bytes.extend_from_slice(&record.source_row_index.to_be_bytes());
            graph_bytes.extend_from_slice(record.source_record_digest.as_array());
            push_id(&mut graph_bytes, &record.task_id);
            graph_bytes.extend_from_slice(&(dependencies.len() as u64).to_be_bytes());
            for dependency in dependencies {
                push_id(&mut graph_bytes, &dependency);
            }
            if graph_bytes.len() > MAX_SOURCE_GRAPH_BYTES {
                return Err(TaskLineageError::ResourceLimit);
            }
        }

        let indexed: Vec<_> = tasks.iter().collect();
        let mut parents: Vec<_> = (0..indexed.len()).collect();
        let mut owners = BTreeMap::new();
        for (index, (_, dependencies)) in indexed.iter().enumerate() {
            for dependency in *dependencies {
                if let Some(previous) = owners.insert(dependency, index) {
                    let left = component_root(&mut parents, index);
                    let right = component_root(&mut parents, previous);
                    parents[left.max(right)] = left.min(right);
                }
            }
        }
        let mut components: BTreeMap<_, Vec<_>> = BTreeMap::new();
        for index in 0..indexed.len() {
            components
                .entry(component_root(&mut parents, index))
                .or_default()
                .push(index);
        }
        let mut by_task = BTreeMap::new();
        for members in components.values() {
            let mut component_bytes = b"hepta.eval.archived-task.component.v1".to_vec();
            component_bytes.extend_from_slice(scope_digest.as_array());
            component_bytes.extend_from_slice(&(members.len() as u64).to_be_bytes());
            for index in members {
                let (task, dependencies) = indexed[*index];
                push_id(&mut component_bytes, task);
                component_bytes.extend_from_slice(&(dependencies.len() as u64).to_be_bytes());
                for dependency in dependencies {
                    push_id(&mut component_bytes, dependency);
                }
            }
            let component_digest = Digest32::of_bytes(&component_bytes);
            for index in members {
                let (task, _) = indexed[*index];
                let mut episode_bytes = b"hepta.eval.archived-task.episode.v1".to_vec();
                episode_bytes.extend_from_slice(scope_digest.as_array());
                push_id(&mut episode_bytes, task);
                by_task.insert(
                    task,
                    TaskRecordLineageV1 {
                        principal: digest_id("task-principal", component_digest)?,
                        cluster: digest_id("task-cluster", component_digest)?,
                        episode: digest_id("task-episode", Digest32::of_bytes(&episode_bytes))?,
                    },
                );
            }
        }
        Ok(Self {
            objective_digest: scope.objective_digest,
            scope_digest,
            source_graph_digest: Digest32::of_bytes(&graph_bytes),
            records: ordered
                .into_iter()
                .map(|record| {
                    (
                        record.source_record_digest,
                        by_task[&record.task_id].clone(),
                    )
                })
                .collect(),
        })
    }

    #[must_use]
    pub fn source_graph_digest(&self) -> Digest32 {
        self.source_graph_digest
    }

    /// Construct the existing native partition without caller-invented subjects.
    /// The normal plan freezer still validates windows, coverage and all gates.
    pub fn cross_fold_partition(
        &self,
        inputs: TaskCrossFoldInputsV1,
    ) -> Result<CrossFoldPartitionV1, TaskLineageError> {
        require_digest(inputs.model_digest)?;
        require_digest(inputs.predictions_digest)?;
        let mut membership = BTreeSet::new();
        let mut sides: [(BTreeSet<StableId>, BTreeSet<StableId>); 2] = Default::default();
        for (records, (principals, episodes)) in [&inputs.training_records, &inputs.holdout_records]
            .into_iter()
            .zip(&mut sides)
        {
            if records.is_empty() || records.len() > MAX_RECORDS {
                return Err(TaskLineageError::ResourceLimit);
            }
            for digest in records {
                if !membership.insert(*digest) {
                    return Err(TaskLineageError::DuplicateMembership);
                }
                let lineage = self.record(*digest)?;
                principals.insert(lineage.principal.clone());
                episodes.insert(lineage.episode.clone());
            }
        }
        let [
            (training_principals, training_episodes),
            (holdout_principals, holdout_episodes),
        ] = sides;
        if !training_principals.is_disjoint(&holdout_principals)
            || !training_episodes.is_disjoint(&holdout_episodes)
        {
            return Err(TaskLineageError::DependentSplit);
        }
        Ok(CrossFoldPartitionV1 {
            fold_id: inputs.fold_id,
            training_principals: training_principals.into_iter().collect(),
            training_episodes: training_episodes.into_iter().collect(),
            training_windows: inputs.training_windows,
            holdout_principals: holdout_principals.into_iter().collect(),
            holdout_episodes: holdout_episodes.into_iter().collect(),
            holdout_windows: inputs.holdout_windows,
            model_digest: inputs.model_digest,
            predictions_digest: inputs.predictions_digest,
        })
    }

    pub(crate) fn scope_digest(&self) -> Digest32 {
        self.scope_digest
    }

    pub(crate) fn record_digests(&self) -> impl Iterator<Item = Digest32> + '_ {
        self.records.keys().copied()
    }

    pub(crate) fn record(
        &self,
        digest: Digest32,
    ) -> Result<&TaskRecordLineageV1, TaskLineageError> {
        self.records
            .get(&digest)
            .ok_or(TaskLineageError::UnknownRecord)
    }
}

fn component_root(parents: &mut [usize], mut index: usize) -> usize {
    while parents[index] != index {
        parents[index] = parents[parents[index]];
        index = parents[index];
    }
    index
}

pub(crate) fn require_digest(digest: Digest32) -> Result<(), TaskLineageError> {
    if digest.is_zero() {
        Err(TaskLineageError::MissingDigest)
    } else {
        Ok(())
    }
}

pub(crate) fn digest_id(prefix: &str, digest: Digest32) -> Result<StableId, TaskLineageError> {
    StableId::new(format!("{prefix}:{digest}")).map_err(|_| TaskLineageError::Identity)
}

#[cfg(test)]
#[path = "task_lineage_tests.rs"]
mod tests;
