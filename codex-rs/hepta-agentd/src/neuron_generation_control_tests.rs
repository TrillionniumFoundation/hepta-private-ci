//! Real private socket, Fleet fence, service queue, journal and witness tests.
//! The file control fixture isolates transport/recovery from model quality.

use std::fs;
use std::sync::Arc;
use std::sync::atomic::Ordering;

use codex_hepta_agent_protocol::AGENTD_GENERATION_CONTROL_CAPABILITY;
use codex_hepta_agent_protocol::GenerationControlRequestV1 as Request;
use codex_hepta_agent_protocol::GenerationControlResponseV1 as Response;
use codex_hepta_agent_protocol::GenerationDispositionV1;
use codex_hepta_agent_protocol::GenerationPendingV1;
use codex_hepta_agent_protocol::GenerationStatusV1;
use codex_hepta_agent_protocol::GenerationStepV1;
use codex_hepta_agent_protocol::MAX_GENERATION_CONTROL_INPUT_BYTES;
use pretty_assertions::assert_eq;
use tokio_util::sync::CancellationToken;

use super::support::Fixture;
use super::support::host;
use crate::AgentdClient;
use crate::RuntimeTasks;
use crate::control::AgentdControlServer;
use crate::neuron_generation_channel_v2;
use crate::neuron_generation_service::spawn_neuron_generation_service;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

struct Serving {
    client: AgentdClient,
    tasks: RuntimeTasks,
    cancellation: CancellationToken,
    server: tokio::task::JoinHandle<Result<(), crate::AgentdError>>,
}

impl Serving {
    async fn start(fixture: &Fixture) -> TestResult<Self> {
        let (handle, bootstrap) = neuron_generation_channel_v2(
            &fixture.identity,
            fixture.journal(),
            fixture.control.clone(),
            fixture.clock(),
            /*capacity*/ 4,
        )?;
        let bootstrap = bootstrap.with_control_endpoint()?;
        drop(handle); // The process caller need not retain a second owner handle.
        let (mut tasks, lifetime) = host();
        spawn_neuron_generation_service(
            &mut tasks,
            bootstrap,
            Arc::clone(fixture.state()),
            lifetime,
        )?;
        let path = fixture.directory.path().join("generation.ctl");
        let cancellation = CancellationToken::new();
        let server = AgentdControlServer::bind(
            path.clone(),
            Arc::clone(fixture.state()),
            cancellation.clone(),
        )
        .await?;
        let server = tokio::spawn(server.run());
        let client = AgentdClient::new(
            path,
            fixture.identity.agent_id.clone(),
            fixture.identity.spawn_generation,
        )?;
        Ok(Self {
            client,
            tasks,
            cancellation,
            server,
        })
    }

    async fn finish(mut self) -> TestResult {
        self.cancellation.cancel();
        self.server.await??;
        self.tasks.shutdown().await;
        Ok(())
    }
}

async fn status(client: &AgentdClient) -> TestResult<GenerationStatusV1> {
    match client.generation(Request::Status {}).await? {
        Response::Status(value) => Ok(*value),
        other => {
            Err(std::io::Error::other(format!("expected generation status: {other:?}")).into())
        }
    }
}

fn step(fixture: &Fixture, snapshot: &GenerationStatusV1, key: &str) -> Request {
    Request::Step {
        request: Box::new(GenerationStepV1 {
            client_operation_id: key.into(),
            expected_snapshot_digest: snapshot.snapshot_digest,
            task_digest: fixture.config.task_digest,
            source_frontier: fixture.config.source_frontier,
            input: vec![1, 2, 3],
            deadline_micros: 10_000,
        }),
    }
}

#[tokio::test]
async fn private_socket_pages_acknowledges_and_reopens_exact_original_operation() -> TestResult {
    let mut fixture = Fixture::new().await;
    let serving = Serving::start(&fixture).await?;
    assert!(
        serving
            .client
            .capabilities()
            .await?
            .capabilities
            .iter()
            .any(|item| item.id == AGENTD_GENERATION_CONTROL_CAPABILITY)
    );
    let initial = status(&serving.client).await?;
    let original = step(&fixture, &initial, "socket-step");
    let receipt = serving.client.generation(original.clone()).await?;
    assert!(
        matches!(&receipt, Response::Receipt(value) if value.disposition == GenerationDispositionV1::Advanced)
    );
    let after = status(&serving.client).await?;
    let delivery = after
        .output
        .clone()
        .ok_or_else(|| std::io::Error::other("missing committed output"))?;
    assert_eq!(after.revision, 1);
    assert!(after.pending.is_none());
    assert_eq!(
        serving.client.generation(Request::Drain {}).await?,
        Response::Drain { complete: false }
    );

    let mut bytes = Vec::new();
    while bytes.len() < delivery.bytes as usize {
        let response = serving
            .client
            .generation(Request::Output {
                expected_chunk_digest: delivery.chunk_digest,
                offset: bytes.len() as u32,
                limit: 7,
            })
            .await?;
        let Response::Output {
            delivery: observed,
            offset,
            bytes: page,
            complete,
        } = response
        else {
            return Err(std::io::Error::other("expected output page").into());
        };
        assert_eq!(observed, delivery);
        assert_eq!(offset, bytes.len() as u32);
        assert!(page.len() <= 7);
        bytes.extend(page);
        assert_eq!(complete, bytes.len() == delivery.bytes as usize);
    }
    assert_eq!(
        bytes,
        format!("observed:{}\n", delivery.operation_id).into_bytes()
    );
    assert_eq!(
        status(&serving.client).await?.output,
        Some(delivery.clone())
    );
    let acknowledgement = Request::Acknowledge {
        delivery,
        acknowledgement: [61; 32],
    };
    assert_eq!(
        serving.client.generation(acknowledgement.clone()).await?,
        Response::Acknowledged {}
    );
    let journal_path = fixture.directory.path().join("generation-journal");
    let durable = fs::read(&journal_path)?;
    assert_eq!(
        serving.client.generation(acknowledgement.clone()).await?,
        Response::Acknowledged {}
    );
    assert_eq!(fs::read(&journal_path)?, durable);
    assert!(status(&serving.client).await?.drained);

    fixture.ticks.store(20_000, Ordering::SeqCst);
    assert_eq!(serving.client.generation(original.clone()).await?, receipt);
    assert_eq!(fixture.control.signals.calls.load(Ordering::SeqCst), 1);
    serving.finish().await?;
    fixture.reopen_state().await;
    let reopened = Serving::start(&fixture).await?;
    assert_eq!(reopened.client.generation(original).await?, receipt);
    assert_eq!(
        reopened.client.generation(acknowledgement).await?,
        Response::Acknowledged {}
    );
    assert_eq!(fs::read(&journal_path)?, durable);
    let Response::Cost(cost) = reopened.client.generation(Request::Cost {}).await? else {
        return Err(std::io::Error::other("expected task cost").into());
    };
    assert_eq!(cost.exclusive_entries, 2);
    assert_eq!(cost.communication_bytes.unknown_entries, 2);
    assert_eq!(cost.energy_microjoules.known_sum, 0);
    assert_eq!(cost.energy_microjoules.unknown_entries, 2);
    assert!(cost.missing_stages.contains(&"training".to_string()));
    assert_eq!(
        reopened.client.generation(Request::Resume {}).await?,
        Response::Resumed {}
    );
    reopened.finish().await
}

#[tokio::test]
async fn stale_generation_changed_content_and_oversized_input_do_not_mutate_owner() -> TestResult {
    let fixture = Fixture::new().await;
    let serving = Serving::start(&fixture).await?;
    let initial = status(&serving.client).await?;
    let journal_path = fixture.directory.path().join("generation-journal");
    let pristine = fs::read(&journal_path)?;
    let mut oversized = step(&fixture, &initial, "oversized");
    let Request::Step { request } = &mut oversized else {
        unreachable!()
    };
    request.input = vec![1; MAX_GENERATION_CONTROL_INPUT_BYTES + 1];
    assert!(serving.client.generation(oversized).await.is_err());
    assert_eq!(fs::read(&journal_path)?, pristine);
    let stale_client = AgentdClient::new(
        fixture.directory.path().join("generation.ctl"),
        fixture.identity.agent_id.clone(),
        fixture.identity.spawn_generation + 1,
    )?;
    assert!(
        stale_client
            .generation(step(&fixture, &initial, "fenced"))
            .await
            .is_err()
    );
    assert_eq!(fs::read(&journal_path)?, pristine);
    let original = step(&fixture, &initial, "same-client-key");
    serving.client.generation(original.clone()).await?;
    let committed = fs::read(&journal_path)?;
    let mut changed = original;
    let Request::Step { request } = &mut changed else {
        unreachable!()
    };
    request.input.push(4);
    assert!(serving.client.generation(changed).await.is_err());
    for request in [
        Request::Output {
            expected_chunk_digest: [0; 32],
            offset: 0,
            limit: 1,
        },
        Request::Output {
            expected_chunk_digest: [0; 32],
            offset: 0,
            limit: 0,
        },
    ] {
        assert!(serving.client.generation(request).await.is_err());
    }
    assert_eq!(fs::read(&journal_path)?, committed);
    assert_eq!(fixture.control.signals.calls.load(Ordering::SeqCst), 1);
    serving.finish().await
}

#[tokio::test]
async fn uncertain_dispatch_cancels_and_reads_original_without_second_execution() -> TestResult {
    let fixture = Fixture::new().await;
    fixture
        .control
        .signals
        .lose_response
        .store(true, Ordering::SeqCst);
    let serving = Serving::start(&fixture).await?;
    let original = step(
        &fixture,
        &status(&serving.client).await?,
        "lost-worker-response",
    );
    assert!(serving.client.generation(original.clone()).await.is_err());
    let pending = status(&serving.client)
        .await?
        .pending
        .ok_or_else(|| std::io::Error::other("uncertain dispatch lost admission"))?;
    assert_eq!(
        serving.client.generation(original.clone()).await?,
        Response::Pending(pending.clone())
    );
    assert!(
        serving
            .client
            .generation(Request::Cancel {
                request_digest: [33; 32]
            })
            .await
            .is_err()
    );
    assert_eq!(
        serving
            .client
            .generation(Request::Cancel {
                request_digest: pending.request_digest
            })
            .await?,
        Response::CancelRequested {}
    );
    fixture
        .control
        .signals
        .readable
        .store(true, Ordering::SeqCst);
    let receipt = serving
        .client
        .generation(Request::Reconcile {
            request_digest: pending.request_digest,
        })
        .await?;
    assert!(
        matches!(&receipt, Response::Receipt(value) if value.disposition == GenerationDispositionV1::Cancelled && value.cost_entries == 1)
    );
    assert_eq!(
        serving
            .client
            .generation(Request::Reconcile {
                request_digest: pending.request_digest
            })
            .await?,
        receipt
    );
    assert_eq!(serving.client.generation(original).await?, receipt);
    let after = status(&serving.client).await?;
    assert!(after.pending.is_none());
    assert!(after.output.is_none());
    assert_eq!(after.prefix_bytes, 0);
    assert_eq!(fixture.control.signals.calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        fixture.control.signals.cancellations.load(Ordering::SeqCst),
        1
    );
    serving.finish().await
}

#[tokio::test]
async fn simultaneous_steps_compare_predecessors_inside_one_owner() -> TestResult {
    let fixture = Fixture::new().await;
    let serving = Serving::start(&fixture).await?;
    let before = status(&serving.client).await?;
    let (left, right) = tokio::join!(
        serving
            .client
            .generation(step(&fixture, &before, "parallel-left")),
        serving
            .client
            .generation(step(&fixture, &before, "parallel-right")),
    );
    assert_eq!(usize::from(left.is_ok()) + usize::from(right.is_ok()), 1);
    assert_eq!(fixture.control.signals.calls.load(Ordering::SeqCst), 1);
    assert_eq!(status(&serving.client).await?.revision, 1);
    serving.finish().await
}

#[tokio::test]
async fn typed_generation_bootstrap_does_not_implicitly_expose_control() -> TestResult {
    let fixture = Fixture::new().await;
    let (handle, bootstrap) = neuron_generation_channel_v2(
        &fixture.identity,
        fixture.journal(),
        fixture.control.clone(),
        fixture.clock(),
        /*capacity*/ 4,
    )?;
    let (mut tasks, lifetime) = host();
    spawn_neuron_generation_service(&mut tasks, bootstrap, Arc::clone(fixture.state()), lifetime)?;
    assert!(!fixture.state().generation_control_enabled()?);
    assert!(
        fixture
            .state()
            .generation_control(Box::new(Request::Status {}))
            .await
            .is_err()
    );
    assert_eq!(handle.snapshot().await?.revision, 0);
    tasks.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn typed_operation_with_same_derived_id_cannot_impersonate_control_intent() -> TestResult {
    let fixture = Fixture::new().await;
    let journal = fixture.journal();
    let predecessor = journal.snapshot()?.clone();
    let compact = GenerationStepV1 {
        client_operation_id: "mixed-callers".into(),
        expected_snapshot_digest: predecessor.digest()?,
        task_digest: fixture.config.task_digest,
        source_frontier: fixture.config.source_frontier,
        input: vec![1, 2, 3],
        deadline_micros: 10_000,
    };
    let operation_id = format!(
        "generation-control-v1-{}",
        codex_hepta_types::Digest32::of_parts(&[
            b"hepta.agentd.generation-step.v1\0",
            &serde_json::to_vec(&compact)?,
        ])
    );
    let mut owner = crate::AgentdNeuronGenerationOwnerV2::new(journal, fixture.control.clone());
    let typed = codex_hepta_neuron::CellGenerationRequestV2 {
        operation_id,
        task_digest: compact.task_digest,
        source_frontier: compact.source_frontier,
        predecessor,
        input: vec![9, 9],
        admitted_at_micros: 10,
        deadline_micros: compact.deadline_micros,
    };
    owner.step(typed, fixture.clock())?;
    drop(owner);
    let before = fs::read(fixture.directory.path().join("generation-journal"))?;
    let serving = Serving::start(&fixture).await?;
    assert!(
        serving
            .client
            .generation(Request::Step {
                request: Box::new(compact)
            })
            .await
            .is_err()
    );
    assert_eq!(
        fs::read(fixture.directory.path().join("generation-journal"))?,
        before
    );
    assert_eq!(fixture.control.signals.calls.load(Ordering::SeqCst), 1);
    serving.finish().await
}

#[tokio::test]
async fn pending_typed_operation_with_same_derived_id_rejects_control_intent_without_readback()
-> TestResult {
    let fixture = Fixture::new().await;
    fixture
        .control
        .signals
        .lose_response
        .store(true, Ordering::SeqCst);
    let journal = fixture.journal();
    let predecessor = journal.snapshot()?.clone();
    let compact = GenerationStepV1 {
        client_operation_id: "mixed-pending-callers".into(),
        expected_snapshot_digest: predecessor.digest()?,
        task_digest: fixture.config.task_digest,
        source_frontier: fixture.config.source_frontier,
        input: vec![1, 2, 3],
        deadline_micros: 10_000,
    };
    let operation_id = format!(
        "generation-control-v1-{}",
        codex_hepta_types::Digest32::of_parts(&[
            b"hepta.agentd.generation-step.v1\0",
            &serde_json::to_vec(&compact)?,
        ])
    );
    let typed = codex_hepta_neuron::CellGenerationRequestV2 {
        operation_id,
        task_digest: compact.task_digest,
        source_frontier: compact.source_frontier,
        predecessor,
        input: vec![9, 9],
        admitted_at_micros: 10,
        deadline_micros: compact.deadline_micros,
    };
    let pending = GenerationPendingV1 {
        operation_id: typed.operation_id.clone(),
        request_digest: typed.digest()?,
        admitted_at_micros: typed.admitted_at_micros,
        deadline_micros: typed.deadline_micros,
    };
    let mut owner = crate::AgentdNeuronGenerationOwnerV2::new(journal, fixture.control.clone());
    assert!(matches!(
        owner.step(typed, fixture.clock()),
        Err(codex_hepta_neuron::CellGenerationErrorV2::Unavailable)
    ));
    drop(owner);

    // The original result is available: the conflicting compact intent must
    // be rejected before any readback, settlement, or second dispatch.
    fixture
        .control
        .signals
        .readable
        .store(true, Ordering::SeqCst);
    let journal_path = fixture.directory.path().join("generation-journal");
    let before = fs::read(&journal_path)?;
    let serving = Serving::start(&fixture).await?;
    assert_eq!(
        status(&serving.client).await?.pending,
        Some(pending.clone())
    );
    assert!(
        serving
            .client
            .generation(Request::Step {
                request: Box::new(compact)
            })
            .await
            .is_err()
    );
    assert_eq!(fs::read(&journal_path)?, before);
    assert_eq!(
        status(&serving.client).await?.pending,
        Some(pending.clone())
    );
    assert_eq!(fixture.control.signals.calls.load(Ordering::SeqCst), 1);
    assert_eq!(fixture.control.signals.reads.load(Ordering::SeqCst), 0);
    assert_eq!(
        fixture.control.signals.cancellations.load(Ordering::SeqCst),
        0
    );

    let receipt = serving
        .client
        .generation(Request::Reconcile {
            request_digest: pending.request_digest,
        })
        .await?;
    assert!(matches!(receipt, Response::Receipt(value)
        if value.request_digest == pending.request_digest
            && value.disposition == GenerationDispositionV1::Advanced));
    assert_eq!(fixture.control.signals.calls.load(Ordering::SeqCst), 1);
    assert_eq!(fixture.control.signals.reads.load(Ordering::SeqCst), 1);
    serving.finish().await
}
