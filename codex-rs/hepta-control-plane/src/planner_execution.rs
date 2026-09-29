//! Durable dispatch admission around the authority-separated execution core.
//!
//! The core defines authority and effect-owner ports. The durable wrapper
//! persists an exact claim before dispatch, returns conclusive receipts
//! idempotently, and reconciles unresolved operations without replay.

#[path = "planner_execution_core.rs"]
mod core;
#[path = "planner_execution_codec.rs"]
mod codec;
#[path = "planner_execution_durable.rs"]
mod durable;

pub use core::PlannerAuthorizationDecisionV1;
pub use core::PlannerAuthorityConsumerV1;
pub use core::PlannerAuthorityRevalidationV1;
pub use core::PlannerEffectDispositionV1;
pub use core::PlannerEffectExecutorV1;
pub use core::PlannerEffectObservationV1;
pub use core::PlannerExecutionError;
pub use core::PlannerExecutionGrantV1;
pub use core::PlannerTerminalReceiptSinkV1;
pub use core::PlannerTerminalReceiptV1;
pub use durable::execute_planner_request_v1;
pub use durable::reconcile_planner_request_v1;
