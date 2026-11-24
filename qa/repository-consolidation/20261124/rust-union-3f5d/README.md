# Rust branch integration audit, 24 November 2026

The observed remote had 8,102 heads. The ordinary Rust integration candidate advanced from `bedc5a34f666122eba4cef54218706958ea8a544` to source `2d40161a40e067a956887f2d32089193afdfc1bd`. The remote `main` head was `732e934ba496d90fbe042b8d41d479ef901643e5`.

| Scope | Heads |
| --- | ---: |
| Ordinary, excluding main | 7,493 |
| Reachable from prior candidate | 2,904 |
| Reachable from integrated source | 2,930 |
| Ordinary heads still outside the candidate | 4,563 |
| Ordinary heads reachable from main | 0 |
| Protected HIA names and aliases | 608 |

The [compressed branch inventory](branches.json.gz) records every branch and observed tip, HIA scope, before-and-after ancestry and Rust source differences for the initially pending tips. Its SHA-256 is `ad94f25a717e4876f5f375101c2dfa89a9470bad1ff23497f2cb8434bf769a34`. In that input inventory, 3,930 pending branch names changed Rust source relative to every best common ancestor with the prior candidate. The other 659 had zero net Rust source paths against all those ancestors. Cargo and Bazel updates, test inputs and CI support can still be required for Rust.

The HIA union contains 171 literal names, 437 other branch names and 1,627 known historical nodes. We recovered the prior union from the published archive and checked it against the complete current parent graph. All 608 protected tips were excluded from mutation. One historical pin identity reported in previous audits remains outstanding. The integrated history includes none of the known protected nodes or the previously held commit.

## Merges

- Merge Windows lease timing test history (4f91c182f0).
- Reconcile Windows AuthBus fixture flush history (627de12a73).
- Reconcile the incomplete evaluation branch (b7b4a2f654).
- Merge the HCSN research and recovery branch history (d57ae654cb).
- Merge the cookie 0.18.3 update with both candidate locks regenerated (422428d048).
- Reconcile PERC canonical test-root history and its original records (19c795116a).
- Reconcile VERIFY3 canonical platform and automation fixture histories (2d40161a40).

Every merge retains the incoming tip as a parent. The detailed record includes the before-and-after object identities for the PERC test fixtures. The earlier CA77 branch remains outside the candidate. One independently exercised exec-server fixture was imported at the file level from an ordinary source, without attaching its other ancestors.

## Checks

- The 43 tests across eight imported HCSN test modules passed on PyTorch 2.8.0 for CPU. Original archive verification checked 1,543 runtime members, 28 audit members and 35 CI follow-up members by hash. The original experiment outcomes and their source identities remain available in the incoming history.
- The native Cargo 1.96 and Bazel 9.3.0 generators produced the two candidate-specific lockfiles. The repository's read-only Bazel lock check passed. With the previous lock, cargo-deny 0.19.0 reported one advisory error. With the updated lock all four check categories passed. Other package records and Bazel facts were preserved.
- The two Rust lint and formatting changes were checked with the repository workspace formatting command and with a focused compile and strict Clippy run for the affected conversion. The imported lease test retains the real expiry and transaction assertions.
- Fifteen existing spelling-custody tests passed. Verification re-read 121 registered paths. All 51 diagnostics in the eight original archive parts were reproduced before correction. On the imported HCSN paths, two archive parts and one historical CI report accounted for 81 further diagnostics. The scoped post-change scan passed using exact path and SHA-256 registration. The workflow and dictionary remain at their original settings.
- The Linux exec-server suite on the source fixture passed 304 of 304 tests using the default OpenTelemetry sampler. With the host's one-percent sampler, four trace-export assertions failed. The specific timeout test passed in isolation. The original harness and production timeout are preserved.
- The PRED frontier `dd53b53a` remains open. Its default HTTP path performs synchronous database and file operations before provider execution. The 64-slot bound limits stored observations per owner but does not bound latency. The detailed review records the tests and unresolved service behavior.

Required hosting checks on the published candidate govern main admission. This checkpoint records no updates to main and no branch retirements.
