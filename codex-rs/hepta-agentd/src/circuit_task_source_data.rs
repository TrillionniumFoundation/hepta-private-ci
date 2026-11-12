//! Canonical original publication data for the complete Root historical lane.
//! Decoding supplies no custody, currentness, Dataset or learning authority.

use base64::Engine;
use base64::engine::general_purpose::STANDARD;
use codex_hepta_neuron::CellDecisionReceiptV1;
use serde::Deserialize;
use serde::Serialize;

use super::*;
use crate::root_historical_ledger_data::RootHistoricalLedgerReadDataV1;

#[path = "circuit_task_source_data_decision.rs"]
mod decision;

const PURPOSE: &str = "runtime.learning.historical-task-publication-data.v1";
const DATA_BOUND: usize = 16_384;

/// Exact canonical request/result bytes, projected only from the Root's actual
/// observation in production. Raw deserialization alone grants no read right.
#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct RootHistoricalTaskPublicationDataV1 {
    schema: u8,
    purpose: String,
    source_configuration: String,
    request: String,
    result: String,
    publication: String,
}

impl RootHistoricalTaskPublicationDataV1 {
    /// Pure canonical data projection for the same-Root successor receipt.
    /// The closed actual client separately supplies current admission/custody.
    pub(crate) fn decode_original_successor_data(
        &self,
    ) -> Result<(CircuitTaskSourcePublicationV1, CellDecisionReceiptV1), Error> {
        self.decode_data()
    }

    pub(crate) fn from_original_observation(
        observed: &HistoricalCircuitTaskSourceObservationV1,
        cell: &CellDecisionReceiptV1,
    ) -> Result<Self, Error> {
        let publication = observed.publication();
        publication.require_decision(cell)?;
        let record = publication.original_record();
        let source = observed.original_source();
        let request = CircuitTaskRequestV1 {
            start: CircuitStartV2 {
                run_id: record.snapshot.run_id.to_string(),
                scope_digest: circuit_cell_scope_digest_v1(&source.scope)?,
                input_digest: Sha256Digest::for_bytes(&source.observation),
                created_at_ms: record.admission.observed_at_unix_micros / 1_000,
                lease_duration_ms: source.lease_duration_ms,
            },
            objective_digest: source.objective_digest,
            deadline_ms: (record.admission.deadline_unix_micros / 1_000)
                .min(record.authentication.expires_at_ms),
        };
        request.validate_record(record, observed.original_fence().generation)?;
        let data = Self {
            schema: 1,
            purpose: PURPOSE.into(),
            source_configuration: observed.binding_digest().to_string(),
            request: STANDARD.encode(super::request(&request, record)?),
            result: STANDARD.encode(publication.result_bytes()),
            publication: publication.publication_digest().to_string(),
        };
        let decoded = data.decode_data()?;
        if decoded != (publication.clone(), cell.clone()) {
            return Err(Error::InvalidBinding);
        }
        Ok(data)
    }

    /// The only inputs are data. The opaque same-Root client still has to
    /// observe the complete physical task before exposing either value.
    pub(crate) fn validate_against(
        &self,
        ledger: &RootHistoricalLedgerReadDataV1,
    ) -> Result<(CircuitTaskSourcePublicationV1, CellDecisionReceiptV1), Error> {
        ledger.validate_data().map_err(|_| Error::InvalidBinding)?;
        let (publication, cell) = self.decode_data()?;
        let scope = ledger.target.scope();
        let input = publication.input();
        let decision = Digest32::of_parts(&[
            b"hepta.root.original-ledger-cell-decision.v1\0",
            &crate::circuit_cell_output::encode_receipt(&cell)?,
            &json(&(
                &cell.representation.drive_q24,
                &cell.representation.prediction_q24,
            ))?,
        ]);
        if self.source_configuration != ledger.source.configuration
            || self.publication != ledger.source.publication
            || self.publication != ledger.cut.source_publication
            || publication.history_digest().as_str() != ledger.source.completed_task
            || decision.to_string() != ledger.cut.cell_decision
            || input.scope.agent_id.as_str() != scope.agent_id
            || input.scope.cell_id.as_str() != scope.cell_id
            || input.scope.run_id.as_str() != scope.run_id
            || input.scope.principal_digest.into_array() != scope.principal_digest
            || input.source_frontier.into_array() != ledger.target.source_frontier()
            || input.objective_digest.to_string() != ledger.trust.objective
        {
            return Err(Error::InvalidBinding);
        }
        Ok((publication, cell))
    }

    fn decode_data(
        &self,
    ) -> Result<(CircuitTaskSourcePublicationV1, CellDecisionReceiptV1), Error> {
        if self.schema != 1 || self.purpose != PURPOSE || json(self)?.len() > DATA_BOUND {
            return Err(Error::InvalidBinding);
        }
        let binding = self
            .source_configuration
            .parse::<Digest32>()
            .map_err(|_| Error::InvalidBinding)?;
        if binding.is_zero() || binding.to_string() != self.source_configuration {
            return Err(Error::InvalidBinding);
        }
        let request_bytes = STANDARD
            .decode(&self.request)
            .map_err(|_| Error::InvalidBinding)?;
        let result_bytes = STANDARD
            .decode(&self.result)
            .map_err(|_| Error::InvalidBinding)?;
        bounded(&request_bytes)?;
        bounded(&result_bytes)?;
        if STANDARD.encode(&request_bytes) != self.request
            || STANDARD.encode(&result_bytes) != self.result
        {
            return Err(Error::InvalidBinding);
        }
        let record = original_record(&request_bytes)?;
        let mut request_reader = Reader::new(&request_bytes, b"HCSTREQ1")?;
        let (start, objective, deadline_ms): (CircuitStartV2, String, u64) =
            serde_json::from_slice(request_reader.blob()?).map_err(|_| Error::InvalidBinding)?;
        let request = CircuitTaskRequestV1 {
            start,
            objective_digest: objective.parse().map_err(|_| Error::InvalidBinding)?,
            deadline_ms,
        };
        request.validate_record(&record, record.snapshot.generation)?;
        if super::request(&request, &record)? != request_bytes {
            return Err(Error::InvalidBinding);
        }
        let mut result = Reader::new(&result_bytes, b"HCSTRES1")?;
        let saved_input = result.blob()?;
        let input = decode_input(saved_input)?;
        let (history_digest, output) = publication(&result_bytes, saved_input)?;
        for _ in 0..3 {
            result.blob()?;
        }
        let cell = decision::decode_original_decision(result.blob()?, result.blob()?)?;
        result.end()?;
        if input.scope != cell.scope
            || input.operation_id != cell.operation_id
            || input.source_frontier != cell.source_frontier
            || input.scope.run_id != record.snapshot.run_id
            || input.objective_digest != request.objective_digest
            || request.start.scope_digest != circuit_cell_scope_digest_v1(&input.scope)?
            || request.start.input_digest != Sha256Digest::for_bytes(&input.observation)
            || output != crate::circuit_cell_output::encode_output(&cell)?
        {
            return Err(Error::InvalidBinding);
        }
        let publication_digest = Digest32::of_parts(&[
            b"hepta.circuit.original-source-publication.v1\0",
            binding.as_array(),
            &request_bytes,
            saved_input,
            &result_bytes,
        ]);
        if publication_digest.to_string() != self.publication {
            return Err(Error::InvalidBinding);
        }
        let publication = CircuitTaskSourcePublicationV1 {
            record,
            input,
            output,
            history_digest,
            publication_digest,
            bundle_digest: cell.bundle_digest,
            checkpoint_digest: cell.checkpoint_after,
            result_bytes,
        };
        publication.require_decision(&cell)?;
        Ok((publication, cell))
    }
}
