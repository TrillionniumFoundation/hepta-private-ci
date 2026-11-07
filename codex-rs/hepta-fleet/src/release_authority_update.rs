//! Journal mutations use the existing M15 signature domains and one external CAS.

use std::sync::atomic::Ordering;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::ReleaseFrontierV1;
use serde::Deserialize;
use sha2::Digest;
use sha2::Sha256;
use trnm_release_bundle::pq_release::PqReleaseMetadataV1;
use trnm_release_bundle::pq_release::PqReleaseRootV1;
use trnm_release_bundle::pq_release::PqReleaseSignatureV1;

use super::PendingUpdate;
use super::ReleaseAuthority;
use super::invalid;
use crate::FleetRegistryError;
use crate::ReleaseId;
use crate::release_authority_set::SignedReleaseSet;
use crate::release_authority_set::manifest_bytes;
use crate::release_authority_set::record_bytes;
use crate::release_authority_state::Admission;
use crate::release_authority_state::Journal;
use crate::release_authority_state::JournalEntry;
use crate::release_authority_state::LoadedState;
use crate::release_authority_state::MAX_JOURNAL_ENTRIES;
use crate::release_authority_store::MAX_AUTHORITY_BYTES;
use crate::release_authority_store::MAX_SET_BYTES;
use crate::release_authority_wire::AuthorityEventRecord;
use crate::release_authority_wire::RootRecord;
use crate::release_authority_wire::SignatureRecord;

impl ReleaseAuthority {
    pub fn publish_set(&self, input: &[u8]) -> Result<(), FleetRegistryError> {
        if input.len() > MAX_SET_BYTES {
            return Err(invalid("release set exceeds its byte bound"));
        }
        let signed: SignedReleaseSet = serde_json::from_slice(input)
            .map_err(|_| invalid("invalid signed Fleet release-set envelope"))?;
        let binding = signed.release_set.bind(self.config.platform_sha256)?;
        let (_lock, mut state, now) = self.load()?;
        let metadata = PqReleaseMetadataV1::from(&signed.metadata);
        let signatures = signed
            .signatures
            .iter()
            .map(PqReleaseSignatureV1::from)
            .collect::<Vec<_>>();
        state
            .authority
            .accept_bundle(
                &binding.bundle,
                &binding.required_packages,
                &metadata,
                &signatures,
                now,
            )
            .map_err(|error| invalid(format!("M15 release-set authorization rejected: {error}")))?;
        let checkpoint = state.authority.checkpoint();
        let event = JournalEntry::Authority {
            event: AuthorityEventRecord::ReleaseSet {
                metadata: signed.metadata,
                signatures: signed.signatures,
                observed_at: now,
            },
        };
        state.journal.current_set = Some(signed.release_set);
        self.append_and_commit(state, event, checkpoint)
    }

    pub fn rotate_root(&self, input: &[u8]) -> Result<(), FleetRegistryError> {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Rotation {
            root: RootRecord,
            old_signatures: Vec<SignatureRecord>,
            new_signatures: Vec<SignatureRecord>,
        }
        if input.len() > 512 * 1024 {
            return Err(invalid("root rotation exceeds its byte bound"));
        }
        let change: Rotation =
            serde_json::from_slice(input).map_err(|_| invalid("invalid signed root rotation"))?;
        let (_lock, mut state, now) = self.load()?;
        let checkpoint = state
            .authority
            .rotate_root(
                PqReleaseRootV1::try_from(&change.root)?,
                &change
                    .old_signatures
                    .iter()
                    .map(PqReleaseSignatureV1::from)
                    .collect::<Vec<_>>(),
                &change
                    .new_signatures
                    .iter()
                    .map(PqReleaseSignatureV1::from)
                    .collect::<Vec<_>>(),
                now,
            )
            .map_err(|error| invalid(format!("M15 root rotation rejected: {error}")))?;
        self.append_and_commit(
            state,
            JournalEntry::Authority {
                event: AuthorityEventRecord::RootRotation {
                    root: change.root,
                    old_signatures: change.old_signatures,
                    new_signatures: change.new_signatures,
                    observed_at: now,
                },
            },
            checkpoint,
        )
    }

    pub fn allow(
        &self,
        agent_id: &AgentId,
        release_id: &ReleaseId,
        manifest_sha256: [u8; 32],
    ) -> Result<(), FleetRegistryError> {
        let (_lock, state, now) = self.load()?;
        let current = self.current_member(&state, release_id, now)?;
        if manifest_sha256 != <[u8; 32]>::from(Sha256::digest(manifest_bytes(current)?)) {
            return Err(invalid(
                "allowance does not bind the currently published manifest",
            ));
        }
        match state
            .admissions
            .get(&(agent_id.clone(), release_id.clone()))
        {
            Some(Admission::Allowed(digest)) if *digest == manifest_sha256 => return Ok(()),
            Some(Admission::Revoked(_)) => {
                return Err(FleetRegistryError::ReleaseRevoked {
                    agent_id: agent_id.clone(),
                    release_id: release_id.to_string(),
                });
            }
            Some(Admission::Allowed(_)) => {
                return Err(invalid("durable allowance manifest changed"));
            }
            None => {}
        }
        let checkpoint = state.authority.checkpoint();
        self.append_and_commit(
            state,
            JournalEntry::Allow {
                agent_id: agent_id.clone(),
                release_id: release_id.clone(),
                manifest_sha256,
                observed_at: now,
            },
            checkpoint,
        )
    }

    pub fn revoke(
        &self,
        agent_id: &AgentId,
        release_id: &ReleaseId,
    ) -> Result<(), FleetRegistryError> {
        let (_lock, state, now) = self.load()?;
        let manifest_sha256 = match state
            .admissions
            .get(&(agent_id.clone(), release_id.clone()))
        {
            Some(Admission::Allowed(digest)) => *digest,
            Some(Admission::Revoked(_)) => return Ok(()),
            None => {
                return Err(FleetRegistryError::ReleaseNotAllowed {
                    agent_id: agent_id.clone(),
                    release_id: release_id.to_string(),
                });
            }
        };
        let checkpoint = state.authority.checkpoint();
        self.append_and_commit(
            state,
            JournalEntry::Revoke {
                agent_id: agent_id.clone(),
                release_id: release_id.clone(),
                manifest_sha256,
                observed_at: now,
            },
            checkpoint,
        )
    }

    pub fn publish_protocol_configuration(&self, input: &[u8]) -> Result<(), FleetRegistryError> {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct SignedConfiguration {
            metadata: crate::release_authority_wire::MetadataRecord,
            signatures: Vec<SignatureRecord>,
        }
        if input.len() > 512 * 1024 {
            return Err(invalid(
                "protocol configuration authorization exceeds its byte bound",
            ));
        }
        let signed: SignedConfiguration = serde_json::from_slice(input)
            .map_err(|_| invalid("invalid protocol configuration authorization"))?;
        if signed.metadata.role != crate::release_authority_wire::RoleRecord::ProtocolConfiguration
        {
            return Err(invalid(
                "protocol configuration requires its distinct M15 role",
            ));
        }
        let (_lock, mut state, now) = self.load()?;
        state
            .authority
            .accept(
                &PqReleaseMetadataV1::from(&signed.metadata),
                &signed
                    .signatures
                    .iter()
                    .map(PqReleaseSignatureV1::from)
                    .collect::<Vec<_>>(),
                now,
            )
            .map_err(|error| {
                invalid(format!(
                    "M15 protocol configuration authorization rejected: {error}"
                ))
            })?;
        let checkpoint = state.authority.checkpoint();
        self.append_and_commit(
            state,
            JournalEntry::Authority {
                event: AuthorityEventRecord::ProtocolConfiguration {
                    metadata: signed.metadata,
                    signatures: signed.signatures,
                    observed_at: now,
                },
            },
            checkpoint,
        )
    }

    pub(super) fn append_and_commit(
        &self,
        state: LoadedState,
        entry: JournalEntry,
        checkpoint: [u8; 32],
    ) -> Result<(), FleetRegistryError> {
        self.append_and_commit_checked(state, entry, checkpoint, || Ok(()))
    }

    pub(super) fn append_and_commit_checked(
        &self,
        mut state: LoadedState,
        entry: JournalEntry,
        checkpoint: [u8; 32],
        before_cas: impl FnOnce() -> Result<(), FleetRegistryError>,
    ) -> Result<(), FleetRegistryError> {
        if state.journal.entries.len() >= MAX_JOURNAL_ENTRIES {
            return Err(invalid("release security history is full"));
        }
        state.journal.generation = state
            .frontier
            .generation
            .checked_add(1)
            .ok_or_else(|| invalid("release generation overflow"))?;
        state.journal.previous_frontier = Some(state.frontier);
        state.journal.entries.push(entry);
        self.commit_checked(Some(state.frontier), &state.journal, checkpoint, before_cas)
    }

    pub(super) fn commit(
        &self,
        expected: Option<ReleaseFrontierV1>,
        journal: &Journal,
        checkpoint: [u8; 32],
    ) -> Result<(), FleetRegistryError> {
        self.commit_checked(expected, journal, checkpoint, || Ok(()))
    }

    fn commit_checked(
        &self,
        expected: Option<ReleaseFrontierV1>,
        journal: &Journal,
        checkpoint: [u8; 32],
        before_cas: impl FnOnce() -> Result<(), FleetRegistryError>,
    ) -> Result<(), FleetRegistryError> {
        self.commit_checked_publication(expected, journal, checkpoint, before_cas)
            .map(|_| ())
    }

    // Only the held intent path consumes this exact publication evidence.
    // Existing mutation callers retain their original unit-return contract.
    pub(super) fn commit_checked_publication(
        &self,
        expected: Option<ReleaseFrontierV1>,
        journal: &Journal,
        checkpoint: [u8; 32],
        before_cas: impl FnOnce() -> Result<(), FleetRegistryError>,
    ) -> Result<(ReleaseFrontierV1, Vec<u8>), FleetRegistryError> {
        let bytes = record_bytes(journal)?;
        if bytes.len() > MAX_AUTHORITY_BYTES {
            return Err(invalid("release security history exceeds its byte bound"));
        }
        let next = ReleaseFrontierV1 {
            generation: journal.generation,
            initial_root_sha256: self.config.initial_root_sha256,
            checkpoint_sha256: checkpoint,
            state_sha256: Sha256::digest(&bytes).into(),
        };
        let attempt = record_bytes(&PendingUpdate {
            schema_version: 1,
            expected,
            proposed: next,
        })?;
        self.files.prepare(&bytes, &attempt)?;
        if before_cas().is_err() {
            // The durable records remain a fenced preparation even though no
            // CAS was issued by this call. Recovery must inspect exact state.
            self.fenced.store(true, Ordering::Release);
            return Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired);
        }
        // From this point an error is an unresolved external effect. Never retry
        // or erase the prepared journal after a timeout, bad signature or ack.
        if self
            .frontier
            .compare_and_set(&self.config.owner_id, &expected, &Some(next))
            .is_err()
            || self.files.publish().is_err()
        {
            self.fenced.store(true, Ordering::Release);
            return Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired);
        }
        Ok((next, bytes))
    }
}
