//! Residual inventory reads within the existing Agentd lifecycle and owners.

use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use codex_hepta_cognitive_store::{DurableCognitiveStore, InventoryCellOwnerSnapshotV1};
use codex_hepta_cognitive_types::{InventoryCellReadoutV1, InventoryCellRequestV1, InventoryCellRouteV1, MemoryPredictionKindV1, MemoryReadStatusV1, MemoryReadoutV1};
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_memory::{CognitiveAccess, CognitiveScope};
use serde_json::Value;
use crate::{AgentdError, LoadedInventoryCellBundleV1};
use crate::memory_cell_release::TypedMemoryCellReleaseHostV1;
use crate::memory_cell_release::MemoryCellReleaseBundleV1;

#[path = "inventory_cell_execution.rs"]
mod execution;
#[path = "inventory_cell_snapshot.rs"]
pub(crate) mod snapshot;

pub type InventoryCellReleaseHostV1 = TypedMemoryCellReleaseHostV1<LoadedInventoryCellBundleV1>;

/// Configured resolvers bind their exact model and the acquired owner cut.
/// The control request contains neither an operation label nor source authority.
pub trait InventoryCellAddressResolverV1: Send + Sync {
    fn model_digest(&self) -> ContractDigestV1;
    fn resolve<'a>(
        &'a self,
        request: &'a InventoryCellRequestV1,
        snapshot: &'a InventoryCellOwnerSnapshotV1,
    ) -> Pin<Box<dyn Future<Output = Result<Option<InventoryCellResolvedAddressV1>, String>> + Send + 'a>>;
}

#[derive(Clone, Debug)]
pub struct InventoryCellResolvedAddressV1 {
    pub request: InventoryCellRequestV1,
    pub route: InventoryCellRouteV1,
    pub owner_cut_digest: ContractDigestV1,
    pub model_digest: ContractDigestV1,
}

/// Startup configuration is trusted locally; it cannot be supplied over the
/// request wire. All facts, revisions and holds stay in the real cognitive owner.
pub struct AgentdInventoryCellRuntimeV1 {
    owner_agent_id: AgentId,
    spawn_generation: u64,
    scope: CognitiveScope,
    access: CognitiveAccess,
    release: Arc<InventoryCellReleaseHostV1>,
    resolver: Arc<dyn InventoryCellAddressResolverV1>,
    resolver_digest: ContractDigestV1,
}

impl AgentdInventoryCellRuntimeV1 {
    pub fn new(
        owner_agent_id: AgentId,
        spawn_generation: u64,
        scope: CognitiveScope,
        release: Arc<InventoryCellReleaseHostV1>,
        resolver: Arc<dyn InventoryCellAddressResolverV1>,
    ) -> Result<Self, AgentdError> {
        if spawn_generation == 0 {
            return Err(AgentdError::Invalid("inventory host generation is zero".to_string()));
        }
        let access = match &scope {
            CognitiveScope::AgentPrivate => CognitiveAccess::agent_private(owner_agent_id.clone()),
            CognitiveScope::WorkspacePrivate { workspace_sha256 } => CognitiveAccess::workspace_private(owner_agent_id.clone(), workspace_sha256.clone()),
        };
        let resolver_digest = resolver.model_digest();
        Ok(Self { owner_agent_id, spawn_generation, scope, access, release, resolver, resolver_digest })
    }

    pub(crate) fn require_identity(&self, owner: &AgentId, generation: u64, workspace: &std::path::Path) -> Result<(), AgentdError> {
        if owner != &self.owner_agent_id || generation != self.spawn_generation {
            return Err(AgentdError::GenerationFenced("inventory host identity differs from Agentd".to_string()));
        }
        if let CognitiveScope::WorkspacePrivate { workspace_sha256 } = &self.scope
            && *workspace_sha256 != codex_hepta_memory::workspace_binding_digest(workspace)
        {
            return Err(AgentdError::GenerationFenced("inventory scope differs from Agentd workspace".to_string()));
        }
        Ok(())
    }

    pub(crate) fn access(&self) -> &CognitiveAccess { &self.access }
    pub(crate) fn scope(&self) -> &CognitiveScope { &self.scope }

    pub async fn read(&self, store: &DurableCognitiveStore, request: &InventoryCellRequestV1) -> Result<InventoryCellReadoutV1, AgentdError> {
        request.validate().map_err(|error| AgentdError::Invalid(error.to_string()))?;
        if store.owner_agent_id() != &self.owner_agent_id {
            return Err(AgentdError::GenerationFenced("inventory store owner differs from host".to_string()));
        }
        let started = Instant::now();
        let bundle = self.release.load_current().map_err(|_| AgentdError::Protocol("selected inventory release unavailable".to_string()))?;
        let result = match tokio::time::timeout(Duration::from_secs(5), self.read_bound(store, request, &bundle)).await {
            Ok(result) => result,
            Err(_) => Err(unavailable("inventory read deadline exceeded")),
        };
        let mut readout = match result {
            Ok(readout) => readout,
            Err((status, reason)) => failed(request, &bundle, status, reason),
        };
        readout.result.elapsed_seconds = started.elapsed().as_secs_f64();
        readout.validate().map_err(|error| AgentdError::Protocol(error.to_string()))?;
        Ok(readout)
    }

    async fn read_bound(&self, store: &DurableCognitiveStore, request: &InventoryCellRequestV1, bundle: &LoadedInventoryCellBundleV1) -> Result<InventoryCellReadoutV1, ReadFailure> {
        let acquired = store.inventory_cell_snapshot(&self.access, &self.scope, now()?).await
            .map_err(|_| unavailable("canonical inventory owner unavailable"))?;
        if request.scope != *acquired.scope() {
            return Err((MemoryReadStatusV1::Abstain, "inventory request scope differs from authenticated owner"));
        }
        bundle.validate_owner_snapshot(&acquired).map_err(|_| (MemoryReadStatusV1::Stale, "inventory bundle differs from current source lineage"))?;
        if self.resolver.model_digest() != self.resolver_digest {
            return Err(unavailable("inventory resolver model changed"));
        }
        let decision = self.resolver.resolve(request, &acquired).await
            .map_err(|_| unavailable("inventory address resolver unavailable"))?
            .ok_or((MemoryReadStatusV1::Abstain, "inventory address resolver declined question"))?;
        if decision.request != *request || decision.owner_cut_digest != acquired.owner_cut_digest() || decision.model_digest != self.resolver_digest {
            return Err(unavailable("inventory address decision differs from request or owner binding"));
        }
        decision.route.validate().map_err(|_| unavailable("inventory resolver returned an invalid dual address"))?;
        let readout = execution::execute(request, &decision.route, bundle, &acquired)?;
        self.release.revalidate(bundle).map_err(|_| (MemoryReadStatusV1::Stale, "inventory publication changed before use"))?;
        store.revalidate_inventory_cell_readout(&self.access, &self.scope, &acquired, request, &readout, bundle.generation(), bundle.bundle_digest(), now()?).await
            .map_err(|_| (MemoryReadStatusV1::Stale, "inventory source owner changed before use"))?;
        Ok(readout)
    }
}

type ReadFailure = (MemoryReadStatusV1, &'static str);
fn unavailable(reason: &'static str) -> ReadFailure { (MemoryReadStatusV1::Unavailable, reason) }
fn now() -> Result<i64, ReadFailure> {
    let seconds = SystemTime::now().duration_since(UNIX_EPOCH).map_err(|_| unavailable("inventory host clock unavailable"))?.as_secs();
    i64::try_from(seconds).map_err(|_| unavailable("inventory host clock overflow"))
}
fn failed(request: &InventoryCellRequestV1, bundle: &LoadedInventoryCellBundleV1, status: MemoryReadStatusV1, reason: &str) -> InventoryCellReadoutV1 {
    InventoryCellReadoutV1 {
        schema: "hepta.memory.inventory-readout.v1".to_string(), route: None,
        result: MemoryReadoutV1 {
            schema: "hepta.memory.readout.v1".to_string(), query_id: request.query_id.clone(), operation: None,
            status, value: Value::Null, source_ids: Vec::new(), generation: bundle.generation(), snapshot_digest: bundle.bundle_digest(),
            prediction_kind: MemoryPredictionKindV1::None, cell_digests: Vec::new(), hops: 0, elapsed_seconds: 0.0, reason: Some(reason.to_string()),
        },
    }
}
