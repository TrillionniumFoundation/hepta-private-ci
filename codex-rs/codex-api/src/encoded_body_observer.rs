use std::fmt;
use std::sync::Arc;

use futures::future::BoxFuture;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum EncodedRequestTerminal {
    Completed { response_id: String },
    Rejected { reason_code: String },
    Indeterminate { reason_code: String },
    Abandoned { reason_code: String },
}

/// Host-supplied observer for one exact Responses request.
///
/// The body callback runs after canonical JSON encoding and before
/// transport-level compression/signing. The terminal callback runs from the
/// core provider terminal path. A product owner can therefore bind the exact
/// model request semantics to a terminal delivery disposition without granting
/// the API layer any domain authority.
pub trait EncodedRequestBodyObserver: Send + Sync + fmt::Debug {
    fn observe_encoded_body<'a>(&'a self, body: &'a [u8]) -> BoxFuture<'a, Result<(), String>>;

    fn observe_terminal<'a>(
        &'a self,
        _terminal: EncodedRequestTerminal,
    ) -> BoxFuture<'a, Result<(), String>> {
        Box::pin(async { Ok(()) })
    }
}

/// Turn-scoped capability installed in extension data by a product owner.
///
/// Core retrieves this exact object only after turn context assembly. Presence
/// forces the Responses HTTP path so every physical send crosses the canonical
/// JSON body observer; WebSocket encoding cannot silently bypass the proof
/// boundary. The wrapper grants no dispatch or provider authority.
#[derive(Clone)]
pub struct EncodedRequestBodyObserverAttachment {
    observer: Arc<dyn EncodedRequestBodyObserver>,
}

impl EncodedRequestBodyObserverAttachment {
    #[must_use]
    pub fn new(observer: Arc<dyn EncodedRequestBodyObserver>) -> Self {
        Self { observer }
    }

    #[must_use]
    pub fn observer(&self) -> Arc<dyn EncodedRequestBodyObserver> {
        Arc::clone(&self.observer)
    }
}

impl fmt::Debug for EncodedRequestBodyObserverAttachment {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("EncodedRequestBodyObserverAttachment")
            .finish_non_exhaustive()
    }
}
