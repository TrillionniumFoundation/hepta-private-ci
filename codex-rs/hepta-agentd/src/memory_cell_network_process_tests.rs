use std::collections::BTreeSet;
use std::fs::OpenOptions;
use std::io::Write;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use serde_json::json;

use crate::AgentdClient;

use super::MemoryCellNetworkV1;
use super::MemoryCellNetworkVersionV1;
use super::anchor::NetworkAnchor;
use super::process_test_support::ProcessFleet;

#[tokio::test]
#[ignore = "private OS-child entry; launched only by the parent network process test"]
async fn memory_cell_network_child() {
    super::process_test_support::child_main().await;
}

#[tokio::test]
async fn memory_cell_network_os_process_crash_reopens_same_owners_and_requires_successor_vector() {
    let started = Instant::now();
    let mut fixture = ProcessFleet::new().await;
    let pids = vec![
        std::process::id(),
        fixture.consumer.ready.pid,
        fixture.nodes[0].ready.pid,
        fixture.nodes[1].ready.pid,
    ];
    assert_eq!(
        pids.iter().copied().collect::<BTreeSet<_>>().len(),
        4,
        "consumer and both owners occupy separate OS processes"
    );
    let journal_path = fixture.root.join("network.anchor");
    let journal = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(&journal_path)
        .expect("new route anchor");
    let first = fixture.deployment(1).await;
    let version = first.version();
    let network = MemoryCellNetworkV1::open_anchored(
        fixture.registry.clone(),
        fixture.consumer.ready.owner.clone(),
        fixture.consumer.ready.spawn_generation,
        first.clone(),
        journal,
    )
    .expect("anchored process network");
    let initial = network
        .recover(version)
        .await
        .expect("full process vector admitted");
    let requests = fixture.requests();
    let old_read = network
        .read(version, requests.clone())
        .await
        .expect("cross-process native parameter reads");
    assert_eq!(
        old_read
            .readouts()
            .iter()
            .map(|row| row.readout.value.clone())
            .collect::<Vec<_>>(),
        vec![json!(29), json!(29)]
    );
    let old_node = fixture.nodes[1].ready.clone();
    let predecessor_setup_traffic = fixture.nodes[1].client.traffic_snapshot();
    let predecessor_handshake = json!({"received":fixture.nodes[1].handshake_received_bytes,"transmitted":fixture.nodes[1].handshake_transmitted_bytes});
    let owner = fixture
        .registry
        .load_agent(&old_node.owner)
        .expect("old owner layout");
    let stale_client = AgentdClient::new(
        owner.layout.agentd_control_socket().to_path_buf(),
        old_node.owner.clone(),
        old_node.spawn_generation,
    )
    .expect("retained old spawn client");
    let before_crash = network
        .cumulative_cost()
        .expect("cost before process failure");
    fixture.nodes[1].crash().await;
    let failure = network
        .read(version, requests.clone())
        .await
        .err()
        .expect("hard process exit closes entire vector");
    assert!(failure.cost.rpc_attempts > 0 && failure.cost.transmitted_bytes > 0);
    let after_crash = network.cumulative_cost().expect("failed attempt charged");
    assert_eq!(
        (
            after_crash.rpc_attempts - before_crash.rpc_attempts,
            after_crash.transmitted_bytes - before_crash.transmitted_bytes,
            after_crash.received_bytes - before_crash.received_bytes
        ),
        (
            failure.cost.rpc_attempts,
            failure.cost.transmitted_bytes,
            failure.cost.received_bytes
        )
    );
    assert!(network.revalidate(&old_read).await.is_err());
    fixture.restart(1).await;
    let restarted = fixture.nodes[1].ready.clone();
    assert_ne!(restarted.pid, old_node.pid);
    assert!(restarted.spawn_generation > old_node.spawn_generation);
    assert_eq!(
        (
            &restarted.release,
            restarted.cut,
            restarted.bundle,
            restarted.artifact_generation
        ),
        (
            &old_node.release,
            old_node.cut,
            old_node.bundle,
            old_node.artifact_generation
        )
    );
    let second_request =
        requests[&StableId::new(old_node.owner.as_str()).expect("second node label")].clone();
    assert!(
        stale_client.memory_cell_read(second_request).await.is_err(),
        "an old process identity cannot call the successor socket"
    );
    assert!(
        network.recover(version).await.is_err(),
        "restored transport and parameters do not revive a stale spawn pin"
    );
    let successor = fixture.deployment(2).await;
    let migrated = network
        .migrate(version, successor.clone())
        .await
        .expect("complete successor vector and durable route acknowledgement");
    let new_read = network
        .read(migrated.version, requests.clone())
        .await
        .expect("successor process reads");
    assert_eq!(
        new_read
            .readouts()
            .iter()
            .map(|row| row.readout.value.clone())
            .collect::<Vec<_>>(),
        vec![json!(29), json!(29)]
    );
    assert!(network.revalidate(&old_read).await.is_err());
    let cost_before_reopen = network
        .cumulative_cost()
        .expect("predecessor composition costs");
    drop(network);
    let old_open = MemoryCellNetworkV1::open_anchored(
        fixture.registry.clone(),
        fixture.consumer.ready.owner.clone(),
        fixture.consumer.ready.spawn_generation,
        first,
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(&journal_path)
            .expect("old route attempt"),
    );
    assert!(
        old_open.is_err(),
        "acknowledged route generation survives host reopen"
    );
    let restored = MemoryCellNetworkV1::open_anchored(
        fixture.registry.clone(),
        fixture.consumer.ready.owner.clone(),
        fixture.consumer.ready.spawn_generation,
        successor,
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(&journal_path)
            .expect("route anchor reopen"),
    )
    .expect("exact acknowledged composition");
    assert!(
        restored
            .read(migrated.version, requests.clone())
            .await
            .is_err()
    );
    restored
        .recover(migrated.version)
        .await
        .expect("fresh complete vector validation after reopen");
    assert!(
        restored.revalidate(&new_read).await.is_err(),
        "retained in-memory admission is not reconstructed from disk"
    );
    let final_read = restored
        .read(migrated.version, requests)
        .await
        .expect("post-reopen read");
    assert_eq!(
        final_read
            .readouts()
            .iter()
            .map(|row| row.readout.value.clone())
            .collect::<Vec<_>>(),
        vec![json!(29), json!(29)]
    );
    let receipt = json!({"schema":"hepta.memory.v8.process-network-receipt.v1", "parent_and_initial_node_pids":pids,
        "predecessor":old_node,"successor":restarted,"successful_node_readbacks":6,"initial_admission":initial,
        "failed_attempt":failure.cost,"migration":migrated,"network_cost_before_composition_reopen":cost_before_reopen,
        "network_cost_after_composition_reopen":restored.cumulative_cost().expect("restored costs"),
        "predecessor_setup_control_traffic":predecessor_setup_traffic,"stale_spawn_control_traffic":stale_client.traffic_snapshot(),
        "remaining_setup_control_traffic":fixture.nodes.iter().map(|node| node.client.traffic_snapshot()).chain(std::iter::once(fixture.consumer.client.traffic_snapshot())).collect::<Vec<_>>(),
        "predecessor_handshake_bytes":predecessor_handshake,
        "remaining_handshake_bytes":fixture.nodes.iter().chain(std::iter::once(&fixture.consumer)).map(|node| json!({"received":node.handshake_received_bytes,"transmitted":node.handshake_transmitted_bytes})).collect::<Vec<_>>(),
        "anchor_bytes":std::fs::metadata(&journal_path).expect("anchor size").len(),
        "elapsed_before_shutdown_ns":started.elapsed().as_nanos().to_string(),
        "fault":"parent killed and reaped a real owner process before a successor opened the same SQLite and artifact roots",
        "parameter_profile":"single-class native integration fixture; no training-effectiveness claim",
        "app_server_readiness":"explicit control-only fixture seam",
        "scope":"same-host OS processes; existing read-only federation discovery; no database transfer or cross-machine replication",
        "accounting_scope":"application RPC bytes and attempts, including failure, recovery and migration; handshake counts exclude harness trailer, stderr and shutdown; not exclusive wire cost"});
    if let Some(path) = std::env::var_os("MEMORY_CELL_NETWORK_PROCESS_RECEIPT_PATH") {
        let mut file = std::fs::File::create_new(path).expect("new process-network receipt");
        file.write_all(&serde_json::to_vec_pretty(&receipt).expect("receipt JSON"))
            .expect("receipt bytes");
        file.sync_all().expect("durable process-network receipt");
    }
    println!("MEMORY_V8_PROCESS_NETWORK_RECEIPT:{receipt}");
    fixture.finish().await;
}

#[test]
#[ignore = "private abrupt-exit child used to exercise the journal commit boundary"]
fn memory_cell_anchor_crash_child() {
    let path = std::env::var_os("HEPTA_MEMORY_ANCHOR_CRASH_PATH").expect("parent journal path");
    let phase = std::env::var("HEPTA_MEMORY_ANCHOR_CRASH_PHASE").expect("parent fault phase");
    let predecessor = crash_version(1);
    let mut anchor = NetworkAnchor::open(
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(path)
            .expect("child journal"),
        Digest32::of_bytes(b"actual-process-crash-anchor"),
        predecessor,
    )
    .expect("child acquired journal");
    match phase.as_str() {
        "before_commit" => {}
        "after_commit" => anchor
            .commit(predecessor, crash_version(2))
            .expect("fsynced successor"),
        _ => panic!("unknown fault phase"),
    }
    // Skip Rust destructors deliberately. The parent waits for this OS process
    // to exit before reacquiring the same exclusive journal.
    std::process::exit(73);
}

#[tokio::test]
async fn memory_cell_network_anchor_recovers_both_sides_of_actual_process_commit_exit() {
    let journal = tempfile::NamedTempFile::new().expect("independent journal");
    let scope = Digest32::of_bytes(b"actual-process-crash-anchor");
    let open = |version| {
        NetworkAnchor::open(
            OpenOptions::new()
                .read(true)
                .write(true)
                .open(journal.path())
                .expect("journal handle"),
            scope,
            version,
        )
    };
    drop(open(crash_version(1)).expect("initial deployment"));
    for (phase, expected) in [("before_commit", 1), ("after_commit", 2)] {
        let mut child =
            tokio::process::Command::new(std::env::current_exe().expect("test executable"))
                .args([
                    "--ignored",
                    "--exact",
                    "memory_cell_network::process_tests::memory_cell_anchor_crash_child",
                    "--nocapture",
                ])
                .env("HEPTA_MEMORY_ANCHOR_CRASH_PATH", journal.path())
                .env("HEPTA_MEMORY_ANCHOR_CRASH_PHASE", phase)
                .kill_on_drop(true)
                .spawn()
                .expect("crash-boundary process");
        let status = tokio::time::timeout(Duration::from_secs(15), child.wait())
            .await
            .expect("crash child deadline")
            .expect("reap crash child");
        assert_eq!(status.code(), Some(73));
        drop(
            open(crash_version(expected)).expect("only the committed side of the boundary reopens"),
        );
        assert!(
            open(crash_version(3 - expected)).is_err(),
            "the other side of commit cannot become acknowledged"
        );
    }
}

fn crash_version(generation: u64) -> MemoryCellNetworkVersionV1 {
    MemoryCellNetworkVersionV1 {
        generation: ContractGenerationV1::new(generation).expect("generation"),
        deployment_digest: ContractDigestV1::from_digest(Digest32::of_bytes(
            format!("crash-vector-{generation}").as_bytes(),
        ))
        .expect("vector digest"),
    }
}
