// Keep the canonical bounded runner at its established module path. The active
// owner-port type below wraps the native seven-owner adapters and closes the
// final Intuition -> Context identity edge without adding another executor.
#[path = "intelligence_stage_bound_ports.rs"]
mod stage_bound_ports;
use stage_bound_ports::StageBoundAgentdOwnerPortsV1 as AgentdOwnerPortsV1;

include!("intelligence_product_runner_base.rs");
