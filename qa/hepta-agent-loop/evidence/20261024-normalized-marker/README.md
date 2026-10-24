# Actual normalized fixed-marker request: HTTP 400

One new qualification was executed against the installed gpt-6.1-sol model
after normalized source 396a54cbf83d5b031089b8e5573bc88f93d55ea3 passed the
recorded affected gates. This is a new attempt, not a retry or repair of the
earlier Indeterminate request. The actual debug binary and invocation are
bound in admission.json and process.json.

The transport returned HTTP 400 at the request stage. No text, complete
continuation, server model or usage was observed. The original terminal
remains Indeterminate/native_response_unresolved. The error body was not
retained by the safe diagnostics, so a specific server rejection reason is
not established. Shared settings normalization has not qualified this path.

The exact harmless marker body, normalized metadata, original terminal and
bounded process logs are retained. Token numbers are local reservations,
not provider-enforced caps. No primary task A/B, tool execution, deployed
service change, automatic retry or lighter-memory qualification occurred.
Private policy databases and credentials remain outside this publication.
