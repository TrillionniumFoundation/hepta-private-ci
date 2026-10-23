//! Actual original Agentd control/App Server branch tests. Provider responses
//! and the independent FinalUse signer are fixtures, not production authority.
//! Admission starts at the trusted original RunStart/RunAttachContext APIs;
//! this does not qualify the signed Objective compiler or crash recovery.

use super::*;
use codex_hepta_agentd::AgentCancellationDisposition;
use codex_hepta_agentd::AgentContextAttachment;
use codex_hepta_agentd::AgentRunReceipt;
use codex_hepta_agentd::AgentRunSnapshot;
use codex_hepta_agentd::test_support::CognitiveTestHost;
use core_test_support::responses;
use std::cell::RefCell;

tokio::task_local! {
    static INTERRUPTS: RefCell<Vec<(String, String)>>;
}

// Observe the real interrupt entry without replacing the client or transport.
// A count alone cannot pass: the test also requires the actual correlated
// terminal, original native journal and original Agentd readback below.
pub(super) fn record_interrupt(output: &NativeRunOutput) {
    let _ = INTERRUPTS.try_with(|calls| {
        calls
            .borrow_mut()
            .push((output.thread_id.clone(), output.turn_id.clone()));
    });
}

#[derive(Clone, Copy, Eq, PartialEq)]
enum Scenario {
    Complete,
    ExternalCancel,
    Indeterminate,
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_intelligence_branch_keeps_spawn_one_and_run_two() -> Result<()> {
    run_scenario(Scenario::Complete).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_external_cancel_interrupts_once_and_commits_correlated_terminal() -> Result<()> {
    run_scenario(Scenario::ExternalCancel).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_indeterminate_run_stops_exact_turn_without_rewriting_run_terminal() -> Result<()>
{
    run_scenario(Scenario::Indeterminate).await
}

async fn run_scenario(scenario: Scenario) -> Result<()> {
    let server = responses::start_mock_server().await;
    let response = responses::sse(vec![
        responses::ev_response_created("resp-original-run"),
        responses::ev_assistant_message("msg-original-run", "original run complete"),
        responses::ev_completed("resp-original-run"),
    ]);
    let delay = if scenario == Scenario::Complete {
        Duration::ZERO
    } else {
        Duration::from_secs(30)
    };
    let response_mock =
        responses::mount_response_once(&server, responses::sse_response(response).set_delay(delay))
            .await;
    let root = tempfile::tempdir()?;
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let host = CognitiveTestHost::start(
        root.path().to_path_buf(),
        agent_id,
        "mock-model",
        &format!("{}/v1", server.uri()),
    )
    .await?;
    let owner = AgentdClient::new(
        host.control_socket().to_path_buf(),
        host.agent_id().clone(),
        /*spawn_generation*/ 1,
    )?;
    let handoff = original_handoff(&owner, host.agent_id()).await?;
    let authority = tempfile::tempdir()?;
    let (authorizer, issuer) = crate::final_use_authorizer::tests::independent_test_authorizer(
        authority.path(),
        /*expected_claims*/ 1,
    )
    .await?;
    let driver = AppServerModelDriver::new(NativeWorkerConfig {
        agentd_socket: host.control_socket().to_path_buf(),
        agent_id: host.agent_id().clone(),
        generation: 1,
        model: "mock-model".into(),
        timeout: Duration::from_secs(20),
    })?
    .with_turn_start_authorizer(Arc::new(authorizer));
    let journal_path = root.path().join("native.journal");
    let mut journal = DurableInferenceControl::open(&journal_path, /*capacity*/ 8)?;
    let cancellation = CancellationToken::new();
    let worker = INTERRUPTS.scope(RefCell::new(Vec::new()), async {
        let output = driver
            .run_intelligence(
                &mut journal,
                NativeAdmission {
                    request_id: "original-intelligence-request".into(),
                    maximum_in_flight: 1,
                },
                "respond once".into(),
                /*context_query*/ None,
                handoff.clone(),
                &cancellation,
            )
            .await?;
        let interrupts = INTERRUPTS.with(|calls| calls.borrow().clone());
        Ok::<_, Box<dyn std::error::Error + Send + Sync>>((output, interrupts))
    });
    let mutation = async {
        if scenario == Scenario::Complete {
            return Ok(None);
        }
        // Synchronize on the real provider request, not a guessed turn-start
        // delay. The provider response remains pending while Agentd cancels.
        timeout(Duration::from_secs(15), async {
            while response_mock.requests().is_empty() {
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .map_err(|_| "original physical provider request was never observed")?;
        let dispatched = owner
            .run_status(handoff.run_id.clone())
            .await?
            .ok_or("original run disappeared")?;
        assert_eq!(dispatched.phase, AgentRunPhase::Dispatched);
        assert_eq!(dispatched.generation, 2);
        let receipt = match scenario {
            Scenario::ExternalCancel => {
                let cancelled = owner
                    .run_cancel(
                        handoff.run_id.clone(),
                        dispatched.revision,
                        "independent operator cancellation".into(),
                    )
                    .await?;
                assert_eq!(
                    cancelled.disposition,
                    AgentCancellationDisposition::CancellingAfterDispatch
                );
                cancelled.receipt
            }
            Scenario::Indeterminate => {
                owner
                    .run_observe_terminal(
                        handoff.run_id.clone(),
                        dispatched.revision,
                        AgentRunPhase::Indeterminate,
                        /*terminal_observed*/ false,
                    )
                    .await?
            }
            Scenario::Complete => unreachable!("completed scenario has no owner mutation"),
        };
        Ok::<Option<AgentRunReceipt>, Box<dyn std::error::Error + Send + Sync>>(Some(receipt))
    };
    let (worker_result, mutation_result) = timeout(Duration::from_secs(30), async {
        tokio::join!(worker, mutation)
    })
    .await?;
    let mutation_receipt = mutation_result?;
    let (output, interrupts) = worker_result?;
    issuer.await??;
    assert_eq!(
        response_mock.requests().len(),
        1,
        "no second physical model request"
    );
    assert!(
        output.terminal_observed,
        "interrupt ACK alone cannot satisfy this test"
    );
    assert!(output.codex_terminal_correlation_digest.is_some());
    assert_eq!(output.owner_authority, NativeOwnerAuthority::ObservedReady);
    let final_receipt = owner
        .run_status(handoff.run_id.clone())
        .await?
        .ok_or("missing final original run")?;
    assert_eq!(
        final_receipt.generation, 2,
        "spawn must not replace the retained run generation"
    );
    match scenario {
        Scenario::Complete => {
            assert!(output.succeeded(), "{output:?}");
            assert_eq!(final_receipt.phase, AgentRunPhase::Succeeded);
            assert!(interrupts.is_empty());
        }
        Scenario::ExternalCancel => {
            assert_eq!(output.status, NativeRunStatus::Interrupted);
            assert_eq!(output.boundary_status, NativeBoundaryStatus::Cancelled);
            let mut expected = mutation_receipt.ok_or("missing external cancellation ACK")?;
            expected.phase = AgentRunPhase::Cancelled;
            expected.revision += 1;
            expected.cancel_ack_deadline_ms = None;
            expected.terminal_observed = true;
            assert_eq!(
                final_receipt, expected,
                "no second RunCancel or changed reason/revision"
            );
        }
        Scenario::Indeterminate => {
            assert_eq!(output.status, NativeRunStatus::Interrupted);
            assert_eq!(output.boundary_status, NativeBoundaryStatus::Quarantined);
            let expected = mutation_receipt.ok_or("missing original unresolved observation")?;
            assert_eq!(
                final_receipt, expected,
                "containment must not publish a guessed run terminal"
            );
            assert!(!output.succeeded());
        }
    }
    if scenario != Scenario::Complete {
        assert_eq!(
            interrupts,
            vec![(output.thread_id.clone(), output.turn_id.clone())]
        );
    }
    let record = journal
        .native_record("original-intelligence-request")
        .cloned()
        .ok_or("missing original native journal")?;
    assert_eq!(record.cancel_requested, scenario != Scenario::Complete);
    assert_eq!(record.observation.as_ref(), Some(&output));
    assert_eq!(record.turn_id.as_deref(), Some(output.turn_id.as_str()));
    drop(journal);
    let reopened = DurableInferenceControl::open(&journal_path, /*capacity*/ 8)?;
    assert_eq!(
        reopened.native_record("original-intelligence-request"),
        Some(&record)
    );
    drop(reopened);
    host.shutdown().await;
    Ok(())
}

async fn original_handoff(
    owner: &AgentdClient,
    agent_id: &AgentId,
) -> Result<NativeIntelligenceRunBinding> {
    let mut fence = b"hepta:agentd:objective-fence:v1\0".to_vec();
    fence.extend_from_slice(agent_id.as_str().as_bytes());
    fence.extend_from_slice(&1_u64.to_be_bytes());
    fence.extend_from_slice(&2_u64.to_be_bytes());
    let snapshot = AgentRunSnapshot {
        run_id: "run:original-intelligence".into(),
        request_digest: Digest32::of_bytes(b"fixture-request").to_string(),
        objective_digest: Digest32::of_bytes(b"fixture-objective").to_string(),
        body_digest: Digest32::of_bytes(b"fixture-body").to_string(),
        artifact_set_digest: Digest32::of_bytes(b"fixture-artifacts").to_string(),
        authority_epoch: 7,
        generation: 2,
        fence_digest: Digest32::of_bytes(&fence).to_string(),
        deadline_ms: unix_time_ms()?
            .checked_add(60_000)
            .ok_or("fixture deadline overflow")?,
    };
    let admitted = owner.run_start(snapshot.clone()).await?;
    let context_digest = Digest32::of_bytes(b"fixture-context").to_string();
    let envelope_digest = Digest32::of_bytes(b"fixture-envelope").to_string();
    let attached = owner
        .run_attach_context(
            admitted.revision,
            AgentContextAttachment {
                run_id: snapshot.run_id.clone(),
                request_digest: snapshot.request_digest,
                objective_digest: snapshot.objective_digest,
                body_digest: snapshot.body_digest,
                artifact_set_digest: snapshot.artifact_set_digest,
                authority_epoch: snapshot.authority_epoch,
                generation: snapshot.generation,
                fence_digest: snapshot.fence_digest,
                deadline_ms: snapshot.deadline_ms,
                context_digest: context_digest.clone(),
                compilation_receipt_digest: envelope_digest.clone(),
            },
        )
        .await?;
    Ok(NativeIntelligenceRunBinding {
        run_id: snapshot.run_id,
        expected_revision: attached.revision,
        context_digest,
        envelope_digest,
    })
}
