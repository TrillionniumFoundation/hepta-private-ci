# platform.types qualification hardening — 2026-09-28

This note documents source changes, not a production-completion receipt. It supplements
`TECHNICAL.md` and `TECHNICAL_CURRENT_AMENDMENT_V2.md`; it does not replace protocol
semantics, owner authorization policies, independent review, or retained execution
receipts. Historical technical material is intentionally retained.

## Implemented execution path

The existing `.github/workflows/platform-types-deep-qualification.yml` owns this path:

1. A resolver checks out the explicitly selected candidate, runs the real-Git binding
   regression suite, and resolves source and base to immutable commit/tree pairs.
2. Both lanes check out that same resolved source commit. Each verifies the checkout
   and availability of the frozen base object before invoking qualification.
3. The source lane uses the frozen source as its exact expected candidate. The merge
   lane passes the frozen source/base pair to the existing
   `.github/actions/hepta-synthetic-merge` action and qualifies its returned commit.
4. API compatibility in both lanes uses the same frozen base. A later movement of
   `main` or of the requested candidate branch does not change either lane's input.
5. Schema qualification and the existing deep qualification receipt pipeline remain
   required. Diagnostic upload does not turn a failed outcome into success.

The helper is `scripts/platform_types_candidate_binding.py`; its regression suite is
`scripts/test_platform_types_candidate_binding.py`. The helper writes no tracked
source and does not push, repair a candidate, or issue a qualification receipt.
Its resolver evidence explicitly contains `qualification_passed: false`.

## Manual dispatch contract

Dispatch declares three required inputs:

| Input | Meaning |
| --- | --- |
| `candidate_ref` | Source branch, tag or full commit to resolve once. An unknown or invalid ref fails; there is no fallback after a resolution failure. |
| `base_ref` | Baseline to resolve once. The default is `origin/main`. |
| `pr_number` | Positive PR number passed to the existing synthetic-merge provenance protocol. |

Use the workflow revision containing these changes. The workflow revision and
candidate revision can differ and are recorded separately. Selecting an older
candidate without the binding helper fails rather than silently using later helper
bytes. A PR number is provenance context, not evidence of an approval.

For pull requests, source and base come from the event's immutable head/base SHAs.
For main pushes, the source lane uses the push source and preceding base; such a
source-only run is not a substitute for the two-lane PR acceptance requirement.

## Fail-closed binding checks

The binding helper rejects empty/control-character/option-like refs, nonexistent
refs, non-commit objects, dirty tracked source, and a checkout different from the
requested source. The verification subcommand accepts full immutable object IDs,
not branch names or abbreviated SHAs. Submodule dirtiness is not hidden.

Untracked diagnostic files are allowed; this is a tracked-source integrity check,
not a claim that arbitrary untracked executable code is trusted. Checkout remains
clean and credentials are not persisted by the workflow. Candidate inputs are
passed through environment variables and quoted argument vectors, not inserted
into shell program text.

The two lanes consume resolver job outputs only after that job succeeds. The
resolver output is not accepted as native-test, schema-parity, performance,
independent-review, deployment or release evidence.

## Reproducible native toolchain and environment record

`RUSTUP_TOOLCHAIN=1.96.0` pins implicit Rust/Cargo commands in both lanes to the
existing declared MSRV. Each lane explicitly installs that toolchain with Clippy
and rustfmt before the schema gate. The existing explicitly pinned Miri, rustdoc
and fuzz toolchains remain distinct; this change does not relabel them as native
or MSRV tests.

Each lane retains `candidate-binding.json` and `environment.txt` under a separate
runner-temporary `platform-types-context/<lane>/` directory. Keeping this outside
schema and deep-output directories prevents those scripts' output initialization
from removing it. The record includes source/base SHA, workflow ref/SHA, run ID and
attempt, runner OS/architecture, runner image metadata when available, verbose
Rust/Cargo versions, Python/Node versions, and the host kernel identity.

This is environmental diagnostic evidence, not a cryptographic runner attestation
or a performance result. A runner label is not an immutable machine image. Resource
workload depth, repeated timing, allocation/RSS comparisons, and qualification
threshold acceptance require actual separately retained measurements.

## Regression validation

Run from the repository root:

```sh
python3 -m unittest discover -s scripts -p 'test_platform_types_candidate_binding.py' -v
```

The suite uses real temporary Git repositories and covers 12 cases, including a
non-default candidate, full SHA and annotated tag resolution, wrong checkout,
missing/invalid refs, tracked staged/unstaged changes, untracked diagnostics,
non-commit IDs, branch movement after freezing, and CLI output behavior on success
and failure. The suite was executed locally with all 12 tests passing. Local YAML
parsing and shell syntax checks were also performed for the workflow change.

These local checks do not execute hosted jobs or compile the Rust workspace. They
must not be copied into exact-head or synthetic-merge qualification fields.

## Protocol and owner boundaries remain unchanged

The current `numeric_registry_v2.rs` implements generation-bound registered
conversion receipts and `RegistrySnapshotIdentityV1`, with owner-pinned
`verify_for_snapshot`. Its admission digest uses the versioned canonical digest
path. This change does not introduce a replacement identity algorithm, reinterpret
V1 digests, or claim a measured registry-cache speedup.

Receipt self-verification is not current-generation acceptance. Owners still have
to provide their independently pinned snapshot and actual host/calibration/root
seed context at existing product boundaries. Existing `DENY_ALL` posture is not
changed. No parallel product-owner implementation or deployment activation is
introduced by this qualification change.

## Acceptance state and remaining work

| State | Evidence required | Status of this change |
| --- | --- | --- |
| Binding behavior specified | This note and executable helper | Implemented |
| Binding source integrated | Existing deep workflow consumes resolver outputs | Implemented |
| Local binding regressions | Actual 12-case test execution | Passed locally |
| Native/source qualification | Retained successful receipt for the final exact source | Not asserted here |
| Synthetic-merge qualification | Retained successful receipt for the same frozen pair | Not asserted here |
| Resource/performance acceptance | Actual workload depth, repeated measurements and gate results | Not asserted here |
| Owner negative-path acceptance | Final-candidate execution through real owners | Not asserted here |
| Independent approval | Eligible formal approval on the final source head | Not asserted here |
| Production/operator/release acceptance | Separate deployment and governance evidence | Not granted |

Before final acceptance, inspect the first failing command and its exact candidate
rather than carrying forward an earlier prose diagnosis. A compile/schema failure
cannot be reclassified as a measured performance failure, and a later source change
cannot inherit an earlier run's success. Keep failed diagnostics, rerun the final
fixed source and its fixed merge candidate, and retain their receipts separately.
No completion field should be changed merely because these source commits exist.
