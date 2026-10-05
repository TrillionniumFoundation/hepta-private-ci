//! Real final-use probes on the original retained bytes. No new delivery or
//! weight-forgetting authority follows from a structural withdrawal.
use super::super::*;
use super::issuance::Issuance;
use codex_hepta_agent_components::learning_ledger::open_root_review_input;
use std::cell::Cell;

pub(super) fn deny(
    inputs: &Inputs,
    withdrawals: &DatasetWithdrawalRegistry,
    issuance: &Issuance,
) -> HostResult<Vec<Value>> {
    let receipt = issuance.before.native()?;
    let snapshot = inputs.profile.owner_root.join("registries").join(format!(
        "{}-{}.snapshot",
        receipt.head_digest, receipt.file_digest
    ));
    let registry = read_registry_snapshot(open_root_review_input(&snapshot)?, receipt)?;
    let current = ReadOnlyArtifactCurrentOwnerV1::open(
        &inputs.profile.owner_root,
        inputs.trust()?,
        withdrawals.clone(),
        now_ms()?,
    )?;
    let mut results = Vec::new();
    for target in &issuance.delivery_targets {
        let manifest = registry
            .manifest(&id(target)?)
            .ok_or("original delivery manifest disappeared")?
            .clone();
        let payload = inputs.profile.owner_root.join("payloads").join(format!(
            "{}-{}.bin",
            manifest.artifact_id, manifest.content_digest
        ));
        let loaded = load_pinned_candidate(
            open_root_review_input(&snapshot)?,
            open_root_review_input(&payload)?,
            PinnedCandidateSpec {
                registry_receipt: receipt,
                manifest,
            },
        )?;
        let mut consumer = RevalidatingCandidate::new(loaded);
        let dispatched = Cell::new(false);
        let result = consumer.with_current(current.current_registry_view(now_ms()?)?, |_| {
            dispatched.set(true)
        });
        if result != Err(PinnedCandidateLoadError::Ineligible) || dispatched.get() {
            return Err(
                "original physical delivery gate did not reject the withdrawn source/descendant"
                    .into(),
            );
        }
        results.push(
            serde_json::json!({"artifact_id":target,"gate":"RevalidatingCandidate::with_current",
            "result":"Ineligible","consumer_invoked":false}),
        );
    }
    Ok(results)
}
