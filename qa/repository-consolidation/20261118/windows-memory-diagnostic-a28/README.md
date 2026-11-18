# Windows Memory lifecycle diagnostic checkpoint

This checkpoint adds one independent, path-filtered Windows PR workflow to obtain
an isolated baseline for the original Memory recovery case. Its sole parent is
`9a96facdfb878162bb0427b5313fd53a6996a5d4`. It changes no production Rust file,
existing workflow, required aggregate, test assertion, retry policy, or deadline.
The native Windows result is **not yet available** at publication.

## Original failure and diagnostic scope

The original blocking CI run `44331198533` recorded eight terminal Windows test
failures: seven Agentd control cases rejected an unavailable peer identity, and
one Memory case failed `guard.active.is_none()`. The original logs and their
source binding remain intact in `windows-required-8cases-originals.tar.gz`.
The separate Agentd repair is not part of this diagnostic.

The new workflow runs the exact original case
`local_lifecycle::tests::indeterminate_crash_window_replays_as_terminal_and_releases`
through the existing Bazel wrapper and MSVC target. It retains the original
250ms production budget, every assertion, one test attempt, and the unchanged
source file. It records the exact PR head/tree, raw source hashes, tool/platform
versions, argv, exit status, stdout/stderr, original test log, and original XML.
Its collector rejects missing, skipped, duplicated, retried, cached, or failing
case evidence. A passing isolated case does not establish that the original
concurrent full-target failure is repaired.

The independent static review found that the retained active handle can follow
either a returned finalization error or a timeout. The vendored SQL transaction
worker can also commit before its acknowledgement receiver is cancelled, so the
final assertion alone does not prove that a durable release failed to commit.
No unobserved timing cause is claimed. If the baseline fails, phase/result and
read-only durable-state observations are still needed before a narrow repair.

## Complete evidence

- `windows-memory-baseline-review.tar.gz` contains the exact workflow, full source
  and configuration chain, capability discovery, static control records, peer
  review, and original native formatter request and receipt.
- `windows-required-8cases-originals.tar.gz` retains both complete original native
  job logs, all eight failed case excerpts, original artifact inventories, and
  exact merge-commit/source binding. Those artifacts contain no original JUnit
  XML; absence of XML is not treated as success.
- `memory-lifecycle-static-review.tar.gz` contains the full source review and all
  27 immutable source files used for its conclusions.
- `branch-boundary-7595-originals.tar.gz` retains the full incremental boundary
  proof from the 16:19:41 UTC snapshot: 7,595 refs, 7,224 ordinary branches,
  370 protected HIA branches, and main. All 40,872 ancestors of the published
  parent were enumerated with no missing parent record and no protected tip,
  HIA root, or anchor intersection. Other writers may advance protected refs;
  this checkpoint writes only the existing integration ref.

`verification.json` records all archive sizes, SHA-256 digests, member manifests,
and root verification results. Every archive member was checked byte-for-byte
against its manifest, including the nested complete job-log archive. All members
are unique safe regular paths. Each newly added Git blob is below 512,000 bytes.

## Qualification boundary

The workflow's 17 receipt controls and four pipeline controls passed before
maintenance. They are synthetic controls, not a Windows Rust test. Prettier and
Codespell passed, followed by the real scoped `just fmt --base 9a96fac...` on ROG,
job `1a1ef8a4507-ffbe-535`, exit zero. The formatter selected no source group for
the YAML-only change and left the exact validated workflow unchanged. No test
was rerun after maintenance. Required CI and Architecture checks remain required
before main can advance; no branch deletion is authorized by this diagnostic's
result alone.

## Subsequent registration correction

GitHub rejected the first published diagnostic at `e2c3adbf1098` before assigning
a runner: run `44353316661` had zero jobs and zero native test executions. The
job-level environment referenced `runner.temp`, which is available only in the
appropriate step contexts. The original YAML/parser controls did not detect this
GitHub expression-context rule.

The current workflow initializes the same absolute evidence directory in the
first step and exports it through `GITHUB_ENV`. The always-running collector and
upload action address that directory independently. The original case, source,
250ms budget, assertions, invocation count and collector remain unchanged.
`registration-fix/` retains the complete hosted failure page, original API
records, exact correction, independent review and new validation/maintenance
receipts. No native Windows test result is claimed by that correction.
