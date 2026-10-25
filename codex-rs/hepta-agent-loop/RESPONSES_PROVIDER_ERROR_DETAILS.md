# Bounded provider error labels

The native Responses adapter can retain a small diagnostic projection from the
original `TransportError::Http` body. It retains only enum labels for the exact
JSON fields `error.type`, `error.code` and `error.param`. This adds diagnostic
information to `ResponsesFailure`; it does not change request construction,
transport, authentication, admission, cancellation or terminal settlement.

## Projection boundary

`responses_provider_error.rs` contains the complete static allowlists. Matching
is exact and case-sensitive. There is no prefix matching, Unicode normalization,
message parsing, dynamic parameter path retention or raw provider string field
in the result. Known request parameter labels include `tools`, `tool_choice`
and `reasoning.effort`; recognizing a label does not establish which requests
or parameter values the configured provider supports.

The parser accepts at most 16 KiB of the original UTF-8 body, measured in bytes.
It parses the whole bounded JSON document, never a truncated prefix. Duplicate
recognized envelope/field names are rejected by the typed decoder. Unknown
fields are ignored. Unknown, absent, null or wrongly typed field values produce
no label for that field. If no field has a known label, the entire diagnostic
projection is absent. Malformed, oversized or differently shaped bodies also
produce no projection. A response containing only free-form `message` or
`detail` remains unclassified.

The typed decoder uses the crate's existing optional Serde dependency, now
enabled by `responses-api`, which already enables `serde_json`. No package or
version is added. Neither transient wire structure implements `Debug` or
`Serialize`. Only fixed enum discriminants survive into the public error.
No raw body, message, URL, auth header, request ID, body digest or extracted
unknown string is retained. The pre-existing HTTP transport already owns the
error body; this diagnostic bound is not a new transport download limit.

Only `ApiError::Transport(TransportError::Http { body: Some(..), .. })` supplies
this projection. `ApiError::Api.message`, native owner errors and SSE error
strings are not reinterpreted as an HTTP body. Existing typed stage, category
and numeric status remain intact. In particular, a stream error does not gain
an invented HTTP status or synthetic structured body.

## Interpretation and original attempt ownership

All labels are untrusted statements reported by the responding service. They
are useful for comparing a future request with its original typed contract;
they do not prove a particular backend accepted the request, that effects are
absent, that a terminal acknowledgement occurred, or that another attempt is
authorized. A label such as `unsupported_parameter` must not automatically
remove a field, downgrade an effort, switch models or trigger a retry.

The qualifier writes an optional `provider_error` object with the static
`type`, `code` and `param` strings. Its absence has no causal interpretation.
The original managed attempt still performs exactly one transport attempt and
uses its original policy and exact encoded-body observer. An unresolved error
continues to settle as `native_response_unresolved` / Indeterminate. No old
receipt is reopened or relabelled by this addition.

The request-stage HTTP 400 observed at source
`396a54cbf83d5b031089b8e5573bc88f93d55ea3` did not retain its response body. This
change cannot reconstruct its provider labels or diagnose its cause after the
fact. The earlier admission, body digest and terminal receipts remain unchanged.

## Validation scope

Sibling unit tests cover static labels, secret and dynamic-value rejection,
duplicate recognized keys, wrong envelopes, byte limits, malformed JSON and
the distinction between an HTTP body and a JSON-shaped error message. The
existing controlled loopback transport fixture adds two real HTTP 400 cases.
Those tests retain the original exact-body observer and attempt lease, assert
one physical request despite configured transport retry settings, and assert
both original Indeterminate terminal receipts with no usage or continuation.
The existing HTTP 401/429/503 and SSE tests remain included.

These fixture responses are not the earlier provider's actual error body.
Successful fixture tests establish the diagnostic and ownership behavior at
this boundary; they do not establish a successful hosted generation, a cause
for the earlier HTTP 400, a complete native agent or the task A/B qualification.
