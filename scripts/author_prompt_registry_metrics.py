#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()


def read(path: str) -> str:
    return (ROOT / path).read_text()


def write(path: str, value: str) -> None:
    (ROOT / path).write_text(value)


def replace_once(path: str, old: str, new: str) -> None:
    value = read(path)
    count = value.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one exact match, found {count}: {old[:140]!r}")
    write(path, value.replace(old, new, 1))


def regex_once(path: str, pattern: str, replacement: str, flags: int = 0) -> None:
    value = read(path)
    updated, count = re.subn(pattern, replacement, value, count=1, flags=flags)
    if count != 1:
        raise SystemExit(f"{path}: expected one regex match, found {count}: {pattern[:140]!r}")
    write(path, updated)


# Full-operation and component timing, including costs before Store::persist.
path = "codex-rs/hepta-prompt-registry/src/durable_io.rs"
replace_once(
    path,
    """pub struct PromptRegistryIoMetrics {
    pub publish_attempts: u64,
""",
    """pub struct PromptRegistryIoMetrics {
    pub mutation_attempts: u64,
    pub successful_mutations: u64,
    pub unchanged_mutations: u64,
    pub failed_mutations: u64,
    pub last_operation_nanos: u128,
    pub total_operation_nanos: u128,
    pub maximum_operation_nanos: u128,
    pub last_clone_nanos: u128,
    pub total_clone_nanos: u128,
    pub maximum_clone_nanos: u128,
    pub last_mutation_apply_nanos: u128,
    pub total_mutation_apply_nanos: u128,
    pub maximum_mutation_apply_nanos: u128,
    pub metadata_encode_attempts: u64,
    pub metadata_encode_nanos: u128,
    pub maximum_metadata_encode_nanos: u128,
    pub publish_attempts: u64,
""",
)
replace_once(
    path,
    """impl PromptRegistryIoMetrics {
    pub(super) fn observe_publish(
""",
    """impl PromptRegistryIoMetrics {
    pub(super) fn observe_mutation(
        &mut self,
        operation_nanos: u128,
        clone_nanos: u128,
        mutation_apply_nanos: u128,
        changed: Option<bool>,
    ) {
        self.mutation_attempts = self.mutation_attempts.saturating_add(1);
        self.last_operation_nanos = operation_nanos;
        self.total_operation_nanos = self.total_operation_nanos.saturating_add(operation_nanos);
        self.maximum_operation_nanos = self.maximum_operation_nanos.max(operation_nanos);
        self.last_clone_nanos = clone_nanos;
        self.total_clone_nanos = self.total_clone_nanos.saturating_add(clone_nanos);
        self.maximum_clone_nanos = self.maximum_clone_nanos.max(clone_nanos);
        self.last_mutation_apply_nanos = mutation_apply_nanos;
        self.total_mutation_apply_nanos = self
            .total_mutation_apply_nanos
            .saturating_add(mutation_apply_nanos);
        self.maximum_mutation_apply_nanos = self
            .maximum_mutation_apply_nanos
            .max(mutation_apply_nanos);
        match changed {
            Some(true) => self.successful_mutations = self.successful_mutations.saturating_add(1),
            Some(false) => self.unchanged_mutations = self.unchanged_mutations.saturating_add(1),
            None => self.failed_mutations = self.failed_mutations.saturating_add(1),
        }
    }

    pub(super) fn observe_metadata_encode(&mut self, elapsed: u128) {
        self.metadata_encode_attempts = self.metadata_encode_attempts.saturating_add(1);
        self.metadata_encode_nanos = self.metadata_encode_nanos.saturating_add(elapsed);
        self.maximum_metadata_encode_nanos = self.maximum_metadata_encode_nanos.max(elapsed);
    }

    pub(super) fn observe_publish(
""",
)

path = "codex-rs/hepta-prompt-registry/src/durable.rs"
regex_once(
    path,
    r"    fn commit\(\n        &mut self,\n        mutation: impl FnOnce\(&mut PromptRegistry\) -> Result<RegistryReceipt, Error>,\n    \) -> Result<RegistryReceipt, DurableRegistryError> \{\n.*?\n    \}\n\}\n\n#\[derive\(Deserialize, Serialize\)\]",
    """    fn commit(
        &mut self,
        mutation: impl FnOnce(&mut PromptRegistry) -> Result<RegistryReceipt, Error>,
    ) -> Result<RegistryReceipt, DurableRegistryError> {
        if self.poisoned {
            return Err(DurableRegistryError::ReopenRequired);
        }
        let operation_started = std::time::Instant::now();
        let clone_started = std::time::Instant::now();
        let mut next = self.registry.clone();
        let clone_nanos = clone_started.elapsed().as_nanos();
        let mutation_started = std::time::Instant::now();
        let receipt = match mutation(&mut next) {
            Ok(receipt) => receipt,
            Err(error) => {
                let apply_nanos = mutation_started.elapsed().as_nanos();
                self.store.io.observe_mutation(
                    operation_started.elapsed().as_nanos(),
                    clone_nanos,
                    apply_nanos,
                    None,
                );
                return Err(DurableRegistryError::Core(error));
            }
        };
        let apply_nanos = mutation_started.elapsed().as_nanos();
        let changed = receipt.disposition != crate::MutationDisposition::Unchanged;
        if changed {
            match self.store.persist(&next) {
                Ok(()) => self.registry = next,
                Err(DurableRegistryError::IndeterminateDurability) => {
                    self.poisoned = true;
                    self.store.io.observe_mutation(
                        operation_started.elapsed().as_nanos(),
                        clone_nanos,
                        apply_nanos,
                        None,
                    );
                    return Err(DurableRegistryError::IndeterminateDurability);
                }
                Err(error) => {
                    self.store.io.observe_mutation(
                        operation_started.elapsed().as_nanos(),
                        clone_nanos,
                        apply_nanos,
                        None,
                    );
                    return Err(error);
                }
            }
        }
        self.store.io.observe_mutation(
            operation_started.elapsed().as_nanos(),
            clone_nanos,
            apply_nanos,
            Some(changed),
        );
        Ok(receipt)
    }
}

#[derive(Deserialize, Serialize)]""",
    flags=re.S,
)
replace_once(
    path,
    """    fn persist_inner(&mut self, registry: &PromptRegistry) -> Result<(), DurableRegistryError> {
        let successor = self.payloads.successor(registry)?;
        let bytes = if successor.uses_generation_manifest() {
            serde_json::to_vec(&payloads::StoredV5 {
                schema: 5,
                state: stored_metadata(registry),
                payload_slot: successor.slot(),
                payload_references: successor.references(),
            })
        } else {
            serde_json::to_vec(&payloads::StoredV4 {
                schema: 4,
                state: stored_metadata(registry),
                payload_references: successor.references(),
            })
        }
        .map_err(|_| DurableRegistryError::Unavailable)?;
""",
    """    fn persist_inner(&mut self, registry: &PromptRegistry) -> Result<(), DurableRegistryError> {
        let encode_started = std::time::Instant::now();
        let encoded = (|| {
            let successor = self.payloads.successor(registry)?;
            let bytes = if successor.uses_generation_manifest() {
                serde_json::to_vec(&payloads::StoredV5 {
                    schema: 5,
                    state: stored_metadata(registry),
                    payload_slot: successor.slot(),
                    payload_references: successor.references(),
                })
            } else {
                serde_json::to_vec(&payloads::StoredV4 {
                    schema: 4,
                    state: stored_metadata(registry),
                    payload_references: successor.references(),
                })
            }
            .map_err(|_| DurableRegistryError::Unavailable)?;
            Ok::<_, DurableRegistryError>((successor, bytes))
        })();
        self.io
            .observe_metadata_encode(encode_started.elapsed().as_nanos());
        let (successor, bytes) = encoded?;
""",
)

# Policy-aware operational gauges expose real durable age facts when a trusted
# clock policy is supplied; legacy metrics remain explicitly unknown.
path = "codex-rs/hepta-prompt-registry/src/durable_gc_age.rs"
replace_once(
    path,
    """    pub(super) fn revision_age(
        &self,
        id: &StableId,
        source_revision: u64,
    ) -> Result<u64, DurableRegistryError> {
""",
    """    pub(super) fn contains(&self, id: &StableId) -> bool {
        self.facts.contains_key(id.as_str())
    }

    pub(super) fn revision_age(
        &self,
        id: &StableId,
        source_revision: u64,
    ) -> Result<u64, DurableRegistryError> {
""",
)

path = "codex-rs/hepta-prompt-registry/src/durable_maintenance.rs"
replace_once(
    path,
    "use super::DurableRegistryError;\n",
    "use super::DurableRegistryError;\nuse super::PromptRegistryGcPolicyV1;\nuse super::gc_age::GcAgeState;\n",
)
replace_once(
    path,
    """    /// None: V4 has no durable GC enqueue timestamp. Never report an invented 0.
    pub oldest_reclaimable_age_ms: Option<u64>,
""",
    """    /// Present only when a trusted clock policy matches durable V1 age facts.
    pub oldest_reclaimable_age_ms: Option<u64>,
    /// Durable revision age does not depend on a wall clock.
    pub oldest_reclaimable_revision_age: Option<u64>,
""",
)
replace_once(
    path,
    """    pub fn operational_metrics(
        &self,
    ) -> Result<PromptRegistryOperationalMetrics, PromptRegistryMaintenanceError> {
        metrics_for(self)
    }
""",
    """    pub fn operational_metrics(
        &self,
    ) -> Result<PromptRegistryOperationalMetrics, PromptRegistryMaintenanceError> {
        metrics_for(self, None)
    }

    pub fn operational_metrics_with_gc_policy(
        &self,
        policy: &PromptRegistryGcPolicyV1,
    ) -> Result<PromptRegistryOperationalMetrics, PromptRegistryMaintenanceError> {
        policy.validate()?;
        metrics_for(self, Some(policy))
    }
""",
)
replace_once(
    path,
    """fn metrics_for(
    owner: &DurablePromptRegistry,
) -> Result<PromptRegistryOperationalMetrics, PromptRegistryMaintenanceError> {
""",
    """fn metrics_for(
    owner: &DurablePromptRegistry,
    gc_policy: Option<&PromptRegistryGcPolicyV1>,
) -> Result<PromptRegistryOperationalMetrics, PromptRegistryMaintenanceError> {
""",
)
replace_once(
    path,
    """    let physical_payload_file_bytes = file_bytes(&owner.store, owner.store.payloads.file_name())?;
""",
    """    let (oldest_reclaimable_revision_age, oldest_reclaimable_age_ms) =
        if let Some(policy) = gc_policy {
            let ages = GcAgeState::load(&owner.store.root)?;
            let mut oldest_revision = None::<u64>;
            let mut oldest_ms = None::<u64>;
            for id in registry.realization_payloads.keys().filter(|id| {
                !registry
                    .realizations
                    .get(*id)
                    .is_some_and(|realization| realization.active)
            }) {
                if !ages.contains(id) {
                    continue;
                }
                let revision_age = ages.revision_age(id, registry.revision.get())?;
                oldest_revision = Some(
                    oldest_revision.map_or(revision_age, |current| current.max(revision_age)),
                );
                if let Some(age_ms) = ages.trusted_age_ms(id, policy)? {
                    oldest_ms = Some(oldest_ms.map_or(age_ms, |current| current.max(age_ms)));
                }
            }
            (oldest_revision, oldest_ms)
        } else {
            (None, None)
        };
    let physical_payload_file_bytes = file_bytes(&owner.store, owner.store.payloads.file_name())?;
""",
)
replace_once(
    path,
    """        reclaimable_payload_bytes,
        oldest_reclaimable_age_ms: None,
        physical_payload_file_bytes,
""",
    """        reclaimable_payload_bytes,
        oldest_reclaimable_age_ms,
        oldest_reclaimable_revision_age,
        physical_payload_file_bytes,
""",
)

print("prompt.registry full-operation metrics source edits applied")
