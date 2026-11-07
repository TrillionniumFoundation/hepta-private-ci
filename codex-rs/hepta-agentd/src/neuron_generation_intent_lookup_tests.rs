//! Real Circuit claim and private generation socket crash-cut regressions.
//! The controlled file port does not claim a Circuit driver or model qualification.

use std::fs;
use std::path::PathBuf;
use std::sync::atomic::Ordering;

use codex_hepta_agent_protocol::GenerationControlRequestV1 as Request;
use codex_hepta_agent_protocol::GenerationControlResponseV1 as Response;
use codex_hepta_agent_protocol::GenerationStepV1;
use codex_hepta_agent_protocol::MAX_GENERATION_CONTROL_INPUT_BYTES;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::BoundedCircuitDefinitionV2;
use codex_hepta_automation::CircuitCommandV2;
use codex_hepta_automation::CircuitComputationClaimV2;
use codex_hepta_automation::CircuitEdgeV2;
use codex_hepta_automation::CircuitEventV2;
use codex_hepta_automation::CircuitExitV2;
use codex_hepta_automation::CircuitLimitsV2;
use codex_hepta_automation::CircuitNodeKindV2;
use codex_hepta_automation::CircuitNodeV2;
use codex_hepta_automation::CircuitProfileV2;
use codex_hepta_automation::CircuitProgramV2;
use codex_hepta_automation::CircuitStartV2;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;

use super::Fixture;
use super::Serving;
use super::TestResult;
use super::status;
use super::step;

pub(super) fn lookup(request: &GenerationStepV1) -> TestResult<Request> {
    let digest = Digest32::of_parts(&[
        b"hepta.agentd.generation-step.v1\0",
        &serde_json::to_vec(request)?,
    ]);
    Ok(Request::LookupIntent {
        expected_operation_id: format!("generation-control-v1-{digest}"),
        request: Box::new(request.clone()),
    })
}

async fn claimed_circuit(
    fixture: &Fixture,
    request: &GenerationStepV1,
) -> TestResult<AutomationStore> {
    let store = AutomationStore::open(&fixture.identity.layout).await?;
    let fence = TaskFlowFence::new(
        fixture.identity.agent_id.clone(),
        "intent-claim-owner",
        /*owner_epoch*/ 1,
        fixture.identity.spawn_generation,
        "original-fence",
    )?;
    let schema = Sha256Digest::for_bytes(b"generation-intent-test-schema");
    let definition = BoundedCircuitDefinitionV2 {
        profile: CircuitProfileV2::BoundedFeedbackV2,
        circuit_id: "intent-claim-cut".into(),
        version: 1,
        predecessor_digest: None,
        entry_program: "root".into(),
        parameter_bundle_digest: Sha256Digest::for_bytes(b"fixture-bundle"),
        route_policy_digest: Sha256Digest::for_bytes(b"fixture-route"),
        limits: CircuitLimitsV2 {
            max_rounds: 1,
            max_activations: 4,
            max_frontier: 1,
            max_events: 16,
            max_causal_depth: 4,
            max_child_depth: 1,
            max_quantum: 1,
            max_no_progress: 2,
            max_elapsed_ms: 1000,
            work_budget: 1000,
        },
        programs: vec![CircuitProgramV2 {
            program_id: "root".into(),
            entry_node: "compute".into(),
            fallback_node: "fallback".into(),
            nodes: vec![
                CircuitNodeV2 {
                    node_id: "compute".into(),
                    input_schema: schema.clone(),
                    output_schema: schema.clone(),
                    kind: CircuitNodeKindV2::Compute { max_work: 1000 },
                },
                CircuitNodeV2 {
                    node_id: "success".into(),
                    input_schema: schema.clone(),
                    output_schema: schema.clone(),
                    kind: CircuitNodeKindV2::Exit {
                        outcome: CircuitExitV2::Succeeded,
                    },
                },
                CircuitNodeV2 {
                    node_id: "fallback".into(),
                    input_schema: schema.clone(),
                    output_schema: schema,
                    kind: CircuitNodeKindV2::Exit {
                        outcome: CircuitExitV2::Failed,
                    },
                },
            ],
            edges: vec![CircuitEdgeV2 {
                edge_id: "done".into(),
                from: "compute".into(),
                to: "success".into(),
                feedback_delay_ms: None,
            }],
        }],
    };
    let created = store
        .create_bounded_circuit_run(
            &definition,
            &CircuitStartV2 {
                run_id: "claim-cut".into(),
                scope_digest: Sha256Digest::for_bytes(
                    fixture.identity.agent_id.as_str().as_bytes(),
                ),
                input_digest: Sha256Digest::for_bytes(&request.input),
                created_at_ms: 10,
                lease_duration_ms: 500,
            },
            &fence,
        )
        .await?;
    let advanced = store
        .apply_bounded_circuit_command(&CircuitCommandV2 {
            run_id: "claim-cut".into(),
            command_id: "advance".into(),
            fence: fence.clone(),
            expected_revision: created.run.revision(),
            now_ms: 11,
            event: CircuitEventV2::Advance { quantum: 1 },
        })
        .await?;
    assert_eq!(advanced.dispatches.len(), 1);
    let activation_id = advanced.dispatches[0].activation_id;
    let claim = store
        .claim_circuit_computation(&CircuitComputationClaimV2 {
            run_id: "claim-cut".into(),
            activation_id,
            command_id: "claim-original-intent".into(),
            fence: fence.clone(),
            expected_revision: advanced.run.revision(),
            now_ms: 12,
            execution_request_digest: Sha256Digest::for_bytes(&serde_json::to_vec(request)?),
        })
        .await?;
    assert!(!claim.reconciliation_only());
    // Simulate losing the committed claim response. This test deliberately
    // does not invent the still-unimplemented Circuit -> Generation bridge.
    drop(claim);
    let recovered = store
        .recover_circuit_computation("claim-cut", activation_id, &fence, /*now_ms*/ 13)
        .await?;
    assert!(recovered.reconciliation_only());
    assert_eq!(
        recovered.execution_request_digest(),
        Some(&Sha256Digest::for_bytes(&serde_json::to_vec(request)?))
    );
    Ok(store)
}

#[derive(Debug, Eq, PartialEq)]
struct Observation {
    journal: Vec<u8>,
    witness: Vec<u8>,
    control_files: Vec<(PathBuf, Vec<u8>)>,
    cost: Response,
    calls_reads_cancels: [usize; 3],
    clock: u64,
    circuit: serde_json::Value,
}

impl Observation {
    async fn capture(
        fixture: &Fixture,
        serving: &Serving,
        store: &AutomationStore,
    ) -> TestResult<Self> {
        let mut control_files = fs::read_dir(fixture.directory.path().join("control-results"))?
            .map(|entry| {
                let entry = entry?;
                Ok((PathBuf::from(entry.file_name()), fs::read(entry.path())?))
            })
            .collect::<Result<Vec<_>, std::io::Error>>()?;
        control_files.sort_by(|left, right| left.0.cmp(&right.0));
        Ok(Self {
            journal: fs::read(fixture.directory.path().join("generation-journal"))?,
            witness: fs::read(fixture.directory.path().join("generation-witness"))?,
            control_files,
            cost: serving.client.generation(Request::Cost {}).await?,
            calls_reads_cancels: [
                fixture.control.signals.calls.load(Ordering::SeqCst),
                fixture.control.signals.reads.load(Ordering::SeqCst),
                fixture.control.signals.cancellations.load(Ordering::SeqCst),
            ],
            clock: fixture.ticks.load(Ordering::SeqCst),
            circuit: serde_json::to_value(store.bounded_circuit_run("claim-cut").await?)?,
        })
    }
}

enum Cut {
    Missing,
    Pending,
    Receipt,
}

async fn inspect_cut(cut: Cut) -> TestResult {
    let mut fixture = Fixture::new().await;
    let serving = Serving::start(&fixture).await?;
    let Request::Step { request } =
        step(&fixture, &status(&serving.client).await?, "original-claim")
    else {
        unreachable!()
    };
    let query = lookup(&request)?;
    let store = claimed_circuit(&fixture, &request).await?;
    let expected = match cut {
        Cut::Missing => {
            let Request::LookupIntent {
                expected_operation_id,
                ..
            } = &query
            else {
                unreachable!()
            };
            Response::IntentMissing {
                operation_id: expected_operation_id.clone(),
            }
        }
        Cut::Pending => {
            fixture
                .control
                .signals
                .lose_response
                .store(true, Ordering::SeqCst);
            assert!(
                serving
                    .client
                    .generation(Request::Step {
                        request: request.clone()
                    })
                    .await
                    .is_err()
            );
            Response::Pending(
                status(&serving.client)
                    .await?
                    .pending
                    .ok_or_else(|| std::io::Error::other("lost generation admission"))?,
            )
        }
        Cut::Receipt => {
            // The test retains a reference receipt only for exact comparison;
            // the recovering caller receives nothing from this original Step.
            let result = serving
                .client
                .generation(Request::Step {
                    request: request.clone(),
                })
                .await?;
            assert!(matches!(&result, Response::Receipt(_)));
            result
        }
    };
    fixture.ticks.store(20_000, Ordering::SeqCst); // Original deadline is now expired.
    fixture
        .control
        .signals
        .readable
        .store(true, Ordering::SeqCst);
    fixture
        .control
        .signals
        .panic_on_read
        .store(true, Ordering::SeqCst);
    let before = Observation::capture(&fixture, &serving, &store).await?;
    for _ in 0..2 {
        assert_eq!(serving.client.generation(query.clone()).await?, expected);
        assert_eq!(
            Observation::capture(&fixture, &serving, &store).await?,
            before
        );
    }
    let run = store
        .bounded_circuit_run("claim-cut")
        .await?
        .ok_or_else(|| std::io::Error::other("lost Circuit claim"))?;
    assert_eq!(run.budget().reserved(), 1000);
    assert_eq!(run.budget().spent(), 0);
    fixture
        .control
        .signals
        .panic_on_read
        .store(false, Ordering::SeqCst);
    fixture
        .control
        .signals
        .readable
        .store(false, Ordering::SeqCst);
    serving.finish().await?;
    if matches!(cut, Cut::Receipt) {
        fixture.reopen_state().await;
        let reopened = Serving::start(&fixture).await?;
        let before = Observation::capture(&fixture, &reopened, &store).await?;
        assert_eq!(reopened.client.generation(query).await?, expected);
        assert_eq!(
            Observation::capture(&fixture, &reopened, &store).await?,
            before
        );
        reopened.finish().await?;
    }
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn committed_circuit_claim_with_no_step_stays_missing_without_dispatch_or_refund()
-> TestResult {
    inspect_cut(Cut::Missing).await
}

#[tokio::test]
async fn lost_generation_response_is_pending_without_worker_readback_or_settlement() -> TestResult {
    inspect_cut(Cut::Pending).await
}

#[tokio::test]
async fn lost_step_receipt_is_read_exactly_after_reopen_without_new_cost() -> TestResult {
    inspect_cut(Cut::Receipt).await
}

#[tokio::test]
async fn altered_intent_and_stale_host_cannot_become_missing_or_mutate_owners() -> TestResult {
    let fixture = Fixture::new().await;
    let serving = Serving::start(&fixture).await?;
    let Request::Step { request } =
        step(&fixture, &status(&serving.client).await?, "pinned-intent")
    else {
        unreachable!()
    };
    let query = lookup(&request)?;
    let store = claimed_circuit(&fixture, &request).await?;
    let before = Observation::capture(&fixture, &serving, &store).await?;
    for field in [
        "input",
        "client",
        "snapshot",
        "task",
        "frontier",
        "deadline",
        "expected-id",
        "oversized",
    ] {
        let mut changed = query.clone();
        let Request::LookupIntent {
            expected_operation_id,
            request,
        } = &mut changed
        else {
            unreachable!()
        };
        match field {
            "input" => request.input.push(9),
            "client" => request.client_operation_id.push('x'),
            "snapshot" => request.expected_snapshot_digest = [99; 32],
            "task" => request.task_digest = [99; 32],
            "frontier" => request.source_frontier = [99; 32],
            "deadline" => request.deadline_micros += 1,
            "expected-id" => expected_operation_id.push('x'),
            "oversized" => request.input = vec![0; MAX_GENERATION_CONTROL_INPUT_BYTES + 1],
            _ => unreachable!(),
        }
        assert!(serving.client.generation(changed).await.is_err(), "{field}");
        assert_eq!(
            Observation::capture(&fixture, &serving, &store).await?,
            before
        );
    }
    let stale = crate::AgentdClient::new(
        fixture.directory.path().join("generation.ctl"),
        fixture.identity.agent_id.clone(),
        fixture.identity.spawn_generation + 1,
    )?;
    assert!(stale.generation(query).await.is_err());
    assert_eq!(
        Observation::capture(&fixture, &serving, &store).await?,
        before
    );
    assert_eq!(before.calls_reads_cancels, [0; 3]);
    serving.finish().await?;
    store.close().await;
    Ok(())
}
