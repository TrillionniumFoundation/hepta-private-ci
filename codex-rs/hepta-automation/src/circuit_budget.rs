//! Conserved work reservations. Unknown work never returns its reservation.

use std::collections::BTreeMap;

use serde::Serialize;

use crate::TaskFlowError;
use crate::circuit_profile::invalid;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum CircuitWorkSettlementV2 {
    WithinReservation,
    Overrun,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CircuitBudgetV2 {
    limit: u64,
    spent: u64,
    reservations: BTreeMap<u64, u64>,
}

impl CircuitBudgetV2 {
    pub(crate) fn new(limit: u64) -> Self {
        Self {
            limit,
            spent: 0,
            reservations: BTreeMap::new(),
        }
    }

    pub fn spent(&self) -> u64 {
        self.spent
    }

    pub fn reserved(&self) -> u64 {
        self.reservations.values().sum()
    }

    pub fn available(&self) -> u64 {
        self.limit
            .saturating_sub(self.spent)
            .saturating_sub(self.reserved())
    }

    pub(crate) fn reserve(&mut self, id: u64, amount: u64) -> Result<(), TaskFlowError> {
        if amount == 0 || self.reservations.contains_key(&id) || amount > self.available() {
            return Err(invalid(
                "work reservation exceeds available budget or repeats identity",
            ));
        }
        self.reservations.insert(id, amount);
        Ok(())
    }

    /// Actual observation is never clamped to the reservation. An overrun is
    /// charged in full and makes the run take its resource-failure fallback.
    pub(crate) fn settle(
        &mut self,
        id: u64,
        actual_work: u64,
    ) -> Result<CircuitWorkSettlementV2, TaskFlowError> {
        let reserved = *self
            .reservations
            .get(&id)
            .ok_or_else(|| invalid("missing work reservation"))?;
        self.spent = self
            .spent
            .checked_add(actual_work)
            .ok_or_else(|| invalid("work charge overflow"))?;
        self.reservations.remove(&id);
        Ok(if actual_work > reserved {
            CircuitWorkSettlementV2::Overrun
        } else {
            CircuitWorkSettlementV2::WithinReservation
        })
    }
}
