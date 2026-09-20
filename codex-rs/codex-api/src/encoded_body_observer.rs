use futures::future::BoxFuture;

/// Host-supplied observer for the exact JSON bytes handed to a Responses transport.
///
/// The observer runs after canonical JSON encoding and before transport-level
/// compression/signing. It may reject the request, allowing a product owner to
/// fail closed when final payload binding has drifted.
pub trait EncodedRequestBodyObserver: Send + Sync + std::fmt::Debug {
    fn observe_encoded_body<'a>(
        &'a self,
        body: &'a [u8],
    ) -> BoxFuture<'a, Result<(), String>>;
}
