//! Opt-in real parameters, separate owner processes and actual Agentd sockets.
//! Oracle routing controls content/lifecycle tests; trained hybrid routing is
//! exercised separately and reported under its own model and process identity.

use std::path::PathBuf;

use codex_hepta_cognitive_types::{MemoryInventoryKindV1, MemoryReadStatusV1};
use codex_hepta_fleet::AgentLifecycle;
use pretty_assertions::assert_eq;
use serde_json::{Value, json};

use crate::AgentdClient;
use crate::memory_inventory_release_test_support::InventoryReleaseCheckpoint;
use crate::memory_inventory_withdrawal_test_support::InventoryWithdrawalCheckpoint;

#[path = "memory_inventory_actual_cases.rs"]
mod cases;
#[path = "memory_inventory_process_test_support.rs"]
mod process;
#[path = "memory_inventory_migration_actual.rs"]
mod migration;
#[path = "memory_inventory_numeric_actual.rs"]
mod numeric;
use cases::{Inputs, check_composition, check_written_values, empty_failure, export, initial_records, install, query, record, save};
use process::{NativeOwner, WorkerSpec};

#[tokio::test]
#[ignore = "only the native actual parent launches this separate owner process"]
async fn memory_inventory_owner_child() { process::child_main().await; }

#[tokio::test]
#[ignore = "requires explicit V10 Python, encoder, legacy checkpoint and fresh evidence paths"]
async fn memory_inventory_actual_trained_owner_lifecycle() {
    let inputs = Inputs::load();
    let root = inputs.output.join("native-owner");
    std::fs::create_dir(&root).expect("isolated native owner root");
    let (registry, owner) = process::fleet(&root);
    let records = initial_records(&inputs.legacy);
    let records_path = root.join("authored-records.json");
    save(&records_path, &json!(records));
    let mut process = NativeOwner::spawn(&root, &registry, owner.clone(), Some(records_path), None, None, None).await;
    let mut processes = Vec::new();
    let mut observations = Vec::<Value>::new();
    let snapshot_path = inputs.output.join("owner-before.json");
    let pages = export(&process.client, &snapshot_path).await;
    assert_eq!(pages.iter().map(|page| page.records.len()).sum::<usize>(), 32);
    let scope = pages[0].scope.clone();
    let models = inputs.fit_or_export("original-checkpoint", &snapshot_path, true).await;
    observations.push(json!({"stage":"original_checkpoint_native_numeric_parity","receipt":numeric::verify(&models, &pages)}));
    let installed = install(&mut process, &models, &inputs.research.join("legacy_worker.py")).await;
    let checkpoint: InventoryReleaseCheckpoint = serde_json::from_value(installed["checkpoint"].clone()).expect("durable release checkpoint");
    let initial = check_written_values(&process.client, &pages).await;
    observations.push(json!({"stage":"original_parameters_on_actual_owner","reads":initial,"selection":installed}));
    for (entity, workflow) in [(0, 0), (0, 1), (1, 0), (1, 1)] {
        observations.push(json!({"stage":"independent_entity_and_workflow_composition","entity":entity,"workflow":workflow,
            "read":check_composition(&process.client, &pages, entity, workflow).await}));
    }
    let mut bounded = query(&scope, "apply", 0, 0);
    bounded.max_steps = 2;
    let stopped = process.client.memory_inventory_read(bounded).await.expect("step-bound read");
    empty_failure(&stopped, MemoryReadStatusV1::BudgetExceeded);
    observations.push(json!({"stage":"step_budget","read":stopped}));
    assert_eq!(process.command(json!({"op":"sleep"})).await, json!({"slept":true}));
    let woke = check_composition(&process.client, &pages, 0, 0).await;
    observations.push(json!({"stage":"decoded_cache_reloaded","read":woke,"rss_claim":false}));
    let malformed_path = inputs.output.join("malformed-semantic.json");
    let mut malformed = std::fs::read(models.join("semantic.json")).expect("trained bytes");
    malformed[0] ^= 1;
    std::fs::write(&malformed_path, malformed).expect("negative fixture");
    assert_eq!(process.command(json!({"op":"validate","semantic":malformed_path,"procedure":models.join("procedure.json")})).await,
        json!({"accepted":false}));
    check_composition(&process.client, &pages, 0, 0).await;

    // Suspend a real socket request inside addressing, then close the real
    // lifecycle before releasing it. A successful model result cannot escape.
    let registration = registry.load_agent(&owner).expect("owner registration");
    let client = AgentdClient::new(registration.layout.agentd_control_socket().to_path_buf(), owner.clone(), process.ready["spawn_generation"].as_u64().expect("spawn generation")).expect("inflight client");
    let gated = query(&scope, "gate:apply", 0, 0);
    let inflight = tokio::spawn(async move { client.memory_inventory_read(gated).await });
    assert_eq!(process.command(json!({"op":"wait_gate"})).await, json!({"entered":true}));
    registry.compare_and_transition(&owner, registration.lifecycle.generation, AgentLifecycle::Draining).expect("real owner draining");
    process.command(json!({"op":"release_gate"})).await;
    assert!(inflight.await.expect("join inflight read").is_err());
    assert!(process.client.memory_inventory_snapshot(None, None, 16).await.is_err());
    assert!(process.client.memory_inventory_read(query(&scope, "apply", 0, 0)).await.is_err());
    processes.push(process.stop(&registry, &owner).await);
    assert!(process.client.memory_inventory_read(query(&scope, "apply", 0, 0)).await.is_err());
    save(&inputs.output.join("native-progress.json"), &json!({"observations":observations,"processes":processes}));

    // Reopen the exact persisted owner and selected residual bytes in a fresh
    // OS process after the original Torch and original owner have both exited.
    let mut process = NativeOwner::spawn(&root, &registry, owner.clone(), None, Some(checkpoint), None, None).await;
    let resumed = check_written_values(&process.client, &pages).await;
    observations.push(json!({"stage":"fresh_process_original_parameters","reads":resumed,"process":process.ready}));
    let corrected = record(MemoryInventoryKindV1::Semantic, 1, json!({"reserve":5,"pack":4,"limit":11}));
    process.command(json!({"op":"correct","record":corrected,"revision":1})).await;
    let unrelated = process.client.memory_inventory_read(query(&scope, "semantic", 0, 0)).await.expect("stale full cut read");
    empty_failure(&unrelated, MemoryReadStatusV1::Stale);
    let hold = record(MemoryInventoryKindV1::Hold, 2, json!(true));
    process.command(json!({"op":"correct","record":hold,"revision":1})).await;
    observations.push(json!({"stage":"unqueried_correction_invalidates_complete_cut","read":unrelated}));
    let corrected_snapshot = inputs.output.join("owner-corrected.json");
    let corrected_pages = export(&process.client, &corrected_snapshot).await;
    assert_ne!(corrected_pages[0].owner_cut_digest, pages[0].owner_cut_digest);
    let updated = inputs.fit_or_export("corrected-training", &corrected_snapshot, false).await;
    observations.push(json!({"stage":"corrected_training_native_numeric_parity","receipt":numeric::verify(&updated, &corrected_pages)}));
    let installed = install(&mut process, &updated, &inputs.research.join("native_train_worker.py")).await;
    let checkpoint: InventoryReleaseCheckpoint = serde_json::from_value(installed["checkpoint"].clone()).expect("trained release checkpoint");
    let retained = check_written_values(&process.client, &corrected_pages).await;
    observations.push(json!({"stage":"actual_new_training_and_retention","selection":installed,"reads":retained}));
    let held = process.client.memory_inventory_read(query(&scope, "apply", 2, 0)).await.expect("explicit hold read");
    empty_failure(&held, MemoryReadStatusV1::Abstain);
    assert_eq!(held.reason.as_deref(), Some("inventory entity is on hold"));
    observations.push(json!({"stage":"owner_exception","read":held}));
    processes.push(process.stop(&registry, &owner).await);

    let mut process = NativeOwner::spawn(&root, &registry, owner.clone(), None, Some(checkpoint), None, None).await;
    let cold = check_written_values(&process.client, &corrected_pages).await;
    observations.push(json!({"stage":"fresh_process_new_training","reads":cold,"process":process.ready}));
    check_composition(&process.client, &corrected_pages, 1, 0).await;
    let removed = records.iter().find(|row| row.kind == MemoryInventoryKindV1::Semantic && row.key.as_str() == "inventory:semantic:0").expect("source being deleted");
    process.command(json!({"op":"forget","record":removed,"revision":1})).await;
    let stale = process.client.memory_inventory_read(query(&scope, "semantic", 1, 0)).await.expect("post-delete stale read");
    empty_failure(&stale, MemoryReadStatusV1::Stale);
    let deleted_snapshot = inputs.output.join("owner-deleted.json");
    let deleted_pages = export(&process.client, &deleted_snapshot).await;
    assert_eq!(deleted_pages.iter().map(|page| page.records.len()).sum::<usize>(), 31);
    let rebuilt = inputs.fit_or_export("deleted-rebuild", &deleted_snapshot, false).await;
    observations.push(json!({"stage":"deleted_rebuild_native_numeric_parity","receipt":numeric::verify(&rebuilt, &deleted_pages)}));
    let installed = install(&mut process, &rebuilt, &inputs.research.join("native_train_worker.py")).await;
    let checkpoint: InventoryReleaseCheckpoint = serde_json::from_value(installed["checkpoint"].clone()).expect("rebuilt checkpoint");
    let survivors = check_written_values(&process.client, &deleted_pages).await;
    let forgotten = process.client.memory_inventory_read(query(&scope, "semantic", 0, 0)).await.expect("removed key read");
    empty_failure(&forgotten, MemoryReadStatusV1::Abstain);
    observations.push(json!({"stage":"delete_and_rebuild_from_remaining_sources","selection":installed,"reads":survivors,"removed_key":forgotten}));
    processes.push(process.stop(&registry, &owner).await);
    save(&inputs.output.join("native-progress.json"), &json!({"observations":observations,"processes":processes}));

    let router = std::env::var_os("HEPTA_MEMORY_V10_ROUTER").map(PathBuf::from).unwrap_or_else(|| rebuilt.join("inventory-router"));
    assert!(router.join("manifest.json").is_file(), "explicit trained inventory router is required for actual worker qualification");
    let (destination, destination_registry, mut recovery, migration_evidence) = migration::transfer(&inputs.output, &root, &registry, &owner, &checkpoint).await;
    let worker = WorkerSpec { python:inputs.python.clone(), research:inputs.research.clone(), model:router, encoder:inputs.encoder.clone() };
    let mut process = NativeOwner::spawn(&destination, &destination_registry, owner.clone(), None, Some(checkpoint.clone()), Some(worker), Some(recovery.clone())).await;
    let mut routed_query = query(&scope, "apply", 1, 0);
    routed_query.text = "Use workflow inventory:procedure:0 with the current stock for inventory:semantic:1.".into();
    let routed = process.client.memory_inventory_read(routed_query.clone()).await.expect("actual worker exchange and model execution");
    assert_eq!(routed.status, MemoryReadStatusV1::Ok);
    assert_eq!(routed.cell_digests.len(), 2);
    let worker_receipt = process.command(json!({"op":"worker_receipt"})).await;
    observations.push(json!({"stage":"fresh_process_trained_hybrid_worker","read":routed,"process":process.ready,
        "operation_learned":true,"key_binding":"deterministic_unique_registry_match","worker_receipt":worker_receipt}));
    let mut unsupported = routed_query.clone();
    unsupported.text = "Use workflow inventory:procedure:0 for inventory:semantic:1 and inventory:semantic:3.".into();
    let declined = process.client.memory_inventory_read(unsupported).await.expect("ambiguous worker request");
    empty_failure(&declined, MemoryReadStatusV1::Abstain);
    let revoked = process.command(json!({"op":"revoke"})).await;
    let withdrawal: InventoryWithdrawalCheckpoint = serde_json::from_value(revoked["withdrawal_checkpoint"].clone()).expect("independently retained frontier receipt");
    assert!(process.client.memory_inventory_read(routed_query).await.is_err());
    observations.push(json!({"stage":"ambiguous_address_and_real_artifact_revocation","ambiguous":declined,"revoked_read_rejected":true,
        "withdrawal":revoked,"revocation_scope":"live frontier followed by parent-pinned cold frontier restoration"}));
    processes.push(process.stop(&destination_registry, &owner).await);
    recovery.withdrawal = Some(withdrawal);
    let refused = NativeOwner::spawn(&destination, &destination_registry, owner.clone(), None, Some(checkpoint), None, Some(recovery)).await;
    assert_eq!(refused.ready["refused"], json!(true));
    assert!(refused.client.memory_inventory_read(query(&scope, "apply", 1, 0)).await.is_err());
    observations.push(json!({"stage":"cold_reopen_with_retained_withdrawal_frontier","refusal":refused.ready,
        "control_read_rejected":true,"frontier_floor":"independent parent-held receipt; production authentication remains a control-plane responsibility"}));
    processes.push(json!({"process":refused.ready,"reaped":true,"control":refused.client.traffic_snapshot(),
        "frames_tx_bytes":refused.frames_tx_bytes,"frames_rx_bytes":refused.frames_rx_bytes}));
    save(&inputs.output.join("NATIVE_ACTUAL.json"), &json!({
        "schema":"hepta.memory.inventory-native-actual.v1","status":"passed","parent_pid":std::process::id(),
        "separate_owner_processes":processes.len(),"readiness":"explicit_control_only_test_seam","old_holdout_run":false,
        "authority":"real_SQLite_owner_and_signed_artifact_owner_with_explicit_test_keys", "observations":observations,"processes":processes,
        "migration":migration_evidence,"migration_claim":"actual_same_host_TCP_to_independent_root; no cross_physical_host_claim", "rss_claim":false,
    }));
}
