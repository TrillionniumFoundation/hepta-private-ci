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
pub trait EncodedRequestBodyObserver: Send + Sync + std::fmt::Debug {
    fn observe_encoded_body<'a>(&'a self, body: &'a [u8]) -> BoxFuture<'a, Result<(), String>>;

    fn observe_terminal<'a>(
        &'a self,
        _terminal: EncodedRequestTerminal,
    ) -> BoxFuture<'a, Result<(), String>> {
        Box::pin(async { Ok(()) })
    }
}
