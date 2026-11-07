use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

use crate::AnchorWitnessStore;
use crate::FileAnchorWitnessStore;
use crate::JournalAnchor;
use crate::JournalScope;
use crate::WitnessStoreError;
use crate::cell_generation_journal::CellGenerationJournalV2;
use crate::cell_generation_state::CellGenerationConfigV2;
use crate::cell_generation_types::*;
use crate::cell_task_cost::*;
use crate::cell_test_support::checked;

static NEXT: AtomicU64 = AtomicU64::new(0);

pub(super) struct Fixture(pub(super) PathBuf);

impl Fixture {
    pub(super) fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let path =
            std::env::temp_dir().join(format!("hepta-generation-{}-{serial}", std::process::id()));
        checked(fs::create_dir(&path));
        Self(path)
    }

    pub(super) fn file(&self, name: &str) -> File {
        checked(
            OpenOptions::new()
                .create(true)
                .truncate(false)
                .read(true)
                .write(true)
                .open(self.0.join(name)),
        )
    }

    pub(super) fn witness(&self) -> FileAnchorWitnessStore {
        checked(FileAnchorWitnessStore::open(
            self.file("witness"),
            JournalScope {
                scope_digest: Digest32::of_bytes(b"scope"),
                objective_digest: Digest32::of_bytes(b"objective"),
            },
            checked(Generation::new(1)),
            /*max_records*/ 4_096,
        ))
    }

    pub(super) fn open(&self) -> CellGenerationJournalV2<FileAnchorWitnessStore> {
        self.open_with(config(), /*max_records*/ 128)
    }

    pub(super) fn open_with(
        &self,
        config: CellGenerationConfigV2,
        max_records: u64,
    ) -> CellGenerationJournalV2<FileAnchorWitnessStore> {
        checked(CellGenerationJournalV2::open(
            self.file("journal"),
            self.witness(),
            config,
            max_records,
        ))
    }

    pub(super) fn bytes(&self) -> Vec<u8> {
        checked(fs::read(self.0.join("journal")))
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

pub(super) fn config() -> CellGenerationConfigV2 {
    let manifest = CellBackendManifestV2 {
        profile: "qualification-generation".to_string(),
        source_digest: [1; 32],
        bundle_digest: [2; 32],
        encoder: Some([3; 32]),
        head: None,
        memory: None,
        world_model: Some([4; 32]),
        decoder: Some([5; 32]),
        runtime_digest: [6; 32],
        device_digest: [7; 32],
        input_schema: [8; 32],
        state_schema: [9; 32],
        output_schema: [10; 32],
        learning: CellLearningBindingV2::Resumable {
            weights: [11; 32],
            optimizer: [12; 32],
            rng: [13; 32],
            sampler: [14; 32],
            training_cursor: [15; 32],
        },
        evolution: CellEvolutionBindingV2 {
            structure: [16; 32],
            lineage: [17; 32],
            source_dependencies: [18; 32],
            adoption_receipt: [19; 32],
        },
        max_input_bytes: 256,
        max_state_bytes: 256,
        max_delta_bytes: 256,
        max_prefix_bytes: 1024,
        max_step_cost_entries: 32,
        max_ack_cost_entries: 16,
    };
    let initial = CellRuntimeSnapshotV2 {
        scope: CellGenerationScopeV2 {
            principal_digest: [20; 32],
            agent_id: "agent".to_string(),
            cell_id: "cell".to_string(),
            run_id: "run".to_string(),
        },
        manifest_digest: checked(manifest.digest()),
        generation: 1,
        writer_epoch: 1,
        revision: 0,
        state: vec![1],
        prefix: Vec::new(),
        stopped: false,
    };
    CellGenerationConfigV2 {
        manifest,
        initial,
        source_frontier: [21; 32],
        task_digest: [22; 32],
    }
}

pub(super) fn request<W: AnchorWitnessStore>(
    owner: &CellGenerationJournalV2<W>,
    id: &str,
) -> CellGenerationRequestV2 {
    CellGenerationRequestV2 {
        operation_id: id.to_string(),
        task_digest: [22; 32],
        source_frontier: [21; 32],
        predecessor: checked(owner.snapshot()).clone(),
        input: vec![2, 3],
        admitted_at_micros: 10,
        deadline_micros: 100,
    }
}

pub(super) fn cost() -> CellTaskCostV2 {
    checked(CellTaskCostV2::new(CellTaskCostIdentityV2 {
        task_digest: [22; 32],
        source_digest: [1; 32],
    }))
}

pub(super) fn charge(name: &str, stage: CellCostStageV2) -> CellCostEntryV2 {
    CellCostEntryV2 {
        event_id: Digest32::of_bytes(name.as_bytes()).into_array(),
        identity: cost().identity(),
        stage,
        outcome: CellCostOutcomeV2::Succeeded,
        accounting: CellCostAccountingV2::Exclusive,
        metrics: CellCostMetricsV2 {
            cpu_micros: Some(1),
            ..CellCostMetricsV2::default()
        },
    }
}

pub(super) fn charges(label: &str, stage: CellCostStageV2, count: usize) -> CellTaskCostV2 {
    let mut result = cost();
    for index in 0..count {
        checked(result.record(charge(&format!("{label}-{index}"), stage)));
    }
    result
}

pub(super) fn saturate_cost_records<W: AnchorWitnessStore>(
    owner: &mut CellGenerationJournalV2<W>,
    label: &str,
    max_attempts: u64,
) -> CellCostEntryV2 {
    let mut recorded = None;
    for index in 0..max_attempts {
        let entry = charge(&format!("{label}-{index}"), CellCostStageV2::Persistence);
        match owner.record_cost(entry.clone()) {
            Ok(()) => recorded = Some(entry),
            Err(CellGenerationErrorV2::Capacity) => {
                return checked(recorded.ok_or("capacity reached before test overhead"));
            }
            Err(error) => panic!("unexpected cost refusal: {error:?}"),
        }
    }
    panic!("journal did not preserve reserved record capacity");
}

pub(super) fn proposal(request: &CellGenerationRequestV2) -> CellGenerationProposalV2 {
    let mut cost = cost();
    checked(cost.record(CellCostEntryV2 {
        event_id: checked(request.digest()),
        identity: cost.identity(),
        stage: CellCostStageV2::Inference,
        outcome: CellCostOutcomeV2::Succeeded,
        accounting: CellCostAccountingV2::Exclusive,
        metrics: CellCostMetricsV2 {
            wall_micros: Some(3),
            cpu_micros: Some(7),
            ..CellCostMetricsV2::default()
        },
    }));
    CellGenerationProposalV2 {
        request_digest: checked(request.digest()),
        bundle_digest: [2; 32],
        runtime_digest: [6; 32],
        device_digest: [7; 32],
        successor_state: vec![2],
        output_delta: "中🙂\n".as_bytes().to_vec(),
        disposition: CellGenerationDispositionV2::Advanced,
        cost,
    }
}

pub(super) struct FailOnce<W> {
    pub(super) inner: W,
    pub(super) fail: Arc<AtomicBool>,
}

impl<W: AnchorWitnessStore> AnchorWitnessStore for FailOnce<W> {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.inner.current()
    }

    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        if self.fail.swap(false, Ordering::SeqCst) {
            return Err(WitnessStoreError::Unavailable);
        }
        self.inner.compare_and_swap(expected, next)
    }
}
