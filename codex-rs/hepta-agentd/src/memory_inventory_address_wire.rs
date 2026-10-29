//! Independent inventory wire profile. Values and operation labels are never
//! supplied as input to the address worker; all returned bindings are checked.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_cognitive_store::MemoryInventoryOwnerSnapshotV1;
use codex_hepta_cognitive_types::MemoryInventoryKindV1;
use codex_hepta_cognitive_types::MemoryInventoryRequestV1;
use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use serde::Deserialize;
use serde_json::Value;

use crate::MemoryInventoryResolvedAddressV1;
use super::wire::{MAX_REQUEST_FRAME, WorkerCost, canonical, hash};

pub(super) struct BoundInventoryRequest {
    pub bytes: Vec<u8>,
    digest: ContractDigestV1,
    registry_digest: ContractDigestV1,
    source_cut: ContractDigestV1,
    request: MemoryInventoryRequestV1,
}

impl BoundInventoryRequest {
    pub fn build(
        request: &MemoryInventoryRequestV1,
        owner: &MemoryInventoryOwnerSnapshotV1,
        aliases: &BTreeMap<ContractIdV1, Vec<String>>,
    ) -> Result<Self, String> {
        request.validate().map_err(|error| error.to_string())?;
        if request.scope != *owner.scope() { return Err("inventory address scope mismatch".to_string()); }
        let mut entities = BTreeSet::new();
        let mut workflows = BTreeSet::new();
        for row in owner.records().iter().filter(|row| owner.current_source_ids().contains(&row.source_id)) {
            match row.record.kind {
                MemoryInventoryKindV1::Procedure => { workflows.insert(row.record.key.clone()); }
                MemoryInventoryKindV1::Semantic | MemoryInventoryKindV1::Event | MemoryInventoryKindV1::Hold => {
                    entities.insert(row.record.key.clone());
                }
            }
        }
        if entities.is_empty() || workflows.is_empty() || entities.len() + workflows.len() > 4_096 {
            return Err("inventory address registry size is invalid".to_string());
        }
        let rows = |keys: BTreeSet<ContractIdV1>| keys.into_iter().map(|key| {
            serde_json::json!({"aliases": aliases.get(&key).cloned().unwrap_or_default(), "key": key})
        }).collect::<Vec<_>>();
        let registry = serde_json::json!({
            "schema":"hepta.memory.inventory-owner-registry.v1", "scope":owner.scope(),
            "source_cut":owner.owner_cut_digest(), "entities":rows(entities), "workflows":rows(workflows),
        });
        let request_value = serde_json::to_value(request).map_err(|error| error.to_string())?;
        let digest = hash(&canonical(&request_value)?);
        let registry_digest = hash(&canonical(&registry)?);
        let mut bytes = canonical(&serde_json::json!({
            "schema":"hepta.memory.inventory-address-worker-request.v1", "request":request_value, "registry":registry,
        }))?;
        bytes.push(b'\n');
        if bytes.len() > MAX_REQUEST_FRAME { return Err("inventory address request exceeds frame bound".to_string()); }
        Ok(Self { bytes, digest, registry_digest, source_cut: owner.owner_cut_digest(), request: request.clone() })
    }

    pub fn validate_response(
        &self,
        bytes: &[u8],
        model: ContractDigestV1,
        original: &MemoryInventoryRequestV1,
    ) -> Result<(Option<MemoryInventoryResolvedAddressV1>, WorkerCost), String> {
        let decision: Decision = serde_json::from_slice(bytes).map_err(|_| "malformed inventory address response")?;
        let shape: Value = serde_json::from_slice(bytes).map_err(|_| "malformed inventory response JSON")?;
        if self.request != *original || shape.as_object().is_none_or(|object| object.len() != 13)
            || shape.get("decision").is_some_and(|scores| !scores.is_null() && scores.as_object().is_none_or(|object| object.len() != 8))
            || decision.schema != "hepta.memory.inventory-address-decision.v1" || decision.authority
            || decision.query_id.as_ref() != Some(&original.query_id)
            || decision.request_digest != Some(self.digest) || decision.registry_digest != Some(self.registry_digest)
            || decision.source_cut != Some(self.source_cut) || decision.model_digest != model
        { return Err("inventory address response binding mismatch".to_string()); }
        let cost = decision.cost.ok_or("inventory address response lacks cost")?;
        if cost.request_body_bytes != self.bytes.len() - 1
            || ![cost.processing_wall_seconds, cost.processing_cpu_seconds].iter()
                .all(|number| number.is_finite() && (0.0..=120.0).contains(number))
        { return Err("inventory address processing cost is invalid".to_string()); }
        if let Some(scores) = &decision.decision { scores.validate()?; }
        match decision.status.as_str() {
            "accepted" => {
                let plan = decision.plan.ok_or("accepted inventory decision lacks a plan")?;
                let scores = decision.decision.ok_or("accepted inventory decision lacks model scores")?;
                let (cells, hops) = required(plan.operation);
                if decision.reason.is_some() || decision.request.as_ref() != Some(original)
                    || plan.source_cut != self.source_cut || plan.registry_digest != self.registry_digest
                    || plan.required_cells != cells || plan.read_hops != hops
                    || cells.len() > usize::from(original.max_cells) || hops > original.max_hops
                    || scores.operation != Some(plan.operation)
                    || scores.raw_operation != operation_name(plan.operation)
                    || scores.score < scores.threshold || scores.margin < scores.required_margin
                    || scores.capability_reason.is_some()
                { return Err("accepted inventory plan differs from request or model decision".to_string()); }
                Ok((Some(MemoryInventoryResolvedAddressV1 {
                    request: original.clone(), operation: plan.operation, owner_cut_digest: self.source_cut, model_digest: model,
                }), cost))
            }
            "rejected" | "unavailable" => {
                if decision.request.is_some() || decision.plan.is_some()
                    || decision.reason.is_none_or(|reason| reason.is_empty() || reason.len() > 1_024 || reason.contains('\0'))
                { return Err("failed inventory address response contains partial authority".to_string()); }
                if decision.status == "unavailable" { return Err("inventory address worker is unavailable".to_string()); }
                Ok((None, cost))
            }
            _ => Err("unknown inventory address status".to_string()),
        }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Decision {
    schema: String, query_id: Option<ContractIdV1>, request_digest: Option<ContractDigestV1>,
    status: String, reason: Option<String>, request: Option<MemoryInventoryRequestV1>, plan: Option<Plan>,
    model_digest: ContractDigestV1, registry_digest: Option<ContractDigestV1>, source_cut: Option<ContractDigestV1>,
    decision: Option<Scores>, authority: bool, cost: Option<WorkerCost>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Plan {
    operation: MemoryOperationV1, required_cells: Vec<MemoryInventoryKindV1>, read_hops: u8,
    source_cut: ContractDigestV1, registry_digest: ContractDigestV1,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Scores {
    raw_operation: String, score: f64, margin: f64, score_kind: String, capability_reason: Option<String>,
    operation: Option<MemoryOperationV1>, threshold: f64, required_margin: f64,
}

impl Scores {
    fn validate(&self) -> Result<(), String> {
        if !["current", "history", "semantic", "procedure", "change", "apply", "reject"].contains(&self.raw_operation.as_str())
            || ![self.score, self.margin, self.threshold, self.required_margin].iter()
                .all(|number| number.is_finite() && (0.0..=1.01).contains(number))
            || self.score_kind.is_empty() || self.score_kind.len() > 512
            || self.capability_reason.as_ref().is_some_and(|reason| reason.len() > 1_024 || reason.contains('\0'))
        { return Err("invalid inventory address scores".to_string()); }
        Ok(())
    }
}

fn required(operation: MemoryOperationV1) -> (Vec<MemoryInventoryKindV1>, u8) {
    use MemoryInventoryKindV1::{Event, Semantic, Procedure, Hold};
    match operation {
        MemoryOperationV1::Current | MemoryOperationV1::History => (vec![Event], 1),
        MemoryOperationV1::Change => (vec![Event], 2),
        MemoryOperationV1::Semantic => (vec![Semantic], 1),
        MemoryOperationV1::Procedure => (vec![Procedure], 1),
        MemoryOperationV1::Apply => (vec![Event, Semantic, Procedure, Hold], 3),
    }
}

fn operation_name(operation: MemoryOperationV1) -> &'static str {
    match operation {
        MemoryOperationV1::Current => "current", MemoryOperationV1::History => "history",
        MemoryOperationV1::Change => "change", MemoryOperationV1::Semantic => "semantic",
        MemoryOperationV1::Procedure => "procedure", MemoryOperationV1::Apply => "apply",
    }
}

#[cfg(test)]
#[path = "memory_inventory_address_wire_tests.rs"]
mod tests;
