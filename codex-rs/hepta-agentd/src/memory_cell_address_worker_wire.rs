//! Exact Python-worker wire shapes and canonical, authority-free binding checks.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_cognitive_store::MemoryCellOwnerSnapshotV1;
use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_cognitive_types::MemoryRequestV1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;

use super::time_view::TimeView;
use crate::MemoryCellResolvedAddressV1;

pub(super) const MAX_REQUEST_FRAME: usize = 2_097_152;
pub(super) const MAX_RESPONSE_BODY: usize = 32_768;

#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct AddressRequest {
    query_id: ContractIdV1,
    scope: ContractIdV1,
    entity: ContractIdV1,
    text: String,
    at: u64,
    since: u64,
    max_hops: u8,
    max_cells: u8,
}

impl From<&MemoryRequestV1> for AddressRequest {
    fn from(value: &MemoryRequestV1) -> Self {
        Self {
            query_id: value.query_id.clone(),
            scope: value.scope.clone(),
            entity: value.entity.clone(),
            text: value.text.clone(),
            at: value.at,
            since: value.since,
            max_hops: value.max_hops,
            max_cells: value.max_cells,
        }
    }
}

pub(super) struct BoundRequest {
    pub bytes: Vec<u8>,
    pub digest: ContractDigestV1,
    pub registry_digest: ContractDigestV1,
    pub source_cut: ContractDigestV1,
    request: AddressRequest,
    time_view: TimeView,
}

impl BoundRequest {
    pub fn build(
        request: &MemoryRequestV1,
        owner: &MemoryCellOwnerSnapshotV1,
        aliases: &BTreeMap<ContractIdV1, Vec<String>>,
    ) -> Result<Self, String> {
        request
            .validate()
            .map_err(|_| "invalid typed address request".to_string())?;
        if request.scope != *owner.scope() {
            return Err("address request is outside the owner scope".to_string());
        }
        let entities: BTreeSet<_> = owner
            .records()
            .iter()
            .filter(|row| owner.current_source_ids().contains(&row.source_id))
            .map(|row| row.record.entity.clone())
            .collect();
        if entities.is_empty() || entities.len() > 4_096 {
            return Err("owner address registry size is invalid".to_string());
        }
        let registry = serde_json::json!({
            "schema": "hepta.memory.v7.owner-registry.v1", "scope": owner.scope(), "source_cut": owner.owner_cut_digest(),
            "entities": entities.iter().map(|entity| serde_json::json!({"entity": entity,
                "aliases": aliases.get(entity).cloned().unwrap_or_default()})).collect::<Vec<_>>()
        });
        let time_view = TimeView::build(request, &entities, aliases)?;
        let mut request = AddressRequest::from(request);
        request.at = time_view.at;
        request.since = time_view.since;
        let request_value =
            serde_json::to_value(&request).map_err(|_| "address encoding failed".to_string())?;
        let digest = hash(&canonical(&request_value)?);
        let registry_digest = hash(&canonical(&registry)?);
        let source_cut = owner.owner_cut_digest();
        let mut bytes = canonical(
            &serde_json::json!({"schema": "hepta.memory.v7.address-worker-request.v1", "request": request_value, "registry": registry}),
        )?;
        bytes.push(b'\n');
        if bytes.len() > MAX_REQUEST_FRAME {
            return Err("address worker request exceeds frame bound".to_string());
        }
        Ok(Self {
            bytes,
            digest,
            registry_digest,
            source_cut,
            request,
            time_view,
        })
    }

    pub fn validate_response(
        &self,
        bytes: &[u8],
        model: ContractDigestV1,
        original: &MemoryRequestV1,
    ) -> Result<(Option<MemoryCellResolvedAddressV1>, WorkerCost), String> {
        self.time_view.verify_original(original)?;
        let decision: WorkerDecision = serde_json::from_slice(bytes)
            .map_err(|_| "invalid or duplicate address worker response fields".to_string())?;
        let shape: Value = serde_json::from_slice(bytes)
            .map_err(|_| "invalid address worker response JSON".to_string())?;
        if shape.as_object().is_none_or(|object| object.len() != 13)
            || shape.get("decision").is_some_and(|scores| {
                !scores.is_null() && scores.as_object().is_none_or(|object| object.len() != 8)
            })
        {
            return Err("address decision omitted required nullable fields".to_string());
        }
        if decision.schema != "hepta.memory.v7.address-decision.v1"
            || decision.authority
            || decision.query_id.as_ref() != Some(&original.query_id)
            || decision.request_digest != Some(self.digest)
            || decision.model_digest != model
            || decision.registry_digest != Some(self.registry_digest)
            || decision.source_cut != Some(self.source_cut)
        {
            return Err(
                "address decision binding differs from request, model or owner registry"
                    .to_string(),
            );
        }
        let cost = decision
            .cost
            .ok_or_else(|| "address decision lacks bounded processing cost".to_string())?;
        if cost.request_body_bytes != self.bytes.len() - 1
            || !cost.processing_wall_seconds.is_finite()
            || !cost.processing_cpu_seconds.is_finite()
            || !(0.0..=120.0).contains(&cost.processing_wall_seconds)
            || !(0.0..=120.0).contains(&cost.processing_cpu_seconds)
        {
            return Err("address decision processing cost is invalid".to_string());
        }
        if let Some(scores) = &decision.decision {
            scores.validate()?;
        }
        match decision.status {
            WorkerStatus::Accepted => {
                let plan = decision
                    .plan
                    .ok_or_else(|| "accepted address lacks a typed plan".to_string())?;
                let scores = decision
                    .decision
                    .ok_or_else(|| "accepted address lacks a pinned model decision".to_string())?;
                if decision.reason.is_some()
                    || decision.request.as_ref() != Some(&self.request)
                    || plan.source_cut != self.source_cut
                    || plan.registry_digest != self.registry_digest
                    || scores.operation != Some(plan.operation)
                    || scores.raw_operation != operation_name(plan.operation)
                    || scores.score < scores.threshold
                    || scores.margin < scores.required_margin
                    || scores.capability_reason.is_some()
                {
                    return Err(
                        "accepted address plan differs from the original request or model decision"
                            .to_string(),
                    );
                }
                let (cells, hops) = match plan.operation {
                    MemoryOperationV1::Current | MemoryOperationV1::History => {
                        (vec![MemoryCellKindV1::Event], 1)
                    }
                    MemoryOperationV1::Change => (vec![MemoryCellKindV1::Event], 2),
                    MemoryOperationV1::Semantic => (vec![MemoryCellKindV1::Semantic], 1),
                    MemoryOperationV1::Procedure => (vec![MemoryCellKindV1::Procedure], 1),
                    MemoryOperationV1::Apply => (
                        vec![
                            MemoryCellKindV1::Event,
                            MemoryCellKindV1::Semantic,
                            MemoryCellKindV1::Procedure,
                        ],
                        3,
                    ),
                };
                if plan.required_cells != cells
                    || plan.read_hops != hops
                    || hops > original.max_hops
                    || cells.len() > usize::from(original.max_cells)
                {
                    return Err(
                        "address plan cell or hop semantics exceed the typed request".to_string(),
                    );
                }
                if !self.time_view.permits(original, plan.operation) {
                    return Ok((None, cost));
                }
                Ok((
                    Some(MemoryCellResolvedAddressV1 {
                        request: original.clone(),
                        operation: plan.operation,
                        owner_cut_digest: self.source_cut,
                        model_digest: model,
                    }),
                    cost,
                ))
            }
            WorkerStatus::Rejected | WorkerStatus::Unavailable => {
                if decision.request.is_some()
                    || decision.plan.is_some()
                    || decision.reason.as_ref().is_none_or(|reason| {
                        reason.is_empty() || reason.len() > 1_024 || reason.contains('\0')
                    })
                {
                    return Err(
                        "failed address decision contains a partial plan or lacks a reason"
                            .to_string(),
                    );
                }
                if decision.status == WorkerStatus::Unavailable {
                    return Err("address worker reported unavailable".to_string());
                }
                Ok((None, cost))
            }
        }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct WorkerReady {
    pub schema: String,
    pub model_digest: ContractDigestV1,
    pub policy_digest: ContractDigestV1,
    pub max_frame_bytes: usize,
    pub max_response_bytes: usize,
}

#[derive(Clone, Copy, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
enum WorkerStatus {
    Accepted,
    Rejected,
    Unavailable,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct WorkerDecision {
    schema: String,
    query_id: Option<ContractIdV1>,
    request_digest: Option<ContractDigestV1>,
    status: WorkerStatus,
    reason: Option<String>,
    request: Option<AddressRequest>,
    plan: Option<WorkerPlan>,
    model_digest: ContractDigestV1,
    registry_digest: Option<ContractDigestV1>,
    source_cut: Option<ContractDigestV1>,
    decision: Option<WorkerScores>,
    authority: bool,
    cost: Option<WorkerCost>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct WorkerPlan {
    operation: MemoryOperationV1,
    required_cells: Vec<MemoryCellKindV1>,
    read_hops: u8,
    source_cut: ContractDigestV1,
    registry_digest: ContractDigestV1,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct WorkerScores {
    raw_operation: String,
    score: f64,
    margin: f64,
    score_kind: String,
    capability_reason: Option<String>,
    operation: Option<MemoryOperationV1>,
    threshold: f64,
    required_margin: f64,
}

impl WorkerScores {
    fn validate(&self) -> Result<(), String> {
        if ![
            "current",
            "history",
            "semantic",
            "procedure",
            "change",
            "apply",
            "reject",
        ]
        .contains(&self.raw_operation.as_str())
            || ![
                self.score,
                self.margin,
                self.threshold,
                self.required_margin,
            ]
            .iter()
            .all(|number| number.is_finite() && (0.0..=1.01).contains(number))
            || self.score_kind.is_empty()
            || self.score_kind.len() > 512
            || self
                .capability_reason
                .as_ref()
                .is_some_and(|reason| reason.len() > 1_024 || reason.contains('\0'))
        {
            return Err("address model score envelope is invalid".to_string());
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct WorkerCost {
    pub request_body_bytes: usize,
    pub processing_wall_seconds: f64,
    pub processing_cpu_seconds: f64,
}

pub(super) fn canonical(value: &Value) -> Result<Vec<u8>, String> {
    fn sorted(value: &Value) -> Value {
        match value {
            Value::Object(items) => {
                let ordered: BTreeMap<_, _> = items
                    .iter()
                    .map(|(key, value)| (key.clone(), sorted(value)))
                    .collect();
                Value::Object(ordered.into_iter().collect())
            }
            Value::Array(items) => Value::Array(items.iter().map(sorted).collect()),
            _ => value.clone(),
        }
    }
    serde_json::to_vec(&sorted(value))
        .map_err(|_| "address canonical JSON encoding failed".to_string())
}

pub(super) fn hash(bytes: &[u8]) -> ContractDigestV1 {
    ContractDigestV1::from_digest(Digest32::of_bytes(bytes))
        .expect("SHA-256 of bounded wire has a nonzero digest")
}

fn operation_name(operation: MemoryOperationV1) -> &'static str {
    match operation {
        MemoryOperationV1::Current => "current",
        MemoryOperationV1::History => "history",
        MemoryOperationV1::Semantic => "semantic",
        MemoryOperationV1::Procedure => "procedure",
        MemoryOperationV1::Change => "change",
        MemoryOperationV1::Apply => "apply",
    }
}
