//! Residual inventory profile on the existing owner and Agentd control host.

use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_cognitive_store::DurableCognitiveStore;
use codex_hepta_cognitive_store::MemoryInventoryOwnerSnapshotV1;
use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_cognitive_types::MemoryPredictionKindV1;
use codex_hepta_cognitive_types::MemoryReadStatusV1;
use codex_hepta_cognitive_types::MemoryInventoryReadoutV1;
use codex_hepta_cognitive_types::MemoryInventoryRequestV1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use serde_json::Value;

use crate::AgentdError;
use crate::memory_cell_runtime::now_unix_seconds;
use crate::LoadedMemoryInventoryBundleV1;
use crate::MemoryInventoryReleaseHostV1;

#[path = "memory_inventory_execution.rs"]
mod execution;
#[path = "memory_inventory_snapshot.rs"]
pub(crate) mod snapshot;

/// A configured resolver is trusted to execute its pinned addressing model.
/// Callers supply no operation, answer, registry or source authority on the wire.
pub trait MemoryInventoryAddressResolverV1: Send + Sync {
    fn model_digest(&self) -> ContractDigestV1;

    fn resolve<'a>(
        &'a self,
        request: &'a MemoryInventoryRequestV1,
        snapshot: &'a MemoryInventoryOwnerSnapshotV1,
    ) -> Pin<
        Box<dyn Future<Output = Result<Option<MemoryInventoryResolvedAddressV1>, String>> + Send + 'a>,
    >;
}

#[derive(Clone, Debug)]
pub struct MemoryInventoryResolvedAddressV1 {
    pub request: MemoryInventoryRequestV1,
    pub operation: MemoryOperationV1,
    pub owner_cut_digest: ContractDigestV1,
    pub model_digest: ContractDigestV1,
}

/// Explicit startup configuration, never constructed from request JSON. The
/// canonical SQLite owner remains the only source of facts and freshness.
pub struct AgentdMemoryInventoryRuntimeV1 {
    owner_agent_id: AgentId,
    spawn_generation: u64,
    scope: CognitiveScope,
    access: CognitiveAccess,
    release: Arc<MemoryInventoryReleaseHostV1>,
    resolver: Arc<dyn MemoryInventoryAddressResolverV1>,
    resolver_digest: ContractDigestV1,
}

impl AgentdMemoryInventoryRuntimeV1 {
    pub fn new(
        owner_agent_id: AgentId,
        spawn_generation: u64,
        scope: CognitiveScope,
        release: Arc<MemoryInventoryReleaseHostV1>,
        resolver: Arc<dyn MemoryInventoryAddressResolverV1>,
    ) -> Result<Self, AgentdError> {
        if spawn_generation == 0 {
            return Err(AgentdError::Invalid(
                "memory inventory host generation is zero".to_string(),
            ));
        }
        let access = match &scope {
            CognitiveScope::AgentPrivate => CognitiveAccess::agent_private(owner_agent_id.clone()),
            CognitiveScope::WorkspacePrivate { workspace_sha256 } => {
                CognitiveAccess::workspace_private(owner_agent_id.clone(), workspace_sha256.clone())
            }
        };
        let resolver_digest = resolver.model_digest();
        Ok(Self {
            owner_agent_id,
            spawn_generation,
            scope,
            access,
            release,
            resolver,
            resolver_digest,
        })
    }

    pub(crate) fn require_identity(
        &self,
        owner: &AgentId,
        generation: u64,
        workspace: &std::path::Path,
    ) -> Result<(), AgentdError> {
        if owner != &self.owner_agent_id || generation != self.spawn_generation {
            return Err(AgentdError::GenerationFenced(
                "memory inventory host identity differs from Agentd".to_string(),
            ));
        }
        if let CognitiveScope::WorkspacePrivate { workspace_sha256 } = &self.scope
            && *workspace_sha256 != codex_hepta_memory::workspace_binding_digest(workspace)
        {
            return Err(AgentdError::GenerationFenced(
                "memory inventory scope differs from Agentd workspace".to_string(),
            ));
        }
        Ok(())
    }

    pub(crate) fn access(&self) -> &CognitiveAccess {
        &self.access
    }
    pub(crate) fn scope(&self) -> &CognitiveScope {
        &self.scope
    }

    /// A successful return is checked against the publication owner and the
    /// source owner immediately before exposure. Every failed readout is empty.
    pub async fn read(
        &self,
        store: &DurableCognitiveStore,
        request: &MemoryInventoryRequestV1,
    ) -> Result<MemoryInventoryReadoutV1, AgentdError> {
        request
            .validate()
            .map_err(|error| AgentdError::Invalid(error.to_string()))?;
        if store.owner_agent_id() != &self.owner_agent_id {
            return Err(AgentdError::GenerationFenced(
                "memory inventory store owner differs from host".to_string(),
            ));
        }
        let started = Instant::now();
        let bundle = self.release.load_current().map_err(|_| {
            AgentdError::Protocol("selected memory inventory release is unavailable".to_string())
        })?;
        let mut readout = failed(
            request,
            &bundle,
            MemoryReadStatusV1::Unavailable,
            "memory inventory read unavailable",
        );
        let result = match tokio::time::timeout(
            Duration::from_secs(5),
            self.read_bound(store, request, &bundle),
        )
        .await
        {
            Ok(result) => result,
            Err(_) => Err(unavailable("memory inventory read deadline exceeded")),
        };
        match result {
            Ok(value) => readout = value,
            Err((status, reason)) => {
                readout.status = status;
                readout.reason = Some(reason.to_string());
            }
        }
        readout.elapsed_seconds = started.elapsed().as_secs_f64();
        readout
            .validate()
            .map_err(|error| AgentdError::Protocol(error.to_string()))?;
        Ok(readout)
    }

    async fn read_bound(
        &self,
        store: &DurableCognitiveStore,
        request: &MemoryInventoryRequestV1,
        bundle: &LoadedMemoryInventoryBundleV1,
    ) -> Result<MemoryInventoryReadoutV1, ReadFailure> {
        let now = now_unix_seconds().map_err(|_| unavailable("host clock is unavailable"))?;
        let acquired = store
            .memory_inventory_snapshot(&self.access, &self.scope, now)
            .await
            .map_err(|_| unavailable("canonical memory inventory owner is unavailable"))?;
        if request.scope != *acquired.scope() {
            return Err((
                MemoryReadStatusV1::Abstain,
                "request scope differs from authenticated owner scope",
            ));
        }
        bundle.validate_owner_snapshot(&acquired).map_err(|_| {
            (
                MemoryReadStatusV1::Stale,
                "selected memory inventory bundle lineage differs from the owner cut",
            )
        })?;
        if self.resolver.model_digest() != self.resolver_digest {
            return Err(unavailable("configured address resolver changed its model"));
        }
        let decision = self
            .resolver
            .resolve(request, &acquired)
            .await
            .map_err(|_| unavailable("configured address resolver is unavailable"))?
            .ok_or((
                MemoryReadStatusV1::Abstain,
                "address resolver declined the request",
            ))?;
        if decision.request != *request
            || decision.owner_cut_digest != acquired.owner_cut_digest()
            || decision.model_digest != self.resolver_digest
        {
            return Err(unavailable(
                "address decision differs from its request or owner binding",
            ));
        }
        let readout = execution::execute(request, decision.operation, bundle, &acquired)?;
        self.release.revalidate(bundle).map_err(|_| {
            (
                MemoryReadStatusV1::Stale,
                "memory inventory publication changed before final use",
            )
        })?;
        let now = now_unix_seconds().map_err(|_| unavailable("host clock is unavailable"))?;
        store
            .revalidate_memory_inventory_readout(
                &self.access,
                &self.scope,
                &acquired,
                request,
                &readout,
                bundle.generation(),
                bundle.bundle_digest(),
                now,
            )
            .await
            .map_err(|_| {
                (
                    MemoryReadStatusV1::Stale,
                    "memory inventory source owner changed before final use",
                )
            })?;
        Ok(readout)
    }
}

type ReadFailure = (MemoryReadStatusV1, &'static str);

fn unavailable(reason: &'static str) -> ReadFailure {
    (MemoryReadStatusV1::Unavailable, reason)
}

fn failed(
    request: &MemoryInventoryRequestV1,
    bundle: &LoadedMemoryInventoryBundleV1,
    status: MemoryReadStatusV1,
    reason: &str,
) -> MemoryInventoryReadoutV1 {
    MemoryInventoryReadoutV1 {
        schema: "hepta.memory.inventory-readout.v1".to_string(),
        query_id: request.query_id.clone(),
        operation: None,
        status,
        value: Value::Null,
        source_ids: Vec::new(),
        generation: bundle.generation(),
        snapshot_digest: bundle.bundle_digest(),
        prediction_kind: MemoryPredictionKindV1::None,
        cell_digests: Vec::new(),
        hops: 0,
        elapsed_seconds: 0.0,
        reason: Some(reason.to_string()),
    }
}

