//! Research-only independent issuers. These private keys are never product keys.
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::{self};
use std::io::Read;
use std::io::Write;
use std::path::Path;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_learning_artifacts::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

pub fn id(value: &str) -> Result<StableId, String> {
    StableId::new(value.to_owned()).map_err(|e| e.to_string())
}
pub fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
pub fn now_ms() -> Result<u64, String> {
    let value = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|e| e.to_string())?
        .as_millis();
    u64::try_from(value).map_err(|e| e.to_string())
}

pub struct Fixture {
    pub owner: LearningArtifactOwnerService,
    pub selected: RevalidatingSelectedCandidateV1,
    pub authority: FinalUseAuthority,
    pub selection_expires_at: u64,
    pub native_trust: ArtifactOwnerTrustV1,
    pub manifest: LearningArtifactManifestV2,
    pub reload: ReloadSpec,
}

/// Retained signed fixture evidence, never a new durable authorization store.
pub struct ReloadSpec {
    pub config: LearningArtifactOwnerServiceConfigV1,
    pub verifier: ArtifactSelectionVerifierV1,
    pub selection: SignedArtifactSelectionV1,
}

/// Exact native CURRENT publication, separate selector, and existing final-use owner.
/// Each fixture key belongs to a distinct test role; no descriptor grants authority.
pub fn open(
    root: &Path,
    payload: &[u8],
    generation: Generation,
    selection_lifetime: u64,
) -> Result<Fixture, String> {
    fs::create_dir_all(root).map_err(|e| e.to_string())?;
    let created_path = root.join("research-created-at");
    let created = match fs::read_to_string(&created_path) {
        Ok(value) => value.trim().parse::<u64>().map_err(|e| e.to_string())?,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            let now = now_ms()? / 1000;
            let mut file = OpenOptions::new()
                .create_new(true)
                .write(true)
                .open(&created_path)
                .map_err(|e| e.to_string())?;
            writeln!(file, "{now}").map_err(|e| e.to_string())?;
            file.sync_all().map_err(|e| e.to_string())?;
            File::open(root)
                .and_then(|f| f.sync_all())
                .map_err(|e| e.to_string())?;
            now
        }
        Err(error) => return Err(error.to_string()),
    };
    let now = now_ms()? / 1000;
    let publisher = SigningKey::from_bytes(&[19; 32]);
    let selector = SigningKey::from_bytes(&[43; 32]);
    let scope = DatasetWithdrawalScopeV1 {
        authority_domain_id: id("research.dataset.authority")?,
        registry_id: id("research.withdrawals")?,
        scope_id: id("research.scope")?,
    };
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope);
    let scope_digest = withdrawals.scope_digest().ok_or("withdrawal scope")?;
    let signer = TrustedArtifactSignerV1 {
        signer_id: id("research.publisher")?,
        verifying_key: publisher.verifying_key().to_bytes(),
        minimum_authority_epoch: 1,
        maximum_authority_epoch: 1,
        valid_from: created,
        expires_at: created + 3600,
        revoked_at: None,
    };
    let trust = ArtifactOwnerTrustV1 {
        registry_id: id("research.artifacts")?,
        withdrawal_scope_digest: scope_digest,
        minimum_registry_generation: Generation::new(1).map_err(|e| e.to_string())?,
        genesis_predecessor_head_digest: Digest32::ZERO,
        minimum_authority_epoch: 1,
        writer_signers: vec![signer.clone()],
        head_signers: vec![signer],
    };
    let mut lease = SignedArtifactWriterLeaseV1 {
        lease_id: id("research.writer")?,
        producer_id: id("research.trainer")?,
        registry_id: trust.registry_id.clone(),
        withdrawal_scope_digest: scope_digest,
        signer_id: id("research.publisher")?,
        signing_key_digest: Digest32::of_bytes(&publisher.verifying_key().to_bytes()),
        authority_epoch: 1,
        lease_generation: 1,
        issued_at: created,
        expires_at: created + 3600,
        signature: [0; 64],
    };
    lease.signature = publisher.sign(&lease.signing_bytes()).to_bytes();
    let artifact_id = id("research.rule.bundle")?;
    let content = Digest32::of_bytes(payload);
    let manifest = LearningArtifactManifestV2 {
        artifact_id: artifact_id.clone(),
        kind: ArtifactKind::Policy,
        generation,
        provenance_mode: ProvenanceModeV1::DatasetIndependent,
        source_dataset_digests: vec![],
        lineage_digests: vec![digest("research.rule.lineage")],
        predecessor_ids: vec![],
        rollback_predecessor: None,
        bytes_digest: content,
        encoded_size_bytes: payload.len() as u64,
        training_code_digest: digest("research.rule.driver"),
        runtime_tuple_digest: digest("research.native.runtime"),
        device_profile_digest: digest("research.cpu"),
        objective_class_digest: digest("research.role.permutation"),
        compatibility_digest: digest("research.rule.v1"),
        schema_profile_digest: digest("research.bundle.json.v1"),
        normalization_digest: digest("research.role.q24"),
        producer_id: id("research.trainer")?,
        created_at: created,
        expires_at: created + 3600,
    };
    let admission = admit_manifest_at_withdrawal_head_v3(
        &withdrawals,
        withdrawals.head_digest(),
        manifest.clone(),
        created,
    )
    .map_err(|e| e.to_string())?;
    let transaction = ArtifactPublicationTransactionV1::begin(
        id("research.publish")?,
        admission.clone(),
        &withdrawals,
        &ArtifactRegistry::new(),
        Digest32::ZERO,
        created,
    )
    .map_err(|e| e.to_string())?;
    let mut staged = ArtifactRegistry::new();
    staged
        .append(ArtifactEvent::Register {
            event_id: id(&format!(
                "artifact-publication:{}",
                transaction.intent().intent_digest
            ))?,
            manifest: ArtifactManifest {
                artifact_id: artifact_id.clone(),
                kind: manifest.kind,
                generation,
                predecessor_id: None,
                content_digest: content,
                objective_digest: manifest.objective_class_digest,
                support_digest: admission.validated_manifest.manifest_digest,
                producer_id: manifest.producer_id.clone(),
                compatibility_digest: manifest.compatibility_digest,
                encoded_size_bytes: manifest.encoded_size_bytes,
            },
        })
        .map_err(|e| e.to_string())?;
    let binding = digest("research.artifact.storage");
    let mut signed_head = SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: scope_digest,
        binding,
        witness: RegistryHeadWitnessV1 {
            registry_id: trust.registry_id.clone(),
            generation: Generation::new(1).map_err(|e| e.to_string())?,
            head_digest: staged.snapshot().head_digest,
            predecessor_head_digest: Digest32::ZERO,
            authority_epoch: 1,
            signer_id: id("research.publisher")?,
            signing_key_digest: Digest32::of_bytes(&publisher.verifying_key().to_bytes()),
            issued_at: created,
            expires_at: created + 3600,
        },
        signature: [0; 64],
    };
    signed_head.signature = publisher.sign(&signed_head.signing_bytes()).to_bytes();
    let artifact_root = root.join("artifacts");
    let existing = artifact_root.join("heads").exists()
        && fs::read_dir(artifact_root.join("heads"))
            .map_err(|e| e.to_string())?
            .next()
            .is_some();
    let mut owner_config = LearningArtifactOwnerServiceConfigV1 {
        root: artifact_root.clone(),
        trust: trust.clone(),
        writer_lease: lease,
        required_current_head: existing.then(|| signed_head.clone()),
        withdrawal_registry: withdrawals,
        storage_binding: binding,
        now,
    };
    let mut owner =
        LearningArtifactOwnerService::open(owner_config.clone()).map_err(|e| e.to_string())?;
    owner_config.required_current_head = Some(signed_head.clone());
    let receipt = owner
        .publish(LearningArtifactPublishRequestV1 {
            operation_id: id("research.publish")?,
            admission,
            payload: payload.to_vec(),
            signed_current_head: signed_head,
            expected_registry_predecessor_head: Digest32::ZERO,
            now: created,
        })
        .map_err(|e| e.to_string())?;
    let current = owner
        .current_registry_view(now)
        .map_err(|e| e.to_string())?;
    let native_manifest = owner
        .registry()
        .manifest(&artifact_id)
        .ok_or("manifest missing")?;
    let verifier = ArtifactSelectionVerifierV1::new(
        ArtifactSelectionTrustV1 {
            registry_id: trust.registry_id.clone(),
            withdrawal_scope_digest: scope_digest,
            minimum_authority_epoch: 1,
            selectors: vec![TrustedArtifactSelectorV1 {
                selector_id: id("research.selector")?,
                verifying_key: selector.verifying_key().to_bytes(),
                minimum_authority_epoch: 1,
                maximum_authority_epoch: 1,
                valid_from: created,
                expires_at: created + 3600,
                revoked_at: None,
            }],
        },
        &trust,
    )
    .map_err(|e| e.to_string())?;
    let selection_expires_at = created + selection_lifetime;
    let mut signed_selection = SignedArtifactSelectionV1 {
        selection_id: id("research.selection")?,
        artifact_id: artifact_id.clone(),
        registry_id: trust.registry_id.clone(),
        withdrawal_scope_digest: scope_digest,
        registry_head_digest: current.receipt().head_digest,
        current_witness_digest: current.witness_digest(),
        current_trust_digest: current.trust_digest(),
        artifact_kind: native_manifest.kind,
        artifact_generation: generation,
        predecessor_id: native_manifest.predecessor_id.clone(),
        content_digest: content,
        objective_digest: native_manifest.objective_digest,
        support_digest: native_manifest.support_digest,
        compatibility_digest: native_manifest.compatibility_digest,
        encoded_size_bytes: payload.len() as u64,
        selector_id: id("research.selector")?,
        selector_credential_digest: digest("research.selector.credential"),
        signing_key_digest: Digest32::of_bytes(&selector.verifying_key().to_bytes()),
        authority_epoch: 1,
        issued_at: created,
        expires_at: selection_expires_at,
        signature: [0; 64],
    };
    signed_selection.signature = selector.sign(&signed_selection.signing_bytes()).to_bytes();
    let reload = ReloadSpec {
        config: owner_config,
        verifier: verifier.clone(),
        selection: signed_selection.clone(),
    };
    let snapshot_path = artifact_root.join("registries").join(format!(
        "{}-{}.snapshot",
        receipt.registry_head_digest,
        current.receipt().file_digest
    ));
    let payload_path = artifact_root
        .join("payloads")
        .join(format!("{artifact_id}-{content}.bin"));
    let selected = RevalidatingSelectedCandidateV1::load(
        verifier,
        signed_selection,
        current,
        now,
        File::open(snapshot_path).map_err(|e| e.to_string())?,
        File::open(&payload_path).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    let authority = open_authority(root)?;
    Ok(Fixture {
        owner,
        selected,
        authority,
        selection_expires_at,
        native_trust: trust,
        manifest,
        reload,
    })
}

pub fn open_authority(root: &Path) -> Result<FinalUseAuthority, String> {
    let issuer = SigningKey::from_bytes(&[67; 32]);
    FinalUseAuthority::open_state_dir(
        &root.join("final-use"),
        "research.final-use".into(),
        issuer.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: Default::default(),
        },
    )
    .map_err(|e| e.to_string())
}

pub fn signed_grant(
    binding: codex_hepta_contracts::FinalUseBinding,
    sequence: u64,
    expires: u64,
) -> Result<SignedFinalUseGrant, String> {
    let key = SigningKey::from_bytes(&[67; 32]);
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "research.final-use".into(),
        authority_epoch: 1,
        grant_id: format!("research.use.{sequence}"),
        nonce: digest(&format!("research.nonce.{sequence}")).into_array(),
        binding,
        not_before_unix_ms: now_ms()?,
        expires_at_unix_ms: expires,
    };
    let signature = key
        .sign(&grant.signing_bytes().map_err(|e| e.to_string())?)
        .to_bytes()
        .to_vec();
    Ok(SignedFinalUseGrant { grant, signature })
}

pub fn corrupt_current(root: &Path) -> Result<(), String> {
    let entry = fs::read_dir(root.join("artifacts/heads"))
        .map_err(|e| e.to_string())?
        .next()
        .ok_or("CURRENT absent")?
        .map_err(|e| e.to_string())?;
    let mut bytes = Vec::new();
    File::open(entry.path())
        .and_then(|mut f| f.read_to_end(&mut bytes))
        .map_err(|e| e.to_string())?;
    if bytes.len() < 3 {
        return Err("CURRENT too short".into());
    }
    let offset = bytes.len() - 2;
    bytes[offset] = if bytes[offset] == b'0' { b'1' } else { b'0' };
    let mut file = OpenOptions::new()
        .write(true)
        .truncate(true)
        .open(entry.path())
        .map_err(|e| e.to_string())?;
    file.write_all(&bytes)
        .and_then(|()| file.sync_all())
        .map_err(|e| e.to_string())
}
