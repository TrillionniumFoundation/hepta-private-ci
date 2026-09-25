//! Exact historical acknowledgement recovery; never an event replay API.
//!
//! The caller retains a small identity in its existing durable intent before
//! submission. Recovery reads the authenticated owner journal, not a model or
//! a new parameter generation. A recovered receipt certifies a historical commit,
//! not current data eligibility, execution authority or external-effect success.

use super::*;

const IDENTITY_SCHEMA: &str = "hepta.learning-ledger.append-identity.v1";
const MAX_IDENTITY_BYTES: usize = 1_024;

/// Persistable non-authorizing lookup key for one signed Decision, Outcome or CreditBatch.
/// Changing the store, predecessor or signed request cannot recover another
/// operation under the same record ID. No signing key or model input is stored.
#[derive(Clone, Debug, Eq, PartialEq, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LearningAppendIdentityV1 {
    schema: String,
    ledger_binding: String,
    record_id: String,
    expected_predecessor: String,
    authentication_digest: String,
}

impl LearningAppendIdentityV1 {
    pub fn encode(&self) -> Result<Vec<u8>, ProductionLedgerError> {
        self.validate()?;
        let bytes = serde_json::to_vec(self)
            .map_err(|_| ProductionLedgerError::Binding("append identity encoding"))?;
        if bytes.len() > MAX_IDENTITY_BYTES {
            return Err(ProductionLedgerError::Binding("append identity capacity"));
        }
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, ProductionLedgerError> {
        if bytes.len() > MAX_IDENTITY_BYTES {
            return Err(ProductionLedgerError::Binding("append identity capacity"));
        }
        let identity: Self = serde_json::from_slice(bytes)
            .map_err(|_| ProductionLedgerError::Binding("append identity encoding"))?;
        identity.validate()?;
        Ok(identity)
    }

    fn validate(&self) -> Result<(), ProductionLedgerError> {
        if self.schema != IDENTITY_SCHEMA {
            return Err(ProductionLedgerError::Binding("append identity schema"));
        }
        StableId::new(self.record_id.clone())
            .map_err(|_| ProductionLedgerError::Binding("append identity record"))?;
        for value in [
            &self.ledger_binding,
            &self.expected_predecessor,
            &self.authentication_digest,
        ] {
            let digest: Digest32 = value
                .parse()
                .map_err(|_| ProductionLedgerError::Binding("append identity digest"))?;
            if digest.to_string() != *value {
                return Err(ProductionLedgerError::Binding(
                    "noncanonical append identity",
                ));
            }
        }
        Ok(())
    }
}

impl LedgerWriter {
    /// Create this lookup identity before submitting the signed owner request.
    /// It is not proof that admission or a commit has happened.
    pub fn authenticated_append_identity(
        &self,
        record_id: &StableId,
        expected_predecessor: Digest32,
        evidence: &SignedLearningEvidenceV1,
    ) -> LearningAppendIdentityV1 {
        LearningAppendIdentityV1 {
            schema: IDENTITY_SCHEMA.to_owned(),
            ledger_binding: self.backend.binding().to_string(),
            record_id: record_id.to_string(),
            expected_predecessor: expected_predecessor.to_string(),
            authentication_digest: signed_evidence_digest(evidence).to_string(),
        }
    }

    /// Resolve an uncertain signed append using the recovered authoritative
    /// journal. Never inserts an event, reruns a model, or renews expired trust.
    /// A one-event-late witness is completed only for the exact committed event.
    /// `None` means absent from this recovered journal, not "no external effect";
    /// a new append still requires normal current signed admission.
    pub fn recover_authenticated_append(
        &mut self,
        identity: &LearningAppendIdentityV1,
    ) -> Result<Option<AppendReceipt>, ProductionLedgerError> {
        identity.validate()?;
        if identity.ledger_binding != self.backend.binding().to_string() {
            return Err(ProductionLedgerError::Binding("append identity ledger"));
        }
        let record_id = StableId::new(identity.record_id.clone())
            .map_err(|_| ProductionLedgerError::Binding("append identity record"))?;
        let core = self.backend.core()?;
        let ledger_frontier = self.backend.frontier()?;
        let witness_frontier = self.witness.frontier()?;
        let lag = validate_witness_state(core.records(), ledger_frontier, witness_frontier)?;
        let Some(record) = core.record_by_id(&record_id)? else {
            return Ok(None);
        };
        let authentication_digest = match &record.event {
            LedgerEvent::AuthenticatedDecisionV2(value) => value.authentication_digest,
            LedgerEvent::AuthenticatedOutcomeV2(value) => value.authentication_digest,
            LedgerEvent::CreditBatchV2(value) => value.authentication_digest,
            _ => return Err(ProductionLedgerError::Binding("append recovery event kind")),
        };
        if record.predecessor_chain_digest.to_string() != identity.expected_predecessor
            || authentication_digest.to_string() != identity.authentication_digest
        {
            return Err(ProductionLedgerError::Binding(
                "append recovery request identity",
            ));
        }
        let receipt = AppendReceipt {
            disposition: AppendDisposition::IdempotentReplay,
            sequence: record.sequence,
            event_digest: record.event_digest,
            chain_digest: record.chain_digest,
        };
        if receipt.sequence.get() > witness_frontier.anchor.sequence {
            if lag != 1
                || receipt.sequence.get() != ledger_frontier.anchor.sequence
                || receipt.chain_digest != ledger_frontier.anchor.chain_digest
            {
                return Err(ProductionLedgerError::WitnessLag);
            }
            if let Err(witness_error) = self.witness.advance(witness_frontier, ledger_frontier) {
                return Err(ProductionLedgerError::IndeterminateAfterLedgerCommit {
                    receipt,
                    witness_error,
                });
            }
        }
        Ok(Some(receipt))
    }
}
