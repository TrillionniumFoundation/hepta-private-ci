//! Bounded native model/tool orchestration over existing Hepta owners.
//!
//! This crate stores no conversation, issues no authority, and launches no
//! process. The context/TaskFlow owner supplies a frozen request and atomically
//! commits observations with its cursor. Inference and effect owners retain
//! admission, cancellation and same-operation recovery responsibilities.

#![forbid(unsafe_code)]

mod types;

pub use types::EffectObservation;
pub use types::EffectOwner;
pub use types::Error;
pub use types::Frame;
pub use types::InferenceOwner;
pub use types::Limits;
pub use types::ModelEvent;
pub use types::ModelOutput;
pub use types::ModelRequest;
pub use types::ModelSession;
pub use types::Outcome;
pub use types::Phase;
pub use types::Result;
pub use types::StopObservation;
pub use types::ToolCall;
pub use types::Transition;
pub use types::TurnBinding;
pub use types::TurnOwner;
pub use types::Usage;
