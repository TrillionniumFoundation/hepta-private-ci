//! Actual socket peer and original physical canary export; no model replay.
use super::*;
use crate::AgentdNeuronRuntimeV2Host;
use crate::AgentdNeuronTickProviderV2;
use std::os::unix::fs::MetadataExt;
use tokio_util::sync::CancellationToken;

struct UnusedTickProvider;
impl AgentdNeuronTickProviderV2 for UnusedTickProvider {
    fn build_tick(
        &self,
        _: &crate::AgentdIdentity,
        _: &codex_hepta_agent_components::learning_ledger::RunStartRecordV1,
        _: &crate::AgentdIntelligenceInvocationV1,
    ) -> Result<NeuronTickInputV1, crate::AgentdError> {
        Err(crate::AgentdError::Invalid(
            "readonly export cannot dispatch a tick".into(),
        ))
    }
}

async fn original_owner_roundtrip(root_expected: bool) -> Result<(), Box<dyn std::error::Error>> {
    let uid = std::fs::metadata("/proc/self")?.uid();
    assert_eq!(
        uid == 0,
        root_expected,
        "fixture must use the actual expected kernel peer"
    );
    let h = Harness::new();
    let owner = scope_owner(&h, h.tick.objective_digest);
    let current_scope = checked(AgentdNeuronGoalScopeV3::capture(1, &owner));
    let controller = checked(
        AgentdNeuronGenerationControllerV2::from_recovered_goal_scopes_v3(
            current_scope,
            owner.clone(),
            std::iter::empty(),
            h.root.path().join("canary-export-controller.json"),
        ),
    );
    checked(controller.start());
    let actual = checked(h.prepared(&controller).execute(&h.input(), &mut h.allow()));
    let query = crate::CanaryOperationQueryV2 {
        model_generation: 1,
        configuration_digest: owner.configuration_digest().to_string(),
        body_digest: owner
            .body_bundle_digest()
            .ok_or("body unavailable")?
            .to_string(),
        scope_digest: scope().scope_digest.to_string(),
        objective_digest: scope().objective_digest.to_string(),
        tick_id: actual.key.tick_id.to_string(),
        input_semantic_digest: actual.key.input_semantic_digest.to_string(),
    };
    let host = Arc::new(AgentdNeuronRuntimeV2Host {
        controller,
        tick_provider: Arc::new(UnusedTickProvider),
        goal_scope_factory: None,
        lifecycle: Mutex::new(()),
        stopped: AtomicBool::new(false),
        iteration_quarantine: AtomicBool::new(false),
    });
    let fixture = crate::runtime::tests::runtime_fixture();
    fixture
        .state
        .neuron_runtime_v2
        .set(host.clone())
        .map_err(|_| "host already attached")?;
    let cancellation = CancellationToken::new();
    let server = crate::control::AgentdControlServer::bind(
        fixture.identity.control_socket.clone(),
        fixture.state.clone(),
        cancellation.clone(),
    )
    .await?;
    let task = tokio::spawn(server.run());
    let client = crate::AgentdClient::new(
        fixture.identity.control_socket.clone(),
        fixture.identity.agent_id.clone(),
        1,
    )?;
    let result = client.canary_operation_receipt(query.clone()).await;
    if root_expected {
        let (generation, portable) = result?;
        assert_eq!(generation, 1);
        assert_eq!(portable.commit(), &actual);
        for field in [
            "model",
            "configuration",
            "body",
            "scope",
            "objective",
            "tick",
            "input",
        ] {
            let mut other = query.clone();
            match field {
                "model" => other.model_generation += 1,
                "configuration" => {
                    other.configuration_digest = digest("foreign config").to_string()
                }
                "body" => other.body_digest = digest("foreign body").to_string(),
                "scope" => other.scope_digest = digest("foreign scope").to_string(),
                "objective" => other.objective_digest = digest("foreign objective").to_string(),
                "tick" => other.tick_id = "foreign-tick".into(),
                "input" => other.input_semantic_digest = digest("foreign input").to_string(),
                _ => unreachable!(),
            }
            assert!(
                client.canary_operation_receipt(other).await.is_err(),
                "{field}"
            );
        }
        checked(host.controller.begin_quiesce());
        assert!(client.canary_operation_receipt(query).await.is_err());
    } else {
        assert!(
            matches!(result, Err(crate::AgentdError::Protocol(message)) if message.contains("root_peer_required"))
        );
        // The denied read leaves the exact physical operation and acknowledged witness unchanged.
        let exported = host.export_current_operation_v2(
            checked(AgentdNeuronGenerationIdV2::new(1)),
            owner.configuration_digest(),
            owner.body_bundle_digest().ok_or("body unavailable")?,
            scope(),
            &checked(AgentdNeuronOperationIdentityV2::new(
                actual.key.tick_id.clone(),
                actual.key.input_semantic_digest,
            )),
        )?;
        assert_eq!(exported.commit(), &actual);
    }
    assert_eq!(h.calls.load(Ordering::SeqCst), 1);
    cancellation.cancel();
    task.await??;
    Ok(())
}

#[tokio::test]
async fn real_non_root_canary_peer_cannot_export_or_reexecute_the_original_operation()
-> Result<(), Box<dyn std::error::Error>> {
    original_owner_roundtrip(/* root_expected */ false).await
}

#[tokio::test]
#[ignore = "requires an actual UID0 process; ordinary owning tests verify non-Root rejection"]
async fn real_root_canary_peer_reads_the_whole_original_ack_and_rejects_substitution()
-> Result<(), Box<dyn std::error::Error>> {
    original_owner_roundtrip(/* root_expected */ true).await
}
