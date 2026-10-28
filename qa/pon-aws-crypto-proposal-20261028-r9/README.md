# AWS crypto dependency proposal, round 9

This is a concrete source and hosted-generation proposal for the remaining
`crypto-bigint 0.5.5` / `RUSTSEC-2026-0387` blocker. The current product manifest,
Cargo lock, Bazel lock and production source are still unchanged. No native
compatibility or cryptographic test has passed merely because this proposal's
Python controls pass. All original qualification workflows remain intact.

## Current failing evidence and exact dependency path

On remote head `682a88a7f847e31ffb6cd5e0a630dd71dde4bfee`, the original
[cargo-deny job 122636269894](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40633626405/job/122636269894)
reports one vulnerability error: `RUSTSEC-2026-0387`. The four earlier ctutils,
zstd and zstd-safe errors are absent in this actual run. The job remains failed.
Its complete raw log identity and readback are retained in
[`transport-readback.json`](../pon-dependency-transport-20261028-r9/transport-readback.json).

The actual hosted metadata from artifact 12791038108 identifies:

```text
codex-aws-auth
  -> aws-config 1.8.12 [credentials-login, default, sso, ...]
  -> p256 0.13.2
  -> elliptic-curve 0.13.8
  -> crypto-bigint 0.5.5
```

The only active direct parent of `p256 0.13.2` is `aws-config`; the only active
direct parent of `crypto-bigint 0.5.5` is `elliptic-curve`. `aws-sigv4 1.3.7`
currently has `default`, `http0-compat`, `http1` and `sign-http` enabled. Its
SigV4a feature was already inactive; this proposal does not remove it. Its
dormant old P-256/bigint requirements are addressed too, using a formal release.

## Official versions and why only one package needs a local patch

Registry evidence is frozen at
[`d81bdb3483af17165174bb94e0a2aca7353f24cc`](https://github.com/rust-lang/crates.io-index/commit/d81bdb3483af17165174bb94e0a2aca7353f24cc).
`upstream/index-records.json` preserves the complete selected official entries,
including their requirements, checksums, release times, feature definitions,
MSRV and yank status.

| Component       | Reviewed source                                                                 | Proposed use                                                                    |
| --------------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `aws-config`    | Official `1.8.12` source; newest indexed `1.13.0` still requires `p256 ^0.13.2` | Minimal path patch of the currently used `1.8.12`, preserving provider behavior |
| `aws-sigv4`     | Official `1.6.4`, published 2026-10-28 01:07:56 UTC                             | Registry dependency `=1.6.4`; no SigV4a fork                                    |
| `p256`          | Official `0.14.0`                                                               | Provider compatibility migration, with original arithmetic/PEM behavior         |
| `rand`          | Official `0.10.3`, already present elsewhere in the product lock                | Retain `std` and `std_rng`; add `sys_rng` for the fallible OS RNG               |
| `crypto-bigint` | Official unyanked `0.7.10`                                                      | Require the actual hosted graph to contain exactly this reviewed version        |

The exact smithy-rs main source at
[`c97559a2cc78ef17e534b2e88c08046a8f473110`](https://github.com/smithy-lang/smithy-rs/blob/c97559a2cc78ef17e534b2e88c08046a8f473110/aws/rust-runtime/aws-config/Cargo.toml)
also still declares P-256 0.13.2 and rand 0.8.5. Its complete manifest is retained
as `upstream/aws-config-main-c975.Cargo.toml.txt`. There is no safe published
crypto-bigint 0.5.x backport in this snapshot. The
[RustSec advisory](https://rustsec.org/advisories/RUSTSEC-2026-0387.html) names
0.7.6 as the first patched release; 0.7.6–0.7.8 are yanked in the frozen index,
and the current formal AWS SigV4a release explicitly requires `^0.7.10`.

Official aws-sigv4 1.6.4 already migrates to P-256 0.14 and bigint 0.7.10. Its
source archive and published standalone lock are retained. All 808 original
non-Rust fixture files below subdirectories of the 1.3.7 crate are present and
byte-identical in 1.6.4; their complete per-file identities are in
`upstream/sigv4-original-vector-equivalence.json`. This is source preservation,
not a claim that all 808 files are independent test cases or have run here.

## Concrete source change

`provider-source.patch` is the complete human-readable change against the
official aws-config source. It modifies only two existing files: the normalized
manifest and `src/login/dpop.rs`. It adds the independent migration tests, a
Bazel library declaration, and an explicit patch notice. `overrides/` contains
the exact proposed files, and `source-spec.json` binds every original and
proposed file by size and SHA-256.

The two diffs use standard zero-context unified format, so their blank context
lines do not violate the repository's whitespace checks. Complete original and
proposed file bytes remain available. The assembler writes those exact reviewed
files under their hashes; it does not perform a fuzzy patch application.

The P-256 0.14 API migration is supported by the retained official archives:

- `ToEncodedPoint::to_encoded_point` becomes `ToSec1Point::to_sec1_point`.
- `SecretKey::from_sec1_pem` and `SigningKey::from(&SecretKey)` remain supported.
- ECDSA 0.17 uses signature 3 and rand_core 0.10; rand 0.8's RNG cannot satisfy
  that different trait generation.
- `rand::rngs::SysRng` implements `TryCryptoRng`; the real
  `try_sign_with_rng` reports entropy failure instead of returning a token.
- Successful DPoP output keeps ES256, raw 64-byte signatures, unpadded base64url,
  the public JWK, and the original method, endpoint, timestamp and JTI claims.

The private signing function accepts a fallible RNG for testability, with the
production call passing `SysRng`. There is no alternate successful signing
implementation or crypto mock. Only the negative control injects an RNG that
always fails. UUID JTI generation remains upstream `Uuid::new_v4`; this patch
does not claim to make every SDK entropy failure fallible.

The entire original provider feature table remains equal as parsed TOML,
including `credentials-login`, `default`, `sso`, process credentials and all
other published feature names. The only production dependency changes inside
this provider are P-256 and rand. The new ring dev dependency supports independent
ES256 verification even in a login-only feature test. The original four DPoP
tests remain byte-identical before the explicitly recorded hosted formatting.

`workspace.patch` adds the patched provider as an explicit workspace member,
pins `aws-config = "=1.8.12"` and official `aws-sigv4 = "=1.6.4"`, and installs
one `[patch.crates-io]` entry. Explicit membership ensures normal workspace test
selection can exercise this provider's original tests. The directory is named
`aws-config-1.8.12-hepta-p256014`; the package retains the upstream name/version
for dependency compatibility and sets `publish = false`. License and original
attribution remain intact.

## Complete source and test preservation

The official aws-config crate contains 72 files but omits its test-data,
integration-test and fuzz directories. All 247 omitted files were recovered
from the exact release VCS commit
[`f031610a8cbb4ac2dac3229bfaeaa88182787ab4`](https://github.com/awslabs/aws-sdk-rust/tree/f031610a8cbb4ac2dac3229bfaeaa88182787ab4/sdk/aws-config).
The 235 test-data files, 10 integration sources and 2 fuzz files were verified
against the official Git trees; the 63 original `src/` files also match those
Git blob identities. All are ordinary mode-100644 files. Public upstream dummy
credentials and conformance keys are preserved as test data.

The untouched original `.crate` and the lossless exact-VCS extra-file archive
hold all 319 original files. The proposed installed vendor has 321 files: it
omits only the original standalone `Cargo.lock` and adds three files. The
original standalone lock stays inside the original source archive as provenance;
the explicit workspace member uses the one actual generated product lock.
No source or fixture is omitted. The EKS deployment integration sources are
retained but are not execution targets of this proposal or its unit-test plan.
No real AWS account or private credential is required.

## Hosted generation contract

The independent workflow is
`.github/workflows/hepta-pon-aws-crypto-proposal.yml`. It has read-only contents
permission and checkout with `persist-credentials: false`. Its PR trigger is
restricted to its own files; forks and foreign repositories are rejected before
checkout. PR events select the exact PR head SHA, while dispatch requires an
explicit full `source_sha` equal to the workflow run SHA. These origins cannot
be combined. Actual checkout HEAD must equal the selected source.

The one-shot PR trigger exists only to generate this proposal before default
branch dispatch registration. After a reviewable artifact is retained, its
automatic PR entry must be retired in the coherent import candidate. PR paths
are cumulative three-dot differences; a new QA directory alone will not prevent
another run. Original qualification jobs and their skip conditions are untouched.

Preparation records the exact source/tree/run/merge identities and original
manifest/locks before any mutation. It verifies every source archive and file,
retains the complete prepared vendor, then installs only the declared source
patch and workspace mutation. The fixed hosted commands are:

1. Capture Cargo 1.96.0, Bazel and just versions; run the original Python manifest
   preflight on the actual materialized workspace.
2. Run real `cargo +1.96.0 update --package aws-sigv4 --precise 1.6.4` and
   `cargo +1.96.0 update --package crypto-bigint --precise 0.7.10`.
3. Run hosted `cargo +1.96.0 fmt --package aws-config -- --config imports_granularity=Item`.
   The repository's format gate applies to this newly explicit member, so its
   mechanical formatting must be generated, preserved and reviewed too.
4. Capture actual locked all-features metadata and a second locked metadata run
   from `codex-rs/aws-auth` with `--features aws-sigv4/sigv4a`. The latter must
   really activate SigV4a or finalization fails.
5. Run the original `just bazel-lock-update` and `just bazel-lock-check` recipes.

Every command's raw stdout/stderr, exit code, start/end time and elapsed time is
retained. Failure stops later stages with their `not_started` status intact.
Interrupted stages stay unknown; a timeout is not rewritten into a pass. The
workflow has the original 35-minute execution-step and 75-minute job bounds.
Its finalizer and artifact upload run after failures when GitHub permits them;
a hard runner/job termination may leave no artifact and cannot qualify anything.

The finalizer verifies all intended target package versions/checksums, the
single actual path provider, the exact vendor file inventory, all non-Rust
fixture bytes, the original credential features and the activated SigV4a graph.
It saves every final source file and both real locks. Full graph equivalence,
new AWS dependency/API changes and formatter-only semantics still require
independent artifact review; `ready_for_review` is not that review or native
qualification. The final dirty-tree guard deliberately fails because generated
source/locks are uncommitted. Nothing pushes or commits from the runner.

## Native acceptance after coherent import

The generated source and both locks must first be reviewed and committed
together. A fresh run bound to that exact committed source must then retain
the original CI denominators, all failures and timeouts, plus these focused
native checks using the repository's `just test` entry point:

```sh
just test -p aws-config --locked --features credentials-login
just test -p aws-config --locked --no-default-features --features credentials-login,rt-tokio
just test -p codex-aws-auth --locked
just test -p codex-aws-auth --locked --features aws-sigv4/sigv4a
```

The first provider run covers the original credential/provider fixtures and
the new actual DPoP signing/verifying controls; the second checks the login
path with SSO disabled only for that additional test configuration. Production
SSO remains enabled. Test discovery, selected/executed/ignored/failed counts and
raw outputs must be retained. Existing profiles, cache refresh/expiry behavior,
session-token handling and first-party signing tests stay in the denominator.

The unchanged official aws-sigv4 1.6.4 archive also supports an additional hosted
upstream vector run with its published Cargo.lock:

```sh
just test --manifest-path "$RUNNER_TEMP/upstream/aws-sigv4-1.6.4/Cargo.toml" \
  --locked --all-features
```

That is explicitly a separate upstream dependency graph. It does not replace
the first-party tests or qualify the product graph. Its full discovery and
results must be retained alongside the unchanged 808 fixture files.

The original product Cargo/Bazel/Linux/macOS/Windows qualification and fresh
cargo-deny still apply. The new Bazel library fixes the six production provider
features and version explicitly and includes compile-time Markdown data; it
does not silently rely on the generic macro's empty feature default. The original
first-party AWS auth Bazel tests exercise that library. The original upstream
provider suite executes through Cargo, where its relative fixture paths retain
their original package working directory.

## Remaining risks and honest status

Official aws-sigv4 1.6.4 raises several AWS/Smithy minimums, including credential
types, HTTP/runtime API/types, HMAC and SHA-2. The actual resolver must expose the
full new graph and all consumers; the apparent size of the manifest diff does
not prove API or ABI compatibility. Its declared Rust 1.94.1 minimum is below
the repository's pinned 1.96.0, but that alone proves no build success.

Upstream SigV4a still documents a secret-derived rejection comparison and an
unreachable stack copy that is not wiped through its current API. This proposal
does not claim universal constant-time behavior, perfect zeroization, or a
practical exploit from those observations. It targets the concrete published
RustSec finding while preserving explicit residual assumptions. The temporary
provider patch should be retired when an official aws-config release supplies
the same compatible fixed dependency path.

Local evidence consists only of static source/data checks, Python failure
controls, formatting of Python/JSON/YAML/Markdown, and source-policy checks.
No local Hepta Cargo, Rust, Bazel, build, formatter or native test has executed.
The bigint blocker remains open until reviewed real generated locks and fresh
native/RustSec qualification close it.
