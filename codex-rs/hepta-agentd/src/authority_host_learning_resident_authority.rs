//! The original Root lease and issuer fences surround only synchronous store
//! operations. They never surround a returned future or remote role execution.

use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use std::io;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;
use tokio_util::sync::CancellationToken;

use super::profile::RootResidentLearningProfileV3;
use super::profile::ResidentPurposeV3;
use super::profile::RootResidentLearningReadbackAuthorizationV3;
use super::profile::invalid;
use super::profile::lease_binding;
use super::store::FreshResidentCheckpointV3;
use super::store::ResidentCheckpointV3;
use super::store::ResidentSnapshotV3;
use crate::DeploymentFinalUseIssuer;

#[derive(Clone, Copy)]
enum ResidentAccessV3 { Observe, Work }

pub(super) enum ResidentAuthorizationV3 {
    Fresh,
    Readback(RootResidentLearningReadbackAuthorizationV3),
}

pub(super) struct ResidentRootAuthorityV3 {
    pub(super) profile: RootResidentLearningProfileV3,
    issuer: Arc<DeploymentFinalUseIssuer>,
    registry: Arc<AuthorityLeaseRegistry>,
    authorization: ResidentAuthorizationV3,
    root_pid: u32,
}

pub(super) enum ResidentStoreActionV3<'a> {
    Register(Arc<RootAuthorityDirectory>),
    Recover(Arc<RootAuthorityDirectory>),
    Check,
    Read(&'a ResidentCheckpointV3),
    Admit(&'a ResidentCheckpointV3),
    Begin(&'a ResidentCheckpointV3, &'a mut FreshResidentCheckpointV3,
        &'a LearningIterationSnapshotV1, LearningIterationStageV1),
    RequireDispatch(&'a ResidentCheckpointV3, &'a FreshResidentCheckpointV3,
        &'a LearningIterationSnapshotV1),
    Checkpoint(&'a ResidentCheckpointV3, &'a mut FreshResidentCheckpointV3,
        &'a LearningIterationSnapshotV1, &'a LearningIterationSnapshotV1),
}

pub(super) enum ResidentStoreValueV3 {
    Store(ResidentCheckpointV3),
    Snapshot(ResidentSnapshotV3),
    Fresh(Option<FreshResidentCheckpointV3>),
    Checked,
}

pub(super) struct ResidentBoundaryV3 {
    pub(super) value: ResidentStoreValueV3,
    pub(super) now_ms: u64,
}

impl ResidentRootAuthorityV3 {
    pub(super) fn new(
        profile: RootResidentLearningProfileV3,
        issuer: Arc<DeploymentFinalUseIssuer>,
        registry: Arc<AuthorityLeaseRegistry>,
        authorization: ResidentAuthorizationV3,
    ) -> io::Result<Self> {
        // Credentials alone confer no permission; every operation below also
        // verifies the exact externally supplied intent and same Registry.
        if rustix::process::geteuid().as_raw() != 0 {
            return Err(invalid("resident authority must remain in its original Root process"));
        }
        let owner = Self {
            profile, issuer, registry, authorization, root_pid: std::process::id(),
        };
        owner.perform(ResidentStoreActionV3::Check, &CancellationToken::new())?;
        Ok(owner)
    }

    pub(super) fn readonly(&self) -> bool {
        matches!(&self.authorization, ResidentAuthorizationV3::Readback(_))
    }

    pub(super) fn authorization_binding(&self) -> io::Result<codex_hepta_types::Digest32> {
        let (intent, lease) = self.artifacts();
        super::profile::authorization_binding(&self.profile, intent, lease)
    }

    fn artifacts(&self) -> (&SignedFinalUseGrant, &AuthorityLease) {
        match &self.authorization {
            ResidentAuthorizationV3::Fresh => (&self.profile.intent, &self.profile.lease),
            ResidentAuthorizationV3::Readback(authorization) =>
                (&authorization.intent, &authorization.lease),
        }
    }

    pub(super) fn perform(
        &self,
        action: ResidentStoreActionV3<'_>,
        cancellation: &CancellationToken,
    ) -> io::Result<ResidentBoundaryV3> {
        let access = if matches!(&action,
            ResidentStoreActionV3::Register(_) | ResidentStoreActionV3::Admit(_)
            | ResidentStoreActionV3::Begin(..) | ResidentStoreActionV3::RequireDispatch(..)
            | ResidentStoreActionV3::Checkpoint(..)) {
                ResidentAccessV3::Work
            } else {
                ResidentAccessV3::Observe
            };
        if self.root_pid != std::process::id()
            || rustix::process::geteuid().as_raw() != 0
            || cancellation.is_cancelled()
            || (matches!(access, ResidentAccessV3::Work) && self.readonly())
        {
            return Err(invalid("resident original process, cancellation or readonly fence"));
        }
        let before = Instant::now() + Duration::from_secs(2);
        let (intent, lease) = self.artifacts();
        let expected = self.profile.expected(if self.readonly() {
            ResidentPurposeV3::Readback
        } else {
            ResidentPurposeV3::Execute
        })?;
        let binding = lease_binding(&expected);
        let verifier = self.registry.verifier();
        let current = verifier.read_lease(&lease.lease_id).map_err(io::Error::other)?
            .ok_or_else(|| invalid("resident original lease is missing"))?;
        if current.lease != *lease || intent.grant.binding != expected
            || lease.binding != binding
        {
            return Err(invalid("resident complete original authorization changed"));
        }
        let token = verifier.verify_use(&lease.lease_id, lease.revision, &binding)
            .map_err(io::Error::other)?;
        // The callback produces concrete synchronous data only. Registry ->
        // issuer -> Root file CAS is the existing lock order; remote stages
        // run after all three fences have been released.
        verifier.with_dispatch_boundary(token, &binding, || {
            let issuer = self.issuer.hold_original_resident_intent_v3(
                intent, &expected, before,
            )?;
            let started = issuer.require_current()?;
            require_time(started, lease, self.profile.deadline_ms, access)?;
            if cancellation.is_cancelled() {
                return Err(invalid("resident cancelled before its local boundary"));
            }
            let value = match action {
                ResidentStoreActionV3::Register(root) =>
                    ResidentStoreValueV3::Store(ResidentCheckpointV3::register(
                        root, self.profile.clone(),
                    )?),
                ResidentStoreActionV3::Recover(root) =>
                    ResidentStoreValueV3::Store(ResidentCheckpointV3::recover(
                        root, self.profile.clone(),
                    )?),
                ResidentStoreActionV3::Check => ResidentStoreValueV3::Checked,
                ResidentStoreActionV3::Read(owner) =>
                    ResidentStoreValueV3::Snapshot(owner.read()?),
                ResidentStoreActionV3::Admit(owner) =>
                    ResidentStoreValueV3::Fresh(owner.admit()?),
                ResidentStoreActionV3::Begin(owner, fresh, predecessor, stage) => {
                    owner.begin_dispatch(fresh, predecessor, stage)?;
                    ResidentStoreValueV3::Checked
                }
                ResidentStoreActionV3::RequireDispatch(owner, fresh, predecessor) => {
                    owner.require_dispatch(fresh, predecessor)?;
                    ResidentStoreValueV3::Checked
                }
                ResidentStoreActionV3::Checkpoint(owner, fresh, predecessor, next) => {
                    owner.checkpoint(fresh, predecessor, next)?;
                    ResidentStoreValueV3::Checked
                }
            };
            // An elapsed window/cancellation after persistence is uncertain,
            // never proof that the CAS or a preceding remote effect did not occur.
            let now_ms = issuer.require_current()?;
            require_time(now_ms, lease, self.profile.deadline_ms, access)?;
            if now_ms < started || cancellation.is_cancelled() {
                return Err(invalid("resident boundary lost its current authorization"));
            }
            Ok(ResidentBoundaryV3 { value, now_ms })
        }).map_err(io::Error::other)?
    }
}

fn require_time(now_ms: u64, lease: &AuthorityLease, deadline_ms: u64, access: ResidentAccessV3)
    -> io::Result<()>
{
    if now_ms < lease.issued_at_unix_ms || now_ms >= lease.expires_at_unix_ms
        || (matches!(access, ResidentAccessV3::Work) && (now_ms >= deadline_ms
            || deadline_ms.saturating_sub(now_ms) > 86_400_000))
    {
        return Err(invalid("resident original lease or work deadline elapsed"));
    }
    Ok(())
}
