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
