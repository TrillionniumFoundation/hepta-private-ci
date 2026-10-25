use super::*;

impl Engine {
    fn decode_directory(&self, raw: &str) -> Result<Entries, ControlError> {
        if raw.len() > MAX_DIRECTORY_BYTES {
            return Err(failure("directory_oversized"));
        }
        let root: Value = serde_json::from_str(raw).map_err(|_| failure("directory_corrupt"))?;
        let object = root
            .as_object()
            .ok_or_else(|| failure("directory_scope_mismatch"))?;
        if object.len() != 3
            || object.get("schema").and_then(Value::as_str) != Some(DIRECTORY_SCHEMA)
            || object.get("scopeDigest").and_then(Value::as_str) != Some(self.scope_digest.as_str())
        {
            return Err(failure("directory_scope_mismatch"));
        }
        let items = object
            .get("entries")
            .and_then(Value::as_array)
            .ok_or_else(|| failure("directory_scope_mismatch"))?;
        if items.len() > self.max_entries {
            return Err(failure("capacity_exhausted"));
        }
        let mut entries = Entries::new();
        let mut previous: Option<&str> = None;
        for item in items {
            let object = item
                .as_object()
                .ok_or_else(|| failure("directory_corrupt"))?;
            let id = operation_id(item)?;
            if previous.is_some_and(|previous| id <= previous) {
                return Err(failure("directory_corrupt"));
            }
            let state = item
                .get("state")
                .and_then(Value::as_str)
                .ok_or_else(|| failure("directory_corrupt"))?;
            let entry = if state == "ready" && object.len() == 2 {
                Entry::Ready
            } else {
                if object.len() != 3 {
                    return Err(failure("directory_corrupt"));
                }
                let identity = item
                    .get("identity")
                    .and_then(Value::as_array)
                    .filter(|items| items.len() == IDENTITY_FIELDS.len())
                    .ok_or_else(|| failure("directory_corrupt"))?;
                match state {
                    "reserving" => Entry::Reserving(identity.clone()),
                    "removing" => Entry::Removing(identity.clone()),
                    _ => return Err(failure("directory_corrupt")),
                }
            };
            entries.insert(id.into(), entry);
            previous = Some(id);
        }
        Ok(entries)
    }

    pub(super) fn read_directory(&self) -> Result<Entries, ControlError> {
        let raw = self
            .storage
            .get(&self.directory_key, "directory_read_failed")?
            .ok_or_else(|| failure("directory_missing"))?;
        self.decode_directory(&raw)
    }

    pub(super) fn write_directory(&self, entries: &Entries) -> Result<(), ControlError> {
        if entries.len() > self.max_entries {
            return Err(failure("capacity_exhausted"));
        }
        let items: Vec<Value> = entries
            .iter()
            .map(|(id, entry)| match entry {
                Entry::Ready => json!({"operationId": id, "state": "ready"}),
                Entry::Reserving(identity) => {
                    json!({"operationId": id, "state": "reserving", "identity": identity})
                }
                Entry::Removing(identity) => {
                    json!({"operationId": id, "state": "removing", "identity": identity})
                }
            })
            .collect();
        let raw = serde_json::to_string(&json!({"schema": DIRECTORY_SCHEMA, "scopeDigest": self.scope_digest, "entries": items}))
            .map_err(|_| failure("directory_corrupt"))?;
        if raw.len() > MAX_DIRECTORY_BYTES {
            return Err(failure("directory_oversized"));
        }
        self.storage
            .set(&self.directory_key, &raw, "directory_write_failed")?;
        if self
            .storage
            .get(&self.directory_key, "directory_readback_failed")?
            .as_deref()
            != Some(raw.as_str())
        {
            return Err(failure("directory_write_readback_failed"));
        }
        Ok(())
    }

    fn scan_legacy(&self) -> Result<Entries, ControlError> {
        let count = self.storage.len()?;
        if count > MAX_MIGRATION_KEYS {
            return Err(failure("migration_inventory_exceeded"));
        }
        self.migration_scans.set(self.migration_scans.get() + 1);
        self.migration_keys.set(self.migration_keys.get() + count);
        let mut entries = Entries::new();
        for index in 0..count {
            let Some(key) = self
                .storage
                .key(index)?
                .filter(|key| key.starts_with(&self.prefix))
            else {
                continue;
            };
            let Some(raw) = self.storage.get(&key, "record_read_failed")? else {
                continue;
            };
            let operation = self.decode_record(&key, &raw)?;
            entries.insert(operation_id(&operation)?.into(), Entry::Ready);
            if entries.len() > self.max_entries {
                return Err(failure("capacity_exhausted"));
            }
        }
        Ok(entries)
    }

    pub(super) fn reconcile(&self, entries: &mut Entries) -> Result<bool, ControlError> {
        let mut changed = false;
        for (id, entry) in entries.clone() {
            let (expected, reserving) = match entry {
                Entry::Ready => continue,
                Entry::Reserving(identity) => (identity, true),
                Entry::Removing(identity) => (identity, false),
            };
            let key = self.record_key(&id)?;
            let Some(raw) = self.storage.get(&key, "record_read_failed")? else {
                entries.remove(&id);
                changed = true;
                continue;
            };
            let operation = self.decode_record(&key, &raw)?;
            if !IDENTITY_FIELDS
                .iter()
                .zip(&expected)
                .all(|(field, expected)| value_equal(operation.get(field), Some(expected)))
            {
                return Err(failure("directory_identity_mismatch"));
            }
            if reserving {
                // No request is dispatched until the ready marker has been read back.
                self.storage.remove(&key, "record_remove_failed")?;
                if self
                    .storage
                    .get(&key, "record_remove_readback_failed")?
                    .is_some()
                {
                    return Err(failure("reservation_repair_failed"));
                }
                entries.remove(&id);
            } else {
                // A failed terminal removal retains the old identity for lookup.
                entries.insert(id, Entry::Ready);
            }
            changed = true;
        }
        Ok(changed)
    }

    pub(super) fn needs_initialization(&self) -> Result<bool, ControlError> {
        let Some(raw) = self
            .storage
            .get(&self.directory_key, "directory_read_failed")?
        else {
            return Ok(true);
        };
        Ok(self
            .decode_directory(&raw)?
            .values()
            .any(|entry| entry != &Entry::Ready))
    }

    pub(super) fn initialize_locked(&self) -> Result<(), ControlError> {
        let Some(raw) = self
            .storage
            .get(&self.directory_key, "directory_read_failed")?
        else {
            return self.write_directory(&self.scan_legacy()?);
        };
        let mut entries = self.decode_directory(&raw)?;
        if self.reconcile(&mut entries)? {
            self.write_directory(&entries)?;
        }
        Ok(())
    }
}
