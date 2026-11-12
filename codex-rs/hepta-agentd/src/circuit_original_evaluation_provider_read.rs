//! Current original source/ledger reads around complete cohort materialization.

use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::dataset_freeze_signing_payload_v2;
use codex_hepta_learning_ledger::verify_signed_role_separation;
use codex_hepta_types::Digest32;

use super::Error;
use super::Materialized;
use super::OriginalCircuitEvaluationCohortV1;
use super::Publications;
use super::binding;
use super::records;
use crate::CircuitTaskSourceReadbackV1;

impl OriginalCircuitEvaluationCohortV1 {
    pub(super) fn read_original_material(
        &mut self,
        started_at: u64,
        clock: &mut impl FnMut() -> Result<u64, Error>,
    ) -> Result<Materialized, Error> {
        let training = binding::authenticate_training(&self.config, started_at)?;
        if started_at < self.config.rule.evaluation_end_unix_seconds {
            return Err(Error::Binding("registered observation window is not closed"));
        }
        let before = LedgerWriter::read_current_durable_snapshot(&mut self.owners.ledger)?;
        if before.records().iter().any(|record| {
            record.event.record_id() == &self.config.training.request.source_run_id
        }) {
            // A's exact freeze is not extended with B. A real SourceBound
            // Training completion required this Decision in its original A
            // ledger, so that same ledger cannot satisfy this independent cut.
            return Err(Error::Binding("B must use an independent original ledger domain"));
        }
        let freeze_payload = dataset_freeze_signing_payload_v2(&before, &self.config.freeze_plan)?;
        let evaluator = self.config.verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            &self.config.freeze_evidence,
            &freeze_payload,
            started_at,
        )?;
        verify_signed_role_separation(&training.generator, &evaluator, started_at)?;
        let receipt = LedgerWriter::freeze_dataset(
            &self.owners.ledger,
            self.config.freeze_plan.clone(),
            &self.config.freeze_evidence,
            started_at,
        )?;
        if receipt.snapshot.ledger_head_digest != before.head_digest
            || receipt.snapshot.pending_outcomes != 0
            || receipt.snapshot.censored_outcomes != 0
            || receipt.snapshot.source_record_digests.is_empty()
            || receipt.snapshot.source_record_digests.len() > 4096
        {
            return Err(Error::Binding("complete original B freeze with terminal outcomes"));
        }
        let records = LedgerWriter::read_dataset_records(
            &self.owners.ledger,
            &receipt,
            started_at,
        )?.into_iter().cloned().collect::<Vec<_>>();
        let mut actual = records.iter().map(|record| record.event_digest).collect::<Vec<_>>();
        actual.sort_unstable();
        if actual != receipt.snapshot.source_record_digests {
            return Err(Error::Binding("exact active original B freeze source set"));
        }
        let sources = self.read_sources()?;
        let inputs = records::assemble(
            &self.config,
            &self.owners.ledger,
            &receipt,
            &records,
            &sources,
            &self.owners.sources,
            &training,
            started_at,
        )?;
        let mut provenance = b"hepta.circuit.original-evaluation-material.v1\0".to_vec();
        for digest in [
            self.rule_digest,
            self.config.registration.evaluation_profile(),
            self.config.training.head_digest,
            self.config.scope.binding(),
            self.owners.ledger.binding_digest(),
            self.owners.ledger.trust_distribution_digest(),
            before.head_digest,
            receipt.snapshot.dataset_digest,
            receipt.correction_cut_digest,
            receipt.revocation_cut_digest,
        ] {
            provenance.extend_from_slice(digest.as_array());
        }
        for evidence in [&self.config.training_evidence, &self.config.freeze_evidence] {
            let mut full = evidence.signing_bytes();
            full.extend_from_slice(&evidence.signature);
            provenance.extend_from_slice(&(full.len() as u64).to_be_bytes());
            provenance.extend_from_slice(&full);
        }
        provenance.extend_from_slice(&(sources.len() as u64).to_be_bytes());
        for (run, observed) in &sources {
            super::contract::push_id(&mut provenance, run);
            provenance.extend_from_slice(observed.publication_digest().as_array());
        }

        if self.read_sources()? != sources
            || LedgerWriter::read_current_durable_snapshot(&mut self.owners.ledger)? != before
        {
            return Err(Error::Binding("original B source or ledger CURRENT changed"));
        }
        let fresh_now = clock()?;
        if fresh_now < started_at {
            return Err(Error::Binding("system clock moved backwards"));
        }
        let training = binding::authenticate_training(&self.config, fresh_now)?;
        let evaluator = self.config.verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            &self.config.freeze_evidence,
            &freeze_payload,
            fresh_now,
        )?;
        verify_signed_role_separation(&training.generator, &evaluator, fresh_now)?;
        // Reverify the same complete freeze signature at the final wall clock.
        // Active-record lookup alone cannot replace signature-window checking.
        if LedgerWriter::freeze_dataset(
            &self.owners.ledger,
            self.config.freeze_plan.clone(),
            &self.config.freeze_evidence,
            fresh_now,
        )? != receipt {
            return Err(Error::Binding("same original signed B freeze after all I/O"));
        }
        let _ = LedgerWriter::read_dataset_records(
            &self.owners.ledger,
            &receipt,
            fresh_now,
        )?;
        self.last_observed_at = fresh_now;
        // No further file, witness or peer I/O follows fresh authentication.
        Ok(Materialized {
            manifest: Digest32::of_bytes(&provenance),
            dataset: receipt,
            inputs,
        })
    }

    fn read_sources(&self) -> Result<Publications, Error> {
        let mut observed = Publications::new();
        for original in &self.owners.sources {
            let publication = CircuitTaskSourceReadbackV1::read_run_publication(
                &original.source,
                &original.identity,
                &original.run_id,
            )?;
            if publication.input().scope.run_id != original.run_id
                || publication.original_record().snapshot.run_id != original.run_id
                || publication.input().objective_digest != self.config.rule.objective_digest
                || observed.insert(original.run_id.clone(), publication).is_some()
            {
                return Err(Error::Binding("exact original source registry"));
            }
        }
        if observed.keys().cloned().collect::<std::collections::BTreeSet<_>>()
            != self.config.rule.run_ids()
        {
            return Err(Error::Binding("complete original source registry"));
        }
        Ok(observed)
    }
}
