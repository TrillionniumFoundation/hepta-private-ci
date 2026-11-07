//! Synthetic matching declarations and observations; actual file journal,
//! witness and final-holdout CAS owners. These are not model experiment results.

use std::fmt::Debug;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_intelligence_eval::*;
use codex_hepta_neuron::*;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::*;

#[path = "neuron_cell_evaluation_test_observations.rs"]
mod observations;
pub(super) use observations::signed;

pub(super) fn checked<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture: {error:?}"),
    }
}
pub(super) fn digest(name: &str) -> Digest32 {
    Digest32::of_bytes(name.as_bytes())
}
pub(super) fn id(name: &str) -> StableId {
    checked(StableId::new(name))
}
pub(super) fn file(path: &Path) -> File {
    checked(
        OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(path),
    )
}

pub(super) type Journal = CellGenerationJournalV2<FileAnchorWitnessStore>;

#[derive(Clone, Copy)]
pub(super) enum Costs {
    Complete,
    Empty,
    MissingStage,
    UnknownCpu,
    UnknownOutcome,
    UnknownEnvelope,
}

pub(super) fn journal(path: &Path, name: &str, costs: Costs, task_digest: [u8; 32]) -> Journal {
    let source = digest(name).into_array();
    let manifest = CellBackendManifestV2 {
        profile: "synthetic-cell-evaluation".into(),
        source_digest: source,
        bundle_digest: digest(&format!("{name}-bundle")).into_array(),
        encoder: Some([3; 32]),
        head: Some([4; 32]),
        memory: None,
        world_model: None,
        decoder: None,
        runtime_digest: [5; 32],
        device_digest: [6; 32],
        input_schema: [7; 32],
        state_schema: [8; 32],
        output_schema: [9; 32],
        learning: CellLearningBindingV2::Frozen { weights: [10; 32] },
        evolution: CellEvolutionBindingV2 {
            structure: [11; 32],
            lineage: [12; 32],
            source_dependencies: [13; 32],
            adoption_receipt: [14; 32],
        },
        max_input_bytes: 128,
        max_state_bytes: 128,
        max_delta_bytes: 128,
        max_prefix_bytes: 256,
        max_step_cost_entries: 16,
        max_ack_cost_entries: 4,
    };
    let initial = CellRuntimeSnapshotV2 {
        scope: CellGenerationScopeV2 {
            principal_digest: [15; 32],
            agent_id: "agent".into(),
            cell_id: name.into(),
            run_id: "comparison".into(),
        },
        manifest_digest: checked(manifest.digest()),
        generation: 1,
        writer_epoch: 1,
        revision: 0,
        state: Vec::new(),
        prefix: Vec::new(),
        stopped: false,
    };
    let witness = checked(FileAnchorWitnessStore::open(
        file(&path.join(format!("{name}-witness"))),
        JournalScope {
            scope_digest: digest(name),
            objective_digest: digest("objective"),
        },
        checked(Generation::new(1)),
        /*max_records*/ 256,
    ));
    let mut journal = checked(CellGenerationJournalV2::open(
        file(&path.join(name)),
        witness,
        CellGenerationConfigV2 {
            manifest,
            initial,
            source_frontier: [16; 32],
            task_digest,
        },
        /*max_records*/ 128,
    ));
    if !matches!(costs, Costs::Empty) {
        for (index, stage) in [
            CellCostStageV2::Encoder,
            CellCostStageV2::Routing,
            CellCostStageV2::Inference,
            CellCostStageV2::Training,
            CellCostStageV2::Planning,
            CellCostStageV2::Critic,
            CellCostStageV2::Codec,
            CellCostStageV2::Queue,
            CellCostStageV2::Persistence,
            CellCostStageV2::Recovery,
            CellCostStageV2::Communication,
            CellCostStageV2::Evaluation,
        ]
        .into_iter()
        .enumerate()
        {
            if index == 11 && matches!(costs, Costs::MissingStage) {
                continue;
            }
            checked(journal.record_cost(CellCostEntryV2 {
                event_id: digest(&format!("{name}-{index}")).into_array(),
                identity: CellTaskCostIdentityV2 {
                    task_digest,
                    source_digest: source,
                },
                stage,
                outcome: if index == 0 && matches!(costs, Costs::UnknownOutcome) {
                    CellCostOutcomeV2::Unknown
                } else if index == 1 {
                    CellCostOutcomeV2::Failed
                } else {
                    CellCostOutcomeV2::Succeeded
                },
                accounting: CellCostAccountingV2::Exclusive,
                metrics: CellCostMetricsV2 {
                    wall_micros: Some(10),
                    cpu_micros: if index == 0 && matches!(costs, Costs::UnknownCpu) {
                        None
                    } else {
                        Some(5)
                    },
                    ..CellCostMetricsV2::default()
                },
            }));
        }
    }
    if matches!(costs, Costs::UnknownEnvelope) {
        let cost = checked(journal.task_cost());
        let Some(entry) = cost.entries().first() else {
            panic!("fixture cost entry");
        };
        let envelope = CellCostEntryV2 {
            event_id: [98; 32],
            identity: cost.identity(),
            stage: CellCostStageV2::Evaluation,
            outcome: CellCostOutcomeV2::Unknown,
            accounting: CellCostAccountingV2::InclusiveEnvelope {
                exclusive_event_ids: vec![entry.event_id],
            },
            metrics: CellCostMetricsV2::default(),
        };
        checked(journal.record_cost(envelope));
    }
    checked(journal.drain());
    journal
}

pub(super) fn comparison() -> CellComparisonContractV1 {
    let observation = |name: &str| CellTrainingObservationV1 {
        participant_id: id(name),
        capacity: CellParameterCapacityV1 {
            total_parameters: 1_000,
            trainable_parameters: 100,
            maximum_active_parameters: 250,
        },
        cumulative: CellTrainingBudgetV1 {
            examples_seen: 200,
            optimizer_steps: 20,
            parameter_updates: 1_000,
            compute_units: 40_000,
            compute_unit_contract: [31; 32],
        },
        selective_update: CellSelectiveUpdateV1 {
            policy_digest: [32; 32],
            eligibility_digest: [33; 32],
            schedule_digest: [34; 32],
            maximum_parameters_per_step: 50,
        },
        structure_before: [11; 32],
        structure_after: [11; 32],
        training_receipt_digest: digest(&format!("{name}-training-declaration")).into_array(),
    };
    CellComparisonContractV1 {
        candidate: observation("candidate"),
        fixed_expert: observation("fixed"),
        cost_coverage: CellCostCoverageV1::wall_and_cpu([35; 32]),
    }
}

pub(super) fn fence() -> HoldoutWriterFenceV1 {
    HoldoutWriterFenceV1 {
        owner_id: id("synthetic-holdout-owner"),
        generation: 1,
        lease_digest: digest("lease"),
    }
}

pub(super) struct Provider {
    pub(super) inputs: Option<TemporalComparisonInputsV1>,
    pub(super) calls: u32,
    pub(super) releases: u32,
    path: PathBuf,
    initial_bytes: u64,
}
impl FinalHoldoutProviderV1 for Provider {
    fn manifest_digest(&mut self) -> Result<Digest32, ProductProviderErrorV1> {
        self.calls += 1;
        Ok(digest("final-holdout"))
    }
    fn release_after_consumption(
        &mut self,
        receipt: &FinalHoldoutJournalReceiptV1,
    ) -> Result<TemporalComparisonInputsV1, ProductProviderErrorV1> {
        self.releases += 1;
        let size = fs::metadata(&self.path)
            .map_err(|_| ProductProviderErrorV1::Unavailable)?
            .len();
        if receipt.sequence == 0 || size <= self.initial_bytes {
            return Err(ProductProviderErrorV1::Rejected);
        }
        self.inputs
            .take()
            .ok_or(ProductProviderErrorV1::Indeterminate)
    }
}

pub(super) struct Fixture {
    pub(super) candidate: Journal,
    pub(super) fixed: Journal,
    pub(super) runner: CellEvaluationRunnerV1<LockedFileFinalHoldoutCasStoreV1>,
    pub(super) registration: CellEvaluationRegistrationV1,
    pub(super) candidate_temporal: TemporalEvaluationPlan,
    pub(super) baseline_temporal: TemporalEvaluationPlan,
    pub(super) provider: Provider,
    pub(super) directory: tempfile::TempDir,
}
impl Fixture {
    pub(super) fn new(costs: Costs) -> Self {
        let directory = checked(tempfile::tempdir());
        let candidate = journal(directory.path(), "candidate", costs, [17; 32]);
        let fixed = journal(directory.path(), "fixed", Costs::Complete, [17; 32]);
        let path = directory.path().join("holdout");
        let store = checked(LockedFileFinalHoldoutCasStoreV1::create(
            file(&path),
            digest("binding"),
        ));
        let owner = checked(FencedFinalHoldoutOwnerV1::initialize(
            store,
            digest("binding"),
            fence(),
        ));
        let initial_bytes = checked(fs::metadata(&path)).len();
        let runner = CellEvaluationRunnerV1::new(ProductEvaluationRunnerV1::new(owner));
        let (registration, candidate_temporal, baseline_temporal, inputs) =
            observations::observations();
        Self {
            candidate,
            fixed,
            runner,
            registration,
            candidate_temporal,
            baseline_temporal,
            provider: Provider {
                inputs: Some(inputs),
                calls: 0,
                releases: 0,
                path,
                initial_bytes,
            },
            directory,
        }
    }
    pub(super) fn journals(
        &self,
    ) -> CellEvaluationJournalsV1<'_, FileAnchorWitnessStore, FileAnchorWitnessStore> {
        CellEvaluationJournalsV1 {
            candidate: &self.candidate,
            fixed_expert: &self.fixed,
        }
    }
    pub(super) fn freeze(&self) -> Result<CellEvaluationPlanV1, CellEvaluationErrorV1> {
        freeze_cell_evaluation_plan_v1(
            self.registration.clone(),
            self.journals(),
            &self.candidate_temporal,
            &self.baseline_temporal,
        )
    }
    pub(super) fn run(
        &mut self,
        plan: &CellEvaluationPlanV1,
    ) -> Result<CellEvaluationReceiptV1, CellEvaluationErrorV1> {
        self.runner.evaluate(
            plan,
            CellEvaluationJournalsV1 {
                candidate: &self.candidate,
                fixed_expert: &self.fixed,
            },
            &self.candidate_temporal,
            &self.baseline_temporal,
            &mut self.provider,
        )
    }
    pub(super) fn holdout_bytes(&self) -> Vec<u8> {
        checked(fs::read(self.directory.path().join("holdout")))
    }
}
