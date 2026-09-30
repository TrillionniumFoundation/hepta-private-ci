//! Physical resource contracts for knowledge.graph admission and execution.
//!
//! Cardinality limits remain part of the semantic schema. This module adds
//! byte, shape, deadline, cancellation, cache and publication-concurrency
//! limits so a small record count cannot hide an unbounded physical operation.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_types::StableId;

use crate::KnowledgeEdgeV2;
use crate::KnowledgeGenerationV2;
use crate::KnowledgeNodeV2;
use crate::KnowledgeProjectionInputV2;
use crate::KnowledgeRelationKindV2;
use crate::KnowledgeRelationResultV2;
use crate::KnowledgeSupportV2;

pub const MAX_KNOWLEDGE_GENERATION_BYTES_V2: u64 = 128 * 1024 * 1024;
pub const MAX_KNOWLEDGE_QUERY_OUTPUT_BYTES_V2: u64 = 8 * 1024 * 1024;
pub const MAX_KNOWLEDGE_FIELD_BYTES_V2: u64 = 16 * 1024;
pub const MAX_KNOWLEDGE_JSON_BYTES_V2: u64 = 16 * 1024 * 1024;
pub const MAX_KNOWLEDGE_JSON_DEPTH_V2: u64 = 64;
pub const MAX_KNOWLEDGE_JSON_ELEMENTS_V2: u64 = 1_000_000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum KnowledgeResourceErrorCodeV2 {
    InputBytesExceeded,
    FieldBytesExceeded,
    JsonDepthExceeded,
    JsonElementsExceeded,
    GenerationBytesExceeded,
    QueryOutputBytesExceeded,
    DeadlineExceeded,
    Cancelled,
    GlobalPublicationConcurrencyExceeded,
    TenantPublicationConcurrencyExceeded,
    CacheCapacityExceeded,
    StatePoisoned,
}

impl KnowledgeResourceErrorCodeV2 {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::InputBytesExceeded => "kg_input_bytes_exceeded",
            Self::FieldBytesExceeded => "kg_field_bytes_exceeded",
            Self::JsonDepthExceeded => "kg_json_depth_exceeded",
            Self::JsonElementsExceeded => "kg_json_elements_exceeded",
            Self::GenerationBytesExceeded => "kg_generation_bytes_exceeded",
            Self::QueryOutputBytesExceeded => "kg_query_output_bytes_exceeded",
            Self::DeadlineExceeded => "kg_deadline_exceeded",
            Self::Cancelled => "kg_cancelled",
            Self::GlobalPublicationConcurrencyExceeded => {
                "kg_global_publication_concurrency_exceeded"
            }
            Self::TenantPublicationConcurrencyExceeded => {
                "kg_tenant_publication_concurrency_exceeded"
            }
            Self::CacheCapacityExceeded => "kg_cache_capacity_exceeded",
            Self::StatePoisoned => "kg_resource_state_poisoned",
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct KnowledgeResourceErrorV2 {
    pub code: KnowledgeResourceErrorCodeV2,
    pub observed: u64,
    pub limit: u64,
    pub context: &'static str,
}

impl KnowledgeResourceErrorV2 {
    pub(crate) fn exceeded(
        code: KnowledgeResourceErrorCodeV2,
        observed: u64,
        limit: u64,
        context: &'static str,
    ) -> Self {
        Self {
            code,
            observed,
            limit,
            context,
        }
    }
}

impl fmt::Display for KnowledgeResourceErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "{}: {} observed {}, limit {}",
            self.code.as_str(),
            self.context,
            self.observed,
            self.limit
        )
    }
}

impl StdError for KnowledgeResourceErrorV2 {}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct KnowledgePhysicalLimitsV2 {
    pub maximum_input_bytes: u64,
    pub maximum_generation_bytes: u64,
    pub maximum_query_output_bytes: u64,
    pub maximum_field_bytes: u64,
}

impl Default for KnowledgePhysicalLimitsV2 {
    fn default() -> Self {
        Self {
            maximum_input_bytes: MAX_KNOWLEDGE_GENERATION_BYTES_V2,
            maximum_generation_bytes: MAX_KNOWLEDGE_GENERATION_BYTES_V2,
            maximum_query_output_bytes: MAX_KNOWLEDGE_QUERY_OUTPUT_BYTES_V2,
            maximum_field_bytes: MAX_KNOWLEDGE_FIELD_BYTES_V2,
        }
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct KnowledgePhysicalUsageV2 {
    /// Deterministic cross-host admission cost. This is not allocator RSS,
    /// SQLite page growth or wire-encoding size.
    pub canonical_bytes: u64,
    pub maximum_field_bytes: u64,
    pub node_count: u64,
    pub edge_count: u64,
    pub support_count: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct KnowledgeJsonShapeV2 {
    pub encoded_bytes: u64,
    pub maximum_depth: u64,
    pub element_count: u64,
    pub maximum_string_bytes: u64,
}

pub fn validate_json_shape_v2(shape: KnowledgeJsonShapeV2) -> Result<(), KnowledgeResourceErrorV2> {
    check_limit(
        KnowledgeResourceErrorCodeV2::InputBytesExceeded,
        shape.encoded_bytes,
        MAX_KNOWLEDGE_JSON_BYTES_V2,
        "encoded JSON bytes",
    )?;
    check_limit(
        KnowledgeResourceErrorCodeV2::JsonDepthExceeded,
        shape.maximum_depth,
        MAX_KNOWLEDGE_JSON_DEPTH_V2,
        "JSON nesting depth",
    )?;
    check_limit(
        KnowledgeResourceErrorCodeV2::JsonElementsExceeded,
        shape.element_count,
        MAX_KNOWLEDGE_JSON_ELEMENTS_V2,
        "JSON element count",
    )?;
    check_limit(
        KnowledgeResourceErrorCodeV2::FieldBytesExceeded,
        shape.maximum_string_bytes,
        MAX_KNOWLEDGE_FIELD_BYTES_V2,
        "JSON string bytes",
    )
}

pub fn measure_projection_input_v2(input: &KnowledgeProjectionInputV2) -> KnowledgePhysicalUsageV2 {
    measure_nodes_and_edges(&input.nodes, &input.edges, 96)
}

pub fn measure_generation_v2(generation: &KnowledgeGenerationV2) -> KnowledgePhysicalUsageV2 {
    measure_nodes_and_edges(&generation.nodes, &generation.edges, 144)
}

pub fn validate_projection_input_physical_limits_v2(
    input: &KnowledgeProjectionInputV2,
    limits: KnowledgePhysicalLimitsV2,
) -> Result<KnowledgePhysicalUsageV2, KnowledgeResourceErrorV2> {
    let usage = measure_projection_input_v2(input);
    validate_usage(
        usage,
        limits.maximum_input_bytes,
        limits.maximum_field_bytes,
        KnowledgeResourceErrorCodeV2::InputBytesExceeded,
        "projection input bytes",
    )?;
    Ok(usage)
}

pub fn validate_generation_physical_limits_v2(
    generation: &KnowledgeGenerationV2,
    limits: KnowledgePhysicalLimitsV2,
) -> Result<KnowledgePhysicalUsageV2, KnowledgeResourceErrorV2> {
    let usage = measure_generation_v2(generation);
    validate_usage(
        usage,
        limits.maximum_generation_bytes,
        limits.maximum_field_bytes,
        KnowledgeResourceErrorCodeV2::GenerationBytesExceeded,
        "generation canonical bytes",
    )?;
    Ok(usage)
}

pub(crate) fn measure_query_result_base_bytes_v2(query_id: &StableId) -> u64 {
    128_u64.saturating_add(id_bytes(query_id))
}

pub(crate) fn measure_query_edge_bytes_v2(
    edge: &KnowledgeEdgeV2,
    supports: &[&KnowledgeSupportV2],
) -> u64 {
    let support_bytes = supports.iter().fold(0_u64, |total, support| {
        total
            .saturating_add(id_bytes(&support.source_id))
            .saturating_add(96)
    });
    edge_identity_bytes(edge)
        .saturating_add(48)
        .saturating_add(support_bytes)
}

pub fn measure_query_result_bytes_v2(result: &KnowledgeRelationResultV2) -> u64 {
    let mut bytes = measure_query_result_base_bytes_v2(&result.query_id);
    for edge in &result.edges {
        bytes = bytes.saturating_add(edge_bytes(edge));
    }
    bytes
}

pub fn validate_query_output_physical_limits_v2(
    result: &KnowledgeRelationResultV2,
    limits: KnowledgePhysicalLimitsV2,
) -> Result<u64, KnowledgeResourceErrorV2> {
    let observed = measure_query_result_bytes_v2(result);
    check_limit(
        KnowledgeResourceErrorCodeV2::QueryOutputBytesExceeded,
        observed,
        limits.maximum_query_output_bytes,
        "query result bytes",
    )?;
    Ok(observed)
}

fn validate_usage(
    usage: KnowledgePhysicalUsageV2,
    byte_limit: u64,
    field_limit: u64,
    byte_code: KnowledgeResourceErrorCodeV2,
    context: &'static str,
) -> Result<(), KnowledgeResourceErrorV2> {
    check_limit(byte_code, usage.canonical_bytes, byte_limit, context)?;
    check_limit(
        KnowledgeResourceErrorCodeV2::FieldBytesExceeded,
        usage.maximum_field_bytes,
        field_limit,
        "maximum stable-id field bytes",
    )
}

fn check_limit(
    code: KnowledgeResourceErrorCodeV2,
    observed: u64,
    limit: u64,
    context: &'static str,
) -> Result<(), KnowledgeResourceErrorV2> {
    if observed > limit {
        Err(KnowledgeResourceErrorV2::exceeded(
            code, observed, limit, context,
        ))
    } else {
        Ok(())
    }
}

fn measure_nodes_and_edges(
    nodes: &[KnowledgeNodeV2],
    edges: &[KnowledgeEdgeV2],
    fixed_bytes: u64,
) -> KnowledgePhysicalUsageV2 {
    let mut usage = KnowledgePhysicalUsageV2 {
        canonical_bytes: fixed_bytes,
        node_count: usize_to_u64(nodes.len()),
        edge_count: usize_to_u64(edges.len()),
        ..KnowledgePhysicalUsageV2::default()
    };
    for node in nodes {
        observe_field(&mut usage, &node.node_id);
        observe_field(&mut usage, &node.node_kind_id);
        usage.canonical_bytes = usage
            .canonical_bytes
            .saturating_add(id_bytes(&node.node_id))
            .saturating_add(id_bytes(&node.node_kind_id))
            .saturating_add(40);
        observe_supports(&mut usage, &node.supports);
    }
    for edge in edges {
        observe_field(&mut usage, &edge.identity.source_node_id);
        observe_field(&mut usage, &edge.identity.target_node_id);
        if let KnowledgeRelationKindV2::Custom(identifier) = &edge.identity.relation {
            observe_field(&mut usage, identifier);
        }
        usage.canonical_bytes = usage
            .canonical_bytes
            .saturating_add(edge_identity_bytes(edge))
            .saturating_add(48);
        observe_supports(&mut usage, &edge.supports);
    }
    usage
}

fn observe_supports(usage: &mut KnowledgePhysicalUsageV2, supports: &[KnowledgeSupportV2]) {
    usage.support_count = usage
        .support_count
        .saturating_add(usize_to_u64(supports.len()));
    for support in supports {
        observe_field(usage, &support.source_id);
        usage.canonical_bytes = usage
            .canonical_bytes
            .saturating_add(id_bytes(&support.source_id))
            .saturating_add(96);
    }
}

fn observe_field(usage: &mut KnowledgePhysicalUsageV2, value: &StableId) {
    usage.maximum_field_bytes = usage
        .maximum_field_bytes
        .max(usize_to_u64(value.as_str().len()));
}

fn edge_bytes(edge: &KnowledgeEdgeV2) -> u64 {
    let support_bytes = edge.supports.iter().fold(0_u64, |total, support| {
        total
            .saturating_add(id_bytes(&support.source_id))
            .saturating_add(96)
    });
    edge_identity_bytes(edge)
        .saturating_add(48)
        .saturating_add(support_bytes)
}

fn edge_identity_bytes(edge: &KnowledgeEdgeV2) -> u64 {
    id_bytes(&edge.identity.source_node_id)
        .saturating_add(relation_bytes(&edge.identity.relation))
        .saturating_add(id_bytes(&edge.identity.target_node_id))
}

fn relation_bytes(relation: &KnowledgeRelationKindV2) -> u64 {
    match relation {
        KnowledgeRelationKindV2::Custom(identifier) => 1_u64.saturating_add(id_bytes(identifier)),
        _ => 1,
    }
}

fn id_bytes(value: &StableId) -> u64 {
    8_u64.saturating_add(usize_to_u64(value.as_str().len()))
}

fn usize_to_u64(value: usize) -> u64 {
    u64::try_from(value).unwrap_or(u64::MAX)
}

#[derive(Clone, Debug, Default)]
pub struct KnowledgeCancellationV2 {
    cancelled: Arc<AtomicBool>,
}

impl KnowledgeCancellationV2 {
    pub fn cancel(&self) {
        self.cancelled.store(true, Ordering::Release);
    }

    pub fn is_cancelled(&self) -> bool {
        self.cancelled.load(Ordering::Acquire)
    }
}

#[derive(Clone, Debug)]
pub struct KnowledgeOperationGuardV2 {
    deadline: Option<Instant>,
    cancellation: KnowledgeCancellationV2,
}

impl KnowledgeOperationGuardV2 {
    pub fn unbounded(cancellation: KnowledgeCancellationV2) -> Self {
        Self {
            deadline: None,
            cancellation,
        }
    }

    pub fn with_timeout(timeout: Duration, cancellation: KnowledgeCancellationV2) -> Self {
        let now = Instant::now();
        Self {
            deadline: Some(now.checked_add(timeout).unwrap_or(now)),
            cancellation,
        }
    }

    pub fn with_deadline(deadline: Instant, cancellation: KnowledgeCancellationV2) -> Self {
        Self {
            deadline: Some(deadline),
            cancellation,
        }
    }

    pub fn checkpoint(&self) -> Result<(), KnowledgeResourceErrorV2> {
        if self.cancellation.is_cancelled() {
            return Err(KnowledgeResourceErrorV2::exceeded(
                KnowledgeResourceErrorCodeV2::Cancelled,
                1,
                0,
                "operation cancellation",
            ));
        }
        if self
            .deadline
            .is_some_and(|deadline| Instant::now() >= deadline)
        {
            return Err(KnowledgeResourceErrorV2::exceeded(
                KnowledgeResourceErrorCodeV2::DeadlineExceeded,
                1,
                0,
                "absolute operation deadline",
            ));
        }
        Ok(())
    }
}

#[derive(Default)]
struct PublicationLimiterState {
    global: u32,
    tenants: BTreeMap<String, u32>,
}

pub struct KnowledgePublicationLimiterV2 {
    global_limit: u32,
    per_tenant_limit: u32,
    state: Mutex<PublicationLimiterState>,
}

impl KnowledgePublicationLimiterV2 {
    pub fn new(global_limit: u32, per_tenant_limit: u32) -> Self {
        Self {
            global_limit,
            per_tenant_limit,
            state: Mutex::new(PublicationLimiterState::default()),
        }
    }

    pub fn try_acquire<'a>(
        &'a self,
        tenant: &StableId,
    ) -> Result<KnowledgePublicationPermitV2<'a>, KnowledgeResourceErrorV2> {
        let mut state = self.state.lock().map_err(|_| {
            KnowledgeResourceErrorV2::exceeded(
                KnowledgeResourceErrorCodeV2::StatePoisoned,
                1,
                0,
                "publication limiter mutex",
            )
        })?;
        if state.global >= self.global_limit {
            return Err(KnowledgeResourceErrorV2::exceeded(
                KnowledgeResourceErrorCodeV2::GlobalPublicationConcurrencyExceeded,
                u64::from(state.global).saturating_add(1),
                u64::from(self.global_limit),
                "concurrent publications",
            ));
        }
        let tenant_key = tenant.as_str().to_string();
        let tenant_count = state.tenants.get(&tenant_key).copied().unwrap_or(0);
        if tenant_count >= self.per_tenant_limit {
            return Err(KnowledgeResourceErrorV2::exceeded(
                KnowledgeResourceErrorCodeV2::TenantPublicationConcurrencyExceeded,
                u64::from(tenant_count).saturating_add(1),
                u64::from(self.per_tenant_limit),
                "concurrent tenant publications",
            ));
        }
        state.global = state.global.saturating_add(1);
        state
            .tenants
            .insert(tenant_key.clone(), tenant_count.saturating_add(1));
        Ok(KnowledgePublicationPermitV2 {
            limiter: self,
            tenant: tenant_key,
            released: false,
        })
    }

    fn release(&self, tenant: &str) {
        let Ok(mut state) = self.state.lock() else {
            return;
        };
        state.global = state.global.saturating_sub(1);
        let remove_tenant = if let Some(count) = state.tenants.get_mut(tenant) {
            *count = count.saturating_sub(1);
            *count == 0
        } else {
            false
        };
        if remove_tenant {
            state.tenants.remove(tenant);
        }
    }
}

pub struct KnowledgePublicationPermitV2<'a> {
    limiter: &'a KnowledgePublicationLimiterV2,
    tenant: String,
    released: bool,
}

impl KnowledgePublicationPermitV2<'_> {
    pub fn release(mut self) {
        if !self.released {
            self.limiter.release(&self.tenant);
            self.released = true;
        }
    }
}

impl fmt::Debug for KnowledgePublicationPermitV2<'_> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("KnowledgePublicationPermitV2")
            .field("tenant", &self.tenant)
            .field("released", &self.released)
            .finish_non_exhaustive()
    }
}

impl Drop for KnowledgePublicationPermitV2<'_> {
    fn drop(&mut self) {
        if !self.released {
            self.limiter.release(&self.tenant);
            self.released = true;
        }
    }
}

#[path = "generation_cache.rs"]
mod generation_cache;
pub use generation_cache::KnowledgeCacheErrorV2;
pub use generation_cache::KnowledgeGenerationCacheMetricsV2;
pub use generation_cache::KnowledgeGenerationCacheV2;

#[cfg(test)]
#[path = "resource_tests.rs"]
mod tests;
