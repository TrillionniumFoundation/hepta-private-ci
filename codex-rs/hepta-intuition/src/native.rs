//! Native profile routing with byte-compatible historical digest projections.
//!
//! The observed request is never rewritten. Only the historical digest encoder
//! projects the old effective-risk byte; it cannot affect routing or authority.

use codex_hepta_types::Digest32;
use crate::calibrated::CalibratedDecisionRequestV1;
use crate::calibrated::CalibratedError;
use crate::calibrated::CalibratedIntuitionReceiptV1;
use crate::calibrated::RiskClass;
use crate::calibrated::RiskRouting;
use crate::calibrated::canonical_calibrated_request_digest_v1;
use crate::calibrated::canonical_request_digest_with_risk;
use crate::calibrated::decide_with_routing;
use crate::calibrated::digest_receipt_with_risk;
use crate::qualified::CanonicalPolicyProfileV1;
use crate::qualified::CanonicalRiskRuleV1;
use crate::qualified::QualifiedCalibratedError;
use crate::qualified::canonical_policy_profile_digest_v1;
use crate::qualified::validate_profile_for_request;

pub(crate) fn decide_native_profile(
    request: &CalibratedDecisionRequestV1,
    profile: &CanonicalPolicyProfileV1,
) -> Result<CalibratedIntuitionReceiptV1, QualifiedCalibratedError> {
    validate_profile_for_request(request, profile)?;
    if request.completeness.omitted_count_bound != 0 {
        return Err(CalibratedError::IncompleteCandidateSet.into());
    }
    let forced = match profile.risk_rule {
        CanonicalRiskRuleV1::HighOnlySlowPath => request.risk_class == RiskClass::High,
        CanonicalRiskRuleV1::ElevatedAndHighSlowPath => request.risk_class != RiskClass::Low,
        CanonicalRiskRuleV1::AlwaysSlowPath => true,
    };
    let route = if forced { RiskRouting::ProfileSlowPath } else { RiskRouting::Request };
    let mut receipt = decide_with_routing(request, route)?;
    // Encoding-only compatibility projection, not a second decision execution.
    let encoded_risk = if forced { RiskClass::High } else { request.risk_class };
    let legacy_v1 = digest_receipt_with_risk(
        request, &receipt.disposition, &receipt.propensities,
        receipt.abstain_probability, receipt.slow_path_probability, encoded_risk,
    )?;
    let mut v2 = b"hepta.intuition.calibrated-decision.v2".to_vec();
    v2.extend_from_slice(canonical_request_digest_with_risk(request, encoded_risk)?.as_array());
    v2.extend_from_slice(legacy_v1.as_array());
    let mut v3 = b"hepta.intuition.calibrated-decision.v3\0".to_vec();
    v3.extend_from_slice(canonical_calibrated_request_digest_v1(request)?.as_array());
    v3.extend_from_slice(canonical_policy_profile_digest_v1(profile)?.as_array());
    v3.extend_from_slice(Digest32::of_bytes(&v2).as_array());
    v3.push(u8::from(forced));
    receipt.receipt_digest = Digest32::of_bytes(&v3);
    Ok(receipt)
}
