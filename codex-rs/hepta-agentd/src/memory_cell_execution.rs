//! Six typed operations. Semantic and procedural values come from native tensors.

use std::collections::BTreeSet;

use codex_hepta_cognitive_store::MemoryCellOwnerSnapshotV1;
use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_cognitive_types::MemoryPredictionKindV1;
use codex_hepta_cognitive_types::MemoryReadStatusV1;
use codex_hepta_cognitive_types::MemoryReadoutV1;
use codex_hepta_cognitive_types::MemoryRequestV1;
use codex_hepta_cognitive_types::execute_memory_cell_program_v1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_neuron::AssociativeMemoryCellV1;
use serde_json::Value;

use crate::LoadedMemoryCellBundleV1;

use super::ReadFailure;
use super::unavailable;

pub(super) fn execute(request: &MemoryRequestV1, operation: MemoryOperationV1, bundle: &LoadedMemoryCellBundleV1, owner: &MemoryCellOwnerSnapshotV1) -> Result<MemoryReadoutV1, ReadFailure> {
    let (cells, hops) = match operation {
        MemoryOperationV1::Apply => (3, 3),
        MemoryOperationV1::Change => (1, 2),
        _ => (1, 1),
    };
    if request.max_cells < cells || request.max_hops < hops {
        return Err((MemoryReadStatusV1::BudgetExceeded, "typed memory operation exceeds cell or hop budget"));
    }
    let mut sources = BTreeSet::new();
    let mut models = BTreeSet::new();
    let event = |at, sources: &mut BTreeSet<_>| {
        let source = owner.at(&request.entity, MemoryCellKindV1::Event, at)
            .ok_or((MemoryReadStatusV1::Abstain, "event source is missing or withdrawn"))?;
        sources.insert(source.source_id);
        source.record.value.as_i64().ok_or_else(|| unavailable("owner event value is invalid"))
    };
    let current_at = owner.observed_at_unix_seconds() as u64;
    let mut prediction_kind = MemoryPredictionKindV1::SourceEvidence;
    let value = match operation {
        MemoryOperationV1::Current => Value::from(event(current_at, &mut sources)?),
        MemoryOperationV1::History => Value::from(event(request.at, &mut sources)?),
        MemoryOperationV1::Change => Value::from(event(current_at, &mut sources)? - event(request.since, &mut sources)?),
        MemoryOperationV1::Semantic | MemoryOperationV1::Procedure => {
            prediction_kind = MemoryPredictionKindV1::ModelPrediction;
            let model = if operation == MemoryOperationV1::Semantic { bundle.semantic() } else { bundle.procedure() };
            predict(model, request, owner, &mut sources, &mut models)?
        }
        MemoryOperationV1::Apply => {
            prediction_kind = MemoryPredictionKindV1::Mixed;
            let event = event(current_at, &mut sources)?;
            let semantic = predict(bundle.semantic(), request, owner, &mut sources, &mut models)?;
            let procedure = predict(bundle.procedure(), request, owner, &mut sources, &mut models)?;
            Value::from(execute_memory_cell_program_v1(&procedure, event, &semantic)
                .map_err(|_| unavailable("predicted procedure could not execute within its typed bounds"))?)
        }
    };
    let readout = MemoryReadoutV1 {
        schema: "hepta.memory.readout.v1".to_string(), query_id: request.query_id.clone(), operation: Some(operation),
        status: MemoryReadStatusV1::Ok, value, source_ids: sources.into_iter().collect(), generation: bundle.generation(),
        snapshot_digest: bundle.bundle_digest(), prediction_kind, cell_digests: models.into_iter().collect(),
        hops, elapsed_seconds: 0.0, reason: None,
    };
    readout.validate().map_err(|_| unavailable("native memory readout is invalid"))?;
    Ok(readout)
}

fn predict(model: &AssociativeMemoryCellV1, request: &MemoryRequestV1, owner: &MemoryCellOwnerSnapshotV1, sources: &mut BTreeSet<ContractDigestV1>, models: &mut BTreeSet<ContractDigestV1>) -> Result<Value, ReadFailure> {
    let predicted = model.predict(request.entity.as_str()).map_err(|_| unavailable("native memory inference failed"))?;
    let value = predicted.value.ok_or((MemoryReadStatusV1::Abstain, "native memory model declined the entity or confidence"))?;
    let source = owner.current(&request.entity, model.kind())
        .ok_or((MemoryReadStatusV1::Abstain, "predicted memory support is missing or withdrawn"))?;
    if predicted.kind != model.kind() || predicted.source_ids != vec![source.source_id.to_string()]
        || predicted.artifact_digest != model.digest().to_string()
        || predicted.parameter_digest != model.parameters_digest().to_string() || predicted.abstain.is_some() {
        return Err(unavailable("native prediction differs from the selected artifact or owner support"));
    }
    sources.insert(source.source_id);
    models.insert(ContractDigestV1::from_digest(model.digest()).map_err(|_| unavailable("native artifact digest is invalid"))?);
    Ok(value)
}
