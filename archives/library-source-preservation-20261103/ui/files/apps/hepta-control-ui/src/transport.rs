//! Typed owner transport boundary; never used directly by the GUI callback.
use crate::Result;
use serde_json::Value;

/// An authenticated owner transport; implementations must never retry mutations.
/// An error after possible dispatch must preserve that uncertainty.
pub trait ControlTransport: Send {
    /// Canonical API origin and base path. Must remain stable throughout a session.
    fn endpoint(&self) -> &str;
    fn connect(&mut self, manifest: &Value) -> Result<Value>;
    fn refresh_session(&mut self, session: &Value) -> Result<Value>;
    fn read_snapshot(&mut self, session: &Value) -> Result<Value>;
    fn request(&mut self, method: &str, input: &Value) -> Result<Value>;
    fn lookup(&mut self, input: &Value) -> Result<Value>;
    fn close(&mut self, session: &Value) -> Result<()>;
    fn revoke(&mut self, session: &Value) -> Result<()>;
}
