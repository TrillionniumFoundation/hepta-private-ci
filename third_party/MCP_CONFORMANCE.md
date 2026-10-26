# MCP conformance source and dependency maintenance

`mcp-conformance/` contains the complete official source at
[`c37eec888e1c6ff140af79987a40008548b7cc5f`](https://github.com/modelcontextprotocol/conformance/commit/c37eec888e1c6ff140af79987a40008548b7cc5f),
including its MIT license. Its upstream tree is
`22eb98b99b522401dd1911dc2c2a55bee3547b50`.
The source archive SHA-256 is
`6ab798454dc41840631b77024f34de7d05d6ad0eda67ac04050d664e447171a2`.
The adjacent upstream manifest records the original Git blob, byte hash, size,
and executable mode of all 291 files. The original upstream lock is retained
separately for an exact comparison.

The sole local upstream-file change is the `node_modules/proxy-addr` record in
`package-lock.json`: npm resolved 2.0.7 to 2.0.8 and recorded its published
integrity and funding metadata. This fixes
[GHSA-jqcg-44mw-7w3h](https://github.com/advisories/GHSA-jqcg-44mw-7w3h)
in the tool's own preparation dependencies. The original package manifest,
prepare/build/test scripts, source, test cases, requirements, and oracle are
unchanged. This is a local dependency patch; upstream c37 still has the affected
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
lock change is the reviewed proxy record. Only normal build/install/test output
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
