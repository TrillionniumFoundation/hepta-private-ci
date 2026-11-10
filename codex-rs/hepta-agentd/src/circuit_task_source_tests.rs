//! Real source/Cell journals and Circuit execution. RunStart authentication and
//! model receipts are controlled fixtures, not original-owner custody evidence.

use std::fs;
use std::fs::OpenOptions;
use std::path::Path;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::CircuitCommandV2;
use codex_hepta_automation::CircuitEventV2;
use codex_hepta_contracts::AgentId;
use codex_hepta_learning_ledger::RunStartAdmissionBindingV1;
use codex_hepta_learning_ledger::RunStartAuthenticationV1;
use codex_hepta_learning_ledger::RunStartObjectiveDispositionV1;
use codex_hepta_learning_ledger::RunStartSnapshotV1;
use codex_hepta_neuron::CellJournalPartitionV1;
use codex_hepta_neuron::CellOwnerJournalV1;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::WitnessStoreError;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

use super::*;
use crate::AgentdCircuitCellOwnerV1;
use crate::circuit_cell::tests::configuration;
use crate::circuit_cell::tests::support as cell;
use crate::circuit_task::CircuitTaskModeV1;
use crate::circuit_task::driver::CircuitTaskDriverV1;

type Source = DurableCircuitTaskSourceV1<FileAnchorWitnessStore>;

fn opened(root: &Path, name: &str) -> anyhow::Result<File> {
    Ok(OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(root.join(name))?)
}

fn witness(root: &Path, name: &str) -> anyhow::Result<FileAnchorWitnessStore> {
    Ok(FileAnchorWitnessStore::open(
        opened(root, name)?,
        JournalScope {
            scope_digest: cell::d(name),
            objective_digest: cell::d("original ordinary source"),
        },
        Generation::new(7)?,
        /*max_records*/ 64,
    )?)
}

fn identity(root: &Path) -> anyhow::Result<AgentdIdentity> {
    let agent_id = AgentId::parse(cell::scope("A").agent_id.as_str())?;
    let fleet = HeptaFleetRoot::parse(root.join("fleet"))?;
    let layout = fleet.layout().agent(&agent_id);
    Ok(AgentdIdentity {
        agent_id,
        spawn_generation: 1,
        fleet_root: fleet.as_path().to_path_buf(),
        workspace: root.to_path_buf(),
        resources: codex_hepta_fleet::ResourceBudget::local_default(),
        home_root: layout.home_root().to_path_buf(),
        run_root: layout.run_root().to_path_buf(),
        control_socket: layout.agentd_control_socket().to_path_buf(),
        app_server_socket: layout.app_server_socket().to_path_buf(),
        layout,
    })
}

fn fence(identity: &AgentdIdentity) -> anyhow::Result<TaskFlowFence> {
    Ok(TaskFlowFence::new(
        identity.agent_id.clone(),
        "original-source-owner",
        /*owner_epoch*/ 1,
        /*generation*/ 7,
        "original-source-fence",
    )?)
}

fn source(run: &str, observation: &[u8]) -> CircuitTaskSourceInputV1 {
    let input = cell::input(run);
    CircuitTaskSourceInputV1 {
        scope: input.scope,
        source_frontier: input.source_frontier,
        objective_digest: input.objective_digest,
        ndu_snapshot_digest: input.ndu_snapshot_digest,
        monotonic_micros: input.monotonic_micros,
        deadline_micros: input.deadline_micros,
        observation: observation.to_vec(),
        candidates: input.candidates,
        lease_duration_ms: 2_000,
    }
}

fn record(run: &str) -> RunStartRecordV1 {
    RunStartRecordV1 {
        authentication: RunStartAuthenticationV1 {
            issuer_id: cell::id("fixture-issuer"),
            key_epoch: 1,
            message_id: cell::id(&format!("message:{run}")),
            sequence: 1,
            expires_at_ms: 1_010,
            scope_digest: cell::d("auth-scope"),
            signed_body_digest: cell::d("signed-body"),
            signature: [7; 64],
        },
        admission: RunStartAdmissionBindingV1 {
            profile_id: cell::id("profile"),
            profile_revision: 1,
            profile_digest: cell::d("profile"),
            supplied_source_digest: cell::d("supplied-source"),
            intent_digest: cell::d("intent"),
            admitted_source_digest: cell::d("admitted-source"),
            observed_at_unix_micros: 10_000,
            deadline_unix_micros: 1_010_000,
            authority: AuthorityPosture::DENY_ALL,
        },
        disposition: RunStartObjectiveDispositionV1::Compiled,
        snapshot: RunStartSnapshotV1 {
            run_id: cell::id(run),
            objective_digest: cell::d("objective"),
            hard_constraint_digest: cell::d("hard"),
            preference_state_digest: cell::d("preferences"),
            model_tuple_digest: cell::d("models"),
            prompt_registry_digest: cell::d("prompts"),
            artifact_set_digest: cell::d("artifacts"),
            authority_epoch: 1,
            generation: 7,
            fence_digest: cell::d("fence"),
        },
        runtime_body_digest: cell::d("body"),
        objective_semantic_bytes: b"objective".to_vec(),
        objective_function_v1_digest: cell::d("protocol"),
        objective_function_v1_bytes: b"protocol".to_vec(),
    }
}

fn registry() -> anyhow::Result<CircuitCellRegistryV1> {
    let (definition, bindings) = configuration();
    Ok(CircuitCellRegistryV1::new(definition, bindings)?)
}

fn cell_owner(
    root: &Path,
    inputs: &[CircuitTaskSourceInputV1],
) -> anyhow::Result<CellOwnerJournalV1<FileAnchorWitnessStore>> {
    Ok(CellOwnerJournalV1::open(
        opened(root, "cell-journal")?,
        witness(root, "cell-witness")?,
        inputs
            .iter()
            .map(|input| CellJournalPartitionV1 {
                scope: input.scope.clone(),
                definition: cell::definition(),
                source_frontier: input.source_frontier,
                writer_epoch: 1,
            })
            .collect(),
        /*max_records*/ 64,
    )?)
}

fn time() -> crate::CircuitCellTimeV1 {
    crate::CircuitCellTimeV1 {
        circuit_millis: 20,
        cell_micros: 20,
    }
}

#[tokio::test]
async fn ordinary_source_publishes_original_circuit_result_and_reopens_exact_inputs()
-> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let identity = identity(root.path())?;
    let fence = fence(&identity)?;
    let store = AutomationStore::open(&identity.layout).await?;
    let sources = vec![
        source("A", b"original input A"),
        source("C", b"different input C"),
    ];
    let owner = Source::create(
        opened(root.path(), "source-journal")?,
        witness(root.path(), "source-witness")?,
        &identity,
        &fence,
        &registry()?,
        sources.clone(),
    )?;
    let request = owner.build(&identity, &record("A"))?;
    let model = cell::Model::new(/*latency*/ 20, /*lose_response*/ false);
    let first_calls = Arc::clone(&model.calls);
    let mut driver = CircuitTaskDriverV1 {
        store: store.clone(),
        fence: fence.clone(),
        inputs: owner.clone(),
        cells: AgentdCircuitCellOwnerV1::new(
            registry()?,
            cell_owner(root.path(), &sources)?,
            model,
            cell::Encoder,
        ),
    };
    let receipt = driver
        .execute(&request, CircuitTaskModeV1::Drive, || Ok(time()))
        .await?;
    let mut changed = receipt.clone();
    let execution = changed
        .executions
        .values_mut()
        .next()
        .expect("one original Cell");
    let raw_decision_digest = Sha256Digest::for_bytes(&crate::circuit_cell_output::encode_receipt(
        &execution.decision,
    )?);
    assert_ne!(execution.completion.receipt_digest, raw_decision_digest);
    execution.completion.receipt_digest = raw_decision_digest;
    assert!(
        owner
            .publish_result(&identity, &record("A"), &changed)
            .is_err()
    );
    assert!(owner.read_publication(&identity, &record("A")).is_err());
    owner.publish_result(&identity, &record("A"), &receipt)?;
    let published = owner.read_publication(&identity, &record("A"))?;
    assert_eq!(
        owner.read_run_publication(&identity, &cell::id("A"))?,
        published
    );
    {
        let observer = owner.readback();
        assert_eq!(
            observer.read_publication(&identity, &record("A"))?,
            published
        );
        assert_eq!(
            observer.read_run_publication(&identity, &cell::id("A"))?,
            published
        );
    }
    assert!(
        owner
            .read_run_publication(&identity, &cell::id("C"))
            .is_err()
    );
    assert_eq!(published.original_record(), &record("A"));
    assert_eq!(published.input().observation, sources[0].observation);
    assert_eq!(
        published.output(),
        receipt
            .executions()
            .values()
            .next()
            .expect("one Cell")
            .output
    );
    assert_eq!(published.history_digest(), receipt.trace().history_digest());
    assert_eq!(first_calls.load(Ordering::SeqCst), 1);
    drop(driver);
    drop(owner);
    let original_files = [
        "source-journal",
        "source-witness",
        "cell-journal",
        "cell-witness",
    ]
    .map(|name| fs::read(root.path().join(name)).expect("original files"));
    let reopened = Source::recover(
        opened(root.path(), "source-journal")?,
        witness(root.path(), "source-witness")?,
        &identity,
        &fence,
        &registry()?,
        sources.clone(),
    )?;
    assert_eq!(
        reopened.read_publication(&identity, &record("A"))?,
        published
    );
    assert_eq!(
        reopened.read_run_publication(&identity, &cell::id("A"))?,
        published
    );
    assert_eq!(reopened.build(&identity, &record("A"))?, request);
    let model = cell::Model::new(/*latency*/ 20, /*lose_response*/ false);
    let recovered_calls = Arc::clone(&model.calls);
    let mut driver = CircuitTaskDriverV1 {
        store: store.clone(),
        fence: fence.clone(),
        inputs: reopened.clone(),
        cells: AgentdCircuitCellOwnerV1::new(
            registry()?,
            cell_owner(root.path(), &sources)?,
            model,
            cell::Encoder,
        ),
    };
    let recovered = driver
        .execute(&request, CircuitTaskModeV1::Readback, || Ok(time()))
        .await?;
    assert_eq!(recovered, receipt);
    reopened.publish_result(&identity, &record("A"), &recovered)?;
    assert_eq!(recovered_calls.load(Ordering::SeqCst), 0);
    assert_eq!(
        [
            "source-journal",
            "source-witness",
            "cell-journal",
            "cell-witness"
        ]
        .map(|name| fs::read(root.path().join(name)).expect("same files")),
        original_files
    );
    let next = reopened.build(&identity, &record("C"))?;
    let next_receipt = driver
        .execute(&next, CircuitTaskModeV1::Drive, || Ok(time()))
        .await?;
    reopened.publish_result(&identity, &record("C"), &next_receipt)?;
    let next_publication = reopened.read_publication(&identity, &record("C"))?;
    assert_eq!(next_publication.input().observation, sources[1].observation);
    assert_ne!(
        next_publication.publication_digest(),
        published.publication_digest()
    );
    assert_eq!(recovered_calls.load(Ordering::SeqCst), 1);
    {
        let observer = reopened.readback();
        assert_eq!(
            observer.read_run_publication(&identity, &cell::id("C"))?,
            next_publication
        );
        reopened.withdraw_source(&cell::id("C"))?;
        assert!(
            observer
                .read_run_publication(&identity, &cell::id("C"))
                .is_err()
        );
        assert!(observer.read_publication(&identity, &record("C")).is_err());
    }
    drop(driver);
    drop(reopened);
    store.close().await;
    Ok(())
}

async fn dispatch(
    store: &AutomationStore,
    fence: &TaskFlowFence,
    request: &CircuitTaskRequestV1,
) -> anyhow::Result<CircuitDispatchV2> {
    let created = store
        .create_bounded_circuit_run(registry()?.definition(), &request.start, fence)
        .await?;
    let advanced = store
        .apply_bounded_circuit_command(&CircuitCommandV2 {
            run_id: request.start.run_id.clone(),
            command_id: "advance".into(),
            fence: fence.clone(),
            expected_revision: created.run.revision(),
            now_ms: 20,
            event: CircuitEventV2::Advance { quantum: 1 },
        })
        .await?;
    Ok(advanced.dispatches[0].clone())
}

#[tokio::test]
async fn ordinary_source_rejects_rebound_record_dispatch_source_and_torn_history()
-> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let identity = identity(root.path())?;
    let fence = fence(&identity)?;
    let store = AutomationStore::open(&identity.layout).await?;
    let sources = vec![source("A", b"source A")];
    let mut owner = Source::create(
        opened(root.path(), "source-journal")?,
        witness(root.path(), "source-witness")?,
        &identity,
        &fence,
        &registry()?,
        sources.clone(),
    )?;
    let original = record("A");
    let request = owner.build(&identity, &original)?;
    let dispatch = dispatch(&store, &fence, &request).await?;
    let before = fs::read(root.path().join("source-journal"))?;
    assert_eq!(
        owner.resolve(
            &request,
            &dispatch,
            &BTreeMap::new(),
            CircuitTaskInputModeV1::Readback
        ),
        Err(Error::ReconciliationRequired)
    );
    assert!(owner.read_publication(&identity, &original).is_err());
    assert_eq!(fs::read(root.path().join("source-journal"))?, before);
    let input = owner.resolve(
        &request,
        &dispatch,
        &BTreeMap::new(),
        CircuitTaskInputModeV1::Prepare,
    )?;
    let retained = fs::read(root.path().join("source-journal"))?;
    let alterations: [fn(&mut RunStartRecordV1); 5] = [
        |r: &mut RunStartRecordV1| r.authentication.signature[0] ^= 1,
        |r: &mut RunStartRecordV1| r.admission.admitted_source_digest = cell::d("replacement"),
        |r: &mut RunStartRecordV1| r.snapshot.preference_state_digest = cell::d("replacement"),
        |r: &mut RunStartRecordV1| r.snapshot.generation += 1,
        |r: &mut RunStartRecordV1| r.objective_function_v1_bytes.push(0),
    ];
    for alter in alterations {
        let mut changed = original.clone();
        alter(&mut changed);
        assert!(owner.build(&identity, &changed).is_err());
    }
    let mut changed = dispatch.clone();
    changed.invocation_digest = Sha256Digest::for_bytes(b"other invocation");
    assert_eq!(
        owner.resolve(
            &request,
            &changed,
            &BTreeMap::new(),
            CircuitTaskInputModeV1::Prepare
        ),
        Err(Error::InvalidBinding)
    );
    assert_eq!(
        owner.resolve(
            &request,
            &dispatch,
            &BTreeMap::new(),
            CircuitTaskInputModeV1::Readback
        )?,
        input
    );
    assert_eq!(fs::read(root.path().join("source-journal"))?, retained);
    drop(owner);
    let mut substituted = sources.clone();
    substituted[0].candidates[0].allowed = false;
    assert!(
        Source::recover(
            opened(root.path(), "source-journal")?,
            witness(root.path(), "source-witness")?,
            &identity,
            &fence,
            &registry()?,
            substituted
        )
        .is_err()
    );
    assert_eq!(fs::read(root.path().join("source-journal"))?, retained);
    use std::io::Write;
    OpenOptions::new()
        .append(true)
        .open(root.path().join("source-journal"))?
        .write_all(&[1])?;
    let torn = fs::read(root.path().join("source-journal"))?;
    assert!(
        Source::recover(
            opened(root.path(), "source-journal")?,
            witness(root.path(), "source-witness")?,
            &identity,
            &fence,
            &registry()?,
            sources
        )
        .is_err()
    );
    assert_eq!(fs::read(root.path().join("source-journal"))?, torn);
    store.close().await;
    Ok(())
}

struct LostAckWitness {
    original: FileAnchorWitnessStore,
    fail_sequence: Arc<AtomicU64>,
    failure: WitnessFailure,
}
#[derive(Clone, Copy)]
enum WitnessFailure {
    BeforeWrite,
    AfterWrite,
}
impl AnchorWitnessStore for LostAckWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.original.current()
    }
    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        let fail = self.fail_sequence.load(Ordering::SeqCst) == next.sequence;
        if fail && matches!(self.failure, WitnessFailure::BeforeWrite) {
            self.fail_sequence.store(0, Ordering::SeqCst);
            return Err(WitnessStoreError::Io(std::io::ErrorKind::BrokenPipe));
        }
        self.original.compare_and_swap(expected, next)?;
        if fail {
            self.fail_sequence.store(0, Ordering::SeqCst);
            return Err(WitnessStoreError::Io(std::io::ErrorKind::BrokenPipe));
        }
        Ok(())
    }
}

#[test]
fn ordinary_source_withdrawal_and_uncertain_withdrawal_survive_reopen() -> anyhow::Result<()> {
    for fail_sequence in [0, 2, 3] {
        let root = tempfile::tempdir()?;
        let identity = identity(root.path())?;
        let fence = fence(&identity)?;
        let sources = vec![source("A", b"withdrawn source")];
        let owner = DurableCircuitTaskSourceV1::create(
            opened(root.path(), "source-journal")?,
            LostAckWitness {
                original: witness(root.path(), "source-witness")?,
                fail_sequence: Arc::new(AtomicU64::new(fail_sequence)),
                failure: WitnessFailure::BeforeWrite,
            },
            &identity,
            &fence,
            &registry()?,
            sources.clone(),
        )?;
        assert_eq!(
            owner.withdraw_source(&cell::id("A")).is_ok(),
            fail_sequence == 0
        );
        assert!(owner.build(&identity, &record("A")).is_err());
        drop(owner);
        let bytes = fs::read(root.path().join("source-journal"))?;
        let reopened = Source::recover(
            opened(root.path(), "source-journal")?,
            witness(root.path(), "source-witness")?,
            &identity,
            &fence,
            &registry()?,
            sources,
        )?;
        assert!(reopened.build(&identity, &record("A")).is_err());
        assert!(reopened.read_publication(&identity, &record("A")).is_err());
        assert!(
            reopened
                .read_run_publication(&identity, &cell::id("A"))
                .is_err()
        );
        assert_eq!(fs::read(root.path().join("source-journal"))?, bytes);
    }
    Ok(())
}

#[test]
fn ordinary_source_lost_admission_ack_remains_pending_and_completed_ack_is_read_only()
-> anyhow::Result<()> {
    for (fail_sequence, failure) in [2, 3].into_iter().flat_map(|sequence| {
        [WitnessFailure::BeforeWrite, WitnessFailure::AfterWrite]
            .into_iter()
            .map(move |failure| (sequence, failure))
    }) {
        let root = tempfile::tempdir()?;
        let identity = identity(root.path())?;
        let fence = fence(&identity)?;
        let sources = vec![source("A", b"input")];
        let owner = DurableCircuitTaskSourceV1::create(
            opened(root.path(), "source-journal")?,
            LostAckWitness {
                original: witness(root.path(), "source-witness")?,
                fail_sequence: Arc::new(AtomicU64::new(fail_sequence)),
                failure,
            },
            &identity,
            &fence,
            &registry()?,
            sources.clone(),
        )?;
        assert!(owner.build(&identity, &record("A")).is_err());
        assert!(owner.build(&identity, &record("A")).is_err());
        drop(owner);
        let bytes = fs::read(root.path().join("source-journal"))?;
        let recovered = Source::recover(
            opened(root.path(), "source-journal")?,
            witness(root.path(), "source-witness")?,
            &identity,
            &fence,
            &registry()?,
            sources,
        )?;
        if fail_sequence == 2 {
            assert!(recovered.build(&identity, &record("A")).is_err());
        } else {
            assert!(recovered.build(&identity, &record("A")).is_ok());
        }
        assert!(recovered.read_publication(&identity, &record("A")).is_err());
        assert_eq!(fs::read(root.path().join("source-journal"))?, bytes);
    }
    Ok(())
}

#[tokio::test]
async fn ordinary_source_input_and_result_ack_loss_never_repeat_committed_inference()
-> anyhow::Result<()> {
    for (fail_sequence, failure) in [4, 5, 6, 7].into_iter().flat_map(|sequence| {
        [WitnessFailure::BeforeWrite, WitnessFailure::AfterWrite]
            .into_iter()
            .map(move |failure| (sequence, failure))
    }) {
        let root = tempfile::tempdir()?;
        let identity = identity(root.path())?;
        let fence = fence(&identity)?;
        let store = AutomationStore::open(&identity.layout).await?;
        let sources = vec![source("A", b"original retained input")];
        let owner = DurableCircuitTaskSourceV1::create(
            opened(root.path(), "source-journal")?,
            LostAckWitness {
                original: witness(root.path(), "source-witness")?,
                fail_sequence: Arc::new(AtomicU64::new(fail_sequence)),
                failure,
            },
            &identity,
            &fence,
            &registry()?,
            sources.clone(),
        )?;
        let request = owner.build(&identity, &record("A"))?;
        let model = cell::Model::new(/*latency*/ 20, /*lose_response*/ false);
        let first_calls = Arc::clone(&model.calls);
        let mut driver = CircuitTaskDriverV1 {
            store: store.clone(),
            fence: fence.clone(),
            inputs: owner.clone(),
            cells: AgentdCircuitCellOwnerV1::new(
                registry()?,
                cell_owner(root.path(), &sources)?,
                model,
                cell::Encoder,
            ),
        };
        let original = driver
            .execute(&request, CircuitTaskModeV1::Drive, || Ok(time()))
            .await;
        if fail_sequence <= 5 {
            assert_eq!(original, Err(Error::CommitUncertain));
            assert_eq!(first_calls.load(Ordering::SeqCst), 0);
        } else {
            assert!(
                owner
                    .publish_result(
                        &identity,
                        &record("A"),
                        original.as_ref().expect("committed task")
                    )
                    .is_err()
            );
            assert_eq!(first_calls.load(Ordering::SeqCst), 1);
        }
        drop(driver);
        drop(owner);
        let unchanged = fs::read(root.path().join("source-journal"))?;
        let reopened = Source::recover(
            opened(root.path(), "source-journal")?,
            witness(root.path(), "source-witness")?,
            &identity,
            &fence,
            &registry()?,
            sources.clone(),
        )?;
        assert_eq!(fs::read(root.path().join("source-journal"))?, unchanged);
        let model = cell::Model::new(/*latency*/ 20, /*lose_response*/ false);
        let recovered_calls = Arc::clone(&model.calls);
        let mut driver = CircuitTaskDriverV1 {
            store: store.clone(),
            fence: fence.clone(),
            inputs: reopened.clone(),
            cells: AgentdCircuitCellOwnerV1::new(
                registry()?,
                cell_owner(root.path(), &sources)?,
                model,
                cell::Encoder,
            ),
        };
        if fail_sequence == 4 {
            assert_eq!(
                driver
                    .execute(&request, CircuitTaskModeV1::Drive, || Ok(time()))
                    .await,
                Err(Error::ReconciliationRequired)
            );
            assert!(reopened.read_publication(&identity, &record("A")).is_err());
        } else {
            let mode = if fail_sequence == 5 {
                CircuitTaskModeV1::Drive
            } else {
                CircuitTaskModeV1::Readback
            };
            let recovered = driver.execute(&request, mode, || Ok(time())).await?;
            if let Ok(original) = original {
                assert_eq!(recovered, original);
            }
            let publication = reopened.publish_result(&identity, &record("A"), &recovered);
            if fail_sequence == 6 {
                assert!(publication.is_err());
                assert!(reopened.read_publication(&identity, &record("A")).is_err());
            } else {
                publication?;
                assert_eq!(
                    reopened
                        .read_publication(&identity, &record("A"))?
                        .history_digest(),
                    recovered.trace().history_digest()
                );
            }
        }
        assert_eq!(
            recovered_calls.load(Ordering::SeqCst),
            usize::from(fail_sequence == 5)
        );
        if fail_sequence != 5 {
            assert_eq!(fs::read(root.path().join("source-journal"))?, unchanged);
        }
        drop(driver);
        drop(reopened);
        store.close().await;
    }
    Ok(())
}
