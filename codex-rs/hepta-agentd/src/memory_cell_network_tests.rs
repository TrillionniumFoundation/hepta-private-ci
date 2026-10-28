use std::collections::BTreeMap;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::MemoryCellRecordV1;
use codex_hepta_memory::MemoryCellWriteModeV1;
use pretty_assertions::assert_eq;
use serde_json::json;

use crate::MemoryFederationCapabilityId;

use super::MemoryCellDeploymentV1;
use super::MemoryCellNetworkV1;
use super::MemoryCellVersionPinV1;
use super::test_support::NetworkFixture;

fn network(
    fixture: &NetworkFixture,
    deployment: MemoryCellDeploymentV1,
) -> Arc<MemoryCellNetworkV1> {
    Arc::new(
        MemoryCellNetworkV1::new(
            fixture.registry.clone(),
            fixture.consumer.state().identity().agent_id.clone(),
            fixture.consumer.state().identity().spawn_generation,
            deployment,
        )
        .expect("configured network"),
    )
}

#[tokio::test]
async fn real_two_owner_reads_bind_the_whole_version_vector_and_charge_actual_control_bytes() {
    let fixture = NetworkFixture::new().await;
    let deployment = fixture.deployment(1);
    assert_ne!(
        deployment.nodes()[0].pin().owner_cut_digest,
        deployment.nodes()[1].pin().owner_cut_digest
    );
    let version = deployment.version();
    let network = network(&fixture, deployment);
    assert!(
        network.read(version, fixture.requests()).await.is_err(),
        "configuration alone is not readiness"
    );
    let ready = network.recover(version).await.expect("all owners admitted");
    assert!(
        ready.cost.rpc_attempts >= 2
            && ready.cost.received_bytes > 0
            && ready.cost.transmitted_bytes > 0
    );
    let before = network.cumulative_cost().expect("cost before read");
    let read = network
        .read(version, fixture.requests())
        .await
        .expect("real multi-node read");
    assert_eq!(
        read.readouts()
            .iter()
            .map(|row| row.readout.value.clone())
            .collect::<Vec<_>>(),
        vec![json!(29), json!(29)]
    );
    assert_eq!(read.version(), version);
    let after = network.cumulative_cost().expect("cost after read");
    assert_eq!(
        (
            after.rpc_attempts - before.rpc_attempts,
            after.transmitted_bytes - before.transmitted_bytes,
            after.received_bytes - before.received_bytes
        ),
        (
            read.cost().rpc_attempts,
            read.cost().transmitted_bytes,
            read.cost().received_bytes
        )
    );
    network
        .revalidate(&read)
        .await
        .expect("full-vector final use");
    fixture.finish().await;
}

#[tokio::test]
async fn a_real_peer_socket_failure_closes_all_routes_until_explicit_complete_recovery() {
    let mut fixture = NetworkFixture::new().await;
    let deployment = fixture.deployment(1);
    let version = deployment.version();
    let network = network(&fixture, deployment);
    network.recover(version).await.expect("ready");
    let requests = fixture.requests();
    let old = network
        .read(version, requests.clone())
        .await
        .expect("old reader");
    fixture.nodes[1].stop().await;
    let only_first = BTreeMap::from([(
        fixture.nodes[0].label.clone(),
        requests[&fixture.nodes[0].label].clone(),
    )]);
    let failure = network
        .read(version, only_first)
        .await
        .err()
        .expect("unqueried selected peer is still required");
    assert!(failure.cost.rpc_attempts > 0 && failure.cost.transmitted_bytes > 0);
    assert!(network.revalidate(&old).await.is_err());
    assert!(network.recover(version).await.is_err());
    fixture.nodes[1].restart_socket().await;
    assert!(
        network.read(version, requests.clone()).await.is_err(),
        "transport recovery cannot silently reopen admission"
    );
    network
        .recover(version)
        .await
        .expect("explicit complete-vector recovery");
    assert!(
        network.revalidate(&old).await.is_err(),
        "old admission epoch cannot revive"
    );
    network
        .read(version, requests)
        .await
        .expect("new reader after socket recovery");
    fixture.finish().await;
}

#[tokio::test]
async fn migration_cas_closes_admission_cancellation_recovers_and_inflight_old_reads_fail() {
    let fixture = NetworkFixture::new().await;
    let first = fixture.deployment(1);
    let version = first.version();
    let network = network(&fixture, first);
    network.recover(version).await.expect("ready");
    let old = network
        .read(version, fixture.requests())
        .await
        .expect("old result");
    fixture.nodes[0].gate.block_once();
    let candidate = fixture.deployment(2);
    let migrating = {
        let network = Arc::clone(&network);
        let candidate = candidate.clone();
        tokio::spawn(async move { network.migrate(version, candidate).await })
    };
    tokio::time::timeout(
        Duration::from_secs(5),
        fixture.nodes[0].gate.entered.notified(),
    )
    .await
    .expect("migration reached real remote resolver");
    assert!(network.read(version, fixture.requests()).await.is_err());
    assert!(network.revalidate(&old).await.is_err());
    assert!(
        network.migrate(version, candidate.clone()).await.is_err(),
        "second migration fails CAS while preparing"
    );
    migrating.abort();
    assert!(
        migrating
            .await
            .expect_err("cancelled migration")
            .is_cancelled()
    );
    fixture.nodes[0].gate.release.notify_waiters();
    assert!(network.read(version, fixture.requests()).await.is_err());
    network
        .recover(version)
        .await
        .expect("explicit recovery after cancelled preparation");
    assert!(network.revalidate(&old).await.is_err());

    fixture.nodes[0].gate.block_once();
    let requests = fixture.requests();
    let reading = {
        let network = Arc::clone(&network);
        tokio::spawn(async move { network.read(version, requests).await })
    };
    tokio::time::timeout(
        Duration::from_secs(5),
        fixture.nodes[0].gate.entered.notified(),
    )
    .await
    .expect("old read reached real resolver");
    let destination_only = MemoryCellDeploymentV1::new(
        ContractGenerationV1::new(2).expect("successor generation"),
        vec![fixture.nodes[1].binding()],
    )
    .expect("move read routes to the admitted destination");
    let successor = network
        .migrate(version, destination_only)
        .await
        .expect("organ generation handoff");
    fixture.nodes[0].gate.release.notify_waiters();
    assert!(
        reading.await.expect("old read join").is_err(),
        "inflight old read cannot cross successful migration"
    );
    assert_eq!(successor.version.generation.get(), 2);
    assert!(
        network
            .migrate(version, fixture.deployment(2))
            .await
            .is_err(),
        "stale expected version cannot replace successor"
    );
    let mut requests = fixture.requests();
    requests.remove(&fixture.nodes[0].label);
    network
        .read(successor.version, requests)
        .await
        .expect("new destination route generation");
    fixture.finish().await;
}

#[tokio::test]
async fn partial_parameter_publication_never_activates_a_mixed_vector_and_retry_uses_both_new_nodes()
 {
    let fixture = NetworkFixture::new().await;
    let first = fixture.deployment(1);
    let version = first.version();
    let network = network(&fixture, first);
    network.recover(version).await.expect("ready");
    let requests = fixture.requests();
    let corrected = MemoryCellRecordV1 {
        schema: "hepta.memory.cell-record.v1".to_string(),
        entity: ContractIdV1::new("meter:network").expect("entity"),
        kind: MemoryCellKindV1::Semantic,
        effective_at: 20,
        value: json!({"factor":5,"label":"corrected peer"}),
    };
    let node_b = &fixture.nodes[1];
    node_b
        .store
        .write_memory_cell(
            &CognitiveAccess::agent_private(node_b.state().identity().agent_id.clone()),
            &CognitiveScope::AgentPrivate,
            &corrected,
            MemoryCellWriteModeV1::Correct {
                expected_revision: 1,
            },
        )
        .await
        .expect("actual source correction");
    let snapshot_b = node_b.snapshot().await;
    let release_b = node_b.release.as_ref().expect("release B");
    let publish_b = release_b.prepare(&snapshot_b, /*generation*/ 2);
    release_b
        .host
        .publish(publish_b.clone(), &snapshot_b)
        .expect("publish B2");
    release_b.install(&publish_b).expect("select B2");
    assert!(
        network.read(version, requests.clone()).await.is_err(),
        "old vector does not substitute B2 for B1"
    );

    let node_a = &fixture.nodes[0];
    let snapshot_a = node_a.snapshot().await;
    let release_a = node_a.release.as_ref().expect("release A");
    let publish_a = release_a.prepare(&snapshot_a, /*generation*/ 2);
    let candidate = MemoryCellDeploymentV1::new(
        ContractGenerationV1::new(2).expect("deployment generation"),
        vec![
            node_a.binding_with_pin(MemoryCellVersionPinV1 {
                scope: snapshot_a.scope().clone(),
                owner_cut_digest: snapshot_a.owner_cut_digest(),
                generation: ContractGenerationV1::new(2).expect("model generation"),
                bundle_digest: ContractDigestV1::from_digest(
                    publish_a.admission.validated_manifest.manifest.bytes_digest,
                )
                .expect("planned bundle digest"),
            }),
            node_b.binding(),
        ],
    )
    .expect("planned complete vector");
    assert!(
        network.migrate(version, candidate.clone()).await.is_err(),
        "only one newly published node is insufficient"
    );
    assert_eq!(network.version().expect("still predecessor"), version);
    release_a
        .host
        .publish(publish_a.clone(), &snapshot_a)
        .expect("publish A2");
    release_a.install(&publish_a).expect("select A2");
    let admitted = network
        .migrate(version, candidate)
        .await
        .expect("retry after both nodes are selected");
    let result = network
        .read(admitted.version, requests)
        .await
        .expect("consistent successor read");
    assert_eq!(
        result
            .readouts()
            .iter()
            .map(|row| (row.readout.generation.get(), row.readout.value.clone()))
            .collect::<Vec<_>>(),
        vec![(2, json!(29)), (2, json!(47))]
    );
    fixture.finish().await;
}

#[tokio::test]
async fn live_federation_revocation_and_real_fleet_rotation_require_new_route_admission() {
    let mut fixture = NetworkFixture::new().await;
    let first = fixture.deployment(1);
    let version = first.version();
    let network = network(&fixture, first);
    network.recover(version).await.expect("ready");
    let old = network
        .read(version, fixture.requests())
        .await
        .expect("before revocation");
    let cap = fixture.nodes[1]
        .grant
        .as_ref()
        .expect("grant")
        .id()
        .as_str()
        .to_string();
    fixture.nodes[1]
        .client
        .memory_federation_revoke(MemoryFederationCapabilityId::parse(cap).expect("capability id"))
        .await
        .expect("actual source authority revoke");
    assert!(network.revalidate(&old).await.is_err());
    assert!(network.recover(version).await.is_err());
    let consumer = fixture.consumer.state().identity().agent_id.clone();
    fixture.nodes[1].grant_to(&consumer).await;
    let second = network
        .migrate(version, fixture.deployment(2))
        .await
        .expect("new grant generation in complete vector");
    assert!(network.revalidate(&old).await.is_err());
    fixture.nodes[0].rotate_spawn(&fixture.registry).await;
    assert!(
        network
            .read(second.version, fixture.requests())
            .await
            .is_err(),
        "new process cannot inherit old spawn route"
    );
    assert!(network.recover(second.version).await.is_err());
    let third = network
        .migrate(second.version, fixture.deployment(3))
        .await
        .expect("admit actual successor spawn");
    network
        .read(third.version, fixture.requests())
        .await
        .expect("new spawn final-use read");
    fixture.finish().await;
}
