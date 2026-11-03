//! Real Agentd transport with the existing fleet and federation fences.

use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Instant;

use codex_hepta_agent_protocol::MEMORY_CELL_CONTROL_CAPABILITY_V1;
use codex_hepta_cognitive_types::MemoryReadStatusV1;
use codex_hepta_cognitive_types::MemoryReadoutV1;
use codex_hepta_cognitive_types::MemoryRequestV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentRecord;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::workspace_binding_digest;
use codex_hepta_types::StableId;

use crate::AgentdClient;
use crate::MemoryFederationCapabilityId;
use crate::MemoryFederationCapabilityState;
use crate::MemoryFederationScopeKind;

use super::bindings::MemoryCellDeploymentV1;
use super::bindings::MemoryCellNetworkCostV1;
use super::bindings::MemoryCellNodeBindingV1;
use super::bindings::MemoryCellNodeReadoutV1;

struct PeerAttempt {
    binding: MemoryCellNodeBindingV1,
    client: AgentdClient,
}

pub(super) struct NetworkAttempt {
    registry: FleetRegistry,
    consumer: AgentId,
    consumer_spawn: u64,
    consumer_client: AgentdClient,
    peers: Vec<PeerAttempt>,
    started: Instant,
    accounting: Arc<Mutex<MemoryCellNetworkCostV1>>,
}

impl NetworkAttempt {
    pub fn new(
        registry: &FleetRegistry,
        consumer: &AgentId,
        consumer_spawn: u64,
        deployment: &MemoryCellDeploymentV1,
        accounting: Arc<Mutex<MemoryCellNetworkCostV1>>,
    ) -> Result<Self, String> {
        let started = Instant::now();
        let consumer_record = live_agent(registry, consumer, consumer_spawn)?;
        let consumer_client = AgentdClient::new(
            consumer_record.layout.agentd_control_socket().to_path_buf(),
            consumer.clone(),
            consumer_spawn,
        )
        .map_err(|error| error.to_string())?;
        let mut peers = Vec::new();
        for binding in &deployment.nodes {
            if binding.grant.consumer_agent_id() != consumer {
                return Err("memory deployment is granted to another consumer".to_string());
            }
            let record = live_agent(
                registry,
                binding.grant.owner_agent_id(),
                binding.spawn_generation,
            )?;
            let client = AgentdClient::new(
                record.layout.agentd_control_socket().to_path_buf(),
                binding.grant.owner_agent_id().clone(),
                binding.spawn_generation,
            )
            .map_err(|error| error.to_string())?;
            peers.push(PeerAttempt {
                binding: binding.clone(),
                client,
            });
        }
        Ok(Self {
            registry: registry.clone(),
            consumer: consumer.clone(),
            consumer_spawn,
            consumer_client,
            peers,
            started,
            accounting,
        })
    }

    /// A complete pass checks every selected owner and its exact parameter
    /// bundle. An unavailable peer never disappears from the version vector.
    pub async fn verify_complete_vector(&self) -> Result<(), String> {
        live_agent(&self.registry, &self.consumer, self.consumer_spawn)?;
        require_ready(&self.consumer_client).await?;
        for peer in &self.peers {
            self.verify_peer(peer).await?;
        }
        require_ready(&self.consumer_client).await?;
        live_agent(&self.registry, &self.consumer, self.consumer_spawn)?;
        Ok(())
    }

    async fn verify_peer(&self, peer: &PeerAttempt) -> Result<(), String> {
        self.verify_fleet_binding(peer)?;
        require_ready(&peer.client).await?;
        let capabilities = peer
            .client
            .capabilities()
            .await
            .map_err(|error| error.to_string())?;
        if !capabilities.capabilities.iter().any(|capability| {
            capability.id == MEMORY_CELL_CONTROL_CAPABILITY_V1 && capability.major == 1
        }) {
            return Err("selected node has no compatible memory cell capability".to_string());
        }
        self.verify_grant(peer).await?;
        self.verify_cut(peer).await?;
        let result = peer
            .client
            .memory_cell_read(peer.binding.probe.clone())
            .await
            .map_err(|error| error.to_string())?;
        require_model_pin(peer, &result)?;
        if result.status != MemoryReadStatusV1::Ok {
            return Err("selected memory node probe did not produce an admitted read".to_string());
        }
        self.verify_cut(peer).await?;
        self.verify_grant(peer).await?;
        require_ready(&peer.client).await?;
        self.verify_fleet_binding(peer)
    }

    async fn verify_cut(&self, peer: &PeerAttempt) -> Result<(), String> {
        let page = peer
            .client
            .memory_cell_snapshot(
                /*after*/ None,
                Some(peer.binding.pin.owner_cut_digest),
                /*limit*/ 1,
            )
            .await
            .map_err(|error| error.to_string())?;
        if page.scope != peer.binding.pin.scope
            || page.owner_cut_digest != peer.binding.pin.owner_cut_digest
        {
            return Err("memory node changed owner cut or scope".to_string());
        }
        Ok(())
    }

    fn verify_fleet_binding(&self, peer: &PeerAttempt) -> Result<(), String> {
        let owner = live_agent(
            &self.registry,
            peer.binding.grant.owner_agent_id(),
            peer.binding.spawn_generation,
        )?;
        let consumer = live_agent(&self.registry, &self.consumer, self.consumer_spawn)?;
        let grant = &peer.binding.grant;
        if grant.scope().consumer_workspace_sha256()
            != &workspace_binding_digest(consumer.manifest.workspace.as_path())
        {
            return Err("memory federation consumer workspace changed".to_string());
        }
        if let CognitiveScope::WorkspacePrivate { workspace_sha256 } = grant.scope().owner_scope()
            && *workspace_sha256 != workspace_binding_digest(owner.manifest.workspace.as_path())
        {
            return Err("memory federation owner workspace changed".to_string());
        }
        Ok(())
    }

    async fn verify_grant(&self, peer: &PeerAttempt) -> Result<(), String> {
        let expected = &peer.binding.grant;
        let id = MemoryFederationCapabilityId::parse(expected.id().as_str().to_string())?;
        let actual = peer
            .client
            .memory_federation_status(id.clone())
            .await
            .map_err(|error| error.to_string())?
            .ok_or_else(|| "memory federation grant is absent".to_string())?;
        let scope = match expected.scope().owner_scope() {
            CognitiveScope::AgentPrivate => MemoryFederationScopeKind::AgentPrivate,
            CognitiveScope::WorkspacePrivate { .. } => MemoryFederationScopeKind::WorkspacePrivate,
        };
        let now = super::unix_seconds()?;
        if actual.capability_id != id
            || actual.owner_agent_id != *expected.owner_agent_id()
            || actual.consumer_agent_id != self.consumer
            || actual.owner_scope != scope
            || actual.generation != expected.generation()
            || actual.revision != expected.revision()
            || actual.effective_at_unix_seconds != expected.effective_at_unix_seconds()
            || actual.expires_at_unix_seconds != expected.expires_at_unix_seconds()
            || actual.state != MemoryFederationCapabilityState::Granted
            || now < actual.effective_at_unix_seconds
            || now >= actual.expires_at_unix_seconds
        {
            return Err("memory federation grant is revoked, expired or changed".to_string());
        }
        Ok(())
    }

    pub async fn read(
        &self,
        requests: &BTreeMap<StableId, MemoryRequestV1>,
    ) -> Result<Vec<MemoryCellNodeReadoutV1>, String> {
        if requests.is_empty() || requests.len() > self.peers.len() {
            return Err("memory network read node budget mismatch".to_string());
        }
        let mut results = Vec::new();
        for (id, request) in requests {
            let peer = self
                .peers
                .iter()
                .find(|peer| peer.binding.node_id == *id)
                .ok_or_else(|| "memory network request names an unselected node".to_string())?;
            request.validate().map_err(|error| error.to_string())?;
            if request.scope != peer.binding.pin.scope {
                return Err("memory network request changed selected owner scope".to_string());
            }
            self.verify_grant(peer).await?;
            let readout = peer
                .client
                .memory_cell_read(request.clone())
                .await
                .map_err(|error| error.to_string())?;
            require_model_pin(peer, &readout)?;
            if matches!(
                readout.status,
                MemoryReadStatusV1::Stale | MemoryReadStatusV1::Unavailable
            ) {
                return Err("selected memory node became stale or unavailable".to_string());
            }
            results.push(MemoryCellNodeReadoutV1 {
                node_id: id.clone(),
                owner_agent_id: peer.binding.grant.owner_agent_id().clone(),
                readout,
            });
        }
        Ok(results)
    }

    pub fn cost(&self) -> MemoryCellNetworkCostV1 {
        let mut cost = MemoryCellNetworkCostV1 {
            elapsed_micros: self
                .started
                .elapsed()
                .as_micros()
                .try_into()
                .unwrap_or(u64::MAX),
            ..MemoryCellNetworkCostV1::default()
        };
        for client in
            std::iter::once(&self.consumer_client).chain(self.peers.iter().map(|peer| &peer.client))
        {
            let traffic = client.traffic_snapshot();
            cost.rpc_attempts = cost.rpc_attempts.saturating_add(traffic.rpc_attempts);
            cost.transmitted_bytes = cost
                .transmitted_bytes
                .saturating_add(traffic.transmitted_bytes);
            cost.received_bytes = cost.received_bytes.saturating_add(traffic.received_bytes);
        }
        cost
    }
}

impl Drop for NetworkAttempt {
    fn drop(&mut self) {
        let cost = self.cost();
        if let Ok(mut totals) = self.accounting.lock() {
            totals.rpc_attempts = totals.rpc_attempts.saturating_add(cost.rpc_attempts);
            totals.transmitted_bytes = totals
                .transmitted_bytes
                .saturating_add(cost.transmitted_bytes);
            totals.received_bytes = totals.received_bytes.saturating_add(cost.received_bytes);
            totals.elapsed_micros = totals.elapsed_micros.saturating_add(cost.elapsed_micros);
        }
    }
}

fn live_agent(
    registry: &FleetRegistry,
    agent: &AgentId,
    spawn: u64,
) -> Result<AgentRecord, String> {
    let record = registry
        .load_agent(agent)
        .map_err(|error| error.to_string())?;
    if record.lifecycle.lifecycle != AgentLifecycle::Running
        || spawn.checked_add(1) != Some(record.lifecycle.generation)
    {
        return Err("memory network agent generation is not the exact running spawn".to_string());
    }
    Ok(record)
}

async fn require_ready(client: &AgentdClient) -> Result<(), String> {
    let health = client.health().await.map_err(|error| error.to_string())?;
    let lifecycle = client
        .lifecycle()
        .await
        .map_err(|error| error.to_string())?;
    if !health.ready
        || health.fenced
        || health.lifecycle != AgentLifecycle::Running
        || !lifecycle.app_server_ready
        || lifecycle.fenced
        || lifecycle.lifecycle != AgentLifecycle::Running
    {
        return Err("memory network peer is not ready".to_string());
    }
    Ok(())
}

fn require_model_pin(peer: &PeerAttempt, readout: &MemoryReadoutV1) -> Result<(), String> {
    if readout.generation != peer.binding.pin.generation
        || readout.snapshot_digest != peer.binding.pin.bundle_digest
    {
        return Err(
            "memory network peer has a different selected parameter generation".to_string(),
        );
    }
    Ok(())
}
