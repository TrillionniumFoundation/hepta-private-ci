//! Root-administered B trust and signed input admission. The private caller
//! supplies original descriptors; no daemon-selected root or signer is accepted.
//! Authentication binds the attester. It cannot turn declared provenance or
//! timestamps into an independently observed preregistration event.

use std::io;

use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_learning_ledger::verify_independent_roles;
use codex_hepta_types::Digest32;
use ed25519_dalek::SigningKey;
use serde::Deserialize;
use serde::Serialize;

use super::files::OriginalBFile;
use super::source::OriginalHoldoutSourceData;
use crate::root_initial_learning_trust_data::LearningTrustPayloadV1;
use crate::root_initial_learning_trust_data::LearningTrustRoleSelectionV1;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct RootIndependentBTrustData {
    schema: u8,
    purpose: String,
    original: LearningTrustPayloadV1,
    evaluator: LearningTrustRoleSelectionV1,
}

pub(super) struct OriginalBAuthorities {
    pub(super) verifier: LearningEvidenceVerifierV1,
    pub(super) generator: TrustedLearningSignerV1,
    pub(super) observer: TrustedLearningSignerV1,
    pub(super) evaluator: TrustedLearningSignerV1,
}

impl RootIndependentBTrustData {
    pub(super) fn decode(bytes: &[u8]) -> io::Result<Self> {
        if bytes.is_empty() || bytes.len() > 65_536 {
            return Err(io::Error::other("bounded original B trust required"));
        }
        let value: Self = serde_json::from_slice(bytes).map_err(io::Error::other)?;
        if serde_json::to_vec(&value).map_err(io::Error::other)? != bytes
            || value.schema != 1
            || value.purpose != "runtime.learning.independent-b-trust.v1"
        {
            return Err(io::Error::other("canonical original B trust required"));
        }
        Ok(value)
    }

    pub(super) fn activate(
        &self,
        initial: &LearningIterationSnapshotV1,
        now: u64,
    ) -> io::Result<OriginalBAuthorities> {
        let (activated, generator, observer) = self.original.activate_pinned_genesis(now)?;
        let verifier = activated.verifier();
        let mut selected = self.original.distribution.signers.iter().filter(|signer| {
            signer.principal_id == self.evaluator.principal_id
                && signer.controller_id == self.evaluator.controller_id
        });
        let evaluator = selected
            .next()
            .ok_or_else(|| io::Error::other("original B Evaluator is not enrolled"))?
            .original_signer()?;
        if selected.next().is_some()
            || verifier.trust_digest() != initial.owners.evidence_trust_digest
            || verifier.objective_digest() != initial.request.envelope.objective_digest
            || generator.principal.principal_id != initial.owners.trainer
            || evaluator.principal.principal_id != initial.owners.evaluator
        {
            return Err(io::Error::other(
                "original B trust differs from the Root learning owner",
            ));
        }
        verifier
            .require_signer_binding(LearningEvidenceRoleV1::Evaluator, &evaluator, now)
            .map_err(io::Error::other)?;
        for (left, right) in [
            (&generator, &observer),
            (&generator, &evaluator),
            (&observer, &evaluator),
        ] {
            verify_independent_roles(&left.principal, &right.principal, now)
                .map_err(io::Error::other)?;
            if left.controller_id == right.controller_id {
                return Err(io::Error::other("independent B controllers are required"));
            }
        }
        Ok(OriginalBAuthorities {
            verifier: verifier.clone(),
            generator,
            observer,
            evaluator,
        })
    }
}

impl OriginalBAuthorities {
    pub(super) fn original_key(&self, file: &OriginalBFile) -> io::Result<SigningKey> {
        let bytes = file.read_stable(32)?;
        let secret: [u8; 32] = bytes.as_slice().try_into().map_err(io::Error::other)?;
        let key = SigningKey::from_bytes(&secret);
        if key.verifying_key().to_bytes() != self.evaluator.verifying_key {
            return Err(io::Error::other(
                "B key is not the Root-fixed Evaluator key",
            ));
        }
        file.require_original()?;
        Ok(key)
    }

    pub(super) fn require_statement(
        &self,
        file: &OriginalBFile,
        role: LearningEvidenceRoleV1,
        expected: &[u8],
        now: u64,
    ) -> io::Result<SignedLearningEvidenceV1> {
        let signer = match role {
            LearningEvidenceRoleV1::Generator => &self.generator,
            LearningEvidenceRoleV1::Observer => &self.observer,
            LearningEvidenceRoleV1::Evaluator => &self.evaluator,
            LearningEvidenceRoleV1::CreditAllocator
            | LearningEvidenceRoleV1::UnlearningAuthority
            | LearningEvidenceRoleV1::Selector => {
                return Err(io::Error::other("B source role is not admitted"));
            }
        };
        let original = file.read_stable(65_536)?;
        let (payload, evidence) =
            crate::learning_owner_evidence::decode(&original).map_err(io::Error::other)?;
        let verified = self
            .verifier
            .verify(role, &evidence, &payload, now)
            .map_err(io::Error::other)?;
        if payload != expected
            || verified.principal() != &signer.principal
            || verified.controller_id() != &signer.controller_id
            || file.read_stable(65_536)? != original
        {
            return Err(io::Error::other("original B signed statement differs"));
        }
        Ok(evidence)
    }

    /// Invoked only within the actual consumed original holdout and Root arm.
    /// `registered_at` is supplied by the separate durable Root record, never
    /// parsed from these bytes and then treated as its own acknowledgement.
    pub(super) fn require_source(
        &self,
        source: &OriginalBFile,
        observed: &OriginalBFile,
        policy: &OriginalBFile,
        registered_at: u64,
        now: u64,
    ) -> io::Result<OriginalHoldoutSourceData> {
        let bytes = source.read_stable(1_048_576)?;
        let data = OriginalHoldoutSourceData::decode(&bytes)?;
        let payload = [
            b"hepta.root.independent-b.observed-source.v1\0".as_slice(),
            Digest32::of_bytes(&bytes).as_array(),
        ]
        .concat();
        let observed =
            self.require_statement(observed, LearningEvidenceRoleV1::Observer, &payload, now)?;
        let policy = self.require_statement(
            policy,
            LearningEvidenceRoleV1::Generator,
            &data.policy_payload()?,
            now,
        )?;
        data.require_original_times(registered_at, policy.issued_at, observed.issued_at, now)?;
        if data.objective != self.verifier.objective_digest().into_array()
            || source.read_stable(1_048_576)? != bytes
        {
            return Err(io::Error::other(
                "original B source changed during admission",
            ));
        }
        Ok(data)
    }
}
