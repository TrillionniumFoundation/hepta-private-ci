# Coherent AWS crypto import and native qualification, round 11

This candidate imports the actual hosted AWS provider source, Cargo lock and
Bazel lock generated on Hepta `ec3171c55848c3ebef5558119b9238b3120c6e1f`.
It fixes the observed Queue diagnostic lint errors and archived-template
package-loading failure, and adds five explicit native compatibility jobs.
The import and local evidence are static. Native compatibility, fresh RustSec
qualification and whole-product qualification remain **NOT RUN** here.

The earlier unpublished local commit `05588010b20a27698a3ca14b9033dfb1e6b76393`
was unavailable after the workspace reset. This is a new candidate restored
from actual published evidence, not a claim to have recovered that commit.

## Exact original observations

The [original generation run 40640050932](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40640050932)
used head `ec3171c55848c3ebef5558119b9238b3120c6e1f`, tree
`fee6095d8ce44cca33ef0b3dc7bfdba29a65de0f`, and actual PR merge
`e3e663727ff824b5935792cc19ea3d69d615a3f4`. All eleven declared source-generation
stages succeeded, including both actual Cargo metadata runs and the original
Bazel lock update/check recipes. The final dirty-worktree guard deliberately
failed. Generated source was never accepted as committed-source qualification.

Artifact `12794934188` has 2,558,468 bytes and SHA-256
`15da6c22f053c2352c407b61aaac5932b8cc66e8b15bcfbcebd5891daa44e50a`.
Its ZIP contains 527 members, while its internal manifest lists 672 payloads.
The 146 missing copies correspond to 73 unchanged upstream files under hidden
paths. They were recovered from the already verified official source capsule,
and every recovered copy matches the original hosted manifest's size and hash.
The original ZIP remains incomplete; this fact is recorded in
`artifact-complete-review.json`. Public upstream dummy credentials are test
fixtures, not newly acquired credentials.

`generation-logs.tar.xz` retains every original stage's complete stdout/stderr,
the original record and the full file manifest. In particular, both complete
8.3-MB metadata JSON outputs are present, not only a selected-package summary.
`generation-logs.json` binds every member and the lossless transport. Its
474,240-byte archive fits the unchanged 512,000-byte blob policy.

The [original full CI 40640050988](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40640050988)
has a final denominator of **37 jobs: 10 successful, 17 failed, 6 cancelled,
and 4 skipped**. `original-ci-final-state.zip` retains the recovered final
state, including the late aggregate job. Eight Bazel platform/shard jobs
failed while loading the archived `overrides/BUILD.bazel`; their test case
inventory was not discovered. Windows Clippy was ultimately cancelled but had
already emitted eleven real `expect()` errors in the Queue diagnostic helper.
Cancellation does not erase those compiler errors. The cancellation cause is
not established by the recovered logs.

The original paired run has four failed Linux jobs and two successful Windows
ledger jobs; the Cell run has two successful jobs. Both still pin old Chain
`131f673d9563e72aca7139f3239856957d118d49` and merge
`66634191298767b40691d6b2a298418ec19e3673`. They do not qualify a later Chain
candidate. No observed Cell success changes the existing no-update decision.

## What was imported and reviewed

`import-review.json` binds all **324 installed files**: 321 provider files and
the three root dependency inputs. The provider is the reviewed minimal patch
of official aws-config 1.8.12; the root selects official aws-sigv4 1.6.4 and
the actual resolved graph contains crypto-bigint 0.7.10. Login, SSO, process
credentials and the existing production provider features remain enabled.

The actual generated Cargo lock and all-features metadata agree on all
**1,546 packages and 7,662 dependency edges**. The explicitly activated
SigV4a metadata has 7,666 edges: five signer crypto edges become active and one
aws-runtime regex edge is inactive. These are declared feature-conditioned
differences, not missing lock entries. All 31 new registry package checksums,
dependency requirements and feature definitions match the retained official
index records. The reader includes Cargo's documented implicit optional
dependency features; its first attempt omitted that normalization and failed.
That failed reader output is retained among the local observations.

`retained-package-resolution-delta.json` lists 43 already-versioned packages
whose resolved dependency selections changed. This includes fourteen Windows
dependencies selecting windows 0.61.2 and tempfile selecting getrandom 0.3.4
within their original declared ranges. These real resolver results are not
manually rewritten to reduce the diff. Native Windows, macOS and Linux tests
remain necessary.

Hosted Rust formatting changed 50 files. Every changed file passes the retained
token/import comparison against the complete prepared source. The comparison
is a narrow static lexer and import normalization, not a Rust parser, compiler
or proof of program equivalence. All other provider fixtures remain intact.

Two further formatting changes are explicit derived bytes: the installed Bazel
file was formatted according to the original buildifier diagnostic, with equal
parsed Python AST, and the retained EKS Jest configuration was formatted with
Prettier, with equal Acorn 8.15.0 AST and comments after source locations and
raw-literal spellings are removed. The initial failing formatter checks and
both original and derived hashes are retained. These files are not mislabelled
as byte-identical hosted output.

Run the reproducible non-native readback from the repository root:

```sh
python3 -B qa/pon-aws-crypto-resolution-20261028-r11/readback.py
```

It verifies the full installed inventory, original stage logs, fifty Rust
format deltas, complete lock/metadata graphs and all 31 new official registry
records. It does not resolve dependencies, compile or execute project code.

## Concrete CI repairs

The archived proposal template was inadvertently discoverable as a live Bazel
package, where its compile-data glob had no matching Markdown files. Four raw
upstream/template files now live inside the hash-bound, seven-member
`source-inputs.zip`; the other three members retain the original root inputs.
The source reader retrieves the same exact bytes from that transport. The
archived BUILD file is no longer active. No `allow_empty`, test exclusion,
code-spelling ignore or blob-policy exception was added.

The Queue helper replaces its eleven Windows `expect()` calls and the matching
Unix permission branch with the existing adjacent `unwrap_or_else`/panic
convention. Failure still aborts the diagnostic setup, now with the concrete
error value. The original four callers, commands, assertions, hooks and request
deadlines remain unchanged. The original Rust-format diagnostic is addressed
in the same helper. Fresh strict Clippy and Rustfmt are still required; neither
was run locally.

Fence is pinned to the official immutable v0.12.5 distribution commit
`f9751ca5d767dc0199e88733c2b286bd4800a008`. Its sole source parent is
`424c1ac6cc2f844986f38defc6d43150796f35f5`; the distribution delta consists of
the bundled executable and manifest. The manifest and published release asset
agree on SHA-256
`3434ef8eb32d130daf272c4794772b497a5d4390d458fd0ef73bac6612b6aa1a`.
This readback did not download the binary or verify an attestation.

The reviewed resolver fix `a80d24f55cc9854d0e8446d8a02d1e93e774dfe1` is an
ancestor of that source. It handles a canonical, root-owned regular resolver
file while retaining no-follow opens, mount identity, rollback and readiness
checks. The old job reported only `unsupported_resolver_layout`, so its exact
failed layout remains unknown. This is a compatibility candidate until a fresh
hosted run succeeds. Audit mode, permissions, the comparison range, allowlist,
512,000-byte threshold and check order are unchanged. Official responses and
the ancestry check are retained in `fence-official-review.zip`.

The one-shot AWS proposal's automatic PR trigger is retired as its original
contract required after a coherent import. Its historical script and manual
entry remain; an already imported tree cannot masquerade as untouched proposal
input. All original product qualification jobs and their conditions remain.

## Five actual native acceptance scenarios

`.github/workflows/hepta-pon-aws-crypto-native.yml` supplies five independent
Ubuntu 24.04 jobs, with `fail-fast: false` and no cancellation by a successor.
This focused workflow tests the exact PR head. Existing full CI retains the
actual merge and all original platform/shard denominators.

| Scenario            | Actual dependency graph | Required native work                                                  |
| ------------------- | ----------------------- | --------------------------------------------------------------------- |
| provider-default    | Committed product       | Full aws-config suite with default providers and login                |
| provider-login-only | Committed product       | Full aws-config suite with only login and rt-tokio requested          |
| auth-default        | Committed product       | All first-party codex-aws-auth tests                                  |
| auth-sigv4a         | Committed product       | All first-party tests with real SigV4a enabled                        |
| upstream-sigv4a     | Published upstream lock | Official aws-sigv4 1.6.4 suite with all features and original vectors |

The last row is explicitly a separate upstream dependency graph. It cannot
replace product tests or establish product lock compatibility. All 808 original
non-Rust SigV4 fixture files are preserved in the source capsule; file count is
not a test count. The provider jobs must discover all four original DPoP tests
and all three migration controls, while retaining the rest of the selected
provider suite. Production uses the real fallible OS RNG and ECDSA signing;
only the entropy-failure negative test injects a failing RNG. No crypto success
mock is introduced.

Before installing native tools, each job binds the clean source/tree, complete
installed input inventory, original locks, scenario, run and attempt. It then
records pinned tool versions, actual metadata, complete nextest discovery and
the original repository `just test` execution. It uses zero retries, two test
threads and the unchanged original per-case nextest deadlines. The initial
experiment bounds are 35 minutes for native work and 50 minutes per job; these
are harness bounds, not product latency goals.

Every discovered binary/test name, ignored flag and selection result is
retained. Final reconciliation joins the selected identities with the actual
JUnit cases, preserving failures, timeouts, launch errors and unobserved cases.
An absent or partial report cannot yield a passing denominator. Duplicate,
unexpected or retry identities are rejected. Discovery failure leaves the
undiscovered inventory unknown. Interrupted stages keep a null exit code and
`interrupted_or_unknown` state; later stages remain `not_started`.

Both source and locks must remain unchanged. Every available raw stdout/stderr,
record, JUnit file and file inventory is uploaded after failures when the runner
permits it, including public hidden upstream fixtures. Hard runner termination
can still leave no artifact and grants no qualification. Passing a single row
does not close the bigint blocker: all five rows, fresh cargo-deny and the
original product platform qualification must succeed on their declared source.

## Remaining acceptance boundary

There was no local Hepta Rust, Cargo, Bazel, build, Rust formatter or native test
execution. Local Python/Node controls and static format/source reviews are
reported separately. The original Python SDK uv-install BrokenPipe failure
still requires fresh evidence; its cause is not inferred from a failed setup.
The pair Host service, independent future-task model improvement, full PQ
authorization integration, quantum PoN assumptions and independent multi-day
WAN acceptance remain outside this dependency repair's claims.
