use std::fs::File;
use std::fs::OpenOptions;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;

use codex_hepta_contracts::ProviderEffectAck;
use codex_hepta_contracts::ProviderEffectAckStatus;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectLookup;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use super::MAX_IMAGE_BYTES;
use super::failure;
use super::image::MemoryCellMigrationManifestV9;
use super::image::decode;

#[path = "memory_cell_migration_v9_storage.rs"]
mod storage;
use storage::*;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
enum Phase { Received, Prepared, Committed }

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct Transaction {
    intent: ProviderEffectIntent,
    manifest: Sha256Digest,
    phase: Phase,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct Current {
    intent: ProviderEffectIntent,
    manifest: MemoryCellMigrationManifestV9,
}

/// Provider-owned create/prepare/commit state. The root must be a private local
/// filesystem with atomic rename and directory fsync. One held lock fences all
/// mutation. A whole-root rollback still needs an independently retained host
/// witness; this store does not manufacture one or grant reader admission.
pub struct MemoryCellMigrationStoreV9 {
    root: PathBuf,
    pub(super) expected: MemoryCellMigrationManifestV9,
    _lock: File,
}

impl MemoryCellMigrationStoreV9 {
    pub fn open(root: PathBuf, expected: MemoryCellMigrationManifestV9) -> Result<Self, String> {
        expected.validate()?;
        private_directory(&root)?;
        let lock_path = root.join("LOCK");
        regular_or_absent(&lock_path)?;
        let lock = OpenOptions::new().read(true).write(true).create(true).truncate(false)
            .mode(0o600).open(lock_path).map_err(failure)?;
        lock.try_lock().map_err(failure)?;
        for name in ["transactions", "images"] { private_directory(&root.join(name))?; }
        let store = Self { root, expected, _lock: lock };
        store.require_predecessor(None)?;
        // Continue only previously durable exact-payload operations. Startup
        // recovery never creates a new logical effect or a new provider key.
        for entry in std::fs::read_dir(store.root.join("transactions")).map_err(failure)? {
            let path = entry.map_err(failure)?.path();
            if path.extension().is_some_and(|value| value == "json") {
                let row: Transaction = read_json(&path)?;
                row.intent.validate().map_err(failure)?;
                Sha256Digest::parse(row.manifest.as_str().to_string()).map_err(failure)?;
                if path != store.transaction_path(&row.intent) { return Err("migration journal key/path mismatch".into()); }
                if row.manifest == store.expected.digest()? && row.phase != Phase::Committed {
                    let payload = read_bounded(&store.payload_path(&row.intent), MAX_IMAGE_BYTES)?;
                    store.commit(&row.intent, &payload, &mut |_| {})?;
                }
            }
        }
        Ok(store)
    }

    /// Return only a verified complete committed image. Opening a cognitive
    /// owner or selecting its artifact still needs the existing owner APIs.
    pub fn committed_image(&self, expected_payload: &Sha256Digest) -> Result<PathBuf, String> {
        let current: Current = read_json(&self.root.join("CURRENT.json"))?;
        current.intent.validate().map_err(failure)?;
        if current.intent.payload_sha256 != *expected_payload || current.manifest != self.expected {
            return Err("migration committed vector mismatch".into());
        }
        if self.verify_image(&current.intent)? != current.manifest { return Err("migration CURRENT differs from retained image".into()); }
        Ok(self.image_path(&current.intent).join("data"))
    }

    pub(super) fn commit(
        &self,
        intent: &ProviderEffectIntent,
        raw: &[u8],
        observe: &mut dyn FnMut(&str),
    ) -> Result<ProviderEffectAck, String> {
        intent.validate().map_err(failure)?;
        if Sha256Digest::for_bytes(raw) != intent.payload_sha256 {
            return Err("migration provider payload binding mismatch".into());
        }
        let (manifest, contents) = decode(raw)?;
        let transaction_path = self.transaction_path(intent);
        if transaction_path.exists() {
            let previous: Transaction = read_json(&transaction_path)?;
            if previous.intent != *intent || previous.manifest != manifest.digest()? {
                return Err("migration idempotency key conflict".into());
            }
            if previous.phase == Phase::Committed {
                self.verify_image(intent)?;
                return Ok(ack(intent));
            }
        }
        if manifest != self.expected { return Err("migration unconfigured manifest".into()); }
        self.require_predecessor(Some(intent))?;
        let image = self.image_path(intent);
        private_directory(&image)?;
        let data = image.join("data");
        private_directory(&data)?;
        immutable_file(&self.payload_path(intent), raw, /*mode*/ 0o600)?;
        let mut row = Transaction { intent: intent.clone(), manifest: manifest.digest()?, phase: Phase::Received };
        save_json(&transaction_path, &row)?;
        observe("received");
        for (entry, bytes) in manifest.files.iter().zip(contents) {
            let destination = data.join(&entry.path);
            let parent = destination.parent().ok_or("migration missing parent")?;
            private_directory(parent)?;
            immutable_file(&destination, bytes, entry.mode)?;
        }
        self.verify_image(intent)?;
        row.phase = Phase::Prepared;
        save_json(&transaction_path, &row)?;
        observe("prepared");
        self.require_predecessor(Some(intent))?;
        save_json(&self.root.join("CURRENT.json"), &Current { intent: intent.clone(), manifest })?;
        observe("current");
        row.phase = Phase::Committed;
        save_json(&transaction_path, &row)?;
        observe("committed");
        Ok(ack(intent))
    }

    pub(super) fn lookup(&self, intent: &ProviderEffectIntent) -> Result<ProviderEffectLookup, String> {
        intent.validate().map_err(failure)?;
        let path = self.transaction_path(intent);
        if !path.exists() { return Ok(ProviderEffectLookup::NotFound); }
        let row: Transaction = read_json(&path)?;
        if row.intent != *intent {
            return Ok(ProviderEffectLookup::Conflict { observed_payload_sha256: Some(row.intent.payload_sha256) });
        }
        if row.phase != Phase::Committed { return Ok(ProviderEffectLookup::Unknown); }
        self.verify_image(intent)?;
        // A historical transaction receipt remains durable after a later image
        // becomes current. It proves transfer completion, never current use.
        Ok(ProviderEffectLookup::Ack(ack(intent)))
    }

    fn require_predecessor(&self, same_intent: Option<&ProviderEffectIntent>) -> Result<(), String> {
        let path = self.root.join("CURRENT.json");
        if !path.exists() {
            if self.expected.generation == 1 && self.expected.predecessor.is_none() { return Ok(()); }
            return Err("migration missing required predecessor".into());
        }
        let current: Current = read_json(&path)?;
        current.intent.validate().map_err(failure)?;
        current.manifest.validate()?;
        if self.verify_image(&current.intent)? != current.manifest { return Err("migration CURRENT differs from retained image".into()); }
        if current.manifest == self.expected && same_intent.is_none_or(|value| value == &current.intent) {
            return Ok(());
        }
        if current.manifest.generation.checked_add(1) == Some(self.expected.generation)
            && self.expected.predecessor.as_ref() == Some(&current.intent.payload_sha256)
            && current.manifest.pin.owner_agent_id == self.expected.pin.owner_agent_id
            && current.manifest.destination == self.expected.destination
        { return Ok(()); }
        Err("migration stale, forked or mismatched current image".into())
    }

    fn verify_image(&self, intent: &ProviderEffectIntent) -> Result<MemoryCellMigrationManifestV9, String> {
        intent.validate().map_err(failure)?;
        let raw = read_bounded(&self.payload_path(intent), MAX_IMAGE_BYTES)?;
        if Sha256Digest::for_bytes(&raw) != intent.payload_sha256 { return Err("migration retained payload corrupt".into()); }
        let (manifest, _) = decode(&raw)?;
        for entry in &manifest.files {
            let path = self.image_path(intent).join("data").join(&entry.path);
            let raw = read_bounded(&path, MAX_IMAGE_BYTES)?;
            let mode = std::fs::metadata(&path).map_err(failure)?.permissions().mode() & 0o777;
            if raw.len() as u64 != entry.bytes || Sha256Digest::for_bytes(&raw) != entry.sha256 || mode != entry.mode {
                return Err("migration materialized file bytes or mode mismatch".into());
            }
        }
        Ok(manifest)
    }

    fn transaction_path(&self, intent: &ProviderEffectIntent) -> PathBuf {
        self.root.join("transactions").join(format!("{}.json", Sha256Digest::for_bytes(intent.key.as_str().as_bytes()).as_str()))
    }
    fn image_path(&self, intent: &ProviderEffectIntent) -> PathBuf { self.root.join("images").join(intent.payload_sha256.as_str()) }
    fn payload_path(&self, intent: &ProviderEffectIntent) -> PathBuf { self.image_path(intent).join("PAYLOAD") }
}

fn ack(intent: &ProviderEffectIntent) -> ProviderEffectAck {
    ProviderEffectAck::new(intent.key.clone(), intent.payload_sha256.clone(),
        Sha256Digest::for_bytes(format!("hepta.memory.migration.v9:{}:{}", intent.key.as_str(), intent.payload_sha256.as_str()).as_bytes()),
        ProviderEffectAckStatus::Completed)
}
