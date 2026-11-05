//! Non-cloneable current publication guards and last-point authorization.

use std::fs::File;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::AgentId;
use sha2::Digest;
use sha2::Sha256;
use trnm_release_bundle::pq_release::PqReleaseRoleV1;

use super::CurrentPublication;
use super::ReleaseAuthority;
use super::ReleaseUse;
use super::invalid;
use crate::FleetRegistryError;
use crate::ReleaseId;
use crate::ReleaseMetadata;
use crate::release_authority_set::manifest_bytes;
use crate::release_authority_state::Admission;
use crate::release_authority_state::LoadedState;

impl ReleaseAuthority {
    pub fn member(&self, release_id: &ReleaseId) -> Result<ReleaseUse, FleetRegistryError> {
        let (lock, state, now) = self.load()?;
        let metadata = self.current_member(&state, release_id, now)?.clone();
        Self::current_use(lock, state, metadata, None, None)
    }

    pub fn admit(
        &self,
        agent_id: &AgentId,
        release_id: &ReleaseId,
    ) -> Result<ReleaseUse, FleetRegistryError> {
        let (lock, state, now) = self.load()?;
        let (metadata, permission) = self.member_projection(&state, agent_id, release_id, now)?;
        Self::current_use(
            lock,
            state,
            metadata,
            Some(agent_id.clone()),
            Some(permission),
        )
    }

    pub(super) fn member_projection(
        &self,
        state: &LoadedState,
        agent_id: &AgentId,
        release_id: &ReleaseId,
        now: u64,
    ) -> Result<(ReleaseMetadata, [u8; 32]), FleetRegistryError> {
        let metadata =
            self.current_member(state, release_id, now)
                .map_err(|error| match error {
                    FleetRegistryError::ReleaseNotPublished(_) => {
                        FleetRegistryError::ReleaseNotAllowed {
                            agent_id: agent_id.clone(),
                            release_id: release_id.to_string(),
                        }
                    }
                    other => other,
                })?;
        let digest: [u8; 32] = Sha256::digest(manifest_bytes(metadata)?).into();
        match state
            .admissions
            .get(&(agent_id.clone(), release_id.clone()))
        {
            Some(Admission::Allowed(expected)) if *expected == digest => {}
            Some(Admission::Revoked(_)) => {
                return Err(FleetRegistryError::ReleaseRevoked {
                    agent_id: agent_id.clone(),
                    release_id: release_id.to_string(),
                });
            }
            Some(Admission::Allowed(_)) => {
                return Err(invalid("published member differs from durable allowance"));
            }
            None => {
                return Err(FleetRegistryError::ReleaseNotAllowed {
                    agent_id: agent_id.clone(),
                    release_id: release_id.to_string(),
                });
            }
        }
        let metadata = metadata.clone();
        let permission = self.permission_sha256(state, agent_id)?;
        Ok((metadata, permission))
    }

    pub fn publication_member_projection(
        &self,
        admission: &CurrentPublication,
        agent_id: &AgentId,
        release_id: &ReleaseId,
    ) -> Result<(ReleaseMetadata, [u8; 32]), FleetRegistryError> {
        if admission.role != PqReleaseRoleV1::ProtocolConfiguration {
            return Err(invalid(
                "release observation requires its actual protocol admission",
            ));
        }
        let (state, now) = self.load_locked(&admission._lock)?;
        if state.frontier != admission.frontier {
            return Err(FleetRegistryError::ReleaseAuthorityRollback);
        }
        state
            .authority
            .check_current(
                admission.role,
                admission.content,
                state.frontier.checkpoint_sha256,
                now,
            )
            .map_err(|error| {
                invalid(format!("M15 release observation policy rejected: {error}"))
            })?;
        self.member_projection(&state, agent_id, release_id, now)
    }

    fn permission_sha256(
        &self,
        state: &LoadedState,
        agent_id: &AgentId,
    ) -> Result<[u8; 32], FleetRegistryError> {
        // Intent snapshots advance the complete antirollback frontier but do
        // not mutate M15's publication checkpoint. Every dispatch still checks
        // the full fresh frontier; this projection only stabilizes transaction
        // bindings while the exact publisher/agent permissions are unchanged.
        // Source and target must share this complete authorization snapshot.
        // Their individual manifests/programs remain bound by ReleaseBinding;
        // including the selected member here would forbid every real upgrade.
        let release_set = state
            .journal
            .current_set
            .as_ref()
            .ok_or(FleetRegistryError::ReleaseAuthorityRequired)?
            .bundle
            .bundle_digest;
        let allowances = state
            .admissions
            .iter()
            .filter(|((agent, _), _)| agent == agent_id)
            .map(|((_, release), value)| match value {
                Admission::Allowed(digest) => (release, true, *digest),
                Admission::Revoked(digest) => (release, false, *digest),
            })
            .collect::<Vec<_>>();
        let mut hash = Sha256::new();
        hash.update(b"hepta.fleet.release-permission.v2\0");
        hash.update(
            serde_json::to_vec(&(
                &self.config.owner_id,
                self.config.initial_root_sha256,
                state.frontier.checkpoint_sha256,
                release_set,
                agent_id,
                allowances,
            ))
            .map_err(|_| invalid("cannot encode release permission binding"))?,
        );
        Ok(hash.finalize().into())
    }

    fn current_use(
        lock: File,
        state: LoadedState,
        metadata: ReleaseMetadata,
        agent_id: Option<AgentId>,
        permission_sha256: Option<[u8; 32]>,
    ) -> Result<ReleaseUse, FleetRegistryError> {
        let content = state
            .journal
            .current_set
            .as_ref()
            .ok_or(FleetRegistryError::ReleaseAuthorityRequired)?
            .bundle
            .bundle_digest;
        Ok(ReleaseUse {
            metadata,
            agent_id,
            permission_sha256,
            publication: Self::publication_use(lock, state, PqReleaseRoleV1::NodeSoftware, content),
        })
    }

    fn publication_use(
        lock: File,
        state: LoadedState,
        role: PqReleaseRoleV1,
        content: [u8; 32],
    ) -> CurrentPublication {
        CurrentPublication {
            _lock: lock,
            frontier: state.frontier,
            authority: state.authority,
            role,
            content,
            time_floor: state.time_floor,
            decision_window: None,
        }
    }

    pub fn protocol_configuration(
        &self,
        content: [u8; 32],
    ) -> Result<CurrentPublication, FleetRegistryError> {
        let (lock, state, now) = self.load()?;
        state
            .authority
            .check_current(
                PqReleaseRoleV1::ProtocolConfiguration,
                content,
                state.frontier.checkpoint_sha256,
                now,
            )
            .map_err(|error| {
                invalid(format!(
                    "M15 current protocol configuration rejected: {error}"
                ))
            })?;
        Ok(Self::publication_use(
            lock,
            state,
            PqReleaseRoleV1::ProtocolConfiguration,
            content,
        ))
    }

    /// Recheck immediately before dispatch after any copying, hashing, or
    /// queuing. A held local lock cannot keep a signed publication unexpired.
    pub fn recheck(&self, admission: &CurrentPublication) -> Result<u64, FleetRegistryError> {
        if self.fenced.load(Ordering::Acquire) {
            return Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired);
        }
        let frontier = self.frontier.load(&self.config.owner_id).map_err(|error| {
            invalid(format!("release frontier unavailable at dispatch: {error}"))
        })?;
        if frontier != Some(admission.frontier)
            || <[u8; 32]>::from(Sha256::digest(self.files.journal()?))
                != admission.frontier.state_sha256
        {
            return Err(FleetRegistryError::ReleaseAuthorityRollback);
        }
        let unix_ms = self.now_unix_ms()?;
        if let Some(window) = admission.decision_window {
            window.check(unix_ms)?;
        }
        let now = unix_ms / 1000;
        if now < admission.time_floor {
            return Err(invalid("release clock regressed at dispatch"));
        }
        admission
            .authority
            .check_current(
                admission.role,
                admission.content,
                admission.frontier.checkpoint_sha256,
                now,
            )
            .map_err(|error| invalid(format!("M15 dispatch publication rejected: {error}")))?;
        Ok(unix_ms)
    }

    pub fn recheck_with_protocol_configuration(
        &self,
        admission: &CurrentPublication,
        content: [u8; 32],
    ) -> Result<u64, FleetRegistryError> {
        let unix_ms = self.recheck(admission)?;
        admission
            .authority
            .check_current(
                PqReleaseRoleV1::ProtocolConfiguration,
                content,
                admission.frontier.checkpoint_sha256,
                unix_ms / 1000,
            )
            .map_err(|error| {
                invalid(format!(
                    "M15 dispatch protocol configuration rejected: {error}"
                ))
            })?;
        Ok(unix_ms)
    }

    pub(super) fn current_member<'a>(
        &self,
        state: &'a LoadedState,
        release_id: &ReleaseId,
        now: u64,
    ) -> Result<&'a ReleaseMetadata, FleetRegistryError> {
        let set = state
            .journal
            .current_set
            .as_ref()
            .ok_or(FleetRegistryError::ReleaseAuthorityRequired)?;
        state
            .authority
            .check_current(
                PqReleaseRoleV1::NodeSoftware,
                set.bundle.bundle_digest,
                state.frontier.checkpoint_sha256,
                now,
            )
            .map_err(|error| invalid(format!("M15 current publication rejected: {error}")))?;
        set.members
            .iter()
            .find(|member| &member.release.release_id == release_id)
            .map(|member| &member.release)
            .ok_or_else(|| FleetRegistryError::ReleaseNotPublished(release_id.to_string()))
    }
}
