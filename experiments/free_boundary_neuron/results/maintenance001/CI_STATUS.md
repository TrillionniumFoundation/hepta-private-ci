# CI diagnosis for the published results head

This review inspected GitHub Actions for `c32392367b7587d09806ca5cbc74678a168b4e16`
on 2026-10-28 at 09:13:32 UTC. It does not certify a later maintenance commit.
The exact-head snapshot contains **44 checks: 6 failed, 16 successful, 11 skipped,
and 11 cancelled**. CI is not green.

The [diagnostic receipt](ci_diagnostics.json) retains the check URLs, input-object
comparison, recognized failing-test names, and selected verbatim log excerpts.
It is an excerpt archive, not a complete copy of the job logs.

## Observed failures and baseline comparison

| Job | Direct observation | Baseline evidence |
| --- | --- | --- |
| [macOS Clippy](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40634872515/job/122639715088) | `clippy::unwrap-used` in `hepta-fleet/src/authority_port.rs:197:9` | The source file is identical. The corresponding baseline job was cancelled; the same diagnostic was not observed there. |
| [Windows test shard 3](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40634872515/job/122639715035) | Native fixture directory failures, evidence capacity, Windows file locking, matrixd socket state, V8 feature assertion, and other test failures | All 51 recognized `test NAME ... FAILED` names also occur as failed in the baseline shard. Selected error messages repeat; a matching name alone does not establish an identical cause. |
| [Windows test shard 1](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40634872515/job/122639714982) | Schema fixtures, readiness timeout, migration, canonical workspace, federation, supervisor, and guardian-permissions test failures | Nine recognized failed names repeat. The guardian-permissions failure was not found as failed in the baseline log. |
| [Cargo-deny](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40634872515/job/122639714542) | Failed check; earlier inspection identified the failed Cargo-deny step | Earlier head and baseline log requests returned `Transport closed`. This review did not repeat them. The exact diagnostic remains unavailable. |
| Windows aggregate and CI required | Aggregate checks failed | These do not supply an independent root-cause diagnosis. |

The head-only guardian outcome is
`request_permissions_routes_to_guardian_when_reviewer_is_enabled`. Its observed
assertion compares actual network permissions `None` with expected `Some`.
The absence of a matching failure in the inspected baseline log does not prove
that this research change caused it.

The baseline is `fb9281e4a7ccfc4034281ed6310adea7e50f4474`, associated with
[run 40472591263](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40472591263).
Both runs execute pull-request merge checkouts; their checkout identifiers are
preserved in the receipt. Direct Git-object comparison shows the complete
`codex-rs` tree, the Clippy-referenced source file, and `bazel.yml` are identical
between the two immutable branch commits.

## Interpretation and action scope

The retrieved logs establish specific failing outcomes and several recurring
baseline signatures. They do not establish the cause of every failure, make
cancelled checks successful, or make the PR ready to merge. The frozen study's
local validation and scientific evidence remain separate from repository CI.

This diagnostic review performed read-only retrieval and wrote these new
maintenance records. It did not rerun workflows, alter dependencies or
workflows, waive gates, weaken identity checks, or merge the PR.
