//! Complete public trust material for the same protected CURRENT reader.
//! Decoding alone creates no reader, writer lease, signing key or grant.
use super::*;
use std::io::Read;
use std::os::unix::fs::MetadataExt;
const MAGIC: &str = "HEPTA-ARTIFACT-PUBLIC-TRUST-V1";
pub const MAX_ARTIFACT_PUBLIC_TRUST_BYTES_V1: usize = 64 * 1024;

pub fn encode_artifact_public_trust_v1(
    trust: &ArtifactOwnerTrustV1,
) -> Result<Vec<u8>, ArtifactOwnerHostError> {
    let trust = ArtifactOwnerVerifierV1::new(trust.clone())?.trust;
    let mut text = format!(
        "{MAGIC}\n{}\n{}\n{}\n{}\n{}\n",
        trust.registry_id,
        trust.withdrawal_scope_digest,
        trust.minimum_registry_generation.get(),
        trust.genesis_predecessor_head_digest,
        trust.minimum_authority_epoch
    );
    for signers in [&trust.writer_signers, &trust.head_signers] {
        if signers.len() > 128 {
            return Err(ArtifactOwnerHostError::InvalidTrust);
        }
        text.push_str(&format!("{}\n", signers.len()));
        for signer in signers {
            let key = Digest32::from_array(signer.verifying_key);
            let revoked = signer
                .revoked_at
                .map_or_else(|| "-".into(), |at| at.to_string());
            text.push_str(&format!(
                "{}\n{}\n{}\n{}\n{}\n{}\n{}\n",
                signer.signer_id,
                key,
                signer.minimum_authority_epoch,
                signer.maximum_authority_epoch,
                signer.valid_from,
                signer.expires_at,
                revoked
            ));
        }
    }
    if text.len() > MAX_ARTIFACT_PUBLIC_TRUST_BYTES_V1 {
        return Err(ArtifactOwnerHostError::InvalidTrust);
    }
    Ok(text.into_bytes())
}
pub fn decode_artifact_public_trust_v1(
    bytes: &[u8],
) -> Result<ArtifactOwnerTrustV1, ArtifactOwnerHostError> {
    if bytes.is_empty()
        || bytes.len() > MAX_ARTIFACT_PUBLIC_TRUST_BYTES_V1
        || !bytes.ends_with(b"\n")
    {
        return Err(ArtifactOwnerHostError::InvalidTrust);
    }
    let text = std::str::from_utf8(bytes).map_err(|_| ArtifactOwnerHostError::InvalidTrust)?;
    let mut fields = text.lines();
    let next = |fields: &mut std::str::Lines<'_>| -> Result<String, ArtifactOwnerHostError> {
        fields
            .next()
            .map(str::to_owned)
            .ok_or(ArtifactOwnerHostError::InvalidTrust)
    };
    let number = |fields: &mut std::str::Lines<'_>| -> Result<u64, ArtifactOwnerHostError> {
        next(fields)?
            .parse()
            .map_err(|_| ArtifactOwnerHostError::InvalidTrust)
    };
    if next(&mut fields)? != MAGIC {
        return Err(ArtifactOwnerHostError::InvalidTrust);
    }
    let registry_id =
        StableId::new(next(&mut fields)?).map_err(|_| ArtifactOwnerHostError::InvalidTrust)?;
    let withdrawal_scope_digest = next(&mut fields)?
        .parse()
        .map_err(|_| ArtifactOwnerHostError::InvalidTrust)?;
    let minimum_registry_generation =
        Generation::new(number(&mut fields)?).map_err(|_| ArtifactOwnerHostError::InvalidTrust)?;
    let genesis_predecessor_head_digest = next(&mut fields)?
        .parse()
        .map_err(|_| ArtifactOwnerHostError::InvalidTrust)?;
    let minimum_authority_epoch = number(&mut fields)?;
    let mut sets = Vec::new();
    for _ in 0..2 {
        let count = number(&mut fields)?;
        if count > 128 {
            return Err(ArtifactOwnerHostError::InvalidTrust);
        }
        let mut signers = Vec::new();
        for _ in 0..count {
            let signer_id = StableId::new(next(&mut fields)?)
                .map_err(|_| ArtifactOwnerHostError::InvalidTrust)?;
            let key: Digest32 = next(&mut fields)?
                .parse()
                .map_err(|_| ArtifactOwnerHostError::InvalidTrust)?;
            let minimum_authority_epoch = number(&mut fields)?;
            let maximum_authority_epoch = number(&mut fields)?;
            let valid_from = number(&mut fields)?;
            let expires_at = number(&mut fields)?;
            let revoked = next(&mut fields)?;
            let revoked_at = if revoked == "-" {
                None
            } else {
                Some(
                    revoked
                        .parse()
                        .map_err(|_| ArtifactOwnerHostError::InvalidTrust)?,
                )
            };
            signers.push(TrustedArtifactSignerV1 {
                signer_id,
                verifying_key: *key.as_array(),
                minimum_authority_epoch,
                maximum_authority_epoch,
                valid_from,
                expires_at,
                revoked_at,
            });
        }
        sets.push(signers);
    }
    if fields.next().is_some() {
        return Err(ArtifactOwnerHostError::InvalidTrust);
    }
    let mut sets = sets.into_iter();
    let trust = ArtifactOwnerTrustV1 {
        registry_id,
        withdrawal_scope_digest,
        minimum_registry_generation,
        genesis_predecessor_head_digest,
        minimum_authority_epoch,
        writer_signers: sets.next().ok_or(ArtifactOwnerHostError::InvalidTrust)?,
        head_signers: sets.next().ok_or(ArtifactOwnerHostError::InvalidTrust)?,
    };
    if encode_artifact_public_trust_v1(&trust)? != bytes {
        return Err(ArtifactOwnerHostError::InvalidTrust);
    }
    Ok(trust)
}

/// Independently pinned original public material. Root path protection and the
/// original signed CURRENT/trust/withdrawal checks must all hold at construction.
pub struct ArtifactReadOnlyOwnerSourcesV1 {
    pub root: PathBuf,
    pub trust_path: PathBuf,
    pub trust_digest: Digest32,
    pub withdrawal_path: PathBuf,
    pub withdrawal_receipt: crate::DatasetWithdrawalSnapshotReceiptV1,
}
fn protected_file(path: &Path) -> Result<File, ArtifactOwnerHostError> {
    root_read_frontier::protected_root(path.parent().ok_or(ArtifactOwnerHostError::PathBoundary)?)?;
    let before = fs::symlink_metadata(path)?;
    if !before.is_file() || before.uid() != 0 || before.nlink() != 1 || before.mode() & 0o022 != 0 {
        return Err(ArtifactOwnerHostError::PathBoundary);
    }
    let file = File::open(path)?;
    let after = file.metadata()?;
    if before.dev() != after.dev()
        || before.ino() != after.ino()
        || before.len() != after.len()
        || after.uid() != 0
        || after.nlink() != 1
        || after.mode() & 0o022 != 0
    {
        return Err(ArtifactOwnerHostError::PathBoundary);
    }
    Ok(file)
}
fn trust_bytes(
    sources: &ArtifactReadOnlyOwnerSourcesV1,
) -> Result<Vec<u8>, ArtifactOwnerHostError> {
    let file = protected_file(&sources.trust_path)?;
    if sources.trust_digest.is_zero()
        || file.metadata()?.len() > MAX_ARTIFACT_PUBLIC_TRUST_BYTES_V1 as u64
    {
        return Err(ArtifactOwnerHostError::InvalidTrust);
    }
    let mut bytes = Vec::new();
    file.take(MAX_ARTIFACT_PUBLIC_TRUST_BYTES_V1 as u64 + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() > MAX_ARTIFACT_PUBLIC_TRUST_BYTES_V1
        || Digest32::of_bytes(&bytes) != sources.trust_digest
    {
        return Err(ArtifactOwnerHostError::InvalidTrust);
    }
    Ok(bytes)
}
impl ReadOnlyArtifactCurrentOwnerV1 {
    pub fn from_protected_sources(
        sources: &ArtifactReadOnlyOwnerSourcesV1,
        now: u64,
    ) -> Result<Self, ArtifactOwnerHostError> {
        let bytes = trust_bytes(sources)?;
        let trust = decode_artifact_public_trust_v1(&bytes)?;
        let withdrawals = crate::read_dataset_withdrawal_snapshot(
            protected_file(&sources.withdrawal_path)?,
            sources.withdrawal_receipt,
        )?;
        let owner = Self::open(&sources.root, trust, withdrawals, now)?;
        if trust_bytes(sources)? != bytes {
            return Err(ArtifactOwnerHostError::InvalidTrust);
        }
        owner.current_registry_view(now)?;
        Ok(owner)
    }
}
#[cfg(test)]
#[path = "owner_public_trust_tests.rs"]
mod tests;
