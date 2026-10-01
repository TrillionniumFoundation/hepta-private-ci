//! Original Root issuance and completion survive an artifact-store rollback.
//! These are fixed-purpose public records under a separate protected Root path.
use super::*;
use ed25519_dalek::Signature;
use serde::Serialize;
use std::fs::File;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalTimeSignature {
    profile_digest: String,
    evidence_digest: String,
    pub(super) issued_at: u64,
    pub(super) expires_at: u64,
    pub(super) signature_hex: String,
}
impl OriginalTimeSignature {
    pub(super) fn new(
        inputs: &Inputs,
        issued_at: u64,
        expires_at: u64,
        signature: [u8; 64],
    ) -> Self {
        Self {
            profile_digest: inputs.profile_source.digest.clone(),
            evidence_digest: inputs.evidence.authentication_digest().to_string(),
            issued_at,
            expires_at,
            signature_hex: hex(&signature),
        }
    }
    pub(super) fn validate(&self, inputs: &Inputs) -> HostResult<()> {
        if self.profile_digest != inputs.profile_source.digest
            || self.evidence_digest != inputs.evidence.authentication_digest().to_string()
            || self.issued_at < inputs.profile.frozen_at_ms
            || self.issued_at > now_ms()?
            || self.issued_at > self.expires_at
            || self.expires_at
                != inputs
                    .evidence
                    .expires_at()
                    .min(inputs.profile.expires_at_ms)
        {
            return Err("original Root issuance context changed".into());
        }
        Ok(())
    }
    pub(super) fn signature(&self) -> HostResult<[u8; 64]> {
        Ok(decode_review_payload_hex(&self.signature_hex)?
            .try_into()
            .map_err(|_| "signature width")?)
    }
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalHead {
    pub(super) time: OriginalTimeSignature,
    pub(super) generation: u64,
    pub(super) predecessor: String,
    pub(super) head: String,
}
impl OriginalHead {
    pub(super) fn historical(
        &self,
        source: &Source,
        profile: &Profile,
        binding: Digest32,
    ) -> HostResult<SignedCurrentArtifactHeadV1> {
        if self.time.profile_digest != source.digest
            || digest(&self.time.evidence_digest)?.is_zero()
            || self.time.issued_at < profile.frozen_at_ms
            || self.time.issued_at > now_ms()?
            || self.time.issued_at > self.time.expires_at
            || self.time.expires_at > profile.expires_at_ms
        {
            return Err("original retained Root head context changed".into());
        }
        self.signed(profile, binding)
    }
    pub(super) fn native(
        &self,
        inputs: &Inputs,
        binding: Digest32,
    ) -> HostResult<SignedCurrentArtifactHeadV1> {
        self.time.validate(inputs)?;
        self.signed(&inputs.profile, binding)
    }
    fn signed(
        &self,
        profile: &Profile,
        binding: Digest32,
    ) -> HostResult<SignedCurrentArtifactHeadV1> {
        let signed = SignedCurrentArtifactHeadV1 {
            withdrawal_scope_digest: profile.withdrawals()?.scope_digest().ok_or("scope")?,
            binding,
            witness: RegistryHeadWitnessV1 {
                registry_id: id(&profile.registry_id)?,
                generation: Generation::new(self.generation)?,
                head_digest: digest(&self.head)?,
                predecessor_head_digest: self.predecessor.parse()?,
                authority_epoch: 1,
                signer_id: id(&profile.owner.id)?,
                signing_key_digest: Digest32::of_bytes(&public(&profile.owner.public_key_hex)?),
                issued_at: self.time.issued_at,
                expires_at: self.time.expires_at,
            },
            signature: self.time.signature()?,
        };
        ed25519_dalek::VerifyingKey::from_bytes(&public(&profile.owner.public_key_hex)?)?
            .verify_strict(
                &signed.signing_bytes(),
                &Signature::from_bytes(&signed.signature),
            )?;
        Ok(signed)
    }
}
pub(super) fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}
pub(super) fn directory(inputs: &Inputs) -> HostResult<()> {
    directory_for_profile(&inputs.profile)
}
pub(super) fn directory_for_profile(profile: &Profile) -> HostResult<()> {
    let directory = &profile.original_owner_state;
    for ancestor in directory.ancestors() {
        let meta = std::fs::symlink_metadata(ancestor)?;
        if !meta.is_dir() || meta.uid() != 0 || meta.mode() & 0o022 != 0 {
            return Err("original Root state boundary".into());
        }
    }
    if std::fs::symlink_metadata(directory)?.mode() & 0o077 != 0 {
        return Err("original Root state must be private".into());
    }
    for (index, entry) in std::fs::read_dir(directory)?.enumerate() {
        if index >= 7 {
            return Err("initial Root state capacity".into());
        }
        let entry = entry?;
        let name = entry.file_name();
        let name = name.to_str().ok_or("Root state filename")?;
        if ![
            "lease.json",
            "head-0.json",
            "head-1.json",
            "head-2.json",
            "done-0",
            "done-1",
            "done-2",
        ]
        .contains(&name)
        {
            return Err("unknown original Root state retained".into());
        }
        let meta = entry.metadata()?;
        if !meta.is_file()
            || meta.uid() != 0
            || meta.mode() & 0o077 != 0
            || meta.nlink() != 1
            || meta.len() > 16 * 1024
            || entry.path().canonicalize()? != entry.path()
        {
            return Err("original Root state file boundary".into());
        }
    }
    Ok(())
}
pub(super) fn read<T: serde::de::DeserializeOwned>(
    inputs: &Inputs,
    name: &str,
) -> HostResult<Option<T>> {
    directory(inputs)?;
    let path = inputs.profile.original_owner_state.join(name);
    match std::fs::symlink_metadata(&path) {
        Ok(_) => Ok(Some(serde_json::from_slice(&read_root_review_input(
            &path,
            16 * 1024,
        )?)?)),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(error.into()),
    }
}
pub(super) fn retain<T: Serialize>(inputs: &Inputs, name: &str, value: &T) -> HostResult<()> {
    directory(inputs)?;
    let path = inputs.profile.original_owner_state.join(name);
    let bytes = serde_json::to_vec(value)?;
    if bytes.is_empty() || bytes.len() > 16 * 1024 {
        return Err("Root original record capacity".into());
    }
    if path.try_exists()? {
        if read_root_review_input(&path, 16 * 1024)? != bytes {
            return Err("original Root record conflict".into());
        }
        return Ok(());
    }
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&path)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    File::open(&inputs.profile.original_owner_state)?.sync_all()?;
    Ok(())
}
