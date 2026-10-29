//! Native actual inputs and assertions. No frozen holdout files are loaded.

use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::time::{Duration, Instant};

use codex_hepta_cognitive_types::{MemoryInventoryKindV1, MemoryInventoryPolicyV1, MemoryInventoryProgramV1, MemoryInventoryReadoutV1, MemoryInventoryRequestV1, MemoryReadStatusV1, execute_memory_inventory_program_v1};
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_memory::MemoryInventoryRecordV1;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use serde_json::{Value, json};
use tokio::process::Command;

use crate::{AgentdClient, MemoryInventorySnapshotPageV1};
use super::process::NativeOwner;

pub(super) struct Inputs {
    pub python: PathBuf,
    pub research: PathBuf,
    pub encoder: PathBuf,
    pub legacy: PathBuf,
    pub output: PathBuf,
}

impl Inputs {
    pub fn load() -> Self {
        let path = |name| {
            let path = PathBuf::from(std::env::var_os(name).expect("explicit native actual input"));
            assert!(path.is_absolute(), "native actual paths must be absolute");
            path
        };
        let inputs = Self {
            python:path("HEPTA_MEMORY_V10_PYTHON"), research:path("HEPTA_MEMORY_V10_RESEARCH_ROOT"),
            encoder:path("HEPTA_MEMORY_V10_ENCODER"), legacy:path("HEPTA_MEMORY_V10_LEGACY_ROOT"), output:path("HEPTA_MEMORY_V10_EVIDENCE"),
        };
        std::fs::create_dir(&inputs.output).expect("new immutable native actual evidence directory");
        inputs
    }

    pub async fn fit_or_export(&self, label: &str, snapshot: &Path, legacy: bool) -> PathBuf {
        let directory = self.output.join(label);
        let script = self.research.join(if legacy { "legacy_bridge.py" } else { "native_bridge.py" });
        let started = Instant::now();
        let mut command = Command::new(&self.python);
        command.arg(&script).arg("--owner-snapshot").arg(snapshot).arg("--encoder-dir").arg(&self.encoder).arg("--output").arg(&directory)
            .env("OPENBLAS_NUM_THREADS", "1").env("OMP_NUM_THREADS", "1").env("MKL_NUM_THREADS", "1")
            .stdout(Stdio::from(std::fs::File::create_new(self.output.join(format!("{label}.stdout"))).expect("raw stdout")))
            .stderr(Stdio::from(std::fs::File::create_new(self.output.join(format!("{label}.stderr"))).expect("raw stderr")))
            .kill_on_drop(true);
        if legacy { command.arg("--legacy-root").arg(&self.legacy); }
        let mut child = command.spawn().expect("external bridge process");
        let pid = child.id().expect("bridge PID");
        let status = tokio::time::timeout(Duration::from_secs(300), child.wait()).await.expect("bounded bridge deadline").expect("bridge exit");
        save(&self.output.join(format!("{label}-process.json")), &json!({"pid":pid,"parent_pid":std::process::id(),"script":script,
            "script_sha256":Digest32::of_bytes(&std::fs::read(&script).expect("script bytes")).to_string(),"exit_status":status.to_string(),
            "wall_seconds":started.elapsed().as_secs_f64(),"reaped_before_native_read":true}));
        assert!(status.success(), "bridge failed; raw logs are preserved");
        directory
    }
}

pub(super) fn initial_records(legacy: &Path) -> Vec<MemoryInventoryRecordV1> {
    let sources: Vec<Value> = serde_json::from_slice(&std::fs::read(legacy.join("sources.json")).expect("original authored sources")).expect("authored sources JSON");
    assert_eq!(sources.len(), 16);
    let mut records = Vec::new();
    for row in sources {
        let index = row["index"].as_u64().expect("source index");
        let semantic = row["kind"] == "semantic";
        assert!(semantic || row["kind"] == "skill");
        let kind = if semantic { MemoryInventoryKindV1::Semantic } else { MemoryInventoryKindV1::Procedure };
        let value = if semantic { json!({"reserve":row["value"][0],"pack":row["value"][1],"limit":row["value"][2]}) }
            else { json!({"opcodes":row["value"]}) };
        records.push(record(kind, index, value));
        if semantic {
            records.push(record(MemoryInventoryKindV1::Event, index, json!(4 + index)));
            records.push(record(MemoryInventoryKindV1::Hold, index, json!(false)));
        }
    }
    records
}

pub(super) fn record(kind: MemoryInventoryKindV1, index: u64, value: Value) -> MemoryInventoryRecordV1 {
    let family = if kind == MemoryInventoryKindV1::Procedure { "procedure" } else { "semantic" };
    MemoryInventoryRecordV1 { schema:"hepta.memory.inventory-record.v1".into(), key:ContractIdV1::new(format!("inventory:{family}:{index}")).expect("source key"), kind, effective_at:20, value }
}

pub(super) fn query(scope: &ContractIdV1, operation: &str, entity: u64, workflow: u64) -> MemoryInventoryRequestV1 {
    MemoryInventoryRequestV1 {
        schema:"hepta.memory.inventory-request.v1".into(), query_id:ContractIdV1::new(format!("native-{operation}-{entity}-{workflow}").replace(':', "-")).expect("query ID"),
        scope:scope.clone(), entity_key:ContractIdV1::new(format!("inventory:semantic:{entity}")).expect("entity"),
        workflow_key:ContractIdV1::new(format!("inventory:procedure:{workflow}")).expect("workflow"),
        text:operation.into(), at:20, since:20, max_hops:3, max_cells:4, max_steps:4,
    }
}

pub(super) async fn export(client: &AgentdClient, path: &Path) -> Vec<MemoryInventorySnapshotPageV1> {
    let mut pages = Vec::new();
    let mut after = None;
    let mut cut = None;
    loop {
        let page = client.memory_inventory_snapshot(after, cut, 16).await.expect("actual owner snapshot page");
        if let Some(expected) = cut { assert_eq!(page.owner_cut_digest, expected); }
        cut = Some(page.owner_cut_digest);
        after = page.next_after;
        pages.push(page);
        if after.is_none() { break; }
    }
    save(path, &json!(pages));
    pages
}

pub(super) async fn install(node: &mut NativeOwner, models: &Path, code: &Path) -> Value {
    node.command(json!({"op":"install","semantic":models.join("semantic.json"),"procedure":models.join("procedure.json"),
        "code":Digest32::of_bytes(&std::fs::read(code).expect("release producer code")).to_string()})).await
}

pub(super) async fn check_written_values(client: &AgentdClient, pages: &[MemoryInventorySnapshotPageV1]) -> Vec<MemoryInventoryReadoutV1> {
    let scope = &pages[0].scope;
    let mut reads = Vec::new();
    for row in pages.iter().flat_map(|page| &page.records).filter(|row| matches!(row.record.kind, MemoryInventoryKindV1::Semantic | MemoryInventoryKindV1::Procedure)) {
        let operation = if row.record.kind == MemoryInventoryKindV1::Semantic { "semantic" } else { "procedure" };
        let mut request = query(scope, operation, 0, 0);
        if operation == "semantic" { request.entity_key = row.record.key.clone(); } else { request.workflow_key = row.record.key.clone(); }
        let read = client.memory_inventory_read(request).await.expect("native parameter read");
        assert_eq!(read.status, MemoryReadStatusV1::Ok);
        assert_eq!(read.value, row.record.value);
        assert_eq!(read.source_ids, vec![row.source_id]);
        assert_eq!(read.cell_digests.len(), 1);
        reads.push(read);
    }
    reads
}

pub(super) async fn check_composition(client: &AgentdClient, pages: &[MemoryInventorySnapshotPageV1], entity: u64, workflow: u64) -> MemoryInventoryReadoutV1 {
    let request = query(&pages[0].scope, "apply", entity, workflow);
    let rows = pages.iter().flat_map(|page| &page.records).collect::<Vec<_>>();
    let find = |key: &ContractIdV1, kind| rows.iter().find(|row| row.record.key == *key && row.record.kind == kind).expect("exact owner dependency");
    let semantic = find(&request.entity_key, MemoryInventoryKindV1::Semantic);
    let procedure = find(&request.workflow_key, MemoryInventoryKindV1::Procedure);
    let event = find(&request.entity_key, MemoryInventoryKindV1::Event);
    let hold = find(&request.entity_key, MemoryInventoryKindV1::Hold);
    let policy: MemoryInventoryPolicyV1 = serde_json::from_value(semantic.record.value.clone()).expect("gold policy for scoring only");
    let program: MemoryInventoryProgramV1 = serde_json::from_value(procedure.record.value.clone()).expect("gold program for scoring only");
    let expected = execute_memory_inventory_program_v1(&program, event.record.value.as_i64().expect("event"), &policy, 4).expect("expected execution");
    let mut sources = vec![semantic.source_id, procedure.source_id, event.source_id, hold.source_id];
    sources.sort();
    let read = client.memory_inventory_read(request).await.expect("native composed read");
    assert_eq!(read.status, MemoryReadStatusV1::Ok);
    assert_eq!(read.value, serde_json::to_value(expected).expect("expected JSON"));
    assert_eq!(read.source_ids, sources);
    assert_eq!(read.cell_digests.len(), 2);
    read
}

pub(super) fn empty_failure(read: &MemoryInventoryReadoutV1, status: MemoryReadStatusV1) {
    assert_eq!(read.status, status);
    assert!(read.value.is_null() && read.source_ids.is_empty() && read.cell_digests.is_empty());
}

pub(super) fn save(path: &Path, value: &Value) {
    std::fs::write(path, serde_json::to_vec_pretty(value).expect("evidence JSON")).expect("retained evidence");
}
