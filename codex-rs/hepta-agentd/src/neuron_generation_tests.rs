use std::fs;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

use super::AgentdNeuronGenerationOwnerV2;

fn checked<T, E: std::fmt::Debug>(value: Result<T, E>) -> T {
    match value {
        Ok(value) => value,
        Err(error) => panic!("fixture: {error:?}"),
    }
}

static NEXT: AtomicU64 = AtomicU64::new(0);
struct Fixture(PathBuf);
impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let path =
            std::env::temp_dir().join(format!("agentd-generation-{}-{serial}", std::process::id()));
        checked(fs::create_dir(&path));
        Self(path)
    }
    fn owner(&self, model: Model) -> AgentdNeuronGenerationOwnerV2<FileAnchorWitnessStore, Model> {
        self.owner_with_bundle(model, None)
    }
    fn owner_with_bundle(
        &self,
        model: Model,
        artifact: Option<&codex_hepta_learning_artifacts::CellCompatibilityBundleV1>,
    ) -> AgentdNeuronGenerationOwnerV2<FileAnchorWitnessStore, Model> {
        self.owner_with_cell(model, artifact, "cell")
    }
    fn owner_with_cell(
        &self,
        model: Model,
        artifact: Option<&codex_hepta_learning_artifacts::CellCompatibilityBundleV1>,
        cell: &str,
    ) -> AgentdNeuronGenerationOwnerV2<FileAnchorWitnessStore, Model> {
        let file = |name: &str| {
            checked(
                OpenOptions::new()
                    .create(true)
                    .truncate(false)
                    .read(true)
                    .write(true)
                    .open(self.0.join(name)),
            )
        };
        let witness = checked(FileAnchorWitnessStore::open(
            file("witness"),
            JournalScope {
                scope_digest: Digest32::of_bytes(b"host"),
                objective_digest: Digest32::of_bytes(b"task"),
            },
            checked(Generation::new(1)),
            /*max_records*/ 64,
        ));
        let mut manifest = CellBackendManifestV2 {
            profile: "host-generation-fixture".to_string(),
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
            max_input_bytes: 64,
            max_state_bytes: 64,
            max_delta_bytes: 64,
            max_prefix_bytes: 256,
            max_step_cost_entries: 32,
            max_ack_cost_entries: 16,
        };
        if let Some(artifact) = artifact {
            manifest.bundle_digest = checked(artifact.digest()).into_array();
        }
        let initial = CellRuntimeSnapshotV2 {
            scope: CellGenerationScopeV2 {
                principal_digest: [15; 32],
                agent_id: "agent".to_string(),
                cell_id: cell.to_string(),
                run_id: "run".to_string(),
            },
            manifest_digest: checked(manifest.digest()),
            generation: 1,
            writer_epoch: 1,
            revision: 0,
            state: vec![0],
            prefix: Vec::new(),
            stopped: false,
        };
        let journal = checked(CellGenerationJournalV2::open(
            file("journal"),
            witness,
            CellGenerationConfigV2 {
                manifest,
                initial,
                source_frontier: [16; 32],
                task_digest: [17; 32],
            },
            /*max_records*/ 64,
        ));
        AgentdNeuronGenerationOwnerV2::new(journal, model)
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[derive(Clone, Default)]
struct Model {
    calls: Arc<AtomicUsize>,
    cancellations: Arc<AtomicUsize>,
    stored: Arc<Mutex<Option<CellGenerationProposalV2>>>,
    lose_response: bool,
    wrong_bundle: bool,
}
impl CellGenerationControlPortV2 for Model {
    fn execute_generation(
        &mut self,
        manifest: &CellBackendManifestV2,
        request: &CellGenerationRequestV2,
    ) -> Result<CellGenerationProposalV2, CellGenerationErrorV2> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        let mut cost = checked(CellTaskCostV2::new(CellTaskCostIdentityV2 {
            task_digest: request.task_digest,
            source_digest: manifest.source_digest,
        }));
        checked(cost.record(CellCostEntryV2 {
            event_id: checked(request.digest()),
            identity: cost.identity(),
            stage: CellCostStageV2::Inference,
            outcome: CellCostOutcomeV2::Succeeded,
            accounting: CellCostAccountingV2::Exclusive,
            metrics: CellCostMetricsV2 {
                cpu_micros: Some(4),
                ..CellCostMetricsV2::default()
            },
        }));
        let proposal = CellGenerationProposalV2 {
            request_digest: checked(request.digest()),
            bundle_digest: if self.wrong_bundle {
                [99; 32]
            } else {
                manifest.bundle_digest
            },
            runtime_digest: manifest.runtime_digest,
            device_digest: manifest.device_digest,
            successor_state: vec![1],
            output_delta: "原样🙂\n".as_bytes().to_vec(),
            disposition: CellGenerationDispositionV2::Advanced,
            cost,
        };
        *checked(self.stored.lock()) = Some(proposal.clone());
        if self.lose_response {
            Err(CellGenerationErrorV2::Unavailable)
        } else {
            Ok(proposal)
        }
    }
    fn read_generation(
        &mut self,
        request: &CellGenerationRequestV2,
    ) -> Result<Option<CellGenerationProposalV2>, CellGenerationErrorV2> {
        Ok(checked(self.stored.lock())
            .as_ref()
            .filter(|p| p.request_digest == checked(request.digest()))
            .cloned())
    }
    fn cancel_generation(
        &mut self,
        _: &CellGenerationRequestV2,
    ) -> Result<(), CellGenerationErrorV2> {
        self.cancellations.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }
}

fn request(
    owner: &AgentdNeuronGenerationOwnerV2<FileAnchorWitnessStore, Model>,
) -> CellGenerationRequestV2 {
    CellGenerationRequestV2 {
        operation_id: "generation-one".to_string(),
        task_digest: [17; 32],
        source_frontier: [16; 32],
        predecessor: checked(owner.journal().snapshot()).clone(),
        input: vec![1],
        admitted_at_micros: 10,
        deadline_micros: 100,
    }
}

#[test]
fn ordinary_owner_reopen_reads_original_worker_and_committed_prefix_without_dispatch() {
    let fixture = Fixture::new();
    let model = Model {
        lose_response: true,
        ..Model::default()
    };
    let mut owner = fixture.owner(model.clone());
    let request = request(&owner);
    assert_eq!(
        owner.step(request.clone(), || 11),
        Err(CellGenerationErrorV2::Unavailable)
    );
    drop(owner);
    let mut owner = fixture.owner(model.clone());
    let receipt = checked(owner.step(request.clone(), || 20));
    assert_eq!(model.calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        checked(owner.journal().snapshot()).prefix,
        "原样🙂\n".as_bytes()
    );
    assert_eq!(checked(owner.step(request.clone(), || 500)), receipt);
    assert_eq!(checked(owner.drain()), false);
    let chunk = checked(owner.journal().pending_output()).cloned();
    let Some(chunk) = chunk else {
        panic!("committed outbox");
    };
    let cost = checked(CellTaskCostV2::new(receipt.cost.identity()));
    checked(owner.journal_mut().acknowledge(chunk, [1; 32], cost));
    assert_eq!(checked(owner.drain()), true);
    drop(owner);
    let mut owner = fixture.owner(model.clone());
    assert_eq!(checked(owner.step(request, || 600)), receipt);
    assert_eq!(model.calls.load(Ordering::SeqCst), 1);
}

#[test]
fn cancel_and_drain_survive_reopen_and_retain_actual_worker_cost() {
    let fixture = Fixture::new();
    let model = Model {
        lose_response: true,
        ..Model::default()
    };
    let mut owner = fixture.owner(model.clone());
    let req = request(&owner);
    assert_eq!(
        owner.step(req, || 11),
        Err(CellGenerationErrorV2::Unavailable)
    );
    checked(owner.cancel_pending());
    assert!(!checked(owner.drain()));
    drop(owner);
    let mut owner = fixture.owner(model.clone());
    let receipt = checked(owner.reconcile(|| 20));
    assert_eq!(receipt.disposition, CellGenerationDispositionV2::Cancelled);
    assert_eq!(checked(owner.journal().snapshot()).state, vec![0]);
    assert_eq!(checked(owner.journal().pending_output()), None);
    assert_eq!(
        checked(owner.journal().task_cost()).entries()[0]
            .metrics
            .cpu_micros,
        Some(4)
    );
    assert!(checked(owner.drain()));
    assert_eq!(model.calls.load(Ordering::SeqCst), 1);
    assert_eq!(model.cancellations.load(Ordering::SeqCst), 1);
}

#[test]
fn expiration_during_admission_settles_known_no_contact_without_calling_model() {
    let fixture = Fixture::new();
    let model = Model::default();
    let mut owner = fixture.owner(model.clone());
    let req = request(&owner);
    let mut times = [11, 100].into_iter();
    let receipt = checked(owner.step(req, || times.next().unwrap_or(100)));
    assert_eq!(
        receipt.disposition,
        CellGenerationDispositionV2::DeadlineExceeded
    );
    assert_eq!(model.calls.load(Ordering::SeqCst), 0);
    assert_eq!(checked(owner.journal().pending_request()), None);
    assert_eq!(checked(receipt.cost.summary()).complete_metrics(), None);
    assert!(checked(owner.drain()));
}

#[test]
fn changed_model_identity_remains_pending_with_no_published_prefix() {
    let fixture = Fixture::new();
    let model = Model {
        wrong_bundle: true,
        ..Model::default()
    };
    let mut owner = fixture.owner(model.clone());
    let req = request(&owner);
    assert_eq!(
        owner.step(req.clone(), || 11),
        Err(CellGenerationErrorV2::InvalidBinding)
    );
    assert_eq!(
        owner.step(req, || 20),
        Err(CellGenerationErrorV2::InvalidBinding)
    );
    assert_eq!(model.calls.load(Ordering::SeqCst), 1);
    assert!(checked(owner.journal().snapshot()).prefix.is_empty());
    assert!(!checked(owner.drain()));
}

#[test]
fn lost_response_retains_precontact_clock_floor_across_host_reopen() {
    let fixture = Fixture::new();
    let model = Model {
        lose_response: true,
        ..Model::default()
    };
    let mut owner = fixture.owner(model.clone());
    let req = request(&owner);
    let mut times = [11, 90].into_iter();
    assert_eq!(
        owner.step(req.clone(), || times.next().unwrap_or(90)),
        Err(CellGenerationErrorV2::Unavailable)
    );
    drop(owner);
    let mut owner = fixture.owner(model.clone());
    assert_eq!(
        owner.step(req.clone(), || 20),
        Err(CellGenerationErrorV2::Deadline)
    );
    assert!(checked(owner.journal().snapshot()).prefix.is_empty());
    assert_eq!(
        checked(owner.step(req, || 91)).disposition,
        CellGenerationDispositionV2::Advanced
    );
    assert_eq!(model.calls.load(Ordering::SeqCst), 1);
}

#[path = "neuron_generation_population_tests.rs"]
mod population;
