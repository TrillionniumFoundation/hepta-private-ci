//! Independent selection verification and pinned load admission.
//!
//! Selection is intentionally a separate trust domain from artifact publication
//! and current-head ownership. This module verifies an externally signed
//! selection against an authenticated CURRENT registry view. A verified
//! selection permits exact immutable loading only; it grants no activation,
//! canary, promotion, release, provider, tool or external-effect authority.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::fs::File;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;

use crate::ArtifactKind;
use crate::ArtifactLifecycleEventV1;
use crate::ArtifactLifecycleJournalError;
use crate::ArtifactLifecycleJournalReceiptV2;
use crate::ArtifactLifecycleJournalV2;
use crate::ArtifactLifecycleStateV1;
use crate::ArtifactManifest;
use crate::ArtifactOwnerTrustV1;
use crate::ArtifactOwnerVerifierV1;
use crate::LifecycleActorEvidenceV2;
use crate::LifecycleActorRoleV2;
use crate::PinnedCandidateLoadError;
use crate::PinnedCandidateSpec;
use crate::RevalidatingCandidate;
use crate::VerifiedCurrentRegistryViewV1;
use crate::load_pinned_candidate;

#[path = "selection_encoding.rs"]
mod encoding;

const MAX_TRUSTED_SELECTORS: usize = 32;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TrustedArtifactSelectorV1 {
    pub selector_id: StableId,
    pub verifying_key: [u8; 32],
    pub minimum_authority_epoch: u64,
    pub maximum_authority_epoch: u64,
    pub valid_from: u64,
    pub expires_at: u64,
    pub revoked_at: Option<u64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactSelectionTrustV1 {
    pub registry_id: StableId,
    pub withdrawal_scope_digest: Digest32,
    pub minimum_authority_epoch: u64,
    pub selectors: Vec<TrustedArtifactSelectorV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedArtifactSelectionV1 {
    pub selection_id: StableId,
    pub artifact_id: StableId,
    pub registry_id: StableId,
    pub withdrawal_scope_digest: Digest32,
    pub registry_head_digest: Digest32,
    pub current_witness_digest: Digest32,
    pub current_trust_digest: Digest32,
    pub artifact_kind: ArtifactKind,
    pub artifact_generation: Generation,
    pub predecessor_id: Option<StableId>,
    pub content_digest: Digest32,
    pub objective_digest: Digest32,
    pub support_digest: Digest32,
    pub compatibility_digest: Digest32,
    pub encoded_size_bytes: u64,
    pub selector_id: StableId,
    pub selector_credential_digest: Digest32,
    pub signing_key_digest: Digest32,
    pub authority_epoch: u64,
    pub issued_at: u64,
    pub expires_at: u64,
    pub signature: [u8; 64],
}

impl SignedArtifactSelectionV1 {
    #[must_use]
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut bytes = b"hepta.learning-artifacts.selection.v1".to_vec();
        push_id(&mut bytes, &self.selection_id);
        push_id(&mut bytes, &self.artifact_id);
        push_id(&mut bytes, &self.registry_id);
        bytes.extend_from_slice(self.withdrawal_scope_digest.as_array());
        bytes.extend_from_slice(self.registry_head_digest.as_array());
        bytes.extend_from_slice(self.current_witness_digest.as_array());
        bytes.extend_from_slice(self.current_trust_digest.as_array());
        bytes.push(self.artifact_kind.tag());
        bytes.extend_from_slice(&self.artifact_generation.get().to_be_bytes());
        match &self.predecessor_id {
            Some(predecessor) => {
                bytes.push(1);
                push_id(&mut bytes, predecessor);
            }
            None => bytes.push(0),
        }
        for digest in [
            self.content_digest,
            self.objective_digest,
            self.support_digest,
            self.compatibility_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.encoded_size_bytes.to_be_bytes());
        push_id(&mut bytes, &self.selector_id);
        bytes.extend_from_slice(self.selector_credential_digest.as_array());
        bytes.extend_from_slice(self.signing_key_digest.as_array());
        bytes.extend_from_slice(&self.authority_epoch.to_be_bytes());
        bytes.extend_from_slice(&self.issued_at.to_be_bytes());
        bytes.extend_from_slice(&self.expires_at.to_be_bytes());
        bytes
    }
}

#[derive(Debug)]
pub struct VerifiedArtifactSelectionV1 {
    pin: PinnedCandidateSpec,
    selection_digest: Digest32,
    selector_id: StableId,
    selector_credential_digest: Digest32,
    authority_epoch: u64,
    issued_at: u64,
    expires_at: u64,
    trust_digest: Digest32,
    authority: AuthorityPosture,
}

impl VerifiedArtifactSelectionV1 {
    /// The exact manifest authenticated by the independent selector and CURRENT owner.
    #[must_use]
    pub fn manifest(&self) -> &ArtifactManifest {
        &self.pin.manifest
    }

    #[must_use]
    pub fn artifact_id(&self) -> &StableId {
        &self.pin.manifest.artifact_id
    }

    #[must_use]
    pub const fn selection_digest(&self) -> Digest32 {
        self.selection_digest
    }

    #[must_use]
    pub fn selector_id(&self) -> &StableId {
        &self.selector_id
    }

    #[must_use]
    pub const fn trust_digest(&self) -> Digest32 {
        self.trust_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }
}

#[derive(Clone, Debug)]
pub struct ArtifactSelectionVerifierV1 {
    trust: ArtifactSelectionTrustV1,
    trust_digest: Digest32,
    artifact_owner_trust_digest: Digest32,
    selectors: BTreeMap<StableId, TrustedArtifactSelectorV1>,
}

impl ArtifactSelectionVerifierV1 {
    pub fn new(
        mut trust: ArtifactSelectionTrustV1,
        artifact_owner_trust: &ArtifactOwnerTrustV1,
    ) -> Result<Self, ArtifactSelectionError> {
        if trust.registry_id != artifact_owner_trust.registry_id
            || trust.withdrawal_scope_digest != artifact_owner_trust.withdrawal_scope_digest
        {
            return Err(ArtifactSelectionError::OwnerTrustMismatch);
        }
        let owner_verifier = ArtifactOwnerVerifierV1::new(artifact_owner_trust.clone())
            .map_err(|_| ArtifactSelectionError::InvalidOwnerTrust)?;
        let artifact_owner_trust_digest = owner_verifier.trust_digest();

        if trust.withdrawal_scope_digest.is_zero()
            || trust.minimum_authority_epoch == 0
            || trust.selectors.is_empty()
            || trust.selectors.len() > MAX_TRUSTED_SELECTORS
        {
            return Err(ArtifactSelectionError::InvalidTrust);
        }
        trust
            .selectors
            .sort_by(|left, right| left.selector_id.cmp(&right.selector_id));
        let mut selectors = BTreeMap::new();
        for selector in &trust.selectors {
            if selector.minimum_authority_epoch == 0
                || selector.maximum_authority_epoch < selector.minimum_authority_epoch
                || selector.valid_from > selector.expires_at
            {
                return Err(ArtifactSelectionError::InvalidTrust);
            }
            let key = VerifyingKey::from_bytes(&selector.verifying_key)
                .map_err(|_| ArtifactSelectionError::InvalidKey)?;
            if key.is_weak() {
                return Err(ArtifactSelectionError::InvalidKey);
            }
            let selector_key_digest = Digest32::of_bytes(&selector.verifying_key);
            if artifact_owner_trust
                .writer_signers
                .iter()
                .chain(artifact_owner_trust.head_signers.iter())
                .any(|owner| Digest32::of_bytes(&owner.verifying_key) == selector_key_digest)
            {
                return Err(ArtifactSelectionError::AuthorityKeyCollision);
            }
            if selectors
                .insert(selector.selector_id.clone(), selector.clone())
                .is_some()
            {
                return Err(ArtifactSelectionError::InvalidTrust);
            }
        }

        let mut bytes = b"hepta.learning-artifacts.selection-trust.v1".to_vec();
        push_id(&mut bytes, &trust.registry_id);
        bytes.extend_from_slice(trust.withdrawal_scope_digest.as_array());
        bytes.extend_from_slice(&trust.minimum_authority_epoch.to_be_bytes());
        bytes.extend_from_slice(&(trust.selectors.len() as u64).to_be_bytes());
        for selector in &trust.selectors {
            push_id(&mut bytes, &selector.selector_id);
            bytes.extend_from_slice(&selector.verifying_key);
            bytes.extend_from_slice(&selector.minimum_authority_epoch.to_be_bytes());
            bytes.extend_from_slice(&selector.maximum_authority_epoch.to_be_bytes());
            bytes.extend_from_slice(&selector.valid_from.to_be_bytes());
            bytes.extend_from_slice(&selector.expires_at.to_be_bytes());
            match selector.revoked_at {
                Some(at) => {
                    bytes.push(1);
                    bytes.extend_from_slice(&at.to_be_bytes());
                }
                None => bytes.push(0),
            }
        }

        Ok(Self {
            trust,
            trust_digest: Digest32::of_bytes(&bytes),
            artifact_owner_trust_digest,
            selectors,
        })
    }

    #[must_use]
    pub const fn trust_digest(&self) -> Digest32 {
        self.trust_digest
    }

    pub fn verify(
        &self,
        signed: &SignedArtifactSelectionV1,
        current: &VerifiedCurrentRegistryViewV1,
        now: u64,
    ) -> Result<VerifiedArtifactSelectionV1, ArtifactSelectionError> {
        if current.trust_digest() != self.artifact_owner_trust_digest
            || signed.current_trust_digest != self.artifact_owner_trust_digest
        {
            return Err(ArtifactSelectionError::OwnerTrustMismatch);
        }
        if signed.registry_id != self.trust.registry_id
            || signed.withdrawal_scope_digest != self.trust.withdrawal_scope_digest
            || signed.authority_epoch < self.trust.minimum_authority_epoch
            || signed.authority_epoch == 0
            || signed.issued_at > now
            || now > signed.expires_at
            || signed.issued_at > signed.expires_at
            || signed.selector_credential_digest.is_zero()
            || signed.registry_head_digest.is_zero()
            || signed.current_witness_digest.is_zero()
            || signed.current_trust_digest.is_zero()
        {
            return Err(ArtifactSelectionError::SelectionContext);
        }
        if signed.registry_head_digest != current.receipt().head_digest
            || signed.current_witness_digest != current.witness_digest()
            || signed.current_trust_digest != current.trust_digest()
        {
            return Err(ArtifactSelectionError::CurrentHeadMismatch);
        }

        let manifest = current
            .registry()
            .manifest(&signed.artifact_id)
            .ok_or(ArtifactSelectionError::ArtifactUnavailable)?;
        if !current.registry().is_eligible(&signed.artifact_id) {
            return Err(ArtifactSelectionError::ArtifactUnavailable);
        }
        validate_manifest_binding(signed, manifest)?;
        if signed.selector_id == manifest.producer_id {
            return Err(ArtifactSelectionError::RoleCollision);
        }

        let selector = self
            .selectors
            .get(&signed.selector_id)
            .ok_or(ArtifactSelectionError::UnknownSelector)?;
        if signed.signing_key_digest != Digest32::of_bytes(&selector.verifying_key)
            || signed.authority_epoch < selector.minimum_authority_epoch
            || signed.authority_epoch > selector.maximum_authority_epoch
            || signed.issued_at < selector.valid_from
            || signed.issued_at > selector.expires_at
        {
            return Err(ArtifactSelectionError::SelectorContext);
        }
        if selector
            .revoked_at
            .is_some_and(|revoked_at| signed.issued_at >= revoked_at || now >= revoked_at)
            || now > selector.expires_at
        {
            return Err(ArtifactSelectionError::SelectorRevoked);
        }
        VerifyingKey::from_bytes(&selector.verifying_key)
            .map_err(|_| ArtifactSelectionError::InvalidKey)?
            .verify_strict(
                &signed.signing_bytes(),
                &Signature::from_bytes(&signed.signature),
            )
            .map_err(|_| ArtifactSelectionError::InvalidSignature)?;

        let mut digest_bytes = signed.signing_bytes();
        digest_bytes.extend_from_slice(&signed.signature);
        Ok(VerifiedArtifactSelectionV1 {
            pin: PinnedCandidateSpec {
                registry_receipt: current.receipt(),
                manifest: manifest.clone(),
            },
            selection_digest: Digest32::of_bytes(&digest_bytes),
            selector_id: signed.selector_id.clone(),
            selector_credential_digest: signed.selector_credential_digest,
            authority_epoch: signed.authority_epoch,
            issued_at: signed.issued_at,
            expires_at: signed.expires_at,
            trust_digest: self.trust_digest,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

/// Persist the independently authenticated selection into the artifact lifecycle
/// evidence chain. This does not activate the artifact.
pub fn record_verified_selection(
    journal: &mut ArtifactLifecycleJournalV2,
    expected_head_digest: Digest32,
    producer_id: &StableId,
    selection: &VerifiedArtifactSelectionV1,
    event_id: StableId,
    now: u64,
) -> Result<ArtifactLifecycleJournalReceiptV2, ArtifactSelectionError> {
    if now < selection.issued_at || now > selection.expires_at {
        return Err(ArtifactSelectionError::SelectionContext);
    }
    let event = ArtifactLifecycleEventV1 {
        event_id,
        artifact_id: selection.pin.manifest.artifact_id.clone(),
        prior_state: ArtifactLifecycleStateV1::OperatorAccepted,
        next_state: ArtifactLifecycleStateV1::Selected,
        actor_id: selection.selector_id.clone(),
        actor_credential_digest: selection.selector_credential_digest,
        evidence_digest: selection.selection_digest,
        authority_epoch: selection.authority_epoch,
        occurred_at: now,
    };
    let actor = LifecycleActorEvidenceV2 {
        actor_id: selection.selector_id.clone(),
        credential_digest: selection.selector_credential_digest,
        role: LifecycleActorRoleV2::Selector,
        authority_epoch: selection.authority_epoch,
        verified_at: selection.issued_at,
        expires_at: selection.expires_at,
    };
    journal
        .append(expected_head_digest, producer_id, actor, event, now)
        .map_err(ArtifactSelectionError::Lifecycle)
}

/// Load exactly the selected immutable candidate. The returned cached consumer
/// remains closed until each use receives a fresh authenticated CURRENT view.
pub fn load_selected_candidate(
    snapshot_file: File,
    payload_file: File,
    selection: VerifiedArtifactSelectionV1,
) -> Result<RevalidatingCandidate, ArtifactSelectionError> {
    let loaded = load_pinned_candidate(snapshot_file, payload_file, selection.pin)
        .map_err(ArtifactSelectionError::Load)?;
    Ok(RevalidatingCandidate::new(loaded))
}

fn validate_manifest_binding(
    signed: &SignedArtifactSelectionV1,
    manifest: &ArtifactManifest,
) -> Result<(), ArtifactSelectionError> {
    if signed.artifact_kind != manifest.kind
        || signed.artifact_generation != manifest.generation
        || signed.predecessor_id != manifest.predecessor_id
        || signed.content_digest != manifest.content_digest
        || signed.objective_digest != manifest.objective_digest
        || signed.support_digest != manifest.support_digest
        || signed.compatibility_digest != manifest.compatibility_digest
        || signed.encoded_size_bytes != manifest.encoded_size_bytes
    {
        return Err(ArtifactSelectionError::ManifestMismatch);
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    bytes.extend_from_slice(&(value.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_str().as_bytes());
}

#[derive(Debug)]
pub enum ArtifactSelectionError {
    InvalidTrust,
    InvalidOwnerTrust,
    OwnerTrustMismatch,
    AuthorityKeyCollision,
    InvalidKey,
    UnknownSelector,
    InvalidSignature,
    SelectorContext,
    SelectorRevoked,
    SelectionContext,
    CurrentHeadMismatch,
    ArtifactUnavailable,
    ManifestMismatch,
    RoleCollision,
    Lifecycle(ArtifactLifecycleJournalError),
    Load(PinnedCandidateLoadError),
}

impl fmt::Display for ArtifactSelectionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ArtifactSelectionError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Lifecycle(error) => Some(error),
            Self::Load(error) => Some(error),
            Self::InvalidTrust
            | Self::InvalidOwnerTrust
            | Self::OwnerTrustMismatch
            | Self::AuthorityKeyCollision
            | Self::InvalidKey
            | Self::UnknownSelector
            | Self::InvalidSignature
            | Self::SelectorContext
            | Self::SelectorRevoked
            | Self::SelectionContext
            | Self::CurrentHeadMismatch
            | Self::ArtifactUnavailable
            | Self::ManifestMismatch
            | Self::RoleCollision => None,
        }
    }
}

#[cfg(test)]
mod tests {
    use std::fmt::Debug;

    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    use super::*;
    use crate::ArtifactEvent;
    use crate::ArtifactRegistry;
    use crate::RegistrySnapshotReceipt;
    use crate::TrustedArtifactSignerV1;

    fn must<T, E: Debug>(result: Result<T, E>) -> T {
        match result {
            Ok(value) => value,
            Err(error) => panic!("fixture failed: {error:?}"),
        }
    }

    fn id(value: &str) -> StableId {
        must(StableId::new(value.to_owned()))
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn manifest(producer_id: StableId) -> ArtifactManifest {
        ArtifactManifest {
            artifact_id: id("candidate"),
            kind: ArtifactKind::Model,
            generation: must(Generation::new(2)),
            predecessor_id: None,
            content_digest: digest("payload"),
            objective_digest: digest("objective"),
            support_digest: digest("support"),
            producer_id,
            compatibility_digest: digest("compatibility"),
            encoded_size_bytes: 7,
        }
    }

    fn owner_trust(key: &SigningKey) -> ArtifactOwnerTrustV1 {
        let signer = TrustedArtifactSignerV1 {
            signer_id: id("artifact-owner"),
            verifying_key: key.verifying_key().to_bytes(),
            minimum_authority_epoch: 1,
            maximum_authority_epoch: 9,
            valid_from: 1,
            expires_at: 100,
            revoked_at: None,
        };
        ArtifactOwnerTrustV1 {
            registry_id: id("registry"),
            withdrawal_scope_digest: digest("scope"),
            minimum_registry_generation: must(Generation::new(1)),
            genesis_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 1,
            writer_signers: vec![signer.clone()],
            head_signers: vec![signer],
        }
    }

    fn current_view(
        manifest: &ArtifactManifest,
        owner_trust: &ArtifactOwnerTrustV1,
    ) -> VerifiedCurrentRegistryViewV1 {
        let mut registry = ArtifactRegistry::new();
        must(registry.append(ArtifactEvent::Register {
            event_id: id("register"),
            manifest: manifest.clone(),
        }));
        let owner_verifier = match ArtifactOwnerVerifierV1::new(owner_trust.clone()) {
            Ok(verifier) => verifier,
            Err(error) => panic!("owner trust fixture failed: {error:?}"),
        };
        VerifiedCurrentRegistryViewV1::new(
            RegistrySnapshotReceipt {
                binding: digest("binding"),
                head_digest: registry.snapshot().head_digest,
                file_digest: digest("snapshot-file"),
                records: 1,
                encoded_bytes: 1,
            },
            registry,
            digest("witness"),
            owner_verifier.trust_digest(),
        )
    }

    fn trust(key: &SigningKey, selector_id: StableId) -> ArtifactSelectionTrustV1 {
        ArtifactSelectionTrustV1 {
            registry_id: id("registry"),
            withdrawal_scope_digest: digest("scope"),
            minimum_authority_epoch: 4,
            selectors: vec![TrustedArtifactSelectorV1 {
                selector_id,
                verifying_key: key.verifying_key().to_bytes(),
                minimum_authority_epoch: 4,
                maximum_authority_epoch: 9,
                valid_from: 10,
                expires_at: 100,
                revoked_at: None,
            }],
        }
    }

    fn signed_selection(
        key: &SigningKey,
        selector_id: StableId,
        manifest: &ArtifactManifest,
        current: &VerifiedCurrentRegistryViewV1,
    ) -> SignedArtifactSelectionV1 {
        let mut signed = SignedArtifactSelectionV1 {
            selection_id: id("selection"),
            artifact_id: manifest.artifact_id.clone(),
            registry_id: id("registry"),
            withdrawal_scope_digest: digest("scope"),
            registry_head_digest: current.receipt().head_digest,
            current_witness_digest: current.witness_digest(),
            current_trust_digest: current.trust_digest(),
            artifact_kind: manifest.kind,
            artifact_generation: manifest.generation,
            predecessor_id: manifest.predecessor_id.clone(),
            content_digest: manifest.content_digest,
            objective_digest: manifest.objective_digest,
            support_digest: manifest.support_digest,
            compatibility_digest: manifest.compatibility_digest,
            encoded_size_bytes: manifest.encoded_size_bytes,
            selector_id,
            selector_credential_digest: digest("selector-credential"),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            authority_epoch: 4,
            issued_at: 20,
            expires_at: 80,
            signature: [0; 64],
        };
        signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
        signed
    }

    #[test]
    fn art_12_independent_selector_binds_exact_current_and_manifest() {
        let key = SigningKey::from_bytes(&[41; 32]);
        let producer = id("producer");
        let selector = id("selector");
        let manifest = manifest(producer);
        let owner_key = SigningKey::from_bytes(&[13; 32]);
        let owner_trust = owner_trust(&owner_key);
        let current = current_view(&manifest, &owner_trust);
        let verifier = must(ArtifactSelectionVerifierV1::new(
            trust(&key, selector.clone()),
            &owner_trust,
        ));
        let signed = signed_selection(&key, selector.clone(), &manifest, &current);
        let verified = must(verifier.verify(&signed, &current, 30));
        assert_eq!(verified.artifact_id(), &manifest.artifact_id);
        assert_eq!(verified.selector_id(), &selector);
        assert!(!verified.selection_digest().is_zero());
        assert!(!verified.trust_digest().is_zero());
        assert_eq!(verified.authority(), AuthorityPosture::DENY_ALL);

        let mut drifted = signed;
        drifted.registry_head_digest = digest("different-head");
        drifted.signature = key.sign(&drifted.signing_bytes()).to_bytes();
        assert!(matches!(
            verifier.verify(&drifted, &current, 30),
            Err(ArtifactSelectionError::CurrentHeadMismatch)
        ));
    }

    #[test]
    fn art_12_selection_rejects_self_selection_and_revoked_selector() {
        let key = SigningKey::from_bytes(&[42; 32]);
        let producer = id("producer");
        let manifest = manifest(producer.clone());
        let owner_key = SigningKey::from_bytes(&[13; 32]);
        let owner_trust = owner_trust(&owner_key);
        let current = current_view(&manifest, &owner_trust);
        let verifier = must(ArtifactSelectionVerifierV1::new(
            trust(&key, producer.clone()),
            &owner_trust,
        ));
        let signed = signed_selection(&key, producer, &manifest, &current);
        assert!(matches!(
            verifier.verify(&signed, &current, 30),
            Err(ArtifactSelectionError::RoleCollision)
        ));

        let colliding = ArtifactSelectionVerifierV1::new(
            trust(&owner_key, id("different-selector-id")),
            &owner_trust,
        );
        assert!(matches!(
            colliding,
            Err(ArtifactSelectionError::AuthorityKeyCollision)
        ));

        let selector = id("selector");
        let mut revoked_trust = trust(&key, selector.clone());
        revoked_trust.selectors[0].revoked_at = Some(25);
        let verifier = must(ArtifactSelectionVerifierV1::new(
            revoked_trust,
            &owner_trust,
        ));
        let signed = signed_selection(&key, selector, &manifest, &current);
        assert!(matches!(
            verifier.verify(&signed, &current, 30),
            Err(ArtifactSelectionError::SelectorRevoked)
        ));
    }

    #[test]
    fn art_12_verified_selection_records_only_selected_transition() {
        let key = SigningKey::from_bytes(&[43; 32]);
        let producer = id("producer");
        let selector = id("selector");
        let manifest = manifest(producer.clone());
        let owner_key = SigningKey::from_bytes(&[13; 32]);
        let owner_trust = owner_trust(&owner_key);
        let current = current_view(&manifest, &owner_trust);
        let verifier = must(ArtifactSelectionVerifierV1::new(
            trust(&key, selector),
            &owner_trust,
        ));
        let signed = signed_selection(&key, id("selector"), &manifest, &current);
        let verified = must(verifier.verify(&signed, &current, 30));

        let mut journal = ArtifactLifecycleJournalV2::new();
        let states = [
            (
                LifecycleActorRoleV2::Producer,
                id("producer"),
                ArtifactLifecycleStateV1::Proposed,
                ArtifactLifecycleStateV1::Trained,
            ),
            (
                LifecycleActorRoleV2::Evaluator,
                id("evaluator"),
                ArtifactLifecycleStateV1::Trained,
                ArtifactLifecycleStateV1::Evaluated,
            ),
            (
                LifecycleActorRoleV2::ShadowOperator,
                id("shadow"),
                ArtifactLifecycleStateV1::Evaluated,
                ArtifactLifecycleStateV1::Shadow,
            ),
            (
                LifecycleActorRoleV2::CanaryOperator,
                id("canary"),
                ArtifactLifecycleStateV1::Shadow,
                ArtifactLifecycleStateV1::Canary,
            ),
            (
                LifecycleActorRoleV2::HumanOperator,
                id("operator"),
                ArtifactLifecycleStateV1::Canary,
                ArtifactLifecycleStateV1::OperatorAccepted,
            ),
        ];
        for (index, (role, actor_id, prior_state, next_state)) in states.into_iter().enumerate() {
            let credential = digest(&format!("credential-{index}"));
            let expected_head = journal.head_digest();
            must(journal.append(
                expected_head,
                &producer,
                LifecycleActorEvidenceV2 {
                    actor_id: actor_id.clone(),
                    credential_digest: credential,
                    role,
                    authority_epoch: 4,
                    verified_at: 20,
                    expires_at: 80,
                },
                ArtifactLifecycleEventV1 {
                    event_id: id(&format!("event-{index}")),
                    artifact_id: manifest.artifact_id.clone(),
                    prior_state,
                    next_state,
                    actor_id,
                    actor_credential_digest: credential,
                    evidence_digest: digest(&format!("evidence-{index}")),
                    authority_epoch: 4,
                    occurred_at: 30,
                },
                30,
            ));
        }

        let expected_head = journal.head_digest();
        let receipt = must(record_verified_selection(
            &mut journal,
            expected_head,
            &producer,
            &verified,
            id("selection-event"),
            30,
        ));
        assert_eq!(receipt.state, ArtifactLifecycleStateV1::Selected);
        let Some(last) = journal.records().last() else {
            panic!("selection event missing");
        };
        assert_eq!(last.event.evidence_digest, verified.selection_digest());
        assert_eq!(last.actor.role, LifecycleActorRoleV2::Selector);
    }
}
