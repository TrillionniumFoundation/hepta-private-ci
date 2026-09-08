//! The live shell's first compiled-in organ graph. This is a process-local
//! composition, not a dynamic loader, a physical body, or a selection authority.

use std::collections::BTreeSet;
use std::sync::Arc;
use std::sync::Mutex;

use anyhow::Context;
use anyhow::Result;
use codex_hepta_control_plane::DataflowTiming;
use codex_hepta_control_plane::FailureDomainV1;
use codex_hepta_control_plane::FallbackTerminal;
use codex_hepta_control_plane::InputPort;
use codex_hepta_control_plane::OrganEdge;
use codex_hepta_control_plane::OrganGraphsV1;
use codex_hepta_control_plane::OrganHandlerFaultV1;
use codex_hepta_control_plane::OrganHostV1;
use codex_hepta_control_plane::OrganNodeV1;
use codex_hepta_control_plane::OrganRole;
use codex_hepta_control_plane::OutputPort;
use codex_hepta_control_plane::RuntimeLinkV1;
use codex_hepta_control_plane::TrustedReadOnlyOrganV1;
use codex_hepta_paths::HeptaStateRoot;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::RuntimeAuthorityStatus;
use crate::RuntimeStateAdapter;
use crate::RuntimeStatus;

#[derive(Debug)]
pub(crate) struct RuntimeOrgans {
    // Preserve the public infallible from_adapter constructor without hiding
    // initialization failures. A failed host stays failed, not silently retried.
    host: Mutex<Result<StatusHost, String>>,
}

#[derive(Debug)]
struct StatusHost {
    host: OrganHostV1,
    ingress: StableId,
    generation: Generation,
}

impl RuntimeOrgans {
    pub(crate) fn new(root: HeptaStateRoot, state: Arc<dyn RuntimeStateAdapter>) -> Self {
        let host = build_host(root, state).map_err(|error| format!("{error:#}"));
        Self {
            host: Mutex::new(host),
        }
    }

    pub(crate) fn ensure_ready(&self) -> Result<()> {
        let host = self
            .host
            .lock()
            .map_err(|_| anyhow::anyhow!("organ host poisoned"))?;
        if let Err(error) = &*host {
            anyhow::bail!("organ initialization failed: {error}");
        }
        Ok(())
    }

    pub(crate) fn status_json(&self) -> Result<Vec<u8>> {
        // Never block an async gateway worker behind a concurrent handler.
        let mut host = self
            .host
            .try_lock()
            .map_err(|_| anyhow::anyhow!("organ host unavailable"))?;
        let host = host
            .as_mut()
            .map_err(|error| anyhow::anyhow!("organ initialization failed: {error}"))?;
        let deliveries =
            host.host
                .dispatch_once(host.generation, &host.ingress, /*output_port*/ 0, &[])?;
        let [delivery] = deliveries.as_slice() else {
            anyhow::bail!("status graph returned an unexpected delivery count");
        };
        if delivery.authority != AuthorityPosture::DENY_ALL {
            anyhow::bail!("status graph returned an authority delta");
        }
        Ok(delivery.output.clone())
    }
}

fn build_host(root: HeptaStateRoot, state: Arc<dyn RuntimeStateAdapter>) -> Result<StatusHost> {
    let ingress = StableId::new("runtime.status.ingress")?;
    let generation = Generation::new(/* value */ 1)?;
    let status = StableId::new("runtime.status.adapter")?;
    let owner = StableId::new("runtime.hepta-live-shell")?;
    let port = StableId::new("runtime.status.request.v1")?;
    let process = StableId::new(format!("hepta-live-shell:{}", std::process::id()))?;
    // This names the local process failure domain; it is not a remote host
    // identity, attestation, safety certificate, or physical fallback witness.
    let host_id = StableId::new("process-local")?;
    let terminal = FallbackTerminal::SafeState(Digest32::of_bytes(
        b"hepta.live-shell.status-unavailable.http503.v1",
    ));
    let graph = OrganGraphsV1 {
        generation,
        organs: vec![
            OrganNodeV1 {
                id: ingress.clone(),
                owner: owner.clone(),
                role: OrganRole::Other,
                inputs: vec![],
                outputs: vec![port.clone()],
                effect_scope: BTreeSet::new(),
                terminal: terminal.clone(),
            },
            OrganNodeV1 {
                id: status.clone(),
                owner,
                role: OrganRole::Other,
                inputs: vec![port],
                outputs: vec![],
                effect_scope: BTreeSet::new(),
                terminal,
            },
        ],
        initialization: vec![OrganEdge { from: 1, to: 0 }],
        runtime: vec![RuntimeLinkV1 {
            output: OutputPort { organ: 0, port: 0 },
            input: InputPort { organ: 1, port: 0 },
            timing: DataflowTiming::Synchronous,
        }],
        feedback: vec![],
        fallback: vec![],
        failure_domains: (0..2)
            .map(|organ| FailureDomainV1 {
                organ,
                process: process.clone(),
                host: host_id.clone(),
            })
            .collect(),
    };
    let handlers: Vec<Box<dyn TrustedReadOnlyOrganV1>> = vec![
        Box::new(StatusOrgan {
            id: ingress.clone(),
            data: None,
        }),
        Box::new(StatusOrgan {
            id: status,
            data: Some((root, state)),
        }),
    ];
    let mut host = OrganHostV1::new(graph, handlers)?;
    host.start_all()
        .context("start compiled-in status organs")?;
    Ok(StatusHost {
        host,
        ingress,
        generation,
    })
}

#[derive(Debug)]
struct StatusOrgan {
    id: StableId,
    data: Option<(HeptaStateRoot, Arc<dyn RuntimeStateAdapter>)>,
}

impl TrustedReadOnlyOrganV1 for StatusOrgan {
    fn id(&self) -> &StableId {
        &self.id
    }

    fn start(&mut self) -> Result<(), OrganHandlerFaultV1> {
        Ok(())
    }

    fn handle(
        &mut self,
        input_port: usize,
        payload: &[u8],
    ) -> Result<Vec<u8>, OrganHandlerFaultV1> {
        let Some((root, state)) = &self.data else {
            return Err(OrganHandlerFaultV1::new(self.id.clone()));
        };
        if input_port != 0 || !payload.is_empty() {
            return Err(OrganHandlerFaultV1::new(self.id.clone()));
        }
        serde_json::to_vec(&RuntimeStatus {
            schema: "hepta_vnext_live_runtime_status_v1",
            product: "hepta",
            status: "ready",
            state_root: root.to_string(),
            state: state.status(),
            authority: RuntimeAuthorityStatus::default(),
        })
        .map_err(|_| OrganHandlerFaultV1::new(self.id.clone()))
    }

    fn stop(&mut self) -> Result<(), OrganHandlerFaultV1> {
        Ok(())
    }
}

#[cfg(test)]
#[path = "organs_tests.rs"]
mod tests;
