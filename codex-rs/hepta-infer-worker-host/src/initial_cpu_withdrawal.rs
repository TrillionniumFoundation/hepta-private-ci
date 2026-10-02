//! Fixed Root-only development withdrawal using the actual calibrated writer,
//! independently verified replacement and original artifact checkpoint/ACK.
use super::*;
use codex_hepta_agent_components::learning_ledger as ledger;
use codex_hepta_agentd::HostLearningWithdrawalIntentV1;
use codex_hepta_agentd::withdraw_learning_dataset_v1;
use ed25519_dalek::Signer;
use serde::Serialize;
use std::path::PathBuf;
#[path = "initial_cpu_withdrawal_delivery.rs"]
mod delivery;
#[path = "initial_cpu_withdrawal_input_causality.rs"]
mod input_causality;
#[path = "initial_cpu_withdrawal_inspection.rs"]
mod inspection;
#[path = "initial_cpu_withdrawal_inspection_dependencies.rs"]
mod inspection_dependencies;
#[path = "initial_cpu_withdrawal_inspection_source.rs"]
mod inspection_source;
#[path = "initial_cpu_withdrawal_inspection_targets.rs"]
mod inspection_targets;
#[path = "initial_cpu_withdrawal_issuance.rs"]
mod issuance;
#[path = "initial_cpu_withdrawal_source.rs"]
mod source;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    schema: String,
    owner: Source,
    replacement: Source,
    replacement_index: usize,
    calibration_publication: Source,
    calibration_archive: Source,
    calibration_trust_config: Source,
    ledger_directory: PathBuf,
    witness_directory: PathBuf,
    unlearning_private_key_path: PathBuf,
    record_id: String,
    lineage_id: String,
    source_record_id: String,
    artifact_id: String,
    reason_digest: String,
    expected_ledger_head: String,
    expected_artifact_head: String,
    delivery_targets: Vec<String>,
    previous_withdrawals: Vec<Notice>,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Notice {
    notice_id: String,
    dataset_digest: String,
    source_tombstone_digest: String,
    authority_id: String,
    credential_chain_digest: String,
    signing_key_digest: String,
    authority_epoch: u64,
    issued_at: u64,
}
impl Notice {
    fn native(&self) -> HostResult<DatasetWithdrawalNoticeV1> {
        Ok(DatasetWithdrawalNoticeV1 {
            notice_id: id(&self.notice_id)?,
            dataset_digest: digest(&self.dataset_digest)?,
            source_tombstone_digest: digest(&self.source_tombstone_digest)?,
            authority_id: id(&self.authority_id)?,
            credential_chain_digest: digest(&self.credential_chain_digest)?,
            signing_key_digest: digest(&self.signing_key_digest)?,
            authority_epoch: self.authority_epoch,
            issued_at: self.issued_at,
        })
    }
}

pub(super) fn run(path: &Path, pin: Digest32) -> HostResult<Value> {
    let original_request = Source {
        path: path.to_owned(),
        digest: pin.to_string(),
    };
    let request: Request = serde_json::from_slice(&original_request.read(32 * 1024)?)?;
    if request.schema != "hepta.cpu-neuron.dataset-withdrawal-request.v1"
        || request.replacement_index >= 3
        || request.delivery_targets.is_empty()
        || request.delivery_targets.len() > 64
        || request.previous_withdrawals.len() > 64
        || !request.delivery_targets.contains(&request.artifact_id)
    {
        return Err("fixed withdrawal request/schema/bounds/source delivery target".into());
    }
    let owner_inputs = Inputs::read(&request.owner.path, digest(&request.owner.digest)?)?;
    let replacement = Inputs::read(
        &request.replacement.path,
        digest(&request.replacement.digest)?,
    )?;
    let key = role::actual_role(&owner_inputs, &owner_inputs.profile.owner)?;
    if owner_inputs.profile.owner.uid != 0
        || owner_inputs.profile.owner.gid != 0
        || replacement.profile.owner_root != owner_inputs.profile.owner_root
        || replacement.profile.registry_id != owner_inputs.profile.registry_id
        || replacement.profile.owner.id != owner_inputs.profile.owner.id
        || replacement.profile.owner.public_key_hex != owner_inputs.profile.owner.public_key_hex
        || replacement.profile.owner.credential_digest
            != owner_inputs.profile.owner.credential_digest
        || replacement.profile.program != owner_inputs.profile.program
        || replacement.profile.withdrawals()?.scope_digest()
            != owner_inputs.profile.withdrawals()?.scope_digest()
        || replacement.artifacts[request.replacement_index].artifact_id == id(&request.artifact_id)?
    {
        return Err(
            "replacement must be genuine independent evidence under this original Root owner"
                .into(),
        );
    }
    // Reopening is permitted; initialization/reset of either original owner is not.
    source::directory(&owner_inputs.profile.owner_root)?;
    if state::read::<state::OriginalTimeSignature>(&owner_inputs, "lease.json")?.is_none() {
        return Err("withdrawal requires the existing original artifact writer lease".into());
    }
    let mut source_owner = source::open(&request)?;
    let lineage = ledger::UnlearningLineageRequestV1 {
        record_id: id(&request.record_id)?,
        lineage_id: id(&request.lineage_id)?,
        source_record_id: id(&request.source_record_id)?,
        dataset_snapshot_id: source_owner.dataset.snapshot.snapshot_id.clone(),
        dataset_digest: source_owner.dataset.snapshot.dataset_digest,
        artifact_id: id(&request.artifact_id)?,
        reason_digest: digest(&request.reason_digest)?,
    };
    let issuance_path = path
        .parent()
        .ok_or("withdrawal request parent")?
        .join("withdrawal-issuance.json");
    let retained = issuance::read(&issuance_path, pin)?;
    let evidence = match &retained {
        Some(original) => original.evidence.native()?,
        None => ledger::sign_root_learning_unlearning_v1(
            &request.calibration_trust_config.path,
            &request.unlearning_private_key_path,
            source_owner.writer.activated_trust(),
            &lineage,
        )?,
    };
    let intent = HostLearningWithdrawalIntentV1 {
        ledger_predecessor: digest(&request.expected_ledger_head)?,
        lineage,
        dataset: source_owner.dataset,
        evidence,
        artifact_predecessor: digest(&request.expected_artifact_head)?,
    };
    let preview = source_owner.writer.preview_unlearning(
        intent.ledger_predecessor,
        &intent.lineage,
        &intent.dataset,
        &intent.evidence,
        now_ms()?,
    )?;
    if preview.principal().signing_key_digest == Digest32::of_bytes(key.verifying_key().as_bytes())
    {
        return Err(
            "unlearning authority must remain independent of the artifact owner key".into(),
        );
    }
    let mut withdrawals = owner_inputs.profile.withdrawals()?;
    for notice in &request.previous_withdrawals {
        withdrawals.append(notice.native()?)?;
    }
    let mut owner = if retained.is_some() {
        withdrawals.append(notice(&intent, &preview))?;
        publication::open_original(&owner_inputs, &key, withdrawals.clone())?
    } else {
        // Pin the actual public frontier before retaining any issuance or effect.
        ReadOnlyArtifactCurrentOwnerV1::open(
            &owner_inputs.profile.owner_root,
            owner_inputs.trust()?,
            withdrawals.clone(),
            now_ms()?,
        )?;
        publication::open_original(&owner_inputs, &key, withdrawals.clone())?
    };
    let issuance = match retained {
        Some(original) => original,
        None => {
            if owner.registry().head_digest() != intent.artifact_predecessor {
                return Err("withdrawal original artifact predecessor changed".into());
            }
            let before = owner.current_registry_view(now_ms()?)?;
            for target in &request.delivery_targets {
                before
                    .eligible_manifest(&id(target)?)
                    .ok_or("delivery target was not eligible in original CURRENT")?;
            }
            let prepared = owner.prepare_dataset_revocation_from_current(
                &DatasetRevocationRequest {
                    operation_id: intent.lineage.lineage_id.clone(),
                    dataset_digest: intent.lineage.dataset_digest,
                    source_revocation_digest: preview.event_digest(),
                    evaluator_id: preview.principal().principal_id.clone(),
                },
                now_ms()?,
            )?;
            if !prepared
                .summary()
                .direct_artifacts
                .contains(&intent.lineage.artifact_id)
            {
                return Err("handoff artifact lacks complete dataset membership".into());
            }
            let changes = prepared.registry().records()[owner.registry().records().len()..]
                .iter()
                .map(|record| record.event.clone())
                .collect::<Vec<_>>();
            withdrawals.append(notice(&intent, &preview))?;
            owner.install_withdrawal_frontier(withdrawals.clone())?;
            let admitted_at = now_ms()?;
            let admission = admit_manifest_at_withdrawal_head_v3(
                &withdrawals,
                withdrawals.head_digest(),
                replacement.artifacts[request.replacement_index].clone(),
                admitted_at,
            )?;
            let target = owner.preview_publication_with_state_changes(
                intent.lineage.lineage_id.clone(),
                admission,
                &changes,
                admitted_at,
            )?;
            if target.original_signed_head.is_some() {
                return Err("original issuance missing for an existing publication".into());
            }
            let mut signed = SignedCurrentArtifactHeadV1 {
                withdrawal_scope_digest: withdrawals.scope_digest().ok_or("scope")?,
                binding: owner_inputs.storage_binding(),
                witness: RegistryHeadWitnessV1 {
                    registry_id: id(&owner_inputs.profile.registry_id)?,
                    generation: target.generation,
                    head_digest: target.head_digest,
                    predecessor_head_digest: target.predecessor,
                    authority_epoch: 1,
                    signer_id: id(&owner_inputs.profile.owner.id)?,
                    signing_key_digest: Digest32::of_bytes(key.verifying_key().as_bytes()),
                    issued_at: admitted_at,
                    expires_at: owner_inputs
                        .evidence
                        .expires_at()
                        .min(owner_inputs.profile.expires_at_ms),
                },
                signature: [0; 64],
            };
            signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
            let original = issuance::Issuance {
                request_digest: pin.to_string(),
                evidence: ledger::ReviewEvidenceWireV1::from_native(&intent.evidence),
                source_event: preview.source_event_digest().to_string(),
                event: preview.event_digest().to_string(),
                admitted_at,
                head: state::OriginalHead {
                    time: state::OriginalTimeSignature::new(
                        &owner_inputs,
                        admitted_at,
                        signed.witness.expires_at,
                        signed.signature,
                    ),
                    generation: target.generation.get(),
                    predecessor: target.predecessor.to_string(),
                    head: target.head_digest.to_string(),
                },
                suffix: changes
                    .iter()
                    .map(issuance::Change::of)
                    .collect::<HostResult<_>>()?,
                before: issuance::Snapshot::of(before.receipt()),
                delivery_targets: request.delivery_targets.clone(),
            };
            issuance::retain(&issuance_path, &original)?;
            original
        }
    };
    if issuance.event != preview.event_digest().to_string()
        || issuance.source_event != preview.source_event_digest().to_string()
        || issuance.delivery_targets != request.delivery_targets
        || issuance.before.native()?.head_digest != intent.artifact_predecessor
    {
        return Err(
            "retained issuance no longer binds the original canonical event/frontier".into(),
        );
    }
    let changes = issuance
        .suffix
        .iter()
        .map(issuance::Change::native)
        .collect::<HostResult<Vec<_>>>()?;
    let publication_request = LearningArtifactPublishRequestV1 {
        operation_id: intent.lineage.lineage_id.clone(),
        admission: admit_manifest_at_withdrawal_head_v3(
            &withdrawals,
            withdrawals.head_digest(),
            replacement.artifacts[request.replacement_index].clone(),
            issuance.admitted_at,
        )?,
        payload: replacement.payloads[request.replacement_index].clone(),
        signed_current_head: issuance
            .head
            .native(&owner_inputs, owner_inputs.storage_binding())?,
        expected_registry_predecessor_head: intent.artifact_predecessor,
        now: now_ms()?,
    };
    // Source/config/independent evidence are current at the actual effect boundary.
    original_request.read(32 * 1024)?;
    owner_inputs.revalidate()?;
    replacement.revalidate()?;
    let status = owner.publication_status(&publication_request)?;
    let result = if let Some(status) = status {
        // Resume exactly the admitted operation through the existing checkpoint.
        // No renewed signature, new successor or silent authority extension.
        let mut phase = "withdrawal_fence_uncertain";
        let mut source_acknowledgement = None;
        let mut artifact_acknowledgement = None;
        let recovered = (|| -> HostResult<_> {
            owner.require_root_withdrawal_frontier(now_ms()?)?;
            phase = "source_append_uncertain";
            let ack = source_owner.writer.append_unlearning(
                intent.ledger_predecessor,
                intent.lineage.clone(),
                &intent.dataset,
                &intent.evidence,
                now_ms()?,
            )?;
            source_acknowledgement = Some(source_ack(&ack));
            phase = "source_acknowledged";
            if ack.append.event_digest.to_string() != issuance.event {
                return Err("original source ACK changed".into());
            }
            phase = "publication_uncertain";
            if status.status.phase != ArtifactPublicationPhaseV1::Acknowledged {
                let mut original = publication_request.clone();
                original.now = now_ms()?;
                owner.publish_with_state_changes(original, &changes)?;
            }
            let status = owner
                .publication_status(&publication_request)?
                .ok_or("original checkpoint missing")?;
            if status.status.phase != ArtifactPublicationPhaseV1::Acknowledged {
                return Err("original publication has no durable ACK".into());
            }
            artifact_acknowledgement = Some(artifact_ack(&status));
            phase = "artifact_acknowledged_frontier_uncertain";
            owner.publish_root_read_frontier(now_ms()?)?;
            Ok((ack, status))
        })();
        recovered.map_err(|error| {
            partial(
                pin,
                phase,
                source_acknowledgement,
                artifact_acknowledgement,
                &issuance_path,
                &error.to_string(),
            )
        })
    } else {
        withdraw_learning_dataset_v1(
            &mut source_owner.writer,
            &mut owner,
            &intent,
            |_, suffix, now| {
                if suffix != changes {
                    return Err("original full suffix changed".into());
                }
                let mut original = publication_request.clone();
                original.now = now;
                Ok(original)
            },
        )
        .map_err(|error| {
            partial(
                pin,
                &format!("{:?}", error.phase),
                error.source_ack.map(|ack| source_ack(&ack)),
                error.publication_ack.as_ref().map(publication_receipt),
                &issuance_path,
                &error.detail,
            )
        })
        .and_then(|receipt| {
            let source = source_ack(&receipt.source);
            owner
                .publication_status(&publication_request)
                .map_err(|e| {
                    partial(
                        pin,
                        "artifact_acknowledged_status_unavailable",
                        Some(source.clone()),
                        Some(publication_receipt(&receipt.publication)),
                        &issuance_path,
                        &e.to_string(),
                    )
                })
                .and_then(|status| {
                    status
                        .map(|status| (receipt.source, status))
                        .ok_or_else(|| {
                            partial(
                                pin,
                                "artifact_acknowledged_status_unavailable",
                                Some(source),
                                None,
                                &issuance_path,
                                "checkpoint missing",
                            )
                        })
                })
        })
    };
    let (ack, status) = match result {
        Ok(value) => value,
        Err(partial) => return Ok(partial),
    };
    let denied = match delivery::deny(&owner_inputs, &withdrawals, &issuance) {
        Ok(denied) => denied,
        Err(error) => {
            return Ok(partial(
                pin,
                "artifact_acknowledged_delivery_unavailable",
                Some(source_ack(&ack)),
                Some(artifact_ack(&status)),
                &issuance_path,
                &error.to_string(),
            ));
        }
    };
    Ok(
        serde_json::json!({"schema":"hepta.cpu-neuron.dataset-withdrawal-result.v1",
        "request_digest":pin.to_string(),"phase":"artifact_acknowledged", "source_ack":source_ack(&ack),
        "artifact_ack":artifact_ack(&status), "withdrawal_head":withdrawals.head_digest().to_string(),
        "delivery_denials":denied,"model_weight_forgetting_claimed":false}),
    )
}
fn notice(
    intent: &HostLearningWithdrawalIntentV1,
    preview: &ledger::UnlearningLineagePreviewV1,
) -> DatasetWithdrawalNoticeV1 {
    let principal = preview.principal();
    DatasetWithdrawalNoticeV1 {
        notice_id: intent.lineage.lineage_id.clone(),
        dataset_digest: intent.lineage.dataset_digest,
        source_tombstone_digest: preview.event_digest(),
        authority_id: principal.principal_id.clone(),
        credential_chain_digest: principal.credential_chain_digest,
        signing_key_digest: principal.signing_key_digest,
        authority_epoch: principal.authority_epoch,
        issued_at: intent.evidence.issued_at,
    }
}
fn source_ack(ack: &ledger::UnlearningLineageReceiptV1) -> Value {
    serde_json::json!({"lineage_id":ack.lineage_id.as_str(),"source_record_id":ack.source_record_id.as_str(),
        "source_event_digest":ack.source_event_digest.to_string(),"dataset_snapshot_id":ack.dataset_snapshot_id.as_str(),
        "dataset_digest":ack.dataset_digest.to_string(),"artifact_id":ack.artifact_id.as_str(),
        "append_disposition":format!("{:?}",ack.append.disposition),"sequence":ack.append.sequence.get(),
        "event_digest":ack.append.event_digest.to_string(),"chain_digest":ack.append.chain_digest.to_string()})
}

fn publication_receipt(ack: &ArtifactPublicationReceiptV1) -> Value {
    serde_json::json!({"operation_id":ack.operation_id.as_str(),
        "admission_digest":ack.admission_digest.to_string(),"registry_head":ack.registry_head_digest.to_string(),
        "witness_digest":ack.witness_digest.to_string(),"acknowledged_at":ack.acknowledged_at,
        "state_digest":ack.state_digest.to_string()})
}

fn artifact_ack(status: &LearningArtifactPublicationStatusV1) -> Value {
    serde_json::json!({"operation_id":status.status.operation_id.as_str(),
        "request_identity_digest":status.request_identity_digest.to_string(),
        "phase":format!("{:?}",status.status.phase),
        "registry_head":status.status.registry_head_digest.map(|d|d.to_string()),
        "witness_digest":status.status.witness_digest.map(|d|d.to_string()),
        "acknowledged_at":status.status.acknowledged_at,"state_digest":status.status.state_digest.to_string()})
}
fn partial(
    pin: Digest32,
    phase: &str,
    source: Option<Value>,
    artifact: Option<Value>,
    issuance: &Path,
    detail: &str,
) -> Value {
    serde_json::json!({"schema":"hepta.cpu-neuron.dataset-withdrawal-result.v1","request_digest":pin.to_string(),
        "phase":phase,"source_ack":source,"artifact_ack":artifact,"original_issuance":issuance,
        "detail":detail,"delivery_denials":[],"model_weight_forgetting_claimed":false})
}

pub(super) fn inspect(path: &Path, pin: Digest32) -> HostResult<Value> {
    inspection::run(path, pin)
}
