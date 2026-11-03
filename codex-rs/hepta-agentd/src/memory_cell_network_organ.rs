//! Pure route metadata in the existing read-only organ lifecycle. Socket I/O,
//! authority checks and model execution stay outside these handlers.

use std::collections::BTreeSet;

use codex_hepta_control_plane::DataflowTiming;
use codex_hepta_control_plane::FailureDomainV1;
use codex_hepta_control_plane::FallbackTerminal;
use codex_hepta_control_plane::InputPort;
use codex_hepta_control_plane::OrganEdge;
use codex_hepta_control_plane::OrganGraphsV1;
use codex_hepta_control_plane::OrganHandlerFaultV1;
use codex_hepta_control_plane::OrganHostV1;
use codex_hepta_control_plane::OrganMigrationError;
use codex_hepta_control_plane::OrganNodeV1;
use codex_hepta_control_plane::OrganRole;
use codex_hepta_control_plane::OrganStateMigrationV1;
use codex_hepta_control_plane::OutputPort;
use codex_hepta_control_plane::RuntimeLinkV1;
use codex_hepta_control_plane::TrustedReadOnlyOrganV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::bindings::MemoryCellDeploymentV1;
use super::bindings::MemoryCellNetworkVersionV1;

#[derive(Debug)]
struct RouteOrgan {
    id: StableId,
    deployment: Digest32,
    binding: Digest32,
}

impl TrustedReadOnlyOrganV1 for RouteOrgan {
    fn id(&self) -> &StableId {
        &self.id
    }
    fn start(&mut self) -> Result<(), OrganHandlerFaultV1> {
        Ok(())
    }
    fn stop(&mut self) -> Result<(), OrganHandlerFaultV1> {
        Ok(())
    }
    fn handle(
        &mut self,
        input_port: usize,
        payload: &[u8],
    ) -> Result<Vec<u8>, OrganHandlerFaultV1> {
        if input_port != 0 || payload != self.deployment.as_array() {
            return Err(OrganHandlerFaultV1::new(self.id.clone()));
        }
        Ok(self.binding.as_array().to_vec())
    }
}

pub(super) fn graph(
    deployment: &MemoryCellDeploymentV1,
) -> Result<(OrganGraphsV1, Vec<Box<dyn TrustedReadOnlyOrganV1>>), String> {
    let generation =
        Generation::new(deployment.generation.get()).map_err(|error| error.to_string())?;
    let router = id("memory.network.router")?;
    let port = id("memory.route.v1")?;
    let owner = id(deployment.nodes[0].grant.consumer_agent_id().as_str())?;
    let terminal = FallbackTerminal::SafeState(Digest32::of_bytes(b"memory.network.unavailable"));
    let mut organs = vec![OrganNodeV1 {
        id: router.clone(),
        owner: owner.clone(),
        role: OrganRole::Cognitive,
        inputs: vec![],
        outputs: vec![port.clone()],
        effect_scope: BTreeSet::new(),
        terminal: terminal.clone(),
    }];
    let mut handlers: Vec<Box<dyn TrustedReadOnlyOrganV1>> = vec![Box::new(RouteOrgan {
        id: router,
        deployment: deployment.digest.digest(),
        binding: deployment.digest.digest(),
    })];
    let mut initialization = Vec::new();
    let mut runtime = Vec::new();
    for (offset, node) in deployment.nodes.iter().enumerate() {
        let index = offset + 1;
        organs.push(OrganNodeV1 {
            id: node.node_id.clone(),
            owner: owner.clone(),
            role: OrganRole::Cognitive,
            inputs: vec![port.clone()],
            outputs: vec![],
            effect_scope: BTreeSet::new(),
            terminal: terminal.clone(),
        });
        handlers.push(Box::new(RouteOrgan {
            id: node.node_id.clone(),
            deployment: deployment.digest.digest(),
            binding: node.digest()?,
        }));
        initialization.push(OrganEdge { from: 0, to: index });
        runtime.push(RuntimeLinkV1 {
            output: OutputPort { organ: 0, port: 0 },
            input: InputPort {
                organ: index,
                port: 0,
            },
            timing: DataflowTiming::Buffered,
        });
    }
    // Unix control peers share a local host failure domain; no independence is
    // inferred from their logical node labels or separate Agent generations.
    let failure_domains = organs
        .iter()
        .enumerate()
        .map(|(organ, node)| {
            Ok(FailureDomainV1 {
                organ,
                process: node.id.clone(),
                host: id("memory.local-control-host")?,
            })
        })
        .collect::<Result<Vec<_>, String>>()?;
    let graph = OrganGraphsV1 {
        generation,
        organs,
        initialization,
        runtime,
        feedback: vec![],
        fallback: vec![],
        failure_domains,
    };
    graph
        .validate()
        .map_err(|error| format!("invalid memory organ graph: {error:?}"))?;
    Ok((graph, handlers))
}

pub(super) fn verify_routes(
    host: &mut OrganHostV1,
    deployment: &MemoryCellDeploymentV1,
) -> Result<(), String> {
    let delivered = host
        .dispatch_once(
            host.generation(),
            &id("memory.network.router")?,
            /*output_port*/ 0,
            deployment.digest.digest().as_array(),
        )
        .map_err(|error| error.to_string())?;
    if delivered.len() != deployment.nodes.len() {
        return Err("memory organ route count changed".to_string());
    }
    for node in &deployment.nodes {
        let delivery = delivered
            .iter()
            .find(|delivery| delivery.target == node.node_id)
            .ok_or_else(|| "memory organ omitted a selected node".to_string())?;
        if delivery.authority.grants_any()
            || delivery.output.as_slice() != node.digest()?.as_array()
        {
            return Err("memory organ route metadata binding changed".to_string());
        }
    }
    Ok(())
}

pub(super) struct RouteMigration {
    pub from: MemoryCellNetworkVersionV1,
    pub to: MemoryCellNetworkVersionV1,
    pub applied: bool,
}

impl OrganStateMigrationV1 for RouteMigration {
    fn snapshot(&mut self, predecessor: Generation) -> Result<Vec<u8>, OrganMigrationError> {
        if predecessor.get() != self.from.generation.get() {
            return Err(OrganMigrationError::Rejected);
        }
        Ok(self.from.deployment_digest.digest().as_array().to_vec())
    }
    fn migrate(
        &mut self,
        snapshot: &[u8],
        predecessor: Generation,
        candidate: Generation,
    ) -> Result<(), OrganMigrationError> {
        if predecessor.get() != self.from.generation.get()
            || candidate.get() != self.to.generation.get()
            || snapshot != self.from.deployment_digest.digest().as_array()
        {
            return Err(OrganMigrationError::Rejected);
        }
        self.applied = true;
        Ok(())
    }
    fn rollback(
        &mut self,
        snapshot: &[u8],
        predecessor: Generation,
        candidate: Generation,
    ) -> Result<(), OrganMigrationError> {
        if predecessor.get() != self.from.generation.get()
            || candidate.get() != self.to.generation.get()
            || snapshot != self.from.deployment_digest.digest().as_array()
        {
            return Err(OrganMigrationError::Rejected);
        }
        self.applied = false;
        Ok(())
    }
}

fn id(value: &str) -> Result<StableId, String> {
    StableId::new(value).map_err(|error| error.to_string())
}
