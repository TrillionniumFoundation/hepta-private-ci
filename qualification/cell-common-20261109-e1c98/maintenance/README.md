# Final common-candidate maintenance

The original scoped `just fix`, the narrow CI lint correction, scoped `just fmt`,
and strict seven-package Clippy all completed successfully. This directory
retains their original records, command output, input/output patches, process
completion states, and the two motivating GitHub CI failure logs.

## Source identities and limits

- The completed native/model/Root runs belong to runtime commit
  `f070113bb61cda492d2668b3afbbcda13e11fa52`, tree
  `068b6a7749e94d7335c826d6c43c19198e02cc24`.
- The maintenance code commit is
  `dde0c36ef2b90af37f5cdafe7dca0c7572585b09`, tree
  `19e7619d7b4df0f1ba645151ffb5844a53ad97d3`.
- The exact remote-to-local maintenance patch is 77,255 bytes, SHA256
  `c563731344f58ae74a0c3a903315a7ab64bd5f560145b5808aebfbbc8204a65b`.
  It changes 22 files: 16 Rust files and six Python files, all within the
  existing M6-to-runtime change scope. No Cargo dependency, lockfile, third-party
  source, admission threshold, or test assertion was changed.
- `APPLICATION.json` binds the maintenance commit and all 22 file hashes.
  The local code bytes and committed code diff were checked against the exact
  remote bytes. The local parent differs from `f070` only by evidence commits
  in the `codex-rs`, `scripts`, and `.github` code projection checked here.
- There were **no test executions after fix/format**, following `AGENTS.md`.
  Strict Clippy compiles test targets but does not execute tests. Earlier JUnit
  or model passes are not reassigned to the maintenance commit. This record
  does not claim a final full-CI pass or scientific benefit.

Remote maintenance intentionally keeps HEAD at `f070` with a recorded dirty
worktree. Its `tree` field remains the committed HEAD tree; the explicit
`tree_is_committed_tree_not_dirty_worktree_digest` field and complete patch/file
hashes distinguish that from the final local maintenance tree.

## Concrete CI failures and corrections

The original run is
[42615233826](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42615233826).
Both failing lanes had passed V8 resolution and configuration prerequisites.
Their recorded before/after source identity is the clean `f070` runtime above.

| Job | Observed failure | Narrow correction |
| --- | --- | --- |
| [129153342070](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42615233826/job/129153342070), mechanisms | `clippy::type_complexity` at `outcome_credit_preflight_tests.rs:30` | Give the existing function-pointer/error tuple the `CreditCase` alias; retain all four cases and assertions. |
| [129153342282](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42615233826/job/129153342282), agentd composition | `clippy::duplicate_mod` for `learning_iteration_checkpoint_test_support.rs` | Declare one private `#[cfg(test)]` support module under checkpoint and reuse it from four descendant test modules; remove the former local lint allowance. |

The same run's configuration/actor-recovery job `129153342283` succeeded.
The two raw failing logs are retained in `ci-f070/`, with hashes and job steps.
These were real source lint failures, not V8 fetch failures or failed native
test assertions. They occurred before those lanes reached native test execution.

The shared fixture continues to construct independent `FileCas` instances.
Its visibility remains inside the private checkpoint test subtree. Root and
the checkpoint-owning reviewer inspected the exact six-file narrow patch.
Root also materialized the final patch outside the main worktree and confirmed
that all six changed Python files have the same AST as `f070`.

## Executed maintenance

| Operation | Durable job | Exit | Whole-command wall seconds | Source effect |
| --- | --- | --- | ---: | --- |
| Original `just fix --locked --offline` for seven packages | `1a1c04a8944-5e21-9b1` | 0 | 91.069280 | No automatic edits; retained both motivating warnings. |
| Apply the reviewed CI lint patch | `1a1c04d7ee2-5e21-9c2` | 0 | 0.039003 | Six test/module-declaration files. |
| Original `just fmt --base 885dae0f3285267e9e9c49d8b43b0d009779f9e8` | `1a1c04dfdf2-5e21-9c6` | 0 | 1.420352 | Scoped formatter brings total maintenance to 22 files. |
| Original `just clippy --locked --offline ... -- -D warnings` | `1a1c04e929d-5e21-9c8` | 0 | 119.647073 | Complete input/output patch and all 22 file hashes unchanged. |

The seven primary packages are `codex-hepta-agentd`, `codex-hepta-automation`,
`codex-hepta-intelligence`, `codex-hepta-learning-artifacts`,
`codex-hepta-learning-ledger`, `codex-hepta-neuron`, and
`codex-hepta-prompt-registry`. The strict command covers both owners that failed
CI; it is a scoped check rather than a claim that every other CI job has passed.

All four jobs ended with authoritative `succeeded`, exit 0, durable complete
output, no timeout, and no automatic retry. `RESULT.json` records command-level
wall time, child CPU/RSS, and actual cgroup observations. These maintenance
costs are separate from task/model costs. No energy or provider-price estimate
is substituted for an observation.

The final strict log retains two existing `mismatched_lifetime_syntaxes` warnings
from dependency `third_party/i18n-config-0.4.8`. Cargo's dependency lint behavior
is preserved; the third-party files were not edited. Both targeted first-party
lint diagnostics are absent from the successful final command.

The formatter uses Rust 1.96.0/rustfmt 1.9.0 and the repository's frozen
`scripts/uv.lock` Ruff 0.15.13. Existing uv and cached Ruff were reused with
`UV_OFFLINE=1`. The exact invocation, source-bound environment, and retained
controller/plans are under `commands/` and `tools/`.

## Reading and verifying the retained bytes

JSON records retain their original bytes. Logs, patches, and tool source/plans
are stored as deterministic gzip with `mtime=0`; decompression restores the
original bytes. Empty log/patch files are preserved as valid empty gzip inputs.
`MANIFEST.json` lists every payload's stored SHA256 and, for gzip files, its
uncompressed SHA256 and byte length. No new test run is needed to inspect this
evidence. `maintenance-f070.patch.gz` is the complete reviewed code delta;
`tools/narrow-ci-lint.patch.gz` isolates the six-file manual correction.
