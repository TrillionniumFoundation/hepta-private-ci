use std::fs::OpenOptions;
use std::path::Path;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use pretty_assertions::assert_eq;

use super::MemoryCellDeploymentV1;
use super::MemoryCellNetworkErrorV1;
use super::MemoryCellNetworkV1;
use super::test_support::NetworkFixture;

fn open(fixture: &NetworkFixture, deployment: MemoryCellDeploymentV1, path: &Path)
    -> Result<MemoryCellNetworkV1, MemoryCellNetworkErrorV1> {
    let file = OpenOptions::new().read(true).write(true).open(path).expect("journal file");
    MemoryCellNetworkV1::open_anchored(fixture.registry.clone(),
        fixture.consumer.state().identity().agent_id.clone(),
        fixture.consumer.state().identity().spawn_generation, deployment, file)
}

#[tokio::test]
async fn acknowledged_route_generation_survives_reopen_and_rejects_rollback_and_same_generation_fork() {
    let fixture = NetworkFixture::new().await;
    let journal = tempfile::NamedTempFile::new().expect("independent journal");
    let first = fixture.deployment(1);
    let version = first.version();
    let network = open(&fixture, first.clone(), journal.path()).expect("anchored deployment");
    assert!(open(&fixture, first.clone(), journal.path()).is_err(), "another host cannot acquire its journal");
    network.recover(version).await.expect("complete initial vector");
    let retained = network.read(version, fixture.requests()).await.expect("old read");
    let before = std::fs::metadata(journal.path()).expect("journal metadata").len();
    let next = fixture.deployment(2);
    let committed = network.migrate(version, next.clone()).await.expect("durable successor acknowledgement");
    assert_eq!(committed.version, next.version());
    assert!(std::fs::metadata(journal.path()).expect("committed metadata").len() > before);
    drop(network);

    assert!(open(&fixture, first, journal.path()).is_err(), "reopen must not forget an acknowledged successor");
    let fork = MemoryCellDeploymentV1::new(ContractGenerationV1::new(2).expect("generation"),
        vec![fixture.nodes[0].binding()]).expect("same generation, different vector");
    assert!(open(&fixture, fork, journal.path()).is_err(), "generation alone does not bind routes");
    let restored = open(&fixture, next, journal.path()).expect("exact committed vector");
    assert!(restored.read(committed.version, fixture.requests()).await.is_err(), "journal recovery grants no readiness");
    restored.recover(committed.version).await.expect("explicit complete recovery");
    assert!(restored.revalidate(&retained).await.is_err(), "a new process admission cannot revive an old read token");
    restored.read(committed.version, fixture.requests()).await.expect("fresh read after anchored recovery");
    fixture.finish().await;
}

#[tokio::test]
async fn cancelled_remote_preparation_leaves_the_last_durable_vector_recoverable() {
    let fixture = NetworkFixture::new().await;
    let journal = tempfile::NamedTempFile::new().expect("independent journal");
    let first = fixture.deployment(1);
    let version = first.version();
    let network = Arc::new(open(&fixture, first.clone(), journal.path()).expect("anchored network"));
    network.recover(version).await.expect("ready");
    let before = std::fs::read(journal.path()).expect("durable predecessor bytes");
    let candidate = fixture.deployment(2);
    fixture.nodes[0].gate.block_once();
    let pending = {
        let network = Arc::clone(&network);
        let candidate = candidate.clone();
        tokio::spawn(async move { network.migrate(version, candidate).await })
    };
    tokio::time::timeout(Duration::from_secs(5), fixture.nodes[0].gate.entered.notified())
        .await.expect("preparation reached real peer resolver");
    assert_eq!(std::fs::read(journal.path()).expect("uncommitted bytes"), before);
    pending.abort();
    assert!(pending.await.expect_err("cancelled preparation").is_cancelled());
    fixture.nodes[0].gate.release.notify_waiters();
    assert!(network.read(version, fixture.requests()).await.is_err());
    assert!(network.cumulative_cost().expect("cancelled attempt accounting").rpc_attempts > 0);
    assert_eq!(std::fs::read(journal.path()).expect("retained predecessor"), before);
    drop(network);

    assert!(open(&fixture, candidate.clone(), journal.path()).is_err(), "unacknowledged preparation is not a committed successor");
    let restored = open(&fixture, first, journal.path()).expect("last committed vector");
    restored.recover(version).await.expect("full recovery after interruption");
    let committed = restored.migrate(version, candidate).await.expect("new complete migration");
    restored.read(committed.version, fixture.requests()).await.expect("successor reads");
    fixture.finish().await;
}
