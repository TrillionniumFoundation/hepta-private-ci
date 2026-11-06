use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

use super::*;
use crate::CellBackendManifestV2;
use crate::CellEvolutionBindingV2;
use crate::CellGenerationJournalV2;
use crate::CellGenerationRequestV2;
use crate::CellLearningBindingV2;
use crate::CellRuntimeSnapshotV2;
use crate::FileAnchorWitnessStore;
use crate::JournalScope;

static NEXT: AtomicU64 = AtomicU64::new(0);

struct Files(PathBuf);
impl Files {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!("generation-current-{}-{serial}", std::process::id()));
        fs::create_dir(&path).unwrap();
        Self(path)
    }

    fn file(&self, name: &str) -> File {
        OpenOptions::new().create(true).truncate(false).read(true).write(true).open(self.0.join(name)).unwrap()
    }

    fn witness(&self) -> FileAnchorWitnessStore {
        FileAnchorWitnessStore::open(self.file("witness"), JournalScope {
            scope_digest: Digest32::of_bytes(b"guarded-scope"),
            objective_digest: Digest32::of_bytes(b"guarded-task"),
        }, Generation::new(1).unwrap(), /*max_records*/ 128).unwrap()
    }

    fn bytes(&self) -> Vec<u8> {
        fs::read(self.0.join("journal")).unwrap()
    }
}
impl Drop for Files {
    fn drop(&mut self) { let _ = fs::remove_dir_all(&self.0); }
}

// Only the journal port is exercised here. Actual signed/root-owner behavior
// belongs to the separate Control integration tests, not this test double.
struct Current(Mutex<(Option<CellGenerationOwnerBindingV1>, Option<CellGenerationOwnerBindingV1>)>);
impl CellGenerationCurrentV1 for Current {
    fn check_open(&self, binding: &CellGenerationOwnerBindingV1) -> Result<CellGenerationOpenModeV1, CellGenerationErrorV2> {
        let state = self.0.lock().unwrap();
        if state.0.as_ref() == Some(binding) { Ok(CellGenerationOpenModeV1::Active) }
        else if state.1.as_ref() == Some(binding) { Ok(CellGenerationOpenModeV1::Preparing) }
        else { Err(CellGenerationErrorV2::InvalidBinding) }
    }

    fn check_current(&self, binding: &CellGenerationOwnerBindingV1) -> Result<(), CellGenerationErrorV2> {
        match self.check_open(binding)? {
            CellGenerationOpenModeV1::Active => Ok(()),
            CellGenerationOpenModeV1::Preparing => Err(CellGenerationErrorV2::Pending),
        }
    }
}

fn config() -> CellGenerationConfigV2 {
    let manifest = CellBackendManifestV2 {
        profile: "guarded-journal-test".into(), source_digest: [1; 32], bundle_digest: [2; 32],
        encoder: Some([3; 32]), head: None, memory: None, world_model: None, decoder: None,
        runtime_digest: [4; 32], device_digest: [5; 32], input_schema: [6; 32],
        state_schema: [7; 32], output_schema: [8; 32],
        learning: CellLearningBindingV2::Frozen { weights: [9; 32] },
        evolution: CellEvolutionBindingV2 { structure: [10; 32], lineage: [11; 32], source_dependencies: [12; 32], adoption_receipt: [13; 32] },
        max_input_bytes: 256, max_state_bytes: 256, max_delta_bytes: 256, max_prefix_bytes: 1024,
        max_step_cost_entries: 4, max_ack_cost_entries: 4,
    };
    let initial = CellRuntimeSnapshotV2 {
        scope: CellGenerationScopeV2 { principal_digest: [14; 32], agent_id: "agent".into(), cell_id: "cell".into(), run_id: "run".into() },
        manifest_digest: manifest.digest().unwrap(), generation: 1, writer_epoch: 1,
        revision: 0, state: vec![1], prefix: Vec::new(), stopped: false,
    };
    CellGenerationConfigV2 { manifest, initial, source_frontier: [15; 32], task_digest: [16; 32] }
}

#[test]
fn staged_genesis_is_synced_but_cannot_admit_resume_or_expose_active_snapshot() {
    let files = Files::new();
    let config = config();
    let binding = CellGenerationOwnerBindingV1::new(&config, /*max_records*/ 128).unwrap();
    let current = Arc::new(Current(Mutex::new((None, Some(binding.clone())))));
    let mut owner = CellGenerationJournalV2::open_guarded(files.file("journal"), files.witness(), config.clone(), /*max_records*/ 128, current.clone()).unwrap();
    let actual = owner.prepared_checkpoint().unwrap();
    assert_eq!(actual.binding(), &binding);
    assert_eq!(actual.checkpoint(), binding.genesis_checkpoint());
    let request = CellGenerationRequestV2 { operation_id: "step".into(), task_digest: config.task_digest, source_frontier: config.source_frontier, predecessor: config.initial.clone(), input: vec![2], admitted_at_micros: 10, deadline_micros: 100 };
    let bytes = files.bytes();
    assert_eq!(owner.admit(request.clone(), /*now_micros*/ 10), Err(CellGenerationErrorV2::Pending));
    assert_eq!(owner.resume(), Err(CellGenerationErrorV2::Pending));
    assert_eq!(owner.snapshot(), Err(CellGenerationErrorV2::Pending));
    assert_eq!(files.bytes(), bytes);
    *current.0.lock().unwrap() = (Some(binding), None);
    assert_eq!(owner.snapshot(), Ok(&config.initial));
    assert_eq!(owner.admit(request, /*now_micros*/ 10), Ok(None));
    assert!(owner.prepared_checkpoint().is_err());
}

#[test]
fn retired_guarded_journal_rejects_ordinary_open_and_live_recovery_without_changing_bytes() {
    let files = Files::new();
    let config = config();
    let binding = CellGenerationOwnerBindingV1::new(&config, /*max_records*/ 128).unwrap();
    let current = Arc::new(Current(Mutex::new((Some(binding.clone()), None))));
    let mut owner = CellGenerationJournalV2::open_guarded(files.file("journal"), files.witness(), config.clone(), /*max_records*/ 128, current.clone()).unwrap();
    owner.drain().unwrap();
    let bytes = files.bytes();
    *current.0.lock().unwrap() = (None, None);
    assert_eq!(owner.resume(), Err(CellGenerationErrorV2::InvalidBinding));
    assert_eq!(owner.recover(), Err(CellGenerationErrorV2::InvalidBinding));
    drop(owner);
    assert_eq!(CellGenerationJournalV2::open(files.file("journal"), files.witness(), config.clone(), /*max_records*/ 128).err(), Some(CellGenerationErrorV2::InvalidBinding));
    assert_eq!(CellGenerationJournalV2::open_guarded(files.file("journal"), files.witness(), config, /*max_records*/ 128, current).err(), Some(CellGenerationErrorV2::InvalidBinding));
    assert_eq!(files.bytes(), bytes);
}

#[test]
fn preparing_identity_cannot_import_a_nonempty_history() {
    let files = Files::new();
    let config = config();
    let binding = CellGenerationOwnerBindingV1::new(&config, /*max_records*/ 128).unwrap();
    let current = Arc::new(Current(Mutex::new((Some(binding.clone()), None))));
    let mut owner = CellGenerationJournalV2::open_guarded(files.file("journal"), files.witness(), config.clone(), /*max_records*/ 128, current.clone()).unwrap();
    owner.drain().unwrap();
    drop(owner);
    let bytes = files.bytes();
    *current.0.lock().unwrap() = (None, Some(binding));
    assert_eq!(CellGenerationJournalV2::open_guarded(files.file("journal"), files.witness(), config, /*max_records*/ 128, current).err(), Some(CellGenerationErrorV2::InvalidBinding));
    assert_eq!(files.bytes(), bytes);
}
