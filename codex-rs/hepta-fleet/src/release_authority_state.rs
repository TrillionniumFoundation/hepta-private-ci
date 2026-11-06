use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::ReleaseFrontierV1;
use serde::Deserialize;
use serde::Serialize;
use trnm_release_bundle::pq_release::MAX_RECOVERY_EVENTS_V1;
use trnm_release_bundle::pq_release::PqReleaseAuthorityV1;
use trnm_release_bundle::pq_release::PqReleaseEventV1;
use trnm_release_bundle::pq_release::PqReleaseRoleV1;
use trnm_release_bundle::pq_release::PqReleaseRootV1;

use crate::FleetRegistryError;
use crate::ReleaseId;
use crate::release_authority::FleetReleaseTrustConfig;
use crate::release_authority::invalid;
use crate::release_authority_set::ReleaseSetRecord;
use crate::release_authority_wire::AuthorityEventRecord;
use crate::release_authority_wire::RootRecord;
use crate::release_intent_anchor::AnchorMutation;
use crate::release_intent_anchor::ReleaseIntentAnchorV1;
use crate::release_intent_anchor::validate_transition;
use crate::release_intent_reconciliation_record::IntentReconciliationRecord;

const JOURNAL_PROFILE: &str = "hepta.fleet.release-journal.v1";
pub(crate) const MAX_JOURNAL_ENTRIES: usize = MAX_RECOVERY_EVENTS_V1 * 2;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum JournalEntry {
    Authority {
        event: AuthorityEventRecord,
    },
    Allow {
        agent_id: AgentId,
        release_id: ReleaseId,
        manifest_sha256: [u8; 32],
        observed_at: u64,
    },
    Revoke {
        agent_id: AgentId,
        release_id: ReleaseId,
        manifest_sha256: [u8; 32],
        observed_at: u64,
    },
    IntentAnchor {
        anchor: ReleaseIntentAnchorV1,
        authorization: AnchorMutation,
        observed_at: u64,
    },
    IntentReconciliation {
        record: Box<IntentReconciliationRecord>,
    },
}

impl JournalEntry {
    fn observed_at(&self) -> u64 {
        match self {
            Self::Authority { event } => match event {
                AuthorityEventRecord::RootRotation { observed_at, .. }
                | AuthorityEventRecord::ReleaseSet { observed_at, .. }
                | AuthorityEventRecord::ProtocolConfiguration { observed_at, .. } => *observed_at,
            },
            Self::Allow { observed_at, .. }
            | Self::Revoke { observed_at, .. }
            | Self::IntentAnchor { observed_at, .. } => *observed_at,
            Self::IntentReconciliation { record } => record.observed_at,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Journal {
    pub schema_version: u32,
    pub profile: String,
    pub owner_id: String,
    pub generation: u64,
    pub previous_frontier: Option<ReleaseFrontierV1>,
    pub initial_root: RootRecord,
    pub initialized_at: u64,
    pub entries: Vec<JournalEntry>,
    pub current_set: Option<ReleaseSetRecord>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum Admission {
    Allowed([u8; 32]),
    Revoked([u8; 32]),
}

pub(crate) struct LoadedState {
    pub journal: Journal,
    pub authority: PqReleaseAuthorityV1,
    pub frontier: ReleaseFrontierV1,
    pub admissions: BTreeMap<(AgentId, ReleaseId), Admission>,
    pub intent_anchors: BTreeMap<AgentId, ReleaseIntentAnchorV1>,
    pub previous_closed_intents: BTreeMap<AgentId, ReleaseIntentAnchorV1>,
    pub consumed_grants: BTreeSet<(AgentId, [u8; 32])>,
    pub time_floor: u64,
}

impl Journal {
    pub fn initial(config: &FleetReleaseTrustConfig, root: RootRecord, now: u64) -> Self {
        Self {
            schema_version: 1,
            profile: JOURNAL_PROFILE.to_string(),
            owner_id: config.owner_id.clone(),
            generation: 1,
            previous_frontier: None,
            initial_root: root,
            initialized_at: now,
            entries: Vec::new(),
            current_set: None,
        }
    }

    pub fn rebuild(
        self,
        config: &FleetReleaseTrustConfig,
        frontier: ReleaseFrontierV1,
    ) -> Result<LoadedState, FleetRegistryError> {
        if self.schema_version != 1
            || self.profile != JOURNAL_PROFILE
            || self.owner_id != config.owner_id
            || self.initial_root.network_id != config.network_id
            || self.initialized_at == 0
            || self.entries.len() > MAX_JOURNAL_ENTRIES
            || self.generation != self.entries.len() as u64 + 1
            || self.generation != frontier.generation
            || frontier.initial_root_sha256 != config.initial_root_sha256
        {
            return Err(FleetRegistryError::ReleaseAuthorityRollback);
        }
        frontier
            .validate()
            .map_err(|_| invalid("invalid external release frontier"))?;
        match &self.previous_frontier {
            None if self.generation == 1 => {}
            Some(previous)
                if previous.validate().is_ok()
                    && previous.initial_root_sha256 == config.initial_root_sha256
                    && previous.generation.checked_add(1) == Some(self.generation) => {}
            _ => return Err(invalid("invalid retained release frontier predecessor")),
        }
        let root = PqReleaseRootV1::try_from(&self.initial_root)?;
        let mut authority = PqReleaseAuthorityV1::bootstrap_pinned(
            root,
            config.initial_root_sha256,
            self.initialized_at,
        )
        .map_err(|error| invalid(format!("M15 recovery root rejected: {error}")))?;
        let mut native = Vec::new();
        let latest_set = self.entries.iter().rposition(|entry| {
            matches!(
                entry,
                JournalEntry::Authority {
                    event: AuthorityEventRecord::ReleaseSet { .. }
                }
            )
        });
        if self.current_set.is_some() != latest_set.is_some() {
            return Err(invalid(
                "release set and signed publication history disagree",
            ));
        }
        let mut admissions = BTreeMap::new();
        let mut intent_anchors = BTreeMap::new();
        let mut previous_closed_intents = BTreeMap::new();
        let mut consumed_grants = BTreeSet::new();
        let mut time_floor = self.initialized_at;
        for (entry_index, entry) in self.entries.iter().enumerate() {
            let previous_time_floor = time_floor;
            if entry.observed_at() < time_floor {
                return Err(invalid("release journal clock regressed"));
            }
            time_floor = entry.observed_at();
            match entry {
                JournalEntry::Authority { event } => {
                    let event = PqReleaseEventV1::try_from(event)?;
                    match &event {
                        PqReleaseEventV1::RootRotation {
                            root,
                            old_signatures,
                            new_signatures,
                            observed_at,
                        } => {
                            authority
                                .rotate_root(
                                    root.clone(),
                                    old_signatures,
                                    new_signatures,
                                    *observed_at,
                                )
                                .map_err(|error| {
                                    invalid(format!("M15 recovery root rotation rejected: {error}"))
                                })?;
                        }
                        PqReleaseEventV1::Release {
                            metadata,
                            signatures,
                            observed_at,
                        } => {
                            if Some(entry_index) == latest_set {
                                let set = self.current_set.as_ref().ok_or_else(|| {
                                    invalid("release set and signed publication history disagree")
                                })?;
                                let binding = set.bind(config.platform_sha256)?;
                                // Verify the retained bundle at its actual signed
                                // event prefix before advancing the same authority.
                                // Later rotations and configuration events still
                                // replay normally; no authorization is cached.
                                authority
                                    .accept_bundle(
                                        &binding.bundle,
                                        &binding.required_packages,
                                        metadata,
                                        signatures,
                                        *observed_at,
                                    )
                                    .map_err(|error| {
                                        invalid(format!("M15 retained bundle rejected: {error}"))
                                    })?;
                            } else {
                                authority
                                    .accept(metadata, signatures, *observed_at)
                                    .map_err(|error| {
                                        invalid(format!(
                                            "M15 recovery publication rejected: {error}"
                                        ))
                                    })?;
                            }
                        }
                    }
                    native.push(event);
                }
                JournalEntry::Allow {
                    agent_id,
                    release_id,
                    manifest_sha256,
                    ..
                } => {
                    if *manifest_sha256 == [0; 32]
                        || admissions
                            .insert(
                                (agent_id.clone(), release_id.clone()),
                                Admission::Allowed(*manifest_sha256),
                            )
                            .is_some()
                    {
                        return Err(invalid("duplicate or invalid durable release allowance"));
                    }
                }
                JournalEntry::Revoke {
                    agent_id,
                    release_id,
                    manifest_sha256,
                    ..
                } => {
                    let key = (agent_id.clone(), release_id.clone());
                    if admissions.get(&key) != Some(&Admission::Allowed(*manifest_sha256)) {
                        return Err(invalid("revocation does not bind its durable allowance"));
                    }
                    admissions.insert(key, Admission::Revoked(*manifest_sha256));
                }
                JournalEntry::IntentAnchor {
                    anchor,
                    authorization,
                    observed_at,
                } => {
                    if let Some(policy) = authorization.policy() {
                        // Linear replay checks the actual signed policy prefix
                        // at this event's recorded time. Historical quarantine
                        // and completion do not revive an expired old policy.
                        authority
                            .check_current(
                                PqReleaseRoleV1::ProtocolConfiguration,
                                policy,
                                authority.checkpoint(),
                                *observed_at,
                            )
                            .map_err(|error| {
                                invalid(format!("M15 retained intent policy rejected: {error}"))
                            })?;
                    }
                    validate_transition(
                        intent_anchors.get(&anchor.agent_id),
                        anchor,
                        *authorization,
                        &consumed_grants,
                    )?;
                    retain_anchor(
                        &mut intent_anchors,
                        &mut previous_closed_intents,
                        &mut consumed_grants,
                        anchor,
                    );
                }
                JournalEntry::IntentReconciliation { record } => {
                    let mut prefix = self.clone();
                    prefix.entries.truncate(entry_index);
                    record.original.reconstruct(&prefix)?;
                    if record.original.observed_at < previous_time_floor {
                        return Err(invalid("retained intent proposal clock regressed"));
                    }
                    if let Some(policy) = record.original.authorization.policy() {
                        authority
                            .check_current(
                                PqReleaseRoleV1::ProtocolConfiguration,
                                policy,
                                authority.checkpoint(),
                                record.original.observed_at,
                            )
                            .map_err(|error| {
                                invalid(format!("M15 original intent policy rejected: {error}"))
                            })?;
                    }
                    authority
                        .check_current(
                            PqReleaseRoleV1::ProtocolConfiguration,
                            record.policy_sha256,
                            authority.checkpoint(),
                            record.observed_at,
                        )
                        .map_err(|error| {
                            invalid(format!("M15 reconciliation policy rejected: {error}"))
                        })?;
                    let software = record
                        .original
                        .original_current_set
                        .as_ref()
                        .ok_or(FleetRegistryError::ReleaseAuthorityRequired)?;
                    authority
                        .check_current(
                            PqReleaseRoleV1::NodeSoftware,
                            software.bundle.bundle_digest,
                            authority.checkpoint(),
                            record.observed_at,
                        )
                        .map_err(|error| {
                            invalid(format!("M15 reconciliation software rejected: {error}"))
                        })?;
                    record.validate_transition(
                        intent_anchors.get(&record.anchor.agent_id),
                        &consumed_grants,
                    )?;
                    retain_anchor(
                        &mut intent_anchors,
                        &mut previous_closed_intents,
                        &mut consumed_grants,
                        &record.anchor,
                    );
                }
            }
        }
        if native.len() > MAX_RECOVERY_EVENTS_V1
            || authority.checkpoint() != frontier.checkpoint_sha256
        {
            return Err(FleetRegistryError::ReleaseAuthorityRollback);
        }
        Ok(LoadedState {
            journal: self,
            authority,
            frontier,
            admissions,
            intent_anchors,
            previous_closed_intents,
            consumed_grants,
            time_floor,
        })
    }
}

pub(crate) fn retain_anchor(
    current: &mut BTreeMap<AgentId, ReleaseIntentAnchorV1>,
    previous_closed: &mut BTreeMap<AgentId, ReleaseIntentAnchorV1>,
    consumed: &mut BTreeSet<(AgentId, [u8; 32])>,
    anchor: &ReleaseIntentAnchorV1,
) {
    if let Some(previous) = current.get(&anchor.agent_id)
        && previous.grant_sha256 != anchor.grant_sha256
        && previous.is_closed_history()
    {
        previous_closed.insert(anchor.agent_id.clone(), previous.clone());
    }
    consumed.insert((anchor.agent_id.clone(), anchor.grant_sha256));
    current.insert(anchor.agent_id.clone(), anchor.clone());
}
