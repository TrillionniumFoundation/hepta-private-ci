//! Exact public data for a separately authorized resident operation.
//! Constructing this profile neither registers storage nor admits execution.

use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_types::Digest32;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use std::io;

use crate::learning_iteration_checkpoint::encode_original_owner_snapshot_v1;

pub const ROOT_RESIDENT_LEARNING_EXECUTE_V3: &str = "runtime.learning.resident-admission.v3";
pub const ROOT_RESIDENT_LEARNING_READBACK_V3: &str = "runtime.learning.resident-readback.v3";

#[derive(Clone, Copy)]
pub(super) enum ResidentPurposeV3 { Execute, Readback }

/// The initial cut contains the already completed A receipt. It is supplied
/// after A exists; startup cannot prefill a future completion or role signature.
/// The original Root supplies both signed intent and an already registered
/// exact-purpose lease. No constructor here issues or installs either one.
#[derive(Clone)]
pub struct RootResidentLearningProfileV3 {
    pub(super) initial: LearningIterationSnapshotV1,
    pub(super) scope: FrozenLearningScopeV2,
    pub(super) intent: SignedFinalUseGrant,
    pub(super) lease: AuthorityLease,
    pub(super) storage: Digest32,
    pub(super) operation: Digest32,
    pub(super) binding: Digest32,
    pub(super) deadline_ms: u64,
    evidence_scope: Digest32,
}

struct ResidentProfileIdentityV3 {
    storage: Digest32,
    operation: Digest32,
    deadline_ms: u64,
}

impl RootResidentLearningProfileV3 {
    pub fn new(
        initial: LearningIterationSnapshotV1,
        scope: FrozenLearningScopeV2,
        verifier: &LearningEvidenceVerifierV1,
        intent: SignedFinalUseGrant,
        lease: AuthorityLease,
    ) -> io::Result<Self> {
        let ResidentProfileIdentityV3 { storage, operation, deadline_ms } =
            profile_identity(&initial, &scope, verifier)?;
        let expected = expected_binding(&initial, &scope, operation, ResidentPurposeV3::Execute)?;
        require_artifacts(&intent, &lease, &expected, ROOT_RESIDENT_LEARNING_EXECUTE_V3)?;
        if intent.grant.expires_at_unix_ms < deadline_ms
            || lease.expires_at_unix_ms < deadline_ms
        {
            return Err(invalid("resident intent and lease must cover the original work deadline"));
        }
        let intent_bytes = intent.grant.signing_bytes().map_err(io::Error::other)?;
        let lease_bytes = serde_json::to_vec(&lease).map_err(io::Error::other)?;
        let binding = Digest32::of_parts(&[
            b"hepta.root.learning.resident-profile.v3\0",
            operation.as_array(),
            &intent_bytes,
            &intent.signature,
            &lease_bytes,
        ]);
        Ok(Self { initial, scope, intent, lease, storage, operation, binding, deadline_ms,
            evidence_scope: verifier.scope_digest() })
    }

    /// Canonical public data for an explicit original Root authorization.
    /// This validates the empty initial cut and complete verifier context, but
    /// does not sign, register a lease, initialize a store or admit execution.
    pub fn admission_binding(
        initial: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
        verifier: &LearningEvidenceVerifierV1,
    ) -> io::Result<FinalUseBinding> {
        let identity = profile_identity(initial, scope, verifier)?;
        expected_binding(initial, scope, identity.operation, ResidentPurposeV3::Execute)
    }

    /// The separate read-only purpose uses the same original operation bytes.
    /// A caller must still obtain its own current Root grant and Registry lease.
    pub fn readback_binding(&self) -> io::Result<FinalUseBinding> {
        self.expected(ResidentPurposeV3::Readback)
    }

    pub(super) fn require_verifier(&self, verifier: &LearningEvidenceVerifierV1) -> io::Result<()> {
        if verifier.trust_digest() != self.initial.owners.evidence_trust_digest
            || verifier.objective_digest() != self.initial.request.envelope.objective_digest
            || verifier.scope_digest() != self.evidence_scope
        {
            return Err(invalid("resident retained verifier full context differs"));
        }
        Ok(())
    }

    pub fn initial(&self) -> &LearningIterationSnapshotV1 {
        &self.initial
    }

    pub fn frozen_scope(&self) -> &FrozenLearningScopeV2 {
        &self.scope
    }

    pub fn binding(&self) -> Digest32 {
        self.binding
    }

    pub(super) fn owner_id(&self) -> String {
        // Stable identity excludes replaceable scope, deadline, source and
        // signature windows. Any rebind of the same logical operation collides
        // with this existing record and must match its complete profile.
        format!("root-learning-resident-v3:{}", self.storage)
    }

    pub(super) fn encoded_initial(&self) -> io::Result<String> {
        Ok(STANDARD_NO_PAD.encode(
            encode_original_owner_snapshot_v1(&self.initial).map_err(io::Error::other)?
        ))
    }

    pub(super) fn expected(&self, purpose: ResidentPurposeV3) -> io::Result<FinalUseBinding> {
        expected_binding(&self.initial, &self.scope, self.operation, purpose)
    }
}

/// Separate, explicit current Root permission for cold observation. It can
/// observe the same registered operation after the old work deadline, but can
/// never create a record, fresh token, dispatch intent, or later checkpoint.
pub struct RootResidentLearningReadbackAuthorizationV3 {
    pub(super) intent: SignedFinalUseGrant,
    pub(super) lease: AuthorityLease,
}

impl RootResidentLearningReadbackAuthorizationV3 {
    pub fn from_original_root(
        profile: &RootResidentLearningProfileV3,
        intent: SignedFinalUseGrant,
        lease: AuthorityLease,
    ) -> io::Result<Self> {
        require_artifacts(
            &intent, &lease, &profile.expected(ResidentPurposeV3::Readback)?, ROOT_RESIDENT_LEARNING_READBACK_V3,
        )?;
        Ok(Self { intent, lease })
    }
}

fn profile_identity(
    initial: &LearningIterationSnapshotV1,
    scope: &FrozenLearningScopeV2,
    verifier: &LearningEvidenceVerifierV1,
) -> io::Result<ResidentProfileIdentityV3> {
    let expected = LearningIterationCoordinatorV1::new(
        initial.request.clone(),
        initial.owners.clone(),
    ).map_err(io::Error::other)?;
    if expected.snapshot() != initial {
        return Err(invalid("resident profile requires the exact empty initial cut"));
    }
    scope.validate_snapshot(initial).map_err(io::Error::other)?;
    if verifier.trust_digest() != initial.owners.evidence_trust_digest
        || verifier.objective_digest() != initial.request.envelope.objective_digest
    {
        return Err(invalid("resident original evidence verifier differs"));
    }
    let bytes = encode_original_owner_snapshot_v1(initial).map_err(io::Error::other)?;
    let deadline_ms = initial.request.envelope.expiry_unix_seconds
        .checked_mul(1_000).ok_or_else(|| invalid("resident deadline overflow"))?;
    let stable = serde_json::to_vec(&[
        initial.request.principal_id.as_str(),
        initial.request.agent_id.as_str(),
        initial.request.operation_id.as_str(),
    ]).map_err(io::Error::other)?;
    let storage = Digest32::of_parts(&[
        b"hepta.root.learning.resident-storage.v3\0", &stable,
    ]);
    let operation = Digest32::of_parts(&[
        b"hepta.root.learning.resident-operation.v3\0",
        &bytes,
        scope.binding().as_array(),
        verifier.scope_digest().as_array(),
        &deadline_ms.to_be_bytes(),
    ]);
    Ok(ResidentProfileIdentityV3 { storage, operation, deadline_ms })
}

fn expected_binding(
    initial: &LearningIterationSnapshotV1,
    scope: &FrozenLearningScopeV2,
    operation: Digest32,
    purpose: ResidentPurposeV3,
) -> io::Result<FinalUseBinding> {
    let encoded = encode_original_owner_snapshot_v1(initial).map_err(io::Error::other)?;
    Ok(FinalUseBinding {
        subject_id: initial.request.principal_id.to_string(),
        destination_id: match purpose {
            ResidentPurposeV3::Execute => ROOT_RESIDENT_LEARNING_EXECUTE_V3,
            ResidentPurposeV3::Readback => ROOT_RESIDENT_LEARNING_READBACK_V3,
        }.into(),
        request_sha256: *Digest32::of_bytes(&encoded).as_array(),
        scope_sha256: *scope.binding().as_array(),
        payload_sha256: *operation.as_array(),
    })
}

pub(super) fn lease_binding(expected: &FinalUseBinding) -> AuthorityLeaseBinding {
    AuthorityLeaseBinding {
        principal_id: expected.subject_id.clone(),
        operation_class: expected.destination_id.clone(),
        destination_id: expected.destination_id.clone(),
        scope_sha256: expected.scope_sha256,
        payload_sha256: expected.payload_sha256,
    }
}

fn require_artifacts(
    intent: &SignedFinalUseGrant,
    lease: &AuthorityLease,
    expected: &FinalUseBinding,
    purpose: &str,
) -> io::Result<()> {
    if intent.grant.binding != *expected
        || expected.destination_id != purpose
        || intent.grant.schema_version != 1
        || intent.signature.len() != 64
        || intent.grant.not_before_unix_ms >= intent.grant.expires_at_unix_ms
        || lease.schema_version != 1
        || lease.revision == 0
        || lease.issued_at_unix_ms >= lease.expires_at_unix_ms
        || lease.binding != lease_binding(expected)
        || lease.authority_epoch != intent.grant.authority_epoch
    {
        return Err(invalid("resident original intent/lease full context differs"));
    }
    // Signing bytes validate bounded identifiers and canonical grant shape.
    intent.grant.signing_bytes().map_err(io::Error::other)?;
    Ok(())
}

pub(super) fn invalid(message: &'static str) -> io::Error {
    io::Error::new(io::ErrorKind::PermissionDenied, message)
}

pub(super) fn authorization_binding(
    profile: &RootResidentLearningProfileV3,
    intent: &SignedFinalUseGrant,
    lease: &AuthorityLease,
) -> io::Result<Digest32> {
    let signed = intent.grant.signing_bytes().map_err(io::Error::other)?;
    let lease = serde_json::to_vec(lease).map_err(io::Error::other)?;
    Ok(Digest32::of_parts(&[
        b"hepta.root.learning.resident-authorization.v3\0",
        profile.binding.as_array(), &signed, &intent.signature, &lease,
    ]))
}
