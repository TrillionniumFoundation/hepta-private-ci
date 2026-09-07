//! Independent, read-only trust preparation for the G5 candidate.
//!
//! This module deliberately stops at a head-scoped challenge and an assessor
//! receipt.  It never creates an operator-acceptance receipt, changes CALLERS,
//! or flips a release authority flag.  The external signer remains the only
//! party that can produce the detached SSHSIG consumed by a later ceremony.

#[cfg(unix)]
use std::io::Write;
use std::path::Path;
#[cfg(unix)]
use std::process::Command;
#[cfg(unix)]
use std::process::Stdio;

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest as _;

use crate::AcceptanceError;
use crate::ceremony::nonce_shape;
use crate::ceremony::path_string;
use crate::ceremony::random_hex;
use crate::durable::MAX_SMALL_FILE_BYTES;
use crate::durable::canonical_json;
use crate::durable::secure_canonical_file_path;
use crate::durable::secure_read;
use crate::durable::sha256;
use crate::durable::verify_secure_directory;
use crate::durable::write_private_new;
use crate::trust::SIGNATURE_ALGORITHM;
use crate::trust::SSHSIG_NAMESPACE;

pub const G5_TRUST_POLICY_SCHEMA: &str = "hepta_g5_operator_trust_policy_v1";
pub const G5_REVOCATION_SCHEMA: &str = "hepta_g5_operator_revocation_v1";
pub const G5_CHALLENGE_SCHEMA: &str = "hepta_g5_operator_challenge_v1";
pub const G5_ASSESSMENT_SCHEMA: &str = "hepta_g5_operator_assessment_v1";
pub const G5_TRUST_POLICY_SCOPE: &str =
    "g5_head_scoped_ed25519_external_policy_with_explicit_revocation_v1";
pub const G5_CHALLENGE_SCOPE: &str = "g5_bounded_evidence_only_no_release_or_unfreeze_authority";

const MAX_TRUST_FILE_BYTES: usize = 64 * 1024;
const MAX_SIGNATURE_BYTES: usize = 4 * 1024;
const MAX_LIFETIME_SECONDS: u64 = 900;
const ASSESSMENT_STATUS_READY: &str = "READY_FOR_CHALLENGE";
const ASSESSMENT_STATUS_SIGNATURE_VERIFIED: &str = "SIGNATURE_VERIFIED_NO_AUTHORITY";
const ASSESSMENT_STATUS_EXPIRED: &str = "EXPIRED";
const ASSESSMENT_STATUS_REVOKED: &str = "REVOKED";
const ASSESSMENT_STATUS_SIGNATURE_INVALID: &str = "SIGNATURE_INVALID";

/// External trust policy supplied out of band and pinned by its digest.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct G5TrustPolicy {
    pub allowed_signers_sha256: String,
    pub key_fingerprint: String,
    pub maximum_lifetime_seconds: u64,
    pub principal: String,
    pub revocation_owner: String,
    pub revocation_sha256: String,
    pub revocation_revision: u64,
    pub schema: String,
    pub schema_version: u32,
    pub trust_policy_scope: String,
    pub trust_root_id: String,
    pub trust_root_revision: u64,
}

/// Signed/external revocation state.  A policy owner rotates this document by
/// publishing a new digest and monotonically increasing `revocation_revision`.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct G5RevocationState {
    pub effective_at_unix_seconds: u64,
    pub revoked_challenge_sha256: Vec<String>,
    pub revoked_key_fingerprints: Vec<String>,
    pub revoked_nonces: Vec<String>,
    pub revocation_revision: u64,
    pub schema: String,
    pub schema_version: u32,
    pub trust_root_id: String,
    pub trust_root_revision: u64,
}

/// Values reconstructed from independently loaded policy files and copied into
/// the signed challenge.  No value is accepted from a challenge file itself.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct G5TrustBinding {
    pub allowed_signers_sha256: String,
    pub key_fingerprint: String,
    pub maximum_lifetime_seconds: u64,
    pub principal: String,
    pub revocation_owner: String,
    pub revocation_revision: u64,
    pub revocation_sha256: String,
    pub trust_policy_sha256: String,
    pub trust_policy_scope: String,
    pub trust_root_id: String,
    pub trust_root_revision: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct G5HeadBinding {
    pub base: String,
    pub head: String,
    pub parent_head: String,
    pub parent_tree: String,
    pub tree: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct G5EvidenceBinding {
    pub aggregate_sha256: String,
    pub evidence_manifest_sha256: String,
    pub sha256sums_sha256: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct G5AuthorityBoundary {
    pub deployment: bool,
    pub fleet_and_automation_unfrozen: bool,
    pub g5_allowed: bool,
    pub operator_acceptance: bool,
    pub promotion: bool,
    pub provider_physical_exactly_once: bool,
}

impl G5AuthorityBoundary {
    fn challenge_only() -> Self {
        Self {
            deployment: false,
            fleet_and_automation_unfrozen: false,
            g5_allowed: false,
            operator_acceptance: false,
            promotion: false,
            provider_physical_exactly_once: false,
        }
    }

    fn all_false() -> Self {
        Self {
            deployment: false,
            fleet_and_automation_unfrozen: false,
            g5_allowed: false,
            operator_acceptance: false,
            promotion: false,
            provider_physical_exactly_once: false,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct G5Challenge {
    pub authority: G5AuthorityBoundary,
    pub candidate: G5HeadBinding,
    pub decision: String,
    pub evidence: G5EvidenceBinding,
    pub expires_at_unix_seconds: u64,
    pub issued_at_unix_seconds: u64,
    pub namespace: String,
    pub nonce: String,
    pub not_before_unix_seconds: u64,
    pub schema: String,
    pub schema_version: u32,
    pub scope: String,
    pub signature_algorithm: String,
    pub trust: G5TrustBinding,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct G5Assessment {
    pub authority: G5AuthorityBoundary,
    pub blockers: Vec<String>,
    pub challenge_sha256: String,
    pub checked_at_unix_seconds: u64,
    pub evidence: G5EvidenceBinding,
    pub expires_at_unix_seconds: u64,
    pub head: G5HeadBinding,
    pub kind: String,
    pub policy_sha256: String,
    pub revocation_sha256: String,
    pub schema: String,
    pub schema_version: u32,
    pub signature_digest: Option<String>,
    pub signature_present: bool,
    pub signature_verified: bool,
    pub status: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct G5PreparedChallenge {
    pub challenge_path: String,
    pub challenge_sha256: String,
    pub expires_at_unix_seconds: u64,
    pub nonce: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct G5AssessmentResult {
    pub assessment_path: Option<String>,
    pub assessment_sha256: String,
    pub challenge_sha256: String,
    pub signature_verified: bool,
    pub status: String,
}

type G5SignatureAssessment = (String, bool, bool, Option<String>, Vec<String>);

pub struct G5TrustInputs<'a> {
    pub allowed_signers_path: &'a Path,
    pub externally_pinned_policy_sha256: &'a str,
    pub revocation_path: &'a Path,
    pub trust_policy_path: &'a Path,
}

pub struct G5PrepareRequest<'a> {
    pub challenge_path: &'a Path,
    pub candidate: G5HeadBinding,
    pub evidence: G5EvidenceBinding,
    pub lifetime_seconds: u64,
    pub now_unix_seconds: u64,
    pub trust: G5TrustInputs<'a>,
}

pub enum G5SignatureInput<'a> {
    Absent,
    Detached(&'a Path),
}

pub struct G5AssessRequest<'a> {
    pub assessment_path: Option<&'a Path>,
    pub challenge_path: &'a Path,
    pub expected_candidate: G5HeadBinding,
    pub expected_evidence: G5EvidenceBinding,
    pub now_unix_seconds: u64,
    pub signature: G5SignatureInput<'a>,
    pub trust: G5TrustInputs<'a>,
}

struct LoadedG5Trust {
    binding: G5TrustBinding,
    policy: G5TrustPolicy,
    revocation: G5RevocationState,
    allowed_signers: Vec<u8>,
}

/// Create a canonical challenge only.  This function has no signing path and
/// never writes an acceptance receipt or mutates authority state.
pub fn prepare_g5_challenge(
    request: G5PrepareRequest<'_>,
) -> Result<G5PreparedChallenge, AcceptanceError> {
    let trust = load_g5_trust(request.trust)?;
    validate_head_binding(&request.candidate)?;
    validate_evidence_binding(&request.evidence)?;
    if request.now_unix_seconds == 0 {
        return Err(invalid("challenge time must be nonzero"));
    }
    if request.lifetime_seconds == 0
        || request.lifetime_seconds > MAX_LIFETIME_SECONDS
        || request.lifetime_seconds > trust.policy.maximum_lifetime_seconds
    {
        return Err(invalid(
            "challenge lifetime exceeds the pinned trust policy",
        ));
    }
    if is_key_revoked(&trust, request.now_unix_seconds) {
        return Err(invalid("trusted signer is revoked at challenge issuance"));
    }
    let expires_at = request
        .now_unix_seconds
        .checked_add(request.lifetime_seconds)
        .ok_or_else(|| invalid("challenge expiration overflows"))?;
    let challenge = G5Challenge {
        authority: G5AuthorityBoundary::challenge_only(),
        candidate: request.candidate,
        decision: "accept_bounded_evidence_only".to_string(),
        evidence: request.evidence,
        expires_at_unix_seconds: expires_at,
        issued_at_unix_seconds: request.now_unix_seconds,
        namespace: SSHSIG_NAMESPACE.to_string(),
        nonce: random_hex::<32>()?,
        not_before_unix_seconds: request.now_unix_seconds,
        schema: G5_CHALLENGE_SCHEMA.to_string(),
        schema_version: 1,
        scope: G5_CHALLENGE_SCOPE.to_string(),
        signature_algorithm: SIGNATURE_ALGORITHM.to_string(),
        trust: trust.binding.clone(),
    };
    validate_g5_challenge(
        &challenge,
        &challenge.candidate,
        &challenge.evidence,
        &trust,
    )?;
    let bytes = canonical_json(&challenge)?;
    validate_new_private_path(request.challenge_path, "G5 challenge")?;
    write_private_new(request.challenge_path, &bytes)?;
    Ok(G5PreparedChallenge {
        challenge_path: path_string(request.challenge_path)?,
        challenge_sha256: sha256(&bytes),
        expires_at_unix_seconds: expires_at,
        nonce: challenge.nonce,
    })
}

/// Independently assess a challenge.  A missing signature yields
/// `READY_FOR_CHALLENGE`; a supplied valid signature yields
/// `SIGNATURE_VERIFIED_NO_AUTHORITY`.  Neither status creates acceptance or
/// changes a CALLERS/production flag.
pub fn assess_g5_challenge(
    request: G5AssessRequest<'_>,
) -> Result<G5AssessmentResult, AcceptanceError> {
    let trust = load_g5_trust(request.trust)?;
    let challenge_path = secure_canonical_file_path(request.challenge_path, "G5 challenge")?;
    let challenge_bytes = secure_read(&challenge_path, MAX_SMALL_FILE_BYTES)?;
    let challenge: G5Challenge = serde_json::from_slice(&challenge_bytes)
        .map_err(|error| invalid(format!("invalid G5 challenge: {error}")))?;
    if canonical_json(&challenge)? != challenge_bytes {
        return Err(invalid("G5 challenge is not canonical JSON"));
    }
    validate_g5_challenge(
        &challenge,
        &request.expected_candidate,
        &request.expected_evidence,
        &trust,
    )?;
    let challenge_sha256 = sha256(&challenge_bytes);
    let (status, signature_present, signature_verified, signature_digest, mut blockers) =
        if request.now_unix_seconds < challenge.not_before_unix_seconds
            || request.now_unix_seconds >= challenge.expires_at_unix_seconds
        {
            (
                ASSESSMENT_STATUS_EXPIRED.to_string(),
                false,
                false,
                None,
                vec!["challenge validity window is not currently open".to_string()],
            )
        } else if let Some(reason) = revocation_reason(
            &trust,
            &challenge,
            &challenge_sha256,
            request.now_unix_seconds,
        ) {
            (
                ASSESSMENT_STATUS_REVOKED.to_string(),
                false,
                false,
                None,
                vec![reason],
            )
        } else {
            assess_signature(&request.signature, &challenge_bytes, &trust)?
        };
    if status == ASSESSMENT_STATUS_READY {
        blockers.push("independent signer must sign the exact challenge bytes".to_string());
    }
    if status == ASSESSMENT_STATUS_SIGNATURE_VERIFIED {
        blockers.push(
            "signature verification alone does not create operator acceptance or promotion"
                .to_string(),
        );
    }
    let assessment = G5Assessment {
        authority: G5AuthorityBoundary::all_false(),
        blockers,
        challenge_sha256: challenge_sha256.clone(),
        checked_at_unix_seconds: request.now_unix_seconds,
        evidence: challenge.evidence.clone(),
        expires_at_unix_seconds: challenge.expires_at_unix_seconds,
        head: challenge.candidate,
        kind: "hepta-g5-operator-assessment".to_string(),
        policy_sha256: trust.binding.trust_policy_sha256.clone(),
        revocation_sha256: trust.binding.revocation_sha256,
        schema: G5_ASSESSMENT_SCHEMA.to_string(),
        schema_version: 1,
        signature_digest,
        signature_present,
        signature_verified,
        status: status.clone(),
    };
    let bytes = canonical_json(&assessment)?;
    let assessment_sha256 = sha256(&bytes);
    let assessment_path = if let Some(path) = request.assessment_path {
        validate_new_private_path(path, "G5 assessment")?;
        write_private_new(path, &bytes)?;
        Some(path_string(path)?)
    } else {
        None
    };
    Ok(G5AssessmentResult {
        assessment_path,
        assessment_sha256,
        challenge_sha256,
        signature_verified,
        status,
    })
}

fn assess_signature(
    signature: &G5SignatureInput<'_>,
    statement: &[u8],
    trust: &LoadedG5Trust,
) -> Result<G5SignatureAssessment, AcceptanceError> {
    let G5SignatureInput::Detached(path) = signature else {
        return Ok((
            ASSESSMENT_STATUS_READY.to_string(),
            false,
            false,
            None,
            Vec::new(),
        ));
    };
    let signature_path = secure_canonical_file_path(path, "G5 detached SSHSIG")?;
    let bytes = secure_read(&signature_path, MAX_SIGNATURE_BYTES)?;
    if !bytes.starts_with(b"-----BEGIN SSH SIGNATURE-----\n")
        || !bytes.ends_with(b"-----END SSH SIGNATURE-----\n")
    {
        return Ok((
            ASSESSMENT_STATUS_SIGNATURE_INVALID.to_string(),
            true,
            false,
            Some(sha256(&bytes)),
            vec!["detached signature is not an OpenSSH SSHSIG envelope".to_string()],
        ));
    }
    let digest = sha256(&bytes);
    match verify_sshsig_bytes(
        statement,
        &bytes,
        &trust.allowed_signers,
        &trust.binding.principal,
        SSHSIG_NAMESPACE,
    ) {
        Ok(()) => Ok((
            ASSESSMENT_STATUS_SIGNATURE_VERIFIED.to_string(),
            true,
            true,
            Some(digest),
            Vec::new(),
        )),
        Err(_) => Ok((
            ASSESSMENT_STATUS_SIGNATURE_INVALID.to_string(),
            true,
            false,
            Some(digest),
            vec!["OpenSSH SSHSIG verification failed".to_string()],
        )),
    }
}

fn load_g5_trust(inputs: G5TrustInputs<'_>) -> Result<LoadedG5Trust, AcceptanceError> {
    if !digest_shape(inputs.externally_pinned_policy_sha256) {
        return Err(invalid("pinned G5 trust-policy digest is malformed"));
    }
    let policy_path = secure_canonical_file_path(inputs.trust_policy_path, "G5 trust policy")?;
    let policy_bytes = secure_read(&policy_path, MAX_TRUST_FILE_BYTES)?;
    if sha256(&policy_bytes) != inputs.externally_pinned_policy_sha256 {
        return Err(invalid("G5 trust policy differs from its pinned digest"));
    }
    let policy: G5TrustPolicy = serde_json::from_slice(&policy_bytes)
        .map_err(|error| invalid(format!("invalid G5 trust policy: {error}")))?;
    if canonical_json(&policy)? != policy_bytes {
        return Err(invalid("G5 trust policy is not canonical JSON"));
    }
    validate_policy(&policy)?;

    let allowed_path =
        secure_canonical_file_path(inputs.allowed_signers_path, "G5 allowed_signers")?;
    let allowed_signers = secure_read(&allowed_path, MAX_TRUST_FILE_BYTES)?;
    if sha256(&allowed_signers) != policy.allowed_signers_sha256 {
        return Err(invalid("G5 allowed_signers digest differs from policy"));
    }
    let fingerprint = parse_allowed_signer(&allowed_signers, &policy.principal)?;
    if fingerprint != policy.key_fingerprint {
        return Err(invalid(
            "G5 allowed_signers fingerprint differs from policy",
        ));
    }

    let revocation_path =
        secure_canonical_file_path(inputs.revocation_path, "G5 revocation state")?;
    let revocation_bytes = secure_read(&revocation_path, MAX_TRUST_FILE_BYTES)?;
    if sha256(&revocation_bytes) != policy.revocation_sha256 {
        return Err(invalid("G5 revocation state differs from policy"));
    }
    let revocation: G5RevocationState = serde_json::from_slice(&revocation_bytes)
        .map_err(|error| invalid(format!("invalid G5 revocation state: {error}")))?;
    if canonical_json(&revocation)? != revocation_bytes {
        return Err(invalid("G5 revocation state is not canonical JSON"));
    }
    validate_revocation(&policy, &revocation)?;

    Ok(LoadedG5Trust {
        binding: G5TrustBinding {
            allowed_signers_sha256: policy.allowed_signers_sha256.clone(),
            key_fingerprint: policy.key_fingerprint.clone(),
            maximum_lifetime_seconds: policy.maximum_lifetime_seconds,
            principal: policy.principal.clone(),
            revocation_owner: policy.revocation_owner.clone(),
            revocation_revision: policy.revocation_revision,
            revocation_sha256: policy.revocation_sha256.clone(),
            trust_policy_sha256: inputs.externally_pinned_policy_sha256.to_string(),
            trust_policy_scope: policy.trust_policy_scope.clone(),
            trust_root_id: policy.trust_root_id.clone(),
            trust_root_revision: policy.trust_root_revision,
        },
        policy,
        revocation,
        allowed_signers,
    })
}

fn validate_policy(policy: &G5TrustPolicy) -> Result<(), AcceptanceError> {
    if policy.schema != G5_TRUST_POLICY_SCHEMA
        || policy.schema_version != 1
        || policy.trust_policy_scope != G5_TRUST_POLICY_SCOPE
    {
        return Err(invalid("G5 trust policy schema or scope is invalid"));
    }
    validate_identifier(&policy.principal, "G5 principal")?;
    validate_identifier(&policy.revocation_owner, "G5 revocation owner")?;
    validate_identifier(&policy.trust_root_id, "G5 trust root id")?;
    if policy.trust_root_revision == 0 || policy.revocation_revision == 0 {
        return Err(invalid("G5 trust revisions must be nonzero"));
    }
    if policy.maximum_lifetime_seconds == 0
        || policy.maximum_lifetime_seconds > MAX_LIFETIME_SECONDS
    {
        return Err(invalid("G5 lifetime must be within 1..=900 seconds"));
    }
    if !digest_shape(&policy.allowed_signers_sha256)
        || !digest_shape(&policy.revocation_sha256)
        || !fingerprint_shape(&policy.key_fingerprint)
    {
        return Err(invalid("G5 trust policy contains malformed digests"));
    }
    Ok(())
}

fn validate_revocation(
    policy: &G5TrustPolicy,
    revocation: &G5RevocationState,
) -> Result<(), AcceptanceError> {
    if revocation.schema != G5_REVOCATION_SCHEMA
        || revocation.schema_version != 1
        || revocation.trust_root_id != policy.trust_root_id
        || revocation.trust_root_revision != policy.trust_root_revision
        || revocation.revocation_revision != policy.revocation_revision
        || revocation.effective_at_unix_seconds == 0
    {
        return Err(invalid(
            "G5 revocation state is outside the pinned trust root",
        ));
    }
    validate_sorted_unique(
        &revocation.revoked_challenge_sha256,
        |value| digest_shape(value),
        "challenge digest",
    )?;
    validate_sorted_unique(
        &revocation.revoked_nonces,
        |value| nonce_shape(value),
        "nonce",
    )?;
    validate_sorted_unique(
        &revocation.revoked_key_fingerprints,
        |value| fingerprint_shape(value),
        "key fingerprint",
    )?;
    Ok(())
}

fn validate_g5_challenge(
    challenge: &G5Challenge,
    expected_candidate: &G5HeadBinding,
    expected_evidence: &G5EvidenceBinding,
    trust: &LoadedG5Trust,
) -> Result<(), AcceptanceError> {
    if challenge.schema != G5_CHALLENGE_SCHEMA
        || challenge.schema_version != 1
        || challenge.namespace != SSHSIG_NAMESPACE
        || challenge.signature_algorithm != SIGNATURE_ALGORITHM
        || challenge.scope != G5_CHALLENGE_SCOPE
        || challenge.decision != "accept_bounded_evidence_only"
        || challenge.authority != G5AuthorityBoundary::challenge_only()
        || challenge.candidate != *expected_candidate
        || challenge.evidence != *expected_evidence
        || challenge.trust != trust.binding
    {
        return Err(invalid(
            "G5 challenge differs from independently expected binding",
        ));
    }
    validate_head_binding(&challenge.candidate)?;
    validate_evidence_binding(&challenge.evidence)?;
    if !nonce_shape(&challenge.nonce)
        || challenge.issued_at_unix_seconds == 0
        || challenge.not_before_unix_seconds != challenge.issued_at_unix_seconds
        || challenge.expires_at_unix_seconds <= challenge.issued_at_unix_seconds
    {
        return Err(invalid("G5 challenge nonce or time interval is malformed"));
    }
    let lifetime = challenge
        .expires_at_unix_seconds
        .checked_sub(challenge.issued_at_unix_seconds)
        .ok_or_else(|| invalid("G5 challenge interval underflow"))?;
    if lifetime == 0
        || lifetime > MAX_LIFETIME_SECONDS
        || lifetime > trust.binding.maximum_lifetime_seconds
    {
        return Err(invalid("G5 challenge lifetime exceeds policy"));
    }
    Ok(())
}

fn validate_head_binding(binding: &G5HeadBinding) -> Result<(), AcceptanceError> {
    for (value, label) in [
        (&binding.base, "G5 base"),
        (&binding.head, "G5 head"),
        (&binding.tree, "G5 tree"),
        (&binding.parent_head, "G5 parent head"),
        (&binding.parent_tree, "G5 parent tree"),
    ] {
        if value.len() != 40
            || !value
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
        {
            return Err(invalid(format!("{label} must be a 40-character hex id")));
        }
    }
    if binding.head == binding.parent_head {
        return Err(invalid("G5 head and parent head must differ"));
    }
    Ok(())
}

fn validate_evidence_binding(binding: &G5EvidenceBinding) -> Result<(), AcceptanceError> {
    for (value, label) in [
        (&binding.aggregate_sha256, "G5 aggregate digest"),
        (
            &binding.evidence_manifest_sha256,
            "G5 evidence manifest digest",
        ),
        (&binding.sha256sums_sha256, "G5 SHA256SUMS digest"),
    ] {
        if !digest_shape(value) {
            return Err(invalid(format!("{label} is malformed")));
        }
    }
    Ok(())
}

fn revocation_reason(
    trust: &LoadedG5Trust,
    challenge: &G5Challenge,
    challenge_sha256: &str,
    now_unix_seconds: u64,
) -> Option<String> {
    if now_unix_seconds < trust.revocation.effective_at_unix_seconds {
        return None;
    }
    if trust
        .revocation
        .revoked_key_fingerprints
        .contains(&trust.binding.key_fingerprint)
    {
        return Some("trusted signer key is revoked by external policy".to_string());
    }
    if trust
        .revocation
        .revoked_challenge_sha256
        .contains(&challenge_sha256.to_string())
    {
        return Some("challenge digest is revoked by external policy".to_string());
    }
    if trust.revocation.revoked_nonces.contains(&challenge.nonce) {
        return Some("challenge nonce is revoked by external policy".to_string());
    }
    None
}

fn is_key_revoked(trust: &LoadedG5Trust, now: u64) -> bool {
    now >= trust.revocation.effective_at_unix_seconds
        && trust
            .revocation
            .revoked_key_fingerprints
            .contains(&trust.binding.key_fingerprint)
}

fn validate_sorted_unique<T: Ord>(
    values: &[T],
    valid: impl Fn(&T) -> bool,
    label: &str,
) -> Result<(), AcceptanceError> {
    if values.windows(2).any(|window| window[0] >= window[1])
        || values.iter().any(|value| !valid(value))
    {
        return Err(invalid(format!(
            "G5 revocation {label} list is not sorted and unique"
        )));
    }
    Ok(())
}

fn validate_identifier(value: &str, label: &str) -> Result<(), AcceptanceError> {
    if value.is_empty()
        || value.len() > 128
        || !value.bytes().all(|byte| {
            byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b':' | b'/' | b'@' | b'-')
        })
    {
        return Err(invalid(format!("{label} has an invalid identifier")));
    }
    Ok(())
}

fn validate_new_private_path(path: &Path, label: &str) -> Result<(), AcceptanceError> {
    if !path.is_absolute() {
        return Err(invalid(format!("{label} path must be absolute")));
    }
    let parent = path
        .parent()
        .ok_or_else(|| invalid(format!("{label} path has no parent")))?;
    let canonical_parent = parent.canonicalize()?;
    if canonical_parent != parent {
        return Err(invalid(format!(
            "{label} parent must be canonical and contain no symlink components"
        )));
    }
    verify_secure_directory(parent, &format!("{label} parent"))?;
    match std::fs::symlink_metadata(path) {
        Ok(_) => Err(invalid(format!("{label} already exists"))),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error.into()),
    }
}

fn digest_shape(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

fn fingerprint_shape(value: &str) -> bool {
    value.len() >= 16
        && value.len() <= 64
        && value.starts_with("SHA256:")
        && value[7..]
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'+' | b'/'))
}

fn invalid(message: impl Into<String>) -> AcceptanceError {
    AcceptanceError::Invalid(message.into())
}

fn parse_allowed_signer(bytes: &[u8], principal: &str) -> Result<String, AcceptanceError> {
    let text =
        std::str::from_utf8(bytes).map_err(|_| invalid("G5 allowed_signers is not UTF-8"))?;
    if !text.ends_with('\n') || text.contains('\r') {
        return Err(invalid(
            "G5 allowed_signers must be LF-terminated without carriage returns",
        ));
    }
    let lines = text.lines().collect::<Vec<_>>();
    if lines.len() != 1 {
        return Err(invalid(
            "G5 trust policy requires exactly one allowed signer",
        ));
    }
    let fields = lines[0].split_ascii_whitespace().collect::<Vec<_>>();
    if fields.len() != 3 || fields[0] != principal || fields[1] != "ssh-ed25519" {
        return Err(invalid(
            "G5 allowed_signers principal or algorithm mismatch",
        ));
    }
    let blob = STANDARD
        .decode(fields[2])
        .map_err(|_| invalid("G5 allowed_signers key is not valid base64"))?;
    if STANDARD.encode(&blob) != fields[2] {
        return Err(invalid("G5 allowed_signers key encoding is not canonical"));
    }
    validate_ed25519_blob(&blob)?;
    Ok(format!(
        "SHA256:{}",
        STANDARD_NO_PAD.encode(sha2::Sha256::digest(&blob))
    ))
}

fn validate_ed25519_blob(blob: &[u8]) -> Result<(), AcceptanceError> {
    let (algorithm, rest) = take_ssh_string(blob)?;
    let (key, rest) = take_ssh_string(rest)?;
    let key: [u8; 32] = key
        .try_into()
        .map_err(|_| invalid("G5 Ed25519 public key must be 32 bytes"))?;
    let verifying_key = VerifyingKey::from_bytes(&key)
        .map_err(|_| invalid("G5 allowed_signers contains an invalid Ed25519 point"))?;
    if algorithm != b"ssh-ed25519" || !rest.is_empty() || verifying_key.is_weak() {
        return Err(invalid("G5 allowed_signers key blob is malformed or weak"));
    }
    Ok(())
}

fn take_ssh_string(bytes: &[u8]) -> Result<(&[u8], &[u8]), AcceptanceError> {
    let prefix: [u8; 4] = bytes
        .get(..4)
        .ok_or_else(|| invalid("truncated G5 SSH public key blob"))?
        .try_into()
        .map_err(|_| invalid("truncated G5 SSH public key length"))?;
    let length = usize::try_from(u32::from_be_bytes(prefix))
        .map_err(|_| invalid("G5 SSH public key length overflow"))?;
    let end = 4_usize
        .checked_add(length)
        .ok_or_else(|| invalid("G5 SSH public key length overflow"))?;
    let value = bytes
        .get(4..end)
        .ok_or_else(|| invalid("truncated G5 SSH public key value"))?;
    let rest = bytes
        .get(end..)
        .ok_or_else(|| invalid("truncated G5 SSH public key remainder"))?;
    Ok((value, rest))
}

fn verify_sshsig_bytes(
    statement: &[u8],
    signature_bytes: &[u8],
    allowed_signers_bytes: &[u8],
    principal: &str,
    namespace: &str,
) -> Result<(), AcceptanceError> {
    #[cfg(unix)]
    {
        let allowed_signers = G5InheritedPipe::new(allowed_signers_bytes)?;
        let signature = G5InheritedPipe::new(signature_bytes)?;
        let mut child = Command::new("/usr/bin/ssh-keygen")
            .args(["-Y", "verify", "-f"])
            .arg(allowed_signers.child_path())
            .args(["-I", principal, "-n", namespace, "-s"])
            .arg(signature.child_path())
            .env_clear()
            .env("LANG", "C")
            .env("LC_ALL", "C")
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|error| invalid(format!("failed to start G5 ssh-keygen: {error}")))?;
        let write_result = child
            .stdin
            .take()
            .ok_or_else(|| invalid("G5 ssh-keygen stdin is unavailable"))?
            .write_all(statement);
        let status = child.wait();
        write_result?;
        if !status?.success() {
            return Err(invalid("G5 SSHSIG verification failed"));
        }
        Ok(())
    }
    #[cfg(not(unix))]
    {
        let _ = (
            statement,
            signature_bytes,
            allowed_signers_bytes,
            principal,
            namespace,
        );
        Err(invalid("G5 SSHSIG verification requires Unix"))
    }
}

#[cfg(unix)]
struct G5InheritedPipe {
    read_fd: std::os::fd::OwnedFd,
}

#[cfg(unix)]
impl G5InheritedPipe {
    fn new(bytes: &[u8]) -> Result<Self, AcceptanceError> {
        use std::fs::File;
        use std::os::fd::FromRawFd;
        use std::os::fd::OwnedFd;

        let mut raw = [-1; 2];
        // SAFETY: `pipe` receives a valid two-element integer array and writes
        // exactly two owned descriptors on success.
        if unsafe { libc::pipe(raw.as_mut_ptr()) } != 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        // SAFETY: successful `pipe` returned two newly owned descriptors.
        let read_fd = unsafe { OwnedFd::from_raw_fd(raw[0]) };
        // SAFETY: successful `pipe` returned two newly owned descriptors.
        let write_fd = unsafe { OwnedFd::from_raw_fd(raw[1]) };
        clear_g5_close_on_exec(&read_fd)?;
        let mut writer = File::from(write_fd);
        writer.write_all(bytes)?;
        drop(writer);
        Ok(Self { read_fd })
    }

    fn child_path(&self) -> String {
        use std::os::fd::AsRawFd;
        format!("/dev/fd/{}", self.read_fd.as_raw_fd())
    }
}

#[cfg(unix)]
fn clear_g5_close_on_exec(fd: &std::os::fd::OwnedFd) -> Result<(), AcceptanceError> {
    use std::os::fd::AsRawFd;

    // SAFETY: `fcntl` receives a live descriptor and does not dereference
    // application memory for F_GETFD/F_SETFD.
    let flags = unsafe { libc::fcntl(fd.as_raw_fd(), libc::F_GETFD) };
    if flags == -1
        || unsafe { libc::fcntl(fd.as_raw_fd(), libc::F_SETFD, flags & !libc::FD_CLOEXEC) } == -1
    {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(())
}

#[cfg(test)]
#[path = "g5_trust_tests.rs"]
mod tests;
