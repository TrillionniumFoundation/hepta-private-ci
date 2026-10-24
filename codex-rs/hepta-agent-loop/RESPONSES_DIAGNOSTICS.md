# Bounded Responses failure diagnostics

The optional `responses-api` feature exposes `ResponsesFailure`: a request or
stream stage, a static enum category and an optional numeric HTTP status. Both
the initial single-attempt request and the parsed stream use this projection.
It retains no API error object, message, URL, headers, response body, retry delay
or nested connection source. Display and Debug therefore contain only those
allowlisted fields. No shared Hepta primitive or provider wire format changes.

The existing sensitive-route HTTP client and
`with_redacted_response_diagnostics()` remain enabled. That parser option is
not a guarantee that every API/transport error can safely be formatted: HTTP
errors can carry URL/header/body fields and some typed parser errors carry a
provider message. The new projection never formats those errors.

An HTTP status or an upstream category such as `invalid_request` or
`api_retryable` is an observation, not a final-use decision. The adapter still
performs one transport attempt and uses the original dispatch witness and
terminal owners. Once transport has been invoked, an unresolved result remains
Indeterminate; a status does not become proof of non-execution or permission to
retry. `transport_invoked=true` precedes the transport call and does not prove
that an HTTP request reached a provider.

The runner treats the typed error like its previous `Error::Owner` path: it
preserves the original cursor and does not turn a diagnostic into a validation
failure or an additional cancellation request. Native contract/limit errors
retain their existing cancellation behavior. Original terminal persistence
errors also retain their existing behavior and can supersede an API failure;
the separate owner records remain the source of terminal acknowledgement.

The qualification report adds a `failure_diagnostic` object. Native owner,
contract and limit failures are reported using static categories; arbitrary
owner strings are excluded. Existing attempt/transport/continuation fields and
the original `provider_or_owner_failure` classification remain intact. This
cannot reconstruct the discarded HTTP status of an older report. Historical
Indeterminate attempts remain preserved and are not retried by this change.

Controlled loopback tests exercise real Reqwest and Responses HTTP/SSE paths,
fake sensitive values, the exact encoded-body observer and original lease
terminal callbacks. HTTP 401/429/503 and an SSE error retain their safe category;
retry-enabled provider settings still produce exactly one request, no fabricated
usage/continuation, and Indeterminate receipts for both original owners. These
tests use only local fixture authority and never contact a live model provider.
