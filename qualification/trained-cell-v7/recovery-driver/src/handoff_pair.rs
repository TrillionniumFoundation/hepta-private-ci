//! Bind the candidate's original controller anchors to its immutable predecessor.

use crate::handoff_version::Handoff;
use crate::*;

pub fn serving_payloads(inputs: &report::Inputs) -> Result<[Vec<u8>; 2]> {
    let payloads = [&inputs.predecessor, &inputs.candidate];
    if payloads.iter().all(|p| p.starts_with(b"HPTACV05")) {
        // The inherited synthetic fixture remains a V5 mechanics regression.
        // A future V7 frozen-profile validator must require the V7 envelope.
        return Ok([inputs.predecessor.clone(), inputs.candidate.clone()]);
    }
    let baseline = Handoff::decode(payloads[0], Digest32::of_bytes(payloads[0]))?;
    let candidate = Handoff::decode(payloads[1], Digest32::of_bytes(payloads[1]))?;
    ensure(
        baseline.protocol_digest() == inputs.policy.protocol_digest
            && candidate.protocol_digest() == inputs.policy.protocol_digest
            && baseline.compatibility_digest() == candidate.compatibility_digest()
            && baseline.predecessor_digest().is_none()
            && candidate.predecessor_digest() == Some(baseline.content_digest())
            && Some(candidate.generation().get()) == baseline.generation().get().checked_add(1)
            && baseline.checkpoints().len() == candidate.checkpoints().len(),
        "handoff predecessor binding differs",
    )?;
    for (previous, next) in baseline.checkpoints().iter().zip(candidate.checkpoints()) {
        let before: Value = serde_json::from_slice(previous.state_metadata_json())?;
        let after: Value = serde_json::from_slice(next.state_metadata_json())?;
        let old: Value = serde_json::from_slice(previous.controller_metadata_json())?;
        let new: Value = serde_json::from_slice(next.controller_metadata_json())?;
        let old_source: Value =
            serde_json::from_str(report::string(&old, "source_controller_json")?)?;
        let new_source: Value =
            serde_json::from_str(report::string(&new, "source_controller_json")?)?;
        ensure(
            previous.cell_id() == next.cell_id()
                && before["bindings"] == after["bindings"]
                && before["protocol"] == after["protocol"]
                && before["contexts"] == after["contexts"]
                && old_source["contract"] == new_source["contract"]
                && old["absolute_step"] == 0
                && new["original_warmup_state_sha256"] == old["state_sha256"]
                && new["warmup_step_count"] == before["step_count"],
            "candidate changed original warmup, controller contract or optimizer identity",
        )?;
    }
    Ok([baseline.serving().encode(), candidate.serving().encode()])
}
