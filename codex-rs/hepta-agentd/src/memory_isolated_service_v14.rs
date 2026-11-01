//! Query-local independent selection with explicit current-owner fallback.
//! Every used model keeps its complete training partition; unrelated stale
//! cells cannot disable a read. Source and publication fences are sequential.

use std::collections::BTreeSet;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::MemoryInventoryKindV1;
use codex_hepta_cognitive_types::MemoryInventoryReadoutV1;
use codex_hepta_cognitive_types::MemoryInventoryRequestV1;
use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_cognitive_types::MemoryPredictionKindV1;
use codex_hepta_cognitive_types::MemoryReadStatusV1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::MemoryInventoryOwnerSnapshotV1;
use codex_hepta_memory::MemoryTrainingSelectorV11;
use codex_hepta_neuron::MemoryResidualPredictionV1;
use codex_hepta_types::Digest32;
use serde_json::Value;

use crate::MemoryCellReleaseV11;
use crate::SelectedMemoryCellV11;
use crate::memory_inventory_runtime::ReadFailure;
use crate::memory_inventory_runtime::execution::InventoryParameters;
use crate::memory_inventory_runtime::execution::execute;

const SCHEMA: &str = "hepta.memory.inventory-readout.v14";
const DEADLINE: Duration = Duration::from_secs(5);

struct RegisteredCell {
    selector: MemoryTrainingSelectorV11,
    release: Arc<MemoryCellReleaseV11>,
}

/// Startup-only ownership map. Model revisions are authenticated afresh per
/// request; neither an unavailable model nor this configuration grants facts.
pub struct MemoryIsolatedServiceV14 {
    owner: AgentId,
    scope: ContractIdV1,
    generation: ContractGenerationV1,
    digest: ContractDigestV1,
    cells: Vec<RegisteredCell>,
}

struct UsedCell {
    release: Arc<MemoryCellReleaseV11>,
    selected: Arc<SelectedMemoryCellV11>,
}

pub(crate) struct IsolatedReadV14 {
    snapshot: MemoryInventoryOwnerSnapshotV1,
    generation: ContractGenerationV1,
    digest: ContractDigestV1,
    cells: Vec<UsedCell>,
    fallbacks: Vec<(MemoryCellKindV1, String)>,
}

impl MemoryIsolatedServiceV14 {
    pub fn new(
        owner: &MemoryInventoryOwnerSnapshotV1,
        generation: ContractGenerationV1,
        releases: Vec<(MemoryTrainingSelectorV11, Arc<MemoryCellReleaseV11>)>,
    ) -> Result<Self, String> {
        if releases.len() > 64 || generation.get() >= 1_u64 << 53 {
            return Err("V14 independent cell or generation bound".to_string());
        }
        let mut ids = BTreeSet::new();
        let mut registries = BTreeSet::new();
        let mut addresses = BTreeSet::new();
        let mut cells = Vec::new();
        let mut pins = Vec::new();
        for (selector, release) in releases {
            selector.validate().map_err(|error| error.to_string())?;
            let registry = release.registry_binding()?;
            if &selector.cell_id != release.cell_id()
                || !ids.insert(selector.cell_id.clone())
                || !registries.insert(registry)
                || !matches!(
                    selector.kind,
                    MemoryInventoryKindV1::Semantic | MemoryInventoryKindV1::Procedure
                )
            {
                return Err("V14 scope, duplicate cell or shared registry".to_string());
            }
            for key in &selector.keys {
                let address = serde_json::to_string(&(selector.kind, key))
                    .map_err(|error| error.to_string())?;
                if !addresses.insert(address) {
                    return Err("V14 ambiguous independent ownership".to_string());
                }
            }
            pins.push((selector.clone(), registry.to_string()));
            cells.push(RegisteredCell { selector, release });
        }
        let bytes = serde_json::to_vec(&(
            SCHEMA,
            owner.owner_agent_id(),
            owner.scope(),
            generation,
            pins,
        ))
        .map_err(|error| error.to_string())?;
        Ok(Self {
            owner: owner.owner_agent_id().clone(),
            scope: owner.scope().clone(),
            generation,
            digest: ContractDigestV1::from_digest(Digest32::of_bytes(&bytes))
                .map_err(|error| error.to_string())?,
            cells,
        })
    }

    pub async fn read(
        &self,
        store: &CognitiveStore,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        request: &MemoryInventoryRequestV1,
        operation: MemoryOperationV1,
    ) -> Result<MemoryInventoryReadoutV1, String> {
        let started = Instant::now();
        let future = async {
            let now = crate::memory_cell_runtime::now_unix_seconds()
                .map_err(|error| error.to_string())?;
            let snapshot = store
                .memory_inventory_snapshot(access, scope, now)
                .await
                .map_err(|error| error.to_string())?;
            self.read_acquired(store, access, scope, request, operation, snapshot)
                .await
                .map_err(|(_, reason)| reason.to_string())
        };
        let mut result = tokio::time::timeout(DEADLINE, future)
            .await
            .map_err(|_| "V14 read deadline exceeded".to_string())??;
        if started.elapsed() > DEADLINE {
            return Err("V14 read deadline exceeded".to_string());
        }
        result.elapsed_seconds = started.elapsed().as_secs_f64();
        Ok(result)
    }

    pub(crate) async fn read_acquired(
        &self,
        store: &CognitiveStore,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        request: &MemoryInventoryRequestV1,
        operation: MemoryOperationV1,
        snapshot: MemoryInventoryOwnerSnapshotV1,
    ) -> Result<MemoryInventoryReadoutV1, ReadFailure> {
        let prepared = self.prepare_read(request, operation, snapshot)?;
        let readout = prepared.execute(request, operation)?;
        self.finish_read(store, access, scope, request, prepared, readout)
            .await
    }

    pub(crate) fn prepare_read(
        &self,
        request: &MemoryInventoryRequestV1,
        operation: MemoryOperationV1,
        snapshot: MemoryInventoryOwnerSnapshotV1,
    ) -> Result<IsolatedReadV14, ReadFailure> {
        request
            .validate()
            .map_err(|_| (MemoryReadStatusV1::Abstain, "invalid V14 request"))?;
        if snapshot.owner_agent_id() != &self.owner
            || snapshot.scope() != &self.scope
            || request.scope != self.scope
        {
            return Err((MemoryReadStatusV1::Abstain, "V14 owner or scope differs"));
        }
        let addresses = match operation {
            MemoryOperationV1::Semantic => vec![(MemoryCellKindV1::Semantic, &request.entity_key)],
            MemoryOperationV1::Procedure => {
                vec![(MemoryCellKindV1::Procedure, &request.workflow_key)]
            }
            MemoryOperationV1::Apply => vec![
                (MemoryCellKindV1::Semantic, &request.entity_key),
                (MemoryCellKindV1::Procedure, &request.workflow_key),
            ],
            MemoryOperationV1::Current | MemoryOperationV1::History | MemoryOperationV1::Change => {
                Vec::new()
            }
        };
        let mut cells = Vec::new();
        let mut fallbacks = Vec::new();
        for (kind, key) in addresses {
            let configured = self.cells.iter().find(|cell| {
                matches_kind(cell.selector.kind, kind)
                    && cell.selector.keys.iter().any(|address| address == key)
            });
            let selected = configured
                .and_then(|cell| {
                    cell.release
                        .load_current()
                        .ok()
                        .map(|selected| (cell, selected))
                })
                .filter(|(cell, selected)| {
                    selected.selector() == &cell.selector
                        && selected.validate_owner_snapshot(&snapshot).is_ok()
                        && cell.release.revalidate(selected).is_ok()
                })
                .filter(|(_, selected)| {
                    selected
                        .predict(key.as_str())
                        .is_ok_and(|p| p.value.is_some() && p.abstain.is_none())
                });
            if let Some((cell, selected)) = selected {
                cells.push(UsedCell {
                    release: Arc::clone(&cell.release),
                    selected,
                });
            } else {
                fallbacks.push((kind, key.to_string()));
            }
        }
        let pins: Vec<_> = cells
            .iter()
            .map(|cell| {
                (
                    cell.selected.cell_id(),
                    cell.selected.generation(),
                    cell.selected.digest(),
                    cell.selected.training_projection_digest(),
                )
            })
            .collect();
        let bytes = serde_json::to_vec(&(
            SCHEMA,
            self.digest,
            snapshot.owner_cut_digest(),
            pins,
            &fallbacks,
        ))
        .map_err(|_| {
            (
                MemoryReadStatusV1::Unavailable,
                "V14 read identity encoding",
            )
        })?;
        let digest = ContractDigestV1::from_digest(Digest32::of_bytes(&bytes))
            .map_err(|_| (MemoryReadStatusV1::Unavailable, "V14 read identity digest"))?;
        Ok(IsolatedReadV14 {
            snapshot,
            generation: self.generation,
            digest,
            cells,
            fallbacks,
        })
    }

    pub(crate) async fn finish_read(
        &self,
        store: &CognitiveStore,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        request: &MemoryInventoryRequestV1,
        prepared: IsolatedReadV14,
        readout: MemoryInventoryReadoutV1,
    ) -> Result<MemoryInventoryReadoutV1, ReadFailure> {
        prepared.revalidate()?;
        let now = crate::memory_cell_runtime::now_unix_seconds()
            .map_err(|_| (MemoryReadStatusV1::Unavailable, "V14 clock unavailable"))?;
        let current = store
            .memory_inventory_snapshot(access, scope, now)
            .await
            .map_err(|_| {
                (
                    MemoryReadStatusV1::Unavailable,
                    "V14 current owner unavailable",
                )
            })?;
        let operation = readout
            .operation
            .ok_or((MemoryReadStatusV1::Unavailable, "V14 operation missing"))?;
        if current.owner_agent_id() != &self.owner
            || current.scope() != &self.scope
            || current.owner_cut_digest() != prepared.snapshot.owner_cut_digest()
            || current
                .required_sources(request, operation)
                .map_err(|_| (MemoryReadStatusV1::Stale, "V14 support withdrawn"))?
                != readout.source_ids.iter().copied().collect::<BTreeSet<_>>()
        {
            return Err((
                MemoryReadStatusV1::Stale,
                "V14 complete source cut changed before use",
            ));
        }
        for cell in &prepared.cells {
            cell.selected
                .validate_owner_snapshot(&current)
                .map_err(|_| {
                    (
                        MemoryReadStatusV1::Stale,
                        "V14 used model full projection changed",
                    )
                })?;
        }
        prepared.revalidate()?;
        Ok(readout)
    }

    pub(crate) fn failed(
        &self,
        request: &MemoryInventoryRequestV1,
        status: MemoryReadStatusV1,
        reason: &str,
    ) -> MemoryInventoryReadoutV1 {
        MemoryInventoryReadoutV1 {
            schema: SCHEMA.to_string(),
            query_id: request.query_id.clone(),
            operation: None,
            status,
            value: Value::Null,
            source_ids: Vec::new(),
            generation: self.generation,
            snapshot_digest: self.digest,
            prediction_kind: MemoryPredictionKindV1::None,
            cell_digests: Vec::new(),
            hops: 0,
            elapsed_seconds: 0.0,
            reason: Some(reason.to_string()),
        }
    }
}

impl IsolatedReadV14 {
    pub(crate) fn execute(
        &self,
        request: &MemoryInventoryRequestV1,
        operation: MemoryOperationV1,
    ) -> Result<MemoryInventoryReadoutV1, ReadFailure> {
        execute(request, operation, self, &self.snapshot)
    }

    fn revalidate(&self) -> Result<(), ReadFailure> {
        for cell in &self.cells {
            cell.release.revalidate(&cell.selected).map_err(|_| {
                (
                    MemoryReadStatusV1::Stale,
                    "V14 used publication changed before use",
                )
            })?;
        }
        Ok(())
    }
}

impl InventoryParameters for IsolatedReadV14 {
    fn generation(&self) -> ContractGenerationV1 {
        self.generation
    }
    fn bundle_digest(&self) -> ContractDigestV1 {
        self.digest
    }
    fn readout_schema(&self) -> &'static str {
        SCHEMA
    }
    fn current_source_fallback(&self, kind: MemoryCellKindV1, key: &str) -> bool {
        self.fallbacks
            .iter()
            .any(|(k, address)| *k == kind && address == key)
    }
    fn predict(
        &self,
        kind: MemoryCellKindV1,
        key: &str,
    ) -> Result<MemoryResidualPredictionV1, String> {
        self.cells
            .iter()
            .find(|cell| {
                matches_kind(cell.selected.selector().kind, kind)
                    && cell
                        .selected
                        .selector()
                        .keys
                        .iter()
                        .any(|address| address.as_str() == key)
            })
            .ok_or_else(|| "V14 no selected numerical cell".to_string())?
            .selected
            .predict(key)
    }
}

fn matches_kind(inventory: MemoryInventoryKindV1, cell: MemoryCellKindV1) -> bool {
    matches!(
        (inventory, cell),
        (MemoryInventoryKindV1::Semantic, MemoryCellKindV1::Semantic)
            | (
                MemoryInventoryKindV1::Procedure,
                MemoryCellKindV1::Procedure
            )
    )
}
