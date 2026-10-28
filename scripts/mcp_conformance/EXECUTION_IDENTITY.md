# Vendor conformance execution identity

The `vendor-c37-sdk132-v1` execution profile describes the local c37 conformance
source, its two reviewed SDK 1.32 reference-client patches, and the exact installed
workspace graph. It is distinct from the historical 491 conformance policy.
This verifier supplies source identity; it does not turn regression-gate success
into complete protocol conformance or production authorization.

Run after the original frozen install and lifecycle builds:

```sh
corepack pnpm install --frozen-lockfile
CI=true COREPACK_ENABLE_NETWORK=0 node scripts/verify-mcp-conformance-profile.mjs \
  third_party/mcp-conformance/dist/index.js
node --test scripts/tests/verify-mcp-conformance-profile.test.mjs
```

The code pins the descriptor's bytes. The descriptor pins the original 291-file
manifest, the unchanged source verifier, both reviewed local patch artifacts, the
original vendor lock patch, the root dependency lock and configuration, and the
expected SDK/Zod peer resolutions. Real package resolution and current filesystem
links must agree, including after Node has cached a former resolution.

The selected CLI must resolve to the verified vendor's canonical `dist/index.js`.
Its complete output file set and bytes must match the code-owned profile. The
verifier then copies the validated original source into a fresh private directory
and runs its original `build` script against the same installed graph. The rebuilt
output must match both the selected CLI and the pinned output. Source pins, peers,
and selected output are checked again before verification returns.

The original SDK CI uses Node 22. Canonical builds invoke its adjacent Corepack with
the complete pnpm 10.34.5 integrity pin. Corepack network access is disabled during
verification. The temporary root carries the original packageManager declaration;
no install, dependency resolution, Git hook setup, or moving package-manager default
is allowed in this rebuild. CI's frozen install initializes this exact tool first.
The Node/Corepack installation remains part of the host toolchain trust boundary.

Identity tests reject changed revision/descriptor, vendor source, reviewed patch,
nested and workspace locks, edited verifier code before import, an unrelated CLI,
actual output byte drift, and a real SDK peer-link replacement. The two output/link
mutation tests touch only this test checkout's generated artifacts and restore them
before returning. They do not modify the frozen upstream source or other checkouts.

Returned metadata is an in-process validation result, not a signed proof of arbitrary
external reports. Report-profile validation and the separately measured c37 baseline
must preserve every required legacy passing check and expose all remaining failures.
Historical 491 reports and their original baseline retain their recorded identity.


The current local network derivative has the separate explicit profile
`vendor-c37-sdk132-localnet-v2`, descriptor and
`verify-mcp-conformance-local-network-profile.mjs` entry. The v1 descriptor above
remains historical and cannot authenticate a v2 CLI. See
[CONFORMANCE_PROFILES.md](CONFORMANCE_PROFILES.md) and
[the network contract](../../third_party/MCP_CONFORMANCE_NETWORK.md).
