//! A target-validated retirement ACK retained by the original source owner.
//! Public callers cannot construct or deserialize this observation.

use super::*;

#[derive(Clone, Debug)]
pub struct ProductionRetirementAck {
    record: RecordedRetirementAck,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct RecordedRetirementAck {
    pub(crate) schema_version: u16,
    pub(crate) lease_id: String,
    pub(crate) operation_id: String,
    pub(crate) destination_id: String,
    pub(crate) topic: String,
    pub(crate) payload_sha256: Sha256Digest,
    pub(crate) terminal_receipt_sha256: Sha256Digest,
}

impl ProductionRetirementAck {
    /// Called only after the original application adapter validated an actual
    /// ACK, or its exact process-local already-validated ACK cache.
    pub(crate) fn from_validated_target(
        request: &ProductionDispatchRequest,
        terminal: &str,
    ) -> Result<Self, String> {
        if !matches!(
            request.topic.as_str(),
            crate::NOTES_REPLACE_TOPIC_V1 | crate::CALCULATOR_EVALUATE_TOPIC_V1
        ) || request.payload_sha256 != Sha256Digest::for_bytes(request.payload_json.as_bytes())
        {
            return Err("retirement ACK has invalid original application binding".into());
        }
        Ok(Self {
            record: RecordedRetirementAck {
                schema_version: 1,
                lease_id: request.lease_id.clone(),
                operation_id: request.occurrence_key.clone(),
                destination_id: request.operation_destination_id.clone(),
                topic: request.topic.clone(),
                payload_sha256: request.payload_sha256.clone(),
                terminal_receipt_sha256: Sha256Digest::for_bytes(terminal.as_bytes()),
            },
        })
    }

    pub(crate) fn matches(
        &self,
        request: &ProductionDispatchRequest,
        terminal: &str,
    ) -> Result<(), ProductionWriterError> {
        let expected = RecordedRetirementAck {
            schema_version: 1,
            lease_id: request.lease_id.clone(),
            operation_id: request.occurrence_key.clone(),
            destination_id: request.operation_destination_id.clone(),
            topic: request.topic.clone(),
            payload_sha256: request.payload_sha256.clone(),
            terminal_receipt_sha256: Sha256Digest::for_bytes(terminal.as_bytes()),
        };
        if self.record != expected
            || request.payload_sha256 != Sha256Digest::for_bytes(request.payload_json.as_bytes())
        {
            return Err(ProductionWriterError::Invalid(
                "target retirement ACK changed its original operation".into(),
            ));
        }

        Ok(())
    }
}
