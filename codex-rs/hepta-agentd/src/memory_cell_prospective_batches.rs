//! New composite decisions use native typed readouts after candidate fitting.
//! Request families are fixed by this source before a trial starts; the
//! partition worker receives only completed prefix observations, not futures.

use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_cognitive_types::MemoryReadStatusV1;
use codex_hepta_cognitive_types::execute_memory_cell_program_v1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_types::Digest32;
use serde_json::Value;
use serde_json::json;
use std::time::Instant;

use crate::memory_cell_runtime_tests::TestRoute;
use crate::memory_cell_runtime_tests::TrustedTestResolver;
use crate::memory_cell_test_support::ControlFixture;
use crate::memory_cell_test_support::request;
use crate::memory_cell_training_test_support::Expected;
use super::direct::DirectOwner;

pub(super) enum Reader<'a> { Native(&'a TrustedTestResolver), Direct(&'a DirectOwner) }

pub(super) async fn batches(fixture: &ControlFixture, reader: &Reader<'_>, values: &[Expected], phase: &str) -> Value {
    let snapshot = fixture.snapshot().await;
    let groups = if phase == "prefix" { 16 } else if phase == "future" { 12 } else { 4 };
    let traffic = fixture.client.traffic_snapshot();
    let started = Instant::now();
    let mut records = Vec::new();
    let mut correct = 0_usize;
    let mut decisions_correct = 0_usize;
    for group in 0..groups {
        let family = group / 4;
        let domain = group % 4;
        let indices: Vec<_> = (0..6).map(|offset| {
            if phase == "future" && family == 1 {
                ((domain + usize::from(offset >= 3)) % 4) * 6 + offset
            } else if phase == "future" && family == 2 {
                ((domain + offset) % 4) * 6 + offset
            } else { domain * 6 + if phase == "future" { 5 - offset } else { offset } }
        }).collect();
        let mut queries = Vec::new();
        let mut readouts = Vec::new();
        let mut expected_values = Vec::new();
        let mut actual_total = Some(0_i64);
        let mut expected_total = 0_i64;
        for (offset, index) in indices.iter().enumerate() {
            let item = &values[*index];
            let operation = if phase == "prefix" { MemoryOperationV1::Current }
                else { [MemoryOperationV1::Apply, MemoryOperationV1::Semantic, MemoryOperationV1::Procedure][offset % 3] };
            let mut query = request(snapshot.scope().clone());
            query.query_id = ContractIdV1::new(format!("query:prospective:{phase}:{group}:{offset}")).unwrap();
            query.entity = item.entity.clone();
            let (status, value, readout) = match reader {
                Reader::Native(resolver) => {
                    resolver.set(TestRoute::Read(operation));
                    let result = fixture.client.memory_cell_read(query.clone()).await.unwrap();
                    (result.status, result.value.clone(), serde_json::to_value(result).unwrap())
                }
                Reader::Direct(owner) => owner.read(fixture, &query, operation).await,
            };
            let expected = match operation {
                MemoryOperationV1::Current => json!(item.event),
                MemoryOperationV1::Semantic => item.semantic.clone(),
                MemoryOperationV1::Procedure => item.procedure.clone(),
                MemoryOperationV1::Apply => json!(execute_memory_cell_program_v1(&item.procedure, item.event, &item.semantic).unwrap()),
                MemoryOperationV1::History | MemoryOperationV1::Change => unreachable!("declared prospective operations"),
            };
            let number = |value: &Value| match operation {
                MemoryOperationV1::Semantic => value["factor"].as_i64(),
                MemoryOperationV1::Procedure => value["bias"].as_i64(),
                MemoryOperationV1::Current | MemoryOperationV1::Apply => value.as_i64(),
                MemoryOperationV1::History | MemoryOperationV1::Change => unreachable!("declared prospective operations"),
            };
            correct += usize::from(status == MemoryReadStatusV1::Ok && value == expected);
            let sign = if offset % 2 == 0 { 1 } else { -1 };
            expected_total += sign * number(&expected).unwrap();
            actual_total = actual_total.and_then(|total| (status == MemoryReadStatusV1::Ok)
                .then(|| number(&value)).flatten().map(|value| total + sign * value));
            queries.push(query);
            readouts.push(readout);
            expected_values.push(expected);
        }
        let threshold = (group as i64 % 5 - 2) * 1200;
        let expected_action = expected_total > threshold;
        let action = actual_total.map(|total| total > threshold);
        decisions_correct += usize::from(action == Some(expected_action));
        let mut addresses: Vec<_> = queries.iter().map(|query| Digest32::of_bytes(query.entity.as_str().as_bytes()).to_string()).collect();
        addresses.sort(); addresses.dedup();
        let request_bytes = serde_json::to_vec(&queries).unwrap();
        let readout_bytes = serde_json::to_vec(&readouts).unwrap();
        records.push(json!({"task_id":format!("task:{phase}:{group}"),"family":family,
            "sequence":group+1,"addresses":addresses,
            "request_digest":Digest32::of_bytes(&request_bytes).to_string(),
            "readout_digest":Digest32::of_bytes(&readout_bytes).to_string(),
            "request_bytes":String::from_utf8(request_bytes).unwrap(),"readout_bytes":String::from_utf8(readout_bytes).unwrap(),
            "queries":queries,"readouts":readouts,"expected_values":expected_values,
            "threshold":threshold,"action":action,"expected_action":expected_action,
            "decision_correct":action == Some(expected_action)}));
    }
    let after = fixture.client.traffic_snapshot();
    json!({"phase":phase,"queries":groups*6,"correct":correct,"tasks":groups,"decisions_correct":decisions_correct,
        "socket_and_native_wall_ns":started.elapsed().as_nanos(),"records":records,
        "traffic":{"rpc_attempts":after.rpc_attempts-traffic.rpc_attempts,
            "transmitted_bytes":after.transmitted_bytes-traffic.transmitted_bytes,
            "received_bytes":after.received_bytes-traffic.received_bytes},
        "exclusive_communication_wall_ns":null,"source_cut":snapshot.owner_cut_digest()})
}

pub(super) fn routing_trace(source_cut: Digest32, prefix: &Value) -> Value {
    let records = prefix["records"].as_array().unwrap();
    let end = records.last().unwrap()["sequence"].as_u64().unwrap();
    let mut bytes = b"hepta.memory.causal-coaccess-trace.v1\0".to_vec();
    bytes.extend_from_slice(source_cut.as_array());
    bytes.extend_from_slice(&end.to_be_bytes());
    bytes.extend_from_slice(&(records.len() as u64).to_be_bytes());
    let observations: Vec<_> = records.iter().map(|record| {
        bytes.extend_from_slice(&record["sequence"].as_u64().unwrap().to_be_bytes());
        for name in ["request_digest", "readout_digest"] {
            bytes.extend_from_slice(record[name].as_str().unwrap().parse::<Digest32>().unwrap().as_array());
        }
        let addresses = record["addresses"].as_array().unwrap();
        bytes.extend_from_slice(&(addresses.len() as u64).to_be_bytes());
        for address in addresses { bytes.extend_from_slice(address.as_str().unwrap().parse::<Digest32>().unwrap().as_array()); }
        json!({"sequence":record["sequence"],"request_digest":record["request_digest"],
            "readout_digest":record["readout_digest"],"addresses":record["addresses"]})
    }).collect();
    json!({"schema":"hepta.memory.causal-coaccess-trace.v1","source_cut_digest":source_cut.to_string(),
        "prefix_end_sequence":end,"observations":observations,"trace_digest":Digest32::of_bytes(&bytes).to_string()})
}
