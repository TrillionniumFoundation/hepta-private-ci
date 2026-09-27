# learning.eval recovery amendment — 2026-09-28 JST

## Delivery identity

Canonical integration branch: `fix/learning-eval-full-convergence-20260926`, PR #1011.
The amendment starts from `405a1bab27f3e726b48f43469aac08e82e9d96f7`.
PR #1051 remains unmerged comparison/history material; this report does not claim
all of its divergent commits were ported. No main merge or release was performed.

The complete source/document state before this report is commit
`3f8ff4e499017d8068fa63b0a499a968ee1df188`, tree
`e98ec9aef4a3bf61dfa29688147c0527797f0655`. This is a source observation, not a
qualified execution result. A final map-only rebind uses the repository's supported
`candidate_or_exact_observation_v1` policy and identifies its unchanged mapped
source through `observedAtHead`; the final candidate SHA is supplied by Actions.
The map must never invent a self-referential final commit or reuse another tree's
passing test result.

## Changes actually pushed in this amendment

- `48759d3`: full attempt-history validation, decided-publication reconciliation,
  and bounded cursor-based recovery that advances past unresolved attempts.
- `e4fc68a`: seven recovery unit-test sources covering valid decided recovery,
  absence preservation, spliced histories, stale latest pointers, missing
  predecessors, cursor fairness and page bounds.
- `0be0ee8`, `dafdd5c`, `4ddc65f`: wired decided-only publication resume into the
  actual module tree, then restricted the raw helper to crate scope. Public
  single-/multi-outcome recovery rebuilds the sealed bundle and rechecks current
  V2/V3 signed evidence before matching the preregistered publication request.
- `02c59bb`: added the actual child-process termination cut after durable decision
  and before pending publication. The fixture rejects changed authentication,
  allows only the first matching publication, and rejects a second resume.
- `4c3084e`: compiler-positive public recovery fixtures and a specific E0624
  compiler-negative assertion for the unverified private helper.
- `a265b55`, `ab2e9f0`, `3f8ff4e`: replaced stale recovery/native/technical
  statements, corrected registry-domain ownership and retained detailed design,
  compatibility, statistical assumptions and planned work-package envelopes.
- `90fdc44`, `28d3f31`, `3aec764`, `cdefbed`, `12773d8`: canonical source-status
  projection helper/tests, outcome/recovery inventory and expanded implementation
  mapping. Final source-observation rebinding is a separate map-only commit.

Typed outcome contracts, payload hashing, recorded multi-outcome estimation,
pre-consumption intent, independent anchors, streaming journal replay and raw API
feature gating existed at the amendment baseline. They were inspected and their
stale documentation/mapping was corrected; they are not misattributed as newly
implemented by this amendment.

## Local validation actually executed

Command: `python3 -m unittest -v test_hepta_learning_eval_projection`

Runtime: Python `3.13.5`. Result: **6 tests passed**, exit code **0**.
This exercised the projection helper only: canonical ordering, preserving design
text, idempotent replacement, malformed markers, digest changes and rejection of
source-self-issued acceptance. It did not execute the whole-repository scanner,
Rust compilation, process-kill tests, coverage or selected-host qualification.

Input identities:

| Input | Git blob | SHA-256 |
|---|---|---|
| `scripts/hepta_learning_eval_projection.py` | `3138ea440e20333ee67df647ae888d8c268dd403` | `0ec81b20816747cb4273b6c70c8875f4d227e11cfeeec94ea368c4f6aed1167f` |
| `scripts/test_hepta_learning_eval_projection.py` | `c6e9ef124b815cfbaa231ec60a13547e44a27ee6` | `7bec1c24e3241cf5ff3e2a2b544db3e7ae345e56919a97d709419092164cdd17` |

Captured unittest output SHA-256:
`be5299ea2720557e804943fb36c517ab0cfa9cf802a0421b7a62f346f6693673`.
This is a local execution record, not a GitHub attestation or independent review.

## Remote execution observed, not inferred

At source commit `3f8ff4e499017d8068fa63b0a499a968ee1df188`, the observed PR runs were:

| Run | Workflow | Observed state |
|---|---|---|
| `36334688071` | Hepta learning.eval exact trees | queued |
| `36334688059` | Hepta learning.eval convergence | queued |
| `36334688002` | Hepta Lane E gap closure | queued |

Later commits supersede these candidate-specific runs. They must not be used as
final-candidate receipts. The exact workflow has separate head and merge jobs;
only their actual final-candidate results can establish qualification. Earlier
cancelled jobs and queued jobs are not test passes. The local editing environment
did not contain Rust/cargo/rustfmt, and no local Rust execution is asserted.

The workflow's 85% coverage threshold and strict lint remain unchanged. Qualification
is read-only; no workflow repairs source, rewrites status or pushes a passing
claim back into the candidate.

## Remaining obligations and truthful completion boundary

Repository-controlled work is still required for complete durable sealed-object
serialization/archive recovery, ambiguity-resolving publication submission state,
full signed outcome/public-resume E2E tests, a downstream outcome qualification
consumer, a persistent selected-host recovery controller and long-running
near-capacity storage qualification. The bounded recovery primitive is not a
running service, and a digest-only journal is not an immutable object archive.

The seven process-cut tests are sources awaiting execution. Their fixture anchors
and synthetic publication decisions are not independent-host evidence. Real
selected-host trust/provider/publication bindings, independent physical anchors,
future-calendar outcomes, independent outcome provenance, retention, privacy,
unlearning/non-resurrection, power and independent acceptance must come from
actual qualified observations and authorities.

`CURRENT_STATUS.json` therefore leaves production implementation, target-host
qualification, independent acceptance, activation and release false. The PR stays
draft until its final exact-head, ordered-parent merge and required qualification
checks pass. No completed three-stage or production-ready claim is made.
