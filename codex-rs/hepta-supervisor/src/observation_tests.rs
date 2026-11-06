//! Protocol peers are explicit fixtures; daemon_product covers the real binary.
use std::sync::Arc;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_uds::UnixListener;
use pretty_assertions::assert_eq;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::sync::Notify;
use tokio_util::sync::CancellationToken;

use crate::ControlStateDigest;
use crate::SUPERVISORD_CONTROL_SCHEMA_VERSION;
use crate::SupervisorEpoch;
use crate::SupervisordAgentStatus;
use crate::SupervisordClient;
use crate::SupervisordControlFence;
use crate::SupervisordHealth;
use crate::SupervisordMatrixStatus;
use crate::SupervisordMethod;
use crate::SupervisordPayload;
use crate::SupervisordRequest;
use crate::SupervisordResponse;

fn status() -> SupervisordAgentStatus {
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap();
    let fence = SupervisordControlFence {
        agent_id: agent_id.clone(),
        supervisor_epoch: SupervisorEpoch::parse("018f4f72-5f8f-4cc1-8f55-df9fb3aa2c12").unwrap(),
        lifecycle: AgentLifecycle::Stopped,
        lifecycle_generation: 7,
        spawn_generation: None,
        runtime_generation: None,
        current_release: None,
        previous_release: None,
        release_change_pending: false,
        state_digest: ControlStateDigest::parse("a".repeat(64)).unwrap(),
    };
    SupervisordAgentStatus {
        agent_id,
        lifecycle: AgentLifecycle::Stopped,
        lifecycle_generation: 7,
        active: false,
        healthy: false,
        process_id: None,
        spawn_generation: None,
        runtime_generation: None,
        current_release: None,
        previous_release: None,
        release_change_pending: false,
        control_fence: fence,
        matrix: SupervisordMatrixStatus {
            configured: false,
            active: false,
            healthy: false,
            degraded: false,
            process_id: None,
            attached_agent_generation: None,
            binding_revision: None,
            restart_attempt: 0,
            last_error: None,
        },
    }
}

async fn peer(
    mut listener: UnixListener,
    initial: SupervisordAgentStatus,
    last: SupervisordAgentStatus,
) -> Vec<SupervisordMethod> {
    let health = SupervisordHealth {
        ready: true,
        supervisor_epoch: initial.control_fence.supervisor_epoch.clone(),
        process_id: 1234,
        registered_agents: 1,
        observed_faults: 0,
    };
    let payloads = [
        SupervisordPayload::Health(health.clone()),
        SupervisordPayload::Agent(initial),
        SupervisordPayload::ReleaseSelection { selection: None },
        SupervisordPayload::ProductionMutationStatus { state: None },
        SupervisordPayload::ProductionMutationStatus { state: None },
        SupervisordPayload::ReleaseSelection { selection: None },
        SupervisordPayload::Agent(last),
        SupervisordPayload::Health(health),
    ];
    let mut observed = Vec::new();
    for payload in payloads {
        let stream = listener.accept().await.unwrap();
        let mut reader = BufReader::new(stream);
        let mut raw = String::new();
        reader.read_line(&mut raw).await.unwrap();
        let request: SupervisordRequest = serde_json::from_str(&raw).unwrap();
        request.validate().unwrap();
        observed.push(request.method);
        let mut bytes = serde_json::to_vec(&SupervisordResponse {
            schema_version: SUPERVISORD_CONTROL_SCHEMA_VERSION,
            request_id: request.request_id,
            payload,
        })
        .unwrap();
        bytes.push(b'\n');
        reader.get_mut().write_all(&bytes).await.unwrap();
    }
    observed
}

#[tokio::test]
async fn bracket_uses_only_existing_read_rpcs_and_is_never_atomic_acceptance() {
    let temp = tempfile::tempdir().unwrap();
    let socket = temp.path().join("o.sock");
    let listener = UnixListener::bind(&socket).await.unwrap();
    let initial = status();
    let task = tokio::spawn(peer(listener, initial.clone(), initial.clone()));
    let client = SupervisordClient::new(socket).unwrap();
    let result = client
        .observe_current(&initial.control_fence, &CancellationToken::new())
        .await
        .unwrap();
    assert_eq!(result.agent, initial.clone());
    assert!(
        !result.atomic_snapshot && !result.independently_attested && !result.production_accepted
    );
    assert!(result.ended_unix_micros >= result.started_unix_micros);
    let agent_id = initial.agent_id;
    assert_eq!(
        task.await.unwrap(),
        vec![
            SupervisordMethod::Health,
            SupervisordMethod::Snapshot {
                agent_id: agent_id.clone()
            },
            SupervisordMethod::ReleaseSelection {
                agent_id: agent_id.clone()
            },
            SupervisordMethod::ProductionMutationStatus {
                agent_id: agent_id.clone()
            },
            SupervisordMethod::ProductionMutationStatus {
                agent_id: agent_id.clone()
            },
            SupervisordMethod::ReleaseSelection {
                agent_id: agent_id.clone()
            },
            SupervisordMethod::Snapshot { agent_id },
            SupervisordMethod::Health,
        ]
    );
}

#[tokio::test]
async fn concurrent_generation_change_is_not_a_complete_observation() {
    let temp = tempfile::tempdir().unwrap();
    let socket = temp.path().join("o.sock");
    let listener = UnixListener::bind(&socket).await.unwrap();
    let initial = status();
    let mut changed = initial.clone();
    changed.lifecycle_generation += 1;
    changed.control_fence.lifecycle_generation += 1;
    let task = tokio::spawn(peer(listener, initial.clone(), changed));
    let client = SupervisordClient::new(socket).unwrap();
    assert!(
        client
            .observe_current(&initial.control_fence, &CancellationToken::new())
            .await
            .is_err()
    );
    assert_eq!(task.await.unwrap().len(), 8);
}

#[tokio::test]
async fn restarted_owner_cannot_reuse_a_previous_expectation() {
    let temp = tempfile::tempdir().unwrap();
    let socket = temp.path().join("o.sock");
    let listener = UnixListener::bind(&socket).await.unwrap();
    let current = status();
    let mut expected = current.control_fence.clone();
    expected.supervisor_epoch = SupervisorEpoch::new();
    let task = tokio::spawn(peer(listener, current.clone(), current));
    let client = SupervisordClient::new(socket).unwrap();
    assert!(
        client
            .observe_current(&expected, &CancellationToken::new())
            .await
            .is_err()
    );
    assert_eq!(task.await.unwrap().len(), 8);
}

#[tokio::test]
async fn pre_cancelled_observer_does_not_connect_or_mutate() {
    let temp = tempfile::tempdir().unwrap();
    let client = SupervisordClient::new(temp.path().join("absent.sock")).unwrap();
    let stop = CancellationToken::new();
    stop.cancel();
    let result = client
        .observe_current(&status().control_fence, &stop)
        .await
        .unwrap_err();
    assert!(result.to_string().contains("observation cancelled"));
}

#[tokio::test]
async fn blocked_read_cancels_without_detaching_an_owner_effect() {
    let temp = tempfile::tempdir().unwrap();
    let socket = temp.path().join("o.sock");
    let mut listener = UnixListener::bind(&socket).await.unwrap();
    let stop = CancellationToken::new();
    let entered = Arc::new(Notify::new());
    let signal = Arc::clone(&entered);
    let finish = stop.clone();
    let task = tokio::spawn(async move {
        let stream = listener.accept().await.unwrap();
        signal.notify_one();
        finish.cancelled().await;
        drop(stream);
    });
    let client = SupervisordClient::new(socket).unwrap();
    let cancel = async {
        entered.notified().await;
        stop.cancel();
    };
    let expected = status().control_fence;
    let (result, ()) = tokio::join!(client.observe_current(&expected, &stop), cancel);
    assert!(
        result
            .unwrap_err()
            .to_string()
            .contains("observation cancelled")
    );
    task.await.unwrap();
}
