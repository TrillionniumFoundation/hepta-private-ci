//! Native profile routing with a read-only historical encoding view.
//!
//! The decision kernel receives the original request and an explicit routing
//! rule. Historical V1/V2/V3 digest fields are reproduced from the resulting
//! decision without passing a rewritten request through a legacy policy entry.
//! This preserves durable receipt interpretation and existing signed payloads.

use codex_hepta_types::Digest32;

use crate::calibrated::CalibratedDecisionRequestV1;
use crate::calibrated::CalibratedError;
use crate::calibrated::CalibratedIntuitionReceiptV1;
use crate::calibrated::KernelRiskRouting;
use crate::calibrated::RiskClass;
use crate::calibrated::canonical_calibrated_request_digest_v1;
use crate::calibrated::canonical_request_digest_with_risk;
use crate::calibrated::decide_calibrated_with_routing;
use crate::calibrated::digest_receipt_with_risk;
use crate::qualified::CanonicalPolicyProfileV1;
use crate::qualified::QualifiedCalibratedError;
use crate::qualified::canonical_policy_profile_digest_v1;
use crate::qualified::validate_profile_for_request;

pub(super) fn native_profile_decision(
    request: &CalibratedDecisionRequestV1,
    profile: &CanonicalPolicyProfileV1,
) -> Result<CalibratedIntuitionReceiptV1, QualifiedCalibratedError> {
    validate_profile_for_request(request, profile)?;
    if request.completeness.omitted_count_bound != 0 {
        return Err(CalibratedError::IncompleteCandidateSet.into());
    }
    let force = super::risk_requires_slow_path(profile.risk_rule, request.risk_class);
    let routing = if force {
        KernelRiskRouting::ProfileSlowPath
    } else {
        KernelRiskRouting::RequestRisk
    };
    let mut receipt = decide_calibrated_with_routing(request, routing)?;

    // Encoding compatibility is not routing. In particular, this field cannot
    // change the actual request, masks, sampled action or output distribution.
    let historical_risk = if force {
        RiskClass::High
    } else {
        request.risk_class
    };
    let historical_v1 = digest_receipt_with_risk(
        request,
        &receipt.disposition,
        &receipt.propensities,
        receipt.abstain_probability,
        receipt.slow_path_probability,
        historical_risk,
    )?;
    let mut v2 = b"hepta.intuition.calibrated-decision.v2".to_vec();
    v2.extend_from_slice(canonical_request_digest_with_risk(request, historical_risk)?.as_array());
    v2.extend_from_slice(historical_v1.as_array());
    let mut v3 = b"hepta.intuition.calibrated-decision.v3\0".to_vec();
    v3.extend_from_slice(canonical_calibrated_request_digest_v1(request)?.as_array());
    v3.extend_from_slice(canonical_policy_profile_digest_v1(profile)?.as_array());
    v3.extend_from_slice(Digest32::of_bytes(&v2).as_array());
    v3.push(u8::from(force));
    receipt.receipt_digest = Digest32::of_bytes(&v3);
    Ok(receipt)
}
