//! Trust mapping for two enforced operational controllers under one administrator.
//! The fixed evaluator has no Generator private-key field or read/sign path.
use super::files::Access;
use super::files::ReviewResult;
use super::files::read_root;
use super::generator_wire::program_digest;
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
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde::Deserialize;
use std::path::Path;
use std::path::PathBuf;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct IndependentTrustConfig {
    pub schema: String,
    pub root_key_path: PathBuf,
    pub observer_key_path: PathBuf,
    pub evaluator_key_path: PathBuf,
    pub generator_verifying_key_path: PathBuf,
    pub generator_program_path: PathBuf,
    pub generator_program_digest: String,
    pub scorer_path: PathBuf,
    pub scorer_digest: String,
    pub generator_uid: u32,
    pub scope_digest: String,
    pub objective_digest: String,
    pub authority_epoch: u64,
    pub valid_from: u64,
    pub expires_at: u64,
    #[serde(default)]
    pub independent_reviewer: Option<IndependentReviewerConfig>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct IndependentReviewerConfig {
    pub public_key_path: PathBuf,
    pub program_path: PathBuf,
    pub program_digest: String,
    pub uid: u32,
    pub gid: u32,
    pub publication_directory: PathBuf,
}
pub(super) struct IndependentTrust {
    pub config: IndependentTrustConfig,
    pub config_digest: Digest32,
    pub activated: ActivatedLearningTrustV1,
    pub generator: AuthenticatedPrincipalV1,
    pub observer: AuthenticatedPrincipalV1,
    pub evaluator: AuthenticatedPrincipalV1,
    pub objective: Digest32,
    pub generator_program: Digest32,
    pub evaluator_program: Digest32,
    pub generator_controller: StableId,
    pub evaluator_controller: StableId,
    pub root: LearningTrustRootV1,
    pub distribution: SignedLearningTrustDistributionV1,
    keys: [SigningKey; 2],
}
impl IndependentTrust {
    pub(super) fn open(path: &Path, now: u64) -> ReviewResult<Self> {
        let status = std::fs::read_to_string("/proc/self/status")?;
        if status
            .lines()
            .find_map(|line| line.strip_prefix("Uid:"))
            .ok_or("UID status absent")?
            .split_whitespace()
            .any(|id| id != "0")
        {
            return Err("fixed evaluator requires the actual root owner".into());
        }
        let bytes = read_root(path, 16 * 1024, Access::Private)?;
        let config: IndependentTrustConfig = serde_json::from_slice(&bytes)?;
        if config.schema != "hepta.fixed-custody-evaluator-trust.v1"
            || config.generator_uid == 0
            || config.valid_from > now
            || config.expires_at <= now
            || config.expires_at - config.valid_from > 30 * 24 * 3_600_000
        {
            return Err("invalid fixed evaluator trust window/UID".into());
        }
        let generator_program = program_digest(&config.generator_program_path)?;
        if generator_program != config.generator_program_digest.parse::<Digest32>()?
            || program_digest(&config.scorer_path)? != config.scorer_digest.parse::<Digest32>()?
        {
            return Err("protected generator/scorer executable changed".into());
        }
        let evaluator_program = program_digest(&std::env::current_exe()?)?;
        if generator_program == evaluator_program {
            return Err("generator and evaluator must be distinct immutable programs".into());
        }
        let config_digest = Digest32::of_bytes(&bytes);
        let launcher = program_digest(Path::new("/usr/bin/setpriv"))?;
        let manager = program_digest(Path::new("/usr/bin/systemd-run"))?;
        let generator_controller=StableId::new(format!("bounded-generator.{}",Digest32::of_bytes(&[generator_program.as_array().as_slice(),config.generator_uid.to_be_bytes().as_slice(),launcher.as_array(),manager.as_array(),b"clear-groups;all-caps-zero;no-new-privileges;cgroup-memory-256MiB-pids16-cpu100;protected-eval-custody"].concat())))?;
        let evaluator_controller = StableId::new(format!(
            "fixed-custody-evaluator.{}",
            Digest32::of_bytes(
                &[
                    evaluator_program.as_array().as_slice(),
                    config_digest.as_array(),
                    b"root-private-outcome-custody;no-arbitrary-outcome-or-sign-api"
                ]
                .concat()
            )
        ))?;
        let scope: Digest32 = config.scope_digest.parse()?;
        let objective: Digest32 = config.objective_digest.parse()?;
        let root_key = SigningKey::from_bytes(&read_seed(&config.root_key_path)?);
        let observer_key = SigningKey::from_bytes(&read_seed(&config.observer_key_path)?);
        let evaluator_key = SigningKey::from_bytes(&read_seed(&config.evaluator_key_path)?);
        let generator_public: [u8; 32] =
            read_root(&config.generator_verifying_key_path, 32, Access::Immutable)?
                .try_into()
                .map_err(|_| "generator public key must contain 32 bytes")?;
        let mut signers = Vec::new();
        for (name, role, public, controller) in [
            (
                "native-unprivileged-generator",
                LearningEvidenceRoleV1::Generator,
                generator_public,
                generator_controller.clone(),
            ),
            (
                "fixed-custody-observer",
                LearningEvidenceRoleV1::Observer,
                observer_key.verifying_key().to_bytes(),
                evaluator_controller.clone(),
            ),
            (
                "fixed-custody-evaluator",
                LearningEvidenceRoleV1::Evaluator,
                evaluator_key.verifying_key().to_bytes(),
                evaluator_controller.clone(),
            ),
        ] {
            signers.push(TrustedLearningSignerV1 {
                principal: AuthenticatedPrincipalV1 {
                    principal_id: StableId::new(name)?,
                    credential_chain_digest: Digest32::of_bytes(
                        &[
                            root_key.verifying_key().as_bytes().as_slice(),
                            public.as_slice(),
                            controller.as_str().as_bytes(),
                        ]
                        .concat(),
                    ),
                    signing_key_digest: Digest32::of_bytes(&public),
                    scope_digest: scope,
                    authority_epoch: config.authority_epoch,
                    authenticated_at: config.valid_from,
                    expires_at: config.expires_at,
                },
                controller_id: controller,
                verifying_key: public,
                roles: vec![role],
                revoked_at: None,
            });
        }
        if let Some(reviewer) = &config.independent_reviewer {
            if reviewer.uid == 0
                || reviewer.uid == config.generator_uid
                || reviewer.gid == 0
                || program_digest(&reviewer.program_path)?
                    != reviewer.program_digest.parse::<Digest32>()?
            {
                return Err("independent reviewer UID/program binding".into());
            }
            let reviewer_program: Digest32 = reviewer.program_digest.parse()?;
            if reviewer_program == evaluator_program || reviewer_program == generator_program {
                return Err("reviewer must execute a distinct fixed program".into());
            }
            let public: [u8; 32] = read_root(&reviewer.public_key_path, 32, Access::Immutable)?
                .try_into()
                .map_err(|_| "reviewer public key width")?;
            let controller=StableId::new(format!("fixed-no-custody-reviewer.{}",Digest32::of_bytes(&[reviewer_program.as_array().as_slice(),reviewer.uid.to_be_bytes().as_slice(),reviewer.gid.to_be_bytes().as_slice(),launcher.as_array(),manager.as_array(),b"no-sudo;no-caps;no-groups;no-new-privileges;read-only-anchored-cut;denied-gold-and-other-keys"].concat())))?;
            signers.push(TrustedLearningSignerV1 {
                principal: AuthenticatedPrincipalV1 {
                    principal_id: StableId::new("fixed-no-custody-reviewer")?,
                    credential_chain_digest: Digest32::of_bytes(
                        &[
                            root_key.verifying_key().as_bytes().as_slice(),
                            public.as_slice(),
                            controller.as_str().as_bytes(),
                        ]
                        .concat(),
                    ),
                    signing_key_digest: Digest32::of_bytes(&public),
                    scope_digest: scope,
                    authority_epoch: config.authority_epoch,
                    authenticated_at: config.valid_from,
                    expires_at: config.expires_at,
                },
                controller_id: controller,
                verifying_key: public,
                roles: vec![LearningEvidenceRoleV1::Evaluator],
                revoked_at: None,
            });
        }
        let root = LearningTrustRootV1 {
            root_id: StableId::new("fixed-custody-learning-root")?,
            scope_digest: scope,
            verifying_key: root_key.verifying_key().to_bytes(),
            valid_from: config.valid_from,
            expires_at: config.expires_at,
            revoked_at: None,
        };
        let mut distribution = SignedLearningTrustDistributionV1 {
            distribution: LearningTrustDistributionV1 {
                distribution_id: StableId::new("fixed-custody-learning-distribution")?,
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
        distribution.signature = root_key.sign(&distribution.signing_bytes()?).to_bytes();
        let activated = activate_learning_trust(&root, distribution.clone(), None, now)?;
        Ok(Self {
            root,
            distribution,
            config,
            config_digest,
            activated,
            generator: signers[0].principal.clone(),
            observer: signers[1].principal.clone(),
            evaluator: signers[2].principal.clone(),
            objective,
            generator_program,
            evaluator_program,
            generator_controller,
            evaluator_controller,
            keys: [observer_key, evaluator_key],
        })
    }
    pub(super) fn sign(
        &self,
        role: LearningEvidenceRoleV1,
        id: StableId,
        payload: &[u8],
        issued: u64,
        now: u64,
    ) -> ReviewResult<SignedLearningEvidenceV1> {
        let (index, p) = match role {
            LearningEvidenceRoleV1::Observer => (0, &self.observer),
            LearningEvidenceRoleV1::Evaluator => (1, &self.evaluator),
            _ => return Err(
                "fixed evaluator cannot sign Generator, Selector, credit or unlearning authority"
                    .into(),
            ),
        };
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: id,
            principal_id: p.principal_id.clone(),
            role,
            trust_digest: self.activated.verifier().trust_digest(),
            scope_digest: p.scope_digest,
            objective_digest: self.objective,
            authority_epoch: p.authority_epoch,
            issued_at: issued,
            expires_at: issued
                .checked_add(3_600_000)
                .ok_or("expiry overflow")?
                .min(p.expires_at),
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
fn read_seed(path: &Path) -> ReviewResult<[u8; 32]> {
    read_root(path, 32, Access::Private)?
        .try_into()
        .map_err(|_| "evaluation key must contain 32 bytes".into())
}
