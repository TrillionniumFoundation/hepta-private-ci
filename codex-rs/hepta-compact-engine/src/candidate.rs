//! Structural candidate validation; source authentication belongs to the owner.

use super::*;

impl QualifiedCompactionCandidateV2 {
    /// Verifies bounded, internally consistent partitions and checkpoint bindings.
    /// This does not authenticate a snapshot, policy or evaluation observation.
    pub fn validate(&self) -> Result<(), QualifiedCompactionError> {
        let total = self
            .retained_records
            .len()
            .checked_add(self.omitted_record_digests.len())
            .and_then(|count| count.checked_add(self.deleted_record_digests.len()))
            .ok_or(QualifiedCompactionError::InputLimitExceeded)?;
        if total > MAX_QUALIFIED_COMPACTION_INPUTS {
            return Err(QualifiedCompactionError::InputLimitExceeded);
        }
        let digest_references = self
            .omitted_record_digests
            .len()
            .checked_add(self.deleted_record_digests.len())
            .ok_or(QualifiedCompactionError::InputLimitExceeded)?;
        preflight_records(&self.retained_records, digest_references)
            .map_err(QualifiedCompactionError::ResourceBudgetExceeded)?;
        self.source_snapshot
            .validate()
            .map_err(QualifiedCompactionError::Contract)?;
        ensure_digest("policy", self.policy_digest)?;
        ensure_digest("selection_input", self.selection_input_digest)?;
        self.checkpoint
            .validate()
            .map_err(QualifiedCompactionError::Contract)?;
        self.loss_report.validate()?;
        if self.checkpoint.source_snapshot != self.source_snapshot {
            return Err(QualifiedCompactionError::SnapshotMismatch);
        }
        if self.checkpoint.tombstone_cutoff != self.source_snapshot.vector.tombstone_frontier {
            return Err(QualifiedCompactionError::TombstoneCutoffMismatch);
        }
        let expected_id = format!(
            "compact:{}:{}",
            self.checkpoint.generation.get(),
            self.source_snapshot.vector_digest
        );
        if self.checkpoint.checkpoint_id.as_str() != expected_id {
            return Err(QualifiedCompactionError::InvalidCheckpointIdentity);
        }
        if self.authority.grants_any() {
            return Err(QualifiedCompactionError::AuthorityGranted);
        }
        if self.loss_report.retained_records != self.retained_records.len() as u64
            || self.loss_report.omitted_live_records != self.omitted_record_digests.len() as u64
            || self.loss_report.deleted_records != self.deleted_record_digests.len() as u64
        {
            return Err(QualifiedCompactionError::InvalidLossAccounting);
        }
        let mut identities = BTreeSet::new();
        let mut heads = BTreeSet::new();
        let mut payload = Vec::with_capacity(self.retained_records.len());
        for record in &self.retained_records {
            record
                .validate()
                .map_err(|error| QualifiedCompactionError::InvalidRecord(error.to_string()))?;
            if record.state != RecordState::Live {
                return Err(QualifiedCompactionError::TombstoneRetained(
                    record.record_id.to_string(),
                ));
            }
            if !identities.insert(record.record_id.clone()) {
                return Err(QualifiedCompactionError::DuplicateRetainedRecord(
                    record.record_id.to_string(),
                ));
            }
            let digest = record.record_digest();
            if !heads.insert(digest) {
                return Err(QualifiedCompactionError::DuplicateSourceDigest);
            }
            payload.push(digest);
        }
        for digest in self
            .omitted_record_digests
            .iter()
            .chain(&self.deleted_record_digests)
        {
            ensure_digest("source_head", *digest)?;
            if !heads.insert(*digest) {
                return Err(QualifiedCompactionError::DuplicateSourceDigest);
            }
        }
        if self.checkpoint.payload_digest != digest_digests(PAYLOAD_DOMAIN, &payload) {
            return Err(QualifiedCompactionError::DigestMismatch("payload"));
        }
        if self.checkpoint.omitted_information_digest
            != digest_digests(OMITTED_DOMAIN, &self.omitted_record_digests)
        {
            return Err(QualifiedCompactionError::DigestMismatch(
                "omitted_information",
            ));
        }
        let support = heads.into_iter().collect::<Vec<_>>();
        if self.checkpoint.support_manifest_digest
            != digest_digests(SUPPORT_MANIFEST_DOMAIN, &support)
        {
            return Err(QualifiedCompactionError::DigestMismatch("support_manifest"));
        }
        if self.candidate_digest != self.compute_candidate_digest() {
            return Err(QualifiedCompactionError::DigestMismatch("candidate"));
        }
        Ok(())
    }

    /// Rebuilds the deterministic candidate from the owner's frozen input and policy.
    /// The owner must authenticate those inputs before calling this method.
    pub fn validate_against_inputs(
        &self,
        policy: &CompactionPolicyV2,
        inputs: Vec<CompactionInputRecordV2>,
    ) -> Result<(), QualifiedCompactionError> {
        self.validate()?;
        let expected = build_qualified_candidate(
            self.source_snapshot.clone(),
            self.checkpoint.generation,
            self.checkpoint.predecessor_digest,
            policy,
            inputs,
        )?;
        // Record digests canonicalize citation order; equivalent citation
        // permutations must not fail the frozen-input semantic comparison.
        if self.candidate_digest != expected.candidate_digest {
            return Err(QualifiedCompactionError::CandidateSourceMismatch);
        }
        Ok(())
    }

    /// Canonical hash helper for bounded data, including construction before
    /// the candidate digest is assigned. Use `validate` as the admission boundary
    /// for imported candidates; this helper does not enforce resource limits.
    #[must_use]
    pub fn compute_candidate_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(CANDIDATE_DOMAIN);
        push_digest(&mut bytes, self.source_snapshot.vector_digest);
        push_digest(&mut bytes, self.policy_digest);
        push_digest(&mut bytes, self.selection_input_digest);
        push_digest(&mut bytes, self.checkpoint.checkpoint_digest);
        push_digest(&mut bytes, self.loss_report.loss_report_digest);
        push_len(&mut bytes, self.retained_records.len());
        for record in &self.retained_records {
            push_digest(&mut bytes, record.record_digest());
        }
        for digests in [&self.omitted_record_digests, &self.deleted_record_digests] {
            push_len(&mut bytes, digests.len());
            for digest in digests {
                push_digest(&mut bytes, *digest);
            }
        }
        Digest32::of_bytes(&bytes)
    }
}
