//! Synthetic metadata and real file/fsync CAS for component tests only.
//! This is neither a production Root capability nor authenticated learning.

use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::Path;
use std::sync::Mutex;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_learning_artifacts::*;
use codex_hepta_types::StableId;

use super::*;
use crate::neuron_generation_update_bootstrap::learning_test_baseline;
use crate::neuron_generation_update_bootstrap::learning_test_receipt;

pub(super) const OWNER: &str = "fixture-iteration-owner";

pub(super) struct FileCas {
    file: Mutex<File>,
    pub(super) failure: AtomicU8,
    pub(super) commits: AtomicUsize,
}
impl FileCas {
    pub(super) fn create(
        path: &Path,
        record: &LearningIterationCheckpointRecordV1,
    ) -> anyhow::Result<Self> {
        let mut file = OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(path)?;
        file.write_all(&serde_json::to_vec(record)?)?;
        file.sync_all()?;
        File::open(path.parent().unwrap())?.sync_all()?;
        Self::reopen(path)
    }
    pub(super) fn reopen(path: &Path) -> anyhow::Result<Self> {
        Ok(Self {
            file: Mutex::new(OpenOptions::new().read(true).write(true).open(path)?),
            failure: AtomicU8::new(0),
            commits: AtomicUsize::new(0),
        })
    }
    fn locked<T>(
        &self,
        owner: &str,
        action: impl FnOnce(&mut File) -> Result<T, AuthorityTrustError>,
    ) -> Result<T, AuthorityTrustError> {
        if owner != OWNER {
            return Err(AuthorityTrustError::Invalid);
        }
        let mut file = self
            .file
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        file.try_lock().map_err(|_| AuthorityTrustError::Conflict)?;
        let result = action(&mut file);
        file.unlock()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        result
    }
}
impl AuthorityFrontierStore<LearningIterationCheckpointRecordV1> for FileCas {
    fn load(
        &self,
        owner: &str,
    ) -> Result<LearningIterationCheckpointRecordV1, AuthorityTrustError> {
        self.locked(owner, read)
    }
    fn compare_and_set(
        &self,
        owner: &str,
        expected: &LearningIterationCheckpointRecordV1,
        next: &LearningIterationCheckpointRecordV1,
    ) -> Result<(), AuthorityTrustError> {
        self.locked(owner, |file| {
            if read(file)? != *expected {
                return Err(AuthorityTrustError::Conflict);
            }
            let failure = self.failure.swap(0, Ordering::SeqCst);
            if failure == 1 {
                return Err(AuthorityTrustError::Unavailable);
            }
            let bytes = serde_json::to_vec(next).map_err(|_| AuthorityTrustError::Invalid)?;
            if bytes.len() > 16 * 1024 {
                return Err(AuthorityTrustError::Invalid);
            }
            file.seek(SeekFrom::Start(0)).map_err(unavailable)?;
            file.set_len(0).map_err(unavailable)?;
            file.write_all(&bytes).map_err(unavailable)?;
            file.sync_all().map_err(unavailable)?;
            self.commits.fetch_add(1, Ordering::SeqCst);
            if failure == 2 {
                return Err(AuthorityTrustError::Unavailable);
            }
            Ok(())
        })
    }
}
fn read(file: &mut File) -> Result<LearningIterationCheckpointRecordV1, AuthorityTrustError> {
    file.seek(SeekFrom::Start(0)).map_err(unavailable)?;
    let mut bytes = Vec::new();
    file.take(16 * 1024 + 1)
        .read_to_end(&mut bytes)
        .map_err(unavailable)?;
    if bytes.len() > 16 * 1024 {
        return Err(AuthorityTrustError::Invalid);
    }
    serde_json::from_slice(&bytes).map_err(|_| AuthorityTrustError::Invalid)
}
fn unavailable(_: std::io::Error) -> AuthorityTrustError {
    AuthorityTrustError::Unavailable
}

pub(super) fn owner(
    store: std::sync::Arc<FileCas>,
    initial: &LearningIterationSnapshotV1,
) -> LearningIterationCheckpointOwnerV1 {
    LearningIterationCheckpointOwnerV1 {
        owner_id: OWNER.into(),
        store: Store::Test(store),
        initial: initial.clone(),
    }
}

#[derive(Clone, Copy)]
pub(super) enum Decision {
    Update,
    EvaluatedNoUpdate,
    ProposedNoUpdate,
}

/// Every variable-length identifier has its maximum legal 128-byte value;
/// both bundles include every optional digest and full training lineage.
pub(super) fn snapshots(decision: Decision) -> anyhow::Result<Vec<LearningIterationSnapshotV1>> {
    let id = |label: &str| StableId::new(format!("{label}{}", "x".repeat(128 - label.len())));
    let d = |label: &str| Digest32::of_bytes(label.as_bytes());
    let mut baseline = learning_test_baseline()?;
    baseline.artifact_id = id("baseline")?;
    baseline.components.organ_adapter = Some(d("organ"));
    baseline.components.cell_adapter = Some(d("cell"));
    baseline.rollback_predecessor = Some(d("earlier-bundle"));
    baseline.training_lineage = Some(CellTrainingLineageV1 {
        source_bundle: d("earlier-bundle"),
        dataset: d("earlier-data"),
        update_rule: d("rule"),
        evaluation_profile: d("profile"),
    });
    let request = LearningIterationRequestV1 {
        operation_id: id("operation")?,
        principal_id: id("principal")?,
        agent_id: id("agent")?,
        cell_id: id("cell")?,
        source_run_id: id("source-run")?,
        completed_task_receipt: d("completed"),
        selected_artifact_digest: d("artifact"),
        selected_bundle: baseline.clone(),
        envelope: IterationEnvelopeV1 {
            envelope_id: id("envelope")?,
            base_commit: d("commit"),
            base_tree: d("tree"),
            objective_digest: d("objective"),
            grammar_digest: d("grammar"),
            maximum_files: 100,
            maximum_diff_bytes: 1_048_576,
            maximum_candidates: 32,
            maximum_parallel_sandboxes: 8,
            expiry_unix_seconds: 100,
        },
        budget: LearningIterationBudgetV1 {
            maximum_dataset_rows: 1_000_000,
            maximum_dataset_bytes: 1 << 30,
            maximum_training_steps: 1_000_000,
            maximum_training_milliseconds: 86_400_000,
            maximum_artifact_bytes: 16 << 30,
        },
    };
    let owners = LearningIterationOwnersV1 {
        evidence_trust_digest: d("trust"),
        experience: id("experience")?,
        dataset: id("dataset")?,
        trainer: id("trainer")?,
        evaluator: id("evaluator")?,
        proposal: id("proposal")?,
        selector: id("selector")?,
        next_use_observer: id("observer")?,
    };
    let mut candidate = baseline.clone();
    candidate.artifact_id = id("candidate")?;
    candidate.generation = candidate.generation.next()?;
    candidate.rollback_predecessor = Some(baseline.digest()?);
    candidate.training_lineage = Some(CellTrainingLineageV1 {
        source_bundle: baseline.digest()?,
        dataset: d("data"),
        update_rule: d("rule"),
        evaluation_profile: d("profile"),
    });
    let candidate_digest = candidate.digest()?;
    let task_bundle = match decision {
        Decision::Update => candidate_digest,
        Decision::EvaluatedNoUpdate | Decision::ProposedNoUpdate => baseline.digest()?,
    };
    let partition = CellStatePartitionV1 {
        principal_id: request.principal_id.clone(),
        agent_id: request.agent_id.clone(),
        cell_id: request.cell_id.clone(),
        run_id: id("next-run")?,
    };
    let mut observations = vec![
        LearningIterationObservationV1::Experience {
            episode_digest: d("episode"),
            completed_task_receipt: request.completed_task_receipt,
        },
        LearningIterationObservationV1::Dataset {
            snapshot_digest: d("data"),
            episode_digest: d("episode"),
            withdrawal_frontier: d("withdrawal"),
            rows: 1,
            bytes: 1,
        },
        LearningIterationObservationV1::Training {
            candidate: Box::new(candidate),
            steps: 1,
            milliseconds: 1,
            artifact_bytes: 1,
        },
        LearningIterationObservationV1::Evaluation {
            candidate_bundle: candidate_digest,
            evaluation_profile: d("profile"),
            disposition: match decision {
                Decision::EvaluatedNoUpdate => LearningEvaluationDispositionV1::NoUpdate,
                Decision::Update | Decision::ProposedNoUpdate => {
                    LearningEvaluationDispositionV1::Qualified
                }
            },
        },
    ];
    if !matches!(decision, Decision::EvaluatedNoUpdate) {
        observations.push(LearningIterationObservationV1::Proposal {
            candidate_bundle: candidate_digest,
            proposal_id: request.operation_id.clone(),
            composition_digest: d("composition"),
            disposition: match decision {
                Decision::ProposedNoUpdate => LearningProposalDispositionV1::NoAdmissibleUpdate,
                Decision::Update | Decision::EvaluatedNoUpdate => {
                    LearningProposalDispositionV1::UpdateCandidates
                }
            },
        });
    }
    observations.push(LearningIterationObservationV1::Selection {
        candidate_bundle: task_bundle,
        selection_digest: d("selection"),
    });
    observations.push(match decision {
        Decision::Update => LearningIterationObservationV1::NextUse {
            candidate_bundle: task_bundle,
            state_partition: partition,
            checkpoint_digest: d("checkpoint"),
            selection_digest: d("selection"),
            committed_step_receipt: d("step"),
            state_cutover_receipt: d("cutover"),
        },
        Decision::EvaluatedNoUpdate | Decision::ProposedNoUpdate => {
            LearningIterationObservationV1::RetainedModelNextUse {
                retained_bundle: task_bundle,
                state_partition: partition,
                checkpoint_digest: d("checkpoint"),
                selection_digest: d("selection"),
                committed_step_receipt: d("step"),
                task_owner_publication: d("publication"),
            }
        }
    });
    let mut coordinator = LearningIterationCoordinatorV1::new(request, owners)?;
    let mut snapshots = vec![coordinator.snapshot().clone()];
    for observation in observations {
        coordinator.record(learning_test_receipt(&coordinator, observation), 20)?;
        snapshots.push(coordinator.snapshot().clone());
    }
    Ok(snapshots)
}
