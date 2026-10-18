//! Bounded original G/O publication for a no-custody Evaluator. Decoding stays
//! crate-private; an independent review cannot mint a product qualification.
use crate::recorded_publication::archive::codec::Reader;
use crate::recorded_publication::archive::codec::Wire;
use crate::recorded_publication::archive::codec::Writer;
use crate::recorded_publication::archive::codec::structure;
use crate::recorded_publication::archive::codec::{self};
use crate::*;
use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::ReviewTrustWireV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;

pub(crate) const MAX_REVIEW_PUBLICATION_BYTES: u64 = 128 * 1024 * 1024;
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Publication {
    pub(crate) schema: String,
    plan_inputs_hex: String,
    registration_hex: String,
    holdout_receipt_hex: String,
    observations_hex: String,
    execution_digest: String,
    pub(crate) trust: ReviewTrustWireV1,
}

pub(super) struct Registration {
    pub binding: ProductRegistrationBindingV1,
    pub generator: codex_hepta_learning_ledger::SignedLearningEvidenceV1,
    pub observer: codex_hepta_learning_ledger::SignedLearningEvidenceV1,
}
structure!(Registration {
    binding,
    generator,
    observer
});
structure!(ProductRegistrationBindingV1 {
    registration_digest,
    source_graph_digest,
    deployed_baseline_digest,
    objective_digest,
    dataset_digest,
    plan_digest,
    final_holdout_digest,
    registered_at_unix_micros
});
structure!(FinalHoldoutJournalReceiptV1 {
    disposition,
    sequence,
    record_digest,
    head_digest,
    use_receipt,
    authority
});

/// Publish the original owner's already-sealed execution and the feature-only
/// inputs from which each independent recipient recomputes its graph and plan.
/// No private gold, custody descriptor or signing key is transferred.
pub fn encode_paired_review_publication_v1(
    source: &PairedReviewSourcePlanV1,
    execution: &ProductPairedEvaluationReceiptV1,
    trust: &ReviewTrustWireV1,
) -> Result<Vec<u8>, PairedSupervisedErrorV1> {
    execution.validate()?;
    if source.freeze()? != execution.registration.plan {
        return Err(PairedSupervisedErrorV1::Binding(
            "original review source inputs",
        ));
    }
    let registration = Registration {
        binding: execution.registration.binding.clone(),
        generator: execution.registration.generator_evidence.clone(),
        observer: execution.registration.observer_evidence.clone(),
    };
    let bytes = serde_json::to_vec(&serde_json::json!({
        "schema":"hepta.eval.paired-supervised.review-publication.v1",
        "plan_inputs_hex":hex(&source.encode()?),
        "registration_hex":hex(&encode(&registration)?),
        "holdout_receipt_hex":hex(&encode(&execution.holdout)?),
        "observations_hex":hex(&encode_signed_paired_observation_transport_v1(&execution.observations)?),
        "execution_digest":execution.execution_digest.to_string(),
        "trust":trust,
    })).map_err(|_|invalid())?;
    if bytes.len() as u64 > MAX_REVIEW_PUBLICATION_BYTES {
        return Err(invalid());
    }
    Ok(bytes)
}

impl Publication {
    pub(crate) fn read(bytes: &[u8]) -> Result<Self, PairedSupervisedErrorV1> {
        if bytes.len() as u64 > MAX_REVIEW_PUBLICATION_BYTES {
            return Err(invalid());
        }
        let value: Self = serde_json::from_slice(bytes).map_err(|_| invalid())?;
        if value.schema != "hepta.eval.paired-supervised.review-publication.v1" {
            return Err(invalid());
        }
        Ok(value)
    }
    pub(crate) fn recompute(
        &self,
        trust: &ActivatedLearningTrustV1,
        now: u64,
    ) -> Result<ProductPairedEvaluationReceiptV1, PairedSupervisedErrorV1> {
        trust.revalidate_at(now).map_err(|_| invalid())?;
        let source =
            PairedReviewSourcePlanV1::decode(&unhex(&self.plan_inputs_hex, codec::MAX_BYTES)?)?;
        let plan = source.freeze()?;
        let original: Registration = decode(&unhex(&self.registration_hex, 16 * 1024)?)?;
        let registration = AuthenticatedPairedRegistrationV1::verify(
            &plan,
            original.binding,
            &original.generator,
            &original.observer,
            trust.verifier(),
            now,
        )?;
        let holdout: FinalHoldoutJournalReceiptV1 =
            decode(&unhex(&self.holdout_receipt_hex, 16 * 1024)?)?;
        let observations = crate::paired_observer_transport::decode_transport(&unhex(
            &self.observations_hex,
            crate::paired_observer_transport::MAX_TRANSPORT_BYTES as usize,
        )?)?;
        let execution = crate::paired_supervised_runner::review_execution(
            registration,
            holdout,
            observations,
            trust.verifier(),
            now,
        )?;
        if execution.execution_digest
            != self
                .execution_digest
                .parse::<Digest32>()
                .map_err(|_| invalid())?
        {
            return Err(invalid());
        }
        Ok(execution)
    }
}

pub(super) fn encode<T: Wire>(value: &T) -> codec::Result<Vec<u8>> {
    let mut output = Writer::default();
    value.write(&mut output)?;
    Ok(output.finish())
}
pub(super) fn decode<T: Wire>(bytes: &[u8]) -> codec::Result<T> {
    let mut input = Reader::new(bytes)?;
    let value = T::read(&mut input)?;
    input.finish()?;
    if encode(&value)? != bytes {
        return Err(codec::invalid());
    }
    Ok(value)
}
fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}
fn unhex(text: &str, maximum: usize) -> Result<Vec<u8>, PairedSupervisedErrorV1> {
    if text.len() > maximum * 2 {
        return Err(invalid());
    }
    codex_hepta_learning_ledger::decode_review_payload_hex(text).map_err(|_| invalid())
}
fn invalid() -> PairedSupervisedErrorV1 {
    PairedSupervisedErrorV1::Binding("original paired review publication")
}

#[cfg(test)]
#[path = "paired_review_transport_tests.rs"]
mod tests;
