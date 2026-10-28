//! Bounded V9 population fitting and completed-prefix-only selection.

use std::collections::BTreeSet;
use std::path::Path;

use codex_hepta_memory::MemoryCellOwnerSnapshotV1;
use codex_hepta_types::Digest32;
use serde_json::Value;
use serde_json::json;

use crate::MemoryCellTrainerConfigV1;
use crate::memory_cell_release::test_support::ReleaseFixture;
use crate::memory_cell_release::sleep_selected_memory_v9;
use crate::memory_cell_runtime_tests::TrustedTestResolver;
use crate::memory_cell_test_support::ControlFixture;

use super::super::{data,fit};

pub(super) const BUDGET: u64 = 16_384;

pub(super) fn code(config: &MemoryCellTrainerConfigV1) -> Value {
    let mut result = fit::code_identity(config);
    for name in ["memory-cell-v7/population_training.py","memory-cell-v8/learning/__init__.py",
        "memory-cell-v8/learning/allocation.py","memory-cell-v8/learning/population_training.py",
        "memory-cell-v8/learning/worker.py","memory-cell-v9/learning/structure_selection.py",
        "memory-cell-v9/learning/STRUCTURE_PROTOCOL.json"] {
        let raw = std::fs::read(config.qualification_root.join(name)).unwrap();
        result["files"][name] = json!({"bytes":raw.len(),"sha256":Digest32::of_bytes(&raw).to_string()});
    }
    result["digest"] = json!(Digest32::of_bytes(&serde_json::to_vec(&result["files"]).unwrap()).to_string());
    result
}

pub(super) async fn train(config: &MemoryCellTrainerConfigV1, snapshot: &MemoryCellOwnerSnapshotV1,
    count: usize, trace: Option<&Value>, directory: &Path, identity: &Value) -> Value {
    std::fs::create_dir(directory).unwrap();
    let configuration = json!({"shard_count":count,"seed":91317,"steps":600,"dimension":48,"total_hidden":64,"threshold":0.5});
    let frame = json!({"schema":"hepta.memory.prospective-population-fit.v1","export":snapshot,
        "configuration":configuration,"routing_mode":if trace.is_some() {"learned"} else {"fixed"},"routing_trace":trace});
    let result = fit::execute(config,&frame,"memory-cell-v8/learning/worker.py",identity,directory).await;
    assert_eq!(code(config),*identity);
    assert_eq!(result["configuration"],configuration);
    assert_eq!(result["owner_cut_digest"],snapshot.owner_cut_digest().to_string());
    assert_eq!(result["receipt"]["fit_calls"],2*count);
    result
}

pub(super) async fn select(config: &MemoryCellTrainerConfigV1, snapshot: &MemoryCellOwnerSnapshotV1,
    prefix: &Value, directory: &Path, identity: &Value) -> Value {
    std::fs::create_dir(directory).unwrap();
    let addresses: BTreeSet<_> = snapshot.records().iter()
        .filter(|row| snapshot.current_source_ids().contains(&row.source_id))
        .map(|row|Digest32::of_bytes(row.record.entity.as_str().as_bytes()).to_string()).collect();
    let observations = prefix["records"].as_array().unwrap().iter().enumerate().map(|(index,record)| {
        let used: BTreeSet<_> = record["requests"].as_array().unwrap().iter()
            .map(|query|Digest32::of_bytes(query["entity"].as_str().unwrap().as_bytes()).to_string()).collect();
        json!({"sequence":index+1,"request_digest":record["request_digest"],"readout_digest":record["readout_digest"],"addresses":used})
    }).collect::<Vec<_>>();
    let frame = json!({"schema":"hepta.memory.v9.structure-selection.v1","source_cut_digest":snapshot.owner_cut_digest(),
        "addresses":addresses,"observations":observations,"resident_budget_bytes":BUDGET});
    let result = fit::execute(config,&frame,"memory-cell-v9/learning/structure_selection.py",identity,directory).await;
    assert_eq!(code(config),*identity);
    assert_eq!(result["fit_calls"],0);
    assert_eq!(result["future_task_fields_seen"],false);
    result
}

pub(super) fn native<'a>(trained: &'a Value, kind: &str) -> &'a [u8] {
    trained["artifacts"][kind]["native"].as_str().unwrap().as_bytes()
}

pub(super) fn budget(release: &ReleaseFixture) {
    let selected = release.host.load_current().unwrap();
    for model in [selected.semantic(),selected.procedure()] { model.set_resident_budget(BUDGET).unwrap(); }
}

pub(super) fn publish(release: &ReleaseFixture, snapshot: &MemoryCellOwnerSnapshotV1,
    trained: &Value, generation: u64, identity: Digest32) -> Value {
    let proposal = release.prepare_populations(snapshot,generation,native(trained,"semantic"),native(trained,"procedure"),identity);
    release.host.publish(proposal.clone(),snapshot).unwrap();
    release.install(&proposal).unwrap();
    budget(release);
    let loaded = release.host.load_current().unwrap();
    json!({"generation":loaded.generation().get(),"bundle_digest":loaded.bundle_digest(),
        "bundle_bytes":proposal.payload.len(),
        "source_cut":loaded.owner_cut_digest(),"semantic_digest":loaded.semantic().digest().to_string(),
        "procedure_digest":loaded.procedure().digest().to_string()})
}

pub(super) async fn evaluate(owner: &ControlFixture, resolver: &TrustedTestResolver, release: &ReleaseFixture,
    stage: &data::Stage, directory: &Path, role: &str, fit_directory: &str, publication: Value, count: usize) -> Value {
    let mut phases = Vec::new();
    for (phase,tasks) in [("future",&stage.future),("retention",&stage.retention)] {
        let asleep = sleep_selected_memory_v9(&release.host,publication["bundle_digest"].as_str().unwrap().parse().unwrap()).unwrap();
        assert!(asleep.iter().all(|cost|cost.resident_shards == 0));
        let mut batch = data::evaluate(owner,&data::Reader::Native(resolver),tasks).await;
        let loaded = release.host.load_current().unwrap();
        batch["native_cost"] = json!([loaded.semantic().cost().unwrap(),loaded.procedure().cost().unwrap()]);
        let identity = data::save(&directory.join(format!("{role}-{phase}.json")),&batch);
        phases.push(json!({"identity":identity,"queries":batch["queries"],"correct":batch["correct"],
            "tasks":batch["tasks"],"decisions_correct":batch["decisions_correct"],"wall_ns":batch["wall_ns"],
            "traffic":batch["traffic"],"native_cost":batch["native_cost"]}));
    }
    json!({"role":role,"fit_directory":fit_directory,"publication":publication,"shards":count,"phases":phases})
}
