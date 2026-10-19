//! Opt-in PoN material admission. The path is transport, while the original
//! FinalUse and dispatch ledger continue to bind the actual immutable bytes.
use super::*;
use std::borrow::Cow;
use std::path::Component;

#[derive(Clone, Copy)]
pub(crate) enum AgentdEffectMaterial<'a> {
    Inline(&'a [u8]),
    PonPacketFile(&'a crate::AutomationPonPacketFile),
}

#[derive(Clone, Copy)]
pub(super) enum EffectMaterialProfile {
    Inline,
    PonPacket,
}

#[derive(Clone, Debug)]
pub(super) struct PonPacketRoot {
    path: PathBuf,
    identity: fs::Metadata,
}

impl PonPacketRoot {
    pub(super) fn open(path: &Path, agent: &AgentdIdentity) -> Result<Self, AgentdError> {
        if !path.is_absolute()
            || path.canonicalize()? != path
            || [&agent.home_root, &agent.run_root, &agent.workspace]
                .iter()
                .any(|owned| path.starts_with(owned) || owned.starts_with(path))
        {
            return Err(invalid("PoN packet root overlaps an Agent-owned namespace or is not canonical"));
        }
        let root = Self {
            path: path.to_path_buf(),
            identity: fs::symlink_metadata(path)?,
        };
        root.verify_identity()?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            if root.identity.uid() != fs::metadata(&agent.home_root)?.uid() {
                return Err(invalid("PoN packet root must belong to the host owner"));
            }
        }
        Ok(root)
    }

    fn verify_identity(&self) -> Result<(), AgentdError> {
        let observed = fs::symlink_metadata(&self.path)?;
        if !observed.is_dir()
            || observed.file_type().is_symlink()
            || self.path.canonicalize()? != self.path
        {
            return Err(invalid("PoN packet root is no longer the configured directory"));
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            if (observed.dev(), observed.ino(), observed.uid())
                != (self.identity.dev(), self.identity.ino(), self.identity.uid())
                || observed.mode() & 0o022 != 0
            {
                return Err(invalid("PoN packet root identity or host permissions changed"));
            }
        }
        Ok(())
    }
}

impl<'a> AgentdEffectMaterial<'a> {
    pub(super) fn profile(self) -> EffectMaterialProfile {
        match self {
            Self::Inline(_) => EffectMaterialProfile::Inline,
            Self::PonPacketFile(_) => EffectMaterialProfile::PonPacket,
        }
    }

    pub(super) fn validate_request(
        self,
        host: &AgentdAutomationEffectHost,
        intent: &AuthorizedEffectIntent,
    ) -> Result<(), AgentdError> {
        match self {
            Self::Inline(bytes) => host.validate_intent(intent, bytes, self.profile()),
            Self::PonPacketFile(packet) => {
                host.validate_subject(intent)?;
                if !host.pon_packet_files_enabled() {
                    return Err(invalid("PoN packet file transport is disabled"));
                }
                let root = host.pon_packet_root.as_ref().ok_or_else(|| invalid("PoN packet file transport is disabled"))?;
                if !packet.path.is_absolute()
                    || !packet.path.starts_with(&root.path)
                    || packet.path == root.path
                    || packet.path.components().any(|part| matches!(part, Component::ParentDir | Component::CurDir))
                    || packet.byte_length == 0
                    || packet.byte_length > codex_hepta_automation::MAX_EFFECT_DISPATCH_WIRE_BYTES as u64
                    || packet.payload_sha256 != intent.payload_digest
                {
                    return Err(invalid("PoN packet reference is outside its root, length or exact payload binding"));
                }
                Ok(())
            }
        }
    }

    pub(super) fn validate_durable(
        self,
        host: &AgentdAutomationEffectHost,
        intent: &AuthorizedEffectIntent,
        bytes: &[u8],
    ) -> Result<(), AgentdError> {
        host.validate_intent(intent, bytes, self.profile())?;
        let same = match self {
            Self::Inline(input) => input == bytes,
            Self::PonPacketFile(packet) => packet.byte_length == bytes.len() as u64,
        };
        if !same {
            return Err(invalid("durable effect material differs from the original input"));
        }
        Ok(())
    }

    pub(super) fn read_initial(self, host: &AgentdAutomationEffectHost) -> Result<Cow<'a, [u8]>, AgentdError> {
        match self {
            Self::Inline(bytes) => Ok(Cow::Borrowed(bytes)),
            Self::PonPacketFile(packet) => {
                let root = host.pon_packet_root.as_ref().ok_or_else(|| invalid("PoN packet file transport is disabled"))?;
                root.verify_identity()?;
                let bytes = crate::cognitive_materials_io::read_material(
                    &packet.path,
                    codex_hepta_automation::MAX_EFFECT_DISPATCH_WIRE_BYTES as u64,
                ).map_err(|error| invalid(&format!("PoN packet material: {error:#}")))?;
                root.verify_identity()?;
                if bytes.len() as u64 != packet.byte_length
                    || Sha256Digest::for_bytes(&bytes) != packet.payload_sha256
                {
                    return Err(invalid("PoN packet length or digest changed before dispatch"));
                }
                Ok(Cow::Owned(bytes))
            }
        }
    }
}

fn invalid(message: &str) -> AgentdError {
    AgentdError::Invalid(message.to_owned())
}
