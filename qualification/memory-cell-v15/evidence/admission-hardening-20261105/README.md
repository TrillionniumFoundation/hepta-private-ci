# Admission hardening: retained verification evidence

Remote status is preserved in `ci-queue-status.json`: run 42051127746 for exact
source `e455cfb761c8e41d8add94a7790e9d0e51fdff2d` remained queued at the
2026-11-05 15:19 UTC observation, with no executed job or downloadable artifact.
The workflow was left queued. It is not counted as a passing test or new native run.

These are protocol and accounting controls, not new language-model samples.
The source immediately before evidence/documentation commits is
`e030911758aba44a7718390ff2ca7510cbe65a24`. All 16 top-level Python Git blob
identities were checked against that exact GitHub tree; the local workspace was a
partial source snapshot, not a checkout whose `HEAD` could establish this identity.

| Record | Actual scope |
|---|---|
| `normal-checks.json`, `normal-checks.log` | 93/93 cases, no skip, unchanged source, ordinary Python |
| `optimized-checks.json`, `optimized-checks.log` | Same 93/93 cases and exact source with `python -O`; not 93 new scientific samples |
| `history-tests.json`, `history-tests.log` | 9/9 current/historical source and receipt identity controls |
| `historical-device-review.json` | Original 16 signed objects and original finite fixture; no new remote-host operations |
| `runner-initial-review.log`, `runner-green-review.*` | Four independent runner counterexamples before/after their corrections |
| `cohort-independent-red.json`, `frozen-protocol-green.json` | Original protocol reassignment defect and five independent repaired-path checks |
| `history-independent-review.json` | Coordinated archive/metadata rebinding still refuses against fixed verifier identity |
| `source-manifest.json`, `published-source-verification.json` | Local SHA-256/Git blob identities, plus exact remote-tree comparison |
| `format-local.*` | No trailing whitespace in the checked sources/docs; `just fmt` unavailable, exit 127 |
| `QUALIFICATION.json` | Machine-readable scope and explicit non-claims |

The paired eight-defect admission experiment and preserved positive control are
in [`../cost-admission-20261105/`](../cost-admission-20261105/README.md). Those two
results run the same probe and artificial resource vector against original #4864
and repaired code. `admission-red.json` is an earlier discovery record; the full
paired experiment is the authoritative before/after reproduction.

The independent `*-reproducer.py`/`*-review.py`/`verify-frozen-protocol.py` copies
preserve the original review scripts, including their historical sandbox paths.
They are audit records, not portable command-line interfaces. Portable behavior
regressions are in the top-level `*tests.py`, device `history_tests.py`, and the
cost experiment's source-path-parameterized `probe.py`.

Normal/optimized wall times describe separate validation runs on a shared host.
They do not establish a speedup, serving latency, complete device cost or energy
measurement. The subsequent CI receipt must have its own exact executed commit,
artifact identity and source comparison. The original failing CI and earlier
53/57/67-case records retain their own source boundaries.

Production activation remains false. Whole-authority rollback protection,
persistent experiment/look reservation, native service integration, real-model
complete-state migration and positive full-cost long-term benefit are not closed
by these controls.
