//! Transport-created completion evidence and a one-shot owner notification.

use std::future::Future;
use std::pin::Pin;

use anyhow::Result;
use anyhow::Context;
use anyhow::ensure;
use codex_hepta_types::Digest32;
use serde_json::Value;

use super::ModelRequest;
use super::ObservedModelCompletion;
use super::ResponsesStream;

/// A completion observed on the original HTTP stream. Callers cannot construct
/// this from model text, a response id, or an arbitrary JSON document.
#[derive(Debug)]
pub struct ObservedModelTerminal {
    operation_id: String,
    response_id: String,
    evidence_digest: Digest32,
}

impl ObservedModelTerminal {
    pub(super) fn observed(
        operation_id: String,
        response_id: String,
        output: &[Value],
        usage: &Value,
    ) -> Result<Self> {
        let evidence_digest = Self::evidence_digest_for_output(&operation_id, &response_id, output, usage)?;
        Ok(Self { operation_id, response_id, evidence_digest })
    }

    /// Recompute a persisted result's canonical content digest. This returns
    /// only an authority-free hash, never a transport-created terminal value.
    pub fn evidence_digest_for_output(operation_id: &str, response_id: &str,
        output: &[Value], usage: &Value) -> Result<Digest32> {
        let mut witness = serde_json::json!({
            "schema": "hepta.responses.terminal.v2",
            "operation_id": operation_id,
            "response_id": response_id,
            "status": "completed",
            "output": output,
            "usage": usage,
        });
        // Provider JSON object key order is not evidence of a different
        // result. Preserve array order and every output value, including
        // message contents, tool arguments, call ids and annotations.
        witness.sort_all_objects();
        let bytes = serde_json::to_vec(&witness)?;
        Ok(Digest32::of_bytes(&bytes))
    }

    pub fn operation_id(&self) -> &str { &self.operation_id }
    pub fn response_id(&self) -> &str { &self.response_id }
    pub fn evidence_digest(&self) -> Digest32 { self.evidence_digest }
}

pub(super) fn completed_output(response: &Value) -> Result<&[Value]> {
    ensure!(response["status"] == "completed", "provider terminal status is not completed");
    let items = response["output"].as_array().context("complete provider output is missing")?;
    ensure!(items.iter().all(Value::is_object), "provider output contains a non-object item");
    Ok(items)
}

pub(super) type TerminalObserver = Box<dyn FnOnce(ObservedModelTerminal) -> Pin<Box<dyn Future<Output = Result<()>> + Send>> + Send>;

impl ResponsesStream {
    /// Notify the existing owner once, after an authentic terminal event and
    /// before exposing completion to the loop. Dropping an unfinished stream
    /// drops the notification without fabricating an outcome or retrying POST.
    pub fn with_terminal_observer<F, Fut>(mut self, request: &ModelRequest, observer: F) -> Result<Self>
    where
        F: FnOnce(ObservedModelTerminal) -> Fut + Send + 'static,
        Fut: Future<Output = Result<()>> + Send + 'static,
    {
        anyhow::ensure!(self.operation_id == request.operation_id, "stream operation changed");
        anyhow::ensure!(!self.completed, "stream has already terminated");
        anyhow::ensure!(self.terminal_observer.is_none(), "stream completion owner already attached");
        self.terminal_observer = Some(Box::new(move |terminal| Box::pin(observer(terminal))));
        Ok(self)
    }
}

impl ObservedModelCompletion {
    pub fn operation_id(&self) -> &str { &self.operation_id }
    pub fn response_id(&self) -> &str { &self.response_id }

    /// Evidence from the original provider's GET, never another model POST.
    pub fn terminal(&self) -> Result<ObservedModelTerminal> {
        ObservedModelTerminal::observed(
            self.operation_id.clone(), self.response_id.clone(), &self.items, &self.usage,
        )
    }
}

#[cfg(test)]
#[path = "responses_terminal_tests.rs"]
mod tests;
