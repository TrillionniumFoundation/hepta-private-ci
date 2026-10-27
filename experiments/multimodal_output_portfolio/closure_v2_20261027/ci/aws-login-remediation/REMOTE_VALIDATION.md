# Remaining independent validation

This plan is not an execution receipt. Keep the production candidate and upstream
qualification graph separate. Do not make the vendor a main-workspace member to
obtain its development dependencies.

## Production dependency and actual consumer

Apply the vendor copy and `workspace-manifest.patch` in a review checkout. The
patch records its original manifest digest in `CANDIDATE_HANDOFF.json`; if other
remediation work edits that manifest, merge these three intended changes rather
than replacing the whole file. Preserve every existing `codex-aws-auth` feature,
including `credentials-login`.

Generate the full workspace lock using the coherent candidate. Inspect the actual
dependency graph and ensure the selected signer chain is P-256 0.14.0 or newer,
elliptic-curve 0.14.3 or newer, and non-yanked crypto-bigint at least 0.7.8. The
isolated tested version is 0.7.10; do not select the yanked 0.7.6. Do not silently
update all AWS packages: the recorded compatibility result retains the existing
22 AWS package versions. If the coherent lock changes them, report that difference
and validate that changed graph rather than reusing this isolated result.

From the full repository, run the actual consumer with the standard entrypoint:

```sh
just test -p codex-aws-auth
```

Run any additional consumer and cross-platform tests required by the repository's
normal gates, the unchanged dependency advisory policy, and `just bazel-lock-update`.
The production crate remains a nonmember; no upstream development feature is added
to its normal dependency declaration for these checks.

## Full upstream qualification

Copy the complete candidate vendor to a new isolated directory outside the
first-party workspace. Add `evidence/STANDALONE_TEST_Cargo.lock` as `Cargo.lock` and
`evidence/STANDALONE_TEST_nextest.toml` as `.config/nextest.toml` in that copy. This
is a qualification-only workspace containing the complete upstream crate; do not
remove providers, fixture files, tests or development dependencies. Record every
source and executable hash before execution.

Use the same full suite, on a runner whose network does not turn the unchanged
240.0.0.0 timeout endpoint into an HTTP response:

```sh
env -u NO_COLOR just test --manifest-path "$AWS_QUALIFICATION_DIR/Cargo.toml" \
    --locked -p aws-config --features credentials-login
```

The expected inventory is 245 tests total: 244 executed and one original upstream
ignored DNS test. A diagnostic filtered login run is not a substitute for this
full result. Preserve failed retries and the final exit code. If the two timeout
tests still fail, report the actual error and keep the gate pending; do not modify
their assertions or add skips. The archive contains all earlier failures.

The tested standalone lock is deliberately distinct from the production lock.
Qualification may additionally run against a source-preserving copy with the
coherent production versions, but must record that lock and feature difference.

## Explicit Bazel qualification

First regenerate production metadata without promoting the vendor to a workspace
member. Ensure its library is reachable from the actual `codex-aws-auth` target and
that the selected local features include `credentials-login`, the default HTTPS
client, Tokio, credentials-process, and SSO. Review the newly resolved crypto graph
and lock drift before calling any gate closed.

The upstream unit-test target needs upstream development dependencies. If the
metadata generator only emits those for workspace members, create a **separate
qualification-only checkout/overlay** containing that membership change, regenerate
its metadata there, and retain its manifest/lock/feature diff. That overlay must
not replace production metadata. Run the complete explicit target:

```sh
bazel test //codex-rs/third_party/aws-config-1.8.12:aws-config-unit-tests \
    --test_output=all --cache_test_results=no
```

The wrapper and internal test binary are both `manual`, so an ordinary production
`//...` does not accidentally construct an upstream dev graph. Marking this newly
introduced qualification target manual does not remove any existing first-party
test. Preserve the full upstream test inventory when explicitly executing it.

The crate-root marker and all 235 official fixtures are included in its runfiles.
The wrapper's empty `NO_COLOR` is equivalent to an absent value for the exact
locked tracing-subscriber version, as shown in `BAZEL_SOURCE_PREMISES.json`.
Bazel execution and cross-platform launchers remain unverified until the explicit
runner result exists.
