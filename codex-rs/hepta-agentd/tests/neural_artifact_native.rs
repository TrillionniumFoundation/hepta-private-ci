//! Opt-in publication of real, externally pinned neural bytes through the
//! original artifact owner. A controlled local signer grants material storage
//! only. This test does not issue model qualification, selection or FinalUse.

#![cfg(target_os = "linux")]

use std::error::Error;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::{self};
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::DirBuilderExt;
use std::path::Path;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_learning_artifacts as artifacts;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde::Deserialize;

type Result<T> = std::result::Result<T, Box<dyn Error>>;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Input {
    schema: String,
    chain: PathBuf,
    parent: PathBuf,
    parent_sha256: String,
    training_input: PathBuf,
    training_input_sha256: String,
    training_receipt: PathBuf,
    training_receipt_sha256: String,
    output: PathBuf,
}

fn id(text: &str) -> StableId {
    StableId::new(text).unwrap()
}
fn hash(text: &str) -> Digest32 {
    Digest32::of_bytes(text.as_bytes())
}
fn seconds() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs()
}
fn bounded(path: &Path, maximum: u64) -> Result<Vec<u8>> {
    if !path.is_absolute() || !fs::symlink_metadata(path)?.file_type().is_file() {
        return Err("regular absolute input required".into());
    }
    let file = File::open(path)?;
    let length = file.metadata()?.len();
    if length == 0 || length > maximum {
        return Err("native input size bound".into());
    }
    let mut bytes = Vec::new();
    file.take(maximum + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 != length {
        return Err("native input changed while reading".into());
    }
    Ok(bytes)
}
fn pinned(path: &Path, expected: &str, maximum: u64) -> Result<Vec<u8>> {
    let bytes = bounded(path, maximum)?;
    if Digest32::of_bytes(&bytes) != expected.parse()? {
        return Err("native input SHA256 differs from retained pin".into());
    }
    Ok(bytes)
}

#[test]
#[ignore = "requires HEPTA_PN3_ARTIFACT_NATIVE_CONFIG with downloaded real weights and retained training evidence"]
fn real_smollm_material_publishes_and_recovers_through_original_artifact_owner() -> Result<()> {
    let config = std::env::var_os("HEPTA_PN3_ARTIFACT_NATIVE_CONFIG")
        .ok_or("explicit native configuration required")?;
    let input: Input = serde_json::from_slice(&bounded(Path::new(&config), 65_536)?)?;
    if input.schema != "hepta-smollm-artifact-native-v1"
        || !input.output.is_absolute()
        || !input.chain.is_absolute()
    {
        return Err("native artifact schema/absolute project paths".into());
    }
    let raw_parent = pinned(&input.parent, &input.parent_sha256, 65_536)?;
    let parent: serde_json::Value = serde_json::from_slice(&raw_parent)?;
    let source = PathBuf::from(parent["directory"].as_str().ok_or("parent directory")?);
    let payload_digest: Digest32 = parent["file_sha256"]
        .as_str()
        .ok_or("parameter SHA256")?
        .parse()?;
    let payload = pinned(
        &source.join("artifact.safetensors"),
        &payload_digest.to_string(),
        2 * 1024 * 1024,
    )?;
    let training_input = pinned(&input.training_input, &input.training_input_sha256, 65_536)?;
    let training_receipt = pinned(
        &input.training_receipt,
        &input.training_receipt_sha256,
        4 * 1024 * 1024,
    )?;
    let training: serde_json::Value = serde_json::from_slice(&training_receipt)?;
    if parent["schema"] != "hepta-smollm-parent-material-v1"
        || training["outcome"] != "success"
        || training["phase"] != "train"
        || training["actual_backend"] != "cpu"
        || training["generation"] != parent["generation"]
        || training["artifact"] != parent["adapter"]
        || training["contract"] != parent["contract"]
        || training["operation_id"] != parent["operation_id"]
        || training["input_sha256"].as_str() != Some(input.training_input_sha256.as_str())
        || training["authority"]["installation_authorized"] != false
        || training["authority"]["independent_accepted"] != false
    {
        return Err("native source differs from retained unqualified CPU training evidence".into());
    }
    let training_code = bounded(
        &input.chain.join("scripts/llm_inherited_runtime.py"),
        1024 * 1024,
    )?;
    let training_code_digest = Digest32::of_bytes(&training_code);
    if training["source_pins"]["llm_inherited_runtime.py"].as_str()
        != Some(training_code_digest.to_string().as_str())
    {
        return Err("runtime source differs from actual training pin".into());
    }
    fs::DirBuilder::new().mode(0o700).create(&input.output)?;
    let root = input.output.join("original-artifact-owner");
    let now = seconds();
    let until = now + 3600;
    let key = SigningKey::from_bytes(&[73; 32]);
    let public_key = key.verifying_key().to_bytes();
    let namespace = Digest32::of_bytes(input.output.to_string_lossy().as_bytes());
    let withdrawals =
        artifacts::DatasetWithdrawalRegistry::new_scoped(artifacts::DatasetWithdrawalScopeV1 {
            authority_domain_id: id("controlled-material-test-operator"),
            registry_id: id(&format!("material-withdrawals-{namespace}")),
            scope_id: id("controlled-material-storage-only"),
        });
    let signer = artifacts::TrustedArtifactSignerV1 {
        signer_id: id("controlled-material-publisher"),
        verifying_key: public_key,
        minimum_authority_epoch: 1,
        maximum_authority_epoch: 1,
        valid_from: now,
        expires_at: until,
        revoked_at: None,
    };
    let trust = artifacts::ArtifactOwnerTrustV1 {
        registry_id: id(&format!("material-registry-{namespace}")),
        withdrawal_scope_digest: withdrawals.scope_digest().unwrap(),
        minimum_registry_generation: Generation::new(1)?,
        genesis_predecessor_head_digest: Digest32::ZERO,
        minimum_authority_epoch: 1,
        writer_signers: vec![signer.clone()],
        head_signers: vec![signer],
    };
    let producer = id("controlled-external-neural-material-import");
    let mut lease = artifacts::SignedArtifactWriterLeaseV1 {
        lease_id: id("controlled-material-writer"),
        producer_id: producer.clone(),
        registry_id: trust.registry_id.clone(),
        withdrawal_scope_digest: trust.withdrawal_scope_digest,
        signer_id: id("controlled-material-publisher"),
        signing_key_digest: Digest32::of_bytes(&public_key),
        authority_epoch: 1,
        lease_generation: 1,
        issued_at: now,
        expires_at: until,
        signature: [0; 64],
    };
    lease.signature = key.sign(&lease.signing_bytes()).to_bytes();
    let binding = hash("controlled-neural-material-storage-v1");
    let mut owner_config = artifacts::LearningArtifactOwnerServiceConfigV1 {
        root: root.clone(),
        trust: trust.clone(),
        writer_lease: lease,
        required_current_head: None,
        withdrawal_registry: withdrawals,
        storage_binding: binding,
        now,
    };
    let mut service = artifacts::LearningArtifactOwnerService::open(owner_config.clone())?;
    let source_manifest = artifacts::LearningArtifactManifestV2 {
        artifact_id: id(&format!("downloaded-neural-{payload_digest}")),
        kind: artifacts::ArtifactKind::Parameters,
        generation: Generation::new(parent["generation"].as_u64().ok_or("parent generation")?)?,
        provenance_mode: artifacts::ProvenanceModeV1::DatasetDerived,
        // Exact external training input bytes, not an invented Hepta dataset
        // receipt or the independent holdout's dataset identity.
        source_dataset_digests: vec![Digest32::of_bytes(&training_input)],
        lineage_digests: vec![
            Digest32::of_bytes(&raw_parent),
            Digest32::of_bytes(&training_receipt),
        ],
        predecessor_ids: Vec::new(),
        rollback_predecessor: None,
        bytes_digest: payload_digest,
        encoded_size_bytes: payload.len() as u64,
        training_code_digest,
        runtime_tuple_digest: Digest32::of_bytes(&serde_json::to_vec(&training["source_pins"])?),
        device_profile_digest: hash("smollm2-135m-cpu-float32-rank4-alpha8-v1"),
        objective_class_digest: hash("controlled-material-publication-no-efficacy-claim"),
        compatibility_digest: parent["contract"]
            .as_str()
            .ok_or("parent contract")?
            .parse()?,
        schema_profile_digest: hash("safetensors-named-factor-tensors-v1"),
        normalization_digest: hash("unmodified-F32-LoRA-factors"),
        producer_id: producer,
        created_at: now,
        expires_at: until,
    };
    let before = service.registry().snapshot().head_digest;
    let withdrawal = service.withdrawal_registry();
    let admission = artifacts::admit_manifest_at_withdrawal_head_v3(
        withdrawal,
        withdrawal.head_digest(),
        source_manifest.clone(),
        now,
    )?;
    let operation = id("publish-downloaded-neural-material");
    let transaction = artifacts::ArtifactPublicationTransactionV1::begin(
        operation.clone(),
        admission.clone(),
        withdrawal,
        service.registry(),
        before,
        now,
    )?;
    let manifest = artifacts::ArtifactManifest {
        artifact_id: source_manifest.artifact_id.clone(),
        kind: source_manifest.kind,
        generation: source_manifest.generation,
        predecessor_id: None,
        content_digest: payload_digest,
        objective_digest: source_manifest.objective_class_digest,
        support_digest: admission.validated_manifest.manifest_digest,
        producer_id: source_manifest.producer_id.clone(),
        compatibility_digest: source_manifest.compatibility_digest,
        encoded_size_bytes: payload.len() as u64,
    };
    let mut projected = service.registry().clone();
    projected.append(artifacts::ArtifactEvent::Register {
        event_id: id(&format!(
            "artifact-publication:{}",
            transaction.intent().intent_digest
        )),
        manifest: manifest.clone(),
    })?;
    let mut signed = artifacts::SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: trust.withdrawal_scope_digest,
        binding,
        witness: artifacts::RegistryHeadWitnessV1 {
            registry_id: trust.registry_id.clone(),
            generation: Generation::new(1)?,
            head_digest: projected.snapshot().head_digest,
            predecessor_head_digest: before,
            authority_epoch: 1,
            signer_id: id("controlled-material-publisher"),
            signing_key_digest: Digest32::of_bytes(&public_key),
            issued_at: now,
            expires_at: until,
        },
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    let request = artifacts::LearningArtifactPublishRequestV1 {
        operation_id: operation,
        admission,
        payload: payload.clone(),
        signed_current_head: signed.clone(),
        expected_registry_predecessor_head: before,
        now,
    };
    let published = service.publish(request.clone())?;
    let reader = artifacts::ArtifactOwnerCurrentReaderV1::open(&root, trust, signed.clone())?;
    let current = reader.current_registry_view(seconds())?;
    let registry_receipt = current.receipt();
    assert_eq!(
        service.current_registry_view(seconds())?.receipt(),
        registry_receipt
    );
    let snapshot_path = root.join("registries").join(format!(
        "{}-{}.snapshot",
        registry_receipt.head_digest, registry_receipt.file_digest
    ));
    let payload_path = root.join("payloads").join(format!(
        "{}-{}.bin",
        manifest.artifact_id, manifest.content_digest
    ));
    let loaded = artifacts::load_pinned_candidate(
        File::open(&snapshot_path)?,
        File::open(&payload_path)?,
        artifacts::PinnedCandidateSpec {
            registry_receipt,
            manifest: manifest.clone(),
        },
    )?;
    let mut material_only = artifacts::RevalidatingCandidate::new(loaded);
    assert_eq!(
        material_only.with_current(current, seconds(), Digest32::of_bytes)?,
        payload_digest
    );
    assert_eq!(
        artifacts::read_candidate_payload(
            File::open(&payload_path)?,
            service.registry(),
            &manifest.artifact_id
        )?,
        payload
    );
    owner_config.required_current_head = Some(signed);
    drop(service);
    owner_config.now = seconds();
    let mut recovered = artifacts::LearningArtifactOwnerService::open(owner_config)?;
    assert_eq!(
        recovered.registry().manifest(&manifest.artifact_id),
        Some(&manifest)
    );
    assert_eq!(
        recovered.current_registry_view(seconds())?.receipt(),
        registry_receipt
    );
    assert_eq!(recovered.publish(request)?, published);
    assert_eq!(
        material_only.with_current(
            reader.current_registry_view(seconds())?,
            seconds(),
            Digest32::of_bytes
        )?,
        payload_digest
    );
    let evidence = serde_json::json!({ "schema":"hepta-smollm-material-publication-result-v1",
        "source_parent_sha256":input.parent_sha256, "training_input_sha256":input.training_input_sha256,
        "training_receipt_sha256":input.training_receipt_sha256, "payload_sha256":payload_digest.to_string(),
        "generation":manifest.generation.get(), "artifact_id":manifest.artifact_id.as_str(),
        "owner":"LearningArtifactOwnerService", "current_reader":"ArtifactOwnerCurrentReaderV1",
        "registry_head":registry_receipt.head_digest.to_string(), "payload":payload_path, "snapshot":snapshot_path,
        "publication_acknowledged":true, "named_owner_recovered_exact":true, "publication_retry_idempotent":true,
        "verified_current_material_read":true, "controlled_test_signer":true,
        "product_artifact_installed":false, "ordinary_cognitive_context_qualified":false,
        "independent_accepted":false, "prospective_accepted":false, "public_reward_eligible":false });
    let mut output = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(input.output.join("material-publication-result.json"))?;
    serde_json::to_writer_pretty(&mut output, &evidence)?;
    output.write_all(b"\n")?;
    output.sync_all()?;
    File::open(&input.output)?.sync_all()?;
    Ok(())
}
