# AWS credentials-login P-256 compatibility candidate

The candidate preserves `aws-config` 1.8.12 and every existing provider while
moving its DPoP signer to P-256 0.14. The isolated resolved chain is
`p256 0.14.0 → elliptic-curve 0.14.3 → crypto-bigint 0.7.10`. The original 22 AWS
package versions remain unchanged; the only additional AWS package in the
standalone lock is an upstream dev dependency, `aws-smithy-protocol-test`.

This is a reviewable compatibility port with outstanding integration gates.
It is not a passing full CI result or a production approval.

## Copyable candidate

The complete vendor is in:

`/workspace/scratch/95988d8d3ab1/ndu-dependency-remediation/aws-login-port/candidate-root/codex-rs/third_party/aws-config-1.8.12`

`workspace-manifest.patch` changes only the workspace's `aws-config` version pin,
the crates.io patch path, and an explicit workspace exclusion for this vendor.
The vendor remains a production dependency with its original default features.
It is not made a workspace member to activate its development dependencies.
The production vendor contains no standalone test lock or nextest configuration.

The separate qualification copy used for the recorded execution remains in
`aws-login-port/proposed/codex-rs/third_party/aws-config-1.8.12`. It is the complete
upstream crate, with all 235 official test fixture files restored and verified
against their Git blob hashes. It is not a trimmed first-party workspace.

`evidence/CANDIDATE_HANDOFF.json` binds every production vendor byte. The initial
handoff before marking the outer Bazel test wrapper `manual` is retained in the
artifact as `CANDIDATE_HANDOFF_001_BEFORE_MANUAL_WRAPPER.json`. That follow-up only
changes build metadata; all Rust sources and test assertions remain the same.

## Narrow source change

Of 62 original Rust source files, 61 are byte-identical. The only changed original
Rust file is `src/login/dpop.rs`:

- `ToEncodedPoint` becomes the renamed `ToSec1Point` API, still requesting the
  same uncompressed point.
- The existing `rand::rngs::StdRng::from_entropy()` is wrapped by a private bridge
  implementing P-256's newer RNG traits. Every 32-bit draw, 64-bit draw, and byte
  fill forwards directly to that same RNG. Its error type is `Infallible`, as the
  original `StdRng` draw methods are infallible. No new entropy source, buffering,
  deterministic fallback, or cryptographic arithmetic is introduced.
- A test module is attached. Its implementation is in separate test files.

The `rand` manifest constraint and resolved `rand` 0.8.6 are unchanged. All
original feature definitions, provider-selection code, profile handling, cache
formatting, refresh logic, request construction, and error mappings are retained.
Original SEC1 key input and the 64-byte fixed-width ES256 signature format remain
the contract. The upstream license, original manifest, and Git identity are kept.

`production-source.patch` shows the manifest and signer changes against the
official crate. `tests-and-build.patch` shows new regression tests and build glue.
`evidence/VENDOR_PROVENANCE.json` records original and candidate hashes, source
archive checksums, and the official fixture tree at AWS SDK commit
`f031610a8cbb4ac2dac3229bfaeaa88182787ab4`.

## Actual execution

Every Rust test invocation used the repository's `just test` entrypoint.

| Run | Actual result | Interpretation |
| --- | --- | --- |
| `test-001` | No tests executed | The standalone crate had no `local` nextest profile. |
| `test-002` | No tests executed | Copying the whole repository profile produced package-override errors because those first-party packages are absent from a standalone upstream crate. |
| `test-003` | 19 selected login tests passed | Same retry and timeout settings, with no test exclusions or package overrides. The other 226 tests were not selected by this diagnostic run. |
| `test-004` | 241 passed, 3 failed, 1 unchanged upstream ignore | Sandbox network calls returned `EPERM`; an inherited `NO_COLOR=1` also broke an unchanged ANSI-log assertion. |
| `test-005` | 2 of the 3 diagnostic tests passed, 1 failed | Permitted network execution plus removal of `NO_COLOR` fixed the ANSI premise and one timeout branch; the remaining test received Envoy HTTP 503. |
| `test-006` | 242 passed, 2 failed, 1 unchanged upstream ignore | One complete confirmation under the permitted environment. No further repetition or relaxation followed. |

The 19 passing login tests include nine added tests covering mixed RNG draws,
SEC1 DER/PEM round trips, original public point coordinates, rejection of unsupported
key containers, actual randomized signatures, tamper rejection, and actual SDK
refresh requests. Both P-256 and the independent `ring` ES256 verifier validate
the real generated signatures. Refresh tests cover cache update, a newly created
provider reading the cache, a second refresh, unsuccessful refresh preserving old
bytes, and the original 30-second throttle. The original eight-case login fixture
is also executed by its unchanged upstream test.

The provider tests use AWS's injected in-memory `Fs` and an HTTP recording
transport. They exercise actual SDK provider, serializer, signer and refresh code.
They do not establish a real AWS service transaction or an OS process/disk restart.

The two remaining tests are:

- `imds::client::test::one_second_connect_timeout`
- `imds::credentials::test::read_timeout_during_credentials_refresh_should_error_without_last_retrieved_credentials`

Both expect timeout behavior from `http://240.0.0.0`. The network environment
instead returned transparent Envoy HTTP 503 without the token TTL header. The
exact failures remain in the logs. The first full sandbox run and its differing
failures also remain available. No original assertion or ignore was changed.
`ecs::tests::real_dns_lookup` is the one pre-existing upstream ignored test.

All 77 files captured before the first compiled test run remain unchanged;
all 235 restored fixture files were reopened and checked after the final run.
The actual test executable is preserved by content hash. An independent agent
reviewed the original source preservation, RNG bridge, real requests, tests,
failure logs and stated scope; see `evidence/PEER_AWS_PORT.json`.

## Bazel and production scope

The prepared Bazel library explicitly includes the existing default provider
features and `credentials-login`; local vendor crates do not automatically expand
Cargo's default features in these rules. Its test launcher restores the upstream
crate-root working directory and supplies every official fixture as runfiles.
Both the internal unit-test binary and the outer test wrapper are `manual`.
The outer wrapper is an explicit qualification target requiring the upstream dev
dependency graph and a network that supports the unchanged timeout assumptions.

The test wrapper sets `NO_COLOR` to the empty string. This is source-verified for
the exact locked `tracing-subscriber` 0.3.22: its default formatter enables ANSI
when the variable is absent **or empty**, and its own unit-test table covers both.
This confirms that premise, not a Bazel execution result. Bazel build/test and its
metadata generation have not run in this isolated candidate.

Remaining gates are the independent full upstream execution, actual first-party
consumer tests, full Cargo and Bazel lock inspection, the unchanged advisory
policy, and relevant platform CI. `REMOTE_VALIDATION.md` keeps the full upstream
dev graph separate from production selection. The candidate must not be promoted
by removing providers, ignoring advisories, omitting the two failing tests, or
making their assertion conditions weaker.

The reciprocal independent keyring port review is included as
`evidence/PEER_KEYRING_PORT.json`; it is evidence for that separate candidate and
does not change the AWS gate status.
