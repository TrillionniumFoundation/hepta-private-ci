//! Closed Root inspection of original history and independently current use.
//! No signer, seed, writer, repair, acknowledgement or new owner is opened.
use super::super::*;
use super::Request;
use super::inspection_source;
use super::issuance;
use super::source;
use std::cell::Cell;
use std::collections::BTreeSet;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Probe {
    schema: String,
    withdrawal_request: Source,
    current_owner: Source,
}

pub(super) fn run(path: &Path, pin: Digest32) -> HostResult<Value> {
    let original_probe = Source {
        path: path.to_owned(),
        digest: pin.to_string(),
    };
    let probe: Probe = serde_json::from_slice(&original_probe.read(32 * 1024)?)?;
    if probe.schema != "hepta.cpu-neuron.dataset-withdrawal-current-probe.v1" {
        return Err("withdrawal current probe schema".into());
    }
    let current = Inputs::read(
        &probe.current_owner.path,
        digest(&probe.current_owner.digest)?,
    )?;
    if current.profile.owner.uid != 0 || current.profile.owner.gid != 0 {
        return Err("withdrawal inspection requires the original Root owner".into());
    }
    role::require_actual_program(&current.profile.program, &current.profile.owner)?;
    let request: Request = serde_json::from_slice(&probe.withdrawal_request.read(32 * 1024)?)?;
    if request.schema != "hepta.cpu-neuron.dataset-withdrawal-request.v1"
        || request.previous_withdrawals.len() > 64
        || request.delivery_targets.is_empty()
        || request.delivery_targets.len() > 64
    {
        return Err("withdrawal original request schema/capacity".into());
    }
    // Old E1/profile is historical binding only. Current authority came from
    // the independently verified current_owner above, never this old expiry.
    let old_deployment: Deployment = serde_json::from_slice(&request.owner.read(32 * 1024)?)?;
    let old_profile: Profile = serde_json::from_slice(&old_deployment.profile.read(64 * 1024)?)?;
    old_profile.validate_identity()?;
    let binding = current.storage_binding();
    if current.profile.owner_root != old_profile.owner_root
        || current.profile.registry_id != old_profile.registry_id
        || current.profile.owner.id != old_profile.owner.id
        || current.profile.owner.public_key_hex != old_profile.owner.public_key_hex
        || current.profile.owner.credential_digest != old_profile.owner.credential_digest
        || current.profile.withdrawals()?.scope_digest()
            != old_profile.withdrawals()?.scope_digest()
    {
        return Err("current Root owner is not this original withdrawal history".into());
    }
    let retained_path = probe
        .withdrawal_request
        .path
        .parent()
        .ok_or("original request parent")?
        .join("withdrawal-issuance.json");
    let original = issuance::read(&retained_path, digest(&probe.withdrawal_request.digest)?)?
        .ok_or("original withdrawal issuance is absent")?;
    if original.delivery_targets != request.delivery_targets
        || original.before.native()?.head_digest != digest(&request.expected_artifact_head)?
    {
        return Err("original withdrawal issuance/request substitution".into());
    }
    let witnessed = inspection_source::read(
        &request,
        &original.evidence.native()?,
        digest(&original.source_event)?,
        digest(&original.event)?,
    )?;
    let mut withdrawals = current.profile.withdrawals()?;
    for notice in &request.previous_withdrawals {
        withdrawals.append(notice.native()?)?;
    }
    withdrawals.append(witnessed.notice.clone())?;
    let frontier = current.profile.owner_root.join("READ-CURRENT");
    let before = read_root_review_input(&frontier, 16 * 1024)?;
    let owner = ReadOnlyArtifactCurrentOwnerV1::open(
        &current.profile.owner_root,
        current.trust()?,
        withdrawals.clone(),
        now_ms()?,
    )?;
    let historical_head =
        original
            .head
            .historical(&old_deployment.profile, &old_profile, binding)?;
    let ack = owner
        .acknowledged_publication(&id(&request.lineage_id)?, &historical_head, now_ms()?)?
        .ok_or("original artifact ACK is absent")?;
    if ack.withdrawal_head_digest != withdrawals.head_digest() {
        return Err("original artifact ACK does not bind this withdrawal frontier".into());
    }
    let receipt = original.before.native()?;
    let snapshot = current.profile.owner_root.join("registries").join(format!(
        "{}-{}.snapshot",
        receipt.head_digest, receipt.file_digest
    ));
    let registry = read_registry_snapshot(
        codex_hepta_agent_components::learning_ledger::open_root_review_input(&snapshot)?,
        receipt,
    )?;
    let direct: BTreeSet<_> = owner
        .historical_dataset_members(receipt, witnessed.notice.dataset_digest, now_ms()?)?
        .into_iter()
        .collect();
    if !direct.contains(&id(&request.artifact_id)?) || direct.len() > 64 {
        return Err("withdrawal source lacks exact native V2 membership".into());
    }
    let changes = original
        .suffix
        .iter()
        .map(issuance::Change::native)
        .collect::<HostResult<Vec<_>>>()?;
    let affected = super::inspection_targets::complete(
        &registry,
        &direct,
        &original.delivery_targets,
        &changes,
    )?;
    // Complete immutable native suffix must occur immediately after the exact
    // retained predecessor, before the independently signed publication head.
    let current_view = owner.current_registry_view(now_ms()?)?;
    let suffix_start = receipt
        .records
        .checked_add(1)
        .ok_or("withdrawal prefix length")?;
    let suffix_end = suffix_start
        .checked_add(changes.len())
        .ok_or("withdrawal suffix length")?;
    let current_receipt = current_view.receipt();
    let current_snapshot = current.profile.owner_root.join("registries").join(format!(
        "{}-{}.snapshot",
        current_receipt.head_digest, current_receipt.file_digest
    ));
    let current_registry = read_registry_snapshot(
        codex_hepta_agent_components::learning_ledger::open_root_review_input(&current_snapshot)?,
        current_receipt,
    )?;
    let actual_suffix = current_registry
        .records()
        .get(suffix_start..suffix_end)
        .ok_or("original complete withdrawal suffix missing")?;
    if actual_suffix
        .iter()
        .map(|record| &record.event)
        .ne(changes.iter())
    {
        return Err("original native withdrawal suffix changed".into());
    }
    let mut denials = Vec::new();
    for (target, role) in &affected {
        let manifest = registry
            .manifest(target)
            .ok_or("historical delivery target missing")?
            .clone();
        let payload = current.profile.owner_root.join("payloads").join(format!(
            "{}-{}.bin",
            manifest.artifact_id, manifest.content_digest
        ));
        let candidate = load_pinned_candidate(
            codex_hepta_agent_components::learning_ledger::open_root_review_input(&snapshot)?,
            codex_hepta_agent_components::learning_ledger::open_root_review_input(&payload)?,
            PinnedCandidateSpec {
                registry_receipt: receipt,
                manifest,
            },
        )?;
        let dispatched = Cell::new(false);
        let result = RevalidatingCandidate::new(candidate)
            .with_current(owner.current_registry_view(now_ms()?)?, |_| {
                dispatched.set(true)
            });
        if result != Err(PinnedCandidateLoadError::Ineligible) || dispatched.get() {
            return Err("actual original source/descendant consumer was not denied".into());
        }
        denials.push(serde_json::json!({"artifact_id":target.as_str(),"role":role,
            "gate":"RevalidatingCandidate::with_current","result":"Ineligible","accepted":false,"consumer_invoked":false}));
    }
    current.revalidate()?;
    original_probe.read(32 * 1024)?;
    probe.withdrawal_request.read(32 * 1024)?;
    request.owner.read(32 * 1024)?;
    old_deployment.profile.read(64 * 1024)?;
    if read_root_review_input(&frontier, 16 * 1024)? != before {
        return Err("original current Root frontier changed during inspection".into());
    }
    source::directory(&current.profile.owner_root)?;
    let observed = now_ms()?;
    let current_head = owner.protected_current_head(observed)?;
    Ok(
        serde_json::json!({"schema":"hepta.cpu-neuron.dataset-withdrawal-inspection.v1",
        "request_digest":digest(&probe.withdrawal_request.digest)?.to_string(),
        "current_owner_digest":digest(&probe.current_owner.digest)?.to_string(),
        "observed_at_ms":observed,"current_read_digest":Digest32::of_bytes(&before).to_string(),
        "current_head_digest":current_head.witness.head_digest.to_string(),"withdrawal_head":withdrawals.head_digest().to_string(),
        "source_ack":witnessed.ack,"artifact_ack":{"operation_id":ack.operation_id.as_str(),"phase":"Acknowledged",
            "admission_digest":ack.admission_digest.to_string(),"publication_intent_digest":ack.intent_digest.to_string(),
            "registry_head":ack.registry_receipt.ok_or("original registry ACK")?.head_digest.to_string(),
            "witness_digest":ack.witness_receipt.ok_or("original witness ACK")?.witness_digest.to_string(),
            "acknowledged_at":ack.acknowledged_at.ok_or("original ACK time")?,"state_digest":ack.state_digest.to_string()},
        "delivery_denials":denials,"model_weight_forgetting_claimed":false}),
    )
}
