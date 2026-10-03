//! Bounded issuance records in the original Root Owner's retained state.
//! These are not a second publication journal: only the original service's
//! acknowledged head files can advance its required restart floor.
use super::*;
use ed25519_dalek::Signature;
use ed25519_dalek::Signer;
use std::fs::File;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Head {
    schema: String,
    profile_digest: String,
    configuration_digest: String,
    round_digest: String,
    evaluation_digest: String,
    operation_id: String,
    signed_head_hex: String,
}
fn directory(profile: &Profile) -> std::path::PathBuf {
    profile.original_owner_state.join("parameter-heads")
}
fn name(operation: &StableId) -> String {
    Digest32::of_parts(&[
        b"hepta.original-root-state.parameter-head.v1",
        operation.as_str().as_bytes(),
    ])
    .to_string()
}
fn valid_name(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}
pub(super) fn validate_directory(profile: &Profile) -> HostResult<()> {
    let path = directory(profile);
    let meta = std::fs::symlink_metadata(&path)?;
    if !meta.is_dir() || meta.uid() != 0 || meta.mode() & 0o077 != 0 || path.canonicalize()? != path
    {
        return Err("original finite E1 issuance directory boundary".into());
    }
    for (index, entry) in std::fs::read_dir(&path)?.enumerate() {
        if index >= MAX_DURABLE_ARTIFACT_RECORDS {
            return Err("original finite E1 issuance capacity".into());
        }
        let entry = entry?;
        let file_name = entry.file_name();
        let file_name = file_name
            .to_str()
            .ok_or("original finite issuance filename")?;
        if !valid_name(file_name) && !file_name.strip_prefix(".pending-").is_some_and(valid_name) {
            return Err("unknown original finite E1 issuance file".into());
        }
        let meta = std::fs::symlink_metadata(entry.path())?;
        if !meta.is_file()
            || meta.uid() != 0
            || meta.mode() & 0o077 != 0
            || meta.nlink() != 1
            || meta.len() > 16 * 1024
            || entry.path().canonicalize()? != entry.path()
        {
            return Err("original finite E1 issuance file boundary".into());
        }
    }
    Ok(())
}
fn prepare(inputs: &super::super::Inputs) -> HostResult<()> {
    super::super::state::directory(inputs)?;
    let path = directory(&inputs.profile);
    match std::fs::DirBuilder::new().mode(0o700).create(&path) {
        Ok(()) => File::open(&inputs.profile.original_owner_state)?.sync_all()?,
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => (),
        Err(error) => return Err(error.into()),
    }
    validate_directory(&inputs.profile)
}
pub(super) fn has_source(inputs: &super::super::Inputs, source: &Source) -> HostResult<bool> {
    let path = directory(&inputs.profile);
    if !path.try_exists()? {
        return Ok(false);
    }
    validate_directory(&inputs.profile)?;
    for entry in std::fs::read_dir(path)? {
        let entry = entry?;
        if entry.file_name().to_str().is_some_and(valid_name) {
            let head: Head =
                serde_json::from_slice(&read_root_review_input(&entry.path(), 16 * 1024)?)?;
            if head.configuration_digest == source.digest {
                return Ok(true);
            }
        }
    }
    Ok(false)
}
pub(super) fn read(
    inputs: &super::super::Inputs,
    operation: &StableId,
) -> HostResult<Option<Head>> {
    let directory = directory(&inputs.profile);
    if !directory.try_exists()? {
        return Ok(None);
    }
    validate_directory(&inputs.profile)?;
    let path = directory.join(name(operation));
    if !path.try_exists()? {
        return Ok(None);
    }
    Ok(Some(serde_json::from_slice(&read_root_review_input(
        &path,
        16 * 1024,
    )?)?))
}
impl Head {
    fn signed(
        &self,
        inputs: &super::super::Inputs,
        binding: Digest32,
    ) -> HostResult<SignedCurrentArtifactHeadV1> {
        if self.schema != "hepta.original-root-state.parameter-e1-head.v1"
            || self.profile_digest != inputs.profile_source.digest
        {
            return Err("original finite E1 Owner profile changed".into());
        }
        for pin in [
            &self.configuration_digest,
            &self.round_digest,
            &self.evaluation_digest,
        ] {
            digest(pin)?;
        }
        let signed = decode_untrusted_signed_artifact_head_v1(&decode_review_payload_hex(
            &self.signed_head_hex,
        )?)?;
        if signed.binding != binding
            || signed.withdrawal_scope_digest
                != inputs
                    .profile
                    .withdrawals()?
                    .scope_digest()
                    .ok_or("scope")?
            || signed.witness.registry_id.as_str() != inputs.profile.registry_id
            || signed.witness.signer_id.as_str() != inputs.profile.owner.id
            || signed.witness.authority_epoch != 1
            || signed.witness.signing_key_digest
                != Digest32::of_bytes(&public(&inputs.profile.owner.public_key_hex)?)
            || signed.witness.issued_at < inputs.profile.frozen_at_ms
            || signed.witness.issued_at > now_ms()?
            || signed.witness.issued_at >= signed.witness.expires_at
            || signed.witness.expires_at > inputs.profile.expires_at_ms
        {
            return Err("original finite E1 signed Owner head context".into());
        }
        ed25519_dalek::VerifyingKey::from_bytes(&public(&inputs.profile.owner.public_key_hex)?)?
            .verify_strict(
                &signed.signing_bytes(),
                &Signature::from_bytes(&signed.signature),
            )?;
        Ok(signed)
    }
    pub(super) fn verify(
        &self,
        inputs: &super::super::Inputs,
        source: &Source,
        evaluation: &VerifiedParameterPreRegistrationEvaluationV1,
        operation: &StableId,
        binding: Digest32,
    ) -> HostResult<SignedCurrentArtifactHeadV1> {
        if self.configuration_digest != source.digest
            || self.operation_id != operation.as_str()
            || self.round_digest != evaluation.round().round_digest
            || self.evaluation_digest != evaluation.authentication_digest().to_string()
        {
            return Err("original finite E1 issuance/request/round changed".into());
        }
        let signed = self.signed(inputs, binding)?;
        if signed.witness.expires_at != evaluation.expires_at().min(inputs.profile.expires_at_ms) {
            return Err("original finite E1 issuance expiry changed".into());
        }
        Ok(signed)
    }
}
pub(super) fn sign(
    inputs: &super::super::Inputs,
    source: &Source,
    evaluation: &VerifiedParameterPreRegistrationEvaluationV1,
    operation: &StableId,
    preview: &ArtifactPublicationHeadPreviewV1,
    binding: Digest32,
    key: &SigningKey,
) -> HostResult<(Head, SignedCurrentArtifactHeadV1)> {
    let mut signed = SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: inputs
            .profile
            .withdrawals()?
            .scope_digest()
            .ok_or("scope")?,
        binding,
        witness: RegistryHeadWitnessV1 {
            registry_id: id(&inputs.profile.registry_id)?,
            generation: preview.generation,
            head_digest: preview.head_digest,
            predecessor_head_digest: preview.predecessor,
            authority_epoch: 1,
            signer_id: id(&inputs.profile.owner.id)?,
            signing_key_digest: Digest32::of_bytes(key.verifying_key().as_bytes()),
            issued_at: now_ms()?,
            expires_at: evaluation.expires_at().min(inputs.profile.expires_at_ms),
        },
        signature: [0; 64],
    };
    if signed.witness.issued_at >= signed.witness.expires_at {
        return Err("actual E1 expired before Owner signing".into());
    }
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    let record = Head {
        schema: "hepta.original-root-state.parameter-e1-head.v1".into(),
        profile_digest: inputs.profile_source.digest.clone(),
        configuration_digest: source.digest.clone(),
        round_digest: evaluation.round().round_digest.clone(),
        evaluation_digest: evaluation.authentication_digest().to_string(),
        operation_id: operation.to_string(),
        signed_head_hex: super::super::state::hex(&encode_untrusted_signed_artifact_head_v1(
            &signed,
        )),
    };
    record.verify(inputs, source, evaluation, operation, binding)?;
    Ok((record, signed))
}
pub(super) fn retain(
    inputs: &super::super::Inputs,
    operation: &StableId,
    head: &Head,
) -> HostResult<()> {
    prepare(inputs)?;
    let directory = directory(&inputs.profile);
    let path = directory.join(name(operation));
    let bytes = serde_json::to_vec(head)?;
    if bytes.len() > 16 * 1024 {
        return Err("original bounded E1 head record".into());
    }
    if !path.try_exists()? {
        let mut random = [0u8; 32];
        File::open("/dev/urandom")?.read_exact(&mut random)?;
        let temporary = directory.join(format!(".pending-{}", Digest32::of_bytes(&random)));
        let mut file = File::options()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW)
            .open(&temporary)?;
        file.write_all(&bytes)?;
        file.sync_all()?;
        match rustix::fs::renameat_with(
            rustix::fs::CWD,
            &temporary,
            rustix::fs::CWD,
            &path,
            rustix::fs::RenameFlags::NOREPLACE,
        ) {
            Ok(()) => (),
            Err(rustix::io::Errno::EXIST) => std::fs::remove_file(temporary)?,
            Err(error) => return Err(std::io::Error::from(error).into()),
        }
        File::open(&directory)?.sync_all()?;
    }
    if read_root_review_input(&path, 16 * 1024)? != bytes {
        return Err("original E1 signed head conflict".into());
    }
    validate_directory(&inputs.profile)
}
pub(super) fn floor(
    inputs: &super::super::Inputs,
    binding: Digest32,
) -> HostResult<Option<SignedCurrentArtifactHeadV1>> {
    let path = directory(&inputs.profile);
    if !path.try_exists()? {
        return Ok(None);
    }
    validate_directory(&inputs.profile)?;
    let mut floor: Option<SignedCurrentArtifactHeadV1> = None;
    for entry in std::fs::read_dir(path)? {
        let entry = entry?;
        if !entry.file_name().to_str().is_some_and(valid_name) {
            continue;
        }
        let record: Head =
            serde_json::from_slice(&read_root_review_input(&entry.path(), 16 * 1024)?)?;
        if name(&id(&record.operation_id)?) != entry.file_name().to_str().ok_or("head filename")? {
            return Err("original E1 head/operation identity changed".into());
        }
        let signed = record.signed(inputs, binding)?;
        let actual = inputs.profile.owner_root.join("heads").join(format!(
            "{}-{}.head",
            signed.witness.generation.get(),
            Digest32::of_bytes(&signed.signing_bytes())
        ));
        if actual.try_exists()? {
            if read_root_review_input(&actual, 16 * 1024)?
                != encode_untrusted_signed_artifact_head_v1(&signed)
            {
                return Err("actual original E1 published head changed".into());
            }
            if floor
                .as_ref()
                .is_none_or(|old| old.witness.generation < signed.witness.generation)
            {
                floor = Some(signed);
            }
        }
    }
    Ok(floor)
}
