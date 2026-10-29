//! Execute the new profile without consulting owner policy/program values.

use std::collections::BTreeSet;
use codex_hepta_cognitive_types::{InventoryCellKindV1, InventoryCellReadoutV1, InventoryCellRequestV1, InventoryCellRouteV1, InventoryPolicyV1, InventoryProgramV1, MemoryOperationV1, MemoryPredictionKindV1, MemoryReadStatusV1, MemoryReadoutV1, execute_inventory_program_v1};
use codex_hepta_cognitive_types::hnmf::{ContractDigestV1, ContractIdV1};
use codex_hepta_memory::InventoryCellOwnerSnapshotV1;
use codex_hepta_neuron::MemoryResidualValueV1;
use serde_json::{Value, json};
use crate::LoadedInventoryCellBundleV1;
use super::{ReadFailure, unavailable};

pub(super) fn execute(request: &InventoryCellRequestV1, route: &InventoryCellRouteV1, bundle: &LoadedInventoryCellBundleV1, owner: &InventoryCellOwnerSnapshotV1) -> Result<InventoryCellReadoutV1, ReadFailure> {
    let (cells, hops) = match route.operation { MemoryOperationV1::Apply => (3, 3), MemoryOperationV1::Change => (1, 2), _ => (1, 1) };
    if request.max_cells < cells || request.max_hops < hops {
        return Err((MemoryReadStatusV1::BudgetExceeded, "inventory cell or hop budget exhausted"));
    }
    // Exact holds are consulted before either parameter cell is evaluated.
    if route.operation == MemoryOperationV1::Apply
        && route.entity.as_ref().and_then(|key| owner.current(key, InventoryCellKindV1::Hold)).is_some()
    {
        return Err((MemoryReadStatusV1::Abstain, "exact owner hold stops inventory composition"));
    }
    let mut sources = BTreeSet::new();
    let mut models = BTreeSet::new();
    let event = |at, sources: &mut BTreeSet<_>| {
        let source = route.entity.as_ref().and_then(|key| owner.at(key, InventoryCellKindV1::Event, at))
            .ok_or((MemoryReadStatusV1::Abstain, "inventory event missing or withdrawn"))?;
        sources.insert(source.source_id);
        source.record.value.as_i64().ok_or_else(|| unavailable("inventory event is invalid"))
    };
    let mut prediction_kind = MemoryPredictionKindV1::SourceEvidence;
    let current_at = owner.observed_at_unix_seconds() as u64;
    let value = match route.operation {
        MemoryOperationV1::Current => Value::from(event(current_at, &mut sources)?),
        MemoryOperationV1::History => Value::from(event(request.at, &mut sources)?),
        MemoryOperationV1::Change => Value::from(event(current_at, &mut sources)?.checked_sub(event(request.since, &mut sources)?).ok_or_else(|| unavailable("inventory delta overflow"))?),
        MemoryOperationV1::Semantic => {
            prediction_kind = MemoryPredictionKindV1::ModelPrediction;
            let key = route.entity.as_ref().ok_or_else(|| unavailable("inventory entity absent"))?;
            let policy = policy(bundle, owner, key, &mut sources, &mut models)?;
            json!({"reserve": policy.reserve, "pack": policy.pack, "limit": policy.limit})
        }
        MemoryOperationV1::Procedure => {
            prediction_kind = MemoryPredictionKindV1::ModelPrediction;
            let key = route.workflow.as_ref().ok_or_else(|| unavailable("inventory workflow absent"))?;
            json!({"program": program(bundle, owner, key, &mut sources, &mut models)?.program})
        }
        MemoryOperationV1::Apply => {
            prediction_kind = MemoryPredictionKindV1::Mixed;
            let entity = route.entity.as_ref().ok_or_else(|| unavailable("inventory entity absent"))?;
            let workflow = route.workflow.as_ref().ok_or_else(|| unavailable("inventory workflow absent"))?;
            let input = event(current_at, &mut sources)?;
            let policy = policy(bundle, owner, entity, &mut sources, &mut models)?;
            let program = program(bundle, owner, workflow, &mut sources, &mut models)?;
            let stop = program.program.iter().position(|opcode| *opcode == 6)
                .ok_or((MemoryReadStatusV1::Abstain, "predicted inventory program has no stop"))?;
            if stop >= usize::from(request.max_steps) {
                return Err((MemoryReadStatusV1::BudgetExceeded, "inventory instruction budget exhausted"));
            }
            Value::from(execute_inventory_program_v1(input, &policy, &program, request.max_steps)
                .map_err(|_| unavailable("predicted inventory program arithmetic failed"))?)
        }
    };
    let readout = InventoryCellReadoutV1 {
        schema: "hepta.memory.inventory-readout.v1".to_string(), route: Some(route.clone()),
        result: MemoryReadoutV1 {
            schema: "hepta.memory.readout.v1".to_string(), query_id: request.query_id.clone(), operation: Some(route.operation),
            status: MemoryReadStatusV1::Ok, value, source_ids: sources.into_iter().collect(), generation: bundle.generation(), snapshot_digest: bundle.bundle_digest(),
            prediction_kind, cell_digests: models.into_iter().collect(), hops, elapsed_seconds: 0.0, reason: None,
        },
    };
    readout.validate().map_err(|_| unavailable("inventory execution returned invalid readout"))?;
    Ok(readout)
}

fn predict(bundle: &LoadedInventoryCellBundleV1, owner: &InventoryCellOwnerSnapshotV1, key: &ContractIdV1, kind: InventoryCellKindV1, sources: &mut BTreeSet<ContractDigestV1>, models: &mut BTreeSet<ContractDigestV1>) -> Result<MemoryResidualValueV1, ReadFailure> {
    let binding = bundle.binding(kind, key).ok_or((MemoryReadStatusV1::Abstain, "inventory parameter address absent"))?;
    let source = owner.current(key, kind).ok_or((MemoryReadStatusV1::Abstain, "inventory parameter source withdrawn"))?;
    if source.source_id != binding.owner_source {
        return Err((MemoryReadStatusV1::Stale, "inventory parameter source mapping changed"));
    }
    let model = bundle.model(kind).map_err(|_| unavailable("inventory parameter profile absent"))?;
    let prediction = model.predict(&binding.features, bundle.encoder_digest()).map_err(|_| unavailable("inventory residual inference failed"))?;
    if prediction.parameter_digest != model.parameters_digest() || prediction.encoder_digest != bundle.encoder_digest() {
        return Err(unavailable("inventory residual prediction binding changed"));
    }
    sources.insert(source.source_id);
    models.insert(ContractDigestV1::from_digest(model.artifact_digest()).map_err(|_| unavailable("inventory artifact digest invalid"))?);
    Ok(prediction.value)
}

fn policy(bundle: &LoadedInventoryCellBundleV1, owner: &InventoryCellOwnerSnapshotV1, key: &ContractIdV1, sources: &mut BTreeSet<ContractDigestV1>, models: &mut BTreeSet<ContractDigestV1>) -> Result<InventoryPolicyV1, ReadFailure> {
    match predict(bundle, owner, key, InventoryCellKindV1::Semantic, sources, models)? {
        MemoryResidualValueV1::Semantic { reserve, pack, limit } => Ok(InventoryPolicyV1 { reserve, pack, limit }),
        _ => Err(unavailable("inventory semantic output profile differs")),
    }
}
fn program(bundle: &LoadedInventoryCellBundleV1, owner: &InventoryCellOwnerSnapshotV1, key: &ContractIdV1, sources: &mut BTreeSet<ContractDigestV1>, models: &mut BTreeSet<ContractDigestV1>) -> Result<InventoryProgramV1, ReadFailure> {
    match predict(bundle, owner, key, InventoryCellKindV1::Skill, sources, models)? {
        MemoryResidualValueV1::Skill { program } => Ok(InventoryProgramV1 { program }),
        _ => Err(unavailable("inventory skill output profile differs")),
    }
}
