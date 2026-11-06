//! Synthetic and recovered historical Joint math through the normal generation
//! service, existing control owner, Fleet identity, journal and external witness.
//! Lifecycle correctness does not qualify natural-task quality or adoption.

use std::fs;
use std::path::Path;
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

#[path = "neuron_generation_joint_cancel_tests.rs"]
mod cancellation;
#[path = "../../hepta-neuron/tests/support/joint_synthetic.rs"]
mod synthetic;
#[path = "../../hepta-neuron/tests/support/joint_trained.rs"]
mod trained;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;
type Clock = Arc<dyn Fn() -> u64 + Send + Sync>;

#[derive(Clone, Copy)]
enum ModelFixture {
    Synthetic,
    HistoricalTrained,
}

fn evidence_directory(prefix: &str) -> TestResult<tempfile::TempDir> {
    let mut builder = tempfile::Builder::new();
    builder.prefix(prefix);
    Ok(match std::env::var_os("HEPTA_JOINT_TRAINED_EVIDENCE_DIR") {
        Some(parent) => {
            fs::create_dir_all(&parent)?;
            builder.tempdir_in(parent)?
        }
        None => builder.tempdir()?,
    })
}

fn install_model(
    fixture: &mut Fixture,
    clock: Clock,
    model: ModelFixture,
) -> TestResult<(Arc<JointGenerationProcessWorkerV1>, synthetic::Assets)> {
    let (assets, source_digest) = match model {
        ModelFixture::Synthetic => (
            synthetic::assets()?,
            Digest32::of_bytes(b"explicit-synthetic-joint-process-fixture").into_array(),
        ),
        ModelFixture::HistoricalTrained => (
            trained::assets()?,
            Digest32::of_bytes(trained::PROVENANCE.as_bytes()).into_array(),
        ),
    };
    let executable = codex_utils_cargo_bin::cargo_bin("hepta-joint-propose")?;
    if !executable.is_absolute() {
        return Err(std::io::Error::other("Joint helper path must be absolute").into());
    }
    let executable_digest = Digest32::of_bytes(&fs::read(&executable)?).into_array();
    let weights_digest = Digest32::of_bytes(&assets.weights).into_array();
    let public_digest = Digest32::of_bytes(&assets.public).into_array();
    let device_digest = JointGenerationProcessWorkerV1::observed_device_digest()?;
    let weights = fixture.directory.path().join("joint-weights.hps");
    let public = fixture.directory.path().join("joint-public.hps");
    fs::write(&weights, &assets.weights)?;
    fs::write(&public, &assets.public)?;
    let worker = Arc::new(JointGenerationProcessWorkerV1::open(
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
    manifest.profile = JointGenerationProcessWorkerV1::PROFILE.into();
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
    execute_request(handle, original).await
}

async fn execute_request(
    handle: &NeuronGenerationRuntimeHandleV2,
    original: CellGenerationRequestV2,
) -> TestResult<(CellGenerationRequestV2, CellGenerationReceiptV2)> {
    assert_eq!(
        handle.step(original.clone()).await,
        Err(CellGenerationErrorV2::Pending)
    );
    settle_request(handle, original).await
}

async fn settle_request(
    handle: &NeuronGenerationRuntimeHandleV2,
    original: CellGenerationRequestV2,
) -> TestResult<(CellGenerationRequestV2, CellGenerationReceiptV2)> {
    let digest = original.digest()?;
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

#[tokio::test]
async fn frozen_ndu_plan_executes_real_joint_worker_and_exports_settled_episode() -> TestResult {
    use codex_hepta_intelligence::*;
    use codex_hepta_ndu::*;
    use codex_hepta_types::FixedQ32;
    use codex_hepta_types::Generation;
    use codex_hepta_types::StableId;

    let id = |value: &str| StableId::new(value);
    let mut fixture = Fixture::new().await;
    let epoch = Instant::now();
    let clock: Clock =
        Arc::new(move || u64::try_from(epoch.elapsed().as_micros()).unwrap_or(u64::MAX - 1) + 1);
    let (worker, assets) =
        install_model(&mut fixture, Arc::clone(&clock), ModelFixture::Synthetic)?;
    let public_digest = Digest32::of_bytes(&assets.public).into_array();
    let utility = UtilityProfile {
        profile_id: id("joint-planning-qualification")?,
        axis_registry_digest: Digest32::of_bytes(b"qualification-quality-axis"),
        normalization_manifest_digest: Digest32::of_bytes(b"qualification-q32-units"),
        dimensions: vec![(id("quality")?, AxisDirection::Maximize)],
        risk_ceilings: Vec::new(),
        resource_ceilings: Vec::new(),
        required_organs: RequiredOrganSet {
            organ_ids: vec![id("planner")?],
        },
    };
    let policy = legacy_evaluation_policy(&utility)?;
    let profile = JointGenerationPlanningProfileV1 {
        utility,
        policy,
        scalarization: None,
    };
    let frozen = FrozenGenerationEpisodeV1::new(FrozenGenerationEpisodeInputV1 {
        episode_id: id("joint-episode")?,
        run_id: id(&fixture.config.initial.scope.run_id)?,
        decision_id: id("joint-decision")?,
        objective_digest: Digest32::of_bytes(b"joint-explicit-objective"),
        policy_digest: profile.digest()?,
        evaluation_profile_digest: Digest32::of_bytes(b"independent-output-evaluation"),
        sampler_digest: joint_generation_sampler_digest_v1(
            public_digest,
            /*seed*/ 17,
            JointGenerationSamplerV1::Mean,
        )?,
        source_frontier: Digest32::from_array(fixture.config.source_frontier),
        initial: fixture.config.initial.clone(),
    })?;
    fixture.config.task_digest = frozen.task_digest().into_array();
    let plan = JointGenerationEpisodePlanV1::new(
        frozen.clone(),
        public_digest,
        /*seed*/ 17,
        JointGenerationSamplerV1::Mean,
        profile,
    )?;
    let next = |name: &str| -> TestResult<JointGenerationStepV1> {
        let now = clock();
        Ok(JointGenerationStepV1 {
            operation_id: id(name)?,
            planning_attempt_id: id(&format!("plan-{name}"))?,
            admitted_at_micros: now,
            deadline_micros: now + 30_000_000,
        })
    };
    let (handle, mut tasks) =
        start_service(&fixture, Arc::clone(&worker), Arc::clone(&clock)).await?;
    let init = plan.initialize(&handle.observe_generation().await?, next("bound-init")?)?;
    execute_request(&handle, init).await?;
    let mut planning_costs = Vec::new();
    let mut final_step = None;
    for preferred in ["shared", "stop"] {
        let observed = handle.observe_generation().await?;
        assert!(!observed.snapshot().state.is_empty());
        let generation = Generation::new(observed.snapshot().generation)?;
        let objective_digest = frozen.input().objective_digest;
        let mut contributions = Vec::new();
        for name in [
            "abstain", "audio", "image", "shared", "stop", "text", "verify", "video",
        ] {
            let candidate_id = id(name)?;
            let organ_id = id("planner")?;
            let support_digest =
                joint_generation_contribution_support_v1(&observed, &candidate_id, &organ_id)?;
            contributions.push(UtilityContribution {
                candidate_id,
                organ_id,
                objective_digest,
                generation,
                // This fixed fixture disallows STOP until one advance. Real
                // callers must supply their backend's observed feasibility.
                feasibility: if preferred == "shared" && name == "stop" {
                    FeasibilityPosture::HardConstraintViolation
                } else {
                    FeasibilityPosture::Feasible
                },
                utility: vec![AxisValue {
                    axis: id("quality")?,
                    value: if name == preferred {
                        FixedQ32::ONE
                    } else {
                        FixedQ32::ZERO
                    },
                }],
                risk: Vec::new(),
                resource: Vec::new(),
                uncertainty: vec![AxisValue {
                    axis: id("quality")?,
                    value: FixedQ32::ZERO,
                }],
                support_digest,
            });
        }
        let attempt = plan.plan_advance(
            &observed,
            ContributionSet {
                objective_digest,
                generation,
                contributions,
            },
            next(&format!("bound-{preferred}"))?,
        )?;
        let planned = attempt.result?;
        assert_eq!(
            planned.evaluation.base.advisory_recommendation,
            Some(id(preferred)?)
        );
        let request = planned
            .request
            .ok_or_else(|| std::io::Error::other("explicit action"))?;
        assert_eq!(
            handle
                .step_planned(
                    observed.owner_checkpoint(),
                    attempt.planning_cost.clone(),
                    request.clone()
                )
                .await,
            Err(CellGenerationErrorV2::Pending)
        );
        let (_, receipt) = settle_request(&handle, request.clone()).await?;
        planning_costs.push(attempt.planning_cost);
        final_step = Some((request, receipt));
    }
    let (stop_request, receipt) = final_step.ok_or_else(|| std::io::Error::other("final STOP"))?;
    assert_eq!(receipt.disposition, CellGenerationDispositionV2::Stopped);
    assert!(!handle.drain().await?);
    let pending_delivery = handle.observe_generation().await?;
    assert!(frozen.outcome_evidence(&pending_delivery).is_err());
    let facts = synthetic::state(
        &pending_delivery.snapshot().state,
        &pending_delivery.snapshot().prefix,
        &assets,
    )?;
    assert!(facts.stopped);
    assert_eq!(facts.cursors, synthetic::TOTAL_UNITS);
    tasks.shutdown().await;
    assert!(tasks.failures().is_empty());
    drop(handle);
    fixture.reopen_state().await;
    let (handle, mut tasks) = start_service(&fixture, worker, clock).await?;
    assert_eq!(handle.observe_generation().await?, pending_delivery);
    assert_eq!(handle.step(stop_request).await?, receipt);
    let chunk = handle
        .pending_output()
        .await?
        .ok_or_else(|| std::io::Error::other("final outbox"))?;
    let mut sink = Vec::new();
    deliver(&handle, chunk, &fixture, &mut sink).await?;
    let settled = handle.observe_generation().await?;
    assert_eq!(&sink, &settled.snapshot().prefix);
    assert!(
        planning_costs
            .iter()
            .all(|cost| settled.cost().entries().contains(cost))
    );
    let evidence = frozen.outcome_evidence(&settled)?;
    assert!(evidence.complete_metrics().is_none());
    assert!(!evidence.support_digest().is_zero());
    tasks.shutdown().await;
    assert!(tasks.failures().is_empty());
    Ok(())
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
    lifecycle(ModelFixture::Synthetic).await
}

#[tokio::test]
async fn historical_trained_joint_control_service_preserves_real_output_cost_and_owner_on_reopen()
-> TestResult {
    lifecycle(ModelFixture::HistoricalTrained).await
}

async fn lifecycle(model: ModelFixture) -> TestResult {
    let mut fixture = Fixture::new().await;
    let epoch = Instant::now();
    // One real monotonic epoch is shared by owner, actor and process worker.
    let clock: Clock =
        Arc::new(move || u64::try_from(epoch.elapsed().as_micros()).unwrap_or(u64::MAX - 1) + 1);
    let (worker, assets) = install_model(&mut fixture, Arc::clone(&clock), model)?;
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
    match model {
        ModelFixture::Synthetic => {
            assert_eq!(decoded.bytes[0], vec![128; 768]);
            assert_eq!(decoded.bytes[1], vec![0; 2048]);
            assert_eq!(decoded.bytes[2], vec![128; 3072]);
            assert_eq!(decoded.bytes[3], b"action=0;sound=0\n");
        }
        ModelFixture::HistoricalTrained => {
            assert_eq!(decoded.bytes[0].len(), 768);
            assert_eq!(decoded.bytes[1].len(), 2048);
            assert_eq!(decoded.bytes[2].len(), 3072);
            assert!(decoded.bytes[0].windows(2).any(|pair| pair[0] != pair[1]));
            assert!(decoded.bytes[1].iter().any(|byte| *byte != 0));
            assert!(decoded.bytes[2].windows(2).any(|pair| pair[0] != pair[1]));
            let text = std::str::from_utf8(&decoded.bytes[3])?;
            assert!(
                text.starts_with("action=") && text.contains(";sound=") && text.ends_with('\n')
            );
        }
    }
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
    if let ModelFixture::HistoricalTrained = model {
        // Retention is independent of asset admission: this test always executes
        // the trained model, including when no external evidence path is set.
        let evidence = evidence_directory("joint-trained-agentd-")?;
        fs::write(evidence.path().join("prefix.hgc"), &snapshot.prefix)?;
        fs::write(evidence.path().join("state.hps"), &snapshot.state)?;
        fs::write(evidence.path().join("control.log"), &original_control)?;
        for (name, bytes) in ["image.rgb", "audio.s16le", "video.rgb", "text.txt"]
            .into_iter()
            .zip(&decoded.bytes)
        {
            fs::write(evidence.path().join(name), bytes)?;
        }
        let provenance: serde_json::Value = serde_json::from_str(trained::PROVENANCE)?;
        let receipt = serde_json::json!({
            "schema": "hepta.historical-trained-agentd-lifecycle.v1",
            "provenance": provenance,
            "source_digest": fixture.config.manifest.source_digest,
            "runtime_digest": fixture.config.manifest.runtime_digest,
            "device_digest": fixture.config.manifest.device_digest,
            "manifest_digest": fixture.config.manifest.digest()?,
            "state_sha256": Digest32::of_bytes(&snapshot.state).to_string(),
            "prefix_sha256": Digest32::of_bytes(&snapshot.prefix).to_string(),
            "control_sha256": Digest32::of_bytes(&original_control).to_string(),
            "generation": snapshot.generation,
            "writer_epoch": snapshot.writer_epoch,
            "revision": snapshot.revision,
            "receipts": [initialized, advanced, committed, stopped],
            "final_cost": final_cost,
            "delivered_bytes": sink.len(),
            "reopen_snapshot_output_cost_exact": true,
            "committed_retry_without_reexecution": true,
            "consumer_ack_and_drain_complete": true,
            "new_training_updates": 0,
            "scope": "Ordinary Agentd service with historical trained weights and synthetic public input; Init, Shared, audio commit, Stop, ACK and reopen.",
            "cancellation_evidence": "Separate historical_trained_joint_admission_cancel_retains_predecessor_cost_and_receipt_on_reopen test",
            "not_covered": ["Process death during proposal", "Natural-task quality", "Adoption", "Optimizer resume", "CPU/energy and complete historical cost"]
        });
        fs::write(
            evidence.path().join("LIFECYCLE.json"),
            serde_json::to_vec_pretty(&receipt)?,
        )?;
        let retained = evidence.keep();
        println!(
            "historical trained Joint lifecycle evidence: {}",
            retained.display()
        );
    }
    Ok(())
}
