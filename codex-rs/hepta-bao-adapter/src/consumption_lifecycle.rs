//! Metadata-only consumer operation history in the existing lease writer.
use super::*;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoSecretReceipt {
    pub request_sha256: [u8; 32],
    pub response_sha256: [u8; 32],
    pub secret_sha256: [u8; 32],
    pub version: u64,
    pub secret_bytes: usize,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BaoConsumptionStateV1 {
    DispatchAttempted,
    DeliveryPrepared,
    ConsumerSucceeded,
    Succeeded,
    Indeterminate,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoConsumptionOperationV1 {
    pub operation_id: String,
    pub semantic_sha256: [u8; 32],
    pub effect_sha256: [u8; 32],
    pub request_sha256: [u8; 32],
    pub consumer_id: String,
    pub consumer_configuration_sha256: [u8; 32],
    pub amount: u64,
    pub reservation_id: Option<String>,
    pub state: BaoConsumptionStateV1,
    pub receipt: Option<BaoSecretReceipt>,
}

impl DurableLeaseRegistryV1 {
    /// Historical metadata only: this does not re-authorize delivery or replay.
    pub fn consumption_result(
        &self,
        operation_id: &str,
    ) -> Result<BaoConsumptionOperationV1, LeaseRegistryErrorV1> {
        self.ensure_writable()?;
        self.state
            .consumptions
            .get(operation_id)
            .cloned()
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)
    }

    pub(crate) fn claim_consumption(
        &mut self,
        operation: BaoConsumptionOperationV1,
    ) -> Result<Option<BaoConsumptionOperationV1>, LeaseRegistryErrorV1> {
        self.ensure_writable()?;
        validate_consumption(&operation)?;
        if operation.state != BaoConsumptionStateV1::DispatchAttempted
            || operation.reservation_id.is_some()
            || operation.receipt.is_some()
        {
            return Err(LeaseRegistryErrorV1::InvalidInput);
        }
        if self.state.operations.contains_key(&operation.operation_id) {
            return Err(LeaseRegistryErrorV1::OperationConflict);
        }
        if let Some(existing) = self.state.consumptions.get(&operation.operation_id) {
            let mut identity = existing.clone();
            identity.state = operation.state;
            identity.reservation_id = None;
            identity.receipt = None;
            if identity != operation {
                return Err(LeaseRegistryErrorV1::OperationConflict);
            }
            return Ok(Some(existing.clone()));
        }
        let mut next = self.state.clone();
        if next.consumptions.len() >= MAX_RECORDS {
            return Err(LeaseRegistryErrorV1::CapacityExceeded);
        }
        next.consumptions
            .insert(operation.operation_id.clone(), operation);
        self.commit(next, CONTROL_RESERVE_BYTES)?;
        Ok(None)
    }

    pub(crate) fn bind_consumption_reservation(
        &mut self,
        operation_id: &str,
        reservation_id: String,
    ) -> Result<(), LeaseRegistryErrorV1> {
        if !identifier(&reservation_id) {
            return Err(LeaseRegistryErrorV1::InvalidInput);
        }
        let mut next = self.state.clone();
        let row = next
            .consumptions
            .get_mut(operation_id)
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        if row.state != BaoConsumptionStateV1::DispatchAttempted
            || row
                .reservation_id
                .as_ref()
                .is_some_and(|id| *id != reservation_id)
        {
            return Err(LeaseRegistryErrorV1::InvalidTransition);
        }
        row.reservation_id = Some(reservation_id);
        self.commit(next, 0)
    }

    pub(crate) fn enter_consumption(
        &mut self,
        operation_id: &str,
        receipt: BaoSecretReceipt,
    ) -> Result<(), LeaseRegistryErrorV1> {
        let mut next = self.state.clone();
        let row = next
            .consumptions
            .get_mut(operation_id)
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        if row.state != BaoConsumptionStateV1::DispatchAttempted || row.reservation_id.is_none() {
            return Err(LeaseRegistryErrorV1::InvalidTransition);
        }
        row.receipt = Some(receipt);
        row.state = BaoConsumptionStateV1::DeliveryPrepared;
        self.commit(next, 0)
    }

    pub(crate) fn observe_consumption(
        &mut self,
        operation_id: &str,
        succeeded: bool,
    ) -> Result<(), LeaseRegistryErrorV1> {
        let mut next = self.state.clone();
        let row = next
            .consumptions
            .get_mut(operation_id)
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        if !matches!(
            row.state,
            BaoConsumptionStateV1::DeliveryPrepared | BaoConsumptionStateV1::Indeterminate
        ) || row.receipt.is_none()
        {
            return Err(LeaseRegistryErrorV1::InvalidTransition);
        }
        row.state = if succeeded {
            BaoConsumptionStateV1::ConsumerSucceeded
        } else {
            BaoConsumptionStateV1::Indeterminate
        };
        self.commit(next, 0)
    }

    pub(crate) fn settle_consumption(
        &mut self,
        operation_id: &str,
    ) -> Result<BaoSecretReceipt, LeaseRegistryErrorV1> {
        let mut next = self.state.clone();
        let row = next
            .consumptions
            .get_mut(operation_id)
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        if !matches!(
            row.state,
            BaoConsumptionStateV1::ConsumerSucceeded | BaoConsumptionStateV1::Succeeded
        ) {
            return Err(LeaseRegistryErrorV1::InvalidTransition);
        }
        let receipt = row
            .receipt
            .clone()
            .ok_or(LeaseRegistryErrorV1::CorruptState)?;
        row.state = BaoConsumptionStateV1::Succeeded;
        self.commit(next, 0)?;
        Ok(receipt)
    }
}

pub(super) fn validate_consumption(
    row: &BaoConsumptionOperationV1,
) -> Result<(), LeaseRegistryErrorV1> {
    if !identifier(&row.operation_id)
        || !identifier(&row.consumer_id)
        || row.amount == 0
        || [
            row.semantic_sha256,
            row.effect_sha256,
            row.request_sha256,
            row.consumer_configuration_sha256,
        ]
        .contains(&[0; 32])
        || row
            .reservation_id
            .as_deref()
            .is_some_and(|id| !identifier(id))
    {
        return Err(LeaseRegistryErrorV1::CorruptState);
    }
    if row.state != BaoConsumptionStateV1::DispatchAttempted
        && (row.reservation_id.is_none() || row.receipt.is_none())
    {
        return Err(LeaseRegistryErrorV1::CorruptState);
    }
    if let Some(receipt) = &row.receipt
        && (receipt.request_sha256 != row.request_sha256
            || receipt.version == 0
            || receipt.secret_bytes > 1024 * 1024
            || receipt.response_sha256 == [0; 32]
            || receipt.secret_sha256 == [0; 32])
    {
        return Err(LeaseRegistryErrorV1::CorruptState);
    }
    Ok(())
}
