# Minimal lock closure, 2026-10-31

This is an operational dependency candidate for the existing source at
`8aee222b606de814af6b3661c1b03617ba02aeae`. The generation and synthetic tests
establish the candidate's scope and reproducibility. They do not establish that
Cargo, Bazel, the native tests, or cargo-deny accept it. Those outcomes must come
from the new workflow at its actual committed source head.

## Exact scope

The input is the verified [historical dependency artifact](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40683753943/artifacts/12815165944)
from source `d8d81eab0e9b6082406193f7ff5a69bb1f7b806a`. Its original receipt has
`qualification=false`, `dependency_graph_approved=false`, and
`graph_review_required=true`; its successful commands cover Linux x86_64 only.
Those qualifications remain unchanged.

The existing manifests already declare ZIP 9.1.2, Zstd 0.14.3, Norway 0.9.42 under
the YAML dependency name, and the exec-server test dependency. This candidate
preserves those declarations and their lock alignment. The deterministic repair
restores exactly 20 old parent dependency lists whose compatible target package
identities remain present. It retains every other byte of the historical Cargo
candidate. It does not run a general dependency update.

Compared with the currently committed old lock, the repaired graph has 19 added
package identities, 13 removed identities, and 16 retained parents with changed
resolved edges. Eight of these 16 changes are Zstd root replacements behind an
unchanged dependency string. The remaining changes align the existing ZIP/YAML
and exec-server manifests and the selected roots' transitive features. All
package identities, sources, and checksums of retained packages remain fixed.
The historical Bazel candidate is retained byte for byte; its only JSON changes
from the old Bazel lock are the corresponding 19 added and 13 removed crate
facts. Bazel must still validate those bytes against this repaired Cargo graph.

`constraints.json` contains the complete restored edge lists, remaining graph
delta, original artifact and lock hashes, source inputs, and 167 scientific
source hashes. Both lock paths lie outside the original A/C scientific source
inventories. No experiment, estimator, threshold, frozen Python source, or
scientific result is replaced. The original C2 checkout is not an execution
target for this workflow.

## Reproduction

Download the canonical artifact above and supply the original source input
bytes listed in `original_inputs`. The output directory must not exist:

```sh
python3 -B operational/parameter_field_lock_closure_20261031/lock_repair.py \
  --artifact /path/to/verified-artifact.zip \
  --baseline-root /path/to/original-source-inputs \
  --output-dir /path/to/new-candidate
```

The artifact identity, original 22 input identities, historical candidate
identities, all 20 exact edge substitutions, final package graph, and output
identities are checked before writing the two locks and generation receipt.
Generation records `cargo_locked_validation=NOT_RUN` and `qualification=false`.
One upstream crate identifier uses a standard JSON Unicode escape to avoid a
prose spelling false positive; its decoded identity and graph are unchanged.

```sh
python3 -B -m unittest discover \
  -s operational/parameter_field_lock_closure_20261031 -p 'test_*.py' -v
```

The focused fixtures exercise edge scope, ambiguous or absent targets, duplicate
identities, implicit root replacements, source-tree identity, resolver failure,
timeouts, and final source drift. They contain no scientific outcomes.

## Actual validation

`.github/workflows/parameter-field-lock-closure.yml` checks out the exact workflow
commit and executes these bounded jobs:

| Check | Host and scope |
| --- | --- |
| Cargo metadata | Actual `cargo metadata --locked --format-version=1` on Linux x86_64 and aarch64; no lock generation fallback |
| Native regressions | The existing 13 registered dependency regression groups on both Linux architectures, with existing no-retry filters and strict fresh JUnit checks |
| Bazel | Existing `just bazel-lock-check`, which uses `--lockfile_mode=error`, on Linux x86_64 |
| cargo-deny | The unchanged canonical reusable cargo-deny workflow, including its own failure diagnostics |
| Required aggregate | All preceding jobs must succeed; skipped, cancelled, and failed jobs remain failures |

The inherited Rust/Cargo 1.95.0 toolchain and pinned nextest runner are retained.
The runner checks all input and frozen source bytes before loading the reused
command/JUnit helpers and again at completion. Its Git-tree check allows only
the registered `Cargo.lock` replacement within the entire original Rust tree.
The committed lock and the physical lock must agree. Validation evidence must
be written outside the checkout.

Each phase records real command exit codes, bounded prefix/tail logs with
observed-byte hashes, input identities before and after, and fresh JUnit files
where applicable. An aggregate wall deadline bounds each phase; command timeout
or missing evidence fails it. `validation_passed` reports only that phase on
that host. `qualification`, `dependency_graph_approved`, and scientific claims
remain false or unchanged. Successful engineering checks do not by themselves
constitute a general platform or adoption certificate.

For a manual run from an exact committed candidate checkout:

```sh
python3 -B operational/parameter_field_lock_closure_20261031/run_validation.py \
  --phase metadata --expected-machine x86_64 \
  --output-dir /path/outside/checkout/new-evidence
```

Use `aarch64` only on that actual host. Native and Bazel phases require their
workflow-installed tools and Linux prerequisites. A receipt from another
source head, architecture, or candidate cannot close the current CI blocker.
