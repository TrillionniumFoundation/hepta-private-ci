//! Ephemeral research owner. Public fixture keys are never production trust.

use std::collections::BTreeMap;
use std::fs;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_learning_artifacts::*;
use codex_hepta_neuron::trained_cell_compatibility_digest_v5;
use codex_hepta_neuron::trained_cell_normalization_digest_v5;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde_json::Value;
use serde_json::json;

use crate::Result;
use crate::ensure;
use crate::report::Inputs;

pub(crate) fn id(value: &str) -> Result<StableId> {
    Ok(StableId::new(value)?)
}
pub(crate) fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
pub(crate) fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

pub(crate) fn trust(key: &SigningKey, name: &str, now: u64) -> Result<TrustedArtifactSignerV1> {
    Ok(TrustedArtifactSignerV1 {
        signer_id: id(name)?,
        verifying_key: key.verifying_key().to_bytes(),
        minimum_authority_epoch: 1,
        maximum_authority_epoch: 1,
        valid_from: now,
        expires_at: now + 3600,
        revoked_at: None,
    })
}

pub(crate) fn manifest(
    name: &str,
    payload: &[u8],
    previous: Option<StableId>,
    inputs: &Inputs,
    now: u64,
) -> Result<LearningArtifactManifestV2> {
    let schema = trained_cell_compatibility_digest_v5();
    Ok(LearningArtifactManifestV2 {
        artifact_id: id(name)?,
        kind: ArtifactKind::Parameters,
        generation: Generation::new(if previous.is_some() { 2 } else { 1 })?,
        provenance_mode: ProvenanceModeV1::DatasetDerived,
        source_dataset_digests: vec![inputs.dataset_digest],
        lineage_digests: vec![inputs.report_digest, inputs.gate_digest],
        predecessor_ids: previous.iter().cloned().collect(),
        rollback_predecessor: previous,
        bytes_digest: Digest32::of_bytes(payload),
        encoded_size_bytes: payload.len() as u64,
        training_code_digest: inputs.code_digest,
        runtime_tuple_digest: inputs.runtime_digest,
        device_profile_digest: digest("research-qualification-linux-x86_64-cpu.v1"),
        objective_class_digest: inputs.policy.protocol_digest,
        compatibility_digest: schema,
        schema_profile_digest: schema,
        normalization_digest: trained_cell_normalization_digest_v5(),
        producer_id: id("research-bundle-exporter")?,
        created_at: now,
        expires_at: now + 3600,
    })
}

pub(crate) fn request(
    key: &SigningKey,
    registry: &ArtifactRegistry,
    withdrawals: &DatasetWithdrawalRegistry,
    manifest: LearningArtifactManifestV2,
    payload: Vec<u8>,
    now: u64,
) -> Result<LearningArtifactPublishRequestV1> {
    let operation_id = id(&format!("research-import-{}", manifest.artifact_id))?;
    let admission = admit_manifest_at_withdrawal_head_v3(
        withdrawals,
        withdrawals.head_digest(),
        manifest.clone(),
        now,
    )?;
    let predecessor = registry.snapshot().head_digest;
    let transaction = ArtifactPublicationTransactionV1::begin(
        operation_id.clone(),
        admission.clone(),
        withdrawals,
        registry,
        predecessor,
        now,
    )?;
    let mut staged = registry.clone();
    staged.append(ArtifactEvent::Register {
        event_id: id(&format!(
            "artifact-publication:{}",
            transaction.intent().intent_digest
        ))?,
        manifest: ArtifactManifest {
            artifact_id: manifest.artifact_id,
            kind: manifest.kind,
            generation: manifest.generation,
            predecessor_id: manifest.predecessor_ids.first().cloned(),
            content_digest: manifest.bytes_digest,
            objective_digest: manifest.objective_class_digest,
            support_digest: admission.validated_manifest.manifest_digest,
            producer_id: manifest.producer_id,
            compatibility_digest: manifest.compatibility_digest,
            encoded_size_bytes: manifest.encoded_size_bytes,
        },
    })?;
    let mut signed_current_head = SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: withdrawals
            .scope_digest()
            .ok_or("missing withdrawal scope")?,
        binding: digest("ephemeral-research-storage.v1"),
        witness: RegistryHeadWitnessV1 {
            registry_id: id("research-artifacts")?,
            generation: Generation::new(staged.records().len() as u64)?,
            head_digest: staged.snapshot().head_digest,
            predecessor_head_digest: predecessor,
            authority_epoch: 1,
            signer_id: id("research-owner-ephemeral")?,
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            issued_at: now,
            expires_at: now + 3600,
        },
        signature: [0; 64],
    };
    signed_current_head.signature = key.sign(&signed_current_head.signing_bytes()).to_bytes();
    Ok(LearningArtifactPublishRequestV1 {
        operation_id,
        admission,
        payload,
        signed_current_head,
        expected_registry_predecessor_head: predecessor,
        now,
    })
}

pub(crate) fn inventory(root: &Path) -> Result<BTreeMap<PathBuf, Vec<u8>>> {
    let mut files = BTreeMap::new();
    for entry in fs::read_dir(root)? {
        let path = entry?.path();
        if path.is_dir() {
            files.extend(inventory(&path)?);
        } else {
            files.insert(path.clone(), fs::read(path)?);
        }
    }
    Ok(files)
}

pub fn reject(inputs: &Inputs, root: &Path, now: u64) -> Result<Value> {
    fs::create_dir(root)?;
    // Deliberately public, reproducible qualification identities, with no
    // relationship to any installed reviewer or product owner credentials.
    let owner_key = SigningKey::from_bytes(&[33; 32]);
    let reviewer_key = SigningKey::from_bytes(&[34; 32]);
    let scope = DatasetWithdrawalScopeV1 {
        authority_domain_id: id("ephemeral-research-authority")?,
        registry_id: id("research-withdrawals")?,
        scope_id: id("v5-typed-qualification")?,
    };
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope.clone());
    let owner_trust = ArtifactOwnerTrustV1 {
        registry_id: id("research-artifacts")?,
        withdrawal_scope_digest: scope.digest(),
        minimum_registry_generation: Generation::new(1)?,
        genesis_predecessor_head_digest: Digest32::ZERO,
        minimum_authority_epoch: 1,
        writer_signers: vec![trust(&owner_key, "research-owner-ephemeral", now)?],
        head_signers: vec![trust(&owner_key, "research-owner-ephemeral", now)?],
    };
    let mut lease = SignedArtifactWriterLeaseV1 {
        lease_id: id("research-writer")?,
        producer_id: id("research-bundle-exporter")?,
        registry_id: id("research-artifacts")?,
        withdrawal_scope_digest: scope.digest(),
        signer_id: id("research-owner-ephemeral")?,
        signing_key_digest: Digest32::of_bytes(&owner_key.verifying_key().to_bytes()),
        authority_epoch: 1,
        lease_generation: 1,
        issued_at: now,
        expires_at: now + 3600,
        signature: [0; 64],
    };
    lease.signature = owner_key.sign(&lease.signing_bytes()).to_bytes();
    let mut service = LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
        root: root.to_path_buf(),
        trust: owner_trust,
        writer_lease: lease,
        required_current_head: None,
        withdrawal_registry: withdrawals.clone(),
        storage_binding: digest("ephemeral-research-storage.v1"),
        now,
    })?;
    let baseline = request(
        &owner_key,
        service.registry(),
        &withdrawals,
        manifest(
            "all12-typed-warmup-v5",
            &inputs.predecessor,
            None,
            inputs,
            now,
        )?,
        inputs.predecessor.clone(),
        now,
    )?;
    let baseline_receipt = service.publish(baseline)?;
    ensure(
        !baseline_receipt.authority.grants_any(),
        "baseline imported with authority",
    )?;
    let candidate_request = request(
        &owner_key,
        service.registry(),
        &withdrawals,
        manifest(
            "all12-typed-candidate-v5",
            &inputs.candidate,
            Some(id("all12-typed-warmup-v5")?),
            inputs,
            now,
        )?,
        inputs.candidate.clone(),
        now,
    )?;
    let before = inventory(root)?;
    let before_head = service.registry().snapshot().head_digest;
    let mut review = SignedScientificCandidateReviewV1 {
        reviewer_id: id("research-reviewer-ephemeral")?,
        operation_id: candidate_request.operation_id.clone(),
        authority_epoch: 1,
        policy_digest: inputs.policy.digest(),
        admission_digest: candidate_request.admission.admission_digest,
        expected_registry_predecessor_head: candidate_request.expected_registry_predecessor_head,
        report_digest: inputs.report_digest,
        task: inputs.measurements[0].clone(),
        retention: inputs.measurements[1].clone(),
        total_cost: inputs.measurements[2].clone(),
        issued_at: now,
        expires_at: now + 300,
        signature: [0; 64],
    };
    review.signature = reviewer_key.sign(&review.signing_bytes()).to_bytes();
    let mut signed_review_bytes = review.signing_bytes();
    signed_review_bytes.extend_from_slice(&review.signature);
    let signed_review_digest = Digest32::of_bytes(&signed_review_bytes);
    let review_archive = (!inputs.all_numeric_gates_pass).then(|| {
        json!({
            "encoding":"native V1 canonical signing bytes followed by 64-byte Ed25519 signature",
            "signed_review_hex":hex(&signed_review_bytes),
            "reviewer_public_key_hex":hex(&reviewer_key.verifying_key().to_bytes()),
            "trust_scope":"public ephemeral research identity only",
        })
    });
    let mut publisher = ScientificCandidatePublisherV1::new(
        service,
        inputs.policy.clone(),
        trust(&reviewer_key, "research-reviewer-ephemeral", now)?,
    )?;
    // Even an unexpectedly passing research report cannot obtain admission from
    // this negative-only driver. It lacks independently installed host review.
    let evidence = if inputs.all_numeric_gates_pass {
        ScientificReviewEvidenceV1::Missing
    } else {
        ScientificReviewEvidenceV1::Signed(Box::new(review))
    };
    let outcome = publisher.publish(candidate_request, evidence);
    let rejected = match outcome {
        Err(ScientificCandidateReviewError::GateFailed(name)) => format!("GateFailed({name})"),
        Err(ScientificCandidateReviewError::GateUnavailable(name)) => {
            format!("GateUnavailable({name})")
        }
        Err(ScientificCandidateReviewError::MissingReview) if inputs.all_numeric_gates_pass => {
            "MissingIndependentHostReview".to_string()
        }
        other => {
            return Err(format!("unexpected rejection qualification result: {other:?}").into());
        }
    };
    let after = inventory(root)?;
    ensure(
        before == after
            && publisher.registry().snapshot().head_digest == before_head
            && publisher.registry().records().len() == 1
            && publisher
                .registry()
                .manifest(&id("all12-typed-candidate-v5")?)
                .is_none(),
        "owner state changed during rejected admission",
    )?;
    let inventory_hashes: BTreeMap<_, _> = before
        .iter()
        .map(|(path, bytes)| {
            (
                path.strip_prefix(root)
                    .unwrap_or(path)
                    .to_string_lossy()
                    .to_string(),
                Digest32::of_bytes(bytes).to_string(),
            )
        })
        .collect();
    Ok(
        json!({"schema":"hepta.real-report-native-rejection.v5","native_result":rejected,"all_numeric_gates_pass":inputs.all_numeric_gates_pass,"signed_negative_review_submitted":!inputs.all_numeric_gates_pass,"review_digest":signed_review_digest.to_string(),"review_archive":review_archive,"policy_digest":inputs.policy.digest().to_string(),"protocol_sha256":inputs.policy.protocol_digest.to_string(),"report_sha256":inputs.report_digest.to_string(),"gate_input_sha256":inputs.gate_digest.to_string(),"candidate_sha256":Digest32::of_bytes(&inputs.candidate).to_string(),"predecessor_sha256":Digest32::of_bytes(&inputs.predecessor).to_string(),"before_registry_head":before_head.to_string(),"after_registry_head":publisher.registry().snapshot().head_digest.to_string(),"owner_bytes_unchanged":true,"owner_file_sha256":inventory_hashes,"aggregates":inputs.aggregate,"candidate_published":false,"production_authority":false,"activation":false,"trust_scope":"public ephemeral research owner/reviewer keys; no production trust installed","parameter_scope":"actual all12 typed float64 linear/gated native serving payload; scientific rejection prevents candidate publication and activation"}),
    )
}
