//! Canonical description of actual reserved objects, never a capability.

use std::os::fd::AsRawFd;
use std::os::unix::fs::MetadataExt;

use codex_hepta_memory::CognitiveCheckpointPeerLifetime;

use super::*;
use crate::AgentdIdentity;
use crate::HostAuthorityRegisteredIdentity;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct FilePin {
    device: u64,
    inode: u64,
}

impl FilePin {
    pub(crate) fn capture(file: &File) -> io::Result<Self> {
        let metadata = file.metadata()?;
        if !metadata.is_file()
            || metadata.uid() != 0
            || metadata.mode() & 0o777 != 0o600
            || metadata.nlink() != 1
        {
            return Err(io::Error::other(
                "original Root0600 single-link owner file required",
            ));
        }
        Ok(Self {
            device: metadata.dev(),
            inode: metadata.ino(),
        })
    }

    pub(crate) fn require_writable(&self, file: &File) -> io::Result<()> {
        // SAFETY: F_GETFL only observes flags of this retained File descriptor.
        let flags = unsafe { libc::fcntl(file.as_raw_fd(), libc::F_GETFL) };
        if Self::capture(file)? != *self
            || flags < 0
            || flags & libc::O_ACCMODE != libc::O_RDWR
            || flags & libc::O_APPEND != 0
        {
            return Err(io::Error::other(
                "factory original read/write owner file differs",
            ));
        }
        Ok(())
    }

    fn digest(&self, purpose: &[u8], initial: Digest32) -> Digest32 {
        Digest32::of_parts(&[
            purpose,
            initial.as_array(),
            &self.device.to_be_bytes(),
            &self.inode.to_be_bytes(),
        ])
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
enum Backend {
    Q24SingleHeadSgdV1,
}

/// Public immutable description issued by the original Root reservation.
/// It contains no writable path, private key or public factory constructor.
#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostAuthorityQ24ModelFactoryProfileV1 {
    schema_version: u32,
    purpose: String,
    backend: Backend,
    operation_id: String,
    initial_head: String,
    scope_binding: String,
    proposal_owner_id: String,
    process_identity_digest: String,
    writer_proof_digest: String,
    journal_slot_binding: String,
    witness_enrollment_binding: String,
    local_policy_digest: String,
    registry_epoch: u64,
    expiry_unix_seconds: u64,
    factory_binding: String,
    journal: FilePin,
    witness: FilePin,
    witness_domain: String,
}

impl HostAuthorityQ24ModelFactoryProfileV1 {
    pub(super) fn new(
        identity: &AgentdIdentity,
        writer_proof: &str,
        initial: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
        journal: FilePin,
        witness: FilePin,
        witness_domain: Digest32,
        local_policy: Digest32,
    ) -> io::Result<Self> {
        scope.validate_snapshot(initial).map_err(io::Error::other)?;
        if journal == witness || witness_domain.is_zero() || local_policy.is_zero() {
            return Err(io::Error::other(
                "distinct original proposal and witness custody required",
            ));
        }
        let mut profile = Self {
            schema_version: 1,
            purpose: PURPOSE.into(),
            backend: Backend::Q24SingleHeadSgdV1,
            operation_id: initial.request.operation_id.to_string(),
            initial_head: initial.head_digest.to_string(),
            scope_binding: scope.binding().to_string(),
            proposal_owner_id: initial.owners.proposal.to_string(),
            process_identity_digest: crate::neuron_generation_process_identity_digest_v1(identity)
                .map_err(io::Error::other)?
                .to_string(),
            writer_proof_digest: writer_proof.into(),
            journal_slot_binding: journal
                .digest(b"hepta.root.q24-proposal-slot.v1\0", initial.head_digest)
                .to_string(),
            witness_enrollment_binding: Digest32::of_parts(&[
                b"hepta.root.q24-proposal-witness.v1\0",
                witness.digest(b"file\0", initial.head_digest).as_array(),
                witness_domain.as_array(),
            ])
            .to_string(),
            local_policy_digest: local_policy.to_string(),
            registry_epoch: 1,
            expiry_unix_seconds: initial.request.envelope.expiry_unix_seconds,
            factory_binding: String::new(),
            journal,
            witness,
            witness_domain: witness_domain.to_string(),
        };
        profile.factory_binding = profile.canonical_binding()?.to_string();
        Ok(profile)
    }

    fn canonical_binding(&self) -> io::Result<Digest32> {
        // Canonical typed encodings, not arbitrary JSON or caller formatting.
        let digest = |text: &str| -> io::Result<Digest32> {
            let value = text.parse::<Digest32>().map_err(io::Error::other)?;
            if value.is_zero() || value.to_string() != text {
                return Err(io::Error::other("noncanonical factory digest"));
            }
            Ok(value)
        };
        let mut bytes = Vec::new();
        bytes.extend_from_slice(&self.schema_version.to_be_bytes());
        for text in [&self.purpose, &self.operation_id, &self.proposal_owner_id] {
            bytes.extend_from_slice(&(text.len() as u64).to_be_bytes());
            bytes.extend_from_slice(text.as_bytes());
        }
        match self.backend {
            Backend::Q24SingleHeadSgdV1 => bytes.push(1),
        }
        for value in [
            &self.initial_head,
            &self.scope_binding,
            &self.process_identity_digest,
            &self.writer_proof_digest,
            &self.journal_slot_binding,
            &self.witness_enrollment_binding,
            &self.local_policy_digest,
        ] {
            bytes.extend_from_slice(digest(value)?.as_array());
        }
        bytes.extend_from_slice(&self.registry_epoch.to_be_bytes());
        bytes.extend_from_slice(&self.expiry_unix_seconds.to_be_bytes());
        Ok(Digest32::of_parts(&[
            b"hepta.root.learning.q24-model-proposal.factory.v1\0",
            &bytes,
        ]))
    }

    pub(crate) fn require_context(
        &self,
        identity: &AgentdIdentity,
        proof: &str,
        initial: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
    ) -> io::Result<()> {
        let domain = self
            .witness_domain
            .parse::<Digest32>()
            .map_err(io::Error::other)?;
        let policy = self
            .local_policy_digest
            .parse::<Digest32>()
            .map_err(io::Error::other)?;
        let expected = Self::new(
            identity,
            proof,
            initial,
            scope,
            self.journal,
            self.witness,
            domain,
            policy,
        )?;
        if self != &expected {
            return Err(io::Error::other(
                "factory differs from original Root learning scope",
            ));
        }
        Ok(())
    }

    pub(crate) fn require_files(&self, journal: &File, witness: &File) -> io::Result<()> {
        self.journal.require_writable(journal)?;
        self.witness.require_writable(witness)?;
        if witness.metadata()?.len() == 0 {
            return Err(io::Error::other(
                "original enrolled witness is missing; never initialize on reopen",
            ));
        }
        Ok(())
    }

    pub(crate) fn require_observers(&self, journal: &File, witness: &File) -> io::Result<()> {
        if FilePin::capture(journal)? != self.journal || FilePin::capture(witness)? != self.witness
        {
            return Err(io::Error::other("registered factory file identity changed"));
        }
        Ok(())
    }

    pub(crate) fn binding(&self) -> &str {
        &self.factory_binding
    }
    pub(crate) fn expiry(&self) -> u64 {
        self.expiry_unix_seconds
    }
    pub(crate) fn require_local_policy(&self, policy: Digest32) -> io::Result<()> {
        if policy.is_zero() || self.local_policy_digest != policy.to_string() {
            return Err(io::Error::other(
                "local policy differs from original Root factory enrollment",
            ));
        }
        Ok(())
    }
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Q24ModelFactoryBootstrap {
    pub(crate) profile: HostAuthorityQ24ModelFactoryProfileV1,
    pub(crate) root: CognitiveCheckpointPeerLifetime,
    pub(crate) consumer: CognitiveCheckpointPeerLifetime,
    pub(crate) identity: HostAuthorityRegisteredIdentity,
    pub(crate) socket_path: PathBuf,
}

#[cfg(test)]
#[path = "authority_host_q24_model_profile_tests.rs"]
pub(super) mod tests;
