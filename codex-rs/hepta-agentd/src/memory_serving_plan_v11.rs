//! Immutable composition of independently selected cells. A restored plan is
//! only a pin set: fresh signed selections and a live owner view are required.
//! Source and publication checks are sequential fences, not a distributed
//! transaction or a production activation authority.

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
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::MemoryInventoryOwnerSnapshotV1;
use codex_hepta_neuron::MemoryResidualPredictionV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;

use crate::MemoryCellReleaseV11;
use crate::SelectedMemoryCellV11;
use crate::memory_inventory_runtime::execution::InventoryParameters;
use crate::memory_inventory_runtime::execution::execute;

const SCHEMA: &str = "hepta.memory.serving-plan.v11";
const MAX_CELLS: usize = 64;
const MAX_PLAN_BYTES: usize = 64 * 1024;
const READ_DEADLINE: Duration = Duration::from_secs(5);

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MemoryCellVersionV11 {
    pub cell_id: ContractIdV1,
    pub generation: ContractGenerationV1,
    pub artifact_digest: ContractDigestV1,
    pub training_projection_digest: ContractDigestV1,
    pub registry_binding: ContractDigestV1,
}

#[derive(Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct PlanPins {
    schema: String,
    owner_agent_id: AgentId,
    scope: ContractIdV1,
    generation: ContractGenerationV1,
    cells: Vec<MemoryCellVersionV11>,
}

struct PlanCell {
    release: Arc<MemoryCellReleaseV11>,
    selected: Arc<SelectedMemoryCellV11>,
}

/// Read-only composition; this value owns no source, mutable model, registry or
/// new executor. Replacing one cell requires constructing a new immutable plan.
pub struct MemoryServingPlanV11 {
    pins: PlanPins,
    digest: ContractDigestV1,
    cells: Vec<PlanCell>,
}

/// A successful V11 receipt. Artifact versions and the current query cut are
/// separate from each cell's training projection and historical acquisition cut.
#[derive(Clone, Debug, Serialize)]
pub struct MemoryPlanReadoutV11 {
    pub schema: &'static str,
    pub query_id: ContractIdV1,
    pub operation: MemoryOperationV1,
    pub value: Value,
    pub source_ids: Vec<ContractDigestV1>,
    pub cells: Vec<MemoryCellVersionV11>,
    pub plan_digest: ContractDigestV1,
    pub plan_generation: ContractGenerationV1,
    pub query_cut_digest: ContractDigestV1,
    pub prediction_kind: MemoryPredictionKindV1,
    pub hops: u8,
    pub elapsed_seconds: f64,
}

struct PreparedRead {
    snapshot: MemoryInventoryOwnerSnapshotV1,
    readout: MemoryInventoryReadoutV1,
}

impl MemoryServingPlanV11 {
    pub fn prepare(
        owner: &MemoryInventoryOwnerSnapshotV1,
        generation: ContractGenerationV1,
        mut releases: Vec<Arc<MemoryCellReleaseV11>>,
    ) -> Result<Self, String> {
        if releases.is_empty() || releases.len() > MAX_CELLS || generation.get() >= 1_u64 << 53 {
            return Err("V11 serving plan cell or generation bound".to_string());
        }
        releases.sort_by(|a, b| a.cell_id().cmp(b.cell_id()));
        let mut ids = BTreeSet::new();
        let mut registries = BTreeSet::new();
        let mut addresses = BTreeSet::new();
        let mut pins = PlanPins {
            schema: SCHEMA.to_string(),
            owner_agent_id: owner.owner_agent_id().clone(),
            scope: owner.scope().clone(),
            generation,
            cells: Vec::new(),
        };
        let mut cells = Vec::new();
        for release in releases {
            let selected = release.load_current()?;
            selected.validate_owner_snapshot(owner)?;
            let binding = release.registry_binding()?;
            if selected.cell_id() != release.cell_id()
                || !ids.insert(selected.cell_id().clone())
                || !registries.insert(binding)
            {
                return Err("V11 plan duplicates a cell or shares its CURRENT registry".to_string());
            }
            for key in &selected.selector().keys {
                let address = serde_json::to_string(&(selected.selector().kind, key))
                    .map_err(|error| error.to_string())?;
                if !addresses.insert(address) {
                    return Err("V11 plan has ambiguous cell ownership".to_string());
                }
            }
            pins.cells.push(MemoryCellVersionV11 {
                cell_id: selected.cell_id().clone(),
                generation: selected.generation(),
                artifact_digest: selected.digest(),
                training_projection_digest: selected.training_projection_digest(),
                registry_binding: ContractDigestV1::from_digest(binding)
                    .map_err(|error| error.to_string())?,
            });
            cells.push(PlanCell { release, selected });
        }
        let encoded = serde_json::to_vec(&pins).map_err(|error| error.to_string())?;
        if encoded.len() > MAX_PLAN_BYTES {
            return Err("V11 plan byte bound".to_string());
        }
        let digest = ContractDigestV1::from_digest(Digest32::of_bytes(&encoded))
            .map_err(|error| error.to_string())?;
        let plan = Self {
            pins,
            digest,
            cells,
        };
        plan.revalidate_releases()?;
        Ok(plan)
    }

    pub fn checkpoint(&self) -> Result<Vec<u8>, String> {
        serde_json::to_vec(&self.pins).map_err(|error| error.to_string())
    }

    /// No deserialized selection is accepted. The independent artifact owners
    /// authenticate their CURRENT/withdrawal state, then all saved pins must match.
    pub fn restore(
        bytes: &[u8],
        owner: &MemoryInventoryOwnerSnapshotV1,
        releases: Vec<Arc<MemoryCellReleaseV11>>,
    ) -> Result<Self, String> {
        if bytes.is_empty() || bytes.len() > MAX_PLAN_BYTES {
            return Err("V11 checkpoint byte bound".to_string());
        }
        let pins: PlanPins = serde_json::from_slice(bytes).map_err(|error| error.to_string())?;
        let plan = Self::prepare(owner, pins.generation, releases)?;
        if plan.pins != pins {
            return Err("V11 checkpoint differs from current selected cell versions".to_string());
        }
        Ok(plan)
    }

    pub fn digest(&self) -> ContractDigestV1 {
        self.digest
    }
    pub fn versions(&self) -> &[MemoryCellVersionV11] {
        &self.pins.cells
    }

    /// Trusted host entry point; operation is already resolved by the host's
    /// bounded resolver. Request text never supplies source or selection authority.
    pub async fn read(
        &self,
        store: &CognitiveStore,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        request: &MemoryInventoryRequestV1,
        operation: MemoryOperationV1,
    ) -> Result<MemoryPlanReadoutV11, String> {
        let started = Instant::now();
        let future = async {
            let now = crate::memory_cell_runtime::now_unix_seconds()
                .map_err(|error| error.to_string())?;
            let prepared = self
                .prepare_read(store, access, scope, request, operation, now)
                .await?;
            let now = crate::memory_cell_runtime::now_unix_seconds()
                .map_err(|error| error.to_string())?;
            self.finish_read(store, access, scope, request, prepared, now)
                .await
        };
        let mut result = tokio::time::timeout(READ_DEADLINE, future)
            .await
            .map_err(|_| "V11 read deadline exceeded".to_string())??;
        // Tokio cancellation cannot preempt synchronous decoding or inference.
        // The return guard still forbids a successful result after the budget.
        let elapsed = started.elapsed();
        if elapsed > READ_DEADLINE {
            return Err("V11 read deadline exceeded".to_string());
        }
        result.elapsed_seconds = elapsed.as_secs_f64();
        Ok(result)
    }

    async fn prepare_read(
        &self,
        store: &CognitiveStore,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        request: &MemoryInventoryRequestV1,
        operation: MemoryOperationV1,
        now: i64,
    ) -> Result<PreparedRead, String> {
        request.validate().map_err(|error| error.to_string())?;
        self.revalidate_releases()?;
        let snapshot = store
            .memory_inventory_snapshot(access, scope, now)
            .await
            .map_err(|error| error.to_string())?;
        if snapshot.owner_agent_id() != &self.pins.owner_agent_id
            || snapshot.scope() != &self.pins.scope
        {
            return Err("V11 plan source owner or scope differs".to_string());
        }
        for cell in &self.cells {
            cell.selected.validate_owner_snapshot(&snapshot)?;
        }
        let readout = execute(request, operation, self, &snapshot)
            .map_err(|(_, reason)| reason.to_string())?;
        Ok(PreparedRead { snapshot, readout })
    }

    async fn finish_read(
        &self,
        store: &CognitiveStore,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        request: &MemoryInventoryRequestV1,
        prepared: PreparedRead,
        now: i64,
    ) -> Result<MemoryPlanReadoutV11, String> {
        self.revalidate_releases()?;
        // A previously stored future version can become current without a new
        // database write. Recheck all fitted partitions, including cells not
        // used by this particular query, at the return boundary as well.
        let current = store
            .memory_inventory_snapshot(access, scope, now)
            .await
            .map_err(|error| error.to_string())?;
        for cell in &self.cells {
            cell.selected.validate_owner_snapshot(&current)?;
        }
        // Query validation still checks the complete acquired read cut. It can
        // conservatively abort an in-flight query on an unrelated write, while
        // the next query reuses unchanged cell weights without republication.
        store
            .revalidate_memory_inventory_readout(
                access,
                scope,
                &prepared.snapshot,
                request,
                &prepared.readout,
                self.pins.generation,
                self.digest,
                now,
            )
            .await
            .map_err(|error| error.to_string())?;
        self.revalidate_releases()?;
        let readout = prepared.readout;
        Ok(MemoryPlanReadoutV11 {
            schema: "hepta.memory.plan-readout.v11",
            query_id: readout.query_id,
            operation: readout
                .operation
                .ok_or("V11 successful read lacks operation")?,
            value: readout.value,
            source_ids: readout.source_ids,
            cells: self.pins.cells.clone(),
            plan_digest: self.digest,
            plan_generation: self.pins.generation,
            query_cut_digest: prepared.snapshot.owner_cut_digest(),
            prediction_kind: readout.prediction_kind,
            hops: readout.hops,
            elapsed_seconds: 0.0,
        })
    }

    fn revalidate_releases(&self) -> Result<(), String> {
        for cell in &self.cells {
            cell.release.revalidate(&cell.selected)?;
        }
        Ok(())
    }
}

impl InventoryParameters for MemoryServingPlanV11 {
    fn generation(&self) -> ContractGenerationV1 {
        self.pins.generation
    }
    fn bundle_digest(&self) -> ContractDigestV1 {
        self.digest
    }
    fn predict(
        &self,
        kind: MemoryCellKindV1,
        key: &str,
    ) -> Result<MemoryResidualPredictionV1, String> {
        let kind = match kind {
            MemoryCellKindV1::Semantic => MemoryInventoryKindV1::Semantic,
            MemoryCellKindV1::Procedure => MemoryInventoryKindV1::Procedure,
            MemoryCellKindV1::Event => return Err("V11 event prediction forbidden".to_string()),
        };
        let cell = self
            .cells
            .iter()
            .find(|cell| {
                cell.selected.selector().kind == kind
                    && cell
                        .selected
                        .selector()
                        .keys
                        .iter()
                        .any(|candidate| candidate.as_str() == key)
            })
            .ok_or("V11 plan has no selected cell for this key")?;
        cell.selected.predict(key)
    }
}

#[cfg(test)]
#[path = "memory_serving_plan_v11_test_support.rs"]
mod test_support;
#[cfg(test)]
#[path = "memory_serving_plan_v11_tests.rs"]
mod tests;
