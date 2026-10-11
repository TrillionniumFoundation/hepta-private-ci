use std::path::Path;

use serde::Serialize;
use serde::de::DeserializeOwned;

use crate::AcceptanceError;
use crate::CLAIM_SCHEMA;
use crate::RECEIPT_SCHEMA;
use crate::ceremony::path_present;
use crate::ceremony::path_string;
use crate::durable::MAX_SMALL_FILE_BYTES;
use crate::durable::canonical_json;
use crate::durable::secure_read;
use crate::durable::sha256;
use crate::durable::write_private_new;
use crate::model::AcceptanceChallenge;
use crate::model::AcceptanceReceipt;
use crate::model::AuthorityBoundary;
use crate::model::NonceClaim;
use crate::model::OperatorBinding;
use crate::model::SealedAcceptance;
use crate::model::SignatureBinding;
use crate::trust::SIGNATURE_ALGORITHM;
use crate::trust::SSHSIG_NAMESPACE;
use crate::trust::TrustAnchor;
use crate::trust::VerifiedSignature;

pub(crate) fn validate_receipt(
    receipt: &AcceptanceReceipt,
    challenge: &AcceptanceChallenge,
    challenge_sha256: &str,
    signature: &SignatureBinding,
) -> Result<(), AcceptanceError> {
    if receipt.schema != RECEIPT_SCHEMA
        || receipt.schema_version != 1
        || receipt.authority != AuthorityBoundary::evidence_acceptance_only()
        || receipt.authority != receipt.challenge.authority
        || receipt.challenge != *challenge
        || receipt.challenge_sha256 != challenge_sha256
        || receipt.signature != *signature
        || receipt.accepted_at_unix_seconds < challenge.issued_at_unix_seconds
        || receipt.accepted_at_unix_seconds >= challenge.expires_at_unix_seconds
    {
        return Err(invalid("stored acceptance receipt is inconsistent"));
    }
    Ok(())
}

pub(crate) fn persist_final_acceptance(
    receipt_path: &Path,
    claim_path: &Path,
    challenge: &AcceptanceChallenge,
    challenge_sha256: &str,
    operator: &OperatorBinding,
    verified: &VerifiedSignature,
    accepted_at_unix_seconds: u64,
) -> Result<SealedAcceptance, AcceptanceError> {
    if accepted_at_unix_seconds < challenge.not_before_unix_seconds
        || accepted_at_unix_seconds < challenge.issued_at_unix_seconds
        || accepted_at_unix_seconds >= challenge.expires_at_unix_seconds
    {
        return Err(invalid(
            "final trusted host time is outside the signed validity window",
        ));
    }
    if path_present(claim_path)? || path_present(receipt_path)? {
        return Err(invalid(
            "acceptance sidecar changed before nonce consumption",
        ));
    }
    let claim = NonceClaim {
        accepted_at_unix_seconds,
        challenge_sha256: challenge_sha256.to_string(),
        detached_signature_sha256: verified.detached_signature_sha256.clone(),
        nonce: challenge.nonce.clone(),
        schema: CLAIM_SCHEMA.to_string(),
        schema_version: 1,
    };
    write_private_new(claim_path, &canonical_json(&claim)?)?;

    let signature = signature_binding(operator, verified);
    let receipt = AcceptanceReceipt {
        accepted_at_unix_seconds,
        authority: AuthorityBoundary::evidence_acceptance_only(),
        challenge: challenge.clone(),
        challenge_sha256: challenge_sha256.to_string(),
        schema: RECEIPT_SCHEMA.to_string(),
        schema_version: 1,
        signature,
    };
    validate_receipt(&receipt, challenge, challenge_sha256, &receipt.signature)?;
    let receipt_bytes = canonical_json(&receipt)?;
    let receipt_sha256 = sha256(&receipt_bytes);
    write_private_new(receipt_path, &receipt_bytes)?;
    Ok(SealedAcceptance {
        acceptance_receipt_path: path_string(receipt_path)?,
        acceptance_receipt_sha256: receipt_sha256,
        challenge_sha256: challenge_sha256.to_string(),
    })
}

pub(crate) fn validate_idempotent_replay(
    receipt_path: &Path,
    claim_path: &Path,
    challenge: &AcceptanceChallenge,
    challenge_sha256: &str,
    expected_signature: &SignatureBinding,
) -> Result<SealedAcceptance, AcceptanceError> {
    let (receipt, receipt_bytes) =
        read_canonical::<AcceptanceReceipt>(receipt_path, "acceptance receipt")?;
    validate_receipt(&receipt, challenge, challenge_sha256, expected_signature)?;
    let (claim, _) = read_canonical::<NonceClaim>(claim_path, "nonce claim")?;
    let expected_claim = NonceClaim {
        accepted_at_unix_seconds: receipt.accepted_at_unix_seconds,
        challenge_sha256: challenge_sha256.to_string(),
        detached_signature_sha256: expected_signature.detached_signature_sha256.clone(),
        nonce: challenge.nonce.clone(),
        schema: CLAIM_SCHEMA.to_string(),
        schema_version: 1,
    };
    if claim != expected_claim {
        return Err(invalid(
            "stored nonce claim conflicts with the exact replay",
        ));
    }
    Ok(SealedAcceptance {
        acceptance_receipt_path: path_string(receipt_path)?,
        acceptance_receipt_sha256: sha256(&receipt_bytes),
        challenge_sha256: challenge_sha256.to_string(),
    })
}

pub(crate) fn verify_stored_acceptance(
    receipt_path: &Path,
    claim_path: &Path,
    challenge: &AcceptanceChallenge,
    challenge_bytes: &[u8],
    challenge_sha256: &str,
    trust: &TrustAnchor,
) -> Result<SealedAcceptance, AcceptanceError> {
    let (stored, _) = read_canonical::<AcceptanceReceipt>(receipt_path, "acceptance receipt")?;
    let verified = trust.verify_base64(
        challenge_bytes,
        &stored.signature.detached_signature_sshsig_base64,
    )?;
    let expected_signature = signature_binding(&trust.binding, &verified);
    validate_idempotent_replay(
        receipt_path,
        claim_path,
        challenge,
        challenge_sha256,
        &expected_signature,
    )
}

pub(crate) fn signature_binding(
    operator: &OperatorBinding,
    verified: &VerifiedSignature,
) -> SignatureBinding {
    SignatureBinding {
        algorithm: SIGNATURE_ALGORITHM.to_string(),
        allowed_signers_sha256: operator.allowed_signers_sha256.clone(),
        detached_signature_sha256: verified.detached_signature_sha256.clone(),
        detached_signature_sshsig_base64: verified.detached_signature_sshsig_base64.clone(),
        key_fingerprint: operator.key_fingerprint.clone(),
        namespace: SSHSIG_NAMESPACE.to_string(),
        principal: operator.principal.clone(),
    }
}

pub(crate) fn read_canonical<T: DeserializeOwned + Serialize>(
    path: &Path,
    label: &str,
) -> Result<(T, Vec<u8>), AcceptanceError> {
    let bytes = secure_read(path, MAX_SMALL_FILE_BYTES)?;
    let value: T = serde_json::from_slice(&bytes)
        .map_err(|error| invalid(format!("invalid {label}: {error}")))?;
    if canonical_json(&value)? != bytes {
        return Err(invalid(format!("{label} is not canonical JSON")));
    }
    Ok((value, bytes))
}

fn invalid(message: impl Into<String>) -> AcceptanceError {
    AcceptanceError::Invalid(message.into())
}
