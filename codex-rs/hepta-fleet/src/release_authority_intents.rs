//! H7 snapshots share the publication journal, lock, retained attempt and exact
//! external CAS. They never create a second recovery root or launch permission.

use codex_hepta_contracts::AgentId;
use sha2::Digest;
use sha2::Sha256;
use std::sync::atomic::Ordering;
use trnm_release_bundle::pq_release::PqReleaseRoleV1;

use super::CurrentPublication;
use super::ReleaseAuthority;
use super::invalid;
use crate::FleetRegistryError;
use crate::release_authority_state::JournalEntry;
use crate::release_authority_state::LoadedState;
use crate::release_intent_anchor::AnchorMutation;
use crate::release_intent_anchor::ReleaseIntentAnchorV1;
use crate::release_intent_anchor::validate_transition;

impl ReleaseAuthority {
    pub fn intent_anchor(
        &self,
        agent: &AgentId,
    ) -> Result<Option<ReleaseIntentAnchorV1>, FleetRegistryError> {
        let (_lock, state, _now) = self.load()?;
        Ok(state.intent_anchors.get(agent).cloned())
    }

    /// Fresh historical observation under an already-held owner lock. Reading
    /// a terminal snapshot does not demand that its old policy remain current.
    pub fn intent_anchor_held(
        &self,
        admission: &CurrentPublication,
        agent: &AgentId,
    ) -> Result<Option<ReleaseIntentAnchorV1>, FleetRegistryError> {
        self.recheck_history_snapshot(admission)?;
        Ok(admission.state.intent_anchors.get(agent).cloned())
    }

    pub fn previous_closed_intent_held(
        &self,
        admission: &CurrentPublication,
        agent: &AgentId,
    ) -> Result<Option<ReleaseIntentAnchorV1>, FleetRegistryError> {
        self.recheck_history_snapshot(admission)?;
        Ok(admission.state.previous_closed_intents.get(agent).cloned())
    }

    /// The guard owns this already-verified state under the same File lock.
    /// Every history read still authenticates the fresh complete frontier and
    /// hashes all bounded journal bytes before checking the trusted time floor.
    /// History is not current authorization: old policy/window expiry does not
    /// erase a committed fact, and these getters never grant an effect.
    fn recheck_history_snapshot(
        &self,
        admission: &CurrentPublication,
    ) -> Result<(), FleetRegistryError> {
        if self.fenced.load(Ordering::Acquire) {
            return Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired);
        }
        let external = self
            .frontier
            .load(&self.config.owner_id)
            .map_err(|error| invalid(format!("release frontier unavailable: {error}")))?
            .ok_or(FleetRegistryError::ReleaseAuthorityRollback)?;
        let bytes = self.files.journal()?;
        if external != admission.frontier
            || external.initial_root_sha256 != self.config.initial_root_sha256
            || external.state_sha256 != <[u8; 32]>::from(Sha256::digest(&bytes))
        {
            return Err(FleetRegistryError::ReleaseAuthorityRollback);
        }
        if self.now()? < admission.state.time_floor {
            return Err(invalid("release clock regressed behind committed history"));
        }
        Ok(())
    }

    pub fn anchor_protocol_intent(
        &self,
        admission: &mut CurrentPublication,
        expected: Option<&ReleaseIntentAnchorV1>,
        next: &ReleaseIntentAnchorV1,
    ) -> Result<(), FleetRegistryError> {
        let policy_sha256 = Self::protocol_content(admission)?;
        self.anchor_held(
            admission,
            expected,
            next,
            AnchorMutation::Current { policy_sha256 },
        )
    }

    pub fn recover_protocol_intent(
        &self,
        admission: &mut CurrentPublication,
        expected: Option<&ReleaseIntentAnchorV1>,
        next: &ReleaseIntentAnchorV1,
        decision_sha256: [u8; 32],
    ) -> Result<(), FleetRegistryError> {
        let policy_sha256 = Self::protocol_content(admission)?;
        self.anchor_held(
            admission,
            expected,
            next,
            AnchorMutation::Recovery {
                policy_sha256,
                decision_sha256,
            },
        )
    }

    pub fn recover_unanchored_protocol_intent(
        &self,
        admission: &mut CurrentPublication,
        expected: &ReleaseIntentAnchorV1,
        next: &ReleaseIntentAnchorV1,
        decision_sha256: [u8; 32],
        predecessor_anchor_sha256: [u8; 32],
    ) -> Result<(), FleetRegistryError> {
        let policy_sha256 = Self::protocol_content(admission)?;
        self.anchor_held(
            admission,
            Some(expected),
            next,
            AnchorMutation::UnanchoredRecovery {
                policy_sha256,
                decision_sha256,
                predecessor_anchor_sha256,
            },
        )
    }

    pub fn anchor_release_intent(
        &self,
        admission: &mut CurrentPublication,
        policy_sha256: [u8; 32],
        expected: Option<&ReleaseIntentAnchorV1>,
        next: &ReleaseIntentAnchorV1,
    ) -> Result<(), FleetRegistryError> {
        if admission.role != PqReleaseRoleV1::NodeSoftware {
            return Err(invalid(
                "intent dispatch requires its actual release admission",
            ));
        }
        self.anchor_held(
            admission,
            expected,
            next,
            AnchorMutation::Current { policy_sha256 },
        )
    }

    pub fn confirm_abandon_unknown_publication(
        &self,
        admission: &mut CurrentPublication,
        expected: &ReleaseIntentAnchorV1,
        next: &ReleaseIntentAnchorV1,
        confirmation_sha256: [u8; 32],
        expected_anchor_sha256: [u8; 32],
    ) -> Result<(), FleetRegistryError> {
        let policy_sha256 = Self::protocol_content(admission)?;
        self.anchor_held(
            admission,
            Some(expected),
            next,
            AnchorMutation::ConfirmAbandonUnknown {
                policy_sha256,
                confirmation_sha256,
                expected_anchor_sha256,
            },
        )
    }

    /// Only strict quarantine or a hot owner's actual queued completion may use
    /// this path. A cold caller must compare snapshots, never infer completion
    /// from locally edited transaction/status bytes. No policy is revived here.
    pub fn record_intent_history(
        &self,
        expected: &ReleaseIntentAnchorV1,
        next: &ReleaseIntentAnchorV1,
    ) -> Result<(), FleetRegistryError> {
        let (_lock, state, now) = self.load()?;
        self.append_intent(
            state,
            Some(expected),
            next,
            AnchorMutation::Historical,
            now,
            || Ok(()),
        )
    }

    fn protocol_content(admission: &CurrentPublication) -> Result<[u8; 32], FleetRegistryError> {
        if admission.role != PqReleaseRoleV1::ProtocolConfiguration {
            return Err(invalid(
                "intent policy requires its distinct protocol admission",
            ));
        }
        Ok(admission.content)
    }

    fn anchor_held(
        &self,
        admission: &mut CurrentPublication,
        expected: Option<&ReleaseIntentAnchorV1>,
        next: &ReleaseIntentAnchorV1,
        authorization: AnchorMutation,
    ) -> Result<(), FleetRegistryError> {
        let window = admission.decision_window.ok_or_else(|| {
            invalid("intent mutation requires its verified decision validity window")
        })?;
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
            .map_err(|error| invalid(format!("M15 intent admission rejected: {error}")))?;
        let policy = authorization
            .policy()
            .ok_or_else(|| invalid("missing intent policy"))?;
        state
            .authority
            .check_current(
                PqReleaseRoleV1::ProtocolConfiguration,
                policy,
                state.frontier.checkpoint_sha256,
                now,
            )
            .map_err(|error| invalid(format!("M15 intent policy rejected: {error}")))?;
        let software = state
            .journal
            .current_set
            .as_ref()
            .ok_or(FleetRegistryError::ReleaseAuthorityRequired)?
            .bundle
            .bundle_digest;
        window.check(self.now_unix_ms()?)?;
        self.append_intent(state, expected, next, authorization, now, || {
            let unix_ms = self.recheck_with_protocol_configuration(admission, policy)?;
            window.check(unix_ms)?;
            admission
                .state
                .authority
                .check_current(
                    PqReleaseRoleV1::NodeSoftware,
                    software,
                    admission.frontier.checkpoint_sha256,
                    unix_ms / 1000,
                )
                .map_err(|error| {
                    invalid(format!("M15 intent software rejected before CAS: {error}"))
                })?;
            Ok(())
        })?;
        // Retain the same File lock; reopening it would be a non-reentrant
        // acquisition. A fresh load also fences any unexpected external change.
        let (state, _now) = self.load_locked(&admission._lock)?;
        admission.frontier = state.frontier;
        admission.state = state;
        Ok(())
    }

    fn append_intent(
        &self,
        state: LoadedState,
        expected: Option<&ReleaseIntentAnchorV1>,
        next: &ReleaseIntentAnchorV1,
        authorization: AnchorMutation,
        now: u64,
        before_cas: impl FnOnce() -> Result<(), FleetRegistryError>,
    ) -> Result<(), FleetRegistryError> {
        let actual = state.intent_anchors.get(&next.agent_id);
        if actual != expected {
            return Err(FleetRegistryError::ReleaseAuthorityRollback);
        }
        if actual == Some(next) {
            return Ok(());
        }
        validate_transition(actual, next, authorization, &state.consumed_grants)?;
        // No native M15 event is created by an intent snapshot. Publication
        // permissions and their checkpoint remain stable; the complete journal
        // digest, time floor and external generation still advance durably.
        let checkpoint = state.frontier.checkpoint_sha256;
        self.append_and_commit_checked(
            state,
            JournalEntry::IntentAnchor {
                anchor: next.clone(),
                authorization,
                observed_at: now,
            },
            checkpoint,
            before_cas,
        )
    }
}
