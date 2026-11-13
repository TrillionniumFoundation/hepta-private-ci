//! Data copied from the exact already validated Root deployment, without owners.

use super::*;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::Digest32;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(in super::super) struct EnrollmentProfile {
    initial_snapshot: String,
    scope: Scope,
    original_intent: SignedFinalUseGrant,
    original_lease: AuthorityLease,
    binding: String,
}

impl EnrollmentProfile {
    pub(super) fn capture(
        original: (String, Scope, SignedFinalUseGrant, AuthorityLease),
        binding: Digest32,
    ) -> Self {
        let (initial_snapshot, scope, original_intent, original_lease) = original;
        Self { initial_snapshot, scope, original_intent, original_lease, binding: binding.to_string() }
    }

    /// Called only after Root pair, sealed descriptor and recipient validation.
    /// Rebuilding public profile data does not authenticate any stage result.
    pub(in super::super) fn original(
        self,
        verifier: &LearningEvidenceVerifierV1,
    ) -> io::Result<RootResidentLearningProfileV3> {
        let raw = decode(&self.initial_snapshot, 8_192)?;
        let initial = decode_original_owner_snapshot_v1(&raw).map_err(io::Error::other)?;
        if encode_original_owner_snapshot_v1(&initial).map_err(io::Error::other)? != raw {
            return Err(io::Error::other("noncanonical resident initial cut"));
        }
        let scope = FrozenLearningScopeV2::freeze(
            &initial.request,
            &initial.owners,
            match self.scope.update_scope {
                UpdateScope::Cell => LearningUpdateScopeV2::Cell,
                UpdateScope::Organ => LearningUpdateScopeV2::Organ,
            },
            digest(&self.scope.update_rule)?,
        ).map_err(io::Error::other)?;
        if scope.binding() != digest(&self.scope.binding)? {
            return Err(io::Error::other("resident frozen scope differs"));
        }
        let profile = RootResidentLearningProfileV3::new(
            initial, scope, verifier, self.original_intent, self.original_lease,
        )?;
        if profile.binding() != digest(&self.binding)? {
            return Err(io::Error::other("resident full profile differs"));
        }
        Ok(profile)
    }
}
