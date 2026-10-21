// Compile the exact product scheduler and its tests without rebuilding Core.
// Only the unrelated CodexThread wiring and protocol error type are stubbed.
extern crate self as codex_protocol;
pub mod error {
    #[derive(Debug)]
    pub enum CodexErr {
        InvalidRequest(String),
    }
    pub type Result<T> = std::result::Result<T, CodexErr>;
}
use futures::future::BoxFuture;
use futures::future::Shared;
use std::sync::Arc;
pub struct CodexThread {
    session: Session,
    io: Io,
}
struct Session {
    services: Services,
}
struct Services {
    thread_extension_data: ExtensionData,
}
struct ExtensionData;
impl ExtensionData {
    fn get_or_init<T>(&self, init: impl FnOnce() -> T) -> Arc<T> {
        Arc::new(init())
    }
}
struct Io {
    session_loop_termination: Shared<BoxFuture<'static, ()>>,
}
#[path = "idle_work.rs"]
mod idle_work;
