//! Receipt preflight and prepared credential transport have one original budget.
use super::ConsumerPortClient;
use super::ConsumerPortError;
use super::PreparedConnection;
use super::consumer_wire::ConsumerRequest;
use super::consumer_wire::ConsumerResponse;
use crate::BaoPreparedConsumerCallback;
use crate::BaoSecretReceipt;
use codex_hepta_types::Digest32;
use std::time::Duration;
use std::time::Instant;

impl ConsumerPortClient {
    pub(super) fn prepare_receipt(
        &self,
        operation_id: &str,
        semantic: [u8; 32],
        receipt: &BaoSecretReceipt,
    ) -> Result<BaoPreparedConsumerCallback, ConsumerPortError> {
        let intent = self.intent(operation_id, semantic)?;
        if receipt.secret_sha256 != self.config.credential_reference_sha256 {
            return Err(ConsumerPortError::Rejected);
        }
        let deadline = self
            .operation_deadlines
            .lock()
            .map_err(|_| ConsumerPortError::Unavailable)?
            .get(operation_id)
            .copied()
            .ok_or(ConsumerPortError::Unavailable)?;
        let remaining = deadline
            .checked_duration_since(Instant::now())
            .ok_or(ConsumerPortError::Unavailable)?;
        let preflight = PreparedConnection::connect(
            &self.config.socket_path,
            self.config.service_uid,
            remaining.min(Duration::from_millis(self.config.timeout_ms)),
        )?;
        let lifetime_limit_ms = u64::try_from(
            deadline
                .checked_duration_since(Instant::now())
                .ok_or(ConsumerPortError::Unavailable)?
                .as_millis(),
        )
        .map_err(|_| ConsumerPortError::Unavailable)?;
        let token = match preflight.exchange(&ConsumerRequest::PrepareReceipt {
            intent: intent.clone(),
            receipt: receipt.clone(),
            lifetime_limit_ms,
        })? {
            ConsumerResponse::Prepared { token } => token,
            ConsumerResponse::Conflict => return Err(ConsumerPortError::Conflict),
            ConsumerResponse::Rejected => return Err(ConsumerPortError::Rejected),
            ConsumerResponse::Unknown
            | ConsumerResponse::Confirmed { .. }
            | ConsumerResponse::Settlement { .. } => return Err(ConsumerPortError::Unavailable),
        };
        token.verify(&self.config.acknowledgement_verifying_key)?;
        if token.preparation.intent != intent || token.preparation.receipt != *receipt {
            return Err(ConsumerPortError::Conflict);
        }
        let remaining = deadline
            .checked_duration_since(Instant::now())
            .ok_or(ConsumerPortError::Unavailable)?;
        // All IPC above is before final-use entry. This new descriptor is also
        // connected and kernel-peer checked before the one-shot callback escapes.
        let connection = PreparedConnection::connect(
            &self.config.socket_path,
            self.config.service_uid,
            remaining.min(Duration::from_millis(self.config.timeout_ms)),
        )?;
        let ack_key = self.config.acknowledgement_verifying_key;
        let credential_digest = self.config.credential_reference_sha256;
        Ok(Box::new(move |credential| {
            if Instant::now() >= deadline
                || Digest32::of_bytes(credential).into_array() != credential_digest
            {
                return Err(());
            }
            let proof = token.preparation.proof(credential).map_err(|_| ())?;
            let response = connection
                .exchange(&ConsumerRequest::AuthenticatePrepared { token, proof })
                .map_err(|_| ())?;
            match response {
                ConsumerResponse::Confirmed { receipt } => {
                    receipt.verify(&intent, &ack_key).map_err(|_| ())
                }
                ConsumerResponse::Prepared { .. }
                | ConsumerResponse::Settlement { .. }
                | ConsumerResponse::Unknown
                | ConsumerResponse::Rejected
                | ConsumerResponse::Conflict => Err(()),
            }
        }))
    }
}
