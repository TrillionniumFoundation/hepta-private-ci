#[path = "intelligence_stage_bound_ports.rs"]
mod stage_bound_ports;

use stage_bound_ports::StageBoundAgentdOwnerPortsV1 as AgentdOwnerPortsV1;
pub(super) use stage_bound_ports::bind_context_request_v1;
pub(super) use stage_bound_ports::bind_intuition_request_v1;
pub(super) use stage_bound_ports::bind_prompt_request_v1;

// The implementation body is retained byte-for-byte from the reviewed product
// runner. Only the concrete owner-port type above is replaced by the narrow
// stage-binding decorator.
include!("intelligence_product_runner_base.rs");
