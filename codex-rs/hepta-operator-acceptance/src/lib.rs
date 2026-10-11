mod ceremony;
mod durable;
mod evidence;
mod g5_trust;
mod manifest_inventory;
mod model;
mod preflight;
mod qualification_evidence;
mod qualification_runs;
mod receipt_store;
mod trust;

use serde::Deserialize;
use serde::Serialize;
use std::path::Path;
use thiserror::Error;

use ceremony::ValidatedRoots;
use ceremony::nonce_shape;
use ceremony::path_present;
use ceremony::path_string;
use ceremony::random_hex;
use ceremony::reject_existing;
use ceremony::trusted_time;
use durable::canonical_json;
use durable::lock_existing_sidecar;
use durable::lock_sidecar;
use durable::secure_read;
use durable::sha256;
use durable::write_private_atomic_replace;
use durable::write_private_new;
use evidence::EvidenceBinding;
use evidence::load_evidence;
use model::AcceptanceChallenge;
use model::AuthorityBoundary;
use model::ExcludedGates;
use model::OperatorBinding;
use receipt_store::persist_final_acceptance;
use receipt_store::read_canonical;
use receipt_store::verify_stored_acceptance;
use trust::SIGNATURE_ALGORITHM;
use trust::SSHSIG_NAMESPACE;
use trust::TRUST_POLICY_SCOPE;
use trust::TrustAnchor;
use trust::TrustInputs;

pub use g5_trust::G5_ASSESSMENT_SCHEMA;
pub use g5_trust::G5_CHALLENGE_SCHEMA;
pub use g5_trust::G5_CHALLENGE_SCOPE;
pub use g5_trust::G5_REVOCATION_SCHEMA;
pub use g5_trust::G5_TRUST_POLICY_SCHEMA;
pub use g5_trust::G5_TRUST_POLICY_SCOPE;
pub use g5_trust::G5AssessRequest;
pub use g5_trust::G5Assessment;
pub use g5_trust::G5AssessmentResult;
pub use g5_trust::G5AuthorityBoundary;
pub use g5_trust::G5EvidenceBinding;
pub use g5_trust::G5HeadBinding;
pub use g5_trust::G5PrepareRequest;
pub use g5_trust::G5PreparedChallenge;
pub use g5_trust::G5RevocationState;
pub use g5_trust::G5SignatureInput;
pub use g5_trust::G5TrustBinding;
pub use g5_trust::G5TrustInputs;
pub use g5_trust::G5TrustPolicy;
pub use g5_trust::assess_g5_challenge;
pub use g5_trust::prepare_g5_challenge;
pub use model::PreparedChallenge;
pub use model::SealedAcceptance;
pub use preflight::require_formal_environment;

const CHALLENGE_SCHEMA: &str = "hepta_operator_acceptance_v1";
const RECEIPT_SCHEMA: &str = "hepta_operator_acceptance_receipt_v1";
const CLAIM_SCHEMA: &str = "hepta_operator_acceptance_nonce_claim_v1";
const WATERMARK_SCHEMA: &str = "hepta_operator_acceptance_time_watermark_v1";
const ACCEPTANCE_SCOPE: &str = "qualification_evidence_only";
const DECISION: &str = "accept";
const DECLARATION: &str = "Accept only the exact qualification evidence and signed exclusions. This grants no authority for Enforce, promotion, outbound, or retirement. V1 applies no local KRL; the externally pinned policy owner remains responsible for key validity and revocation.";
const CHALLENGE_FILE: &str = "operator-acceptance-challenge.json";
const CLAIM_FILE: &str = "operator-acceptance-nonce-claim.json";
const RECEIPT_FILE: &str = "operator-acceptance-receipt.json";
const WATERMARK_FILE: &str = "operator-acceptance-time-watermark.json";
const DEFAULT_CHALLENGE_LIFETIME_SECONDS: u64 = 900;

#[derive(Debug, Error)]
pub enum AcceptanceError {
    #[error("operator acceptance rejected: {0}")]
    Invalid(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error("operator acceptance serialization failed: {0}")]
    Serialization(String),
}

pub struct PrepareRequest<'a> {
    pub allowed_signers_path: &'a Path,
    pub externally_pinned_trust_policy_sha256: &'a str,
    pub product_audit_root: &'a Path,
    pub qualification_root: &'a Path,
    pub sidecar_root: &'a Path,
    pub trust_policy_path: &'a Path,
}

pub struct VerifyRequest<'a> {
    pub allowed_signers_path: &'a Path,
    pub externally_pinned_trust_policy_sha256: &'a str,
    pub product_audit_root: &'a Path,
    pub qualification_root: &'a Path,
    pub sidecar_root: &'a Path,
    pub signature_path: &'a Path,
    pub trust_policy_path: &'a Path,
}

pub struct ReadReceiptRequest<'a> {
    pub allowed_signers_path: &'a Path,
    pub externally_pinned_trust_policy_sha256: &'a str,
    pub product_audit_root: &'a Path,
    pub qualification_root: &'a Path,
    pub sidecar_root: &'a Path,
    pub trust_policy_path: &'a Path,
}

pub fn prepare(request: PrepareRequest<'_>) -> Result<PreparedChallenge, AcceptanceError> {
    require_formal_environment()?;
    let roots = ValidatedRoots::load(
        request.qualification_root,
        request.product_audit_root,
        request.sidecar_root,
        request.allowed_signers_path,
        request.trust_policy_path,
    )?;
    let _lock = lock_sidecar(&roots.sidecar)?;
    reject_existing(&roots.sidecar.join(CHALLENGE_FILE), "challenge")?;
    reject_existing(&roots.sidecar.join(CLAIM_FILE), "nonce claim")?;
    reject_existing(&roots.sidecar.join(RECEIPT_FILE), "acceptance receipt")?;

    let evidence = load_evidence(&roots.qualification, &roots.product_audit)?;
    let trust = load_trust(&request, &roots)?;
    let issued_at = trusted_time()?;
    advance_time_watermark(
        &roots.sidecar,
        issued_at,
        request.externally_pinned_trust_policy_sha256,
    )?;
    let lifetime = DEFAULT_CHALLENGE_LIFETIME_SECONDS.min(trust.binding.maximum_lifetime_seconds);
    let expires_at = issued_at
        .checked_add(lifetime)
        .ok_or_else(|| invalid("challenge expiration overflows trusted time"))?;
    let challenge = AcceptanceChallenge {
        automatic_transition: false,
        authority: AuthorityBoundary::evidence_acceptance_only(),
        candidate: evidence.candidate.clone(),
        decision: DECISION.to_string(),
        declaration: DECLARATION.to_string(),
        expires_at_unix_seconds: expires_at,
        excluded_gates: ExcludedGates::none_run(),
        frozen_product: evidence.frozen_product.clone(),
        issued_at_unix_seconds: issued_at,
        namespace: SSHSIG_NAMESPACE.to_string(),
        nonce: random_hex::<32>()?,
        not_before_unix_seconds: issued_at,
        operator: trust.binding.clone(),
        oracle: evidence.oracle.clone(),
        qualification_receipt: evidence.qualification_receipt.clone(),
        schema: CHALLENGE_SCHEMA.to_string(),
        schema_version: 1,
        scope: ACCEPTANCE_SCOPE.to_string(),
        signature_algorithm: SIGNATURE_ALGORITHM.to_string(),
    };
    validate_challenge(&challenge, &evidence, &trust.binding)?;
    let bytes = canonical_json(&challenge)?;
    let digest = sha256(&bytes);
    let path = roots.sidecar.join(CHALLENGE_FILE);
    write_private_new(&path, &bytes)?;
    Ok(PreparedChallenge {
        challenge_path: path_string(&path)?,
        challenge_sha256: digest,
        expires_at_unix_seconds: expires_at,
    })
}

pub fn verify_and_seal(request: VerifyRequest<'_>) -> Result<SealedAcceptance, AcceptanceError> {
    require_formal_environment()?;
    let roots = ValidatedRoots::load(
        request.qualification_root,
        request.product_audit_root,
        request.sidecar_root,
        request.allowed_signers_path,
        request.trust_policy_path,
    )?;
    let _lock = lock_sidecar(&roots.sidecar)?;
    let first_time = trusted_time()?;
    advance_time_watermark(
        &roots.sidecar,
        first_time,
        request.externally_pinned_trust_policy_sha256,
    )?;

    let evidence = load_evidence(&roots.qualification, &roots.product_audit)?;
    let trust = load_trust_for_verify(&request, &roots)?;
    let challenge_path = roots.sidecar.join(CHALLENGE_FILE);
    let (challenge, challenge_bytes) =
        read_canonical::<AcceptanceChallenge>(&challenge_path, "acceptance challenge")?;
    validate_challenge(&challenge, &evidence, &trust.binding)?;
    let challenge_sha256 = sha256(&challenge_bytes);
    let receipt_path = roots.sidecar.join(RECEIPT_FILE);
    let claim_path = roots.sidecar.join(CLAIM_FILE);

    if path_present(&receipt_path)? {
        return verify_stored_acceptance(
            &receipt_path,
            &claim_path,
            &challenge,
            &challenge_bytes,
            &challenge_sha256,
            &trust,
        );
    }
    if path_present(&claim_path)? {
        return Err(invalid(
            "nonce was durably claimed but no PASS receipt exists; fail closed",
        ));
    }
    validate_time_window(&challenge, first_time)?;

    let verified = trust.verify(&challenge_bytes, request.signature_path)?;
    let trust_after = load_trust_for_verify(&request, &roots)?;
    if trust_after.binding != trust.binding {
        return Err(invalid("external trust policy changed during verification"));
    }
    let evidence_after = load_evidence(&roots.qualification, &roots.product_audit)?;
    if evidence_after != evidence {
        return Err(invalid(
            "frozen evidence changed during signature verification",
        ));
    }
    if secure_read(&challenge_path, durable::MAX_SMALL_FILE_BYTES)? != challenge_bytes {
        return Err(invalid(
            "canonical challenge changed during signature verification",
        ));
    }
    let accepted_at = trusted_time()?;
    advance_time_watermark(
        &roots.sidecar,
        accepted_at,
        request.externally_pinned_trust_policy_sha256,
    )?;
    persist_final_acceptance(
        &receipt_path,
        &claim_path,
        &challenge,
        &challenge_sha256,
        &trust.binding,
        &verified,
        accepted_at,
    )
}

pub fn verify_receipt(
    request: ReadReceiptRequest<'_>,
) -> Result<SealedAcceptance, AcceptanceError> {
    require_formal_environment()?;
    let roots = ValidatedRoots::load(
        request.qualification_root,
        request.product_audit_root,
        request.sidecar_root,
        request.allowed_signers_path,
        request.trust_policy_path,
    )?;
    let _lock = lock_existing_sidecar(&roots.sidecar)?;
    let evidence = load_evidence(&roots.qualification, &roots.product_audit)?;
    let trust = TrustAnchor::load(TrustInputs {
        acceptance_store_root: &roots.sidecar,
        allowed_signers_path: &roots.allowed_signers,
        externally_pinned_trust_policy_sha256: request.externally_pinned_trust_policy_sha256,
        trust_policy_path: &roots.trust_policy,
    })?;
    let challenge_path = roots.sidecar.join(CHALLENGE_FILE);
    let (challenge, challenge_bytes) =
        read_canonical::<AcceptanceChallenge>(&challenge_path, "acceptance challenge")?;
    validate_challenge(&challenge, &evidence, &trust.binding)?;
    let challenge_sha256 = sha256(&challenge_bytes);
    verify_stored_acceptance(
        &roots.sidecar.join(RECEIPT_FILE),
        &roots.sidecar.join(CLAIM_FILE),
        &challenge,
        &challenge_bytes,
        &challenge_sha256,
        &trust,
    )
}

fn load_trust(
    request: &PrepareRequest<'_>,
    roots: &ValidatedRoots,
) -> Result<TrustAnchor, AcceptanceError> {
    TrustAnchor::load(TrustInputs {
        acceptance_store_root: &roots.sidecar,
        allowed_signers_path: &roots.allowed_signers,
        externally_pinned_trust_policy_sha256: request.externally_pinned_trust_policy_sha256,
        trust_policy_path: &roots.trust_policy,
    })
}

fn load_trust_for_verify(
    request: &VerifyRequest<'_>,
    roots: &ValidatedRoots,
) -> Result<TrustAnchor, AcceptanceError> {
    TrustAnchor::load(TrustInputs {
        acceptance_store_root: &roots.sidecar,
        allowed_signers_path: &roots.allowed_signers,
        externally_pinned_trust_policy_sha256: request.externally_pinned_trust_policy_sha256,
        trust_policy_path: &roots.trust_policy,
    })
}

fn validate_challenge(
    challenge: &AcceptanceChallenge,
    evidence: &EvidenceBinding,
    operator: &OperatorBinding,
) -> Result<(), AcceptanceError> {
    if challenge.schema != CHALLENGE_SCHEMA
        || challenge.schema_version != 1
        || challenge.namespace != SSHSIG_NAMESPACE
        || challenge.signature_algorithm != SIGNATURE_ALGORITHM
        || challenge.scope != ACCEPTANCE_SCOPE
        || challenge.decision != DECISION
        || challenge.declaration != DECLARATION
        || challenge.automatic_transition
        || challenge.authority != AuthorityBoundary::evidence_acceptance_only()
        || challenge.excluded_gates != ExcludedGates::none_run()
        || challenge.candidate != evidence.candidate
        || challenge.frozen_product != evidence.frozen_product
        || challenge.oracle != evidence.oracle
        || challenge.qualification_receipt != evidence.qualification_receipt
        || challenge.operator != *operator
        || challenge.operator.trust_policy_scope != TRUST_POLICY_SCOPE
    {
        return Err(invalid(
            "challenge differs from the exact evidence-acceptance boundary",
        ));
    }
    if !nonce_shape(&challenge.nonce)
        || challenge.issued_at_unix_seconds == 0
        || challenge.not_before_unix_seconds != challenge.issued_at_unix_seconds
        || challenge.expires_at_unix_seconds <= challenge.issued_at_unix_seconds
    {
        return Err(invalid("challenge nonce or validity interval is malformed"));
    }
    let lifetime = challenge
        .expires_at_unix_seconds
        .checked_sub(challenge.issued_at_unix_seconds)
        .ok_or_else(|| invalid("challenge validity interval underflow"))?;
    if lifetime > DEFAULT_CHALLENGE_LIFETIME_SECONDS || lifetime > operator.maximum_lifetime_seconds
    {
        return Err(invalid("challenge lifetime exceeds the external policy"));
    }
    Ok(())
}

fn validate_time_window(
    challenge: &AcceptanceChallenge,
    trusted_now: u64,
) -> Result<(), AcceptanceError> {
    if trusted_now < challenge.not_before_unix_seconds
        || trusted_now < challenge.issued_at_unix_seconds
        || trusted_now >= challenge.expires_at_unix_seconds
    {
        return Err(invalid(
            "trusted host time is outside the signed validity window",
        ));
    }
    Ok(())
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct TimeWatermark {
    last_observed_unix_seconds: u64,
    schema: String,
    schema_version: u32,
    trust_policy_sha256: String,
}

fn advance_time_watermark(
    sidecar: &Path,
    observed: u64,
    trust_policy_sha256: &str,
) -> Result<(), AcceptanceError> {
    let path = sidecar.join(WATERMARK_FILE);
    if path_present(&path)? {
        let (stored, _) = read_canonical::<TimeWatermark>(&path, "trusted-time watermark")?;
        if stored.schema != WATERMARK_SCHEMA
            || stored.schema_version != 1
            || stored.trust_policy_sha256 != trust_policy_sha256
        {
            return Err(invalid(
                "trusted-time watermark has a different policy scope",
            ));
        }
        if observed < stored.last_observed_unix_seconds {
            return Err(invalid(
                "trusted host clock moved behind its durable watermark",
            ));
        }
    }
    let watermark = TimeWatermark {
        last_observed_unix_seconds: observed,
        schema: WATERMARK_SCHEMA.to_string(),
        schema_version: 1,
        trust_policy_sha256: trust_policy_sha256.to_string(),
    };
    let temporary = sidecar.join(format!(
        ".operator-acceptance-watermark-{}.tmp",
        random_hex::<16>()?
    ));
    write_private_atomic_replace(&path, &temporary, &canonical_json(&watermark)?)
}

fn invalid(message: impl Into<String>) -> AcceptanceError {
    AcceptanceError::Invalid(message.into())
}

#[cfg(test)]
mod test_support;

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;
