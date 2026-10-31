//! New 100 mutually exclusive code qualification. The former five-action report is not accepted.
use crate::{Spec, stream_io::Result};
use serde_json::Value;

pub fn validate(spec: &Spec, verification: &Value, calibration: &Value) -> Result<()> {
    if !["development", "qualification_collection", "qualified"].contains(&spec.mode.as_str())
        || verification["schema"] != "hepta.advance.semantic-owner-verification.v1"
        || verification["qualification_protocol_sha256"] != spec.pins.protocol
        || verification["calibration_sha256"] != spec.pins.calibration
        || verification["weights_sha256"] != spec.pins.weights
        || verification["native_measured_ece_ppm"].as_u64()
            != Some(spec.pins.measured_ece_ppm as u64)
        || verification["native_measured_false_acceptance_ppm"].as_u64()
            != Some(spec.pins.measured_false_acceptance_ppm as u64)
        || spec.pins.measured_ece_ppm > 30000
        || spec.pins.measured_false_acceptance_ppm > 4999
        || calibration["schema"] != "hepta.advance.operation-confidence.v1"
        || verification["nonempty_definition"]
            != "fraction_of_ID_requests_with_at_least_one_admitted_action"
        || verification["minimum_confidence_ppm"] != 750000
        || verification["maximum_ece_ppm"] != 30000
        || verification["maximum_false_acceptance_ppm"] != 4999
    {
        return Err(
            "New semantic schema, exact numerical gates or actual calibration evidence rejected"
                .into(),
        );
    }
    if spec.mode == "qualified"
        && (verification["study_qualified"] != true
            || verification["policy"] != spec.policy
            || verification["gates"]["selected_action_ece"] != true
            || verification["gates"]["pooled_ece"] != true
            || verification["gates"]["ID_request_coverage"] != true
            || verification["gates"]["all_missing_false_acceptance"] != true
            || verification["ID_independent_writers"] != 10
            || verification["ID_actual_requests"] != 160
            || verification["OOD_independent_source_speakers"] != 600
            || verification["all_missing_actual_requests"] != 600
            || verification["independent_missing_speaker_is_distinct_model_input"] != false)
    {
        return Err("New end-to-end independent qualification has not passed".into());
    }
    if spec.mode != "qualified" && verification["study_qualified"] != false {
        return Err("Development/collection cannot claim final qualification".into());
    }
    Ok(())
}
