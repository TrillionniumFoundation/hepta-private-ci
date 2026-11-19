use std::fs::File;
use std::fs::OpenOptions;

use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

use crate::FrozenGenerationEpisodeInputV1;
use crate::FrozenGenerationEpisodeV1;
use crate::outcome_credit_v2::tests::digest;
use crate::outcome_credit_v2::tests::id;

pub(crate) struct GenerationFixture {
    temp: tempfile::TempDir,
    pub(crate) config: CellGenerationConfigV2,
    pub(crate) frozen: FrozenGenerationEpisodeV1,
}

impl GenerationFixture {
    pub(crate) fn new() -> Self {
        let manifest = CellBackendManifestV2 {
            profile: "generation-episode-qualification".to_owned(),
            source_digest: [1; 32],
            bundle_digest: [2; 32],
            encoder: Some([3; 32]),
            head: None,
            memory: None,
            world_model: None,
            decoder: Some([4; 32]),
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
            max_input_bytes: 1024,
            max_state_bytes: 1024,
            max_delta_bytes: 1024,
            max_prefix_bytes: 4096,
            max_step_cost_entries: 4,
            max_ack_cost_entries: 4,
        };
        let initial = CellRuntimeSnapshotV2 {
            scope: CellGenerationScopeV2 {
                principal_digest: [15; 32],
                agent_id: "agent".to_owned(),
                cell_id: "cell".to_owned(),
                run_id: "generation-run".to_owned(),
            },
            manifest_digest: manifest.digest().expect("manifest"),
            generation: 1,
            writer_epoch: 1,
            revision: 0,
            state: Vec::new(),
            prefix: Vec::new(),
            stopped: false,
        };
        let source_frontier = digest("generation-source-frontier");
        let frozen = FrozenGenerationEpisodeV1::new(FrozenGenerationEpisodeInputV1 {
            episode_id: id("episode-v2"),
            run_id: id("generation-run"),
            decision_id: id("run-v2"),
            objective_digest: digest("objective"),
            policy_digest: digest("policy"),
            evaluation_profile_digest: digest("reward-unit"),
            sampler_digest: digest("sampler-declaration"),
            source_frontier,
            initial: initial.clone(),
        })
        .expect("frozen generation");
        let config = CellGenerationConfigV2 {
            manifest,
            initial,
            source_frontier: source_frontier.into_array(),
            task_digest: frozen.task_digest().into_array(),
        };
        Self {
            temp: tempfile::tempdir().expect("generation directory"),
            config,
            frozen,
        }
    }

    fn file(&self, name: &str) -> File {
        OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(self.temp.path().join(name))
            .expect("generation file")
    }

    pub(crate) fn open(&self) -> CellGenerationJournalV2<FileAnchorWitnessStore> {
        let witness = FileAnchorWitnessStore::open(
            self.file("witness"),
            JournalScope {
                scope_digest: digest("generation-witness-scope"),
                objective_digest: self.frozen.input().objective_digest,
            },
            Generation::new(self.config.initial.generation).expect("generation"),
            /*max_records*/ 128,
        )
        .expect("generation witness");
        CellGenerationJournalV2::open(
            self.file("journal"),
            witness,
            self.config.clone(),
            /*max_records*/ 128,
        )
        .expect("generation owner")
    }

    pub(crate) fn request(
        &self,
        owner: &CellGenerationJournalV2<FileAnchorWitnessStore>,
        operation_id: &str,
    ) -> CellGenerationRequestV2 {
        CellGenerationRequestV2 {
            operation_id: operation_id.to_owned(),
            task_digest: self.config.task_digest,
            source_frontier: self.config.source_frontier,
            predecessor: owner.snapshot().expect("snapshot").clone(),
            input: Vec::new(),
            admitted_at_micros: 10,
            deadline_micros: 100,
        }
    }

    pub(crate) fn proposal(
        &self,
        request: &CellGenerationRequestV2,
        disposition: CellGenerationDispositionV2,
        output_delta: &[u8],
    ) -> CellGenerationProposalV2 {
        let manifest = &self.config.manifest;
        let identity = CellTaskCostIdentityV2 {
            task_digest: request.task_digest,
            source_digest: manifest.source_digest,
        };
        let mut cost = CellTaskCostV2::new(identity).expect("cost");
        cost.record(CellCostEntryV2 {
            event_id: Digest32::of_parts(&[
                b"fixture-execution",
                &request.digest().expect("request"),
            ])
            .into_array(),
            identity,
            stage: CellCostStageV2::Inference,
            outcome: CellCostOutcomeV2::Succeeded,
            accounting: CellCostAccountingV2::Exclusive,
            metrics: CellCostMetricsV2 {
                wall_micros: Some(7),
                ..CellCostMetricsV2::default()
            },
        })
        .expect("fixture meter");
        CellGenerationProposalV2 {
            request_digest: request.digest().expect("request"),
            bundle_digest: manifest.bundle_digest,
            runtime_digest: manifest.runtime_digest,
            device_digest: manifest.device_digest,
            successor_state: b"settled-state".to_vec(),
            output_delta: output_delta.to_vec(),
            disposition,
            cost,
        }
    }
}
