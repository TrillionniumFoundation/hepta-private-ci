//! One independently enrolled Root withdrawal program. Custody evaluation has
//! only the public enrollment; its ordinary signer never gains this role.
use super::files::Access;
use super::files::ReviewResult;
use super::files::read_root;
use super::generator_wire::program_digest;
use super::independent_trust::IndependentTrustConfig;
use crate::ActivatedLearningTrustV1;
use crate::AuthenticatedPrincipalV1;
use crate::LearningEvidenceRoleV1;
use crate::SignedLearningEvidenceV1;
use crate::TrustedLearningSignerV1;
use crate::UnlearningLineageRequestV1;
use crate::unlearning_signing_payload_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde::Deserialize;
use std::path::Path;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct FixedUnlearningAuthorityConfig {
    pub public_key_path: PathBuf,
    pub program_path: PathBuf,
    pub program_digest: String,
}

fn controller(public: &[u8; 32], program: Digest32, scope: Digest32) -> ReviewResult<StableId> {
    Ok(StableId::new(format!(
        "fixed-root-learning-withdrawal.{}",
        Digest32::of_bytes(
            &[
                program.as_array().as_slice(),
                public.as_slice(),
                scope.as_array(),
                b"root-only;original-ledger-unlearning-payload;delivery-fence-before-append",
            ]
            .concat()
        )
    ))?)
}

pub(super) fn admitted_unlearning_signer(
    authority: &FixedUnlearningAuthorityConfig,
    config: &IndependentTrustConfig,
    root_public: [u8; 32],
    authenticated_at: u64,
    expires_at: u64,
    existing: &[TrustedLearningSignerV1],
    generator_program: Digest32,
    evaluator_program: Digest32,
) -> ReviewResult<TrustedLearningSignerV1> {
    let public: [u8; 32] = read_root(&authority.public_key_path, 32, Access::Immutable)?
        .try_into()
        .map_err(|_| "unlearning public key width")?;
    let program: Digest32 = authority.program_digest.parse()?;
    let reviewer_program = config
        .independent_reviewer
        .as_ref()
        .map(|reviewer| reviewer.program_digest.parse::<Digest32>())
        .transpose()?;
    if program_digest(&authority.program_path)? != program
        || program == generator_program
        || program == evaluator_program
        || reviewer_program == Some(program)
        || public == root_public
        || existing.iter().any(|signer| signer.verifying_key == public)
    {
        return Err("unlearning must use its own protected program and signing key".into());
    }
    let scope: Digest32 = config.scope_digest.parse()?;
    let controller = controller(&public, program, scope)?;
    Ok(TrustedLearningSignerV1 {
        principal: AuthenticatedPrincipalV1 {
            principal_id: StableId::new("fixed-root-unlearning-authority")?,
            credential_chain_digest: Digest32::of_bytes(
                &[
                    root_public.as_slice(),
                    public.as_slice(),
                    controller.as_str().as_bytes(),
                ]
                .concat(),
            ),
            signing_key_digest: Digest32::of_bytes(&public),
            scope_digest: scope,
            authority_epoch: config.authority_epoch,
            authenticated_at,
            expires_at,
        },
        controller_id: controller,
        verifying_key: public,
        roles: vec![LearningEvidenceRoleV1::UnlearningAuthority],
        revoked_at: None,
    })
}

#[cfg(test)]
#[path = "independent_unlearning_tests.rs"]
mod tests;

/// Sign only the original typed lineage payload from the currently enrolled
/// Root executable. No distribution is created/rotated, no dataset is frozen,
/// and no ledger or artifact is written. The final owner rechecks all evidence.
pub fn sign_root_learning_unlearning_v1(
    trust_config_path: &Path,
    dedicated_key_path: &Path,
    trust: &ActivatedLearningTrustV1,
    request: &UnlearningLineageRequestV1,
) -> ReviewResult<SignedLearningEvidenceV1> {
    let status = std::fs::read_to_string("/proc/self/status")?;
    let ids = status
        .lines()
        .find_map(|line| line.strip_prefix("Uid:"))
        .ok_or("UID status absent")?;
    if ids.split_whitespace().count() != 4 || ids.split_whitespace().any(|uid| uid != "0") {
        return Err("unlearning signer requires the original Root controller".into());
    }
    let bytes = read_root(trust_config_path, 16 * 1024, Access::Private)?;
    let config: IndependentTrustConfig = serde_json::from_slice(&bytes)?;
    let authority = config
        .unlearning_authority
        .as_ref()
        .ok_or("unlearning authority not enrolled")?;
    let program: Digest32 = authority.program_digest.parse()?;
    if config.schema != "hepta.fixed-custody-evaluator-trust.v1"
        || program_digest(&authority.program_path)? != program
        || program_digest(&std::env::current_exe()?)? != program
        || config.scope_digest.parse::<Digest32>()? != trust.verifier().scope_digest()
        || config.objective_digest.parse::<Digest32>()? != trust.verifier().objective_digest()
        || config.authority_epoch != trust.verifier().authority_epoch()
    {
        return Err("unlearning controller/config does not match current admitted trust".into());
    }
    let public: [u8; 32] = read_root(&authority.public_key_path, 32, Access::Immutable)?
        .try_into()
        .map_err(|_| "unlearning public key width")?;
    let seed: [u8; 32] = read_root(dedicated_key_path, 32, Access::Private)?
        .try_into()
        .map_err(|_| "unlearning private key width")?;
    let key = SigningKey::from_bytes(&seed);
    if key.verifying_key().to_bytes() != public {
        return Err("unlearning dedicated key differs from enrollment".into());
    }
    let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    trust.revalidate_at(now)?;
    if config.valid_from > now || config.expires_at <= now {
        return Err("unlearning configuration window".into());
    }
    let payload = unlearning_signing_payload_v1(request);
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: StableId::new(format!(
            "fixed-unlearning-evidence.{}",
            Digest32::of_bytes(&payload)
        ))?,
        principal_id: StableId::new("fixed-root-unlearning-authority")?,
        role: LearningEvidenceRoleV1::UnlearningAuthority,
        trust_digest: trust.verifier().trust_digest(),
        scope_digest: trust.verifier().scope_digest(),
        objective_digest: trust.verifier().objective_digest(),
        authority_epoch: trust.verifier().authority_epoch(),
        issued_at: now,
        expires_at: now
            .checked_add(60_000)
            .ok_or("unlearning expiry overflow")?
            .min(config.expires_at)
            .min(trust.expires_at()),
        payload_digest: Digest32::of_bytes(&payload),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    let verified = trust.verifier().verify(
        LearningEvidenceRoleV1::UnlearningAuthority,
        &evidence,
        &payload,
        now,
    )?;
    if verified.controller_id() != &controller(&public, program, trust.verifier().scope_digest())? {
        return Err("unlearning signing program is not the admitted operational controller".into());
    }
    Ok(evidence)
}
