//! Explicit wall-time watchdog for trusted in-process organ handlers.
//!
//! This wrapper detects a handler that returns after its configured wall-time
//! budget and converts that call into a normal handler fault so the existing
//! host quarantines the organ. It is intentionally not described as a hard
//! timeout: synchronous in-process Rust cannot safely preempt a handler that
//! never returns. Work requiring a hard deadline or fault containment belongs
//! in a separately supervised process/worker boundary.

use std::fmt;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_types::StableId;

use crate::OrganHandlerFaultV1;
use crate::TrustedReadOnlyOrganV1;

const START_BUDGET_FAULT: &str = "organ.start.wall-budget-exceeded";
const HANDLE_BUDGET_FAULT: &str = "organ.handle.wall-budget-exceeded";
const STOP_BUDGET_FAULT: &str = "organ.stop.wall-budget-exceeded";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct OrganExecutionBudgetV1 {
    max_wall_time: Duration,
}

impl OrganExecutionBudgetV1 {
    pub fn new(max_wall_time: Duration) -> Result<Self, OrganExecutionBudgetErrorV1> {
        if max_wall_time.is_zero() {
            return Err(OrganExecutionBudgetErrorV1::ZeroWallTime);
        }
        Ok(Self { max_wall_time })
    }

    #[must_use]
    pub const fn max_wall_time(self) -> Duration {
        self.max_wall_time
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OrganExecutionBudgetErrorV1 {
    ZeroWallTime,
    InvalidFaultIdentity,
}

impl fmt::Display for OrganExecutionBudgetErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for OrganExecutionBudgetErrorV1 {}

#[derive(Debug)]
pub struct BudgetedReadOnlyOrganV1 {
    inner: Box<dyn TrustedReadOnlyOrganV1>,
    budget: OrganExecutionBudgetV1,
    start_budget_fault: StableId,
    handle_budget_fault: StableId,
    stop_budget_fault: StableId,
}

impl BudgetedReadOnlyOrganV1 {
    pub fn new(
        inner: Box<dyn TrustedReadOnlyOrganV1>,
        budget: OrganExecutionBudgetV1,
    ) -> Result<Self, OrganExecutionBudgetErrorV1> {
        Ok(Self {
            inner,
            budget,
            start_budget_fault: fault_id(START_BUDGET_FAULT)?,
            handle_budget_fault: fault_id(HANDLE_BUDGET_FAULT)?,
            stop_budget_fault: fault_id(STOP_BUDGET_FAULT)?,
        })
    }

    fn exceeded(&self, started: Instant) -> bool {
        started.elapsed() > self.budget.max_wall_time()
    }
}

impl TrustedReadOnlyOrganV1 for BudgetedReadOnlyOrganV1 {
    fn id(&self) -> &StableId {
        self.inner.id()
    }

    fn start(&mut self) -> Result<(), OrganHandlerFaultV1> {
        let started = Instant::now();
        let result = self.inner.start();
        if self.exceeded(started) {
            return Err(OrganHandlerFaultV1::new(self.start_budget_fault.clone()));
        }
        result
    }

    fn handle(
        &mut self,
        input_port: usize,
        payload: &[u8],
    ) -> Result<Vec<u8>, OrganHandlerFaultV1> {
        let started = Instant::now();
        let result = self.inner.handle(input_port, payload);
        if self.exceeded(started) {
            return Err(OrganHandlerFaultV1::new(self.handle_budget_fault.clone()));
        }
        result
    }

    fn stop(&mut self) -> Result<(), OrganHandlerFaultV1> {
        let started = Instant::now();
        let result = self.inner.stop();
        if self.exceeded(started) {
            return Err(OrganHandlerFaultV1::new(self.stop_budget_fault.clone()));
        }
        result
    }
}

fn fault_id(value: &str) -> Result<StableId, OrganExecutionBudgetErrorV1> {
    StableId::new(value).map_err(|_| OrganExecutionBudgetErrorV1::InvalidFaultIdentity)
}

#[cfg(test)]
mod tests {
    use std::thread;

    use super::*;

    #[derive(Debug)]
    struct SlowHandler {
        id: StableId,
    }

    impl TrustedReadOnlyOrganV1 for SlowHandler {
        fn id(&self) -> &StableId {
            &self.id
        }

        fn start(&mut self) -> Result<(), OrganHandlerFaultV1> {
            Ok(())
        }

        fn handle(
            &mut self,
            _input_port: usize,
            _payload: &[u8],
        ) -> Result<Vec<u8>, OrganHandlerFaultV1> {
            thread::sleep(Duration::from_millis(3));
            Ok(vec![1])
        }

        fn stop(&mut self) -> Result<(), OrganHandlerFaultV1> {
            Ok(())
        }
    }

    #[test]
    fn late_handler_result_becomes_a_fault() {
        let handler = Box::new(SlowHandler {
            id: StableId::new("slow.organ").expect("fixture identity"),
        });
        let budget = OrganExecutionBudgetV1::new(Duration::from_millis(1)).expect("budget");
        let mut bounded = BudgetedReadOnlyOrganV1::new(handler, budget).expect("wrapper");

        let fault = bounded
            .handle(0, b"")
            .expect_err("late handler must fail closed");
        assert_eq!(fault.code.as_str(), HANDLE_BUDGET_FAULT);
    }

    #[test]
    fn zero_budget_is_rejected() {
        assert_eq!(
            OrganExecutionBudgetV1::new(Duration::ZERO),
            Err(OrganExecutionBudgetErrorV1::ZeroWallTime)
        );
    }
}
