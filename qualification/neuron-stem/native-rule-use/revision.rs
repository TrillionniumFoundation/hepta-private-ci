//! Explicit fresh candidate installation by the existing research owner.
//! This is the supported one-Register publication path, never a revocation hack.
use super::decode_hex;
use super::fixture;
use super::number;
use super::pin;
use super::rule_artifact::RuleArtifactConsumerV1;
use super::validate_effects;
use super::Session;
use codex_hepta_learning_artifacts::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde_json::json;
use serde_json::Value;
use std::fs::File;
use std::path::Path;

pub fn install(root: &Path, session: &mut Session, command: &Value) -> Result<Value, String> {
    let payload = decode_hex(
        command["payload_hex"]
            .as_str()
            .ok_or("payload_hex required")?,
    )?;
    let content = Digest32::of_bytes(&payload);
    let generation = Generation::new(number(command, "generation")?).map_err(|e| e.to_string())?;
    let revision = number(command, "rule_revision")?;
    let scope_digest = pin(command, "scope_digest")?;
    let bundle: Value = serde_json::from_slice(&payload).map_err(|e| e.to_string())?;
    if content != pin(command, "checkpoint_digest")?
        || number(command, "authority_epoch")? != 1
        || generation.get() <= session.manifest.generation.get()
        || revision <= number(&session.descriptor, "rule_revision")?
        || bundle["schema"] != "hepta.rule-artifact.research.v1"
        || bundle["revision"] != revision
        || bundle["generation"] != generation.get()
    {
        return Err("fresh revision descriptor mismatch".into());
    }
    validate_effects(&bundle)?;
    let now = fixture::now_ms()? / 1000;
    let lifetime = command["selection_lifetime_s"]
        .as_u64()
        .unwrap_or(3600)
        .clamp(1, 3600);
    let predecessor = session
        .owner
        .current_registry_view(now)
        .map_err(|e| e.to_string())?
        .receipt()
        .head_digest;
    let mut staged = session.owner.registry().clone();
    if staged.snapshot().head_digest != predecessor {
        return Err("native registry/current mismatch".into());
    }
    let artifact_id = fixture::id(&format!("research.rule.{content}"))?;
    let operation_id = fixture::id(&format!("research.publish.{content}"))?;
    let mut manifest = session.manifest.clone();
    manifest.artifact_id = artifact_id.clone();
    manifest.generation = generation;
    manifest.predecessor_ids = vec![session.artifact_id.clone()];
    manifest.rollback_predecessor = None;
    manifest.bytes_digest = content;
    manifest.encoded_size_bytes = payload.len() as u64;
    manifest.created_at = now;
    let withdrawals = session.owner.withdrawal_registry();
    let admission = admit_manifest_at_withdrawal_head_v3(
        withdrawals,
        withdrawals.head_digest(),
        manifest.clone(),
        now,
    )
    .map_err(|e| e.to_string())?;
    let transaction = ArtifactPublicationTransactionV1::begin(
        operation_id.clone(),
        admission.clone(),
        withdrawals,
        &staged,
        predecessor,
        now,
    )
    .map_err(|e| e.to_string())?;
    staged
        .append(ArtifactEvent::Register {
            event_id: fixture::id(&format!(
                "artifact-publication:{}",
                transaction.intent().intent_digest
            ))?,
            manifest: ArtifactManifest {
                artifact_id: artifact_id.clone(),
                kind: manifest.kind,
                generation,
                predecessor_id: Some(session.artifact_id.clone()),
                content_digest: content,
                objective_digest: manifest.objective_class_digest,
                support_digest: admission.validated_manifest.manifest_digest,
                producer_id: manifest.producer_id.clone(),
                compatibility_digest: manifest.compatibility_digest,
                encoded_size_bytes: manifest.encoded_size_bytes,
            },
        })
        .map_err(|e| e.to_string())?;
    let key = SigningKey::from_bytes(&[19; 32]);
    let next_head_generation = session
        .head_generation
        .checked_add(1)
        .ok_or("head generation exhausted")?;
    let mut signed = SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: session.native_trust.withdrawal_scope_digest,
        binding: fixture::digest("research.artifact.storage"),
        witness: RegistryHeadWitnessV1 {
            registry_id: session.native_trust.registry_id.clone(),
            generation: Generation::new(next_head_generation).map_err(|e| e.to_string())?,
            head_digest: staged.snapshot().head_digest,
            predecessor_head_digest: predecessor,
            authority_epoch: 1,
            signer_id: fixture::id("research.publisher")?,
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            issued_at: now,
            expires_at: manifest.expires_at,
        },
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    let receipt = session
        .owner
        .publish(LearningArtifactPublishRequestV1 {
            operation_id,
            admission,
            payload: payload.clone(),
            signed_current_head: signed.clone(),
            expected_registry_predecessor_head: predecessor,
            now,
        })
        .map_err(|e| e.to_string())?;
    let current = session
        .owner
        .current_registry_view(now)
        .map_err(|e| e.to_string())?;
    let native = session
        .owner
        .registry()
        .manifest(&artifact_id)
        .ok_or("new native manifest missing")?;
    let selector = SigningKey::from_bytes(&[43; 32]);
    let key_window = session
        .native_trust
        .head_signers
        .first()
        .ok_or("native head signer missing")?;
    let expires = (now + lifetime).min(key_window.expires_at);
    let verifier = ArtifactSelectionVerifierV1::new(
        ArtifactSelectionTrustV1 {
            registry_id: session.native_trust.registry_id.clone(),
            withdrawal_scope_digest: session.native_trust.withdrawal_scope_digest,
            minimum_authority_epoch: 1,
            selectors: vec![TrustedArtifactSelectorV1 {
                selector_id: fixture::id("research.selector")?,
                verifying_key: selector.verifying_key().to_bytes(),
                minimum_authority_epoch: 1,
                maximum_authority_epoch: 1,
                valid_from: key_window.valid_from,
                expires_at: key_window.expires_at,
                revoked_at: None,
            }],
        },
        &session.native_trust,
    )
    .map_err(|e| e.to_string())?;
    let mut selection = SignedArtifactSelectionV1 {
        selection_id: fixture::id(&format!("research.selection.{content}"))?,
        artifact_id: artifact_id.clone(),
        registry_id: session.native_trust.registry_id.clone(),
        withdrawal_scope_digest: session.native_trust.withdrawal_scope_digest,
        registry_head_digest: current.receipt().head_digest,
        current_witness_digest: current.witness_digest(),
        current_trust_digest: current.trust_digest(),
        artifact_kind: native.kind,
        artifact_generation: generation,
        predecessor_id: native.predecessor_id.clone(),
        content_digest: content,
        objective_digest: native.objective_digest,
        support_digest: native.support_digest,
        compatibility_digest: native.compatibility_digest,
        encoded_size_bytes: payload.len() as u64,
        selector_id: fixture::id("research.selector")?,
        selector_credential_digest: fixture::digest("research.selector.credential"),
        signing_key_digest: Digest32::of_bytes(&selector.verifying_key().to_bytes()),
        authority_epoch: 1,
        issued_at: now,
        expires_at: expires,
        signature: [0; 64],
    };
    selection.signature = selector.sign(&selection.signing_bytes()).to_bytes();
    let mut reload_config = session.reload.config.clone();
    reload_config.now = now;
    reload_config.required_current_head = Some(signed);
    let reload = fixture::ReloadSpec {
        config: reload_config,
        verifier: verifier.clone(),
        selection: selection.clone(),
    };
    let artifact_root = root.join("artifacts");
    let snapshot = artifact_root.join("registries").join(format!(
        "{}-{}.snapshot",
        current.receipt().head_digest,
        current.receipt().file_digest
    ));
    let file = artifact_root
        .join("payloads")
        .join(format!("{artifact_id}-{content}.bin"));
    let selected = RevalidatingSelectedCandidateV1::load(
        verifier,
        selection,
        current,
        now,
        File::open(snapshot).map_err(|e| e.to_string())?,
        File::open(file).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    session.consumer = RuleArtifactConsumerV1::new(
        fixture::id("research.principal")?,
        fixture::id("research.worker")?,
        selected,
    );
    session.payload = payload;
    session.descriptor = json!({"checkpoint_digest":content.to_string(),"rule_revision":revision,"authority_epoch":1,"generation":generation.get(),"scope_digest":scope_digest.to_string()});
    session.manifest = manifest;
    session.artifact_id = artifact_id.clone();
    session.head_generation = next_head_generation;
    session.expires = expires;
    session.lifetime = lifetime;
    session.reload = reload;
    Ok(
        json!({"ok":true,"native_current":true,"independent_selection":true,"fresh_candidate":true,"artifact_id":artifact_id.as_str(),"generation":generation.get(),"rule_revision":revision,"checkpoint_digest":content.to_string(),"registry_head_digest":receipt.registry_head_digest.to_string(),"predecessor_head_digest":predecessor.to_string(),"production_qualified":false}),
    )
}

/// Reopen from the exact retained signed head and selection; no fixture issuer
/// creates a new selection, renews expiry, or publishes during this operation.
pub fn restart(root: &Path, old: Session) -> Result<Session, String> {
    let Session {
        owner,
        consumer,
        authority,
        control,
        payload,
        descriptor,
        lifetime,
        expires,
        driver_log,
        native_trust,
        manifest,
        artifact_id,
        head_generation,
        reload,
    } = old;
    drop((owner, consumer, authority, control));
    let now = fixture::now_ms()? / 1000;
    let mut config = reload.config.clone();
    config.now = now;
    let owner = LearningArtifactOwnerService::open(config).map_err(|e| e.to_string())?;
    let current = owner
        .current_registry_view(now)
        .map_err(|e| e.to_string())?;
    let snapshot = root.join("artifacts/registries").join(format!(
        "{}-{}.snapshot",
        current.receipt().head_digest,
        current.receipt().file_digest
    ));
    let file = root
        .join("artifacts/payloads")
        .join(format!("{artifact_id}-{}.bin", manifest.bytes_digest));
    let selected = RevalidatingSelectedCandidateV1::load(
        reload.verifier.clone(),
        reload.selection.clone(),
        current,
        now,
        File::open(snapshot).map_err(|e| e.to_string())?,
        File::open(file).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    let consumer = RuleArtifactConsumerV1::new(
        fixture::id("research.principal")?,
        fixture::id("research.worker")?,
        selected,
    );
    let authority = fixture::open_authority(root)?;
    let control = codex_hepta_infer_core::durable_control::DurableInferenceControl::open(
        root.join("inference.journal"),
        4096,
    )
    .map_err(|e| e.to_string())?;
    Ok(Session {
        owner,
        consumer,
        authority,
        control,
        payload,
        descriptor,
        lifetime,
        expires,
        driver_log,
        native_trust,
        manifest,
        artifact_id,
        head_generation,
        reload,
    })
}
