# MCP conformance source and dependency maintenance

`mcp-conformance/` contains the complete official source at
[`c37eec888e1c6ff140af79987a40008548b7cc5f`](https://github.com/modelcontextprotocol/conformance/commit/c37eec888e1c6ff140af79987a40008548b7cc5f),
including its complete, unchanged [license notice](mcp-conformance/LICENSE).
That notice describes Apache-2.0 for new code/specification contributions and
relicensed contributions, MIT for contributions without relicensing consent, and
CC-BY-4.0 for documentation excluding specifications. It does not grant a
blanket MIT license to this tree. Package metadata now says
`SEE LICENSE IN LICENSE`; the full notice remains authoritative. Its upstream tree is
`22eb98b99b522401dd1911dc2c2a55bee3547b50`.
The source archive SHA-256 is
`6ab798454dc41840631b77024f34de7d05d6ad0eda67ac04050d664e447171a2`.
The adjacent upstream manifest records the original Git blob, byte hash, size,
and executable mode of all 291 files. The original upstream lock is retained
separately for an exact comparison.

The initial local dependency change was the `node_modules/proxy-addr` record in
`package-lock.json`: npm resolved 2.0.7 to 2.0.8 and recorded its published
integrity and funding metadata. This fixes
[GHSA-jqcg-44mw-7w3h](https://github.com/advisories/GHSA-jqcg-44mw-7w3h)
in the tool's own preparation dependencies. The prepare/build/test commands, dependency versions, original test cases,
requirements and protocol oracles remain unchanged. The explicit SDK 1.32
reference-client patch and the local network patch below are recorded separately
from the original upstream source. This is a local dependency patch; upstream c37 still has the affected
lock. Other audit findings remain separately actionable.

## Installation trust

The SDK refers to this exact local workspace version. The previous Git
dependency fetched its source and ran a separate `npm install` in a temporary
preparation directory. Root pnpm overrides could not update that nested npm
lock. The local workspace makes the complete source reviewable and prevents
that additional Git preparation install.

Workspace lifecycle scripts are trusted repository code. They do not use the
third-party dependency `allowBuilds` list. The old permission for one exact Git
URL is removed because that URL is no longer a dependency. The sole new
`allowBuilds` entry is an explicit `lefthook@2.2.2: false`: its reviewed
postinstall installs shared Git hooks outside CI, which this workspace
does not authorize. This denies only that exact dependency install script;
it grants no third-party build permission and leaves the original conformance
prepare/build/test scripts intact. `strictDepBuilds`, exotic
subdependency blocking, release age, and trust policies remain enabled.

`.pnpmfile.cjs` verifies the source when pnpm loads its hooks, before dependency
resolution or workspace preparation. It changes no package metadata. SDK CI
also runs the verifier and its negative tests explicitly before installation.
The verifier pins the original manifest and patched lock by byte hash, rejects
added, removed, changed or symlinked source, and checks that the only semantic
lock changes are the reviewed proxy record and the root package license notice. Only normal build/install/test output
directories at original package roots are excluded. Generated outputs are not
claimed to be upstream source.

## Reproduce and update

Run `node scripts/verify-mcp-conformance-vendor.mjs` and
`node --test scripts/tests/verify-mcp-conformance-vendor.test.mjs` from the
repository root. Run `npm ci`, `npm run build`, `npm test`, and `npm audit --json`
inside `third_party/mcp-conformance`, with `CI=true` and `LEFTHOOK` unset, to
exercise the tool's own lock and original
scripts. Run the repository's frozen pnpm installation and SDK checks separately
to exercise the workspace dependency graph. Neither audit covers the other
graph. The upstream lefthook postinstall itself returns under these CI
conditions; this prevents npm from changing shared Git hooks. Verify the hooks
directory remains unchanged around the nested npm installation. Do not use a
blanket `ignore-scripts` setting.

The lock patch was produced with `npm update proxy-addr --package-lock-only`
after an original `npm ci`, followed by another `npm ci`. Do not edit oracle
code, weaken assertions, disable lifecycle scripts, or update expected hashes
to accept unexplained changes. An upstream revision or additional dependency
patch requires a reviewed new manifest, explicit verifier hash update, and the
same source-equivalence, original test, audit, and SDK checks.

Upstream c37 requests `@modelcontextprotocol/sdk ^1.29.0`. The separate SDK
maintenance candidate locks 1.32.0, the first version fixing the currently
reported OAuth, redirect, task ownership and validation advisories. It keeps
both legal Zod contexts: the TypeScript SDK uses 3.25.76 and the conformance
workspace uses 4.4.3. The isolated pnpm linker preserves these peer contexts;
the prior hoisted layout resolved the conformance SDK against the root Zod 3
instance and failed the original type check despite two contexts in the lock.
No dependency source, build trust, release age or script policy is weakened.

The original 641-case suite initially reports 639 passes and two failures with
SDK 1.32.0. Wire observations show the SDK sends the pathless resource exactly
as published and registers new credentials after authorization-server migration.
The old example's known-failure expectation and negative producer therefore need
an explicit, reviewed local compatibility patch. Keep those failed results and
the original c37 manifest; do not restore the SDK vulnerabilities to make the
old example fail. The package audit still has other findings, so this candidate
does not close the repository dependency gate or provide Asterinas native or
production qualification.

## Local SDK 1.32 reference-client compatibility

`mcp-conformance-patches/sdk-1.32-reference-clients.patch` records the exact
changes relative to c37. The immutable upstream manifest remains unchanged.
The verifier permits only the pinned source hashes in this compatibility patch,
the previous npm proxy lock fix, the pinned local raw producer, and the explicit
network source/metadata changes described in
[MCP_CONFORMANCE_NETWORK.md](MCP_CONFORMANCE_NETWORK.md). It also refuses
this compatibility patch unless the root SDK resolution is exactly 1.32.0.
Changing a rule, adding a skip or changing a timeout still fails provenance.

The positive `auth/metadata-var2` example now has no known-failure exemption:
SDK 1.32 sends the PRM resource verbatim. The original resource-slash negative
case, all its expected slugs and its detector remain unchanged. For SEP-2352,
the original negative case and all three expected failure slugs remain unchanged.
Its local producer performs real OAuth HTTP requests and deliberately keeps the
first issuer's client credentials at the second issuer. It never calls the
SDK's fixed OAuth implementation to emulate that bug. Both the initial server
and every discovered endpoint must be explicit HTTP loopback URLs, and the
resource transport stays on the initial fixture origin. The positive SDK client
continues to use the fixed implementation and correctly re-registers at AS2.

This is a local compatibility patch to reference clients, not an upstream fix or
a change to the MCP rules. The original 639/2 failed run and its wire capture
remain evidence. The initial standalone npm graph still uses the original SDK
1.29 lock and retains its separately reported advisories; the shared pnpm graph
uses 1.32 and has no reported MCP SDK advisory. Never install an unreviewed
second npm graph as a substitute for the frozen pnpm consumer qualification.


## Local fixture network boundary

`mcp-conformance-patches/local-network-boundary.patch` is a separate derivation
on top of the reviewed SDK 1.32 compatibility patch and proxy lock fix. It binds
the affected OAuth/IdP/MCP fixtures and everything-server to IPv4 loopback,
adds real bounded admission before auth parsing/cryptography, and replaces the
example's wildcard CORS policy with exact browser origins. It adds no dependency,
changes no original scenario/check/assertion, and disables no scanner.

The current derivative has its own fixed
`vendor-c37-sdk132-localnet-v2.json` source/output descriptor and independent
original-command rebuild check. The v1 descriptor and measured v1 baseline stay
byte-for-byte historical records. A new v2 result must never be relabeled as v1
or inherit v1 SDK/product qualification. See the network document for limits,
actual validation, reproduction commands and the explicit profile boundary.
