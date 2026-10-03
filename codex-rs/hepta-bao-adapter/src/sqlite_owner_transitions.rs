//! Existing durable owner transitions implementation.

use super::*;

impl SqliteBaoOwnerV1 {
    pub async fn mark_consumption_reserved(
        &self,
        operation_id: &str,
        expected_revision: u64,
        reservation_id: String,
        reservation_evidence_sha256: [u8; 32],
        now_unix_ms: u64,
    ) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
        validate_identifier(&reservation_id)?;
        let current = self.consumption_result(operation_id).await?;
        let mut next = current.operation;
        if next
            .reservation_id
            .as_ref()
            .is_some_and(|value| value != &reservation_id)
        {
            return Err(SqliteBaoOwnerErrorV1::OperationConflict);
        }
        next.reservation_id = Some(reservation_id);
        next.state = BaoConsumptionStateV1::Reserved;
        self.transition_consumption(
            operation_id,
            expected_revision,
            next,
            reservation_evidence_sha256,
            now_unix_ms,
        )
        .await
    }

    pub async fn mark_consumption_dispatch_fenced(
        &self,
        operation_id: &str,
        expected_revision: u64,
        dispatch_evidence_sha256: [u8; 32],
        now_unix_ms: u64,
    ) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
        let current = self.consumption_result(operation_id).await?;
        let mut next = current.operation;
        if next.reservation_id.is_none() {
            return Err(SqliteBaoOwnerErrorV1::InvalidTransition);
        }
        next.state = BaoConsumptionStateV1::DispatchFenced;
        self.transition_consumption(
            operation_id,
            expected_revision,
            next,
            dispatch_evidence_sha256,
            now_unix_ms,
        )
        .await
    }

    pub async fn prepare_consumption_delivery(
        &self,
        operation_id: &str,
        expected_revision: u64,
        receipt: crate::BaoSecretReceipt,
        preparation_evidence_sha256: [u8; 32],
        now_unix_ms: u64,
    ) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
        let current = self.consumption_result(operation_id).await?;
        let mut next = current.operation;
        if receipt.request_sha256 != next.request_sha256 {
            return Err(SqliteBaoOwnerErrorV1::ObservationMismatch);
        }
        next.receipt = Some(receipt);
        next.state = BaoConsumptionStateV1::DeliveryPrepared;
        self.transition_consumption(
            operation_id,
            expected_revision,
            next,
            preparation_evidence_sha256,
            now_unix_ms,
        )
        .await
    }

    pub async fn mark_consumption_indeterminate(
        &self,
        operation_id: &str,
        expected_revision: u64,
        evidence_sha256: [u8; 32],
        now_unix_ms: u64,
    ) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
        let current = self.consumption_result(operation_id).await?;
        let mut next = current.operation;
        next.state = BaoConsumptionStateV1::Indeterminate;
        self.transition_consumption(
            operation_id,
            expected_revision,
            next,
            evidence_sha256,
            now_unix_ms,
        )
        .await
    }

    pub async fn mark_consumption_succeeded(
        &self,
        operation_id: &str,
        expected_revision: u64,
        now_unix_ms: u64,
    ) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
        let current = self.consumption_result(operation_id).await?;
        let mut next = current.operation;
        let receipt = next
            .receipt
            .as_ref()
            .ok_or(SqliteBaoOwnerErrorV1::InvalidTransition)?;
        let terminal = receipt
            .evidence_digest()
            .map_err(|_| SqliteBaoOwnerErrorV1::InvalidInput)?;
        next.terminal_kind = Some("success".to_owned());
        next.terminal_code = None;
        next.terminal_evidence_sha256 = Some(terminal);
        next.terminal_observed_cost = Some(next.amount);
        next.state = BaoConsumptionStateV1::ConsumerSucceeded;
        self.transition_consumption(operation_id, expected_revision, next, terminal, now_unix_ms)
            .await
    }

    pub async fn mark_consumption_provider_failed(
        &self,
        operation_id: &str,
        expected_revision: u64,
        error_code: String,
        terminal_evidence_sha256: [u8; 32],
        observed_cost: u64,
        now_unix_ms: u64,
    ) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
        if terminal_evidence_sha256 == [0; 32] || observed_cost == 0 {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        let current = self.consumption_result(operation_id).await?;
        let mut next = current.operation;
        next.terminal_kind = Some("provider_failure".to_owned());
        next.terminal_code = Some(error_code);
        next.terminal_evidence_sha256 = Some(terminal_evidence_sha256);
        next.terminal_observed_cost = Some(observed_cost);
        next.state = BaoConsumptionStateV1::ProviderFailed;
        self.transition_consumption(
            operation_id,
            expected_revision,
            next,
            terminal_evidence_sha256,
            now_unix_ms,
        )
        .await
    }

    pub async fn mark_consumption_not_applied(
        &self,
        operation_id: &str,
        expected_revision: u64,
        terminal_evidence_sha256: [u8; 32],
        now_unix_ms: u64,
    ) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
        if terminal_evidence_sha256 == [0; 32] {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        let current = self.consumption_result(operation_id).await?;
        let mut next = current.operation;
        if next.receipt.is_none() {
            return Err(SqliteBaoOwnerErrorV1::InvalidTransition);
        }
        next.terminal_kind = Some("consumer_not_applied".to_owned());
        next.terminal_code = Some("consumer_not_applied".to_owned());
        next.terminal_evidence_sha256 = Some(terminal_evidence_sha256);
        next.terminal_observed_cost = Some(0);
        next.state = BaoConsumptionStateV1::ConsumerNotApplied;
        self.transition_consumption(
            operation_id,
            expected_revision,
            next,
            terminal_evidence_sha256,
            now_unix_ms,
        )
        .await
    }

    pub async fn settle_consumption_terminal(
        &self,
        operation_id: &str,
        expected_revision: u64,
        now_unix_ms: u64,
    ) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
        let current = self.consumption_result(operation_id).await?;
        if matches!(
            current.operation.state,
            BaoConsumptionStateV1::Succeeded | BaoConsumptionStateV1::Failed
        ) {
            return Ok(current);
        }
        let mut next = current.operation;
        let evidence = next
            .terminal_evidence_sha256
            .ok_or(SqliteBaoOwnerErrorV1::InvalidTransition)?;
        next.state = match next.state {
            BaoConsumptionStateV1::ConsumerSucceeded => BaoConsumptionStateV1::Succeeded,
            BaoConsumptionStateV1::ConsumerNotApplied | BaoConsumptionStateV1::ProviderFailed => {
                BaoConsumptionStateV1::Failed
            }
            _ => return Err(SqliteBaoOwnerErrorV1::InvalidTransition),
        };
        self.transition_consumption(operation_id, expected_revision, next, evidence, now_unix_ms)
            .await
    }

    pub async fn abort_consumption_before_reservation(
        &self,
        operation_id: &str,
        expected_revision: u64,
        terminal_evidence_sha256: [u8; 32],
        now_unix_ms: u64,
    ) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
        self.abort_consumption(
            operation_id,
            expected_revision,
            "aborted_before_reservation",
            "no_reservation",
            terminal_evidence_sha256,
            now_unix_ms,
        )
        .await
    }

    pub async fn abort_consumption_before_dispatch(
        &self,
        operation_id: &str,
        expected_revision: u64,
        terminal_code: &str,
        terminal_evidence_sha256: [u8; 32],
        now_unix_ms: u64,
    ) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
        if !matches!(
            terminal_code,
            "reservation_cancelled" | "reservation_released" | "reservation_expired"
        ) {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        self.abort_consumption(
            operation_id,
            expected_revision,
            "aborted_before_dispatch",
            terminal_code,
            terminal_evidence_sha256,
            now_unix_ms,
        )
        .await
    }

    pub(super) async fn abort_consumption(
        &self,
        operation_id: &str,
        expected_revision: u64,
        terminal_kind: &str,
        terminal_code: &str,
        terminal_evidence_sha256: [u8; 32],
        now_unix_ms: u64,
    ) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
        if terminal_evidence_sha256 == [0; 32] {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        let current = self.consumption_result(operation_id).await?;
        let mut next = current.operation;
        next.terminal_kind = Some(terminal_kind.to_owned());
        next.terminal_code = Some(terminal_code.to_owned());
        next.terminal_evidence_sha256 = Some(terminal_evidence_sha256);
        next.terminal_observed_cost = Some(0);
        next.state = BaoConsumptionStateV1::Failed;
        self.transition_consumption(
            operation_id,
            expected_revision,
            next,
            terminal_evidence_sha256,
            now_unix_ms,
        )
        .await
    }
}
