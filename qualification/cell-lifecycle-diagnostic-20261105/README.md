# Cell lifecycle refusal in diagnostic PR #4826

## Result

The missing mandatory public lifecycle refusal is integrated into the existing
diagnostic branch and has fresh native Linux regression evidence. Both public
`HeptaRuntime::apply_governed_topology` and `recover_governed_topology` first call
`require_control_lifecycle_admission_v1`, which returns the typed
`CellLifecycleAdmissionUnavailable` error before grant consumption, state-adapter
reads or migration-owner callbacks.

The complete durable Control Cell lifecycle owner is still unfinished. Public
topology execution and recovery remain **DENY_ALL**. This record does not grant
physical lifecycle, product, deployment or release qualification.

## Exact source

| Identity | Value |
| --- | --- |
| Original diagnostic head | `3419b6ac8adf5b47b140e553f5fff9e74c98d352` |
| Selected safety source, PR #4821 | `7ed5734a7545e2809f9c8e3014bd14f0eafdd80c` |
| Bounded runtime code commit | `43e79c9965816e43a6c339a3a291ab97153a92b8` |
| Tested and published diagnostic head | `3247636513f4cddaede6e9b45110925e9065d507` |
| Tested candidate tree | `99cc2b503f5e9825457066c0d7e2b935a795d234` |
| Observed prospective merge | `1bc1c6e0d2878e6445022a3ddf776983406851d2` |
| Existing PR / branch | [#4826](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4826) / `codex/organ-intermediate-diagnosis-20261105-r2` |

The observed prospective merge has ordered parents `732e934ba496d90fbe042b8d41d479ef901643e5`
and `3247636513f4cddaede6e9b45110925e9065d507`; its tree equals the tested source tree.
This is source-identity evidence, not proof that a CI runner executed that merge.

Only the public admission boundary, its typed error and its behavior tests were
ported from #4821. The unrelated wire-status formatting and Observer key/signature
type adaptations were excluded. The remaining #4821 contracts/operations changes
are outside this port. The private `organs.rs` blob remains
`0950be6088f669be5d00837646e624190efa0e5e`; underlying FinalUse checks and existing
positive/revocation/migration controls were retained.

The existing plasticity implementation map was updated, and its two status
projections were regenerated with the unchanged repository generator. They
distinguish public refusal from private process-local mechanics, retain the
acceptance/activation/release flags as false, and bind source navigation to code
commit `43e79c9`. Historical test results are not transferred to this candidate.

## Fresh native verification

Host: configured `desktop`, Linux x86_64. Rust `1.96.0` (`ac68faa20`), just
`1.51.0`, cargo-nextest `0.9.137`. The original repository test recipe and local
Nextest profile were used, with zero retries. Compilation used two jobs and an
isolated target directory. Complete commands, durations and log digests are in
[`native-results.json`](native-results.json).

| Check | Observed result | Evidence |
| --- | --- | --- |
| Behavioral negative control | 2 tests executed: 0 passed, 2 expected failures; 14 other tests excluded by the focused filter; exit 100 | [Raw red log](native-red.stderr), [exact two-line patch](negative-control.patch) |
| Restored candidate, complete runtime package | **16 tests executed: 16 passed, 0 skipped; exit 0** | [Raw green log](native-green.stderr) |
| Repository formatting against the original diagnostic base | Exit 0; three Rust files selected; tracked source and all three Rust SHA-256 values unchanged | [Format scope](format-scope.json), [final source result](native-final.json) |
| Native durable process | Exit 0; output complete and durable; no timeout or cancellation | [Authoritative status](native-authoritative-status.json), [complete process output](native-process.stdout) |
| Documentation projection and scoped source references | Passed; 39 mapped source objects checked; no execution claim raised | [Documentation validation](documentation-validation.json) |

The negative control retained the new helper, error variant and test fixtures and
removed **only the two public admission calls**. Both tests compiled and reached
a successful private `RuntimeTopologyApplyReceiptV1` with generation `1 -> 2`,
then failed the public-refusal assertion. Compilation failure was not used as
negative-control evidence. The exact candidate was restored before the full run.

The two new tests cover apply and stopped-host recovery, each with four subject
labels: Control, Cognitive, Learning and Evidence. For each valid fixture grant,
they require the typed refusal, an unchanged complete topology snapshot, zero
snapshot/migration/rollback callbacks, zero state-adapter reads and a still
claimable nonce after refusal. These are **two tests with eight scenarios**,
included within the 16 passing tests; the scenario count is not an extra pass count.

The full package command was:

```text
just test --locked -p codex-hepta-runtime --retries 0
```

Final formatting used:

```text
just fmt --base 3419b6ac8adf5b47b140e553f5fff9e74c98d352
```

No tests were rerun after final formatting. The original dependency/scoped-metadata
warnings remain in the raw logs. No test was newly ignored or bypassed.

## Preparation and evidence limits

The first full checkout timed out after 150 seconds before any Rust test. Its
failure output and terminal status are retained as `native-full-checkout-*`.
An isolated sparse checkout then materialized 9,878 tracked inputs and omitted
888 paths. The full Git tree identity, required workspace/build inputs, changed
Rust bytes and clean tracked state were checked; locked offline metadata passed.
The full materialization inventory is retained as `materialization.json.gz` and
bound by `native-inputs.json`. This is not a claim of custody over raw bytes for
all omitted paths or every external dependency. A shared Cargo package-cache lock
caused an initial wait; existing experiments were not interrupted.

The source scan found `RuntimeTopologyExecutionError` consumers only inside the
runtime crate in the materialized `codex-rs` tree. The production guard is
unconditional, but the new behavior tests are Unix-gated. Native Windows/macOS,
cross-host effects, independent signing custody, durable CNS CAS and physical
power-loss recovery are not qualified by this Linux package run.

The unchanged original [blocking CI run 41979312004](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41979312004)
was queued at the retained observation in `ci-observation.json`. No remote CI PASS
is claimed. PR #4826 remains Draft; full-candidate and main-merge qualification
remain separate from closure of this specific public-refusal omission.

These records are published on an evidence-only successor branch so the tested
diagnostic source remains frozen. `evidence-manifest.json` gives the length,
SHA-256 and Git blob identity of every retained record except itself.
