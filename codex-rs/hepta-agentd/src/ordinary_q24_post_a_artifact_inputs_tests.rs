//! External Artifact controller inputs for the ordinary process fixture.
//! The controller previews a public Register event; it never opens a writer,
//! publishes an Artifact, selects inside the daemon or certifies C completion.

use std::fs::File;

use codex_hepta_learning_artifacts::*;
use codex_hepta_neuron::CellBackendManifestV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde_json::json;

use super::post_a_plan::OriginalPostAPlan;
use crate::authority_host_runtime::PublicationInputData;
use crate::cell_q24_publication_driver::validation::Decision;

pub(super) fn write_original_writer_input(plan: &OriginalPostAPlan) -> anyhow::Result<()> {
    let inputs = &plan.root.publication_inputs;
    let trust = inputs.owner_trust.original_owner_trust()?;
    let key = SigningKey::from_bytes(&[61; 32]);
    let signer = trust
        .writer_signers
        .iter()
        .find(|signer| signer.signer_id.as_str() == "test-artifact-authority")
        .ok_or_else(|| anyhow::anyhow!("original Artifact controller absent"))?;
    anyhow::ensure!(
        signer.verifying_key == key.verifying_key().to_bytes(),
        "configured Artifact controller differs from the original public key"
    );
    let initial = plan.profile.original_initial_data()?;
    let now = crate::authbus_ingress::now_ms()?;
    let expiry = original_expiry(plan, now)?.min(signer.expires_at);
    anyhow::ensure!(
        now >= signer.valid_from && now < expiry && signer.revoked_at.is_none(),
        "original Artifact controller validity"
    );
    let mut signed = SignedArtifactWriterLeaseV1 {
        lease_id: StableId::new("ordinary-post-a-artifact-writer")?,
        producer_id: initial.owners.trainer,
        registry_id: trust.registry_id,
        withdrawal_scope_digest: trust.withdrawal_scope_digest,
        signer_id: signer.signer_id.clone(),
        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
        authority_epoch: signer.minimum_authority_epoch,
        lease_generation: 2,
        issued_at: now,
        expires_at: expiry,
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    plan.resources
        .owners
        .writer_lease
        .write_original_once(&serde_json::to_vec(&json!({
            "lease_id":signed.lease_id.to_string(),"producer_id":signed.producer_id.to_string(),
            "registry_id":signed.registry_id.to_string(),
            "withdrawal_scope_digest":signed.withdrawal_scope_digest.into_array(),
            "signer_id":signed.signer_id.to_string(),
            "signing_key_digest":signed.signing_key_digest.into_array(),
            "authority_epoch":signed.authority_epoch,"lease_generation":signed.lease_generation,
            "issued_at":signed.issued_at,"expires_at":signed.expires_at,
            "signature":signed.signature.to_vec()
        }))?)
}

pub(super) fn write_original_candidate_head(
    plan: &OriginalPostAPlan,
    decision: &Decision,
    manifest: &CellBackendManifestV2,
) -> anyhow::Result<SignedCurrentArtifactHeadV1> {
    decision.require_root_publication()?;
    anyhow::ensure!(decision.adopts(), "retention has no candidate publication");
    let now = crate::authbus_ingress::now_ms()?;
    let expires = original_expiry(plan, now)?;
    let inputs = &plan.root.publication_inputs;
    let reader = original_reader(inputs, now)?;
    let current = reader.read_original_registry(now)?;
    let registry = read_registry(inputs, current.receipt())?;
    let withdrawals = reader.read_original_withdrawals()?;
    let admission = admit_manifest_at_withdrawal_head_v3(
        &withdrawals,
        withdrawals.head_digest(),
        original_manifest(decision, manifest, now, expires)?,
        now,
    )?;
    let transaction = ArtifactPublicationTransactionV1::begin(
        decision.artifact_operation.clone(),
        admission.clone(),
        &withdrawals,
        &registry,
        current.receipt().head_digest,
        now,
    )?;
    let material = &admission.validated_manifest.manifest;
    let candidate = ArtifactManifest {
        artifact_id: material.artifact_id.clone(),
        kind: material.kind,
        generation: material.generation,
        predecessor_id: material.rollback_predecessor.clone(),
        content_digest: material.bytes_digest,
        objective_digest: material.objective_class_digest,
        support_digest: admission.validated_manifest.manifest_digest,
        producer_id: material.producer_id.clone(),
        compatibility_digest: material.compatibility_digest,
        encoded_size_bytes: material.encoded_size_bytes,
    };
    let mut preview = registry.clone();
    preview.append(ArtifactEvent::Register {
        event_id: StableId::new(format!(
            "artifact-publication:{}",
            transaction.intent().intent_digest
        ))?,
        manifest: candidate,
    })?;
    let original = inputs.retained_current.original_current()?;
    let key = SigningKey::from_bytes(&[61; 32]);
    let mut signed = SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: admission.withdrawal_scope_digest,
        binding: Digest32::from_array(inputs.storage_binding),
        witness: RegistryHeadWitnessV1 {
            registry_id: original.witness.registry_id,
            generation: Generation::new(preview.records().len() as u64)?,
            head_digest: preview.snapshot().head_digest,
            predecessor_head_digest: current.receipt().head_digest,
            authority_epoch: original.witness.authority_epoch,
            signer_id: original.witness.signer_id,
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            issued_at: now,
            expires_at: expires,
        },
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    let after = reader.read_original_registry(crate::authbus_ingress::now_ms()?)?;
    anyhow::ensure!(
        after.receipt() == current.receipt()
            && after.witness_digest() == current.witness_digest()
            && reader.read_original_withdrawals()?.snapshot() == withdrawals.snapshot(),
        "original Artifact state changed during controller preview"
    );
    // The only mutation is the originally reserved signed INPUT file. The
    // real ordinary daemon is still the sole Artifact publication writer.
    let data = super::super::data::CurrentData::capture(&signed)?;
    plan.resources
        .owners
        .candidate_head
        .write_original_once(&serde_json::to_vec(&data)?)?;
    Ok(signed)
}

pub(super) fn original_reader(
    inputs: &PublicationInputData,
    now: u64,
) -> anyhow::Result<LearningArtifactReadViewV1> {
    let receipt = &inputs.withdrawal;
    let floor = read_dataset_withdrawal_snapshot(
        File::open(&inputs.withdrawal_file)?,
        DatasetWithdrawalSnapshotReceiptV1 {
            binding: Digest32::from_array(receipt.binding),
            scope_digest: Digest32::from_array(receipt.scope),
            head_digest: Digest32::from_array(receipt.head),
            file_digest: Digest32::from_array(receipt.file_digest),
            records: receipt.records,
            encoded_bytes: receipt.encoded_bytes,
        },
    )?;
    Ok(LearningArtifactReadViewV1::open_original(
        inputs.artifact_root.clone(),
        /*consumer_uid*/ 60001,
        inputs.owner_trust.original_owner_trust()?,
        inputs.retained_current.original_current()?,
        now,
    )?
    .with_original_withdrawal_floor(Digest32::from_array(inputs.storage_binding), floor)?)
}

pub(super) fn read_registry(
    inputs: &PublicationInputData,
    receipt: RegistrySnapshotReceipt,
) -> anyhow::Result<ArtifactRegistry> {
    Ok(read_registry_snapshot(
        File::open(inputs.artifact_root.join("registries").join(format!(
            "{}-{}.snapshot",
            receipt.head_digest, receipt.file_digest
        )))?,
        receipt,
    )?)
}

pub(super) fn original_expiry(plan: &OriginalPostAPlan, now: u64) -> anyhow::Result<u64> {
    anyhow::ensure!(
        std::time::Instant::now() < plan.resources.end,
        "original process operation deadline"
    );
    let initial = plan.profile.original_initial_data()?;
    let expiry = initial
        .request
        .envelope
        .expiry_unix_seconds
        .checked_mul(1_000)
        .ok_or_else(|| anyhow::anyhow!("original Artifact input expiry overflow"))?
        .min(plan.root.publication_inputs.retained_current.expires_at);
    anyhow::ensure!(now < expiry, "original Artifact input window expired");
    Ok(expiry)
}

fn original_manifest(
    decision: &Decision,
    original: &CellBackendManifestV2,
    now: u64,
    expires: u64,
) -> anyhow::Result<LearningArtifactManifestV2> {
    let bundle = &decision.bundle;
    crate::cell_composed_q24::validate_manifest(bundle, original)?;
    let lineage = bundle
        .training_lineage
        .as_ref()
        .ok_or_else(|| anyhow::anyhow!("actual trained candidate lineage absent"))?;
    let payload = serde_json::to_vec(original)?;
    let mut lineage_digests = vec![
        lineage.source_bundle,
        lineage.dataset,
        lineage.update_rule,
        lineage.evaluation_profile,
    ];
    lineage_digests.extend(
        decision
            .snapshot
            .receipts
            .iter()
            .filter(|receipt| {
                matches!(
                    receipt.observation,
                    LearningIterationObservationV1::Training { .. }
                        | LearningIterationObservationV1::Evaluation { .. }
                        | LearningIterationObservationV1::Proposal { .. }
                        | LearningIterationObservationV1::LocalDecisionV2(_)
                )
            })
            .map(|receipt| receipt.evidence_digest),
    );
    lineage_digests.sort_unstable();
    lineage_digests.dedup();
    Ok(LearningArtifactManifestV2 {
        artifact_id: bundle.artifact_id.clone(),
        kind: ArtifactKind::Model,
        generation: bundle.generation,
        provenance_mode: ProvenanceModeV1::DatasetDerived,
        source_dataset_digests: vec![lineage.dataset],
        lineage_digests,
        predecessor_ids: vec![
            decision
                .snapshot
                .request
                .selected_bundle
                .artifact_id
                .clone(),
        ],
        rollback_predecessor: Some(
            decision
                .snapshot
                .request
                .selected_bundle
                .artifact_id
                .clone(),
        ),
        bytes_digest: Digest32::of_bytes(&payload),
        encoded_size_bytes: payload.len() as u64,
        training_code_digest: Digest32::from_array(original.source_digest),
        runtime_tuple_digest: Digest32::from_array(original.runtime_digest),
        device_profile_digest: Digest32::from_array(original.device_digest),
        objective_class_digest: decision.snapshot.request.envelope.objective_digest,
        compatibility_digest: Digest32::from_array(original.digest()?),
        schema_profile_digest: bundle.components.state_schema,
        normalization_digest: bundle.components.normalizer,
        producer_id: decision.snapshot.owners.trainer.clone(),
        created_at: now,
        expires_at: expires,
    })
}
