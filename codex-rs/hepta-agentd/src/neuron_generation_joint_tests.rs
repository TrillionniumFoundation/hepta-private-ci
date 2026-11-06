//! Actual synthetic Joint math through the normal generation service, existing
//! control file owner, Fleet identity, Cell journal and external anchor witness.
//! The fixed artificial tensors do not qualify any trained checkpoint/adoption.

use std::fs;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::Error as ControlError;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use tokio::time::sleep;
use tokio::time::timeout;

use super::support::Fixture;
use super::support::host;
use super::support::request;
use crate::NeuronGenerationRuntimeHandleV2;
use crate::RuntimeTasks;
use crate::neuron_generation_channel_v2;
use crate::neuron_generation_service::spawn_neuron_generation_service;

#[path = "../../hepta-neuron/tests/support/joint_synthetic.rs"]
mod synthetic;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;
type Clock = Arc<dyn Fn() -> u64 + Send + Sync>;

#[derive(Clone, Copy)]
enum Transport {
    OneShot,
    Resident,
}

fn install_model(
    fixture: &mut Fixture,
    clock: Clock,
    transport: Transport,
) -> TestResult<(Arc<JointGenerationProcessWorkerV1>, synthetic::Assets)> {
    let assets = synthetic::assets()?;
    let executable = PathBuf::from(
        std::env::var_os("NEXTEST_BIN_EXE_hepta-joint-propose")
            .or_else(|| std::env::var_os("NEXTEST_BIN_EXE_hepta_joint_propose"))
            .or_else(|| std::env::var_os("CARGO_BIN_EXE_hepta-joint-propose"))
            .or_else(|| std::env::var_os("CARGO_BIN_EXE_hepta_joint_propose"))
            .ok_or_else(|| std::io::Error::other("missing actual Joint compiler artifact"))?,
    );
    if !executable.is_absolute() {
        return Err(std::io::Error::other("Joint helper path must be absolute").into());
    }
    let executable_digest = Digest32::of_bytes(&fs::read(&executable)?).into_array();
    let weights_digest = Digest32::of_bytes(&assets.weights).into_array();
    let public_digest = Digest32::of_bytes(&assets.public).into_array();
    let source_digest =
        Digest32::of_bytes(b"explicit-synthetic-joint-process-fixture").into_array();
    let device_digest = JointGenerationProcessWorkerV1::observed_device_digest()?;
    let weights = fixture.directory.path().join("synthetic-weights.hps");
    let public = fixture.directory.path().join("synthetic-public.hps");
    fs::write(&weights, &assets.weights)?;
    fs::write(&public, &assets.public)?;
    let open = match transport {
        Transport::OneShot => JointGenerationProcessWorkerV1::open,
        Transport::Resident => JointGenerationProcessWorkerV1::open_resident,
    };
    let worker = Arc::new(open(
        JointGenerationProcessConfigV1 {
            executable,
            executable_digest,
            source_digest,
            weights,
            weights_digest,
            public,
            public_digest,
            device_digest,
        },
        clock,
    )?);
    let manifest = &mut fixture.config.manifest;
    manifest.profile = worker.profile().into();
    manifest.source_digest = source_digest;
    manifest.encoder = Some(worker.encoder_digest());
    manifest.head = Some(worker.head_digest());
    manifest.memory = Some(worker.memory_digest());
    manifest.decoder = Some(worker.decoder_digest());
    manifest.runtime_digest = executable_digest;
    manifest.device_digest = device_digest;
    manifest.input_schema = JointGenerationProcessWorkerV1::input_schema_digest();
    manifest.state_schema = JointGenerationProcessWorkerV1::state_schema_digest();
    manifest.output_schema = JointGenerationProcessWorkerV1::output_schema_digest();
    manifest.learning = CellLearningBindingV2::Frozen {
        weights: weights_digest,
    };
    manifest.max_input_bytes = 65_536;
    manifest.max_state_bytes = 65_536;
    manifest.max_delta_bytes = 65_536;
    manifest.max_prefix_bytes = 65_536;
    manifest.max_step_cost_entries = 8;
    manifest.max_ack_cost_entries = 1;
    fixture.config.initial.manifest_digest = manifest.digest()?;
    fixture.config.initial.state.clear();
    Ok((worker, assets))
}

async fn open_control(path: &Path) -> TestResult<DurableInferenceControl> {
    // Actor shutdown releases the existing file lock independently of the
    // service task. Observe that real release instead of assuming one yield.
    Ok(timeout(Duration::from_secs(5), async {
        loop {
            match DurableInferenceControl::open(path, /*capacity*/ 32) {
                Ok(control) => return Ok(control),
                Err(ControlError::WriterUnavailable) => sleep(Duration::from_millis(1)).await,
                Err(error) => return Err(error),
            }
        }
    })
    .await??)
}

async fn start_service(
    fixture: &Fixture,
    worker: Arc<JointGenerationProcessWorkerV1>,
    clock: Clock,
) -> TestResult<(NeuronGenerationRuntimeHandleV2, RuntimeTasks)> {
    let control = open_control(&fixture.directory.path().join("joint-control.log")).await?;
    let port = ControlledCellGenerationPortV2::spawn(
        control,
        ControlledCellGenerationConfigV2 {
            scope: fixture.config.initial.scope.clone(),
            manifest: fixture.config.manifest.clone(),
            worker_generation: fixture.identity.spawn_generation,
            queue_capacity: 4,
            rpc_timeout: Duration::from_secs(1),
        },
        worker,
        Arc::clone(&clock),
    )?;
    let (handle, bootstrap) = neuron_generation_channel_v2(
        &fixture.identity,
        fixture.journal(),
        port,
        move || clock(),
        /*capacity*/ 4,
    )?;
    let (mut tasks, lifetime) = host();
    spawn_neuron_generation_service(&mut tasks, bootstrap, Arc::clone(fixture.state()), lifetime)?;
    Ok((handle, tasks))
}

async fn execute(
    handle: &NeuronGenerationRuntimeHandleV2,
    clock: &Clock,
    public_digest: [u8; 32],
    operation: &str,
    command: JointGenerationCommandV1,
) -> TestResult<(CellGenerationRequestV2, CellGenerationReceiptV2)> {
    let mut original = request(operation, handle.snapshot().await?);
    original.input = serde_json::to_vec(&JointGenerationInputV1 {
        public_digest,
        command,
    })?;
    original.admitted_at_micros = clock();
    original.deadline_micros = original.admitted_at_micros + 30_000_000;
    let digest = original.digest()?;
    assert_eq!(
        handle.step(original.clone()).await,
        Err(CellGenerationErrorV2::Pending)
    );
    let receipt = timeout(Duration::from_secs(35), async {
        loop {
            match handle.reconcile(digest).await {
                Ok(receipt) => return Ok(receipt),
                Err(CellGenerationErrorV2::Pending) => sleep(Duration::from_millis(10)).await,
                Err(error) => return Err(error),
            }
        }
    })
    .await??;
    receipt.cost.validate()?;
    assert_eq!(receipt.request_digest, digest);
    assert_eq!(receipt.cost.entries().len(), 7);
    assert!(receipt.cost.entries().iter().all(|entry| {
        entry.accounting == CellCostAccountingV2::Exclusive
            && entry.metrics.wall_micros.is_some()
            && entry.metrics.cpu_micros.is_none()
            && entry.metrics.energy_microjoules.is_none()
    }));
    for stage in [
        CellCostStageV2::Encoder,
        CellCostStageV2::Inference,
        CellCostStageV2::Codec,
        CellCostStageV2::Planning,
        CellCostStageV2::Communication,
        CellCostStageV2::Queue,
        CellCostStageV2::Persistence,
    ] {
        assert!(
            receipt
                .cost
                .entries()
                .iter()
                .any(|entry| entry.stage == stage)
        );
    }
    assert!(receipt.cost.entries().iter().any(|entry| {
        entry
            .metrics
            .communication_bytes
            .is_some_and(|bytes| bytes > 4_778_904)
    }));
    Ok((original, receipt))
}

async fn deliver(
    handle: &NeuronGenerationRuntimeHandleV2,
    chunk: CellOutputChunkV2,
    fixture: &Fixture,
    sink: &mut Vec<u8>,
) -> TestResult {
    assert_eq!(chunk.prefix_offset, sink.len() as u64);
    let started = Instant::now();
    sink.extend(&chunk.bytes);
    let wall_micros = u64::try_from(started.elapsed().as_micros())?;
    let mut cost = CellTaskCostV2::new(CellTaskCostIdentityV2 {
        task_digest: fixture.config.task_digest,
        source_digest: fixture.config.manifest.source_digest,
    })?;
    cost.record(CellCostEntryV2 {
        event_id: Digest32::of_parts(&[b"actual-test-consumer-copy", &chunk.request_digest])
            .into_array(),
        identity: cost.identity(),
        stage: CellCostStageV2::Communication,
        outcome: CellCostOutcomeV2::Succeeded,
        accounting: CellCostAccountingV2::Exclusive,
        metrics: CellCostMetricsV2 {
            wall_micros: Some(wall_micros),
            communication_bytes: Some(chunk.bytes.len() as u64),
            ..CellCostMetricsV2::default()
        },
    })?;
    let acknowledgement = Digest32::of_parts(&[
        b"test-consumer-received",
        &chunk.request_digest,
        &chunk.bytes,
    ])
    .into_array();
    handle.acknowledge(chunk, acknowledgement, cost).await?;
    Ok(())
}

#[tokio::test]
async fn synthetic_joint_control_service_preserves_real_output_cost_and_owner_on_reopen()
-> TestResult {
    control_service_preserves_real_output_cost_and_owner_on_reopen(Transport::OneShot).await
}

#[tokio::test]
async fn resident_joint_control_service_preserves_real_output_cost_and_owner_on_reopen()
-> TestResult {
    control_service_preserves_real_output_cost_and_owner_on_reopen(Transport::Resident).await
}

async fn control_service_preserves_real_output_cost_and_owner_on_reopen(
    transport: Transport,
) -> TestResult {
    let mut fixture = Fixture::new().await;
    let epoch = Instant::now();
    // One real monotonic epoch is shared by owner, actor and process worker.
    let clock: Clock =
        Arc::new(move || u64::try_from(epoch.elapsed().as_micros()).unwrap_or(u64::MAX - 1) + 1);
    let (worker, assets) = install_model(&mut fixture, Arc::clone(&clock), transport)?;
    let public_digest = Digest32::of_bytes(&assets.public).into_array();
    let (handle, mut tasks) =
        start_service(&fixture, Arc::clone(&worker), Arc::clone(&clock)).await?;
    assert_eq!(handle.snapshot().await?, fixture.config.initial);
    let (_, initialized) = execute(
        &handle,
        &clock,
        public_digest,
        "joint-init",
        JointGenerationCommandV1::Init {
            seed: 17,
            sampler: JointGenerationSamplerV1::Mean,
        },
    )
    .await?;
    assert_eq!(
        initialized.disposition,
        CellGenerationDispositionV2::Advanced
    );
    let initial = handle.snapshot().await?;
    assert!(!initial.state.is_empty());
    assert!(initial.prefix.is_empty());
    assert_eq!(handle.pending_output().await?, None);
    let (_, advanced) = execute(
        &handle,
        &clock,
        public_digest,
        "joint-advance",
        JointGenerationCommandV1::Advance {
            action: JointGenerationActionV1::Shared,
        },
    )
    .await?;
    assert_eq!(advanced.disposition, CellGenerationDispositionV2::Advanced);
    assert_ne!(handle.snapshot().await?.state, initial.state);
    let (_, committed) = execute(
        &handle,
        &clock,
        public_digest,
        "joint-audio-prefix",
        JointGenerationCommandV1::Commit {
            modality: JointGenerationModalityV1::Audio,
            units: 16,
        },
    )
    .await?;
    assert_eq!(committed.disposition, CellGenerationDispositionV2::Advanced);
    let partial = handle.snapshot().await?;
    assert_eq!(
        synthetic::state(&partial.state, &partial.prefix, &assets)?.cursors,
        [0, 16, 0, 0]
    );
    let mut sink = Vec::new();
    let chunk = handle
        .pending_output()
        .await?
        .ok_or_else(|| std::io::Error::other("actual partial output"))?;
    deliver(&handle, chunk, &fixture, &mut sink).await?;
    let (stop_request, stopped) = execute(
        &handle,
        &clock,
        public_digest,
        "joint-stop",
        JointGenerationCommandV1::Advance {
            action: JointGenerationActionV1::Stop,
        },
    )
    .await?;
    assert_eq!(stopped.disposition, CellGenerationDispositionV2::Stopped);
    let snapshot = handle.snapshot().await?;
    let output = handle
        .pending_output()
        .await?
        .ok_or_else(|| std::io::Error::other("actual final output"))?;
    assert!(!output.bytes.is_empty());
    assert_eq!(snapshot.generation, fixture.config.initial.generation);
    assert_eq!(snapshot.writer_epoch, fixture.config.initial.writer_epoch);
    assert_eq!(snapshot.revision, 4);
    let facts = synthetic::state(&snapshot.state, &snapshot.prefix, &assets)?;
    assert_eq!(facts.cursors, synthetic::TOTAL_UNITS);
    assert!(facts.stopped);
    let decoded = synthetic::prefix(&snapshot.prefix)?;
    assert_eq!(decoded.bytes[0], vec![128; 768]);
    assert_eq!(decoded.bytes[1], vec![0; 2048]);
    assert_eq!(decoded.bytes[2], vec![128; 3072]);
    assert_eq!(decoded.bytes[3], b"action=0;sound=0\n");
    assert!(!handle.drain().await?);
    assert!(fixture.state().neuron_generation_drain_blockers()? > 0);
    let cost = handle.task_cost().await?;
    assert_eq!(cost.entries().len(), 29);
    let original_control = fs::read(fixture.directory.path().join("joint-control.log"))?;
    tasks.shutdown().await;
    assert!(tasks.failures().is_empty());
    drop(handle);
    fixture.reopen_state().await;
    let (handle, mut tasks) = start_service(&fixture, worker, clock).await?;
    assert_eq!(handle.snapshot().await?, snapshot);
    assert_eq!(handle.pending_output().await?, Some(output.clone()));
    assert_eq!(handle.pending_request().await?, None);
    assert_eq!(handle.task_cost().await?, cost);
    // Exact committed retry is journal readback; it cannot rerun STOP or charge
    // again. The existing control file remains byte-identical after reopen.
    assert_eq!(handle.step(stop_request).await?, stopped);
    assert_eq!(
        fs::read(fixture.directory.path().join("joint-control.log"))?,
        original_control
    );
    deliver(&handle, output, &fixture, &mut sink).await?;
    assert_eq!(sink, snapshot.prefix);
    assert!(handle.drain().await?);
    fixture.begin_drain();
    assert_eq!(handle.snapshot().await?, snapshot);
    assert_eq!(fixture.state().neuron_generation_drain_blockers()?, 0);
    let final_cost = handle.task_cost().await?;
    assert_eq!(final_cost.entries().len(), 30);
    tasks.shutdown().await;
    assert!(tasks.failures().is_empty());
    drop(handle);
    let journal = fixture.journal();
    assert!(journal.is_drained()?);
    assert_eq!(journal.snapshot()?, &snapshot);
    assert_eq!(journal.pending_output()?, None);
    assert_eq!(journal.task_cost()?, &final_cost);
    drop(open_control(&fixture.directory.path().join("joint-control.log")).await?);
    Ok(())
}
