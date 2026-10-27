//! Actual owner export -> independently fit shards -> signed release -> socket
//! reads. The resolver is an explicit seam, not language-quality evidence.

use std::path::PathBuf;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_cognitive_types::MemoryReadStatusV1;
use codex_hepta_cognitive_store::MemoryCellOwnerSnapshotV1;
use codex_hepta_cognitive_store::MemoryCellWriteModeV1;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_types::Digest32;
use serde_json::Value;
use serde_json::json;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;

use crate::MemoryCellTrainerConfigV1;
use crate::memory_cell_release::test_support::ReleaseFixture;
use crate::memory_cell_runtime_tests::TestRoute;
use crate::memory_cell_runtime_tests::TrustedTestResolver;
use crate::memory_cell_runtime_tests::attach;
use crate::memory_cell_test_support::ControlFixture;
use crate::memory_cell_test_support::request;
use crate::memory_cell_training_test_support::CODE_FILES;
use crate::memory_cell_training_test_support::readback;
use crate::memory_cell_training_test_support::row;
use crate::memory_cell_training_test_support::trainer;
use crate::memory_cell_training_test_support::write_new;

fn code_digest(config: &MemoryCellTrainerConfigV1) -> Digest32 {
    let mut bytes = b"hepta.memory.population-integration.code.v2".to_vec();
    for name in CODE_FILES.into_iter().chain(["memory-cell-v7/population_training.py", "memory-cell-v7/population_worker.py"]) {
        bytes.extend_from_slice(&(name.len() as u64).to_be_bytes());
        bytes.extend_from_slice(name.as_bytes());
        bytes.extend_from_slice(Digest32::of_bytes(&std::fs::read(config.qualification_root.join(name)).unwrap()).as_array());
    }
    Digest32::of_bytes(&bytes)
}

async fn fit_population(config: &MemoryCellTrainerConfigV1, snapshot: &MemoryCellOwnerSnapshotV1, count: usize) -> (Value, Digest32) {
    let code = code_digest(config);
    let configuration = json!({"shard_count":count,"seed":91317,"steps":600,"dimension":48,"total_hidden":64,"threshold":0.5});
    let request = serde_json::to_vec(&json!({"schema":"hepta.memory.population-training-request.v2",
        "export":snapshot,"configuration":configuration})).unwrap();
    let mut child = tokio::process::Command::new(&config.python).args(["-I", "-u", "-B"])
        .arg(config.qualification_root.join("memory-cell-v7/population_worker.py"))
        .env("OPENBLAS_NUM_THREADS", "1").env("OMP_NUM_THREADS", "1")
        .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped()).kill_on_drop(true).spawn().unwrap();
    let mut input = child.stdin.take().unwrap();
    let output = child.stdout.take().unwrap();
    let errors = child.stderr.take().unwrap();
    let execution = async {
        let send = async { input.write_all(&request).await.unwrap(); input.shutdown().await.unwrap(); drop(input); };
        let receive = async { let mut raw = Vec::new(); output.take(16 * 1024 * 1024 + 1).read_to_end(&mut raw).await.unwrap(); raw };
        let stderr = async { let mut raw = Vec::new(); errors.take(8193).read_to_end(&mut raw).await.unwrap(); raw };
        let (_, raw, diagnostics) = tokio::join!(send, receive, stderr);
        assert!(child.wait().await.unwrap().success(), "population training failed: {}", String::from_utf8_lossy(&diagnostics));
        assert!(raw.len() <= 16 * 1024 * 1024 && diagnostics.len() <= 8192);
        raw
    };
    let raw = tokio::time::timeout(Duration::from_secs(30), execution).await.expect("bounded true fits");
    assert_eq!(code_digest(config), code, "training imports stayed pinned");
    let result: Value = serde_json::from_slice(&raw).unwrap();
    assert_eq!(result["schema"], "hepta.memory.population-training-result.v2");
    assert_eq!(result["request_digest"], Digest32::of_bytes(&request).to_string());
    assert_eq!(result["owner_cut_digest"], snapshot.owner_cut_digest().to_string());
    assert_eq!(result["configuration"], configuration);
    assert_eq!(result["receipt"]["fit_calls"], 2 * count);
    for kind in ["semantic", "procedure"] {
        for shard in result["receipt"]["types"][kind]["shards"].as_array().unwrap() {
            assert!(shard["training"]["parent_parameters"].is_null());
            assert_ne!(shard["training"]["initial_parameters"], shard["parameter_digest"]);
            assert!(shard["training"]["final_cross_entropy"].as_f64().unwrap() < shard["training"]["initial_cross_entropy"].as_f64().unwrap());
        }
    }
    (result, code)
}

fn native<'a>(result: &'a Value, kind: &str) -> &'a [u8] { result["artifacts"][kind]["native"].as_str().unwrap().as_bytes() }

#[tokio::test]
#[ignore = "requires pinned NumPy CPU training profile"]
async fn actual_population_split_merge_sleep_signed_release_and_source_cut_rejection() {
    let fixture = ControlFixture::new().await;
    let config = trainer();
    let nonce = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos().to_string();
    let expected = write_new(&fixture, &nonce, 0..12).await;
    let snapshot = fixture.snapshot().await;
    let (initial, code) = fit_population(&config, &snapshot, 1).await;
    let release = ReleaseFixture::from_populations_with_training_code(&snapshot, native(&initial, "semantic"), native(&initial, "procedure"), code);
    let resolver = TrustedTestResolver::new(&fixture);
    let _runtime = attach(&fixture, &release, &resolver);
    let mut stages = Vec::new();
    for (generation, count, mode) in [(1, 1, "fixed"), (2, 2, "split"), (3, 1, "merge")] {
        let (trained, code) = if generation == 1 { (initial.clone(), code) } else { fit_population(&config, &snapshot, count).await };
        if generation > 1 {
            let predecessor = release.host.load_current().unwrap();
            let proposal = release.prepare_populations(&snapshot, generation, native(&trained, "semantic"), native(&trained, "procedure"), code);
            release.host.publish(proposal.clone(), &snapshot).unwrap();
            assert!(release.host.revalidate(&predecessor).is_err());
            assert!(release.host.load_current().is_err(), "publication does not invent selection");
            release.install(&proposal).unwrap();
        }
        let loaded = release.host.load_current().unwrap();
        assert_eq!(loaded.semantic().shard_count(), count);
        assert_eq!(loaded.procedure().shard_count(), count);
        let started = Instant::now();
        let reads = readback(&fixture, &resolver, &expected).await;
        let roundtrip_wall_ns = started.elapsed().as_nanos();
        let awake = vec![loaded.semantic().cost().unwrap(), loaded.procedure().cost().unwrap()];
        for model in [loaded.semantic(), loaded.procedure()] {
            model.sleep().unwrap();
            assert_eq!(model.cost().unwrap().resident_parameter_bytes, 0);
        }
        let after_sleep = readback(&fixture, &resolver, &expected).await;
        for (model, before) in [loaded.semantic(), loaded.procedure()].into_iter().zip(&awake) {
            assert!(model.cost().unwrap().wake_count > before.wake_count);
        }
        let costs = vec![loaded.semantic().cost().unwrap(), loaded.procedure().cost().unwrap()];
        loaded.semantic().set_resident_budget(0).unwrap();
        resolver.set(TestRoute::Read(MemoryOperationV1::Semantic));
        let mut query = request(snapshot.scope().clone()); query.entity = expected[0].entity.clone();
        let denied = fixture.client.memory_cell_read(query).await.unwrap();
        assert_ne!(denied.status, MemoryReadStatusV1::Ok);
        assert!(denied.value.is_null() && denied.source_ids.is_empty() && denied.cell_digests.is_empty());
        loaded.semantic().set_resident_budget(awake[0].resident_budget_bytes).unwrap();
        stages.push(json!({"generation":generation,"shards_per_type":count,"transition":mode,
            "training":trained["receipt"],"readback":reads,"after_sleep_readback":after_sleep,
            "runtime_costs":costs,"socket_roundtrip_including_inference_wall_ns":roundtrip_wall_ns,
            "budget_failure_closed":true,"independent_future_task_evaluation":false}));
    }
    let stale = release.prepare_populations(&snapshot, 4, native(&initial, "semantic"), native(&initial, "procedure"), code);
    fixture.store.write_memory_cell(&fixture.access(), &CognitiveScope::AgentPrivate,
        &row(&expected[0], MemoryCellKindV1::Semantic, json!({"factor":29,"label":"post-training owner correction"})),
        MemoryCellWriteModeV1::Correct { expected_revision: 1 }).await.unwrap();
    let current = fixture.snapshot().await;
    assert_ne!(snapshot.owner_cut_digest(), current.owner_cut_digest());
    assert!(release.host.publish(stale, &current).is_err(), "source-cut changes block old structure publication");
    resolver.set(TestRoute::Read(MemoryOperationV1::Apply));
    let mut query = request(snapshot.scope().clone()); query.entity = expected[0].entity.clone();
    let denied = fixture.client.memory_cell_read(query).await.unwrap();
    assert_ne!(denied.status, MemoryReadStatusV1::Ok);
    assert!(denied.value.is_null() && denied.source_ids.is_empty());
    let report = json!({"schema":"hepta.memory.v7.actual-population-lifecycle.v2","nonce":nonce,
        "training_code_digest":code.to_string(),"stages":stages,"stale_source_cut_rejected":true,
        "structural_net_benefit_established":false,"source_ledger_cost":null,"exclusive_communication_cost":null,
        "independent_future_task_evaluation":false,"natural_language_evaluation":false});
    let path = std::env::var_os("MEMORY_CELL_POPULATION_RECEIPT_PATH").map(PathBuf::from)
        .unwrap_or_else(|| std::env::temp_dir().join(format!("hepta-memory-population-receipt-{}.json", std::process::id())));
    assert!(path.is_absolute());
    std::fs::create_dir_all(path.parent().unwrap()).unwrap();
    std::fs::write(&path, serde_json::to_vec_pretty(&report).unwrap()).unwrap();
    println!("MEMORY_CELL_POPULATION_RECEIPT_PATH={}", path.display());
    println!("MEMORY_CELL_POPULATION_RECEIPT={report}");
    fixture.finish().await;
}
