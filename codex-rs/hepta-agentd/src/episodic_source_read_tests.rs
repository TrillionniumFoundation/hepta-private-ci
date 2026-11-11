//! Publication-order tests only; these fixture receipts grant no writer/source authority.

use std::collections::BTreeMap;
use std::sync::Arc;

use codex_hepta_memory::EpisodicImportReceipt;
use codex_hepta_memory::EpisodicSnapshotAdmission;
use pretty_assertions::assert_eq;

use super::EpisodicSourceReads;

fn receipt(generation: u64) -> EpisodicImportReceipt {
    EpisodicImportReceipt {
        schema_version: 1,
        owner_agent_id: "publication-fixture".into(),
        scope_binding: "fixture-private-scope".into(),
        authority_id: "fixture-original-source".into(),
        namespace: "fixture-namespace".into(),
        generation,
        snapshot_sha256: format!("fixture-snapshot-{generation}"),
        admission_sha256: "fixture-empty-admission".into(),
        lease_id: "fixture-original-writer".into(),
        writer_generation: 1,
        bindings: Vec::new(),
    }
}

#[test]
fn episodic_source_observation_follows_commit_generation_not_ack_order() {
    let state = EpisodicSourceReads::default();
    let admission = EpisodicSnapshotAdmission { records: BTreeMap::new(), withdrawal: None };
    let first = receipt(/*generation*/ 1);
    state.publish("first".into(), admission.clone(), first.clone()).unwrap();
    let first_read = state.current.lock().unwrap().clone().unwrap();
    state.publish("first".into(), admission.clone(), first.clone()).unwrap();
    assert!(Arc::ptr_eq(&first_read, state.current.lock().unwrap().as_ref().unwrap()));

    let second = receipt(/*generation*/ 2);
    state.publish("second".into(), admission.clone(), second.clone()).unwrap();
    let current = state.current.lock().unwrap().clone().unwrap();
    assert!(!Arc::ptr_eq(&first_read, &current));
    // Releasing an older post-commit completion last must not replace the cut
    // now used by new readers. A same-generation conflict is also refused.
    state.publish("first".into(), admission.clone(), first).unwrap();
    assert!(Arc::ptr_eq(&current, state.current.lock().unwrap().as_ref().unwrap()));
    let mut conflict = second.clone();
    conflict.writer_generation += 1;
    assert!(state.publish("second".into(), admission.clone(), conflict).is_err());
    assert_eq!(&state.current.lock().unwrap().as_ref().unwrap().receipt, &second);
    state.publish("second".into(), admission, second).unwrap();
    assert!(Arc::ptr_eq(&current, state.current.lock().unwrap().as_ref().unwrap()));
}
