//! Control-only fixture startup uses the real Agentd exclusive writer lock,
//! canonical SQLite owner and signed release owner. Readiness is a test seam.

use std::collections::BTreeMap;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_cognitive_store::DurableCognitiveStore;
use codex_hepta_cognitive_types::{MemoryInventoryRequestV1, MemoryOperationV1};
use codex_hepta_cognitive_types::hnmf::{ContractDigestV1, ContractGenerationV1};
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_learning_artifacts::DatasetWithdrawalNoticeV1;
use codex_hepta_memory::{CognitiveAccess, CognitiveRecoveryRequirement, CognitiveScope, MemoryCellWriteModeV1, MemoryInventoryOwnerSnapshotV1, MemoryInventoryRecordV1};
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use serde_json::{Value, json};
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::sync::Notify;
use tokio_util::sync::CancellationToken;

use crate::{AgentdConfig, AgentdControlServer, AgentdMemoryInventoryRuntimeV1, AgentdState, MemoryCellAddressWorkerConfigV1,
    MemoryInventoryAddressResolverV1, MemoryInventoryAddressWorkerV1, MemoryInventoryBundleCandidateV1, MemoryInventoryResolvedAddressV1};
use crate::memory_cell_release::test_support::{digest, id};
use crate::memory_inventory_release_test_support::InventoryReleaseFixture;
use crate::memory_inventory_withdrawal_test_support::InventoryWithdrawalCheckpoint;
use super::{SPEC_ENV, Spec, WorkerSpec, emit};

#[derive(Default)]
struct OracleGate {
    entered: Notify,
    resume: Notify,
}

impl MemoryInventoryAddressResolverV1 for OracleGate {
    fn model_digest(&self) -> ContractDigestV1 {
        ContractDigestV1::from_digest(digest("inventory-native-actual-explicit-oracle-v1")).expect("oracle label")
    }

    fn resolve<'a>(&'a self, request: &'a MemoryInventoryRequestV1, owner: &'a MemoryInventoryOwnerSnapshotV1)
        -> Pin<Box<dyn Future<Output = Result<Option<MemoryInventoryResolvedAddressV1>, String>> + Send + 'a>> {
        Box::pin(async move {
            let text = if let Some(text) = request.text.strip_prefix("gate:") {
                self.entered.notify_one();
                self.resume.notified().await;
                text
            } else { &request.text };
            let operation = match text {
                "current" => MemoryOperationV1::Current, "history" => MemoryOperationV1::History,
                "change" => MemoryOperationV1::Change, "semantic" => MemoryOperationV1::Semantic,
                "procedure" => MemoryOperationV1::Procedure, "apply" => MemoryOperationV1::Apply,
                _ => return Ok(None),
            };
            Ok(Some(MemoryInventoryResolvedAddressV1 { request: request.clone(), operation,
                owner_cut_digest: owner.owner_cut_digest(), model_digest: self.model_digest() }))
        })
    }
}

pub(crate) async fn child_main() {
    let spec: Spec = serde_json::from_slice(&std::fs::read(std::env::var_os(SPEC_ENV).expect("parent launch spec")).expect("spec bytes")).expect("child spec");
    let registry = FleetRegistry::open_existing(HeptaFleetRoot::parse(spec.fleet_root.clone()).expect("fleet root")).expect("existing fleet");
    let record = registry.load_agent(&spec.owner).expect("registered owner");
    if let Some(recovery) = &spec.recovery {
        assert!(!recovery.unavailable_source.exists(), "original source path must be absent");
        let admitted = DurableCognitiveStore::open_read_only_recovery(&record.layout,
            CognitiveRecoveryRequirement::ExactCurrentCut(&recovery.pin.cognitive_anchor)).await.expect("independent cold-image exact anchor admission");
        assert!(admitted.anchor() == &recovery.pin.cognitive_anchor);
        drop(admitted);
    }
    let config = AgentdConfig::load(spec.fleet_root, spec.owner.clone(), spec.spawn_generation,
        record.layout.home_root().to_path_buf(), record.layout.run_root().to_path_buf(), record.layout.home_root().to_path_buf(),
        record.manifest.workspace.as_path().to_path_buf()).expect("exclusive Agentd writer lock");
    let identity = config.identity().clone();
    let state = Arc::new(AgentdState::new(identity.clone(), registry, 16).expect("actual Agentd state"));
    let store = Arc::new(DurableCognitiveStore::open(&identity.layout).await.expect("actual SQLite owner"));
    let access = CognitiveAccess::agent_private(spec.owner.clone());
    if let Some(path) = spec.records {
        let records: Vec<MemoryInventoryRecordV1> = serde_json::from_slice(&std::fs::read(path).expect("initial source bytes")).expect("typed records");
        for record in records { store.write_memory_inventory(&access, &CognitiveScope::AgentPrivate, &record, MemoryCellWriteModeV1::Create).await.expect("owner source creation"); }
    }
    let gate = Arc::new(OracleGate::default());
    let worker = match spec.worker { Some(worker) => Some(Arc::new(start_worker(worker).await)), None => None };
    let resolver: Arc<dyn MemoryInventoryAddressResolverV1> = match &worker {
        Some(worker) => worker.clone(), None => gate.clone(),
    };
    let mut release = match spec.resume {
        Some(checkpoint) => {
            let withdrawals = spec.recovery.as_ref().and_then(|recovery| recovery.withdrawal.as_ref())
                .map(|withdrawal| withdrawal.restore(&spec.artifact_root));
            let expected_refusal = withdrawals.is_some();
            let result = InventoryReleaseFixture::try_reopen(spec.artifact_root.clone(), &snapshot(&store, &access).await, checkpoint, withdrawals);
            if expected_refusal {
                let Err(reason) = result else { panic!("revoked parameters were reselected after restoring their frontier"); };
                assert!(reason.to_lowercase().contains("withdraw"), "refusal must identify the restored withdrawal frontier: {reason}");
                drop(state);
                store.as_ref().clone().close().await;
                drop(store);
                drop(config);
                emit(json!({"pid":std::process::id(),"owner":spec.owner,"spawn_generation":spec.spawn_generation,
                    "refused":true,"reason":reason,"recovery":spec.recovery,"reaped_by_parent":true}));
                return;
            }
            Some(result.expect("inventory owner readmission"))
        }
        None => None,
    };
    if let Some(release) = &release { attach(&state, &spec.owner, spec.spawn_generation, release, Arc::clone(&resolver)); }
    if let Some(recovery) = &spec.recovery {
        let current = snapshot(&store, &access).await;
        let selected = release.as_ref().expect("migrated selection").host.load_current().expect("actual migrated selected bundle");
        assert!(current.owner_agent_id() == &recovery.pin.owner_agent_id && current.scope() == &recovery.pin.scope
            && current.owner_cut_digest() == recovery.pin.owner_cut_digest && selected.bundle_digest() == recovery.pin.bundle_digest
            && selected.generation() == recovery.pin.generation);
    }
    state.attach_cognitive_store(Arc::clone(&store)).expect("owner attachment");
    let cancellation = CancellationToken::new();
    let server = AgentdControlServer::bind(identity.control_socket, Arc::clone(&state), cancellation.clone()).await.expect("real control socket");
    let control = tokio::spawn(server.run());
    emit(json!({"pid":std::process::id(),"owner":spec.owner,"spawn_generation":spec.spawn_generation,
        "resolver":if worker.is_some(){"trained_operation_with_deterministic_keys"}else{"explicit_oracle_test_seam"},"recovery":spec.recovery}));
    let mut input = BufReader::new(tokio::io::stdin()).lines();
    while let Some(line) = input.next_line().await.expect("owner command") {
        let command: Value = serde_json::from_str(&line).expect("test command JSON");
        let response = match command["op"].as_str().expect("command kind") {
            "activate" => {
                state.refresh_generation().expect("Running fence");
                state.mark_runtime_prerequisites_ready().expect("real stores ready");
                state.mark_app_server_ready().expect("explicit control-only readiness seam");
                json!({"ready":true})
            }
            "install" | "validate" => {
                let semantic = std::fs::read(command["semantic"].as_str().expect("semantic path")).expect("semantic bytes");
                let procedure = std::fs::read(command["procedure"].as_str().expect("procedure path")).expect("procedure bytes");
                let owner = snapshot(&store, &access).await;
                if command["op"] == "validate" {
                    let accepted = MemoryInventoryBundleCandidateV1::from_owner_snapshot(&owner, ContractGenerationV1::new(1).expect("generation"), &semantic, &procedure).is_ok();
                    json!({"accepted":accepted})
                } else {
                    let code: Digest32 = command["code"].as_str().expect("code digest").parse().expect("code digest");
                    match &mut release {
                        Some(release) => release.replace(&owner, &semantic, &procedure, code),
                        None => {
                            let installed = InventoryReleaseFixture::create(spec.artifact_root.clone(), &owner, &semantic, &procedure, code);
                            attach(&state, &spec.owner, spec.spawn_generation, &installed, Arc::clone(&resolver));
                            release = Some(installed);
                        }
                    }
                    let release = release.as_ref().expect("installed release");
                    json!({"checkpoint":release.checkpoint(),"bundle":release.host.load_current().expect("selected bundle").bundle_digest()})
                }
            }
            "sleep" => { release.as_ref().expect("release").host.sleep_selected().expect("cache sleep"); json!({"slept":true}) }
            "correct" => {
                let record: MemoryInventoryRecordV1 = serde_json::from_value(command["record"].clone()).expect("corrected record");
                store.write_memory_inventory(&access, &CognitiveScope::AgentPrivate, &record,
                    MemoryCellWriteModeV1::Correct { expected_revision: command["revision"].as_u64().expect("revision") }).await.expect("actual owner correction");
                json!({"corrected":true})
            }
            "forget" => {
                let record: MemoryInventoryRecordV1 = serde_json::from_value(command["record"].clone()).expect("forgotten address");
                store.forget_memory_inventory(&access, &CognitiveScope::AgentPrivate, &record.address(), command["revision"].as_u64().expect("revision"),
                    "explicit native actual owner deletion", now()).await.expect("actual owner deletion");
                json!({"forgotten":true})
            }
            "revoke" => {
                let release = release.as_ref().expect("release");
                let mut owner = release.service.lock().expect("artifact owner");
                let mut withdrawals = owner.withdrawal_registry().clone();
                withdrawals.append(DatasetWithdrawalNoticeV1 {
                    notice_id:id("inventory-native-actual-withdrawal"), dataset_digest:release.request.admission.validated_manifest.manifest.lineage_digests[0],
                    source_tombstone_digest:digest("inventory-native-actual-tombstone"), authority_id:id("memory-dataset-owner"),
                    credential_chain_digest:digest("inventory-test-credential"), signing_key_digest:digest("inventory-test-dataset-signer"), authority_epoch:1, issued_at:now() as u64,
                }).expect("actual withdrawal frontier");
                owner.install_withdrawal_frontier(withdrawals).expect("owner withdrawal installation");
                let receipt = InventoryWithdrawalCheckpoint::capture(&spec.artifact_root, owner.withdrawal_registry());
                json!({"revoked":true,"withdrawal_checkpoint":receipt})
            }
            "wait_gate" => { gate.entered.notified().await; json!({"entered":true}) }
            "release_gate" => { gate.resume.notify_one(); json!({"released":true}) }
            "worker_receipt" => {
                let worker = worker.as_ref().expect("actual address worker");
                let response = worker.take_last_validated_response().await.expect("validated response");
                let response: Value = serde_json::from_slice(&response).expect("validated response JSON");
                json!({"response":response,"model_digest":worker.model_digest()})
            }
            "stop" => {
                cancellation.cancel();
                break;
            }
            _ => panic!("unknown native actual test command"),
        };
        emit(response);
    }
    cancellation.cancel();
    control.await.expect("join actual control server").expect("stop actual control server");
    let metrics = worker.as_ref().map(|worker| {
        let m=worker.metrics(); json!({"attempted":m.attempted_requests,"validated":m.validated_responses,"process_starts":m.process_starts,
            "stdin_bytes":m.stdin_bytes,"stdout_bytes":m.stdout_bytes,"cpu_nanoseconds":m.reported_cpu_nanoseconds,"wall_nanoseconds":m.reported_wall_nanoseconds})
    });
    drop(state);
    drop(release);
    store.as_ref().clone().close().await;
    drop(store);
    drop(config);
    emit(json!({"stopped":true,"worker_metrics":metrics}));
}

fn attach(state: &AgentdState, owner: &codex_hepta_contracts::AgentId, generation: u64, release: &InventoryReleaseFixture, resolver: Arc<dyn MemoryInventoryAddressResolverV1>) {
    state.attach_memory_inventory(Arc::new(AgentdMemoryInventoryRuntimeV1::new(owner.clone(), generation, CognitiveScope::AgentPrivate,
        Arc::clone(&release.host), resolver).expect("inventory runtime"))).expect("actual runtime attachment");
}

async fn snapshot(store: &DurableCognitiveStore, access: &CognitiveAccess) -> MemoryInventoryOwnerSnapshotV1 {
    store.memory_inventory_snapshot(access, &CognitiveScope::AgentPrivate, now()).await.expect("actual owner snapshot")
}

fn now() -> i64 { crate::memory_cell_runtime::now_unix_seconds().expect("clock") }

async fn start_worker(spec: WorkerSpec) -> MemoryInventoryAddressWorkerV1 {
    let mut pins = BTreeMap::new();
    for directory in [&spec.research, &spec.research.parent().expect("qualification").join("memory-cell-adapters")] {
        for entry in std::fs::read_dir(directory).expect("first-party closure") {
            let path = entry.expect("code entry").path();
            if path.extension().is_some_and(|extension| extension == "py") {
                pins.insert(path.clone(), ContractDigestV1::from_digest(Digest32::of_bytes(&std::fs::read(path).expect("code bytes"))).expect("code pin"));
            }
        }
    }
    let script = spec.research.join("inventory_worker.py");
    let model_digest = ContractDigestV1::from_digest(Digest32::of_bytes(&std::fs::read(spec.model.join("manifest.json")).expect("router manifest"))).expect("model digest");
    MemoryInventoryAddressWorkerV1::start(MemoryCellAddressWorkerConfigV1 {
        python:spec.python, worker_script_digest:pins[&script], worker_script:script, code_pins:pins, model_directory:spec.model,
        model_digest, encoder_directory:spec.encoder, aliases:BTreeMap::new(), request_timeout:Duration::from_millis(1_500), startup_timeout:Duration::from_secs(30),
    }).await.expect("actual trained inventory address worker")
}
