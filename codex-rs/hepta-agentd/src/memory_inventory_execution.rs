//! Inventory composition reads event and hold evidence; values and programs
//! come exclusively from the selected immutable parameter artifacts.

use std::collections::BTreeSet;

use codex_hepta_cognitive_store::MemoryInventoryOwnerSnapshotV1;
use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::MemoryInventoryExecutionStatusV1;
use codex_hepta_cognitive_types::MemoryInventoryKindV1;
use codex_hepta_cognitive_types::MemoryInventoryReadoutV1;
use codex_hepta_cognitive_types::MemoryInventoryRequestV1;
use codex_hepta_cognitive_types::MemoryInventoryValueV1;
use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_cognitive_types::MemoryPredictionKindV1;
use codex_hepta_cognitive_types::MemoryReadStatusV1;
use codex_hepta_cognitive_types::execute_memory_inventory_program_v1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_neuron::MemoryResidualPredictionV1;
use serde_json::Value;

use super::ReadFailure;
use super::unavailable;
use crate::LoadedMemoryInventoryBundleV1;

/// Numerical input to the common bounded interpreter. Implementations only
/// provide immutable predictions; the caller separately authenticates every
/// selected artifact and current owner cut before and after this computation.
pub(crate) trait InventoryParameters {
    fn generation(&self) -> ContractGenerationV1;
    fn bundle_digest(&self) -> ContractDigestV1;
    fn predict(
        &self,
        kind: MemoryCellKindV1,
        key: &str,
    ) -> Result<MemoryResidualPredictionV1, String>;
}

impl InventoryParameters for LoadedMemoryInventoryBundleV1 {
    fn generation(&self) -> ContractGenerationV1 {
        self.generation()
    }
    fn bundle_digest(&self) -> ContractDigestV1 {
        self.bundle_digest()
    }
    fn predict(
        &self,
        kind: MemoryCellKindV1,
        key: &str,
    ) -> Result<MemoryResidualPredictionV1, String> {
        self.predict(kind, key)
    }
}

pub(crate) fn execute(
    request: &MemoryInventoryRequestV1,
    operation: MemoryOperationV1,
    bundle: &impl InventoryParameters,
    owner: &MemoryInventoryOwnerSnapshotV1,
) -> Result<MemoryInventoryReadoutV1, ReadFailure> {
    let (cells, hops) = match operation {
        MemoryOperationV1::Apply => (4, 3),
        MemoryOperationV1::Change => (1, 2),
        _ => (1, 1),
    };
    if request.max_cells < cells || request.max_hops < hops {
        return Err((
            MemoryReadStatusV1::BudgetExceeded,
            "inventory operation exceeds cell or hop budget",
        ));
    }
    let required = owner.required_sources(request, operation).map_err(|_| {
        (
            MemoryReadStatusV1::Abstain,
            "inventory dependency is missing or withdrawn",
        )
    })?;
    let mut sources = BTreeSet::new();
    let mut models = BTreeSet::new();
    let event = |at, sources: &mut BTreeSet<_>| {
        let source = owner
            .at(&request.entity_key, MemoryInventoryKindV1::Event, at)
            .ok_or((
                MemoryReadStatusV1::Abstain,
                "event source is missing or withdrawn",
            ))?;
        sources.insert(source.source_id);
        source
            .record
            .value
            .as_i64()
            .ok_or_else(|| unavailable("owner event value is invalid"))
    };
    let current_at = owner.observed_at_unix_seconds() as u64;
    let mut prediction_kind = MemoryPredictionKindV1::SourceEvidence;
    let value = match operation {
        MemoryOperationV1::Current => Value::from(event(current_at, &mut sources)?),
        MemoryOperationV1::History => Value::from(event(request.at, &mut sources)?),
        MemoryOperationV1::Change => Value::from(
            event(current_at, &mut sources)?
                .checked_sub(event(request.since, &mut sources)?)
                .ok_or_else(|| unavailable("inventory event difference overflow"))?,
        ),
        MemoryOperationV1::Semantic | MemoryOperationV1::Procedure => {
            prediction_kind = MemoryPredictionKindV1::ModelPrediction;
            let (kind, key) = if operation == MemoryOperationV1::Semantic {
                (MemoryCellKindV1::Semantic, &request.entity_key)
            } else {
                (MemoryCellKindV1::Procedure, &request.workflow_key)
            };
            inner_value(predict(
                bundle,
                kind,
                key,
                owner,
                &mut sources,
                &mut models,
            )?)?
        }
        MemoryOperationV1::Apply => {
            let hold = owner
                .current(&request.entity_key, MemoryInventoryKindV1::Hold)
                .ok_or((
                    MemoryReadStatusV1::Abstain,
                    "explicit hold evidence is absent",
                ))?;
            match hold.record.value.as_bool() {
                Some(false) => {
                    sources.insert(hold.source_id);
                }
                Some(true) => {
                    return Err((MemoryReadStatusV1::Abstain, "inventory entity is on hold"));
                }
                None => return Err(unavailable("owner hold value is invalid")),
            }
            prediction_kind = MemoryPredictionKindV1::Mixed;
            let event = event(current_at, &mut sources)?;
            let MemoryInventoryValueV1::Semantic(policy) = predict(
                bundle,
                MemoryCellKindV1::Semantic,
                &request.entity_key,
                owner,
                &mut sources,
                &mut models,
            )?
            else {
                return Err(unavailable(
                    "semantic model returned another inventory kind",
                ));
            };
            let MemoryInventoryValueV1::Procedure(program) = predict(
                bundle,
                MemoryCellKindV1::Procedure,
                &request.workflow_key,
                owner,
                &mut sources,
                &mut models,
            )?
            else {
                return Err(unavailable(
                    "procedure model returned another inventory kind",
                ));
            };
            let execution =
                execute_memory_inventory_program_v1(&program, event, &policy, request.max_steps)
                    .map_err(|_| {
                        unavailable("predicted inventory procedure violates its contract")
                    })?;
            match execution.status {
                MemoryInventoryExecutionStatusV1::Completed => serde_json::to_value(execution)
                    .map_err(|_| unavailable("inventory execution could not be encoded"))?,
                MemoryInventoryExecutionStatusV1::BudgetStop => {
                    return Err((
                        MemoryReadStatusV1::BudgetExceeded,
                        "inventory program exceeds step budget",
                    ));
                }
                MemoryInventoryExecutionStatusV1::MissingStop => {
                    return Err((
                        MemoryReadStatusV1::Abstain,
                        "predicted inventory program has no stop",
                    ));
                }
                MemoryInventoryExecutionStatusV1::ArithmeticOverflow => {
                    return Err((
                        MemoryReadStatusV1::Abstain,
                        "predicted inventory program overflows",
                    ));
                }
            }
        }
    };
    if sources != required {
        return Err(unavailable(
            "inventory read did not consume its exact typed dependencies",
        ));
    }
    let readout = MemoryInventoryReadoutV1 {
        schema: "hepta.memory.inventory-readout.v1".to_string(),
        query_id: request.query_id.clone(),
        operation: Some(operation),
        status: MemoryReadStatusV1::Ok,
        value,
        source_ids: sources.into_iter().collect(),
        generation: bundle.generation(),
        snapshot_digest: bundle.bundle_digest(),
        prediction_kind,
        cell_digests: models.into_iter().collect(),
        hops,
        elapsed_seconds: 0.0,
        reason: None,
    };
    readout
        .validate()
        .map_err(|_| unavailable("native inventory readout is invalid"))?;
    Ok(readout)
}

fn predict(
    bundle: &impl InventoryParameters,
    kind: MemoryCellKindV1,
    key: &ContractIdV1,
    owner: &MemoryInventoryOwnerSnapshotV1,
    sources: &mut BTreeSet<ContractDigestV1>,
    models: &mut BTreeSet<ContractDigestV1>,
) -> Result<MemoryInventoryValueV1, ReadFailure> {
    let predicted = bundle
        .predict(kind, key.as_str())
        .map_err(|_| unavailable("native parameter inference failed"))?;
    let value = predicted.value.ok_or((
        MemoryReadStatusV1::Abstain,
        "native parameter model declined the key or confidence",
    ))?;
    let inventory_kind = match kind {
        MemoryCellKindV1::Semantic => MemoryInventoryKindV1::Semantic,
        MemoryCellKindV1::Procedure => MemoryInventoryKindV1::Procedure,
        MemoryCellKindV1::Event => return Err(unavailable("event prediction is forbidden")),
    };
    let source = owner.current(key, inventory_kind).ok_or((
        MemoryReadStatusV1::Abstain,
        "predicted inventory support is missing or withdrawn",
    ))?;
    if predicted.kind != kind
        || predicted.source_ids != vec![source.source_id.to_string()]
        || predicted.abstain.is_some()
        || !matches!(
            (&value, kind),
            (
                MemoryInventoryValueV1::Semantic(_),
                MemoryCellKindV1::Semantic
            ) | (
                MemoryInventoryValueV1::Procedure(_),
                MemoryCellKindV1::Procedure
            )
        )
    {
        return Err(unavailable(
            "native prediction differs from its typed owner support",
        ));
    }
    let artifact = ContractDigestV1::parse(&predicted.artifact_digest)
        .map_err(|_| unavailable("native parameter artifact digest is invalid"))?;
    sources.insert(source.source_id);
    models.insert(artifact);
    Ok(value)
}

fn inner_value(value: MemoryInventoryValueV1) -> Result<Value, ReadFailure> {
    match value {
        MemoryInventoryValueV1::Semantic(policy) => serde_json::to_value(policy),
        MemoryInventoryValueV1::Procedure(program) => serde_json::to_value(program),
    }
    .map_err(|_| unavailable("native inventory value could not be encoded"))
}
