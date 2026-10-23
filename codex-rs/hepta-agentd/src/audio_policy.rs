//! Read-only owner policy for signed captured-media observations. This does not
//! grant OS capture access, enroll keys, open devices or generate credentials.
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdState;
use crate::audio_observation::AudioObservationBodyV1;
use crate::audio_observation::invalid;
use crate::authbus_trust::read_private_owner_file;
use codex_hepta_codex_adapter::hmi::HmiBindingV1;
use codex_hepta_codex_adapter::hmi::HmiCaptureStreamV1;
use codex_hepta_codex_adapter::hmi::HmiCapturedAudioRefV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use std::path::PathBuf;
use tokio::io::AsyncReadExt;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct AudioPolicy {
    schema_version: u32,
    agent_id: String,
    issuer_id: String,
    key_epoch: u64,
    pub(crate) device_id: String,
    pub(crate) device_generation: u64,
    pub(crate) organ_id: String,
    pub(crate) organ_generation: u64,
    pub(crate) capture_generation: u64,
    media_root: PathBuf,
    max_segment_bytes: u64,
    expires_at_ms: u64,
    pub(crate) revoked: bool,
    #[serde(skip)]
    pub(crate) digest: String,
}
impl AudioPolicy {
    pub(crate) fn load(
        path: &std::path::Path,
        identity: &AgentdIdentity,
    ) -> Result<Self, AgentdError> {
        let bytes = read_private_owner_file(path, identity, 16_384)?;
        let mut policy: Self = serde_json::from_slice(&bytes)?;
        if policy.schema_version != 1
            || policy.agent_id != identity.agent_id.as_str()
            || policy.key_epoch == 0
            || policy.device_generation == 0
            || policy.organ_generation == 0
            || policy.capture_generation == 0
            || policy.max_segment_bytes == 0
            || policy.max_segment_bytes > 1_048_576
        {
            return Err(invalid("invalid owner device-authority profile"));
        }
        for id in [&policy.issuer_id, &policy.device_id, &policy.organ_id] {
            StableId::new(id).map_err(invalid)?;
        }
        policy.digest = Digest32::of_bytes(&bytes).to_string();
        policy.private_root(identity)?;
        Ok(policy)
    }
    pub(crate) fn current(state: &AgentdState) -> Result<Self, AgentdError> {
        let host = crate::authbus_ingress::attached(state)?;
        let path = host
            .audio_authority_file
            .as_ref()
            .ok_or_else(|| invalid("no explicit audio device-authority profile"))?;
        Self::load(path, state.identity())
    }
    pub(crate) fn stream(&self, thread: &str) -> HmiCaptureStreamV1 {
        HmiCaptureStreamV1 {
            principal_id: self.issuer_id.clone(),
            device_id: self.device_id.clone(),
            device_generation: self.device_generation,
            organ_id: self.organ_id.clone(),
            organ_generation: self.organ_generation,
            logical_session_id: format!("thread:{thread}"),
        }
    }
    pub(crate) fn permits(
        &self,
        issuer: &str,
        epoch: u64,
        body: &AudioObservationBodyV1,
    ) -> Result<(), AgentdError> {
        if self.revoked
            || self.expires_at_ms <= crate::authbus_ingress::now_ms()?
            || issuer != self.issuer_id
            || epoch != self.key_epoch
            || body.authority_sha256 != self.digest
            || body.source.stream != self.stream(&body.thread_id)
            || body.source.capture_generation != self.capture_generation
            || body.source.byte_length > self.max_segment_bytes
        {
            return Err(invalid(
                "current device/capture authority changed or does not permit this observation",
            ));
        }
        Ok(())
    }
    pub(crate) fn permits_binding(
        &self,
        binding: &HmiBindingV1,
        digest: &str,
    ) -> Result<(), AgentdError> {
        let stream = self.stream(&binding.thread_id);
        if self.revoked
            || self.expires_at_ms <= crate::authbus_ingress::now_ms()?
            || digest != self.digest
            || binding.principal_id != stream.principal_id
            || binding.device_id != stream.device_id
            || binding.device_generation != stream.device_generation
            || binding.organ_id != stream.organ_id
            || binding.organ_generation != stream.organ_generation
            || binding.logical_session_id != stream.logical_session_id
        {
            return Err(invalid("current device/capture authority changed"));
        }
        Ok(())
    }
    #[cfg(unix)]
    fn private_root(&self, identity: &AgentdIdentity) -> Result<(), AgentdError> {
        use std::os::unix::fs::MetadataExt;
        let metadata = std::fs::symlink_metadata(&self.media_root)?;
        if self.media_root.parent() != Some(identity.home_root.as_path())
            || self.media_root.canonicalize()? != self.media_root
            || !metadata.is_dir()
            || metadata.uid() != std::fs::metadata(&identity.home_root)?.uid()
            || metadata.mode() & 0o077 != 0
        {
            return Err(invalid(
                "media root must be an existing private direct child of the canonical owner home",
            ));
        }
        Ok(())
    }
    #[cfg(not(unix))]
    fn private_root(&self, _: &AgentdIdentity) -> Result<(), AgentdError> {
        Err(invalid("audio profile requires Unix owner checks"))
    }

    #[cfg(unix)]
    pub(crate) async fn verify_media(
        &self,
        identity: &AgentdIdentity,
        source: &HmiCapturedAudioRefV1,
    ) -> Result<(), AgentdError> {
        use std::os::unix::fs::MetadataExt;
        self.private_root(identity)?;
        if source.byte_length > self.max_segment_bytes
            || source.asset_id
                != format!(
                    "capture-{}-{}.pcm16",
                    source.capture_generation, source.sequence
                )
        {
            return Err(invalid(
                "media reference exceeds policy or escapes its capture",
            ));
        }
        let path = self.media_root.join(&source.asset_id);
        let before = tokio::fs::symlink_metadata(&path).await?;
        let owner_uid = std::fs::metadata(&identity.home_root)?.uid();
        if !before.is_file()
            || before.nlink() != 1
            || before.uid() != owner_uid
            || before.mode() & 0o077 != 0
            || before.len() != source.byte_length
        {
            return Err(invalid(
                "media must be an exact private owner-controlled regular file",
            ));
        }
        let file = tokio::fs::File::open(&path).await?;
        let same = |m: &std::fs::Metadata| {
            (
                m.dev(),
                m.ino(),
                m.len(),
                m.mtime(),
                m.mtime_nsec(),
                m.ctime(),
                m.ctime_nsec(),
            )
        };
        if same(&file.metadata().await?) != same(&before) {
            return Err(invalid("media changed while opening"));
        }
        let mut bounded = file.take(source.byte_length + 1);
        let mut bytes = Vec::new();
        bounded.read_to_end(&mut bytes).await?;
        let after = tokio::fs::symlink_metadata(&path).await?;
        if same(&after) != same(&before)
            || same(&bounded.get_ref().metadata().await?) != same(&before)
            || bytes.len() as u64 != source.byte_length
            || Digest32::of_bytes(&bytes).to_string() != source.sha256
        {
            return Err(invalid("media byte digest, length or inode changed"));
        }
        Ok(())
    }
    #[cfg(not(unix))]
    pub(crate) async fn verify_media(
        &self,
        _: &AgentdIdentity,
        _: &HmiCapturedAudioRefV1,
    ) -> Result<(), AgentdError> {
        Err(invalid("audio profile requires Unix owner checks"))
    }
}
