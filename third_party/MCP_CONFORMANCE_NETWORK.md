# Local conformance fixture network boundary

This is a local derivative of upstream conformance c37 plus the explicit SDK
1.32 reference-client compatibility patch. It protects fixture networking; it
is not a production Hepta authorization issuer, protected clock, revocation
service, Agentd deployment, or native-device qualification.

## Implementation contract

`src/fixture-network.ts` owns the shared boundary. `ServerLifecycle` and the
example everything-server listen only on `127.0.0.1`, wait for the actual
`listening` event, and publish the actual port. OAuth discovery continues to use
the actual fixture URL, so issuer/redirect/DPoP checks exercise real requests.

Each affected OAuth/IdP/MCP application admits at most a burst of 120 requests,
refilling at 120 per minute, and at most 32 active responses. The bucket and
active count are per fixture, not an unbounded table indexed by remote input.
Admission runs before JSON/form parsing, logging and expensive auth operations.
A denied request gets HTTP 429 and Retry-After, never a successful protocol
observation. Finish and disconnect release active work exactly once. JSON and
form bodies are bounded to 64 KiB, forms to 64 parameters, compressed bodies are
not inflated, and forms use flat OAuth fields. Listeners bound incomplete
headers/requests to 10/15 seconds, 64 parsed headers and 100 requests per socket.
The response stream itself has no new inactivity deadline: intentional MCP
streaming and original scenario timers remain intact.

The everything-server rejects a supplied unlisted Origin with HTTP 403 before
MCP dispatch. Non-browser clients with no Origin still work. Defaults admit only
`http://localhost:6274` and `http://127.0.0.1:6274` (the local Inspector) plus exact
same-server loopback origins derived from the actual bound socket port. The
latter preserves the original DNS-rebinding positive test without trusting the
request Host or allowing arbitrary local ports. CORS reads that same set.
`MCP_CONFORMANCE_ALLOWED_ORIGINS` replaces the Inspector defaults with a
comma-separated set of exact HTTP(S) origins. Wildcards, null, credentials,
paths, query strings and fragments fail startup validation. Configured external
origins are explicit operator input; the listener remains local.

## Development and provenance

Do not modify the immutable upstream manifest or full LICENSE, delete scenarios,
relax original assertions, or update a digest merely to conceal unexplained
source drift. Keep original failures. The adjacent patch records all local
network and package-license changes; the verifier names every modified file and
the two added files explicitly, with 293 total files (291 upstream plus two).
The upstream package and lock license fields now defer to the full transitional
license notice; no upstream notice has been removed.

To reproduce the source derivation, reverse the separately recorded SDK 1.32
patch and restore the preserved upstream lock, then verify all 291 original
byte hashes, typed Git blob IDs, modes and sizes against the immutable manifest.
Reapply the SDK patch and reviewed proxy record, then apply the network patch.
The result must match all 293 current paths exactly. This source proof does not
claim upstream accepted these changes.

With the repository's pinned Node 22 / pnpm 10.34.5 dependency graph, run the
unchanged vendor commands `pnpm run typecheck`, `pnpm test`, and `pnpm run build`.
The complete original 641 tests remain; four new real HTTP tests cover request
admission, body/parameter bounds, disconnect accounting and browser Origin
rejection. The original DNS-rebinding positive and negative cases remain.
`node --test scripts/tests/verify-mcp-conformance-vendor.test.mjs` exercises
closed source provenance. `node scripts/verify-mcp-conformance-local-network-profile.mjs`
verifies the explicit v2 descriptor, original dependency peer graph, selected
CLI and an independent offline rebuild with the original build command.

The historical v1 descriptor, v1 measured baseline and original upstream
manifest remain unchanged. The v2 descriptor binds new source pins and the
actual canonical output. A full product/conformance comparison needs an
explicit v2 execution identity and reviewed baseline migration; this patch does
not reuse prior SDK50 results or fabricate a v2 product baseline. Existing v1
execution must use its matching historical source/tool snapshot, not a v2 CLI
with a rewritten v1 identity. CI CodeQL conclusions are pending actual CI; local
behavior tests are not evidence that a static analyzer recognizes a custom
admission function.


## Open MCP product and reference gaps

The complete localnet-v2 capture used the original retained normal Codex from
310c (Rust source unchanged), the new canonical CLI, all 55 original scenario
executions across three modes, and all six HTTP/stdio groups. Four groups passed
and two failed. The 18 failing identities below remain open. They are measured
failures, not expected-success changes. The shipping mode passed. Every one of
the 634 required passing identities remains observed; no failure or scenario is
removed by profile migration. Full MCP conformance is not green.

| Mode | Source | Scenario | Open check ID |
|---|---|---|---|
| 2025-11-25 | harness | auth/pre-registration | harness/auth/pre-registration/codex-adapter |
| 2025-11-25 | harness | auth/scope-from-www-authenticate | harness/auth/scope-from-www-authenticate/codex-adapter |
| 2025-11-25 | harness | auth/scope-step-up | harness/auth/scope-step-up/codex-adapter |
| 2025-11-25 | official | auth/pre-registration | pre-registration-auth |
| 2025-11-25 | official | auth/scope-from-www-authenticate | scope-from-www-authenticate |
| 2025-11-25 | official | auth/scope-step-up | scope-step-up-initial |
| 2025-11-25 | official | elicitation-sep1034-client-defaults | client-elicitation-sep1034-boolean-default |
| 2025-11-25 | official | elicitation-sep1034-client-defaults | client-elicitation-sep1034-enum-default |
| 2025-11-25 | official | elicitation-sep1034-client-defaults | client-elicitation-sep1034-integer-default |
| 2025-11-25 | official | elicitation-sep1034-client-defaults | client-elicitation-sep1034-number-default |
| 2025-11-25 | official | elicitation-sep1034-client-defaults | client-elicitation-sep1034-string-default |
| 2026-07-28 | harness | auth/pre-registration | harness/auth/pre-registration/codex-adapter |
| 2026-07-28 | harness | auth/scope-from-www-authenticate | harness/auth/scope-from-www-authenticate/codex-adapter |
| 2026-07-28 | harness | auth/scope-step-up | harness/auth/scope-step-up/codex-adapter |
| 2026-07-28 | official | auth/pre-registration | pre-registration-auth |
| 2026-07-28 | official | auth/scope-from-www-authenticate | scope-from-www-authenticate |
| 2026-07-28 | official | auth/scope-step-up | scope-step-up-initial |
| 2026-07-28 | official | auth/scope-step-up | sep-2350-scope-union-on-reauth |

Raw v1 and v2 captures each observe 654 unique identities with identical status
sets. The compact v1 golden stores 634 passing and 18 failing identities, and
omits pure SKIP observations. Both raw captures retain two optional
request-metadata SKIPs (roots and sampling not declared), plus a standard-header
identity with both PASS and SKIP observations. Those raw observations remain in
the evidence; migration does not relabel them or count them as new passes.

The separate Node EverythingClient run exited 0 for 30 of 55 scenario executions
and exited 1 for 25, without timeouts. Its gaps below are reference-client facts,
not new Codex failures or a product baseline. The original 641 unit/scenario
cases, their negative producers and all protocol oracles remain intact.

| Mode | Reference scenario | Actual failure family |
|---|---|---|
| 2025-11-25 | elicitation-sep1034-client-defaults | Reference client has no matching registered handler |
| 2025-11-25 | sse-retry | Reference client has no matching registered handler |
| 2026-07-28 | http-standard-headers | Reference client has no matching registered handler |
| 2026-07-28 | http-custom-headers | Reference client has no matching registered handler |
| 2026-07-28 | http-invalid-tool-headers | Reference client has no matching registered handler |
| 2026-07-28 | json-schema-ref-no-deref | Reference stateless client attempts JSON parsing of an SSE response |
| 2026-07-28 | auth/metadata-default | SDK 1.32 transport omits required version header on this modern path |
| 2026-07-28 | auth/metadata-var1 | SDK 1.32 transport omits required version header on this modern path |
| 2026-07-28 | auth/metadata-var2 | SDK 1.32 transport omits required version header on this modern path |
| 2026-07-28 | auth/metadata-var3 | SDK 1.32 transport omits required version header on this modern path |
| 2026-07-28 | auth/basic-cimd | SDK 1.32 transport omits required version header on this modern path |
| 2026-07-28 | auth/scope-from-www-authenticate | SDK 1.32 transport omits required version header on this modern path |
| 2026-07-28 | auth/scope-from-scopes-supported | SDK 1.32 transport omits required version header on this modern path |
| 2026-07-28 | auth/scope-omitted-when-undefined | SDK 1.32 transport omits required version header on this modern path |
| 2026-07-28 | auth/scope-step-up | SDK 1.32 transport omits required version header on this modern path |
| 2026-07-28 | auth/scope-retry-limit | SDK 1.32 transport omits required version header on this modern path |
| 2026-07-28 | auth/token-endpoint-auth-basic | SDK 1.32 transport omits required version header on this modern path |
| 2026-07-28 | auth/token-endpoint-auth-post | SDK 1.32 transport omits required version header on this modern path |
| 2026-07-28 | auth/token-endpoint-auth-none | SDK 1.32 transport omits required version header on this modern path |
| 2026-07-28 | auth/pre-registration | SDK 1.32 transport omits required version header on this modern path |
| 2026-07-28 | auth/offline-access-scope | SDK 1.32 transport omits required version header on this modern path |
| 2026-07-28 | auth/offline-access-not-supported | SDK 1.32 transport omits required version header on this modern path |
| 2026-07-28 | auth/authorization-server-migration | SDK 1.32 transport omits required version header on this modern path |
| 2026-07-28 | auth/iss-supported | SDK 1.32 transport omits required version header on this modern path |
| 2026-07-28 | auth/iss-not-advertised | SDK 1.32 transport omits required version header on this modern path |

CodeQL recognition of the custom admission function still needs actual new-head
CI. The local negative and resource tests are not a scanner result. The v2
baseline candidate is derived from the complete actual report and preserves
exactly the existing pass/failure vectors; it requires explicit review before
code-owned admission. Cross-profile comparison remains an error even after
migration. No production authorization or Asterinas native-device qualification
follows from these host captures.
