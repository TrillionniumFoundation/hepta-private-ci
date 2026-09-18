//! Snapshot digesting and closed-world registry integrity validation.

use std::collections::BTreeMap;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::model::Error;
use crate::model::FactorSource;
use crate::model::Lifecycle;
use crate::model::LifecycleEventKind;
use crate::model::lifecycle_code;
use crate::model::push_id;
use crate::registry::MAX_LIFECYCLE_EVENTS;
use crate::registry::MAX_RECORDS;
use crate::registry::PromptRegistry;
use crate::v2;

impl PromptRegistry {
    pub fn snapshot_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(b"hepta.prompt-registry.snapshot.v2");
        bytes.extend_from_slice(&self.revision.get().to_be_bytes());
        bytes.extend_from_slice(&self.lifecycle_frontier.to_be_bytes());
        bytes.extend_from_slice(&self.revocation_frontier.to_be_bytes());
        for factor in self.factors.values() {
            push_id(&mut bytes, &factor.factor_id);
            push_id(&mut bytes, &factor.proposer_id);
            push_id(&mut bytes, &factor.semantic_version);
            bytes.extend_from_slice(factor.content_digest.as_array());
            bytes.push(match factor.source {
                FactorSource::GovernedInternal => 0,
                FactorSource::ExternalUntrusted => 1,
            });
            bytes.push(lifecycle_code(factor.lifecycle));
        }
        for admission in self.admissions.values() {
            bytes.extend_from_slice(admission.admission_digest.as_array());
        }
        for event in &self.lifecycle_history {
            bytes.extend_from_slice(event.event_digest.as_array());
        }
        for realization in self.realizations.values() {
            push_id(&mut bytes, &realization.realization_id);
            push_id(&mut bytes, &realization.factor_id);
            bytes.extend_from_slice(realization.model_digest.as_array());
            bytes.extend_from_slice(realization.tokenizer_digest.as_array());
            bytes.extend_from_slice(realization.content_digest.as_array());
            bytes.push(u8::from(realization.active));
            if let Some(revision) = self.realization_revisions.get(&realization.realization_id) {
                bytes.extend_from_slice(&revision.get().to_be_bytes());
            }
        }
        for binding in self.realization_bindings.values() {
            bytes.extend_from_slice(binding.digest().as_array());
        }
        Digest32::of_bytes(&bytes)
    }

    pub(crate) fn validate_integrity(&self) -> Result<(), Error> {
        if self.maximum_records == 0 || self.maximum_records > MAX_RECORDS {
            return Err(Error::IntegrityMismatch("capacity"));
        }
        if self.factors.len().saturating_add(self.realizations.len()) > self.maximum_records {
            return Err(Error::CapacityExceeded);
        }
        if self.lifecycle_history.len() > MAX_LIFECYCLE_EVENTS {
            return Err(Error::LifecycleHistoryCapacityExceeded);
        }
        if self.revocation_frontier > self.lifecycle_frontier
            || self.lifecycle_frontier > self.revision.get()
        {
            return Err(Error::IntegrityMismatch("frontier"));
        }
        let has_mutation = !self.factors.is_empty() || !self.realizations.is_empty();
        if has_mutation && self.lifecycle_frontier != self.revision.get() {
            return Err(Error::IntegrityMismatch("lifecycle frontier"));
        }
        if !has_mutation && self.lifecycle_frontier != 0 {
            return Err(Error::IntegrityMismatch("empty lifecycle frontier"));
        }

        let mut replay = BTreeMap::<StableId, Lifecycle>::new();
        let mut previous_revision = 0_u64;
        for event in &self.lifecycle_history {
            event.validate()?;
            if event.revision.get() <= previous_revision
                || event.revision.get() > self.revision.get()
            {
                return Err(Error::IntegrityMismatch("lifecycle ordering"));
            }
            previous_revision = event.revision.get();
            match event.kind {
                LifecycleEventKind::Registered => {
                    let proposer_matches = self
                        .factors
                        .get(&event.factor_id)
                        .is_some_and(|factor| factor.proposer_id == event.actor_id);
                    if event.from.is_some()
                        || event.to != Lifecycle::Draft
                        || !proposer_matches
                        || event.evidence_digest.is_some()
                        || event.reviewed_scope_digest.is_some()
                        || event.reason_digest.is_some()
                        || event.cutoff_unix_ms.is_some()
                        || replay
                            .insert(event.factor_id.clone(), Lifecycle::Draft)
                            .is_some()
                    {
                        return Err(Error::IntegrityMismatch("registered lifecycle event"));
                    }
                }
                LifecycleEventKind::Admitted => {
                    if event.from != Some(Lifecycle::Draft)
                        || event.to != Lifecycle::Admitted
                        || event.evidence_digest.is_none()
                        || event.reviewed_scope_digest.is_none()
                        || event.reason_digest.is_some()
                        || event.cutoff_unix_ms.is_some()
                        || replay.get(&event.factor_id) != Some(&Lifecycle::Draft)
                    {
                        return Err(Error::IntegrityMismatch("admitted lifecycle event"));
                    }
                    replay.insert(event.factor_id.clone(), Lifecycle::Admitted);
                }
                LifecycleEventKind::Retired => {
                    if event.from != Some(Lifecycle::Admitted)
                        || event.to != Lifecycle::Retired
                        || event.reason_digest.is_none()
                        || event.cutoff_unix_ms.is_some()
                        || replay.get(&event.factor_id) != Some(&Lifecycle::Admitted)
                    {
                        return Err(Error::IntegrityMismatch("retired lifecycle event"));
                    }
                    replay.insert(event.factor_id.clone(), Lifecycle::Retired);
                }
                LifecycleEventKind::Revoked => {
                    let Some(current) = replay.get(&event.factor_id).copied() else {
                        return Err(Error::IntegrityMismatch("revoked lifecycle event"));
                    };
                    if !matches!(current, Lifecycle::Admitted | Lifecycle::Retired)
                        || event.from != Some(current)
                        || event.to != Lifecycle::Revoked
                        || event.reason_digest.is_none()
                        || event.cutoff_unix_ms.is_none_or(|value| value == 0)
                    {
                        return Err(Error::IntegrityMismatch("revoked lifecycle event"));
                    }
                    replay.insert(event.factor_id.clone(), Lifecycle::Revoked);
                }
            }
        }
        if replay.len() != self.factors.len() {
            return Err(Error::IntegrityMismatch("factor lifecycle coverage"));
        }
        for (factor_id, factor) in &self.factors {
            if replay.get(factor_id) != Some(&factor.lifecycle) {
                return Err(Error::IntegrityMismatch("factor lifecycle replay"));
            }
        }

        let expected_revocation_frontier = self
            .lifecycle_history
            .iter()
            .filter(|event| event.kind == LifecycleEventKind::Revoked)
            .map(|event| event.revision.get())
            .max()
            .unwrap_or(0);
        if self.revocation_frontier != expected_revocation_frontier {
            return Err(Error::IntegrityMismatch("revocation frontier"));
        }

        for admission in self.admissions.values() {
            admission.validate()?;
            let Some(factor) = self.factors.get(&admission.factor_id) else {
                return Err(Error::IntegrityMismatch("admission factor"));
            };
            if matches!(factor.lifecycle, Lifecycle::Draft)
                || factor.source != FactorSource::GovernedInternal
                || factor.proposer_id == admission.reviewer_id
            {
                return Err(Error::IntegrityMismatch("invalid admission"));
            }
            let admitted_event = self.lifecycle_history.iter().find(|event| {
                event.factor_id == admission.factor_id
                    && event.kind == LifecycleEventKind::Admitted
                    && event.revision == admission.revision
            });
            if admitted_event.is_none_or(|event| {
                event.actor_id != admission.reviewer_id
                    || event.evidence_digest != Some(admission.evidence_digest)
                    || event.reviewed_scope_digest != Some(admission.reviewed_scope_digest)
            }) {
                return Err(Error::IntegrityMismatch("admission lineage"));
            }
        }
        for factor in self.factors.values() {
            if factor.lifecycle != Lifecycle::Draft
                && !self.admissions.contains_key(&factor.factor_id)
            {
                return Err(Error::IntegrityMismatch("missing admission"));
            }
        }

        let total_payload_bytes = self
            .realization_payloads
            .values()
            .try_fold(0_usize, |total, payload| total.checked_add(payload.len()))
            .ok_or(Error::PayloadCapacityExceeded)?;
        if total_payload_bytes > v2::MAX_TOTAL_REALIZATION_PAYLOAD_BYTES {
            return Err(Error::PayloadCapacityExceeded);
        }
        for (realization_id, realization) in &self.realizations {
            if !self.realization_revisions.contains_key(realization_id) {
                return Err(Error::IntegrityMismatch("realization revision"));
            }
            if !self.factors.contains_key(&realization.factor_id) {
                return Err(Error::IntegrityMismatch("realization factor"));
            }
        }
        if self.realization_revisions.len() != self.realizations.len() {
            return Err(Error::IntegrityMismatch("orphan realization revision"));
        }
        for realization_id in self.realization_payloads.keys() {
            if !self.realization_bindings.contains_key(realization_id) {
                return Err(Error::IntegrityMismatch("orphan payload"));
            }
        }
        for (realization_id, binding) in &self.realization_bindings {
            binding
                .validate()
                .map_err(|_| Error::IntegrityMismatch("binding"))?;
            let Some(legacy) = self.realizations.get(realization_id) else {
                return Err(Error::IntegrityMismatch("binding realization"));
            };
            if legacy.factor_id != binding.factor_id
                || legacy.model_digest != binding.model_digest
                || legacy.tokenizer_digest != binding.tokenizer_digest
                || legacy.content_digest != binding.payload_digest
            {
                return Err(Error::IntegrityMismatch("binding legacy"));
            }
            let Some(payload) = self.realization_payloads.get(realization_id) else {
                return Err(Error::PayloadMissing(realization_id.to_string()));
            };
            if payload.is_empty()
                || payload.len() > v2::MAX_REALIZATION_PAYLOAD_BYTES
                || Digest32::of_bytes(payload) != binding.payload_digest
            {
                return Err(Error::PayloadDigestMismatch);
            }
        }
        v2::validate_active_uniqueness(self)?;
        Ok(())
    }
}
