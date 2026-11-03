# AWS DPoP maintained P-256 qualification

Status: **HOLD_NO_GO** until the hosted platform jobs, actual generated Bazel
lock adoption, and original required CI have completed for the published head.
This candidate does not clear the other dependency, product, or performance
blockers.

## Change and provenance

The existing AWS login provider selects `p256 0.13.2` and `crypto-bigint 0.5.5`.
The frozen RustSec database reports RUSTSEC-2026-0387 for that bigint version.
The currently published `aws-config 1.13.0` still declares the old P-256 family,
so updating the SDK version alone does not remove that dependency.

This candidate retains the existing `aws-config 1.8.12` SDK API, provider and
credential features, and vendors the official crate with its Apache license.
After applying the same required repository formatter to both inputs, only
the two dependency manifests and `src/login/dpop.rs` differ. The latter uses
the maintained P-256 API, preserves uncompressed JWK coordinates and the raw
64-byte ES256 signature, and returns an error if OS seeding or signing fails.
The updated RNG is seeded by `SysRng`; it does not use a non-cryptographic RNG.

The production lock selects P-256 0.14.0, elliptic-curve 0.14.3 and crypto-bigint
0.7.10. It also selects official ChaCha 0.10.2: 0.10.0 was withdrawn and the
0.10.2 changelog fixes an SSE4.1 intrinsic used in the SSE2 RNG backend. The
other AWS SDK package versions and existing Windows dependency edges are
preserved. `upstream-provenance.json` records every official and final file;
`upstream-functional-diff.json` and `production-lock-delta.json` expose the exact
changes.

## Actual local evidence

On the original Rust 1.95.0 toolchain, original `just test` passed all five
`codex-aws-auth` tests and all eight source-bound DPoP tests, with zero skipped
cases and no retries. The isolated qualification crate compiles the actual
vendored `dpop.rs` and `token.rs`, including all four upstream DPoP unit tests.
Its four additional tests check legacy-verifier acceptance, exact JWK/claims,
message/signature/key mutation rejection, pre-epoch rejection, and malformed
SEC1 input behavior. The legacy P-256 verifier belongs only to this isolated
test workspace; the full production graph contains only P-256 0.14.0.

The final driver deletes prior JUnit files before execution, checks every
case and aggregate, hashes the actual source inputs before and after, and
retains full locked all-features Cargo metadata. Local receipt commit fields
identify the base checkout; their input hashes identify the staged candidate
actually executed. Hosted receipts will identify the exact candidate commit.

With the unchanged policy hash and frozen advisory database
`6c5fedf8ff03c485ed674d8f941e0180f3f72d70`, the baseline reports seven advisory
errors and three advisory warnings. The final candidate reports six errors
and two warnings: RUSTSEC-2026-0387 and the ChaCha withdrawal warning are gone.
The six other errors remain blocking. Bans, licenses and sources retain zero
errors. Original formatting and scoped Clippy also passed.

The reconstructable `local-evidence.zip` retains raw logs, JUnit, source hashes, actual metadata,
resolver counterexamples, and the independent source review. Its internal
SHA256 manifest and `local-evidence-receipt.json` bind the evidence. Earlier
failed resolver/configuration attempts remain in the archive as failures.
Its verified text parts stay below the existing 512,000-byte blob limit.
Rebuild and verify it without executing any contained code:

    python3 qualification/aws-dpop/restore_local_evidence.py --output /tmp/aws-local-evidence.zip

## Hosted acceptance

The added workflow executes the same native driver on Linux, macOS and
Windows. A separate job runs original `just bazel-lock-update`, original lock
validation, the actual AWS SDK Bazel build, and the actual AWS consumer Bazel
tests. It retains the generated lock, source hashes and command results.
No Bazel lock has been manufactured or inferred from the Cargo result. The
generated lock must be verified and committed before this candidate can be
composed with the other dependency repairs.
