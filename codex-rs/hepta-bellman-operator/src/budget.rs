//! Shared absolute resource budget for bounded operator construction.
//!
//! Production qualification paths must account for estimated resident bytes,
//! operation work, and one absolute elapsed deadline before and during long
//! loops. Compatibility V1 APIs retain their historical signatures.

use std::error::Error as StdError;
use std::fmt;
use std::time::Instant;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct OperatorResourceBudgetV1 {
    pub max_operations: u64,
    pub max_estimated_bytes: u64,
    pub max_elapsed_micros: u64,
}

impl OperatorResourceBudgetV1 {
    #[must_use]
    pub const fn qualification_default() -> Self {
        Self {
            max_operations: 50_000_000,
            max_estimated_bytes: 256 * 1024 * 1024,
            max_elapsed_micros: 30_000_000,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OperatorResourceKindV1 {
    Operations,
    EstimatedBytes,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OperatorWorkErrorV1 {
    InvalidBudget,
    ResourceExhausted {
        resource: OperatorResourceKindV1,
        required: u64,
        limit: u64,
    },
    DeadlineExceeded {
        elapsed_micros: u64,
        limit_micros: u64,
    },
    Arithmetic,
}

impl fmt::Display for OperatorWorkErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for OperatorWorkErrorV1 {}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct OperatorWorkSnapshotV1 {
    pub operations: u64,
    pub estimated_bytes: u64,
    pub elapsed_micros: u64,
}

pub(crate) struct OperatorWorkMeter {
    budget: OperatorResourceBudgetV1,
    started: Instant,
    operations: u64,
    estimated_bytes: u64,
}

impl OperatorWorkMeter {
    pub(crate) fn new(
        budget: OperatorResourceBudgetV1,
    ) -> Result<Self, OperatorWorkErrorV1> {
        if budget.max_operations == 0
            || budget.max_estimated_bytes == 0
            || budget.max_elapsed_micros == 0
        {
            return Err(OperatorWorkErrorV1::InvalidBudget);
        }
        Ok(Self {
            budget,
            started: Instant::now(),
            operations: 0,
            estimated_bytes: 0,
        })
    }

    pub(crate) fn preflight_operations(
        &self,
        required: u64,
    ) -> Result<(), OperatorWorkErrorV1> {
        if required > self.budget.max_operations {
            return Err(OperatorWorkErrorV1::ResourceExhausted {
                resource: OperatorResourceKindV1::Operations,
                required,
                limit: self.budget.max_operations,
            });
        }
        Ok(())
    }

    pub(crate) fn reserve_total_bytes(
        &mut self,
        required: u64,
    ) -> Result<(), OperatorWorkErrorV1> {
        if required > self.budget.max_estimated_bytes {
            return Err(OperatorWorkErrorV1::ResourceExhausted {
                resource: OperatorResourceKindV1::EstimatedBytes,
                required,
                limit: self.budget.max_estimated_bytes,
            });
        }
        self.estimated_bytes = self.estimated_bytes.max(required);
        Ok(())
    }

    pub(crate) fn consume(&mut self, amount: u64) -> Result<(), OperatorWorkErrorV1> {
        self.operations = self
            .operations
            .checked_add(amount)
            .ok_or(OperatorWorkErrorV1::Arithmetic)?;
        if self.operations > self.budget.max_operations {
            return Err(OperatorWorkErrorV1::ResourceExhausted {
                resource: OperatorResourceKindV1::Operations,
                required: self.operations,
                limit: self.budget.max_operations,
            });
        }
        self.checkpoint()
    }

    pub(crate) fn checkpoint(&self) -> Result<(), OperatorWorkErrorV1> {
        let elapsed = u64::try_from(self.started.elapsed().as_micros()).unwrap_or(u64::MAX);
        if elapsed > self.budget.max_elapsed_micros {
            return Err(OperatorWorkErrorV1::DeadlineExceeded {
                elapsed_micros: elapsed,
                limit_micros: self.budget.max_elapsed_micros,
            });
        }
        Ok(())
    }

    pub(crate) fn finish(&self) -> Result<OperatorWorkSnapshotV1, OperatorWorkErrorV1> {
        self.checkpoint()?;
        Ok(OperatorWorkSnapshotV1 {
            operations: self.operations,
            estimated_bytes: self.estimated_bytes,
            elapsed_micros: u64::try_from(self.started.elapsed().as_micros())
                .unwrap_or(u64::MAX),
        })
    }
}

pub(crate) fn checked_u64(value: usize) -> Result<u64, OperatorWorkErrorV1> {
    u64::try_from(value).map_err(|_| OperatorWorkErrorV1::Arithmetic)
}

pub(crate) fn checked_mul(left: u64, right: u64) -> Result<u64, OperatorWorkErrorV1> {
    left.checked_mul(right).ok_or(OperatorWorkErrorV1::Arithmetic)
}

pub(crate) fn checked_add(left: u64, right: u64) -> Result<u64, OperatorWorkErrorV1> {
    left.checked_add(right).ok_or(OperatorWorkErrorV1::Arithmetic)
}

pub(crate) fn sort_work(items: usize) -> Result<u64, OperatorWorkErrorV1> {
    if items <= 1 {
        return Ok(0);
    }
    let n = checked_u64(items)?;
    let levels = u64::from(usize::BITS - (items - 1).leading_zeros());
    checked_mul(n, levels)
}
