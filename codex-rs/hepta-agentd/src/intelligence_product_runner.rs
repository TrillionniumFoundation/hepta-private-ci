// Keep the reviewed runner at its original module depth so its pub(super)
// worker/testing seams retain the same visibility. Item order is irrelevant to
// name resolution; the explicit port alias below shadows the parent's glob
// import used by the retained implementation body.
//
// Generated-source anchors for the implementation body retained below:
// - request_digest: run_identity.request_digest.to_string()
// - validate_canonical_outcome_v1
// - with_hard_timeout_process_exit
// - capability_profile_digest
include!("intelligence_product_runner_base.rs");

#[path = "intelligence_stage_bound_ports.rs"]
mod stage_bound_ports;

use stage_bound_ports::StageBoundAgentdOwnerPortsV1 as AgentdOwnerPortsV1;

pub(super) fn bind_prompt_request_v1(
    request: &mut OptimizationRequest,
    neural_output: Digest32,
    candidate_set_digest: Digest32,
) -> Result<(), &'static str> {
    stage_bound_ports::bind_prompt_request_v1(request, neural_output, candidate_set_digest)
}

pub(super) fn bind_intuition_request_v1(
    request: &mut CalibratedDecisionRequestV1,
    prompt_output: Digest32,
    candidate_set_digest: Digest32,
) -> Result<(), &'static str> {
    stage_bound_ports::bind_intuition_request_v1(request, prompt_output, candidate_set_digest)
}

pub(super) fn bind_context_request_v1(
    request: &mut CompilationRequest,
    prompt_output: Digest32,
    intuition_output: Digest32,
    candidate_set_digest: Digest32,
) -> Result<(), &'static str> {
    stage_bound_ports::bind_context_request_v1(
        request,
        prompt_output,
        intuition_output,
        candidate_set_digest,
    )
}
