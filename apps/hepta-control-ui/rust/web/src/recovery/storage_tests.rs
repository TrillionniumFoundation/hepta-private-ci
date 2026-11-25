use super::*;
use std::cell::RefCell;

#[derive(Default)]
struct Memory {
    values: RefCell<BTreeMap<String, String>>,
    enumerations: Cell<u32>,
    directory_writes: Cell<u32>,
    fail_directory_write: Cell<u32>,
    fail_after_directory_write: Cell<bool>,
    fail_record_write: Cell<bool>,
    ignore_removal: Cell<bool>,
}
impl StorageIo for Memory {
    fn get(&self, key: &str, _: &'static str) -> Result<Option<String>, ControlError> {
        Ok(self.values.borrow().get(key).cloned())
    }
    fn set(&self, key: &str, value: &str, reason: &'static str) -> Result<(), ControlError> {
        if key.starts_with(SCHEMA) && self.fail_record_write.get() {
            return Err(failure(reason));
        }
        let mut fail = false;
        if key.starts_with(DIRECTORY_SCHEMA) {
            self.directory_writes.set(self.directory_writes.get() + 1);
            fail = self.directory_writes.get() == self.fail_directory_write.get();
        }
        if fail && !self.fail_after_directory_write.get() {
            return Err(failure(reason));
        }
        self.values.borrow_mut().insert(key.into(), value.into());
        if fail {
            return Err(failure(reason));
        }
        Ok(())
    }
    fn remove(&self, key: &str, _: &'static str) -> Result<(), ControlError> {
        if !self.ignore_removal.get() {
            self.values.borrow_mut().remove(key);
        }
        Ok(())
    }
    fn len(&self) -> Result<u32, ControlError> {
        Ok(self.values.borrow().len() as u32)
    }
    fn key(&self, index: u32) -> Result<Option<String>, ControlError> {
        self.enumerations.set(self.enumerations.get() + 1);
        Ok(self.values.borrow().keys().nth(index as usize).cloned())
    }
}
fn fixture(max_entries: usize) -> (Rc<Memory>, Engine) {
    let storage = Rc::new(Memory::default());
    let engine = Engine::new(storage.clone(), "a".repeat(64), max_entries).unwrap();
    engine.initialize_locked().unwrap();
    (storage, engine)
}
fn operation(id: &str) -> Value {
    json!({"operationId":id,"protocolVersion":"hepta.ui-control.v1","method":"runtime/stop",
        "semanticDigest":"a".repeat(64),"action":"request_stop","targetId":"runtime.agentd",
        "reason":"Maintenance","sessionId":"session-1","connectionGeneration":1,
        "generation":7,"displayedRevision":12,"snapshotDigest":"b".repeat(64),
        "state":"submitting","createdAt":1,"updatedAt":1,"auditTraceId":null})
}
fn terminal(id: &str) -> Value {
    let mut operation = operation(id);
    operation["state"] = json!("terminal");
    operation
}
fn reopen(storage: Rc<Memory>, capacity: usize) -> Result<Engine, ControlError> {
    let engine = Engine::new(storage, "a".repeat(64), capacity)?;
    if engine.needs_initialization()? {
        engine.initialize_locked()?;
    }
    Ok(engine)
}
fn reason(error: ControlError) -> Value {
    error.details["storageReason"].clone()
}

#[test]
fn initializes_exact_schema_and_indexes_durable_operation() {
    let (_, engine) = fixture(1024);
    assert_eq!(
        engine.diagnostics().unwrap(),
        json!({"schema":DIRECTORY_SCHEMA,"entries":0,"maxEntries":1024,
        "states":{"ready":0,"reserving":0,"removing":0},"migrationScans":1,"migrationKeys":0})
    );
    engine.prepare_locked(&operation("op-1")).unwrap();
    assert_eq!(
        engine.load().unwrap(),
        json!({"schema":LEGACY_SCHEMA,"operations":[operation("op-1")]})
    );
}

#[test]
fn duplicate_identity_is_ambiguous_and_cannot_overwrite_record() {
    let (storage, engine) = fixture(1024);
    engine.prepare_locked(&operation("op-1")).unwrap();
    let saved = storage.values.borrow().clone();
    let error = engine.prepare_locked(&operation("op-1")).err().unwrap();
    assert_eq!(
        (error.code, error.request_dispatched),
        (ErrorCode::AmbiguousSubmission, Some(true))
    );
    let mut changed = operation("op-1");
    changed["reason"] = json!("Changed");
    assert_eq!(
        engine.prepare_locked(&changed).err().unwrap().code,
        ErrorCode::OperationConflict
    );
    assert_eq!(*storage.values.borrow(), saved);
}

#[test]
fn independent_tabs_preserve_each_others_ids_and_capacity() {
    let (storage, one) = fixture(2);
    let two = reopen(storage, 2).unwrap();
    one.prepare_locked(&operation("one")).unwrap();
    two.prepare_locked(&operation("two")).unwrap();
    assert_eq!(
        reason(one.prepare_locked(&operation("three")).err().unwrap()),
        json!("capacity_exhausted")
    );
    assert!(one.complete_locked(&terminal("one")).unwrap());
    assert_eq!(
        two.load().unwrap(),
        json!({"schema":LEGACY_SCHEMA,"operations":[operation("two")]})
    );
}

#[test]
fn missing_ready_record_fails_closed_without_losing_identity() {
    let (storage, engine) = fixture(10);
    engine.prepare_locked(&operation("op")).unwrap();
    storage
        .values
        .borrow_mut()
        .remove(&engine.record_key("op").unwrap());
    assert_eq!(
        reason(engine.load().unwrap_err()),
        json!("directory_record_missing")
    );
    assert_eq!(
        reason(reopen(storage, 10).unwrap().load().unwrap_err()),
        json!("directory_record_missing")
    );
    assert_eq!(
        engine.read_directory().unwrap(),
        BTreeMap::from([("op".into(), Entry::Ready)])
    );
}

#[test]
fn failed_record_write_repairs_unadmitted_reservation() {
    let (storage, engine) = fixture(10);
    storage.fail_record_write.set(true);
    assert_eq!(
        reason(engine.prepare_locked(&operation("op")).err().unwrap()),
        json!("record_write_failed")
    );
    storage.fail_record_write.set(false);
    assert_eq!(
        reopen(storage, 10).unwrap().load().unwrap(),
        json!({"schema":LEGACY_SCHEMA,"operations":[]})
    );
}

#[test]
fn failed_ready_write_removes_only_undispatched_reservation_on_reopen() {
    let (storage, engine) = fixture(10);
    storage.fail_directory_write.set(3);
    assert!(engine.prepare_locked(&operation("op")).is_err());
    assert!(
        storage
            .values
            .borrow()
            .contains_key(&engine.record_key("op").unwrap())
    );
    let reopened = reopen(storage.clone(), 10).unwrap();
    assert_eq!(reopened.read_directory().unwrap(), BTreeMap::new());
    assert!(
        !storage
            .values
            .borrow()
            .contains_key(&engine.record_key("op").unwrap())
    );
}

#[test]
fn ready_written_before_error_remains_conservatively_recoverable() {
    let (storage, engine) = fixture(10);
    storage.fail_directory_write.set(3);
    storage.fail_after_directory_write.set(true);
    assert!(engine.prepare_locked(&operation("op")).is_err());
    assert_eq!(
        reopen(storage, 10).unwrap().load().unwrap(),
        json!({"schema":LEGACY_SCHEMA,"operations":[operation("op")]})
    );
}

#[test]
fn failed_removal_restores_ready_and_retains_record() {
    let (storage, engine) = fixture(10);
    engine.prepare_locked(&operation("op")).unwrap();
    storage.ignore_removal.set(true);
    assert_eq!(
        reason(engine.complete_locked(&terminal("op")).unwrap_err()),
        json!("record_remove_readback_failed")
    );
    storage.ignore_removal.set(false);
    let reopened = reopen(storage, 10).unwrap();
    assert_eq!(
        reopened.load().unwrap(),
        json!({"schema":LEGACY_SCHEMA,"operations":[operation("op")]})
    );
    assert!(reopened.complete_locked(&terminal("op")).unwrap());
}

#[test]
fn interrupted_transition_with_changed_identity_never_clears_record() {
    let (storage, engine) = fixture(10);
    engine.prepare_locked(&operation("op")).unwrap();
    let mut identity = identity(&operation("op"));
    identity[3] = json!("d".repeat(64));
    for state in [
        Entry::Reserving(identity.clone()),
        Entry::Removing(identity.clone()),
    ] {
        engine
            .write_directory(&BTreeMap::from([("op".into(), state)]))
            .unwrap();
        let saved = storage.values.borrow().clone();
        assert_eq!(
            reason(reopen(storage.clone(), 10).err().unwrap()),
            json!("directory_identity_mismatch")
        );
        assert_eq!(*storage.values.borrow(), saved);
    }
}

#[test]
fn nonterminal_or_identity_mismatched_completion_retains_record() {
    let (storage, engine) = fixture(10);
    engine.prepare_locked(&operation("op")).unwrap();
    let saved = storage.values.borrow().clone();
    assert!(!engine.complete_locked(&operation("op")).unwrap());
    let mut changed = terminal("op");
    changed["semanticDigest"] = json!("c".repeat(64));
    assert_eq!(
        reason(engine.complete_locked(&changed).unwrap_err()),
        json!("terminal_identity_mismatch")
    );
    assert_eq!(*storage.values.borrow(), saved);
}

#[test]
fn rejection_receipt_only_removes_exact_record() {
    let (storage, engine) = fixture(10);
    let receipt = engine.prepare_locked(&operation("op")).unwrap();
    let key = engine.record_key("op").unwrap();
    let original = storage.values.borrow()[&key].clone();
    storage
        .values
        .borrow_mut()
        .insert(key.clone(), original.replace("Maintenance", "Changed"));
    assert!(!engine.discard_locked(&receipt).unwrap());
    storage.values.borrow_mut().insert(key, original);
    assert!(engine.discard_locked(&receipt).unwrap());
    assert_eq!(
        engine.load().unwrap(),
        json!({"schema":LEGACY_SCHEMA,"operations":[]})
    );
}

#[test]
fn unindexed_existing_record_stays_ambiguous_when_repair_fails() {
    let (storage, engine) = fixture(10);
    engine.prepare_locked(&operation("op")).unwrap();
    engine.write_directory(&Entries::new()).unwrap();
    storage
        .fail_directory_write
        .set(storage.directory_writes.get() + 1);
    let error = engine.prepare_locked(&operation("op")).err().unwrap();
    assert_eq!(
        (
            error.code,
            error.request_dispatched,
            error.details["storageReason"].clone()
        ),
        (
            ErrorCode::AmbiguousSubmission,
            Some(true),
            json!("directory_write_failed")
        )
    );
    assert!(
        storage
            .values
            .borrow()
            .contains_key(&engine.record_key("op").unwrap())
    );
}

#[test]
fn unindexed_terminal_record_can_be_removed_at_capacity() {
    let (storage, engine) = fixture(1);
    engine.prepare_locked(&operation("indexed")).unwrap();
    let key = engine.record_key("legacy").unwrap();
    storage.values.borrow_mut().insert(
        key.clone(),
        json!({"schema":SCHEMA,"scopeDigest":"a".repeat(64),"operation":operation("legacy")})
            .to_string(),
    );
    assert!(engine.complete_locked(&terminal("legacy")).unwrap());
    assert!(!storage.values.borrow().contains_key(&key));
    assert_eq!(
        engine.load().unwrap(),
        json!({"schema":LEGACY_SCHEMA,"operations":[operation("indexed")]})
    );
}

#[test]
fn corrupt_data_and_scope_mismatches_are_retained() {
    let (storage, engine) = fixture(10);
    engine.prepare_locked(&operation("op")).unwrap();
    let key = engine.record_key("op").unwrap();
    for raw in [
        "broken".into(),
        json!({"schema":SCHEMA,"scopeDigest":"b".repeat(64),"operation":operation("op")})
            .to_string(),
        "x".repeat(MAX_RECORD_BYTES + 1),
    ] {
        storage.values.borrow_mut().insert(key.clone(), raw.clone());
        assert!(engine.load().is_err());
        assert_eq!(storage.values.borrow()[&key], raw);
    }
    storage
        .values
        .borrow_mut()
        .insert(engine.directory_key.clone(), "broken".into());
    assert_eq!(
        reason(reopen(storage.clone(), 10).err().unwrap()),
        json!("directory_corrupt")
    );
    assert_eq!(storage.values.borrow()[&engine.directory_key], "broken");
}

#[test]
fn migration_is_bounded_once_and_steady_state_never_enumerates_origin() {
    let (storage, engine) = fixture(10);
    engine.prepare_locked(&operation("op")).unwrap();
    storage.values.borrow_mut().remove(&engine.directory_key);
    let migrated = reopen(storage.clone(), 10).unwrap();
    assert_eq!(
        migrated.load().unwrap(),
        json!({"schema":LEGACY_SCHEMA,"operations":[operation("op")]})
    );
    let before = storage.enumerations.get();
    for index in 0..20000 {
        storage
            .values
            .borrow_mut()
            .insert(format!("unrelated-{index}"), "x".into());
    }
    let reopened = reopen(storage.clone(), 10).unwrap();
    reopened.prepare_locked(&operation("next")).unwrap();
    assert_eq!(storage.enumerations.get(), before);
    storage.values.borrow_mut().remove(&engine.directory_key);
    assert_eq!(
        reason(reopen(storage.clone(), 10).err().unwrap()),
        json!("migration_inventory_exceeded")
    );
    assert_eq!(storage.enumerations.get(), before);
}

#[test]
fn directory_rejects_unknown_fields_unsorted_ids_and_wrong_scope() {
    let (storage, engine) = fixture(10);
    let valid = json!({"schema":DIRECTORY_SCHEMA,"scopeDigest":"a".repeat(64),"entries":[]});
    let mut variants = Vec::new();
    let mut unknown = valid.clone();
    unknown["extra"] = json!(1);
    variants.push(unknown);
    let mut scope = valid.clone();
    scope["scopeDigest"] = json!("b".repeat(64));
    variants.push(scope);
    let mut order = valid.clone();
    order["entries"] = json!([
        {"operationId":"z","state":"ready"},{"operationId":"a","state":"ready"}]);
    variants.push(order);
    let mut duplicate = valid.clone();
    duplicate["entries"] = json!([
        {"operationId":"a","state":"ready"},{"operationId":"a","state":"ready"}]);
    variants.push(duplicate);
    let mut entry_extra = valid.clone();
    entry_extra["entries"] = json!([
        {"operationId":"a","state":"ready","identity":[]}]);
    variants.push(entry_extra);
    let mut invalid_identity = valid;
    invalid_identity["entries"] = json!([
        {"operationId":"a","state":"reserving","identity":[]}]);
    variants.push(invalid_identity);
    for variant in variants {
        let raw = variant.to_string();
        storage
            .values
            .borrow_mut()
            .insert(engine.directory_key.clone(), raw.clone());
        assert!(engine.needs_initialization().is_err());
        assert_eq!(storage.values.borrow()[&engine.directory_key], raw);
    }
}

#[test]
fn completed_removal_with_failed_directory_finalization_repairs_without_replay() {
    let (storage, engine) = fixture(10);
    engine.prepare_locked(&operation("op")).unwrap();
    storage
        .fail_directory_write
        .set(storage.directory_writes.get() + 2);
    assert!(engine.complete_locked(&terminal("op")).is_err());
    assert!(
        !storage
            .values
            .borrow()
            .contains_key(&engine.record_key("op").unwrap())
    );
    let reopened = reopen(storage, 10).unwrap();
    assert_eq!(
        reopened.load().unwrap(),
        json!({"schema":LEGACY_SCHEMA,"operations":[]})
    );
    assert_eq!(reopened.read_directory().unwrap(), Entries::new());
}

#[test]
fn oversized_unadmitted_record_does_not_become_a_recoverable_request() {
    let (storage, engine) = fixture(10);
    let mut oversized = operation("op");
    oversized["reason"] = json!("x".repeat(MAX_RECORD_BYTES));
    assert_eq!(
        reason(engine.prepare_locked(&oversized).err().unwrap()),
        json!("record_oversized")
    );
    assert_eq!(
        reopen(storage, 10).unwrap().load().unwrap(),
        json!({"schema":LEGACY_SCHEMA,"operations":[]})
    );
}

#[test]
fn integer_valued_decimal_record_cleanup_matches_javascript() {
    let (storage, engine) = fixture(1024);
    engine.prepare_locked(&operation("decimal")).unwrap();
    let key = engine.record_key("decimal").unwrap();
    let raw = storage.values.borrow()[&key].clone();
    let mut value: Value = serde_json::from_str(&raw).unwrap();
    value["operation"]["generation"] = serde_json::from_str("7.0").unwrap();
    value["operation"]["connectionGeneration"] = serde_json::from_str("1.0").unwrap();
    storage.values.borrow_mut().insert(key, value.to_string());
    assert!(engine.complete_locked(&terminal("decimal")).unwrap());
    assert!(!engine.complete_locked(&terminal("decimal")).unwrap());
    assert_eq!(engine.load().unwrap()["operations"], json!([]));
}
