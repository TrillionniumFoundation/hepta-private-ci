//! V2 separates durable owner custody from one actual live Root admission.
//! Both descriptions are data; neither can construct an owner or a writer.

use codex_hepta_types::Generation;

use super::*;

pub(crate) const PURPOSE_V2: &str = "runtime.learning.q24-model-proposal.factory.v2";

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct DurableQ24ModelFactoryProfileV2 {
    schema_version: u32,
    purpose: String,
    backend: Backend,
    operation_id: String,
    initial_head: String,
    scope_binding: String,
    proposal_owner_id: String,
    journal_slot_binding: String,
    witness_enrollment_binding: String,
    local_policy_digest: String,
    registry_epoch: u64,
    expiry_unix_seconds: u64,
    witness_generation: u64,
    reservation_binding: String,
    journal: FilePin,
    witness: FilePin,
    witness_domain: String,
}

impl DurableQ24ModelFactoryProfileV2 {
    pub(crate) fn reserve_description(
        initial: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
        journal: FilePin,
        witness: FilePin,
        witness_domain: Digest32,
        local_policy: Digest32,
        generation: Generation,
    ) -> io::Result<Self> {
        scope.validate_snapshot(initial).map_err(io::Error::other)?;
        if journal == witness || witness_domain.is_zero() || local_policy.is_zero() {
            return Err(io::Error::other(
                "distinct original V2 owner custody required",
            ));
        }
        let mut profile = Self {
            schema_version: 2,
            purpose: PURPOSE_V2.into(),
            backend: Backend::Q24SingleHeadSgdV1,
            operation_id: initial.request.operation_id.to_string(),
            initial_head: initial.head_digest.to_string(),
            scope_binding: scope.binding().to_string(),
            proposal_owner_id: initial.owners.proposal.to_string(),
            journal_slot_binding: journal
                .digest(b"hepta.root.q24-proposal-slot.v2\0", initial.head_digest)
                .to_string(),
            witness_enrollment_binding: Digest32::of_parts(&[
                b"hepta.root.q24-proposal-witness.v2\0",
                witness.digest(b"file\0", initial.head_digest).as_array(),
                witness_domain.as_array(),
                &generation.get().to_be_bytes(),
            ])
            .to_string(),
            local_policy_digest: local_policy.to_string(),
            registry_epoch: 1,
            expiry_unix_seconds: initial.request.envelope.expiry_unix_seconds,
            witness_generation: generation.get(),
            reservation_binding: String::new(),
            journal,
            witness,
            witness_domain: witness_domain.to_string(),
        };
        profile.reservation_binding = profile.canonical_reservation_binding()?.to_string();
        Ok(profile)
    }

    fn canonical_reservation_binding(&self) -> io::Result<Digest32> {
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
            &self.journal_slot_binding,
            &self.witness_enrollment_binding,
            &self.local_policy_digest,
        ] {
            bytes.extend_from_slice(canonical_digest(value)?.as_array());
        }
        bytes.extend_from_slice(&self.registry_epoch.to_be_bytes());
        bytes.extend_from_slice(&self.expiry_unix_seconds.to_be_bytes());
        bytes.extend_from_slice(&self.witness_generation.to_be_bytes());
        Ok(Digest32::of_parts(&[
            b"hepta.root.learning.q24-model-proposal.reservation.v2\0",
            &bytes,
        ]))
    }

    pub(crate) fn require_reserved_context(
        &self,
        initial: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
        journal: FilePin,
        witness: FilePin,
        witness_domain: Digest32,
        local_policy: Digest32,
    ) -> io::Result<()> {
        let expected = Self::reserve_description(
            initial,
            scope,
            journal,
            witness,
            witness_domain,
            local_policy,
            self.original_generation()?,
        )?;
        if self != &expected {
            return Err(io::Error::other(
                "original V2 reservation or file custody differs",
            ));
        }
        Ok(())
    }

    pub(crate) fn original_generation(&self) -> io::Result<Generation> {
        Generation::new(self.witness_generation).map_err(io::Error::other)
    }

    pub(crate) fn durable_binding(&self) -> &str {
        &self.reservation_binding
    }

    pub(crate) fn expiry(&self) -> u64 {
        self.expiry_unix_seconds
    }

    pub(crate) fn require_files(&self, journal: &File, witness: &File) -> io::Result<()> {
        self.journal.require_writable(journal)?;
        self.witness.require_writable(witness)?;
        if witness.metadata()?.len() == 0 {
            return Err(io::Error::other(
                "original V2 witness is empty; recovery cannot enroll",
            ));
        }
        Ok(())
    }

    pub(crate) fn require_observers(&self, journal: &File, witness: &File) -> io::Result<()> {
        if FilePin::capture(journal)? != self.journal || FilePin::capture(witness)? != self.witness
        {
            return Err(io::Error::other("original V2 owner file identity changed"));
        }
        Ok(())
    }

    pub(crate) fn require_local_policy(&self, policy: Digest32) -> io::Result<()> {
        if policy.is_zero() || self.local_policy_digest != policy.to_string() {
            return Err(io::Error::other(
                "V2 original precommitted local policy differs",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct LiveQ24ModelFactoryProfileV2 {
    schema_version: u32,
    purpose: String,
    pub(super) reservation: DurableQ24ModelFactoryProfileV2,
    process_identity_digest: String,
    writer_proof_digest: String,
    factory_binding: String,
}

impl LiveQ24ModelFactoryProfileV2 {
    pub(crate) fn admit_current_session(
        identity: &AgentdIdentity,
        proof: &str,
        initial: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
        reservation: DurableQ24ModelFactoryProfileV2,
    ) -> io::Result<Self> {
        reservation.require_reserved_context(
            initial,
            scope,
            reservation.journal,
            reservation.witness,
            canonical_digest(&reservation.witness_domain)?,
            canonical_digest(&reservation.local_policy_digest)?,
        )?;
        let mut profile = Self {
            schema_version: 2,
            purpose: PURPOSE_V2.into(),
            reservation,
            process_identity_digest: crate::neuron_generation_process_identity_digest_v1(identity)
                .map_err(io::Error::other)?
                .to_string(),
            writer_proof_digest: canonical_digest(proof)?.to_string(),
            factory_binding: String::new(),
        };
        profile.factory_binding = profile.canonical_admission_binding()?.to_string();
        Ok(profile)
    }

    fn canonical_admission_binding(&self) -> io::Result<Digest32> {
        Ok(Digest32::of_parts(&[
            b"hepta.root.learning.q24-model-proposal.admission.v2\0",
            &self.schema_version.to_be_bytes(),
            self.purpose.as_bytes(),
            canonical_digest(self.reservation.durable_binding())?.as_array(),
            canonical_digest(&self.process_identity_digest)?.as_array(),
            canonical_digest(&self.writer_proof_digest)?.as_array(),
        ]))
    }

    pub(crate) fn require_live_context(
        &self,
        identity: &AgentdIdentity,
        proof: &str,
        initial: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
    ) -> io::Result<()> {
        let expected =
            Self::admit_current_session(identity, proof, initial, scope, self.reservation.clone())?;
        if self != &expected {
            return Err(io::Error::other("V2 factory live Root session differs"));
        }
        Ok(())
    }

    pub(crate) fn admission_binding(&self) -> &str {
        &self.factory_binding
    }
}

fn canonical_digest(text: &str) -> io::Result<Digest32> {
    let value = text.parse::<Digest32>().map_err(io::Error::other)?;
    if value.is_zero() || value.to_string() != text {
        return Err(io::Error::other("noncanonical V2 factory digest"));
    }
    Ok(value)
}

#[cfg(test)]
#[path = "authority_host_q24_model_profile_v2_tests.rs"]
mod tests;
