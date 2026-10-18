# Reproduce and continue

Use an independently writable clone with enough build disk. Read the repository AGENTS.md first; Rust tests must use the canonical just test entry. Do not write into another active owner's worktree.

## Exact source retrieval

~~~bash
git clone --no-checkout https://github.com/TrillionniumFoundation/hepta-private-ci.git hepta-recovery
cd hepta-recovery
git fetch origin fix/ci-clippy-expect-unwrap-20261017 research/real-reader-intake-p4-20261017
git worktree add ../hepta-2599-19c5cd41 19c5cd41c17dd42da7afac96203a4bc7901e23a6
git worktree add ../hepta-2714-f191cd08 f191cd081ba16fed8827a18093b5a5b39e9a36cd
~~~

Each command must be checked for success. Before any later mutation, GET the PR again and compare its current head/base/state. An advanced branch requires semantic reconciliation; never force it over another owner.

## Research contract suite

Run in the #2714 worktree:

~~~bash
python3 -B -m unittest discover -v -s qualification/neuron-shared-encoder/tests -p 'test_*.py'
~~~

The recorded final result is 109 tests / 109 pass / 0 error / 0 skip. These are synthetic contract tests. Exact touched paths, old/new Git blobs, Ruff commands, negative baseline regressions and stage-specific logs are in research-os-evidence.tar.gz and ci-evidence.tar.gz.

## Clippy and native fixtures

Run in the #2599 worktree with the repository-pinned Rust toolchain and dependencies. These native commands are NEXT ACTIONS, not tests completed by this audit:

~~~bash
just test --locked -p codex-hepta-fleet --lib -E 'test(authority_port)'
just test --locked -p codex-hepta-agentd --test kernel_evidence_product --test plasticity_process_e2e
~~~

Then execute the exact workflow's Clippy commands with its deny flags and all required Windows/macOS/Linux targets. Preserve platform-specific test fences, canonical SQLite adapters, signing/authority tests and coverage.

Recorded static checks:

~~~bash
just fmt --base f8c9419df6ddeb36ff8b522a50219981fb8d9345
git diff --check 1ebb9b8a9313e6504d2ebf9597412f3fe9c49d9e 19c5cd41c17dd42da7afac96203a4bc7901e23a6
python scripts/hepta-implementation-maps.py verify --profile qualification
python scripts/hepta-module-docs.py verify --profile qualification
python scripts/hepta-module-docs.py refresh-derived --check
~~~

The two qualification commands are expected to retain the recorded 26-module failure set on this head. Do not bypass a failed ancestor check through internal helper functions. The source-map archive includes the exact original commands and complete failure output.

## Required GitHub evidence

Use authenticated GitHub plugin GET requests for the PR, commit check-runs, combined statuses and actions/runs filtered by the exact head. Follow every page. For each run follow every latest-attempt job page and verify run ID, source SHA, attempt and any synthetic merge's parents/tree. Required contexts observed are CI required and Architecture required; full administrative protection visibility was not available.

The first two post-push snapshots contain 17 queued jobs and absent aggregators. Queued, pending, missing, cancelled, skipped, metadata-only and old-SHA success are not complete required-check success. No merge was performed.

## Memory experiment

Inspect PR #1452 at 2a0e8d016f5e00359561934909e801ae26f2bfd7 and its locked strong_rag_shards.py protocol before invoking a model. Admit an adequate worker and create a fresh output batch. Complete 40 calibration calls, then 72 nine-arm inference calls, retaining per-sample answers, citation/source provenance, model/prompt/dataset hashes, device/seed/temperature and measured tokens/latency/resources. Do not append the six failed-attempt responses to a different historical batch. Independent calibration and scientific acceptance remain necessary even if counts are met.

## Archive verification

FILES.json and ARCHIVES.json list file and archive SHA-256/Git blob identities. Each evidence archive includes a member manifest. Verify hashes before using its receipts; retain their original timestamps and observation scope. Source code remains recoverable from the exact pushed commits. Never upload model weights or invent missing physical measurements.
