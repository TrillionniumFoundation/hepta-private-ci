//! Local audit roles share their actual root controller. Different keys cannot
//! turn these roles into independent outcomes or authorize product activation.

use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde::Deserialize;

use super::files::Access;
use super::files::ReviewResult;
use super::files::read_root;
use crate::ActivatedLearningTrustV1;
use crate::AuthenticatedPrincipalV1;
use crate::LearningEvidenceRoleV1;
use crate::LearningEvidenceTrustV1;
use crate::LearningTrustDistributionV1;
use crate::LearningTrustRootV1;
use crate::SignedLearningEvidenceV1;
use crate::SignedLearningTrustDistributionV1;
use crate::TrustedLearningSignerV1;
use crate::activate_learning_trust;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct TrustConfig {
    schema: String,
    root_key_path: PathBuf,
    generator_key_path: PathBuf,
    observer_key_path: PathBuf,
    evaluator_key_path: PathBuf,
    scope_digest: String,
    objective_digest: String,
    authority_epoch: u64,
    valid_from: u64,
    expires_at: u64,
}

pub(super) struct LocalAuditTrust {
    pub(super) activated: ActivatedLearningTrustV1,
    pub(super) config_digest: Digest32,
    pub(super) objective: Digest32,
    pub(super) generator: AuthenticatedPrincipalV1,
    pub(super) observer: AuthenticatedPrincipalV1,
    pub(super) evaluator: AuthenticatedPrincipalV1,
    pub(super) program_digest: Digest32,
    keys: [SigningKey; 3],
}

impl LocalAuditTrust {
    pub(super) fn open(path: &Path, now: u64) -> ReviewResult<Self> {
        let program_digest = Digest32::of_bytes(&read_root(
            &std::env::current_exe()?,
            128 * 1024 * 1024,
            Access::Immutable,
        )?);
        let bytes = read_root(path, 16 * 1024, Access::Private)?;
        let config: TrustConfig = serde_json::from_slice(&bytes)?;
        if config.schema != "hepta.local-calibration-review-trust.v1"
            || config.valid_from > now
            || config.expires_at <= now
            || config.expires_at - config.valid_from > 30 * 24 * 60 * 60 * 1000
        {
            return Err("invalid local audit trust schema or validity window".into());
        }
        let scope: Digest32 = config.scope_digest.parse()?;
        let objective: Digest32 = config.objective_digest.parse()?;
        let machine_id = read_root(Path::new("/etc/machine-id"), 128, Access::Immutable)?;
        let machine_id = std::str::from_utf8(&machine_id)?.trim();
        if machine_id.len() != 32 || !machine_id.bytes().all(|byte| byte.is_ascii_hexdigit()) {
            return Err("invalid actual root controller machine identity".into());
        }
        let controller_id = StableId::new(format!("local-root.{machine_id}"))?;
        let root_seed: [u8; 32] = read_root(&config.root_key_path, 32, Access::Private)?
            .try_into()
            .map_err(|_| "root key must contain exactly 32 bytes")?;
        let root_key = SigningKey::from_bytes(&root_seed);
        let mut keys = Vec::new();
        let mut signers = Vec::new();
        for (name, role, key_path) in [
            (
                "local-calibration-generator",
                LearningEvidenceRoleV1::Generator,
                &config.generator_key_path,
            ),
            (
                "local-calibration-observer",
                LearningEvidenceRoleV1::Observer,
                &config.observer_key_path,
            ),
            (
                "local-calibration-evaluator",
                LearningEvidenceRoleV1::Evaluator,
                &config.evaluator_key_path,
            ),
        ] {
            let seed: [u8; 32] = read_root(key_path, 32, Access::Private)?
                .try_into()
                .map_err(|_| "role key must contain exactly 32 bytes")?;
            let key = SigningKey::from_bytes(&seed);
            let principal = AuthenticatedPrincipalV1 {
                principal_id: StableId::new(name)?,
                credential_chain_digest: Digest32::of_bytes(
                    &[
                        root_key.verifying_key().as_bytes().as_slice(),
                        key.verifying_key().as_bytes().as_slice(),
                        name.as_bytes(),
                    ]
                    .concat(),
                ),
                signing_key_digest: Digest32::of_bytes(key.verifying_key().as_bytes()),
                scope_digest: scope,
                authority_epoch: config.authority_epoch,
                authenticated_at: config.valid_from,
                expires_at: config.expires_at,
            };
            signers.push(TrustedLearningSignerV1 {
                principal,
                controller_id: controller_id.clone(),
                verifying_key: key.verifying_key().to_bytes(),
                roles: vec![role],
                revoked_at: None,
            });
            keys.push(key);
        }
        let root = LearningTrustRootV1 {
            root_id: StableId::new("local-calibration-root")?,
            scope_digest: scope,
            verifying_key: root_key.verifying_key().to_bytes(),
            valid_from: config.valid_from,
            expires_at: config.expires_at,
            revoked_at: None,
        };
        let mut signed = SignedLearningTrustDistributionV1 {
            distribution: LearningTrustDistributionV1 {
                distribution_id: StableId::new("local-calibration-distribution")?,
                generation: 1,
                effective_at: config.valid_from,
                trust: LearningEvidenceTrustV1 {
                    scope_digest: scope,
                    objective_digest: objective,
                    authority_epoch: config.authority_epoch,
                    signers: signers.clone(),
                },
            },
            root_id: root.root_id.clone(),
            issued_at: config.valid_from,
            expires_at: config.expires_at,
            signature: [0; 64],
        };
        signed.signature = root_key.sign(&signed.signing_bytes()?).to_bytes();
        let activated = activate_learning_trust(&root, signed, None, now)?;
        Ok(Self {
            activated,
            config_digest: Digest32::of_bytes(&bytes),
            objective,
            generator: signers[0].principal.clone(),
            observer: signers[1].principal.clone(),
            evaluator: signers[2].principal.clone(),
            program_digest,
            keys: keys.try_into().map_err(|_| "local audit role count")?,
        })
    }

    pub(super) fn sign(
        &self,
        role: LearningEvidenceRoleV1,
        identifier: StableId,
        payload: &[u8],
        issued_at: u64,
        now: u64,
    ) -> ReviewResult<SignedLearningEvidenceV1> {
        let (index, principal) = match role {
            LearningEvidenceRoleV1::Generator => (0, &self.generator),
            LearningEvidenceRoleV1::Observer => (1, &self.observer),
            LearningEvidenceRoleV1::Evaluator => (2, &self.evaluator),
            LearningEvidenceRoleV1::CreditAllocator
            | LearningEvidenceRoleV1::UnlearningAuthority
            | LearningEvidenceRoleV1::Selector => {
                return Err(
                    "the local calibration host has no selector or promotion signer".into(),
                );
            }
        };
        let expires_at = issued_at
            .checked_add(60 * 60 * 1000)
            .ok_or("evidence expiry overflow")?
            .min(principal.expires_at);
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: identifier,
            principal_id: principal.principal_id.clone(),
            role,
            trust_digest: self.activated.verifier().trust_digest(),
            scope_digest: principal.scope_digest,
            objective_digest: self.objective,
            authority_epoch: principal.authority_epoch,
            issued_at,
            expires_at,
            payload_digest: Digest32::of_bytes(payload),
            signature: [0; 64],
        };
        evidence.signature = self.keys[index].sign(&evidence.signing_bytes()).to_bytes();
        self.activated
            .verifier()
            .verify(role, &evidence, payload, now)?;
        Ok(evidence)
    }
}
