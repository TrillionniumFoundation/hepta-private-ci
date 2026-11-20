# Interactive OAuth metadata discovery

Interactive login and configured-client login share one metadata resolution
path. Normal advertised GET/well-known metadata keeps the existing RMCP
resolution and validation. A legacy endpoint fallback is insufficient evidence
for a custom protected-resource metadata location: a valid MCP endpoint may
return GET 404 and expose its authorization challenge only on POST.

When that fallback is reached, issue a typed compatibility initialization through
the existing Streamable HTTP adapter. This is an unauthenticated initialization,
not a tool call. It has no stored token or auth provider, and its Authorization
header is removed. The adapter keeps the configured resource headers, routing,
response and redirect boundaries. Its response body is capped at the existing
OAuth limit of one MiB, including a successful unauthenticated response. If the server creates a session without
requiring authentication, end that owned session before continuing login.

Pass the actual unauthorized response's `WWW-Authenticate` value to RMCP's
`resolve_metadata_from_challenge`. A supplied pointer must lead to valid
protected-resource and authorization-server metadata before registration.
Missing or invalid metadata must not silently select `/register` at the MCP
resource origin. Both automatic registration and configured client IDs then use
the same selected metadata and the original endpoint validation.

The OAuth server issuer and its path remain identifiers, rather than endpoint
path hints. RMCP owns the RFC 8414 and OIDC candidate order, percent encoding,
trailing-slash comparison and issuer checks. Keep PKCE, callback state, callback
issuer, redirect URI and resource binding in the original state machine. The
fallback initialization uses the legacy-compatible 2025-06-18 request; the
subsequent real MCP session retains its configured lifecycle negotiation.

The relevant primary specifications are:

- [MCP authorization-server and protected-resource discovery](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization#authorization-server-discovery).
- [RFC 8414 metadata requests and issuer validation](https://www.rfc-editor.org/rfc/rfc8414.html#section-3).
- [OIDC Discovery configuration requests and validation](https://openid.net/specs/openid-connect-discovery-1_0.html#ProviderConfig).

From `codex-rs`, run `just test -p codex-rmcp-client`, followed by the scoped
`just fix -p codex-rmcp-client` and repository `just fmt`. The registration
fixtures exercise separate resource and authorization origins, POST-only
challenges, custom metadata paths, encoded tenant segments and trailing slashes.
They retain real token exchange, PKCE/state checks and the existing refusal
rules. Preserve previous failure reports when generating new evidence.

Build the original CLI from the exact reviewed source and bind its hash before
running the original TypeScript SDK consumer command from the repository root:

```sh
pnpm -r --filter ./sdk/typescript run test
```

Use the pinned SDK 1.32 peer graph and unchanged conformance baseline. A focused
scenario or library test alone does not establish full consumer compatibility,
Asterinas native qualification or production deployment eligibility.
