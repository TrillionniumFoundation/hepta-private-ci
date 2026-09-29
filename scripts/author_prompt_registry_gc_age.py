#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()


def read(path: str) -> str:
    return (ROOT / path).read_text()


def write(path: str, value: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value)


def replace_once(path: str, old: str, new: str) -> None:
    value = read(path)
    count = value.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one exact match, found {count}: {old[:140]!r}")
    write(path, value.replace(old, new, 1))


write(
    "codex-rs/hepta-prompt-registry/src/durable_gc_age.rs",
    r'''//! Versioned, conservative reclaim-age facts for owner-local payload GC.
//!
//! Facts are advisory only for deletion eligibility; they never authorize a
//! prompt use or rewrite semantic/audit history. A newly observed inactive
//! payload starts its retention clock at the current revision/time, even when
//! it became inactive earlier. That conservative rule prevents reconstruction
//! from shortening a retention window after an upgrade or missing sidecar.

use std::collections::BTreeMap;
use std::fs::File;
use std::io::Read;
use std::io::Write;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use super::Access;
use super::DurableRegistryError;
use super::entry_exists;
use super::map_precommit_io;
use super::open_private;

const GC_AGE_SCHEMA: u32 = 1;
const GC_AGE_FILE: &str = "registry.gc-age.json";
const GC_AGE_NEXT: &str = "registry.gc-age.next";
const MAX_GC_AGE_BYTES: u64 = 4 * 1024 * 1024;
const POLICY_DIGEST_DOMAIN: &[u8] = b"hepta.prompt-registry.gc-policy.v1";
const MAX_CLOCK_AUTHORITY_BYTES: usize = 256;

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PromptRegistryGcPolicyV1 {
    pub minimum_revision_retention: u64,
    pub minimum_age_ms: Option<u64>,
    pub trusted_time_epoch: u64,
    pub now_unix_ms: Option<u64>,
    pub clock_authority: String,
    pub clock_version: u32,
}

impl PromptRegistryGcPolicyV1 {
    #[must_use]
    pub fn immediate() -> Self {
        Self {
            minimum_revision_retention: 0,
            minimum_age_ms: None,
            trusted_time_epoch: 1,
            now_unix_ms: None,
            clock_authority: "legacy-immediate-v1".to_owned(),
            clock_version: 1,
        }
    }

    pub fn validate(&self) -> Result<(), DurableRegistryError> {
        if self.trusted_time_epoch == 0
            || self.clock_version == 0
            || self.clock_authority.is_empty()
            || self.clock_authority.len() > MAX_CLOCK_AUTHORITY_BYTES
            || self.clock_authority.as_bytes().contains(&0)
            || self.minimum_age_ms.is_some() != self.now_unix_ms.is_some()
            || self.minimum_age_ms == Some(0)
            || self.now_unix_ms == Some(0)
        {
            return Err(DurableRegistryError::InvalidGcPolicy);
        }
        Ok(())
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = POLICY_DIGEST_DOMAIN.to_vec();
        bytes.extend_from_slice(&self.minimum_revision_retention.to_be_bytes());
        match self.minimum_age_ms {
            None => bytes.push(0),
            Some(value) => {
                bytes.push(1);
                bytes.extend_from_slice(&value.to_be_bytes());
            }
        }
        bytes.extend_from_slice(&self.trusted_time_epoch.to_be_bytes());
        match self.now_unix_ms {
            None => bytes.push(0),
            Some(value) => {
                bytes.push(1);
                bytes.extend_from_slice(&value.to_be_bytes());
            }
        }
        bytes.extend_from_slice(
            &u32::try_from(self.clock_authority.len())
                .unwrap_or(u32::MAX)
                .to_be_bytes(),
        );
        bytes.extend_from_slice(self.clock_authority.as_bytes());
        bytes.extend_from_slice(&self.clock_version.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredAgeFact {
    reclaimable_since_revision: u64,
    trusted_time_epoch: u64,
    reclaimable_since_unix_ms: Option<u64>,
    clock_authority: String,
    clock_version: u32,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub(super) struct GcAgeState {
    facts: BTreeMap<String, StoredAgeFact>,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredGcAgeState {
    schema: u32,
    facts: BTreeMap<String, StoredAgeFact>,
}

impl GcAgeState {
    pub(super) fn load(root: &File) -> Result<Self, DurableRegistryError> {
        if !entry_exists(root, GC_AGE_FILE)? {
            return Ok(Self::default());
        }
        let mut bytes = Vec::new();
        open_private(root, GC_AGE_FILE, Access::Read)?
            .take(MAX_GC_AGE_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| DurableRegistryError::Unavailable)?;
        if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_GC_AGE_BYTES {
            return Err(DurableRegistryError::Corrupt);
        }
        let stored: StoredGcAgeState =
            serde_json::from_slice(&bytes).map_err(|_| DurableRegistryError::Corrupt)?;
        if stored.schema != GC_AGE_SCHEMA {
            return Err(DurableRegistryError::Corrupt);
        }
        for (id, fact) in &stored.facts {
            StableId::new(id.clone()).map_err(|_| DurableRegistryError::Corrupt)?;
            validate_fact(fact)?;
        }
        Ok(Self { facts: stored.facts })
    }

    pub(super) fn ensure_facts(
        &mut self,
        inactive_ids: &[StableId],
        source_revision: u64,
        policy: &PromptRegistryGcPolicyV1,
    ) -> Result<bool, DurableRegistryError> {
        policy.validate()?;
        if source_revision == 0 {
            return Err(DurableRegistryError::Corrupt);
        }
        let mut changed = false;
        for id in inactive_ids {
            let key = id.to_string();
            if let Some(existing) = self.facts.get(&key) {
                validate_fact(existing)?;
                if existing.reclaimable_since_revision > source_revision {
                    return Err(DurableRegistryError::Corrupt);
                }
                continue;
            }
            self.facts.insert(
                key,
                StoredAgeFact {
                    reclaimable_since_revision: source_revision,
                    trusted_time_epoch: policy.trusted_time_epoch,
                    reclaimable_since_unix_ms: policy.now_unix_ms,
                    clock_authority: policy.clock_authority.clone(),
                    clock_version: policy.clock_version,
                },
            );
            changed = true;
        }
        Ok(changed)
    }

    pub(super) fn eligible(
        &self,
        id: &StableId,
        source_revision: u64,
        policy: &PromptRegistryGcPolicyV1,
    ) -> Result<bool, DurableRegistryError> {
        policy.validate()?;
        let fact = self
            .facts
            .get(id.as_str())
            .ok_or(DurableRegistryError::Corrupt)?;
        validate_fact(fact)?;
        let revision_age = source_revision
            .checked_sub(fact.reclaimable_since_revision)
            .ok_or(DurableRegistryError::Corrupt)?;
        if revision_age < policy.minimum_revision_retention {
            return Ok(false);
        }
        let Some(minimum_age_ms) = policy.minimum_age_ms else {
            return Ok(true);
        };
        let Some(now_unix_ms) = policy.now_unix_ms else {
            return Err(DurableRegistryError::InvalidGcPolicy);
        };
        let Some(since_unix_ms) = fact.reclaimable_since_unix_ms else {
            return Ok(false);
        };
        if fact.trusted_time_epoch != policy.trusted_time_epoch
            || fact.clock_authority != policy.clock_authority
            || fact.clock_version != policy.clock_version
        {
            return Ok(false);
        }
        Ok(now_unix_ms
            .checked_sub(since_unix_ms)
            .is_some_and(|age| age >= minimum_age_ms))
    }

    pub(super) fn revision_age(
        &self,
        id: &StableId,
        source_revision: u64,
    ) -> Result<u64, DurableRegistryError> {
        let fact = self
            .facts
            .get(id.as_str())
            .ok_or(DurableRegistryError::Corrupt)?;
        source_revision
            .checked_sub(fact.reclaimable_since_revision)
            .ok_or(DurableRegistryError::Corrupt)
    }

    pub(super) fn trusted_age_ms(
        &self,
        id: &StableId,
        policy: &PromptRegistryGcPolicyV1,
    ) -> Result<Option<u64>, DurableRegistryError> {
        let fact = self
            .facts
            .get(id.as_str())
            .ok_or(DurableRegistryError::Corrupt)?;
        let Some(now_unix_ms) = policy.now_unix_ms else {
            return Ok(None);
        };
        let Some(since_unix_ms) = fact.reclaimable_since_unix_ms else {
            return Ok(None);
        };
        if fact.trusted_time_epoch != policy.trusted_time_epoch
            || fact.clock_authority != policy.clock_authority
            || fact.clock_version != policy.clock_version
        {
            return Ok(None);
        }
        Ok(now_unix_ms.checked_sub(since_unix_ms))
    }

    pub(super) fn persist(&self, root: &File) -> Result<(), DurableRegistryError> {
        let bytes = serde_json::to_vec(&StoredGcAgeState {
            schema: GC_AGE_SCHEMA,
            facts: self.facts.clone(),
        })
        .map_err(|_| DurableRegistryError::Unavailable)?;
        if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_GC_AGE_BYTES {
            return Err(DurableRegistryError::CapacityExceeded);
        }
        let mut next = open_private(root, GC_AGE_NEXT, Access::Create)?;
        next.set_len(0).map_err(map_precommit_io)?;
        next.write_all(&bytes).map_err(map_precommit_io)?;
        next.sync_all().map_err(map_precommit_io)?;
        replace_gc_age(root)?;
        root.sync_all()
            .map_err(|_| DurableRegistryError::IndeterminateDurability)
    }
}

fn validate_fact(fact: &StoredAgeFact) -> Result<(), DurableRegistryError> {
    if fact.reclaimable_since_revision == 0
        || fact.trusted_time_epoch == 0
        || fact.reclaimable_since_unix_ms == Some(0)
        || fact.clock_authority.is_empty()
        || fact.clock_authority.len() > MAX_CLOCK_AUTHORITY_BYTES
        || fact.clock_authority.as_bytes().contains(&0)
        || fact.clock_version == 0
    {
        return Err(DurableRegistryError::Corrupt);
    }
    Ok(())
}

#[cfg(unix)]
fn replace_gc_age(root: &File) -> Result<(), DurableRegistryError> {
    rustix::fs::renameat(root, GC_AGE_NEXT, root, GC_AGE_FILE)
        .map_err(|_| DurableRegistryError::Unavailable)
}

#[cfg(not(unix))]
fn replace_gc_age(_root: &File) -> Result<(), DurableRegistryError> {
    Err(DurableRegistryError::UnsafeStateDirectory)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).unwrap_or_else(|error| panic!("id: {error}"))
    }

    #[test]
    fn revision_and_trusted_time_windows_are_both_required() {
        let policy = PromptRegistryGcPolicyV1 {
            minimum_revision_retention: 2,
            minimum_age_ms: Some(1_000),
            trusted_time_epoch: 7,
            now_unix_ms: Some(10_000),
            clock_authority: "trusted-clock:v1".to_owned(),
            clock_version: 1,
        };
        let mut state = GcAgeState::default();
        state
            .ensure_facts(&[id("realization:one")], 10, &policy)
            .unwrap_or_else(|error| panic!("facts: {error}"));
        let later = PromptRegistryGcPolicyV1 {
            now_unix_ms: Some(11_000),
            ..policy.clone()
        };
        assert!(!state
            .eligible(&id("realization:one"), 11, &later)
            .unwrap_or_else(|error| panic!("revision gate: {error}")));
        assert!(state
            .eligible(&id("realization:one"), 12, &later)
            .unwrap_or_else(|error| panic!("eligible: {error}")));
        let wrong_epoch = PromptRegistryGcPolicyV1 {
            trusted_time_epoch: 8,
            ..later
        };
        assert!(!state
            .eligible(&id("realization:one"), 12, &wrong_epoch)
            .unwrap_or_else(|error| panic!("epoch gate: {error}")));
    }
}
''',
)

replace_once(
    "codex-rs/hepta-prompt-registry/src/durable.rs",
    '''#[path = "durable_gc.rs"]
mod gc;
''',
    '''#[path = "durable_gc.rs"]
mod gc;
#[path = "durable_gc_age.rs"]
mod gc_age;
''',
)
replace_once(
    "codex-rs/hepta-prompt-registry/src/durable.rs",
    "pub use gc::PromptRegistryGcReceipt;\n",
    "pub use gc::PromptRegistryGcReceipt;\npub use gc_age::PromptRegistryGcPolicyV1;\n",
)
replace_once(
    "codex-rs/hepta-prompt-registry/src/durable.rs",
    '''    ConfigurationMismatch,
    StorageFull,
''',
    '''    ConfigurationMismatch,
    InvalidGcPolicy,
    StorageFull,
''',
)
replace_once(
    "codex-rs/hepta-prompt-registry/src/failure.rs",
    "            Self::ConfigurationMismatch => Failure::ConfigurationRejected,\n",
    "            Self::ConfigurationMismatch => Failure::ConfigurationRejected,\n            Self::InvalidGcPolicy => Failure::InvalidInput,\n",
)

write(
    "codex-rs/hepta-prompt-registry/src/durable_gc.rs",
    r'''//! Owner-local payload collection with a bounded two-slot publication protocol.
//!
//! Eligibility is governed by versioned, conservative reclaim-age facts. The
//! selected generation remains intact while the alternate private slot is
//! written; only a durably selected V5 manifest permits predecessor cleanup.
//! Audit records, revocation, relationships and supersession are never pruned.

use std::collections::BTreeSet;

use codex_hepta_types::StableId;
use serde::Serialize;

#[cfg(unix)]
use super::Access;
use super::DurablePromptRegistry;
use super::DurableRegistryError;
use super::PromptRegistryGcPolicyV1;
#[cfg(unix)]
use super::entry_exists;
use super::gc_age::GcAgeState;
#[cfg(unix)]
use super::open_private;
use super::validate_restored;

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PromptRegistryGcReceipt {
    pub source_revision: u64,
    pub selected_revision: u64,
    pub selected_registry_digest: [u8; 32],
    pub policy_digest: [u8; 32],
    pub collected_payload_records: usize,
    pub collected_payload_bytes: u64,
    pub deferred_payload_records: usize,
    pub deferred_payload_bytes: u64,
    pub oldest_reclaimable_revision_age: Option<u64>,
    pub oldest_reclaimable_age_ms: Option<u64>,
    /// Namespace/file allocation reclamation only, not secure device erasure.
    pub unlinked_file_bytes: u64,
    /// False only after predecessor removal and its directory sync succeed.
    pub cleanup_pending: bool,
    pub selected_payload_file_bytes: u64,
    pub total_nanos: u128,
}

impl DurablePromptRegistry {
    /// Compatibility profile: records versioned age facts, but imposes no
    /// retention delay. Production callers should use an explicit policy.
    pub fn collect_payload_garbage(
        &mut self,
    ) -> Result<PromptRegistryGcReceipt, DurableRegistryError> {
        self.collect_payload_garbage_with_policy(&PromptRegistryGcPolicyV1::immediate())
    }

    /// Collect inactive raw payloads only after every configured revision/time
    /// retention gate passes. Missing facts start conservatively at this call.
    pub fn collect_payload_garbage_with_policy(
        &mut self,
        policy: &PromptRegistryGcPolicyV1,
    ) -> Result<PromptRegistryGcReceipt, DurableRegistryError> {
        self.ensure_available()?;
        policy.validate()?;
        let started = std::time::Instant::now();
        let source_revision = self.registry.revision.get();
        let inactive = self
            .registry
            .realization_payloads
            .iter()
            .filter(|(id, _)| {
                !self
                    .registry
                    .realizations
                    .get(*id)
                    .is_some_and(|realization| realization.active)
            })
            .map(|(id, payload)| {
                (
                    id.clone(),
                    u64::try_from(payload.len()).unwrap_or(u64::MAX),
                )
            })
            .collect::<Vec<_>>();
        let inactive_ids = inactive
            .iter()
            .map(|(id, _)| id.clone())
            .collect::<Vec<StableId>>();
        let mut age_state = GcAgeState::load(&self.store.root)?;
        if age_state.ensure_facts(&inactive_ids, source_revision, policy)?
            && let Err(error) = age_state.persist(&self.store.root)
        {
            if matches!(error, DurableRegistryError::IndeterminateDurability) {
                self.poisoned = true;
            }
            return Err(error);
        }

        let mut eligible = BTreeSet::new();
        let mut records = 0_usize;
        let mut bytes = 0_u64;
        let mut deferred_records = 0_usize;
        let mut deferred_bytes = 0_u64;
        let mut oldest_revision_age = None::<u64>;
        let mut oldest_age_ms = None::<u64>;
        for (id, payload_bytes) in &inactive {
            let revision_age = age_state.revision_age(id, source_revision)?;
            oldest_revision_age = Some(
                oldest_revision_age
                    .map_or(revision_age, |current| current.max(revision_age)),
            );
            if let Some(age_ms) = age_state.trusted_age_ms(id, policy)? {
                oldest_age_ms = Some(oldest_age_ms.map_or(age_ms, |current| current.max(age_ms)));
            }
            if age_state.eligible(id, source_revision, policy)? {
                eligible.insert(id.clone());
                records = records.saturating_add(1);
                bytes = bytes.saturating_add(*payload_bytes);
            } else {
                deferred_records = deferred_records.saturating_add(1);
                deferred_bytes = deferred_bytes.saturating_add(*payload_bytes);
            }
        }

        if records != 0 {
            let mut next = self.registry.clone();
            next.realization_payloads
                .retain(|id, _| !eligible.contains(id));
            let revision = next.next_revision().map_err(DurableRegistryError::Core)?;
            next.commit_revision(revision, /*revocation*/ false);
            validate_restored(&next)?;
            let predecessor = self.store.payloads.clone();
            self.store.payloads = predecessor.next_generation();
            if let Err(error) = self.store.persist(&next) {
                self.store.payloads = predecessor;
                if matches!(error, DurableRegistryError::IndeterminateDurability) {
                    self.poisoned = true;
                }
                return Err(error);
            }
            self.registry = next;
        }

        // Sync the selected namespace even on a retry after reopen: unlinking
        // the other slot must never precede stabilizing the selected manifest.
        let (unlinked_file_bytes, cleanup_pending) = self.cleanup_unselected_payload_slot();
        Ok(PromptRegistryGcReceipt {
            source_revision,
            selected_revision: self.registry.revision.get(),
            selected_registry_digest: self.registry.snapshot_digest().into_array(),
            policy_digest: policy.digest().into_array(),
            collected_payload_records: records,
            collected_payload_bytes: bytes,
            deferred_payload_records: deferred_records,
            deferred_payload_bytes: deferred_bytes,
            oldest_reclaimable_revision_age: oldest_revision_age,
            oldest_reclaimable_age_ms: oldest_age_ms,
            unlinked_file_bytes,
            cleanup_pending,
            selected_payload_file_bytes: self.store.payloads.selected_file_bytes(),
            total_nanos: started.elapsed().as_nanos(),
        })
    }

    #[cfg(unix)]
    fn cleanup_unselected_payload_slot(&self) -> (u64, bool) {
        let name = self.store.payloads.slot().other().file_name();
        if self.store.root.sync_all().is_err() {
            return (0, true);
        }
        match entry_exists(&self.store.root, name) {
            Ok(false) => return (0, false),
            Ok(true) => {}
            Err(_) => return (0, true),
        }
        let Ok(file) = open_private(&self.store.root, name, Access::Read) else {
            return (0, true);
        };
        let Ok(metadata) = file.metadata() else {
            return (0, true);
        };
        if rustix::fs::unlinkat(&self.store.root, name, rustix::fs::AtFlags::empty()).is_err() {
            return (0, true);
        }
        (metadata.len(), self.store.root.sync_all().is_err())
    }

    #[cfg(not(unix))]
    fn cleanup_unselected_payload_slot(&self) -> (u64, bool) {
        (0, true)
    }
}

#[cfg(all(test, unix))]
#[path = "durable_gc_tests.rs"]
mod tests;
''',
)

print("prompt.registry versioned GC-age source edits applied")
