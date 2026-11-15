//! Scope of load-time memory observations in the optional legacy fixture.
//!
//! These declared counts do not establish physical allocation or execution
//! authority. The owning worker applies its grant to either accounting mode.

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ModelMemoryAccounting {
    /// Each handle reports only its model's retained bytes. Sum all handles.
    PerModel,
    /// Each successful load reports all current resident bytes in this worker.
    WorkerWide,
}
