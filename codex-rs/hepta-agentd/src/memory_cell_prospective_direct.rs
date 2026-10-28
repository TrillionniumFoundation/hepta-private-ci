//! Strong exact-owner baseline: cache actual paginated control results, then
//! revalidate the complete cut through the same live socket before and after
//! each use. No expected answer, fitted model or artifact selection is used.

use std::collections::BTreeMap;
use std::time::Instant;

use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_cognitive_types::MemoryReadStatusV1;
use codex_hepta_cognitive_types::MemoryRequestV1;
use codex_hepta_cognitive_types::execute_memory_cell_program_v1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

use crate::memory_cell_test_support::ControlFixture;

pub(super) struct DirectOwner {
    cut: ContractDigestV1,
    scope: ContractIdV1,
    cells: BTreeMap<String, BTreeMap<MemoryCellKindV1, (ContractDigestV1, Value)>>,
    pub logical_cache_bytes: usize,
}

impl DirectOwner {
    pub async fn acquire(fixture: &ControlFixture, budget: u64) -> (Self, Value) {
        let started = Instant::now();
        let mut after = None;
        let mut cut = None;
        let mut scope = None;
        let mut cells = BTreeMap::<String, BTreeMap<_, _>>::new();
        let mut pages = Vec::new();
        loop {
            let page = fixture.client.memory_cell_snapshot(after, cut, codex_hepta_agent_protocol::MAX_MEMORY_CELL_PAGE_ROWS).await.unwrap();
            if let Some(expected) = &scope { assert_eq!(expected, &page.scope); }
            scope = Some(page.scope.clone()); cut = Some(page.owner_cut_digest);
            for row in &page.records {
                assert!(cells.entry(row.record.entity.as_str().to_string()).or_default()
                    .insert(row.record.kind, (row.source_id, row.record.value.clone())).is_none());
            }
            after = page.next_after;
            pages.push(page);
            if after.is_none() { break; }
            assert!(pages.len() <= 512, "bounded complete owner export");
        }
        fixture.client.memory_cell_snapshot(/*after*/ None, cut, /*limit*/ 1).await.unwrap();
        let logical_cache_bytes = serde_json::to_vec(&cells).unwrap().len();
        assert!(logical_cache_bytes as u64 <= budget, "exact-owner cache shares the frozen logical payload budget");
        let receipt = json!({"schema":"hepta.memory.direct-owner-acquisition.v1","pages":pages,
            "logical_cache_bytes":logical_cache_bytes,"logical_cache_budget_bytes":budget,
            "acquisition_wall_ns":started.elapsed().as_nanos(),"trained_models":0});
        (Self { cut: cut.unwrap(), scope: scope.unwrap(), cells, logical_cache_bytes }, receipt)
    }

    pub async fn read(&self, fixture: &ControlFixture, request: &MemoryRequestV1, operation: MemoryOperationV1) -> (MemoryReadStatusV1, Value, Value) {
        request.validate().unwrap(); assert_eq!(request.scope, self.scope);
        fixture.client.memory_cell_snapshot(/*after*/ None, Some(self.cut), /*limit*/ 1).await.unwrap();
        let cells = self.cells.get(request.entity.as_str()).unwrap();
        let kinds = match operation {
            MemoryOperationV1::Current => vec![MemoryCellKindV1::Event],
            MemoryOperationV1::Semantic => vec![MemoryCellKindV1::Semantic],
            MemoryOperationV1::Procedure => vec![MemoryCellKindV1::Procedure],
            MemoryOperationV1::Apply => vec![MemoryCellKindV1::Event, MemoryCellKindV1::Semantic, MemoryCellKindV1::Procedure],
            MemoryOperationV1::History | MemoryOperationV1::Change => unreachable!("prospective protocol has no historical lookup"),
        };
        assert!(kinds.len() <= usize::from(request.max_cells) && kinds.len() <= usize::from(request.max_hops));
        let value = if operation == MemoryOperationV1::Apply {
            json!(execute_memory_cell_program_v1(&cells[&MemoryCellKindV1::Procedure].1,
                cells[&MemoryCellKindV1::Event].1.as_i64().unwrap(), &cells[&MemoryCellKindV1::Semantic].1).unwrap())
        } else { cells[&kinds[0]].1.clone() };
        let sources: Vec<_> = kinds.iter().map(|kind| cells[kind].0).collect();
        fixture.client.memory_cell_snapshot(/*after*/ None, Some(self.cut), /*limit*/ 1).await.unwrap();
        let raw = json!({"schema":"hepta.memory.direct-owner-read.v1","query_id":request.query_id,
            "operation":operation,"status":"ok","scope":self.scope,"owner_cut":self.cut,"value":value,"source_ids":sources,
            "before_and_after_cut_verified":true,"prediction_kind":"source_evidence","model_storage_bytes":0});
        (MemoryReadStatusV1::Ok, value, raw)
    }
}
