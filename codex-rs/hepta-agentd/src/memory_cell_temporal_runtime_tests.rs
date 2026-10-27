//! Runs at the end of the real frozen-worker language integration. These new
//! date cases test the host transport profile, not the classifier held split.

use super::*;
use crate::MEMORY_CELL_TIME_VIEW_PROFILE_V1;
use crate::memory_cell_training_test_support::publish;

pub(super) async fn real_dates(fixture: &ControlFixture, release: &ReleaseFixture, entity: &ContractIdV1) -> Value {
    const MIDNIGHT: u64 = 1_738_368_000; // 2025-02-01T00:00:00Z
    const CALENDAR_INTEGER: u64 = 20_250_201; // This epoch is in 1970, deliberately a trap.
    for (effective_at, value) in [(CALENDAR_INTEGER, 555), (MIDNIGHT - 86_400, 21),
        (MIDNIGHT, 37), (MIDNIGHT + 1, 39), (MIDNIGHT + 86_400, 53)] {
        let row = MemoryCellRecordV1 { schema: "hepta.memory.cell-record.v1".to_string(),
            entity: entity.clone(), kind: MemoryCellKindV1::Event, effective_at, value: json!(value) };
        fixture.store.write_memory_cell(&fixture.access(), &CognitiveScope::AgentPrivate, &row,
            MemoryCellWriteModeV1::Create).await.expect("real epoch event source");
    }
    let fitted = fit(&trainer(), fixture, /*generation*/ 2, MemoryCellTrainingModeV1::Clean).await;
    publish(release, &fitted, /*generation*/ 2);
    let snapshot = fitted.snapshot();
    let historical = snapshot.at(entity, MemoryCellKindV1::Event, MIDNIGHT).expect("midnight source");
    let trap = snapshot.at(entity, MemoryCellKindV1::Event, CALENDAR_INTEGER).expect("1970 trap source");
    assert_eq!((historical.record.value.clone(), trap.record.value.clone()), (json!(37), json!(555)));
    let history_text = "Read Orion's observation on or before the provided 2025-02-01.";
    let change_text = "Read Orion's current and earlier values, then return current minus earlier since 2025-02-01.";
    let mut readbacks = Vec::new();
    for (index, (operation, text, at, since, value)) in [
        (MemoryOperationV1::History, history_text, MIDNIGHT, 0, 37),
        (MemoryOperationV1::Change, change_text, MIDNIGHT + 86_400, MIDNIGHT, 16),
    ].into_iter().enumerate() {
        let mut query = request(snapshot.scope().clone());
        query.query_id = ContractIdV1::new(format!("query:real-utc-date-{index}")).unwrap();
        query.entity = entity.clone(); query.text = text.to_string(); query.at = at; query.since = since;
        let readout = fixture.client.memory_cell_read(query.clone()).await.expect("real date worker control read");
        assert_eq!((readout.status, readout.operation, readout.value.clone()), (MemoryReadStatusV1::Ok, Some(operation), json!(value)));
        let mut expected = BTreeSet::from([historical.source_id]);
        if operation == MemoryOperationV1::Change {
            expected.insert(snapshot.current(entity, MemoryCellKindV1::Event).unwrap().source_id);
        }
        assert_eq!(readout.source_ids.iter().copied().collect::<BTreeSet<_>>(), expected);
        assert!(!readout.source_ids.contains(&trap.source_id));
        readbacks.push(json!({"request":query,"readout":readout}));
    }
    for (index, (at, since, text, reason)) in [
        (CALENDAR_INTEGER, 0, history_text, "YYYYMMDD supplied as epoch must not read the 1970 trap"),
        (MIDNIGHT + 86_400, 0, history_text, "native cutoff and literal day conflict"),
        (MIDNIGHT + 1, 0, history_text, "history cutoff is not exactly UTC midnight"),
        (MIDNIGHT + 86_400, MIDNIGHT + 1, change_text, "change cutoff is not exactly UTC midnight"),
    ].into_iter().enumerate() {
        let mut query = request(snapshot.scope().clone());
        query.query_id = ContractIdV1::new(format!("query:real-utc-reject-{index}")).unwrap();
        query.entity = entity.clone(); query.text = text.to_string(); query.at = at; query.since = since;
        let readout = fixture.client.memory_cell_read(query.clone()).await.expect("bound real-worker temporal rejection");
        assert_eq!((readout.status, readout.value.clone(), readout.source_ids.clone(), readout.cell_digests.clone()),
            (MemoryReadStatusV1::Abstain, Value::Null, vec![], vec![]), "{reason}");
        readbacks.push(json!({"request":query,"readout":readout,"boundary":reason}));
    }
    json!({"profile":MEMORY_CELL_TIME_VIEW_PROFILE_V1, "canonical_unit":"unix_seconds",
        "literal_date_semantics":"UTC midnight only", "native_midnight":MIDNIGHT,
        "private_worker_date_slot":CALENDAR_INTEGER, "trap_source":trap.source_id,
        "new_host_transport_outside_frozen_classifier":true, "classifier_held_results_cover_this_adapter":false,
        "frozen_python_or_model_modified":false, "held_reads":0,
        "training_code_digest":fitted.training_code_digest().to_string(), "owner_cut_digest":snapshot.owner_cut_digest(),
        "readbacks":readbacks})
}
